"""
SPECTRA-004 Sorting and Hash Operations
=======================================
Operations for file sorting, categorization, and hash management.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class SortingHashOperations:
    """Operations for file sorting, categorization, and hash management."""

    def __init__(self, db):
        self.db = db
        self.cur = db.cur
        self._exec_retry = db._exec_retry

    # Category and Group Mapping -------------------------------------------
    def add_category_to_group_mapping(self, category: str, group_id: int, priority: int = 0) -> None:
        self._exec_retry(
            "INSERT OR IGNORE INTO category_to_group_mapping(category, group_id, priority) VALUES (?, ?, ?)",
            (category, group_id, priority),
        )
        self.db.commit()

    def get_group_id_for_category(self, category: str) -> Optional[int]:
        self.cur.execute("SELECT group_id FROM category_to_group_mapping WHERE category = ? ORDER BY priority DESC", (category,))
        row = self.cur.fetchone()
        return row[0] if row else None

    def update_category_stats(self, category: str, file_size: int) -> None:
        self._exec_retry(
            """
            INSERT INTO category_stats(category, files_count, bytes_count)
            VALUES (?, 1, ?)
            ON CONFLICT(category) DO UPDATE SET
                files_count = files_count + 1,
                bytes_count = bytes_count + excluded.bytes_count;
            """,
            (category, file_size),
        )
        self.db.commit()

    # Sorting Groups -------------------------------------------------------
    def add_sorting_group(self, group_name: str, template: str) -> None:
        self._exec_retry(
            "INSERT OR IGNORE INTO sorting_groups(group_name, template) VALUES (?, ?)",
            (group_name, template),
        )
        self.db.commit()

    def get_sorting_group_template(self, group_name: str) -> Optional[str]:
        self.cur.execute("SELECT template FROM sorting_groups WHERE group_name = ?", (group_name,))
        row = self.cur.fetchone()
        return row[0] if row else None

    # Sorting Stats and Audit ----------------------------------------------
    def add_sorting_stats(self, source: str, files_sorted: int, bytes_sorted: int, started_at: str, finished_at: str) -> None:
        self._exec_retry(
            "INSERT INTO sorting_stats(source, files_sorted, bytes_sorted, started_at, finished_at) VALUES (?, ?, ?, ?, ?)",
            (source, files_sorted, bytes_sorted, started_at, finished_at),
        )
        self.db.commit()

    def add_sorting_audit_log(self, source: str, message_id: int, file_id: str, category: str, group_id: int) -> None:
        self._exec_retry(
            "INSERT INTO sorting_audit_log(source, message_id, file_id, category, group_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (source, message_id, file_id, category, group_id, datetime.now(timezone.utc).isoformat()),
        )
        self.db.commit()

    # Attribution Stats ----------------------------------------------------
    def update_attribution_stats(self, source_channel_id: int) -> None:
        self._exec_retry(
            """
            INSERT INTO attribution_stats(source_channel_id, attributions_count)
            VALUES (?, 1)
            ON CONFLICT(source_channel_id) DO UPDATE SET
                attributions_count = attributions_count + 1;
            """,
            (source_channel_id,),
        )
        self.db.commit()

    # File Hashes ----------------------------------------------------------
    def add_file_hash(self, file_id: int, sha256_hash: Optional[str], perceptual_hash: Optional[str], fuzzy_hash: Optional[str]) -> None:
        self._exec_retry(
            """
            INSERT INTO file_hashes(file_id, sha256_hash, perceptual_hash, fuzzy_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_id, sha256_hash, perceptual_hash, fuzzy_hash, datetime.now(timezone.utc).isoformat()),
        )
        self.db.commit()

    def get_all_fuzzy_hashes(self, channel_id: Optional[int] = None) -> List[Tuple[int, str]]:
        """
        Retrieves all non-null fuzzy hashes from the database.
        Optionally filters by channel_id.
        """
        if channel_id:
            sql = """
                SELECT f.file_id, f.fuzzy_hash
                FROM file_hashes f
                JOIN channel_file_inventory c ON f.file_id = c.file_id
                WHERE f.fuzzy_hash IS NOT NULL AND c.channel_id = ?
            """
            params = (channel_id,)
        else:
            sql = "SELECT file_id, fuzzy_hash FROM file_hashes WHERE fuzzy_hash IS NOT NULL"
            params = ()
        self.cur.execute(sql, params)
        return self.cur.fetchall()

    def get_all_perceptual_hashes(self, channel_id: Optional[int] = None) -> List[Tuple[int, str]]:
        """
        Retrieves all non-null perceptual hashes from the database.
        Optionally filters by channel_id.
        """
        if channel_id:
            sql = """
                SELECT f.file_id, f.perceptual_hash
                FROM file_hashes f
                JOIN channel_file_inventory c ON f.file_id = c.file_id
                WHERE f.perceptual_hash IS NOT NULL AND c.channel_id = ?
            """
            params = (channel_id,)
        else:
            sql = "SELECT file_id, perceptual_hash FROM file_hashes WHERE perceptual_hash IS NOT NULL"
            params = ()
        self.cur.execute(sql, params)
        return self.cur.fetchall()

    # Channel File Inventory -----------------------------------------------
    def add_channel_file_inventory(self, channel_id: int, file_id: int, message_id: int, topic_id: Optional[int]) -> None:
        """
        Records an entry in the channel_file_inventory table.
        Uses INSERT OR IGNORE to avoid errors on duplicate entries.
        """
        self._exec_retry(
            """
            INSERT OR IGNORE INTO channel_file_inventory(channel_id, file_id, message_id, topic_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (channel_id, file_id, message_id, topic_id, datetime.now(timezone.utc).isoformat())
        )
        self.db.commit()


__all__ = ["SortingHashOperations"]
