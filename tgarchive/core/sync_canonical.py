from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from telethon import TelegramClient

from tgarchive.core.config_models import Config
from tgarchive.core.sync import (
    ProxyCycler,
    TZ,
    console,
    download_avatars,
    extract_usernames,
    get_topics,
    logger,
    safe_download_media,
)
from tgarchive.osint.caas.schema import enqueue_profile_candidate, ensure_schema as ensure_caas_schema


class CanonicalDBHandler(contextlib.AbstractContextManager):
    def __init__(self, db_file: Path):
        self.db_file = db_file
        self.conn: sqlite3.Connection | None = None
        self.cur: sqlite3.Cursor | None = None

    def __enter__(self):
        self.conn = sqlite3.connect(self.db_file)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self.cur = self.conn.cursor()
        self._schema()
        ensure_caas_schema(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is not None:
                if self.conn:
                    self.conn.rollback()
            else:
                if self.conn:
                    self.conn.commit()
        finally:
            if self.conn:
                self.conn.close()
        return False

    def _schema(self):
        assert self.cur is not None
        self.cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                avatar_path TEXT
            );

            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY,
                entity_id INTEGER NOT NULL,
                title TEXT,
                date_created TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                user_id INTEGER REFERENCES users(id),
                topic_id INTEGER REFERENCES topics(id),
                date TEXT,
                edit_date TEXT,
                content TEXT,
                reply_to INTEGER,
                UNIQUE(channel_id, message_id)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_channel_topic ON messages(channel_id, topic_id, message_id);
            CREATE INDEX IF NOT EXISTS idx_messages_channel_date ON messages(channel_id, date);

            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                message_row_id INTEGER REFERENCES messages(row_id),
                message_id INTEGER NOT NULL,
                mime_type TEXT,
                file_path TEXT,
                UNIQUE(channel_id, id, message_id)
            );

            CREATE TABLE IF NOT EXISTS username_mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                message_row_id INTEGER REFERENCES messages(row_id),
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                date TEXT,
                source_type TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_username_mentions_user ON username_mentions(username);
            """
        )

    def add_user(self, user: Any) -> None:
        assert self.cur is not None
        self.cur.execute(
            "INSERT OR REPLACE INTO users(id, username, first_name, last_name, avatar_path) VALUES (?, ?, ?, ?, ?)",
            (user.id, getattr(user, "username", None), getattr(user, "first_name", None), getattr(user, "last_name", None), None),
        )

    def add_topic(self, topic_id: int, entity_id: int, title: str, date_created: str) -> int:
        assert self.cur is not None
        self.cur.execute(
            "INSERT OR REPLACE INTO topics(id, entity_id, title, date_created) VALUES (?, ?, ?, ?)",
            (topic_id, entity_id, title, date_created),
        )
        return topic_id

    def last_message_id(self, channel_id: int, topic_id: Optional[int] = None) -> Optional[int]:
        assert self.cur is not None
        if topic_id is None:
            row = self.cur.execute("SELECT MAX(message_id) FROM messages WHERE channel_id = ?", (channel_id,)).fetchone()
        else:
            row = self.cur.execute(
                "SELECT MAX(message_id) FROM messages WHERE channel_id = ? AND topic_id = ?",
                (channel_id, topic_id),
            ).fetchone()
        return row[0] if row and row[0] else None

    def upsert_message(self, data: dict[str, Any]) -> int:
        assert self.cur is not None
        self.cur.execute(
            """
            INSERT INTO messages(channel_id, message_id, user_id, topic_id, date, edit_date, content, reply_to)
            VALUES (:channel_id, :message_id, :user_id, :topic_id, :date, :edit_date, :content, :reply_to)
            ON CONFLICT(channel_id, message_id) DO UPDATE SET
                user_id=excluded.user_id,
                topic_id=excluded.topic_id,
                date=excluded.date,
                edit_date=excluded.edit_date,
                content=excluded.content,
                reply_to=excluded.reply_to
            """,
            data,
        )
        row = self.cur.execute(
            "SELECT row_id FROM messages WHERE channel_id = ? AND message_id = ?",
            (data["channel_id"], data["message_id"]),
        ).fetchone()
        if not row:
            raise RuntimeError("failed to resolve canonical message row")
        return int(row[0])

    def add_media(self, data: dict[str, Any]) -> None:
        assert self.cur is not None
        self.cur.execute(
            """
            INSERT OR REPLACE INTO media(id, channel_id, message_row_id, message_id, mime_type, file_path)
            VALUES (:id, :channel_id, :message_row_id, :message_id, :mime_type, :file_path)
            """,
            data,
        )

    def add_username(self, username: str, message_row_id: int, channel_id: int, message_id: int, date: str, source: str = "mention") -> None:
        assert self.cur is not None
        self.cur.execute(
            """
            INSERT INTO username_mentions(username, message_row_id, channel_id, message_id, date, source_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, message_row_id, channel_id, message_id, date, source),
        )


