"""Backfill safe typed-record metadata from existing SQLite tables into the index outbox."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from ..db.index_outbox import IndexOutbox
from ..sqlite_runtime import connect_sqlite
from .utils import revision_hash as _revision


RowPayload = Callable[[sqlite3.Row], dict[str, Any]]
RowValue = Callable[[sqlite3.Row], str]


def _minimal(row: sqlite3.Row, *fields: str) -> dict[str, Any]:
    return {field: row[field] for field in fields if field in row.keys()}


_TABLES: dict[str, tuple[str, RowValue, RowPayload, RowValue]] = {
    "messages": (
        "id",
        lambda _row: "upsert",
        lambda row: {
            "message_id": row["id"],
            **_minimal(
                row,
                "type",
                "date",
                "edit_date",
                "content",
                "reply_to",
                "user_id",
                "media_id",
                "checksum",
            ),
        },
        lambda row: f"msg-{row['id']}-{row['checksum'] if 'checksum' in row.keys() else 'nocs'}",
    ),
    "users": (
        "id",
        lambda _row: "upsert",
        lambda row: {
            "user_id": row["id"],
            **_minimal(row, "username", "first_name", "last_name", "tags", "avatar"),
        },
        lambda row: f"user-{row['id']}",
    ),
    "media": (
        "id",
        lambda _row: "upsert",
        lambda row: {
            "media_id": row["id"],
            **_minimal(row, "type", "url", "title", "description", "checksum"),
        },
        lambda row: f"media-{row['id']}",
    ),
    "checkpoints": (
        "id",
        lambda _row: "save",
        lambda row: {
            "checkpoint_id": row["id"],
            **_minimal(row, "last_message_id", "checkpoint_time", "context"),
        },
        lambda row: str(row["checkpoint_time"]),
    ),
    "operation_events": (
        "id",
        lambda row: str(row["event"]),
        lambda row: {
            "event_id": row["id"],
            **_minimal(row, "operation_id", "event", "progress", "timestamp"),
        },
        lambda row: str(row["timestamp"]),
    ),
    "operation_audit_log": (
        "id",
        lambda row: str(row["action"]),
        lambda row: {
            "event_id": row["id"],
            **_minimal(row, "operation_id", "action", "user", "timestamp"),
        },
        lambda row: str(row["timestamp"]),
    ),
    "task_events": (
        "event_id",
        lambda row: str(row["status"] or "event"),
        lambda row: _minimal(
            row,
            "event_id",
            "task_id",
            "kind",
            "status",
            "pid",
            "event_at",
        ),
        lambda row: str(row["event_at"]),
    ),
}


def backfill_database_records(
    database: Path | str,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Append missing safe checkpoint/event records from known durable tables."""
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    database_path = Path(database).expanduser().resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {database_path}")

    scanned = inserted = already_present = 0
    by_table: dict[str, dict[str, int]] = {}
    with connect_sqlite(database_path) as connection:
        connection.row_factory = sqlite3.Row
        existing_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        IndexOutbox.ensure_schema(connection)
        for table, (key_column, event_type_builder, payload_builder, revision_builder) in _TABLES.items():
            if table not in existing_tables or (limit is not None and scanned >= limit):
                continue
            table_scanned = table_inserted = 0
            remaining = None if limit is None else limit - scanned
            sql = f'SELECT * FROM "{table}" ORDER BY "{key_column}"'
            parameters: tuple[Any, ...] = ()
            if remaining is not None:
                sql += " LIMIT ?"
                parameters = (remaining,)
            for row in connection.execute(sql, parameters):
                payload = payload_builder(row)
                source_key = str(row[key_column])
                event_type = event_type_builder(row)
                source_revision = revision_builder(row)
                sequence_id = IndexOutbox.append_to(
                    connection,
                    source_table=table,
                    source_key=source_key,
                    event_type=event_type,
                    payload=payload,
                    source_revision=source_revision or _revision(payload),
                )
                scanned += 1
                table_scanned += 1
                if sequence_id is None:
                    already_present += 1
                else:
                    inserted += 1
                    table_inserted += 1
            by_table[table] = {
                "scanned": table_scanned,
                "inserted": table_inserted,
                "already_present": table_scanned - table_inserted,
            }
        connection.commit()
    return {
        "database": str(database_path),
        "scanned": scanned,
        "inserted": inserted,
        "already_present": already_present,
        "tables": by_table,
    }


__all__ = ["backfill_database_records"]
