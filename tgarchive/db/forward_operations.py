"""
SPECTRA-004 Forward Operations
==============================
Channel and file forwarding operations.
"""
import logging
from collections import namedtuple
from datetime import datetime, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class ForwardOperations:
    """Operations for channel and file forwarding."""

    def __init__(self, db):
        self.db = db
        self.cur = db.cur
        self._exec_retry = db._exec_retry

    # Channel Forward Schedule ---------------------------------------------
    def add_channel_forward_schedule(self, channel_id: int, destination: str, schedule: str) -> None:
        self._exec_retry(
            """
            INSERT INTO channel_forward_schedule(channel_id, destination, schedule, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (channel_id, destination, schedule, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        self.db.commit()

    def get_channel_forward_schedules(self) -> List[Tuple[int, int, str, str, int]]:
        self.cur.execute("SELECT id, channel_id, destination, schedule, last_message_id FROM channel_forward_schedule WHERE is_enabled = TRUE")
        return self.cur.fetchall()

    def get_channel_forward_schedule_by_channel_and_destination(self, channel_id: int, destination: str) -> Optional[Tuple[int, int, str, str, int]]:
        self.cur.execute("SELECT id, channel_id, destination, schedule, last_message_id FROM channel_forward_schedule WHERE channel_id = ? AND destination = ?", (channel_id, destination))
        return self.cur.fetchone()

    def update_channel_forward_schedule_checkpoint(self, schedule_id: int, last_message_id: int) -> None:
        self._exec_retry(
            "UPDATE channel_forward_schedule SET last_message_id = ?, updated_at = ? WHERE id = ?",
            (last_message_id, datetime.now(timezone.utc).isoformat(), schedule_id),
        )
        self.db.commit()

    def add_channel_forward_stats(self, schedule_id: int, messages_forwarded: int, files_forwarded: int, bytes_forwarded: int, started_at: str, finished_at: str, status: str) -> None:
        self._exec_retry(
            """
            INSERT INTO channel_forward_stats(schedule_id, messages_forwarded, files_forwarded, bytes_forwarded, started_at, finished_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (schedule_id, messages_forwarded, files_forwarded, bytes_forwarded, started_at, finished_at, status),
        )
        self.db.commit()

    # File Forward Schedule ------------------------------------------------
    def add_file_forward_schedule(self, source: str, destination: str, schedule: str, file_types: Optional[str], min_file_size: Optional[int], max_file_size: Optional[int], priority: int) -> None:
        self._exec_retry(
            """
            INSERT INTO file_forward_schedule(source, destination, schedule, file_types, min_file_size, max_file_size, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source, destination, schedule, file_types, min_file_size, max_file_size, priority, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        self.db.commit()

    def get_file_forward_schedules(self) -> List[Tuple[int, str, str, str, Optional[str], Optional[int], Optional[int], int]]:
        self.cur.execute("SELECT id, source, destination, schedule, file_types, min_file_size, max_file_size, priority FROM file_forward_schedule WHERE is_enabled = TRUE ORDER BY priority DESC")
        return self.cur.fetchall()

    def get_file_forward_schedule_by_id(self, schedule_id: int) -> Optional[namedtuple]:
        self.cur.execute("SELECT id, source, destination, schedule, file_types, min_file_size, max_file_size, priority FROM file_forward_schedule WHERE id = ?", (schedule_id,))
        row = self.cur.fetchone()
        if row:
            FileForwardSchedule = namedtuple("FileForwardSchedule", ["id", "source", "destination", "schedule", "file_types", "min_file_size", "max_file_size", "priority"])
            return FileForwardSchedule(*row)
        return None

    # File Forward Queue ---------------------------------------------------
    def add_to_file_forward_queue(self, schedule_id: Optional[int], message_id: int, file_id: str, destination: int) -> None:
        self._exec_retry(
            """
            INSERT INTO file_forward_queue(schedule_id, message_id, file_id, status, created_at, updated_at, destination)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (schedule_id, message_id, file_id, "pending", datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), destination),
        )
        self.db.commit()

    def get_file_forward_queue(self) -> List[Tuple[int, int, int, str, int]]:
        self.cur.execute("SELECT id, schedule_id, message_id, file_id, destination FROM file_forward_queue WHERE status = 'pending' ORDER BY id")
        return self.cur.fetchall()

    def update_file_forward_queue_status(self, queue_id: int, status: str) -> None:
        self._exec_retry(
            "UPDATE file_forward_queue SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now(timezone.utc).isoformat(), queue_id),
        )
        self.db.commit()

    def get_file_forward_queue_status_by_schedule_id(self, schedule_id: int) -> List[Tuple[int, str, str]]:
        self.cur.execute("SELECT message_id, file_id, status FROM file_forward_queue WHERE schedule_id = ?", (schedule_id,))
        return self.cur.fetchall()

    def add_file_forward_stats(self, schedule_id: int, files_forwarded: int, bytes_forwarded: int, started_at: str, finished_at: str, status: str) -> None:
        self._exec_retry(
            """
            INSERT INTO file_forward_stats(schedule_id, files_forwarded, bytes_forwarded, started_at, finished_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (schedule_id, files_forwarded, bytes_forwarded, started_at, finished_at, status),
        )
        self.db.commit()


__all__ = ["ForwardOperations"]
