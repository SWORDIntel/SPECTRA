"""
SPECTRA-004 Core Operations
===========================
Core database operations for users, messages, media, and timeline queries.
"""
import logging
from datetime import datetime, timezone
from typing import Iterator, List, Optional, Tuple

from .models import Day, Media, Message, Month, User

logger = logging.getLogger(__name__)


class CoreOperations:
    """Core operations for users, messages, media, and timeline queries."""

    def __init__(self, db):
        self.db = db
        self.cur = db.cur
        self._exec_retry = db._exec_retry

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
        Retrieves unique channel IDs and an associated account phone number.
        Prioritizes channels with access_hash.
        """
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
        return [(int(row[0]), str(row[1])) for row in self.cur.fetchall()]

    # Checkpoints ----------------------------------------------------------
    def save_checkpoint(self, last_id: int, *, context: str = "sync") -> None:
        self._exec_retry(
            "INSERT INTO checkpoints(last_message_id, checkpoint_time, context) VALUES (?, ?, ?)",
            (last_id, datetime.now(timezone.utc).isoformat(), context),
        )
        self.db.commit()
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
            if self.db.tz:
                dt = dt.astimezone(self.db.tz)
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
            if self.db.tz:
                dt = dt.astimezone(self.db.tz)
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


__all__ = ["CoreOperations"]
