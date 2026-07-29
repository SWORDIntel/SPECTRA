"""Idempotent import of completed channel-export manifests into the index outbox."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from ..db.index_outbox import IndexOutbox
from ..sqlite_runtime import connect_sqlite


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read JSON object from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _channel_id(manifest: dict[str, Any]) -> int:
    for key in ("peer_id", "entity"):
        value = manifest.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                pass
    entity_id = manifest.get("entity_id")
    if isinstance(entity_id, int):
        return entity_id
    raise ValueError("manifest does not contain a numeric Telegram channel identity")


def _ensure_export_id(
    export_path: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    channel_id: int,
) -> str:
    existing = manifest.get("export_id")
    if isinstance(existing, str) and existing:
        return existing
    seed = "\0".join(
        (
            str(channel_id),
            str(manifest.get("started_at") or ""),
            str(manifest.get("title") or ""),
            export_path.name,
        )
    )
    export_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"spectra-export:{seed}"))
    manifest["export_id"] = export_id
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)
    return export_id


def backfill_channel_export(
    export_dir: Path | str,
    database: Path | str,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Append a stable snapshot of media_manifest.jsonl to an index outbox."""
    export_path = Path(export_dir).expanduser().resolve()
    database_path = Path(database).expanduser().resolve()
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if not export_path.is_dir():
        raise ValueError(f"export directory not found: {export_path}")
    manifest_path = export_path / "manifest.json"
    manifest = _read_object(manifest_path)
    media_manifest_path = export_path / "media_manifest.jsonl"
    if not media_manifest_path.is_file():
        raise ValueError(f"media manifest not found: {media_manifest_path}")

    channel_id = _channel_id(manifest)
    export_id = _ensure_export_id(export_path, manifest_path, manifest, channel_id)
    snapshot_bytes = media_manifest_path.stat().st_size
    outbox = IndexOutbox(database_path)
    counts = {
        "records_read": 0,
        "inserted": 0,
        "already_present": 0,
        "invalid": 0,
        "incomplete_tail": 0,
    }

    with connect_sqlite(database_path) as connection, media_manifest_path.open("rb") as handle:
        IndexOutbox.ensure_schema(connection)
        record_ordinal = 0
        while handle.tell() < snapshot_bytes and (limit is None or counts["records_read"] < limit):
            byte_offset = handle.tell()
            raw_line = handle.readline(snapshot_bytes - byte_offset)
            if not raw_line:
                break
            if not raw_line.endswith(b"\n"):
                counts["incomplete_tail"] += 1
                break
            current_ordinal = record_ordinal
            record_ordinal += 1
            counts["records_read"] += 1
            try:
                record = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                counts["invalid"] += 1
                continue
            if not isinstance(record, dict) or not isinstance(record.get("message_id"), int):
                counts["invalid"] += 1
                continue

            message_id = int(record["message_id"])
            record_channel_id = record.get("channel_id")
            if not isinstance(record_channel_id, int):
                record_channel_id = channel_id
            line_checksum = hashlib.sha256(raw_line).hexdigest()
            media_manifest = {
                "export_id": export_id,
                "record_ordinal": current_ordinal,
                "channel_id": record_channel_id,
                "message_id": message_id,
                "manifest_path": str(media_manifest_path),
                "byte_offset": byte_offset,
                "byte_length": len(raw_line),
                "record_sha256": line_checksum,
                "media_path": record.get("path"),
                "media_size": record.get("size"),
                "media_sha256": record.get("sha256"),
                "failed": bool(record.get("failed")),
            }
            payload = {
                "export_id": export_id,
                "record_ordinal": current_ordinal,
                "channel_id": record_channel_id,
                "message_id": message_id,
                "media_checksum": record.get("sha256"),
                "media_size": record.get("size"),
                "media_failed": bool(record.get("failed")),
                "media_manifest": media_manifest,
            }
            source_revision = (
                f"export-v1:{export_id}:{current_ordinal}:{line_checksum}"
            )
            sequence_id = IndexOutbox.append_to(
                connection,
                source_table="channel_messages",
                source_key=f"{record_channel_id}:{message_id}",
                event_type="download",
                payload=payload,
                source_revision=source_revision,
            )
            counts["inserted" if sequence_id is not None else "already_present"] += 1

    return {
        "database": str(database_path),
        "export_dir": str(export_path),
        "manifest_path": str(media_manifest_path),
        "export_id": export_id,
        "channel_id": channel_id,
        "snapshot_bytes": snapshot_bytes,
        **counts,
    }


__all__ = ["backfill_channel_export"]
