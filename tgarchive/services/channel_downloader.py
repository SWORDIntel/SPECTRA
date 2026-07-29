"""Whole-channel filesystem downloader."""

from __future__ import annotations

import asyncio
import json
import hashlib
import logging
import os
import re
import time
import uuid
import fcntl
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, Optional

from ..db.index_outbox import IndexOutbox
from ..sqlite_runtime import connect_sqlite

logger = logging.getLogger(__name__)


_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
DEFAULT_MAX_CONCURRENCY = 32
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_DELAY_SECONDS = 3.0
DEFAULT_PROGRESS_INTERVAL_SECONDS = 15.0
DEFAULT_STALL_TIMEOUT_SECONDS = 75.0
STALL_POLL_INTERVAL_SECONDS = 0.25
PARTIAL_SUFFIX = ".part"


@dataclass
class ChannelDownloadOptions:
    entity: str
    output_dir: Path
    include_media: bool = True
    limit: Optional[int] = None
    min_id: Optional[int] = None
    max_id: Optional[int] = None
    resume: bool = True
    deduplicate: bool = True
    write_metadata: bool = True
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY_SECONDS
    fail_fast: bool = False
    retry_flood_waits: bool = True
    progress_interval: float = DEFAULT_PROGRESS_INTERVAL_SECONDS
    stall_timeout: float = DEFAULT_STALL_TIMEOUT_SECONDS
    index_database: Optional[Path] = None


@dataclass
class ChannelDownloadResult:
    entity_id: Optional[int]
    title: str
    output_dir: Path
    messages_written: int
    media_downloaded: int
    media_duplicates: int
    media_skipped: int
    last_message_id: Optional[int]


@dataclass
class MediaDownloadOutcome:
    path: Optional[Path]
    was_duplicate: bool = False
    was_skipped: bool = False
    failed: bool = False
    checksum: Optional[str] = None
    size: Optional[int] = None
    transferred_size: int = 0
    error: Optional[str] = None
    failure_type: Optional[str] = None


@dataclass
class ProcessedMessageResult:
    message: Any
    media: MediaDownloadOutcome


def safe_path_component(value: Any, *, fallback: str = "channel") -> str:
    """Return a stable filename component for Telegram titles/usernames."""
    text = str(value or "").strip().strip("@")
    text = _UNSAFE_PATH_CHARS.sub("_", text).strip("._-")
    return text[:120] or fallback


def _iso_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _message_media_summary(message: Any) -> Optional[Dict[str, Any]]:
    file_obj = getattr(message, "file", None)
    media_obj = getattr(message, "media", None)
    if not media_obj and not file_obj:
        return None

    return {
        "id": getattr(file_obj, "id", None),
        "name": getattr(file_obj, "name", None),
        "mime_type": getattr(file_obj, "mime_type", None),
        "size": getattr(file_obj, "size", None),
        "ext": getattr(file_obj, "ext", None),
        "media_type": type(media_obj).__name__ if media_obj is not None else None,
    }


def _telegram_peer_id(entity: Any) -> Optional[int]:
    """Return the operator-facing Telegram peer ID without importing Telethon."""
    entity_id = getattr(entity, "id", None)
    if not isinstance(entity_id, int):
        return None
    if getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False):
        return -(1_000_000_000_000 + entity_id)
    if type(entity).__name__ == "Chat":
        return -entity_id
    return entity_id


