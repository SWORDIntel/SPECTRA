"""
Import Service — Bring external data into SPECTRA's QIHSE+KEYSTONE index
=======================================================================

Supports importing from:
  - External SQLite databases (tgarchive-compatible schema)
  - JSON exports (message arrays or NDJSON)
  - CSV files with message columns
  - Channel export manifests
  - Telegram Desktop export JSON history

All imported data flows through the IndexOutbox → IndexProjector pipeline,
so it gets projected to QIHSE (content, graph, errors) and KEYSTONE (ID
anchors) for rapid cross-indexing and analysis.

Usage (library)::

    from tgarchive.services.import_service import import_data

    result = import_data(
        target_db="spectra.db",
        source="/path/to/external.db",
        format="sqlite",
        limit=10000,
    )

Usage (CLI)::

    spectra-cli import --source /path/to/data --format sqlite --limit 10000
    spectra-cli import --source /path/to/messages.json --format json
    spectra-cli import --source /path/to/messages.csv --format csv
"""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

try:
    import ijson
    _HAS_IJSON = True
except ImportError:
    ijson = None
    _HAS_IJSON = False

from ..db.index_outbox import IndexOutbox
from ..sqlite_runtime import connect_sqlite
from .utils import revision_hash as _revision

logger = logging.getLogger(__name__)

# Tables to import from a foreign SQLite DB, with column mappings.
# Each entry: (table, key_column, event_type, payload_fields)
# payload_fields maps foreign column → outbox payload field name.
_SQLITE_TABLE_MAP: Dict[str, tuple[str, str, Dict[str, str]]] = {
    "messages": (
        "id",
        "upsert",
        {
            "id": "message_id",
            "type": "type",
            "date": "date",
            "edit_date": "edit_date",
            "content": "content",
            "reply_to": "reply_to",
            "user_id": "user_id",
            "media_id": "media_id",
            "checksum": "checksum",
        },
    ),
    "users": (
        "id",
        "upsert",
        {
            "id": "user_id",
            "username": "username",
            "first_name": "first_name",
            "last_name": "last_name",
            "tags": "tags",
            "avatar": "avatar",
        },
    ),
    "media": (
        "id",
        "upsert",
        {
            "id": "media_id",
            "type": "type",
            "url": "url",
            "title": "title",
            "description": "description",
            "checksum": "checksum",
        },
    ),
    "channel_messages": (
        "message_id",
        "upsert",
        {
            "message_id": "message_id",
            "channel_id": "channel_id",
            "user_id": "user_id",
            "topic_id": "topic_id",
            "date": "date",
            "edit_date": "edit_date",
            "content": "content",
            "reply_to": "reply_to",
        },
    ),
}


_REVISION_TRUNCATE = 32
_DEFAULT_CHUNK_SIZE = 1000


def _notify_progress(
    callback: Optional[Callable[..., Any]],
    scanned: int,
    inserted: int,
    already_present: int,
) -> None:
    """Safely invoke progress callback supporting 1, 2, or 3 arguments."""
    if callback is None:
        return
    try:
        callback(scanned, inserted, already_present)
    except TypeError:
        try:
            callback(scanned, inserted)
        except TypeError:
            try:
                callback(scanned)
            except Exception:
                pass
    except Exception as exc:
        logger.debug("Progress callback exception: %s", exc)


