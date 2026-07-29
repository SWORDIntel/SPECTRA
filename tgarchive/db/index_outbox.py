"""Durable change notifications for derived index projections."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..sqlite_runtime import connect_sqlite

MAX_DELIVERY_ATTEMPTS = 5


class OutboxLeaseLostError(RuntimeError):
    """Raised when a stale worker tries to acknowledge a reclaimed event."""


class IndexOutbox:
    """Append-only, idempotent queue shared by SQLite and index workers."""

    def __init__(self, database: Path | str) -> None:
        self.database = Path(database)
        with connect_sqlite(self.database) as connection:
            self.ensure_schema(connection)

    def _connection(self) -> sqlite3.Connection:
        connection = connect_sqlite(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS index_outbox (
                sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_table TEXT NOT NULL,
                source_key TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source_revision TEXT,
                created_at TEXT NOT NULL,
                claimed_at TEXT,
                claim_token TEXT,
                processed_at TEXT,
                error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                UNIQUE(source_table, source_key, event_type, source_revision)
            );
            CREATE INDEX IF NOT EXISTS idx_index_outbox_pending
                ON index_outbox(processed_at, claimed_at, sequence_id);
            CREATE TABLE IF NOT EXISTS index_projection_state (
                projection_name TEXT PRIMARY KEY,
                projection_version TEXT NOT NULL,
                last_sequence_id INTEGER NOT NULL DEFAULT 0,
                source_checksum TEXT,
                row_count INTEGER NOT NULL DEFAULT 0,
                last_success_at TEXT,
                last_error TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(index_outbox)").fetchall()
        }
        if "claim_token" not in columns:
            connection.execute("ALTER TABLE index_outbox ADD COLUMN claim_token TEXT")

    def append(
        self,
        *,
        source_table: str,
        source_key: str,
        event_type: str,
        payload: dict[str, Any],
        source_revision: str | None = None,
    ) -> int | None:
        with self._connection() as connection:
            return self.append_to(
                connection,
                source_table=source_table,
                source_key=source_key,
                event_type=event_type,
                payload=payload,
                source_revision=source_revision,
            )

    @staticmethod
    def append_to(
        connection: sqlite3.Connection,
        *,
        source_table: str,
        source_key: str,
        event_type: str,
        payload: dict[str, Any],
        source_revision: str | None = None,
    ) -> int | None:
        fields = (source_table, source_key, event_type)
        if any(not isinstance(value, str) or not value.strip() for value in fields):
            raise ValueError("source_table, source_key, and event_type must be non-empty strings")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")
        payload_json = json.dumps(payload, default=str, sort_keys=True)
        revision = source_revision or hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            """
            INSERT INTO index_outbox
                (source_table, source_key, event_type, payload_json, source_revision, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_table, source_key, event_type, source_revision) DO NOTHING
            """,
            (*fields, payload_json, revision, now),
        )
        return int(cursor.lastrowid) if cursor.rowcount else None

    def claim(
        self,
        *,
        batch_size: int = 100,
        lease_seconds: int = 300,
        max_attempts: int = MAX_DELIVERY_ATTEMPTS,
    ) -> list[dict[str, Any]]:
        if batch_size < 1 or lease_seconds < 1 or max_attempts < 1:
            raise ValueError("batch_size, lease_seconds, and max_attempts must be positive")
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=lease_seconds)).isoformat()
        claimed_at = now.isoformat()
        claim_token = uuid.uuid4().hex
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM index_outbox
                WHERE processed_at IS NULL
                  AND attempts < ?
                  AND (claimed_at IS NULL OR claimed_at < ?)
                ORDER BY sequence_id
                LIMIT ?
                """,
                (max_attempts, cutoff, batch_size),
            ).fetchall()
            if not rows:
                connection.commit()
                return []
            ids = [int(row["sequence_id"]) for row in rows]
            connection.executemany(
                """
                UPDATE index_outbox
                SET claimed_at=?, claim_token=?, attempts=attempts+1
                WHERE sequence_id=?
                """,
                [(claimed_at, claim_token, sequence_id) for sequence_id in ids],
            )
            connection.commit()
            return [
                dict(row)
                | {
                    "claimed_at": claimed_at,
                    "claim_token": claim_token,
                    "payload": json.loads(row["payload_json"]),
                }
                for row in rows
            ]

    def events(self, *, after_sequence: int = 0, limit: int | None = None) -> list[dict[str, Any]]:
        if after_sequence < 0 or (limit is not None and limit < 1):
            raise ValueError("after_sequence must be non-negative and limit must be positive")
        sql = "SELECT * FROM index_outbox WHERE sequence_id > ? ORDER BY sequence_id"
        parameters: tuple[Any, ...] = (after_sequence,)
        if limit is not None:
            sql += " LIMIT ?"
            parameters += (limit,)
        with self._connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload_json"])} for row in rows]

    def complete(
        self,
        sequence_id: int,
        *,
        claim_token: str,
        error: str | None = None,
    ) -> None:
        if sequence_id < 1:
            raise ValueError("sequence_id must be positive")
        if not isinstance(claim_token, str) or not claim_token:
            raise ValueError("claim_token must be a non-empty string")
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE index_outbox
                SET processed_at=?, claimed_at=NULL, claim_token=NULL, error=?
                WHERE sequence_id=? AND claim_token=? AND processed_at IS NULL
                """,
                (now if error is None else None, error, sequence_id, claim_token),
            )
            if cursor.rowcount == 0:
                if connection.execute(
                    "SELECT 1 FROM index_outbox WHERE sequence_id=?",
                    (sequence_id,),
                ).fetchone() is None:
                    raise KeyError(f"Unknown index outbox sequence: {sequence_id}")
                raise OutboxLeaseLostError(
                    f"Index outbox lease is no longer owned: {sequence_id}"
                )

    def complete_batch(
        self,
        results: dict[int, str | None],
        *,
        claim_tokens: dict[int, str],
    ) -> None:
        """Acknowledge one projected batch in a single SQLite transaction."""
        if not isinstance(results, dict):
            raise TypeError("results must be a sequence-to-error mapping")
        if any(not isinstance(sequence_id, int) or sequence_id < 1 for sequence_id in results):
            raise ValueError("sequence IDs must be positive integers")
        if any(error is not None and not isinstance(error, str) for error in results.values()):
            raise TypeError("batch errors must be strings or None")
        if set(claim_tokens) != set(results):
            raise ValueError("claim_tokens must cover exactly the completed sequence IDs")
        if any(not isinstance(token, str) or not token for token in claim_tokens.values()):
            raise ValueError("claim tokens must be non-empty strings")
        if not results:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            for sequence_id, error in results.items():
                cursor = connection.execute(
                    """
                    UPDATE index_outbox
                    SET processed_at=?, claimed_at=NULL, claim_token=NULL, error=?
                    WHERE sequence_id=? AND claim_token=? AND processed_at IS NULL
                    """,
                    (
                        now if error is None else None,
                        error,
                        sequence_id,
                        claim_tokens[sequence_id],
                    ),
                )
                if cursor.rowcount == 0:
                    if connection.execute(
                        "SELECT 1 FROM index_outbox WHERE sequence_id=?",
                        (sequence_id,),
                    ).fetchone() is None:
                        raise KeyError(f"Unknown index outbox sequence: {sequence_id}")
                    raise OutboxLeaseLostError(
                        f"Index outbox lease is no longer owned: {sequence_id}"
                    )

    def status(self) -> dict[str, Any]:
        with self._connection() as connection:
            counts = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(processed_at IS NULL AND claimed_at IS NULL AND attempts < ?) AS pending,
                    SUM(processed_at IS NULL AND claimed_at IS NOT NULL) AS claimed,
                    SUM(processed_at IS NOT NULL) AS processed,
                    SUM(processed_at IS NULL AND error IS NOT NULL AND attempts >= ?) AS failed
                FROM index_outbox
                """,
                (MAX_DELIVERY_ATTEMPTS, MAX_DELIVERY_ATTEMPTS),
            ).fetchone()
            projections = [dict(row) for row in connection.execute(
                "SELECT * FROM index_projection_state ORDER BY projection_name"
            ).fetchall()]
        return {
            "database": str(self.database),
            "outbox": {key: int(counts[key] or 0) for key in ("total", "pending", "claimed", "processed", "failed")},
            "projections": projections,
        }
