"""
SPECTRA-004 Mirror Operations
=============================
Database operations specific to group mirroring.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .db_base import BaseDB


class MirrorOperations:
    """Encapsulates all database operations for group mirroring."""

    def __init__(self, db: BaseDB) -> None:
        self.db = db

    def add_mirror_progress(self, source: str, destination: str, status: str) -> int:
        """
        Adds a new mirror progress record.
        Reuses the migration_progress table.
        """
        sql = """
            INSERT INTO migration_progress (source, destination, status, created_at, updated_at)
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
        """
        return self.db.execute(sql, (source, destination, status))

    def update_mirror_progress(self, source: str, destination: str, last_message_id: int) -> None:
        """
        Updates the last processed message ID for a mirror.
        Reuses the migration_progress table.
        """
        sql = """
            UPDATE migration_progress
            SET last_message_id = ?, updated_at = datetime('now')
            WHERE source = ? AND destination = ?
        """
        self.db.execute(sql, (last_message_id, source, destination))

    def get_mirror_progress(self, source: str, destination: str) -> Optional[int]:
        """
        Gets the last processed message ID for a mirror.
        Reuses the migration_progress table.
        """
        sql = "SELECT last_message_id FROM migration_progress WHERE source = ? AND destination = ?"
        result = self.db.fetchone(sql, (source, destination))
        return result[0] if result and result[0] is not None else 0