def _import_sqlite(
    target_conn: sqlite3.Connection,
    source_path: Path,
    *,
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> Dict[str, Any]:
    """Import data from a foreign SQLite database into the target's IndexOutbox."""
    scanned = inserted = already_present = 0
    by_table: Dict[str, Dict[str, int]] = {}

    with sqlite3.connect(str(source_path)) as src_conn:
        src_conn.row_factory = sqlite3.Row
        existing_tables = {
            str(row[0])
            for row in src_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        for table, (key_col, event_type, field_map) in _SQLITE_TABLE_MAP.items():
            if table not in existing_tables:
                continue
            if limit is not None and scanned >= limit:
                break

            table_scanned = table_inserted = 0
            remaining = None if limit is None else limit - scanned

            # Build SELECT with only mapped columns that exist
            available_cols = set()
            col_info = src_conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            for col in col_info:
                if col["name"] in field_map:
                    available_cols.add(col["name"])

            if not available_cols:
                continue

            select_cols = ", ".join(f'"{c}"' for c in field_map if c in available_cols)
            sql = f'SELECT {select_cols} FROM "{table}" ORDER BY "{key_col}"'
            params: tuple = ()
            if remaining is not None:
                sql += " LIMIT ?"
                params = (remaining,)

            for row in src_conn.execute(sql, params):
                payload = {}
                for foreign_col, payload_field in field_map.items():
                    if foreign_column := (foreign_col if foreign_col in available_cols else None):
                        val = row[foreign_column]
                        # Convert None stays None, convert bytes to str
                        if isinstance(val, bytes):
                            val = val.decode("utf-8", errors="replace")
                        payload[payload_field] = val

                source_key = str(row[key_col])
                source_revision = f"{table}-{source_key}-{_revision(payload)[:_REVISION_TRUNCATE]}"

                seq_id = IndexOutbox.append_to(
                    target_conn,
                    source_table=table,
                    source_key=source_key,
                    event_type=event_type,
                    payload=payload,
                    source_revision=source_revision,
                )
                scanned += 1
                table_scanned += 1
                if seq_id is None:
                    already_present += 1
                else:
                    inserted += 1
                    table_inserted += 1

                if chunk_size > 0 and scanned % chunk_size == 0:
                    target_conn.commit()
                    if progress_callback is not None:
                        _notify_progress(progress_callback, scanned, inserted, already_present)

            by_table[table] = {
                "scanned": table_scanned,
                "inserted": table_inserted,
                "already_present": table_scanned - table_inserted,
            }

    target_conn.commit()
    if progress_callback is not None and (chunk_size <= 0 or scanned % chunk_size != 0):
        _notify_progress(progress_callback, scanned, inserted, already_present)

    return {
        "scanned": scanned,
        "inserted": inserted,
        "already_present": already_present,
        "tables": by_table,
    }


def _iter_json_messages_ijson(source_path: Path) -> Iterator[Dict[str, Any]]:
    """Stream message dicts using ijson for memory-efficient parsing."""
    yielded = False
    try:
        # Telegram export format: {"messages": [ {...}, ... ]}
        with open(source_path, "rb") as f:
            for item in ijson.items(f, "messages.item"):
                if isinstance(item, dict):
                    yielded = True
                    yield item
            if yielded:
                return
    except Exception:
        pass

    try:
        # Standard JSON array: [ {...}, {...} ]
        with open(source_path, "rb") as f:
            for item in ijson.items(f, "item"):
                if isinstance(item, dict):
                    yielded = True
                    yield item
            if yielded:
                return
    except Exception:
        pass

    # If neither yielded anything (e.g. NDJSON or single dict), fallback
    yield from _iter_json_messages_fallback(source_path)


def _iter_json_messages_fallback(source_path: Path) -> Iterator[Dict[str, Any]]:
    """Fallback message parser using standard library json."""
    # Try parsing full file as standard JSON or Telegram export
    try:
        with open(source_path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    yield item
            return
        elif isinstance(data, dict):
            if "messages" in data and isinstance(data["messages"], list):
                for item in data["messages"]:
                    if isinstance(item, dict):
                        yield item
            else:
                yield data
            return
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # Fallback to NDJSON (one JSON object per line)
    try:
        with open(source_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            yield obj
                    except json.JSONDecodeError:
                        continue
    except Exception:
        pass


def _iter_json_messages(source_path: Path) -> Iterator[Dict[str, Any]]:
    """Yield message dicts from a JSON, NDJSON, or Telegram export file."""
    if _HAS_IJSON and ijson is not None:
        yield from _iter_json_messages_ijson(source_path)
    else:
        yield from _iter_json_messages_fallback(source_path)


def _import_json(
    target_conn: sqlite3.Connection,
    source_path: Path,
    *,
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> Dict[str, Any]:
    """Import messages from a JSON/NDJSON file."""
    scanned = inserted = already_present = 0

    for msg in _iter_json_messages(source_path):
        if limit is not None and scanned >= limit:
            break

        msg_id = msg.get("id") if msg.get("id") is not None else msg.get("message_id")
        if msg_id is None:
            continue

        source_key = str(msg_id)
        payload = {
            "message_id": int(msg_id) if str(msg_id).isdigit() else msg_id,
            "type": msg.get("type", "text"),
            "date": msg.get("date", datetime.now(timezone.utc).isoformat()),
            "edit_date": msg.get("edit_date"),
            "content": msg.get("content") or msg.get("text") or "",
            "reply_to": msg.get("reply_to"),
            "user_id": msg.get("user_id") if msg.get("user_id") is not None else msg.get("from_id"),
            "media_id": msg.get("media_id"),
            "checksum": msg.get("checksum"),
        }
        # Include channel_id if present (channel_messages format)
        if "channel_id" in msg:
            payload["channel_id"] = msg["channel_id"]

        source_revision = f"json-msg-{source_key}-{_revision(payload)[:_REVISION_TRUNCATE]}"

        seq_id = IndexOutbox.append_to(
            target_conn,
            source_table="messages",
            source_key=source_key,
            event_type="upsert",
            payload=payload,
            source_revision=source_revision,
        )
        scanned += 1
        if seq_id is None:
            already_present += 1
        else:
            inserted += 1

        if chunk_size > 0 and scanned % chunk_size == 0:
            target_conn.commit()
            if progress_callback is not None:
                _notify_progress(progress_callback, scanned, inserted, already_present)

    target_conn.commit()
    if progress_callback is not None and (chunk_size <= 0 or scanned % chunk_size != 0):
        _notify_progress(progress_callback, scanned, inserted, already_present)

    return {
        "scanned": scanned,
        "inserted": inserted,
        "already_present": already_present,
        "source": str(source_path),
        "format": "json",
    }


def _import_csv(
    target_conn: sqlite3.Connection,
    source_path: Path,
    *,
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> Dict[str, Any]:
    """Import messages from a CSV file."""
    scanned = inserted = already_present = 0

    with open(source_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if limit is not None and scanned >= limit:
                break

            msg_id = row.get("id") if row.get("id") is not None else row.get("message_id")
            if not msg_id:
                continue

            source_key = str(msg_id)
            payload = {
                "message_id": int(msg_id) if str(msg_id).isdigit() else msg_id,
                "type": row.get("type", "text"),
                "date": row.get("date", datetime.now(timezone.utc).isoformat()),
                "edit_date": row.get("edit_date"),
                "content": row.get("content") or row.get("text") or "",
                "reply_to": int(row["reply_to"]) if row.get("reply_to") else None,
                "user_id": int(row["user_id"]) if row.get("user_id") else None,
                "media_id": int(row["media_id"]) if row.get("media_id") else None,
                "checksum": row.get("checksum"),
            }
            if "channel_id" in row:
                payload["channel_id"] = int(row["channel_id"]) if row.get("channel_id") else None

            source_revision = f"csv-msg-{source_key}-{_revision(payload)[:_REVISION_TRUNCATE]}"

            seq_id = IndexOutbox.append_to(
                target_conn,
                source_table="messages",
                source_key=source_key,
                event_type="upsert",
                payload=payload,
                source_revision=source_revision,
            )
            scanned += 1
            if seq_id is None:
                already_present += 1
            else:
                inserted += 1

            if chunk_size > 0 and scanned % chunk_size == 0:
                target_conn.commit()
                if progress_callback is not None:
                    _notify_progress(progress_callback, scanned, inserted, already_present)

    target_conn.commit()
    if progress_callback is not None and (chunk_size <= 0 or scanned % chunk_size != 0):
        _notify_progress(progress_callback, scanned, inserted, already_present)

    return {
        "scanned": scanned,
        "inserted": inserted,
        "already_present": already_present,
        "source": str(source_path),
        "format": "csv",
    }


def import_data(
    target_db: Path | str,
    source: Path | str,
    *,
    format: str = "auto",
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> Dict[str, Any]:
    """Import external data into SPECTRA's IndexOutbox for QIHSE/KEYSTONE projection.

    Args:
        target_db: Path to the target SPECTRA SQLite database.
        source: Path to the source data file.
        format: Import format — "auto", "sqlite", "json", "csv", "telegram-export".
        limit: Maximum number of records to import (None = no limit).
        progress_callback: Optional callback invoked with progress (scanned, inserted, already_present).
        chunk_size: Number of records per chunk/commit (default: 1000).

    Returns:
        Dict with import statistics: scanned, inserted, already_present, tables.
    """
    target_path = Path(target_db).expanduser().resolve()
    source_path = Path(source).expanduser().resolve()

    if not source_path.exists():
        raise FileNotFoundError(f"Source does not exist: {source_path}")

    # Auto-detect format
    if format == "auto":
        suffix = source_path.suffix.lower()
        if suffix in (".db", ".sqlite", ".sqlite3"):
            format = "sqlite"
        elif suffix in (".json", ".ndjson"):
            format = "json"
        elif suffix == ".csv":
            format = "csv"
        else:
            # Try to detect by content without reading full file into memory
            try:
                first_bytes = source_path.read_bytes()[:16]
                if first_bytes.startswith(b"SQLite format 3"):
                    format = "sqlite"
                else:
                    with open(source_path, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read(1024).strip()
                    if text.startswith("{") or text.startswith("["):
                        format = "json"
                    else:
                        format = "csv"
            except Exception:
                format = "json"

    logger.info("Importing %s (format=%s) into %s", source_path, format, target_path)

    with connect_sqlite(target_path) as target_conn:
        IndexOutbox.ensure_schema(target_conn)

        if format == "sqlite":
            result = _import_sqlite(
                target_conn,
                source_path,
                limit=limit,
                progress_callback=progress_callback,
                chunk_size=chunk_size,
            )
        elif format == "json":
            result = _import_json(
                target_conn,
                source_path,
                limit=limit,
                progress_callback=progress_callback,
                chunk_size=chunk_size,
            )
        elif format == "csv":
            result = _import_csv(
                target_conn,
                source_path,
                limit=limit,
                progress_callback=progress_callback,
                chunk_size=chunk_size,
            )
        elif format == "telegram-export":
            result = _import_telegram_export(
                target_conn,
                source_path,
                limit=limit,
                progress_callback=progress_callback,
                chunk_size=chunk_size,
            )
        else:
            raise ValueError(f"Unknown import format: {format}")

        target_conn.commit()

    result["target"] = str(target_path)
    result["source"] = str(source_path)
    result["format"] = format
    logger.info(
        "Import complete: %d scanned, %d inserted, %d already present",
        result["scanned"], result["inserted"], result["already_present"],
    )
    return result


# ── Telegram Export Format ──────────────────────────────────────────────────

def _convert_telegram_export(msg: dict[str, Any]) -> dict[str, Any]:
    """Convert a Telegram export message to SPECTRA schema.

    Telegram export fields → SPECTRA fields:
      id → message_id
      date (Unix timestamp string) → date (ISO format)
      from_id ("user123") → user_id (int)
      text (string or array of text entities) → content (string)
      reply_to_message_id → reply_to
      type → type
    """
    msg_id = msg.get("id")
    if msg_id is None:
        return {}

    # Parse date: Telegram uses "2024-01-15T10:30:00" or Unix timestamp
    date_str = msg.get("date", "")
    if isinstance(date_str, (int, float)):
        date_str = datetime.fromtimestamp(date_str, tz=timezone.utc).isoformat()
    elif isinstance(date_str, str) and date_str.isdigit():
        date_str = datetime.fromtimestamp(int(date_str), tz=timezone.utc).isoformat()

    # Parse from_id: Telegram uses "user123" format
    from_id = msg.get("from_id", msg.get("from", ""))
    user_id = None
    if isinstance(from_id, str) and from_id.startswith("user"):
        try:
            user_id = int(from_id[4:])
        except ValueError:
            pass
    elif isinstance(from_id, int):
        user_id = from_id

    # Parse text: can be string or array of {text: "...", type: "..."}
    text = msg.get("text", "")
    if isinstance(text, list):
        text = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in text
        )

    return {
        "message_id": int(msg_id) if str(msg_id).isdigit() else msg_id,
        "type": msg.get("type", "message"),
        "date": date_str,
        "edit_date": msg.get("edited"),
        "content": text or "",
        "reply_to": msg.get("reply_to_message_id"),
        "user_id": user_id,
        "media_id": None,
        "checksum": None,
    }


def _import_telegram_export(
    target_conn: sqlite3.Connection,
    source_path: Path,
    *,
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> Dict[str, Any]:
    """Import from Telegram's Export History JSON format."""
    scanned = inserted = already_present = 0

    for msg in _iter_json_messages(source_path):
        if limit is not None and scanned >= limit:
            break

        payload = _convert_telegram_export(msg)
        if not payload or payload.get("message_id") is None:
            continue

        source_key = str(payload["message_id"])
        source_revision = f"tg-export-{source_key}-{_revision(payload)[:_REVISION_TRUNCATE]}"

        seq_id = IndexOutbox.append_to(
            target_conn,
            source_table="messages",
            source_key=source_key,
            event_type="upsert",
            payload=payload,
            source_revision=source_revision,
        )
        scanned += 1
        if seq_id is None:
            already_present += 1
        else:
            inserted += 1

        if chunk_size > 0 and scanned % chunk_size == 0:
            target_conn.commit()
            if progress_callback is not None:
                _notify_progress(progress_callback, scanned, inserted, already_present)

    target_conn.commit()
    if progress_callback is not None and (chunk_size <= 0 or scanned % chunk_size != 0):
        _notify_progress(progress_callback, scanned, inserted, already_present)

    return {
        "scanned": scanned,
        "inserted": inserted,
        "already_present": already_present,
        "source": str(source_path),
        "format": "telegram-export",
    }


# ── Validation ──────────────────────────────────────────────────────────────

def validate_import(
    source: Path | str,
    *,
    format: str = "auto",
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Validate import data without writing to the database.

    Checks:
      - File exists and is readable
      - Format is auto-detected correctly
      - Required fields are present
      - Record count matches expectations
      - No malformed records

    Returns:
        Dict with: valid, format, record_count, fields_found, errors, warnings
    """
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        return {"valid": False, "error": f"Source not found: {source_path}"}

    # Auto-detect format
    if format == "auto":
        suffix = source_path.suffix.lower()
        if suffix in (".db", ".sqlite", ".sqlite3"):
            format = "sqlite"
        elif suffix in (".json", ".ndjson"):
            format = "json"
        elif suffix == ".csv":
            format = "csv"
        else:
            try:
                first_bytes = source_path.read_bytes()[:16]
                if first_bytes.startswith(b"SQLite format 3"):
                    format = "sqlite"
                else:
                    with open(source_path, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read(1024).strip()
                    if text.startswith("{") or text.startswith("["):
                        format = "json"
                    else:
                        format = "csv"
            except Exception:
                format = "json"

    errors: list[str] = []
    warnings: list[str] = []
    record_count = 0
    fields_found: set[str] = set()

    if format == "sqlite":
        try:
            with sqlite3.connect(str(source_path)) as conn:
                conn.row_factory = sqlite3.Row
                tables = {
                    str(r[0]) for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                for table in _SQLITE_TABLE_MAP:
                    if table in tables:
                        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                        record_count += count
                        col_info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                        fields_found.update(col["name"] for col in col_info)
                if record_count == 0:
                    warnings.append("No records found in known tables")
                if progress_callback is not None:
                    _notify_progress(progress_callback, record_count, record_count, 0)
        except sqlite3.Error as e:
            errors.append(f"SQLite error: {e}")

    elif format in ("json", "telegram-export"):
        try:
            for msg in _iter_json_messages(source_path):
                if limit is not None and record_count >= limit:
                    break
                record_count += 1
                fields_found.update(msg.keys())
                if not msg.get("id") and not msg.get("message_id"):
                    errors.append(f"Record {record_count} missing id/message_id")
                    if len(errors) > 10:
                        errors.append("... (truncated)")
                        break
                if progress_callback is not None and record_count % _DEFAULT_CHUNK_SIZE == 0:
                    _notify_progress(progress_callback, record_count, record_count, 0)
            if progress_callback is not None and record_count % _DEFAULT_CHUNK_SIZE != 0:
                _notify_progress(progress_callback, record_count, record_count, 0)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            errors.append(f"JSON parse error: {e}")

    elif format == "csv":
        try:
            with open(source_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fields_found.update(reader.fieldnames or [])
                for row in reader:
                    if limit is not None and record_count >= limit:
                        break
                    record_count += 1
                    if not row.get("id") and not row.get("message_id"):
                        errors.append(f"Record {record_count} missing id/message_id")
                        if len(errors) > 10:
                            errors.append("... (truncated)")
                            break
                    if progress_callback is not None and record_count % _DEFAULT_CHUNK_SIZE == 0:
                        _notify_progress(progress_callback, record_count, record_count, 0)
                if progress_callback is not None and record_count % _DEFAULT_CHUNK_SIZE != 0:
                    _notify_progress(progress_callback, record_count, record_count, 0)
        except csv.Error as e:
            errors.append(f"CSV parse error: {e}")

    return {
        "valid": len(errors) == 0,
        "format": format,
        "record_count": record_count,
        "fields_found": sorted(fields_found),
        "errors": errors,
        "warnings": warnings,
        "source": str(source_path),
    }


# ── Batch Import ─────────────────────────────────────────────────────────────

def import_batch(
    target_db: Path | str,
    source_dir: Path | str,
    *,
    format: str = "auto",
    limit_per_file: Optional[int] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> Dict[str, Any]:
    """Import all data files from a directory.

    Walks the directory recursively, imports each .db/.json/.csv file found.
    """
    source_dir_path = Path(source_dir).expanduser().resolve()
    if not source_dir_path.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source_dir_path}")

    extensions = {".db", ".sqlite", ".sqlite3", ".json", ".ndjson", ".csv"}
    files = sorted(
        f for f in source_dir_path.rglob("*")
        if f.is_file() and f.suffix.lower() in extensions
    )

    total_scanned = total_inserted = total_already = 0
    file_results = []

    for f in files:
        try:
            result = import_data(
                target_db=target_db,
                source=f,
                format=format,
                limit=limit_per_file,
                progress_callback=progress_callback,
                chunk_size=chunk_size,
            )
            total_scanned += result["scanned"]
            total_inserted += result["inserted"]
            total_already += result["already_present"]
            file_results.append({
                "file": str(f),
                "scanned": result["scanned"],
                "inserted": result["inserted"],
                "already_present": result["already_present"],
            })
            logger.info("Batch: %s — %d inserted", f.name, result["inserted"])
        except Exception as e:
            file_results.append({
                "file": str(f),
                "error": str(e),
            })
            logger.warning("Batch: %s failed: %s", f.name, e)

    return {
        "files_processed": len(files),
        "files_succeeded": sum(1 for r in file_results if "error" not in r),
        "files_failed": sum(1 for r in file_results if "error" in r),
        "total_scanned": total_scanned,
        "total_inserted": total_inserted,
        "total_already_present": total_already,
        "source_dir": str(source_dir_path),
        "files": file_results,
    }


# ── Import Resume ────────────────────────────────────────────────────────────

_IMPORT_CHECKPOINT_TABLE = "import_checkpoints"


def _ensure_checkpoint_table(conn: sqlite3.Connection) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_IMPORT_CHECKPOINT_TABLE} (
            source_path TEXT NOT NULL,
            last_position INTEGER NOT NULL DEFAULT 0,
            records_imported INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (source_path)
        )
    """)


def _get_checkpoint(conn: sqlite3.Connection, source_path: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        f"SELECT last_position, records_imported, updated_at FROM {_IMPORT_CHECKPOINT_TABLE} WHERE source_path = ?",
        (source_path,),
    ).fetchone()
    if row:
        return {"last_position": row[0], "records_imported": row[1], "updated_at": row[2]}
    return None


def _update_checkpoint(conn: sqlite3.Connection, source_path: str, position: int, imported: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        f"""
        INSERT INTO {_IMPORT_CHECKPOINT_TABLE} (source_path, last_position, records_imported, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source_path) DO UPDATE SET
            last_position = excluded.last_position,
            records_imported = excluded.records_imported,
            updated_at = excluded.updated_at
        """,
        (source_path, position, imported, now),
    )


def import_with_resume(
    target_db: Path | str,
    source: Path | str,
    *,
    format: str = "auto",
    limit: Optional[int] = None,
    resume: bool = False,
    progress_callback: Optional[Callable[..., Any]] = None,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> Dict[str, Any]:
    """Import with checkpoint-based resume for interrupted imports.

    Tracks progress in an import_checkpoints table so large imports that
    are interrupted can be resumed from the last checkpoint.

    Args:
        target_db: Target SPECTRA database.
        source: Source file to import.
        format: Import format (auto, sqlite, json, csv, telegram-export).
        limit: Max records to import in this run.
        resume: If True, resume from last checkpoint.
        progress_callback: Optional callback invoked with progress (scanned, inserted, already_present).
        chunk_size: Number of records per chunk/commit (default: 1000).
    """
    target_path = Path(target_db).expanduser().resolve()
    source_path = Path(source).expanduser().resolve()
    source_str = str(source_path)

    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    # Auto-detect format
    if format == "auto":
        suffix = source_path.suffix.lower()
        if suffix in (".db", ".sqlite", ".sqlite3"):
            format = "sqlite"
        elif suffix in (".json", ".ndjson"):
            format = "json"
        elif suffix == ".csv":
            format = "csv"
        else:
            try:
                first_bytes = source_path.read_bytes()[:16]
                if first_bytes.startswith(b"SQLite format 3"):
                    format = "sqlite"
                else:
                    with open(source_path, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read(1024).strip()
                    if text.startswith("{") or text.startswith("["):
                        format = "json"
                    else:
                        format = "csv"
            except Exception:
                format = "json"

    skip_count = 0
    with connect_sqlite(target_path) as target_conn:
        IndexOutbox.ensure_schema(target_conn)
        _ensure_checkpoint_table(target_conn)

        if resume:
            checkpoint = _get_checkpoint(target_conn, source_str)
            if checkpoint:
                skip_count = checkpoint["last_position"]
                logger.info(
                    "Resuming import from checkpoint: position=%d, imported=%d",
                    checkpoint["last_position"], checkpoint["records_imported"],
                )

        scanned = inserted = already_present = 0
        records_iterated = 0
        remaining_to_skip = skip_count

        if format in ("json", "telegram-export"):
            converter = _convert_telegram_export if format == "telegram-export" else None
            for msg in _iter_json_messages(source_path):
                if remaining_to_skip > 0:
                    remaining_to_skip -= 1
                    records_iterated += 1
                    continue
                if limit is not None and scanned >= limit:
                    break
                records_iterated += 1

                if converter:
                    payload = converter(msg)
                else:
                    msg_id = msg.get("id") if msg.get("id") is not None else msg.get("message_id")
                    if msg_id is None:
                        continue
                    payload = {
                        "message_id": int(msg_id) if str(msg_id).isdigit() else msg_id,
                        "type": msg.get("type", "text"),
                        "date": msg.get("date", datetime.now(timezone.utc).isoformat()),
                        "edit_date": msg.get("edit_date"),
                        "content": msg.get("content") or msg.get("text") or "",
                        "reply_to": msg.get("reply_to"),
                        "user_id": msg.get("user_id") if msg.get("user_id") is not None else msg.get("from_id"),
                        "media_id": msg.get("media_id"),
                        "checksum": msg.get("checksum"),
                    }
                    if "channel_id" in msg:
                        payload["channel_id"] = msg["channel_id"]

                if not payload or payload.get("message_id") is None:
                    continue

                source_key = str(payload["message_id"])
                source_revision = f"{format}-{source_key}-{_revision(payload)[:_REVISION_TRUNCATE]}"
                seq_id = IndexOutbox.append_to(
                    target_conn,
                    source_table="messages",
                    source_key=source_key,
                    event_type="upsert",
                    payload=payload,
                    source_revision=source_revision,
                )
                scanned += 1
                if seq_id is None:
                    already_present += 1
                else:
                    inserted += 1

                # Checkpoint and commit every chunk_size records
                if chunk_size > 0 and scanned % chunk_size == 0:
                    _update_checkpoint(target_conn, source_str, records_iterated, inserted)
                    target_conn.commit()
                    if progress_callback is not None:
                        _notify_progress(progress_callback, scanned, inserted, already_present)

        elif format == "csv":
            with open(source_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if remaining_to_skip > 0:
                        remaining_to_skip -= 1
                        records_iterated += 1
                        continue
                    if limit is not None and scanned >= limit:
                        break
                    records_iterated += 1

                    msg_id = row.get("id") if row.get("id") is not None else row.get("message_id")
                    if not msg_id:
                        continue

                    payload = {
                        "message_id": int(msg_id) if str(msg_id).isdigit() else msg_id,
                        "type": row.get("type", "text"),
                        "date": row.get("date", datetime.now(timezone.utc).isoformat()),
                        "edit_date": row.get("edit_date"),
                        "content": row.get("content") or row.get("text") or "",
                        "reply_to": int(row["reply_to"]) if row.get("reply_to") else None,
                        "user_id": int(row["user_id"]) if row.get("user_id") else None,
                        "media_id": int(row["media_id"]) if row.get("media_id") else None,
                        "checksum": row.get("checksum"),
                    }
                    if "channel_id" in row:
                        payload["channel_id"] = int(row["channel_id"]) if row.get("channel_id") else None

                    source_key = str(payload["message_id"])
                    source_revision = f"csv-{source_key}-{_revision(payload)[:_REVISION_TRUNCATE]}"
                    seq_id = IndexOutbox.append_to(
                        target_conn,
                        source_table="messages",
                        source_key=source_key,
                        event_type="upsert",
                        payload=payload,
                        source_revision=source_revision,
                    )
                    scanned += 1
                    if seq_id is None:
                        already_present += 1
                    else:
                        inserted += 1

                    if chunk_size > 0 and scanned % chunk_size == 0:
                        _update_checkpoint(target_conn, source_str, records_iterated, inserted)
                        target_conn.commit()
                        if progress_callback is not None:
                            _notify_progress(progress_callback, scanned, inserted, already_present)

        elif format == "sqlite":
            result = _import_sqlite(
                target_conn,
                source_path,
                limit=limit,
                progress_callback=progress_callback,
                chunk_size=chunk_size,
            )
            scanned = result["scanned"]
            inserted = result["inserted"]
            already_present = result["already_present"]
            records_iterated = scanned

        # Final checkpoint and commit
        _update_checkpoint(target_conn, source_str, records_iterated, inserted)
        target_conn.commit()
        if progress_callback is not None and (chunk_size <= 0 or scanned % chunk_size != 0):
            _notify_progress(progress_callback, scanned, inserted, already_present)

    return {
        "scanned": scanned,
        "inserted": inserted,
        "already_present": already_present,
        "skipped_for_resume": skip_count,
        "source": str(source_path),
        "target": str(target_path),
        "format": format,
        "resumed": resume and skip_count > 0,
    }


__all__ = ["import_data", "validate_import", "import_batch", "import_with_resume"]
