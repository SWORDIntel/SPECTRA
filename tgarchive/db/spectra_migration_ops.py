"""
SPECTRA-004 Migration Operations
================================
Operations for tracking content migration progress.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class MigrationOperations:
    """Operations for tracking migration progress."""

    def __init__(self, db):
        self.db = db
        self.cur = db.cur
        self._exec_retry = db._exec_retry

    def add_migration_progress(self, source: str, destination: str, status: str) -> int:
        self._exec_retry(
            "INSERT INTO migration_progress(source, destination, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (source, destination, status, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        self.db.commit()
        return self.cur.lastrowid

    def update_migration_progress(self, migration_id: int, last_message_id: int, status: str) -> None:
        self._exec_retry(
            "UPDATE migration_progress SET last_message_id = ?, status = ?, updated_at = ? WHERE id = ?",
            (last_message_id, status, datetime.now(timezone.utc).isoformat(), migration_id),
        )
        self.db.commit()

    def get_migration_progress(self, source: str, destination: str) -> Optional[Tuple[int, int]]:
        self.cur.execute("SELECT id, last_message_id FROM migration_progress WHERE source = ? AND destination = ?", (source, destination))
        row = self.cur.fetchone()
        return row if row else None

    def get_migration_report(self, migration_id: int) -> Optional[Tuple[str, str, int, str, str, str]]:
        self.cur.execute("SELECT source, destination, last_message_id, status, created_at, updated_at FROM migration_progress WHERE id = ?", (migration_id,))
        return self.cur.fetchone()


__all__ = ["MigrationOperations"]
