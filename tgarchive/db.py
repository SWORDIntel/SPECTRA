"""
SPECTRA-004 — Telegram Archiver DB Handler (v1.0)
=================================================
A hardened SQLite backend for SPECTRA-series tools.
Built for **SWORD-EPI** with the same conventions as *SPECTRA-002*:

* WAL-mode, foreign-key integrity, application-level checksums.
* Exponential-back-off on locked writes.
* Conveniences for timeline queries + resumable checkpoints.

MIT-style licence.  © 2025 John (SWORD-EPI) – codename *SPECTRA-004*.
"""
from __future__ import annotations

# ── Standard Library ─────────────────────────────────────────────────────
import json
import logging
import math
import os
import sqlite3
import sys
import time
from collections import namedtuple
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, NamedTuple, Optional, Tuple

# ── Third-party ──────────────────────────────────────────────────────────
import pytz  # type: ignore
from rich.console import Console

# ── Logging setup ────────────────────────────────────────────────────────
APP_NAME = "spectra_004_db"
LOGS_DIR = Path.cwd() / "logs"
LOGS_DIR.mkdir(exist_ok=True)
log_file = LOGS_DIR / f"{APP_NAME}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(APP_NAME)
console = Console()

# ── SQL schema ───────────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    last_name     TEXT,
    tags          TEXT,
    avatar        TEXT,
    last_updated  TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY,
    type        TEXT,
    url         TEXT,
    title       TEXT,
    description TEXT,
    thumb       TEXT,
    checksum    TEXT
);
CREATE INDEX IF NOT EXISTS idx_media_type ON media(type);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    type        TEXT NOT NULL,
    date        TEXT NOT NULL,
    edit_date   TEXT,
    content     TEXT,
    reply_to    INTEGER,
    user_id     INTEGER REFERENCES users(id),
    media_id    INTEGER REFERENCES media(id),
    checksum    TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);

CREATE TABLE IF NOT EXISTS checkpoints (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    last_message_id  INTEGER,
    checkpoint_time  TEXT,
    context          TEXT
);

CREATE TABLE IF NOT EXISTS account_channel_access (
    account_phone_number TEXT NOT NULL,
    channel_id           BIGINT NOT NULL,
    channel_name         TEXT,
    access_hash          BIGINT,
    last_seen            TEXT,
    PRIMARY KEY (account_phone_number, channel_id)
);