async def archive_messages_canonical(client: TelegramClient, entity: Any, topic_id: Optional[int], db: CanonicalDBHandler, cfg: Config, media_dir: Path, progress: Progress, task: Any) -> None:
    channel_id = getattr(entity, "id", None)
    if channel_id is None:
        raise ValueError("Entity is missing channel id; cannot build canonical identity")

    last_id = db.last_message_id(channel_id, topic_id)
    kwargs: dict[str, Any] = {"offset_id": last_id or 0, "reverse": True, "wait_time": cfg["sleep_between_batches"]}
    if topic_id is not None:
        kwargs["topic"] = topic_id

    async for msg in client.iter_messages(entity, **kwargs):
        row_data = {
            "channel_id": channel_id,
            "message_id": msg.id,
            "user_id": msg.sender_id,
            "topic_id": topic_id,
            "date": msg.date.astimezone(TZ).isoformat(),
            "edit_date": msg.edit_date.astimezone(TZ).isoformat() if msg.edit_date else None,
            "content": msg.message,
            "reply_to": msg.reply_to_msg_id,
        }
        message_row_id = db.upsert_message(row_data)

        if msg.sender:
            db.add_user(msg.sender)

        if cfg["collect_usernames"]:
            for uname in extract_usernames(msg.message):
                db.add_username(uname, message_row_id, channel_id, msg.id, row_data["date"])

        if msg.message:
            enqueue_profile_candidate(
                db,
                channel_id=channel_id,
                message_id=msg.id,
                topic_id=topic_id,
                sender_id=msg.sender_id,
                sender_username=getattr(msg.sender, "username", None) if msg.sender else None,
                date=row_data["date"],
                content=msg.message,
            )

        if cfg["download_media"] and msg.media:
            topic_subdir = f"topic_{topic_id}" if topic_id is not None else "main"
            dest_dir = media_dir / topic_subdir
            dest = dest_dir / f"{msg.id}_{msg.file.id}"
            downloaded = await safe_download_media(msg, dest, cfg["media_mime_whitelist"], cfg["sidecar_metadata"])
            if downloaded:
                db.add_media(
                    {
                        "id": msg.file.id,
                        "channel_id": channel_id,
                        "message_row_id": message_row_id,
                        "message_id": msg.id,
                        "mime_type": msg.file.mime_type,
                        "file_path": str(downloaded),
                    }
                )

        progress.update(task, advance=1)


async def archive_channel_canonical(cfg: Config, account: dict[str, Any], proxy_tuple: Any = None) -> None:
    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )
    media_dir = Path(cfg["media_dir"])
    media_dir.mkdir(exist_ok=True)

    async with TelegramClient(account["session_name"], account["api_id"], account["api_hash"], proxy=proxy_tuple) as client:
        logger.info("Connected as %s via proxy=%s", await client.get_me(), proxy_tuple or "none")
        entity = await client.get_entity(cfg["entity"])
        entity_id = entity.id

        with CanonicalDBHandler(Path(cfg["db_path"])) as db:
            total_msgs = await client.get_messages(entity, limit=0)
            archive_task = progress.add_task("[green]Archiving main chat", total=len(total_msgs))
            with progress:
                await archive_messages_canonical(client, entity, None, db, cfg, media_dir, progress, archive_task)
                if cfg["archive_topics"]:
                    topics = await get_topics(client, entity)
                    for topic in topics:
                        topic_id = topic.id
                        topic_title = getattr(topic, "title", f"Topic {topic_id}")
                        topic_date = datetime.now(TZ).isoformat()
                        db.add_topic(topic_id, entity_id, topic_title, topic_date)
                        try:
                            topic_msg_count = await client.get_messages(entity, limit=0, topic=topic_id)
                            topic_task = progress.add_task(f"[cyan]Topic: {topic_title}", total=len(topic_msg_count))
                            await archive_messages_canonical(client, entity, topic_id, db, cfg, media_dir, progress, topic_task)
                        except Exception as exc:
                            logger.exception("Error archiving topic %s: %s", topic_id, exc)
                            continue

            logger.info("Canonical archive complete (%s msgs)", progress.tasks[archive_task].completed)
            if cfg["download_avatars"]:
                await download_avatars(client, db, media_dir / "avatars", cfg["avatar_size"])


async def runner_canonical(cfg: Config, auto_account: Optional[dict[str, Any]] = None) -> None:
    pc = ProxyCycler(cfg.proxy_conf)
    accounts = [auto_account] if auto_account else cfg.accounts
    for account in accounts:
        proxy = pc.next()
        await archive_channel_canonical(cfg, account, proxy)
        break


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Canonical Telegram archiver with channel-scoped identity")
    parser.add_argument("--config", default="spectra_config.json")
    parser.add_argument("--entity", required=True)
    parser.add_argument("--db", default="spectra.db")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--no-media", action="store_true")
    parser.add_argument("--no-avatars", action="store_true")
    parser.add_argument("--no-topics", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cfg = Config(Path(args.config))
    cfg.data["entity"] = args.entity
    cfg.data["db_path"] = args.db
    cfg.data["download_media"] = not args.no_media
    cfg.data["download_avatars"] = not args.no_avatars
    cfg.data["archive_topics"] = not args.no_topics
    account = cfg.auto_select_account() if args.auto else None
    try:
        asyncio.run(runner_canonical(cfg, account))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logger.exception("Canonical archive failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
