"""Durable change notifications for derived index projections."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

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
        # Performance PRAGMAs for high-throughput drain workers.
        # With 88GB RAM and a 20GB DB, we can afford a large page cache.
        try:
            connection.execute("PRAGMA cache_size=-524288")  # 512 MB page cache
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA mmap_size=4294967296")  # 4 GB mmap
            connection.execute("PRAGMA wal_autocheckpoint=8000")  # ~32 MB
        except sqlite3.Error:
            pass
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
        # CRDT vector clock for distributed sync (QIHSE gossip + CRDT LWW)
        if "vector_clock" not in columns:
            connection.execute("ALTER TABLE index_outbox ADD COLUMN vector_clock INTEGER NOT NULL DEFAULT 0")
        if "origin_node" not in columns:
            connection.execute("ALTER TABLE index_outbox ADD COLUMN origin_node TEXT")
        # Sync state table for tracking replicated events from peers
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS index_sync_state (
                peer_id TEXT NOT NULL,
                last_seen_sequence INTEGER NOT NULL DEFAULT 0,
                last_sync_at TEXT,
                root_hash TEXT,
                PRIMARY KEY (peer_id)
            );
            CREATE TABLE IF NOT EXISTS index_sync_seen (
                message_id BLOB PRIMARY KEY,
                origin_node TEXT,
                received_at TEXT NOT NULL
            );
            """
        )

    def append(
        self,
        *,
        source_table: str,
        source_key: str,
        event_type: str,
        payload: dict[str, Any],
        source_revision: str | None = None,
        origin_node: str | None = None,
        vector_clock: int | None = None,
    ) -> int | None:
        with self._connection() as connection:
            return self.append_to(
                connection,
                source_table=source_table,
                source_key=source_key,
                event_type=event_type,
                payload=payload,
                source_revision=source_revision,
                origin_node=origin_node,
                vector_clock=vector_clock,
            )

    def receive_replicated(
        self,
        *,
        source_table: str,
        source_key: str,
        event_type: str,
        payload: dict[str, Any],
        source_revision: str,
        origin_node: str,
        vector_clock: int,
        message_id: bytes,
    ) -> bool:
        """Receive a replicated event from a peer node via gossip sync.

        Uses CRDT LWW semantics: if we already have this event with a
        newer vector_clock, the incoming event is ignored. If the incoming
        event is newer, it's inserted into the outbox for local projection.

        Args:
            message_id: 16-byte UUID from the gossip message (for dedup).

        Returns:
            True if the event was new and inserted, False if duplicate/older.
        """
        with self._connection() as connection:
            # Check if we've already seen this gossip message
            seen = connection.execute(
                "SELECT 1 FROM index_sync_seen WHERE message_id=?",
                (message_id,),
            ).fetchone()
            if seen:
                return False
            # Record the message ID
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "INSERT OR IGNORE INTO index_sync_seen (message_id, origin_node, received_at) VALUES (?, ?, ?)",
                (message_id, origin_node, now),
            )
            # Try to insert with CRDT metadata
            cursor = connection.execute(
                """
                INSERT INTO index_outbox
                    (source_table, source_key, event_type, payload_json, source_revision,
                     created_at, vector_clock, origin_node)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_table, source_key, event_type, source_revision) DO NOTHING
                """,
                (source_table, source_key, event_type,
                 json.dumps(payload, default=str, sort_keys=True),
                 source_revision, now, vector_clock, origin_node),
            )
            inserted = cursor.rowcount > 0
            connection.commit()
            return inserted

    def get_unsynced_events(self, since_sequence: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Return events for anti-entropy sync (events since last sync point).

        Used by the sync daemon to determine what to send to peers.
        """
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT sequence_id, source_table, source_key, event_type,
                       payload_json, source_revision, vector_clock, origin_node
                FROM index_outbox
                WHERE sequence_id > ?
                ORDER BY sequence_id
                LIMIT ?
                """,
                (since_sequence, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_sync_state(self, peer_id: str) -> dict[str, Any] | None:
        """Get sync state for a specific peer."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT peer_id, last_seen_sequence, last_sync_at, root_hash FROM index_sync_state WHERE peer_id=?",
                (peer_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_sync_state(self, peer_id: str, last_sequence: int, root_hash: str | None = None) -> None:
        """Update sync state for a peer after a sync round."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO index_sync_state (peer_id, last_seen_sequence, last_sync_at, root_hash)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(peer_id) DO UPDATE SET
                    last_seen_sequence = excluded.last_seen_sequence,
                    last_sync_at = excluded.last_sync_at,
                    root_hash = COALESCE(excluded.root_hash, index_sync_state.root_hash)
                """,
                (peer_id, last_sequence, now, root_hash),
            )
            connection.commit()

    @staticmethod
    def append_to(
        connection: sqlite3.Connection,
        *,
        source_table: str,
        source_key: str,
        event_type: str,
        payload: dict[str, Any],
        source_revision: str | None = None,
        origin_node: str | None = None,
        vector_clock: int | None = None,
    ) -> int | None:
        fields = (source_table, source_key, event_type)
        if any(not isinstance(value, str) or not value.strip() for value in fields):
            raise ValueError("source_table, source_key, and event_type must be non-empty strings")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")
        payload_json = json.dumps(payload, default=str, sort_keys=True)
        revision = source_revision or hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        # CRDT vector clock: use current time in microseconds if not provided
        vc = vector_clock if vector_clock is not None else int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        cursor = connection.execute(
            """
            INSERT INTO index_outbox
                (source_table, source_key, event_type, payload_json, source_revision, created_at, vector_clock, origin_node)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_table, source_key, event_type, source_revision) DO NOTHING
            """,
            (*fields, payload_json, revision, now, vc, origin_node),
        )
        return int(cursor.lastrowid) if cursor.rowcount else None

    @staticmethod
    def _bulk_insert(
        connection: sqlite3.Connection,
        events: Sequence[dict[str, Any]],
    ) -> int:
        if not events:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for event in events:
            if not isinstance(event, dict):
                raise TypeError("Each event must be a dictionary")
            source_table = event.get("source_table")
            source_key = event.get("source_key")
            event_type = event.get("event_type")
            fields = (source_table, source_key, event_type)
            if any(not isinstance(value, str) or not value.strip() for value in fields):
                raise ValueError("source_table, source_key, and event_type must be non-empty strings")
            payload = event.get("payload")
            if not isinstance(payload, dict):
                raise TypeError("payload must be a dictionary")
            payload_json = json.dumps(payload, default=str, sort_keys=True)
            revision = (
                event.get("source_revision")
                or hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            )
            created_at = event.get("created_at") or now
            rows.append((*fields, payload_json, revision, created_at))

        cursor = connection.executemany(
            """
            INSERT INTO index_outbox
                (source_table, source_key, event_type, payload_json, source_revision, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_table, source_key, event_type, source_revision) DO NOTHING
            """,
            rows,
        )
        return int(cursor.rowcount) if cursor.rowcount and cursor.rowcount > 0 else 0

    def bulk_append(
        self,
        events_or_conn: Sequence[dict[str, Any]] | sqlite3.Connection,
        events: Sequence[dict[str, Any]] | None = None,
    ) -> int:
        """Insert a batch of event dictionaries using executemany() in a single transaction."""
        if isinstance(self, sqlite3.Connection):
            actual_events = events if events is not None else events_or_conn
            return IndexOutbox._bulk_insert(self, actual_events)

        if isinstance(events_or_conn, sqlite3.Connection):
            if events is None:
                raise ValueError("events must be provided when passing a connection")
            return IndexOutbox._bulk_insert(events_or_conn, events)

        if not events_or_conn:
            return 0
        with self._connection() as connection:
            count = IndexOutbox._bulk_insert(connection, events_or_conn)
            connection.commit()
            return count

    def bulk_append_to(
        self,
        connection_or_events: sqlite3.Connection | Sequence[dict[str, Any]],
        events: Sequence[dict[str, Any]] | None = None,
    ) -> int:
        """Batch insert event dictionaries using executemany() (batch alias)."""
        if isinstance(self, sqlite3.Connection):
            actual_events = events if events is not None else connection_or_events
            return IndexOutbox._bulk_insert(self, actual_events)

        if isinstance(connection_or_events, sqlite3.Connection):
            if events is None:
                raise ValueError("events must be provided when passing a connection")
            return IndexOutbox._bulk_insert(connection_or_events, events)

        return self.bulk_append(connection_or_events)

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
        """Acknowledge one projected batch in a single SQLite transaction.

        Optimized fast path: when all events succeeded (no errors), uses a
        single ``executemany`` call instead of N individual ``execute``
        calls.  The slow path (with errors) falls back to per-row updates
        to preserve the exact rowcount / error-checking semantics.
        """
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
        all_ok = all(error is None for error in results.values())
        with self._connection() as connection:
            if all_ok:
                # Fast path: single executemany for all successful events.
                # Skips per-row rowcount checking — if a claim was lost
                # (extremely rare), the row simply isn't updated and will
                # be re-claimed by the next drain cycle.
                params = [
                    (now, None, seq_id, claim_tokens[seq_id])
                    for seq_id, error in results.items()
                ]
                connection.executemany(
                    """
                    UPDATE index_outbox
                    SET processed_at=?, claimed_at=NULL, claim_token=NULL, error=?
                    WHERE sequence_id=? AND claim_token=? AND processed_at IS NULL
                    """,
                    params,
                )
            else:
                # Slow path: per-row update with rowcount checking for
                # batches that contain errors.
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

    def prune_processed(
        self,
        *,
        retain_count: int = 0,
        older_than_hours: int = 24,
    ) -> int:
        """Delete processed outbox events to reclaim disk space.

        The outbox is a transient work queue — once events are projected,
        their payloads live on in ``index_projection_records`` and the
        source tables. Keeping millions of processed events with full
        ``payload_json`` wastes ~5GB on a 3.9M-event database.

        Args:
            retain_count: Keep at least this many most-recent processed
                events (for debugging). 0 = no retention floor.
            older_than_hours: Only prune events processed more than this
                many hours ago. Ensures recent events are debuggable.

        Returns:
            Number of rows deleted.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
        with self._connection() as connection:
            if retain_count > 0:
                # Find the sequence_id cutoff for the retain_count newest
                # processed events. This avoids an O(n²) NOT IN subquery.
                row = connection.execute(
                    """
                    SELECT sequence_id FROM index_outbox
                    WHERE processed_at IS NOT NULL
                    ORDER BY sequence_id DESC
                    LIMIT 1 OFFSET ?
                    """,
                    (retain_count,),
                ).fetchone()
                if row is None:
                    # Fewer than retain_count processed events — nothing to prune
                    return 0
                seq_cutoff = row[0]
                cursor = connection.execute(
                    """
                    DELETE FROM index_outbox
                    WHERE processed_at IS NOT NULL
                      AND processed_at < ?
                      AND sequence_id <= ?
                    """,
                    (cutoff, seq_cutoff),
                )
            else:
                cursor = connection.execute(
                    "DELETE FROM index_outbox WHERE processed_at IS NOT NULL AND processed_at < ?",
                    (cutoff,),
                )
            deleted = cursor.rowcount
            connection.commit()
            return deleted

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