CREATE TABLE IF NOT EXISTS channel_forward_schedule (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          BIGINT NOT NULL,
    destination         TEXT NOT NULL,
    schedule            TEXT NOT NULL,
    last_message_id     INTEGER,
    is_enabled          BOOLEAN DEFAULT TRUE,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_forward_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id         INTEGER REFERENCES channel_forward_schedule(id),
    messages_forwarded  INTEGER NOT NULL,
    files_forwarded     INTEGER NOT NULL,
    bytes_forwarded     INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT NOT NULL,
    status              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_forward_schedule (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    destination         TEXT NOT NULL,
    schedule            TEXT NOT NULL,
    file_types          TEXT,
    min_file_size       INTEGER,
    max_file_size       INTEGER,
    is_enabled          BOOLEAN DEFAULT TRUE,
    priority            INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_forward_queue (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id         INTEGER REFERENCES file_forward_schedule(id) ON DELETE SET NULL,
    message_id          INTEGER NOT NULL,
    file_id             TEXT NOT NULL,
    destination         INTEGER,
    status              TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category_to_group_mapping (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category            TEXT NOT NULL,
    group_id            INTEGER NOT NULL,
    priority            INTEGER DEFAULT 0,
    UNIQUE(category, group_id)
);

CREATE TABLE IF NOT EXISTS category_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category            TEXT NOT NULL,
    files_count         INTEGER NOT NULL,
    bytes_count         INTEGER NOT NULL,
    UNIQUE(category)
);

CREATE TABLE IF NOT EXISTS sorting_groups (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name          TEXT NOT NULL,
    template            TEXT NOT NULL,
    is_enabled          BOOLEAN DEFAULT TRUE,
    UNIQUE(group_name)
);

CREATE TABLE IF NOT EXISTS sorting_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    files_sorted        INTEGER NOT NULL,
    bytes_sorted        INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sorting_audit_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    message_id          INTEGER NOT NULL,
    file_id             TEXT NOT NULL,
    category            TEXT NOT NULL,
    group_id            INTEGER NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attribution_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_channel_id   BIGINT NOT NULL,
    attributions_count  INTEGER NOT NULL,
    UNIQUE(source_channel_id)
);

CREATE TABLE IF NOT EXISTS file_forward_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id         INTEGER REFERENCES file_forward_schedule(id),
    files_forwarded     INTEGER NOT NULL,
    bytes_forwarded     INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT NOT NULL,
    status              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS migration_progress (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    destination         TEXT NOT NULL,
    last_message_id     INTEGER,
    status              TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_hashes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id             INTEGER REFERENCES media(id) ON DELETE CASCADE,
    sha256_hash         TEXT,
    perceptual_hash     TEXT,
    fuzzy_hash          TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE(file_id)
);
CREATE INDEX IF NOT EXISTS idx_file_hashes_sha256 ON file_hashes(sha256_hash);
CREATE INDEX IF NOT EXISTS idx_file_hashes_perceptual ON file_hashes(perceptual_hash);
CREATE INDEX IF NOT EXISTS idx_file_hashes_fuzzy ON file_hashes(fuzzy_hash);

CREATE TABLE IF NOT EXISTS channel_file_inventory (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          INTEGER NOT NULL,
    file_id             INTEGER NOT NULL,
    message_id          INTEGER NOT NULL,
    topic_id            INTEGER,
    created_at          TEXT NOT NULL,
    UNIQUE(channel_id, file_id, message_id)
);

CREATE TABLE IF NOT EXISTS topic_file_mapping (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id            INTEGER NOT NULL,
    file_id             INTEGER NOT NULL,
    message_id          INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE(topic_id, file_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_channel_file_inventory_channel_id ON channel_file_inventory(channel_id);
CREATE INDEX IF NOT EXISTS idx_channel_file_inventory_file_id ON channel_file_inventory(file_id);
CREATE INDEX IF NOT EXISTS idx_topic_file_mapping_topic_id ON topic_file_mapping(topic_id);
CREATE INDEX IF NOT EXISTS idx_topic_file_mapping_file_id ON topic_file_mapping(file_id);
"""

# ── Helper SQL functions ────────────────────────────────────────────────

def _page(n: int, multiple: int) -> int:  # noqa: D401
    """Return page number (1-indexed) for *n* with page-size *multiple*."""
    return math.ceil(n / multiple) if n > 0 else 1

# ── NamedTuples (kept for perf; could migrate to `dataclass` later) ─────
class User(NamedTuple):
    id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    tags: List[str]
    avatar: Optional[str]
    last_updated: Optional[datetime]

class Media(NamedTuple):
    id: int
    type: str
    url: Optional[str]
    title: Optional[str]
    description: Optional[str | List | dict]
    thumb: Optional[str]
    checksum: Optional[str]

class Message(NamedTuple):
    id: int
    type: str
    date: datetime
    edit_date: Optional[datetime]
    content: Optional[str]
    reply_to: Optional[int]
    user: Optional[User]
    media: Optional[Media]
    checksum: Optional[str]

class Month(NamedTuple):
    date: datetime
    slug: str
    label: str
    count: int

class Day(NamedTuple):
    date: datetime
    slug: str
    label: str
    count: int
    page: int

# ── DB Handler ───────────────────────────────────────────────────────────
class SpectraDB(AbstractContextManager):
    """SQLite wrapper providing WAL, retries & convenience selects."""

    RETRIES = 3

    def __init__(self, db_path: Path | str, *, tz: str | None = None) -> None:
        self.db_path = Path(db_path)
        self.tz = pytz.timezone(tz) if tz else None
        self.conn: sqlite3.Connection
        self.cur: sqlite3.Cursor
        self._open()

    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    def __exit__(self, exc_type, exc, tb):
        if exc:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()
        logger.info("Connection closed")
        return False

    # ------------------------------------------------------------------ #
    # Insert helpers use exponential back-off on `database is locked`.
    def _exec_retry(self, sql: str, params: tuple = ()) -> None:
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

    # Users ----------------------------------------------------------------
    def upsert_user(self, user: User) -> None:
        self._exec_retry(
            """
            INSERT INTO users(id, username, first_name, last_name, tags, avatar, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                tags=excluded.tags,
                avatar=excluded.avatar,
                last_updated=excluded.last_updated;
            """,
            (
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                " ".join(user.tags),
                user.avatar,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    # Media ----------------------------------------------------------------
    def upsert_media(self, media: Media) -> None:
        self._exec_retry(
            """
            INSERT INTO media(id, type, url, title, description, thumb, checksum)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                url=excluded.url,
                title=excluded.title,
                description=excluded.description,
                thumb=excluded.thumb,
                checksum=excluded.checksum;
            """,
            media,
        )

    # Messages -------------------------------------------------------------
    def upsert_message(self, msg: Message) -> None:
        self._exec_retry(
            """
            INSERT INTO messages(id, type, date, edit_date, content, reply_to, user_id, media_id, checksum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                date=excluded.date,
                edit_date=excluded.edit_date,
                content=excluded.content,
                reply_to=excluded.reply_to,
                user_id=excluded.user_id,
                media_id=excluded.media_id,
                checksum=excluded.checksum;
            """,
            (
                msg.id,
                msg.type,
                msg.date.isoformat(),
                msg.edit_date.isoformat() if msg.edit_date else None,
                msg.content,
                msg.reply_to,
                msg.user.id if msg.user else None,
                msg.media.id if msg.media else None,
                msg.checksum,
            ),
        )

    # Account Channel Access -----------------------------------------------
    def upsert_account_channel_access(
        self,
        account_phone_number: str,
        channel_id: int,
        channel_name: Optional[str],
        access_hash: Optional[int],
        last_seen: str,
    ) -> None:
        self._exec_retry(
            """
            INSERT INTO account_channel_access(account_phone_number, channel_id, channel_name, access_hash, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account_phone_number, channel_id) DO UPDATE SET
                channel_name=excluded.channel_name,
                access_hash=excluded.access_hash,
                last_seen=excluded.last_seen;
            """,
            (account_phone_number, channel_id, channel_name, access_hash, last_seen),
        )

    def get_all_unique_channels(self) -> List[Tuple[int, str]]:
        """
        Retrieves a list of unique channel IDs and an associated account phone number
        that can access each channel. Prioritizes channels with access_hash.
        """
        # This query selects distinct channel_id and one corresponding account_phone_number.
        # It prioritizes entries with non-null access_hash if multiple accounts can see the same channel.
        # The subquery with row_number is a common way to achieve "pick one row per group"
        # based on some ordering.
        sql = """
            SELECT channel_id, account_phone_number
            FROM (
                SELECT
                    channel_id,
                    account_phone_number,
                    access_hash,
                    ROW_NUMBER() OVER (PARTITION BY channel_id ORDER BY CASE WHEN access_hash IS NOT NULL THEN 0 ELSE 1 END, last_seen DESC) as rn
                FROM account_channel_access
            )
            WHERE rn = 1;
        """
        self.cur.execute(sql)
        # The query should return (BIGINT, TEXT), which matches (int, str) in Python
        return [(int(row[0]), str(row[1])) for row in self.cur.fetchall()]


    # Checkpoints ----------------------------------------------------------
    def save_checkpoint(self, last_id: int, *, context: str = "sync") -> None:
        self._exec_retry(
            "INSERT INTO checkpoints(last_message_id, checkpoint_time, context) VALUES (?, ?, ?)",
            (last_id, datetime.now(timezone.utc).isoformat(), context),
        )
        self.conn.commit()
        logger.info("Checkpoint saved (%s – %s)", last_id, context)

    def latest_checkpoint(self, context: str = "sync") -> Optional[int]:
        row = self.cur.execute(
            "SELECT last_message_id FROM checkpoints WHERE context=? ORDER BY checkpoint_time DESC LIMIT 1",
            (context,),
        ).fetchone()
        return row[0] if row else None

    # Timeline helpers -----------------------------------------------------
    def months(self) -> Iterator[Month]:
        for ts, cnt in self.cur.execute(
            "SELECT strftime('%Y-%m-01T00:00:00Z', date), COUNT(*) FROM messages GROUP BY strftime('%Y-%m', date) ORDER BY 1"
        ):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if self.tz:
                dt = dt.astimezone(self.tz)
            yield Month(dt, dt.strftime("%Y-%m"), dt.strftime("%b %Y"), cnt)

    def days(self, year: int, month: int, *, page_size: int = 500) -> Iterator[Day]:
        ym = f"{year}{month:02d}"
        for ts, cnt, page in self.cur.execute(
            """
            SELECT strftime('%Y-%m-%dT00:00:00Z', date), COUNT(*), PAGE(rank, ?) FROM (
                SELECT ROW_NUMBER() OVER(ORDER BY id) AS rank, date FROM messages WHERE strftime('%Y%m', date)=?
            ) GROUP BY 1 ORDER BY 1;
            """,
            (page_size, ym),
        ):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if self.tz:
                dt = dt.astimezone(self.tz)
            yield Day(dt, dt.strftime("%Y-%m-%d"), dt.strftime("%d %b %Y"), cnt, page)

    # Integrity check ------------------------------------------------------
    def verify_checksums(self, table: str, *, id_range: Tuple[int, int] | None = None) -> List[dict]:
        issues: List[dict] = []
        sql = f"SELECT id, checksum FROM {table}"
        params: Tuple = ()
        if id_range:
            sql += " WHERE id BETWEEN ? AND ?"
            params = id_range  # type: ignore
        for id_, checksum in self.cur.execute(sql, params):
            if not checksum:
                issues.append({"id": id_, "issue": "missing checksum"})
        logger.info("Integrity on %s – %d issues", table, len(issues))
        return issues

    # Export (CSV placeholder) --------------------------------------------
    def export_csv(self, table: str, dst: Path) -> int:
        rows = self.cur.execute(f"SELECT * FROM {table}").fetchall()
        headers = [d[0] for d in self.cur.description]
        with dst.open("w", encoding="utf-8") as fh:
            fh.write(",".join(headers) + "\n")
            for row in rows:
                fh.write(",".join(map(lambda x: "" if x is None else str(x), row)) + "\n")
        logger.info("Exported %d rows from %s to %s", len(rows), table, dst)
        return len(rows)

    def add_channel_forward_schedule(self, channel_id: int, destination: str, schedule: str) -> None:
        self._exec_retry(
            """
            INSERT INTO channel_forward_schedule(channel_id, destination, schedule, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (channel_id, destination, schedule, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

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
        self.conn.commit()

    def add_channel_forward_stats(self, schedule_id: int, messages_forwarded: int, files_forwarded: int, bytes_forwarded: int, started_at: str, finished_at: str, status: str) -> None:
        self._exec_retry(
            """
            INSERT INTO channel_forward_stats(schedule_id, messages_forwarded, files_forwarded, bytes_forwarded, started_at, finished_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (schedule_id, messages_forwarded, files_forwarded, bytes_forwarded, started_at, finished_at, status),
        )
        self.conn.commit()

    def add_file_forward_schedule(self, source: str, destination: str, schedule: str, file_types: Optional[str], min_file_size: Optional[int], max_file_size: Optional[int], priority: int) -> None:
        self._exec_retry(
            """
            INSERT INTO file_forward_schedule(source, destination, schedule, file_types, min_file_size, max_file_size, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source, destination, schedule, file_types, min_file_size, max_file_size, priority, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_file_forward_schedules(self) -> List[Tuple[int, str, str, str, Optional[str], Optional[int], Optional[int], int]]:
        self.cur.execute("SELECT id, source, destination, schedule, file_types, min_file_size, max_file_size, priority FROM file_forward_schedule WHERE is_enabled = TRUE ORDER BY priority DESC")
        return self.cur.fetchall()

    def get_file_forward_schedule_by_id(self, schedule_id: int) -> Optional[NamedTuple]:
        self.cur.execute("SELECT id, source, destination, schedule, file_types, min_file_size, max_file_size, priority FROM file_forward_schedule WHERE id = ?", (schedule_id,))
        row = self.cur.fetchone()
        if row:
            FileForwardSchedule = namedtuple("FileForwardSchedule", ["id", "source", "destination", "schedule", "file_types", "min_file_size", "max_file_size", "priority"])
            return FileForwardSchedule(*row)
        return None

    def add_to_file_forward_queue(self, schedule_id: Optional[int], message_id: int, file_id: str, destination: int) -> None:
        self._exec_retry(
            """
            INSERT INTO file_forward_queue(schedule_id, message_id, file_id, status, created_at, updated_at, destination)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (schedule_id, message_id, file_id, "pending", datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), destination),
        )
        self.conn.commit()

    def get_file_forward_queue(self) -> List[Tuple[int, int, int, str, int]]:
        self.cur.execute("SELECT id, schedule_id, message_id, file_id, destination FROM file_forward_queue WHERE status = 'pending' ORDER BY id")
        return self.cur.fetchall()

    def update_file_forward_queue_status(self, queue_id: int, status: str) -> None:
        self._exec_retry(
            "UPDATE file_forward_queue SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now(timezone.utc).isoformat(), queue_id),
        )
        self.conn.commit()

    def get_file_forward_queue_status_by_schedule_id(self, schedule_id: int) -> List[Tuple[int, str, str]]:
        self.cur.execute("SELECT message_id, file_id, status FROM file_forward_queue WHERE schedule_id = ?", (schedule_id,))
        return self.cur.fetchall()

    def add_category_to_group_mapping(self, category: str, group_id: int, priority: int = 0) -> None:
        self._exec_retry(
            "INSERT OR IGNORE INTO category_to_group_mapping(category, group_id, priority) VALUES (?, ?, ?)",
            (category, group_id, priority),
        )
        self.conn.commit()

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
        self.conn.commit()

    def add_sorting_group(self, group_name: str, template: str) -> None:
        self._exec_retry(
            "INSERT OR IGNORE INTO sorting_groups(group_name, template) VALUES (?, ?)",
            (group_name, template),
        )
        self.conn.commit()

    def get_sorting_group_template(self, group_name: str) -> Optional[str]:
        self.cur.execute("SELECT template FROM sorting_groups WHERE group_name = ?", (group_name,))
        row = self.cur.fetchone()
        return row[0] if row else None

    def add_sorting_stats(self, source: str, files_sorted: int, bytes_sorted: int, started_at: str, finished_at: str) -> None:
        self._exec_retry(
            "INSERT INTO sorting_stats(source, files_sorted, bytes_sorted, started_at, finished_at) VALUES (?, ?, ?, ?, ?)",
            (source, files_sorted, bytes_sorted, started_at, finished_at),
        )
        self.conn.commit()

    def add_sorting_audit_log(self, source: str, message_id: int, file_id: str, category: str, group_id: int) -> None:
        self._exec_retry(
            "INSERT INTO sorting_audit_log(source, message_id, file_id, category, group_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (source, message_id, file_id, category, group_id, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def add_migration_progress(self, source: str, destination: str, status: str) -> int:
        self._exec_retry(
            "INSERT INTO migration_progress(source, destination, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (source, destination, status, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()
        return self.cur.lastrowid

    def update_migration_progress(self, migration_id: int, last_message_id: int, status: str) -> None:
        self._exec_retry(
            "UPDATE migration_progress SET last_message_id = ?, status = ?, updated_at = ? WHERE id = ?",
            (last_message_id, status, datetime.now(timezone.utc).isoformat(), migration_id),
        )
        self.conn.commit()

    def get_migration_progress(self, source: str, destination: str) -> Optional[Tuple[int, int]]:
        self.cur.execute("SELECT id, last_message_id FROM migration_progress WHERE source = ? AND destination = ?", (source, destination))
        row = self.cur.fetchone()
        return row if row else None

    def get_migration_report(self, migration_id: int) -> Optional[Tuple[str, str, int, str, str, str]]:
        self.cur.execute("SELECT source, destination, last_message_id, status, created_at, updated_at FROM migration_progress WHERE id = ?", (migration_id,))
        return self.cur.fetchone()

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
        self.conn.commit()

    def add_file_forward_stats(self, schedule_id: int, files_forwarded: int, bytes_forwarded: int, started_at: str, finished_at: str, status: str) -> None:
        self._exec_retry(
            """
            INSERT INTO file_forward_stats(schedule_id, files_forwarded, bytes_forwarded, started_at, finished_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (schedule_id, files_forwarded, bytes_forwarded, started_at, finished_at, status),
        )
        self.conn.commit()

    def add_file_hash(self, file_id: int, sha256_hash: Optional[str], perceptual_hash: Optional[str], fuzzy_hash: Optional[str]) -> None:
        self._exec_retry(
            """
            INSERT INTO file_hashes(file_id, sha256_hash, perceptual_hash, fuzzy_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_id, sha256_hash, perceptual_hash, fuzzy_hash, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

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
        self.conn.commit()

__all__ = [
    "SpectraDB",
    "User",
    "Media",
    "Message",
    "Month",
    "Day",
]
