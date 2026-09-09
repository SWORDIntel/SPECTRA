"""
Error Store — QIHSE error projection capture
============================================

Records structured errors into the IndexOutbox so they are projected into
the dedicated ``qihse.errors.v1`` QIHSE field.  Every error captured here
flows through the same durable outbox → IndexProjector pipeline as all
other SPECTRA data, making errors searchable alongside content, graph,
and event data.

Usage (library)::

    from tgarchive.db.error_store import record_error

    record_error(
        connection,
        error_code=500,
        category="download",
        message="FloodWait: must wait 300s",
        context={"channel_id": -100123, "account": "spectra_tdata_1"},
    )

Usage (standalone)::

    from tgarchive.db.error_store import ErrorStore
    store = ErrorStore("spectra.db")
    store.record(error_code=404, category="archive", message="channel not found")
    stats = store.stats()
"""

from __future__ import annotations

import json
import logging
import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .index_outbox import IndexOutbox

logger = logging.getLogger(__name__)

ERROR_SOURCE_TABLE = "errors"
ERROR_REVISION = "error-v1"


def record_error(
    connection: sqlite3.Connection,
    *,
    error_code: int,
    category: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
    operation_id: Optional[str] = None,
    traceback_text: Optional[str] = None,
) -> int | None:
    """Append a structured error to the IndexOutbox for QIHSE projection.

    Args:
        connection: Live SQLite connection (from SpectraDB or IndexOutbox).
        error_code: Numeric error code (HTTP-style or custom).
        category: Error category (e.g. ``"download"``, ``"archive"``, ``"search"``).
        message: Human-readable error message.
        context: Optional dict with extra context (channel_id, account, etc.).
        operation_id: Optional operation ID that triggered the error.
        traceback_text: Optional Python traceback string.

    Returns:
        The outbox sequence_id if a new row was inserted, ``None`` if deduped.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    payload: Dict[str, Any] = {
        "error_code": error_code,
        "category": category,
        "error_message": message,
        "timestamp": timestamp,
    }
    if context:
        payload["context"] = context
    if operation_id:
        payload["operation_id"] = operation_id
    if traceback_text:
        # Store truncated traceback (max 4KB to keep payload reasonable)
        payload["traceback"] = traceback_text[:4096]

    # Dedup key: hash of category + message + context (without timestamp)
    dedup_source = f"{category}:{message}:{json.dumps(context or {}, sort_keys=True)}"
    source_key = hashlib.sha256(dedup_source.encode("utf-8")).hexdigest()[:16]

    seq_id = IndexOutbox.append_to(
        connection,
        source_table=ERROR_SOURCE_TABLE,
        source_key=source_key,
        event_type="error",
        payload=payload,
        source_revision=ERROR_REVISION,
    )
    if seq_id:
        logger.debug(
            "Error recorded to outbox: [%s:%d] %s (seq=%d)",
            category, error_code, message, seq_id,
        )
    return seq_id


class ErrorStore:
    """Standalone error store that manages its own SQLite connection."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            IndexOutbox.ensure_schema(self._conn)
        return self._conn

    def record(
        self,
        *,
        error_code: int,
        category: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        operation_id: Optional[str] = None,
        traceback_text: Optional[str] = None,
    ) -> int | None:
        """Record an error and commit."""
        conn = self._connection()
        seq = record_error(
            conn,
            error_code=error_code,
            category=category,
            message=message,
            context=context,
            operation_id=operation_id,
            traceback_text=traceback_text,
        )
        conn.commit()
        return seq

    def stats(self) -> Dict[str, Any]:
        """Return error statistics from the outbox."""
        conn = self._connection()
        rows = conn.execute(
            """
            SELECT
                json_extract(payload_json, '$.category') AS category,
                json_extract(payload_json, '$.error_code') AS code,
                COUNT(*) AS count
            FROM index_outbox
            WHERE source_table = ?
            GROUP BY category, code
            ORDER BY count DESC
            """,
            (ERROR_SOURCE_TABLE,),
        ).fetchall()
        return {
            "total": sum(r[2] for r in rows),
            "breakdown": [
                {"category": r[0], "code": r[1], "count": r[2]}
                for r in rows
            ],
        }

    def recent(self, limit: int = 50) -> list[Dict[str, Any]]:
        """Return recent errors from the outbox."""
        conn = self._connection()
        rows = conn.execute(
            """
            SELECT sequence_id, payload_json, created_at
            FROM index_outbox
            WHERE source_table = ?
            ORDER BY sequence_id DESC
            LIMIT ?
            """,
            (ERROR_SOURCE_TABLE, limit),
        ).fetchall()
        results = []
        for row in rows:
            payload = json.loads(row[1])
            payload["sequence_id"] = row[0]
            payload["recorded_at"] = row[2]
            results.append(payload)
        return results

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self._connection()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
