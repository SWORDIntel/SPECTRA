"""
SPECTRA-004 Base Database Handler
=================================
Base SQLite connection management with retry logic and WAL mode.
"""
import logging
import math
import sqlite3
import time
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path

import pytz  # type: ignore

from .schema import SCHEMA_SQL

logger = logging.getLogger(__name__)


def _page(n: int, multiple: int) -> int:
    """Return page number (1-indexed) for n with page-size multiple."""
    return math.ceil(n / multiple) if n > 0 else 1


class BaseDB(AbstractContextManager):
    """Base SQLite wrapper providing WAL mode, foreign keys, and retry logic."""

    RETRIES = 3

    def __init__(self, db_path: Path | str, *, tz: str | None = None) -> None:
        self.db_path = Path(db_path)
        self.tz = pytz.timezone(tz) if tz else None
        self.conn: sqlite3.Connection
        self.cur: sqlite3.Cursor
        self._open()

    def _open(self) -> None:
        backoff = 1.0
        for attempt in range(1, self.RETRIES + 1):
            try:
                self.conn = sqlite3.connect(
                    self.db_path,
                    detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                    timeout=5.0,
                )
                self.conn.execute("PRAGMA journal_mode=WAL;")
                self.conn.execute("PRAGMA foreign_keys=ON;")
                self.conn.create_function("PAGE", 2, _page)
                self.cur = self.conn.cursor()
                self.cur.executescript(SCHEMA_SQL)
                self.conn.commit()
                logger.info("DB ready at %s", self.db_path)
                return
            except sqlite3.OperationalError as exc:
                logger.warning("[%d/%d] DB locked (%s) – backing off %.1fs", attempt, self.RETRIES, exc, backoff)
                time.sleep(backoff)
                backoff *= 2
        raise RuntimeError("Failed to open DB after retries")

    def __exit__(self, exc_type, exc, tb):
        if exc:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()
        logger.info("Connection closed")
        return False

    def _exec_retry(self, sql: str, params: tuple = ()) -> None:
        """Execute SQL with exponential backoff on lock errors."""
        backoff = 1.0
        for attempt in range(1, self.RETRIES + 1):
            try:
                self.cur.execute(sql, params)
                return
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower():
                    logger.debug("[%d/%d] Locked – sleep %.1fs", attempt, self.RETRIES, backoff)
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise

    def export_csv(self, table: str, dst: Path) -> int:
        """Export table to CSV file."""
        rows = self.cur.execute(f"SELECT * FROM {table}").fetchall()
        headers = [d[0] for d in self.cur.description]
        with dst.open("w", encoding="utf-8") as fh:
            fh.write(",".join(headers) + "\n")
            for row in rows:
                fh.write(",".join(map(lambda x: "" if x is None else str(x), row)) + "\n")
        logger.info("Exported %d rows from %s to %s", len(rows), table, dst)
        return len(rows)

    def commit(self):
        """Explicitly commit the current transaction."""
        self.conn.commit()


__all__ = ["BaseDB"]