def serialize_message(message: Any, *, media_path: Optional[Path] = None, output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Serialize the parts of a Telethon message that are useful offline."""
    sender = getattr(message, "sender", None)
    reply_to = getattr(message, "reply_to", None)
    media_rel_path: Optional[str] = None
    if media_path is not None:
        try:
            media_rel_path = str(media_path.relative_to(output_dir or media_path.parent))
        except ValueError:
            media_rel_path = str(media_path)

    return {
        "id": getattr(message, "id", None),
        "date": _iso_or_none(getattr(message, "date", None)),
        "edit_date": _iso_or_none(getattr(message, "edit_date", None)),
        "sender_id": getattr(message, "sender_id", None),
        "sender": {
            "id": getattr(sender, "id", None),
            "username": getattr(sender, "username", None),
            "first_name": getattr(sender, "first_name", None),
            "last_name": getattr(sender, "last_name", None),
        } if sender is not None else None,
        "message": getattr(message, "message", None),
        "raw_text": getattr(message, "raw_text", None),
        "reply_to_msg_id": getattr(message, "reply_to_msg_id", None),
        "reply_to_top_id": getattr(reply_to, "reply_to_top_id", None) if reply_to is not None else None,
        "post_author": getattr(message, "post_author", None),
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "grouped_id": getattr(message, "grouped_id", None),
        "media": _message_media_summary(message),
        "media_path": media_rel_path,
    }


class ChannelDownloader:
    """Download all accessible messages and media for one Telegram entity."""

    def __init__(self, client: Any, *, logger_: Optional[logging.Logger] = None) -> None:
        self.client = client
        self.logger = logger_ or logger

    async def download(self, options: ChannelDownloadOptions) -> ChannelDownloadResult:
        if not isinstance(options.max_concurrency, int) or options.max_concurrency < 1:
            raise ValueError("max_concurrency must be a positive integer")
        if not isinstance(options.max_retries, int) or options.max_retries < 0:
            raise ValueError("max_retries must be zero or a positive integer")
        if not isinstance(options.retry_delay, (int, float)) or options.retry_delay < 0:
            raise ValueError("retry_delay must be zero or a positive number")
        if not isinstance(options.progress_interval, (int, float)) or options.progress_interval < 1:
            raise ValueError("progress_interval must be at least one second")
        if not isinstance(options.stall_timeout, (int, float)) or options.stall_timeout < 1:
            raise ValueError("stall_timeout must be at least one second")
        entity = await self.client.get_entity(options.entity)
        title = self._entity_title(entity, options.entity)
        entity_id = getattr(entity, "id", None)
        peer_id = _telegram_peer_id(entity)
        output_dir = options.output_dir / safe_path_component(f"{title}_{entity_id or options.entity}")
        output_dir.mkdir(parents=True, exist_ok=True)
        media_dir = output_dir / "media"
        if options.include_media:
            media_dir.mkdir(exist_ok=True)

        state_path = output_dir / "state.json"
        manifest_path = output_dir / "manifest.json"
        media_manifest_path = output_dir / "media_manifest.jsonl"
        summary_path = output_dir / "summary.json"
        messages_path = output_dir / "messages.jsonl"
        existing_manifest: dict[str, Any] = {}
        if options.resume and manifest_path.is_file():
            try:
                loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded_manifest, dict):
                    existing_manifest = loaded_manifest
            except (OSError, json.JSONDecodeError):
                existing_manifest = {}
        export_id = str(existing_manifest.get("export_id") or uuid.uuid4())
        last_seen_id = self._resume_message_id(state_path) if options.resume else None
        effective_min_id = max(filter(None, [options.min_id, last_seen_id]), default=None)
        started_at = datetime.now(timezone.utc)
        configured_log_path = os.getenv("SPECTRA_DOWNLOAD_LOG_PATH")

        manifest = {
            "export_id": export_id,
            "entity": options.entity,
            "entity_id": entity_id,
            "peer_id": peer_id,
            "title": title,
            "started_at": started_at.isoformat(),
            "include_media": options.include_media,
            "limit": options.limit,
            "min_id": options.min_id,
            "max_id": options.max_id,
            "resume_from_message_id": last_seen_id,
            "deduplicate": options.deduplicate,
            "write_metadata": options.write_metadata,
            "max_concurrency": options.max_concurrency,
            "max_retries": options.max_retries,
            "retry_delay": options.retry_delay,
            "fail_fast": options.fail_fast,
            "retry_flood_waits": options.retry_flood_waits,
            "progress_interval": options.progress_interval,
            "stall_timeout": options.stall_timeout,
            "log_path": configured_log_path,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        messages_written = 0
        media_downloaded = 0
        media_duplicates = 0
        media_skipped = 0
        completed_transfer_bytes = 0
        last_message_id = last_seen_id
        failed_media_ids: list[Any] = []
        failure_counts: dict[str, int] = {}
        existing_media = self._build_existing_media_index(options.output_dir) if options.deduplicate else {}
        media_index_lock = asyncio.Lock()
        active_transfer_bytes: dict[Any, tuple[int, int]] = {}
        last_summary_report = time.monotonic()
        started_monotonic = time.monotonic()
        self.logger.info("Media transfer concurrency: %s", options.max_concurrency)

        iter_kwargs: Dict[str, Any] = {"reverse": True}
        if options.limit is not None:
            iter_kwargs["limit"] = options.limit
        if effective_min_id is not None:
            iter_kwargs["min_id"] = effective_min_id
        if options.max_id is not None:
            iter_kwargs["max_id"] = options.max_id

        next_sequence_to_write = 0
        media_record_ordinal = 0
        if options.resume and media_manifest_path.is_file():
            with media_manifest_path.open("rb") as existing_manifest_handle:
                media_record_ordinal = sum(
                    1 for line in existing_manifest_handle if line.endswith(b"\n")
                )
        completed_results: dict[int, ProcessedMessageResult] = {}
        checkpoint_blocked = False

        def maybe_log_summary(force: bool = False) -> None:
            nonlocal last_summary_report
            now = time.monotonic()
            if not force and now - last_summary_report < options.progress_interval:
                return
            last_summary_report = now
            active_current = sum(current for current, _total in active_transfer_bytes.values())
            active_total = sum(total for _current, total in active_transfer_bytes.values())
            transferred_bytes = completed_transfer_bytes + active_current
            total_known_bytes = completed_transfer_bytes + active_total
            elapsed = max(time.monotonic() - started_monotonic, 0.001)
            rate = transferred_bytes / elapsed
            remaining = max(total_known_bytes - transferred_bytes, 0)
            eta = remaining / rate if rate > 0 and remaining else 0
            self.logger.info(
                "Download summary: messages=%s media_downloaded=%s media_skipped=%s media_duplicates=%s media_failed=%s active_transfers=%s pending_results=%s transferred=%s rate=%.2fMiB/s active_eta=%.1fs",
                messages_written,
                media_downloaded,
                media_skipped,
                media_duplicates,
                len(failed_media_ids),
                len(active_transfer_bytes),
                len(completed_results),
                transferred_bytes,
                rate / 1024 / 1024,
                eta,
            )

        def drain_completed_results(
            checkpoint: Optional[int],
            message_fh: Any,
            media_fh: Any,
            index_connection: Any,
        ) -> Optional[int]:
            nonlocal messages_written, media_downloaded, media_duplicates, media_skipped, next_sequence_to_write, checkpoint_blocked, completed_transfer_bytes, media_record_ordinal
            next_checkpoint = checkpoint
            while next_sequence_to_write in completed_results:
                result = completed_results.pop(next_sequence_to_write)
                message = result.message
                media = result.media
                completed_transfer_bytes += media.transferred_size
                if media.path is not None:
                    if media.was_skipped:
                        media_skipped += 1
                    else:
                        media_downloaded += 1
                if media.was_duplicate:
                    media_duplicates += 1
                if media.failed:
                    failed_id = getattr(message, "id", None)
                    if failed_id is not None:
                        failed_media_ids.append(failed_id)
                    if media.failure_type:
                        failure_counts[media.failure_type] = failure_counts.get(media.failure_type, 0) + 1
                    checkpoint_blocked = True
                record = serialize_message(message, media_path=media.path, output_dir=output_dir)
                if message_fh is not None:
                    message_fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                media_manifest_record = None
                if media_fh is not None and (media.path is not None or media.was_duplicate or media.failed):
                    media_manifest_record = self._write_media_manifest_record(
                        media_fh,
                        message,
                        media,
                        output_dir,
                        channel_id=peer_id,
                        export_id=export_id,
                        record_ordinal=media_record_ordinal,
                    )
                    media_record_ordinal += 1
                if index_connection is not None:
                    IndexOutbox.append_to(
                        index_connection,
                        source_table="channel_messages",
                        source_key=f"{peer_id}:{record.get('id')}",
                        event_type="download",
                        payload={
                            **record,
                            "message_id": record.get("id"),
                            "channel_id": peer_id,
                            "channel_title": title,
                            "export_id": export_id,
                            "record_ordinal": (
                                media_manifest_record["record_ordinal"]
                                if media_manifest_record is not None
                                else None
                            ),
                            "media_checksum": media.checksum,
                            "media_size": media.size,
                            "media_failed": media.failed,
                            "media_manifest": media_manifest_record,
                        },
                        source_revision=(
                            f"export-v1:{export_id}:{media_manifest_record['record_ordinal']}:"
                            f"{media_manifest_record['record_sha256']}"
                            if media_manifest_record is not None
                            else str(record.get("edit_date") or record.get("date") or media.checksum or "")
                        ),
                    )
                messages_written += 1
                if not checkpoint_blocked:
                    next_checkpoint = getattr(message, "id", next_checkpoint)
                next_sequence_to_write += 1

            self._write_state(
                state_path,
                next_checkpoint,
                messages_written,
                media_downloaded,
                media_skipped,
                failed_media_ids=failed_media_ids,
                failure_counts=failure_counts,
            )
            if index_connection is not None:
                index_connection.commit()
            maybe_log_summary()
            return next_checkpoint

        with ExitStack() as resources:
            if options.index_database is not None:
                IndexOutbox(options.index_database).status()
            index_connection = resources.enter_context(
                connect_sqlite(options.index_database)
            ) if options.index_database is not None else None
            message_fh = resources.enter_context(messages_path.open("a" if options.resume else "w", encoding="utf-8")) if options.write_metadata else None
            media_fh = resources.enter_context(media_manifest_path.open("ab" if options.resume else "wb")) if options.include_media else None
            pending: dict[asyncio.Task[ProcessedMessageResult], int] = {}
            next_sequence = 0
            async for message in self._iter_messages(entity, iter_kwargs):
                task = asyncio.create_task(self._process_message(message, media_dir, existing_media, media_index_lock, options, active_transfer_bytes, maybe_log_summary))
                pending[task] = next_sequence
                next_sequence += 1
                if len(pending) >= options.max_concurrency:
                    done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        sequence = pending.pop(task)
                        try:
                            completed_results[sequence] = task.result()
                        except Exception:
                            self._cancel_pending_tasks(pending)
                            raise
                    last_message_id = drain_completed_results(last_message_id, message_fh, media_fh, index_connection)

            while pending:
                done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    sequence = pending.pop(task)
                    try:
                        completed_results[sequence] = task.result()
                    except Exception:
                        self._cancel_pending_tasks(pending)
                        raise
                last_message_id = drain_completed_results(last_message_id, message_fh, media_fh, index_connection)

        self._write_state(
            state_path,
            last_message_id,
            messages_written,
            media_downloaded,
            media_skipped,
            failed_media_ids=failed_media_ids,
                failure_counts=failure_counts,
            complete=True,
        )
        maybe_log_summary(force=True)
        self._write_summary(
            summary_path,
            manifest,
            started_at,
            last_message_id,
            messages_written,
            media_downloaded,
            media_duplicates,
            media_skipped,
            failed_media_ids,
            completed_transfer_bytes,
            complete=True,
        )
        return ChannelDownloadResult(
            entity_id=entity_id,
            title=title,
            output_dir=output_dir,
            messages_written=messages_written,
            media_downloaded=media_downloaded,
            media_duplicates=media_duplicates,
            media_skipped=media_skipped,
            last_message_id=last_message_id,
        )

    async def retry_failed(self, options: ChannelDownloadOptions) -> ChannelDownloadResult:
        entity = await self.client.get_entity(options.entity)
        title = self._entity_title(entity, options.entity)
        entity_id = getattr(entity, "id", None)
        output_dir = options.output_dir / safe_path_component(f"{title}_{entity_id or options.entity}")
        
        state_path = output_dir / "state.json"
        
        if not state_path.exists():
            self.logger.warning("No state.json found for %s", options.entity)
            return ChannelDownloadResult(entity_id=entity_id, title=title, output_dir=output_dir, messages_written=0, media_downloaded=0, media_duplicates=0, media_skipped=0, last_message_id=None)
            
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            failed_media_ids = state.get("failed_media_ids", [])
        except Exception as exc:
            self.logger.error("Failed to read state.json for %s: %s", options.entity, exc)
            return ChannelDownloadResult(entity_id=entity_id, title=title, output_dir=output_dir, messages_written=0, media_downloaded=0, media_duplicates=0, media_skipped=0, last_message_id=None)
            
        if not failed_media_ids:
            self.logger.info("No failed media to retry for %s", options.entity)
            return ChannelDownloadResult(entity_id=entity_id, title=title, output_dir=output_dir, messages_written=0, media_downloaded=0, media_duplicates=0, media_skipped=0, last_message_id=state.get("last_message_id"))
            
        media_dir = output_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        
        existing_media = self._build_existing_media_index(options.output_dir) if options.deduplicate else {}
        media_index_lock = asyncio.Lock()
        active_transfer_bytes = {}
        
        self.logger.info("Retrying %d failed media downloads for %s", len(failed_media_ids), options.entity)
        
        # Need to fetch the messages
        messages = await self.client.get_messages(entity, ids=failed_media_ids)
        
        messages_written = 0
        media_downloaded = 0
        media_duplicates = 0
        media_skipped = 0
        completed_transfer_bytes = 0
        new_failed_ids = []
        failure_counts = {}
        
        def noop_summary():
            pass
            
        for message in messages:
            if not message or not getattr(message, "media", None):
                continue
            media = await self._download_media(message, media_dir, existing_media, media_index_lock, options, active_transfer_bytes, noop_summary)
            completed_transfer_bytes += media.transferred_size
            if media.path is not None:
                if media.was_skipped:
                    media_skipped += 1
                else:
                    media_downloaded += 1
            if media.was_duplicate:
                media_duplicates += 1
            if media.failed:
                failed_id = getattr(message, "id", None)
                if failed_id is not None:
                    new_failed_ids.append(failed_id)
                if media.failure_type:
                    failure_counts[media.failure_type] = failure_counts.get(media.failure_type, 0) + 1
                    
        self._write_state(
            state_path,
            state.get("last_message_id"),
            state.get("messages_written_this_run", 0),
            state.get("media_downloaded_this_run", 0) + media_downloaded,
            state.get("media_skipped_this_run", 0) + media_skipped,
            failed_media_ids=new_failed_ids,
            failure_counts=failure_counts,
            complete=not bool(new_failed_ids)
        )
        
        return ChannelDownloadResult(
            entity_id=entity_id,
            title=title,
            output_dir=output_dir,
            messages_written=messages_written,
            media_downloaded=media_downloaded,
            media_duplicates=media_duplicates,
            media_skipped=media_skipped,
            last_message_id=state.get("last_message_id")
        )

    async def _iter_messages(self, entity: Any, kwargs: Dict[str, Any]) -> AsyncIterator[Any]:
        iterator = self.client.iter_messages(entity, **kwargs)
        if hasattr(iterator, "__await__"):
            iterator = await iterator
        async for message in iterator:
            yield message

    async def _process_message(
        self,
        message: Any,
        media_dir: Path,
        existing_media: Dict[int, set[Path]],
        media_index_lock: asyncio.Lock,
        options: ChannelDownloadOptions,
        active_transfer_bytes: dict[Any, tuple[int, int]],
        progress_summary: Callable[[], None],
    ) -> ProcessedMessageResult:
        if not getattr(message, "media", None):
            return ProcessedMessageResult(message, MediaDownloadOutcome(None))
        media = await self._download_media(message, media_dir, existing_media, media_index_lock, options, active_transfer_bytes, progress_summary)
        return ProcessedMessageResult(message, media)

    async def _download_media(
        self,
        message: Any,
        media_dir: Path,
        existing_media: Dict[int, set[Path]],
        media_index_lock: asyncio.Lock,
        options: ChannelDownloadOptions,
        active_transfer_bytes: dict[Any, tuple[int, int]],
        progress_summary: Callable[[], None],
    ) -> MediaDownloadOutcome:
        file_obj = getattr(message, "file", None)
        message_id = getattr(message, "id", None)
        name = safe_path_component(getattr(file_obj, "name", None) or getattr(file_obj, "id", None) or getattr(message, "id", None), fallback=str(getattr(message, "id", "media")))
        if getattr(file_obj, "ext", None) and not name.endswith(str(file_obj.ext)):
            name = f"{name}{file_obj.ext}"
        destination = media_dir / f"{getattr(message, 'id', 'message')}_{name}"
        partial_destination = destination.with_name(f"{destination.name}{PARTIAL_SUFFIX}")
        display_name = destination.name
        transfer_key = message_id if message_id is not None else display_name
        expected_size = getattr(file_obj, "size", None)
        self.logger.info("Media check: %s", display_name)
        if destination.exists():
            try:
                existing_size = destination.stat().st_size
                existing_digest = _sha256(destination) if expected_size is None or existing_size == expected_size else None
            except OSError as exc:
                self.logger.warning("Media check failed for %s: %s", display_name, exc)
            else:
                if expected_size is None or existing_size == expected_size:
                    async with media_index_lock:
                        existing_media.setdefault(existing_size, set()).add(destination)
                    self.logger.info("Media already present: %s (%s bytes)", display_name, existing_size)
                    return MediaDownloadOutcome(destination, was_skipped=True, checksum=existing_digest, size=existing_size)
                self.logger.info(
                    "Media incomplete, resuming replacement: %s (%s/%s bytes)",
                    display_name,
                    existing_size,
                    expected_size,
                )

        self.logger.info("Media download started: %s", display_name)
        last_reported_percent = -1
        last_progress_at = time.monotonic()

        def report_progress(current: int, total: int) -> None:
            nonlocal last_reported_percent, last_progress_at
            if not total:
                return
            last_progress_at = time.monotonic()
            active_transfer_bytes[transfer_key] = (current, total)
            progress_summary()
            percent = min(100, int(current * 100 / total))
            bucket = (percent // 10) * 10
            if bucket != last_reported_percent or percent == 100:
                last_reported_percent = bucket
                self.logger.info("Media progress: %s %s%% (%s/%s bytes)", display_name, percent, current, total)

        self._remove_partial_file(partial_destination)
        downloaded = None
        for attempt in range(options.max_retries + 1):
            try:
                last_progress_at = time.monotonic()
                downloaded = await self._download_media_with_stall_watchdog(
                    message,
                    partial_destination,
                    report_progress,
                    lambda: last_progress_at,
                    options.stall_timeout,
                )
                break
            except Exception as exc:
                active_transfer_bytes.pop(transfer_key, None)
                if options.fail_fast:
                    self.logger.error("Media download failed in fail-fast mode for message %s: %s", getattr(message, "id", None), exc)
                    raise
                if not self._should_retry(exc, attempt, options):
                    self.logger.warning("Failed to download media for message %s after %s attempt(s): %s", getattr(message, "id", None), attempt + 1, exc)
                    self._remove_partial_file(partial_destination)
                    return MediaDownloadOutcome(None, failed=True, error=str(exc), failure_type=self._classify_failure(exc))
                delay = self._retry_delay(exc, options)
                self.logger.warning(
                    "Media download retry scheduled: %s attempt=%s/%s delay=%.1fs reason=%s",
                    display_name,
                    attempt + 1,
                    options.max_retries + 1,
                    delay,
                    exc,
                )
                self._remove_partial_file(partial_destination)
                await asyncio.sleep(delay)
        if not downloaded:
            self.logger.warning("Media download returned no file: %s", display_name)
            self._remove_partial_file(partial_destination)
            active_transfer_bytes.pop(transfer_key, None)
            return MediaDownloadOutcome(None, failed=True, error="download returned no file", failure_type="missing_media")

        downloaded_path = Path(downloaded)
        try:
            digest = _sha256(downloaded_path)
            size = downloaded_path.stat().st_size
        except OSError as exc:
            self.logger.warning("Unable to index downloaded media %s: %s", downloaded_path, exc)
            active_transfer_bytes.pop(transfer_key, None)
            return MediaDownloadOutcome(downloaded_path, size=None, error=str(exc))

        async with media_index_lock:
            for candidate in existing_media.get(size, set()):
                if candidate == downloaded_path:
                    continue
                try:
                    if _sha256(candidate) == digest:
                        try:
                            downloaded_path.unlink()
                        except OSError as exc:
                            self.logger.warning("Unable to remove duplicate media %s: %s", downloaded_path, exc)
                        self.logger.info("Media duplicate skipped: %s", display_name)
                        active_transfer_bytes.pop(transfer_key, None)
                        return MediaDownloadOutcome(None, was_duplicate=True, checksum=digest, size=size, transferred_size=size)
                except OSError as exc:
                    self.logger.warning("Skipping unreadable deduplication candidate %s: %s", candidate, exc)

            try:
                downloaded_path.replace(destination)
            except OSError as exc:
                self.logger.warning("Unable to finalize media %s: %s", display_name, exc)
                active_transfer_bytes.pop(transfer_key, None)
                return MediaDownloadOutcome(downloaded_path, failed=True, checksum=digest, size=size, transferred_size=size, error=str(exc), failure_type=self._classify_failure(exc))
            existing_media.setdefault(size, set()).add(destination)
        self.logger.info("Media download complete: %s (%s bytes)", display_name, size)
        active_transfer_bytes.pop(transfer_key, None)
        return MediaDownloadOutcome(destination, checksum=digest, size=size, transferred_size=size)

    async def _download_media_with_stall_watchdog(
        self,
        message: Any,
        destination: Path,
        progress_callback: Callable[[int, int], None],
        last_progress_at: Callable[[], float],
        stall_timeout: float,
    ) -> Any:
        task = asyncio.create_task(message.download_media(file=destination, progress_callback=progress_callback))
        try:
            while not task.done():
                done, _ = await asyncio.wait(
                    {task},
                    timeout=min(STALL_POLL_INTERVAL_SECONDS, stall_timeout),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if done:
                    return await task
                idle_for = time.monotonic() - last_progress_at()
                if idle_for >= stall_timeout:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    raise TimeoutError(f"media transfer stalled for {idle_for:.1f}s")
            return await task
        except Exception:
            if not task.done():
                task.cancel()
            raise

    def _build_existing_media_index(self, root: Path) -> Dict[int, set[Path]]:
        """Index existing files by size without reading their contents."""
        index: Dict[int, set[Path]] = {}
        try:
            candidates = (path for path in root.rglob("*") if path.is_file())
            for path in candidates:
                try:
                    size = path.stat().st_size
                    index.setdefault(size, set()).add(path)
                except OSError as exc:
                    self.logger.warning("Skipping unreadable existing file %s: %s", path, exc)
        except OSError as exc:
            self.logger.warning("Unable to scan existing files under %s: %s", root, exc)
        return index

    def _entity_title(self, entity: Any, fallback: str) -> str:
        return (
            getattr(entity, "title", None)
            or getattr(entity, "username", None)
            or getattr(entity, "first_name", None)
            or fallback
        )

    def _cancel_pending_tasks(self, pending: Dict[asyncio.Task[ProcessedMessageResult], int]) -> None:
        for task in pending:
            task.cancel()

    def _remove_partial_file(self, path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            self.logger.warning("Unable to remove partial media file %s: %s", path, exc)

    def _classify_failure(self, exc: Exception) -> str:
        exc_str = str(exc).lower()
        if 'flood' in type(exc).__name__.lower():
            return 'flood_wait'
        if 'permission' in exc_str or 'access denied' in exc_str or isinstance(exc, PermissionError):
            return 'permission'
        if isinstance(exc, OSError):
            return 'filesystem'
        if 'missing' in exc_str or 'not found' in exc_str:
            return 'missing_media'
        return 'unknown'

    def _should_retry(self, exc: Exception, attempt: int, options: ChannelDownloadOptions) -> bool:
        if attempt >= options.max_retries:
            return False
        if self._flood_wait_seconds(exc) is not None:
            return options.retry_flood_waits
        return True

    def _retry_delay(self, exc: Exception, options: ChannelDownloadOptions) -> float:
        flood_wait = self._flood_wait_seconds(exc)
        if flood_wait is not None:
            return float(flood_wait + 1)
        return float(options.retry_delay)

    def _flood_wait_seconds(self, exc: Exception) -> Optional[int]:
        seconds = getattr(exc, "seconds", None)
        name = type(exc).__name__.lower()
        if seconds is None or "flood" not in name:
            return None
        try:
            return max(0, int(seconds))
        except (TypeError, ValueError):
            return None

    def _write_media_manifest_record(
        self,
        handle: Any,
        message: Any,
        media: MediaDownloadOutcome,
        output_dir: Path,
        *,
        channel_id: Optional[int],
        export_id: str,
        record_ordinal: int,
    ) -> Dict[str, Any]:
        rel_path = None
        if media.path is not None:
            try:
                rel_path = str(media.path.relative_to(output_dir))
            except ValueError:
                rel_path = str(media.path)
        record = {
            "export_id": export_id,
            "record_ordinal": record_ordinal,
            "channel_id": channel_id,
            "message_id": getattr(message, "id", None),
            "path": rel_path,
            "size": media.size,
            "sha256": media.checksum,
            "duplicate": media.was_duplicate,
            "skipped_existing": media.was_skipped,
            "failed": media.failed,
            "error": media.error,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        byte_offset = int(handle.tell())
        serialized = json.dumps(
            record,
            ensure_ascii=False,
            default=str,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        handle.write(serialized)
        return {
            "export_id": export_id,
            "record_ordinal": record_ordinal,
            "channel_id": channel_id,
            "message_id": record["message_id"],
            "manifest_path": "media_manifest.jsonl",
            "byte_offset": byte_offset,
            "byte_length": len(serialized),
            "record_sha256": hashlib.sha256(serialized).hexdigest(),
            "media_path": rel_path,
            "media_size": media.size,
            "media_sha256": media.checksum,
            "failed": media.failed,
        }

    def _write_summary(
        self,
        summary_path: Path,
        manifest: Dict[str, Any],
        started_at: datetime,
        last_message_id: Optional[int],
        messages_written: int,
        media_downloaded: int,
        media_duplicates: int,
        media_skipped: int,
        failed_media_ids: list[Any],
        completed_transfer_bytes: int,
        failure_counts: Optional[dict[str, int]] = None,
        *,
        complete: bool,
    ) -> None:
        finished_at = datetime.now(timezone.utc)
        summary = {
            "entity": manifest.get("entity"),
            "entity_id": manifest.get("entity_id"),
            "title": manifest.get("title"),
            "output_dir": str(summary_path.parent),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "elapsed_seconds": round((finished_at - started_at).total_seconds(), 3),
            "last_message_id": last_message_id,
            "messages_written": messages_written,
            "media_downloaded": media_downloaded,
            "media_duplicates": media_duplicates,
            "media_skipped": media_skipped,
            "transferred_bytes": completed_transfer_bytes,
            "failed_media_ids": failed_media_ids,
            "failure_counts": failure_counts or {},
            "complete": complete,
            "resume": not complete or bool(failed_media_ids),
        }
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    def _resume_message_id(self, state_path: Path) -> Optional[int]:
        if not state_path.exists():
            return None
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            value = state.get("last_message_id")
            return int(value) if value is not None else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.logger.warning("Ignoring unreadable download state at %s", state_path)
            return None

    def _write_state(
        self,
        state_path: Path,
        last_message_id: Optional[int],
        messages_written: int,
        media_downloaded: int,
        media_skipped: int,
        *,
        failed_media_ids: Optional[list[Any]] = None,
        failure_counts: Optional[dict[str, int]] = None,
        complete: bool = False,
    ) -> None:
        state_path.write_text(
            json.dumps(
                {
                    "last_message_id": last_message_id,
                    "messages_written_this_run": messages_written,
                    "media_downloaded_this_run": media_downloaded,
                    "media_skipped_this_run": media_skipped,
                    "media_failed_this_run": len(failed_media_ids or []),
                    "failed_media_ids": failed_media_ids or [],
                    "failure_counts": failure_counts or {},
                    "log_path": os.getenv("SPECTRA_DOWNLOAD_LOG_PATH"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "complete": complete,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
