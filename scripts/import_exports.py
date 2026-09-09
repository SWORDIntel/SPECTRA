#!/usr/bin/env python3
"""Import 64Gram Desktop chat exports into the SPECTRA database.

Reads result.json files from Telegram Desktop export folders and imports
messages into dm_corpus (for personal chats) or spectra_messages (for groups).
Uses INSERT OR IGNORE to avoid duplicates with existing data.
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/fast/home/john/SPECTRA/spectra.db")

EXPORTS = [
    "/home/john/Downloads/64Gram Desktop/ChatExport_2026-08-05",
    "/home/john/Downloads/64Gram Desktop/ChatExport_2026-08-05 (1)",
    "/home/john/Downloads/64Gram Desktop/ChatExport_2026-08-06",
    "/home/john/Downloads/64Gram Desktop/ChatExport_2026-08-08",
]


def extract_text(msg):
    """Extract text from a message, handling rich text arrays."""
    text = msg.get("text", "")
    if isinstance(text, list):
        parts = []
        for t in text:
            if isinstance(t, str):
                parts.append(t)
            elif isinstance(t, dict):
                parts.append(str(t.get("text", "")))
        return "".join(parts)
    return str(text or "")


def parse_date(date_str):
    """Parse ISO date string from export format."""
    if not date_str:
        return ""
    try:
        return date_str
    except Exception:
        return str(date_str)


def import_personal_chat(db, data, export_path):
    """Import a personal chat export into dm_corpus."""
    peer_id = data.get("id")
    peer_name = data.get("name", "")
    chat_type = data.get("type", "")
    messages = data.get("messages", [])

    account = "O07en"
    inserted = 0
    skipped = 0

    for msg in messages:
        msg_id = msg.get("id")
        if not msg_id:
            continue

        date = parse_date(msg.get("date", ""))
        text = extract_text(msg)
        from_name = msg.get("from", "")
        from_id = msg.get("from_id", "")

        # Determine sender_id and is_out
        # In exports, "from" is the display name, "from_id" is like "user_8000000002"
        is_out = 0
        sender_id = 0

        if isinstance(from_id, str):
            if from_id.startswith("user_"):
                try:
                    sender_id = int(from_id.replace("user_", ""))
                except ValueError:
                    pass
            elif from_id.startswith("channel_"):
                try:
                    sender_id = int(from_id.replace("channel_", ""))
                except ValueError:
                    pass

        # If from_id matches our operator ID, it's outgoing
        if sender_id == 8000000002:
            is_out = 1
        # Also check by name as fallback
        elif from_name and "inspector" in from_name.lower():
            is_out = 1
            sender_id = 8000000002
        else:
            # Incoming from peer
            sender_id = peer_id

        has_media = 1 if (msg.get("photo") or msg.get("file") or
                          msg.get("media_type") or msg.get("sticker_emoji") or
                          msg.get("voice_message") or msg.get("video")) else 0
        media_type = ""
        if msg.get("photo"):
            media_type = "photo"
        elif msg.get("file"):
            media_type = "file"
        elif msg.get("media_type"):
            media_type = msg.get("media_type")
        elif msg.get("sticker_emoji"):
            media_type = "sticker"
        elif msg.get("voice_message"):
            media_type = "voice"
        elif msg.get("video"):
            media_type = "video"

        reply_to = msg.get("reply_to_message_id")

        record = (
            account, peer_id, peer_id, "", peer_name, msg_id,
            date, sender_id, from_name, text, has_media, media_type,
            reply_to, is_out, datetime.now(timezone.utc).isoformat(),
        )

        try:
            cursor = db.execute("""INSERT OR IGNORE INTO dm_corpus
                (account, dialog_id, peer_id, peer_username, peer_display,
                 message_id, date, sender_id, sender_name, text, has_media,
                 media_type, reply_to_msg, is_out, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", record)
            if cursor.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
        except sqlite3.Error as e:
            skipped += 1

    return inserted, skipped, peer_id, peer_name


def import_group_chat(db, data, export_path):
    """Import a group/supergroup chat export into spectra_messages."""
    channel_id = data.get("id")
    channel_name = data.get("name", "")
    messages = data.get("messages", [])

    inserted = 0
    skipped = 0

    for msg in messages:
        msg_id = msg.get("id")
        if not msg_id:
            continue

        date = parse_date(msg.get("date", ""))
        text = extract_text(msg)
        from_name = msg.get("from", "")
        from_id = msg.get("from_id", "")

        sender_id = 0
        if isinstance(from_id, str):
            if from_id.startswith("user_"):
                try:
                    sender_id = int(from_id.replace("user_", ""))
                except ValueError:
                    pass
            elif from_id.startswith("channel_"):
                try:
                    sender_id = int(from_id.replace("channel_", ""))
                except ValueError:
                    pass

        has_media = 1 if (msg.get("photo") or msg.get("file") or
                          msg.get("media_type") or msg.get("sticker_emoji") or
                          msg.get("voice_message") or msg.get("video")) else 0
        reply_to = msg.get("reply_to_message_id", 0) or 0
        forwarded_from = 0
        if msg.get("forwarded_from"):
            fwd = msg.get("forwarded_from")
            # Can't easily extract ID from display name, leave as 0

        try:
            cursor = db.execute("""INSERT OR REPLACE INTO spectra_messages
                (id, channel_id, sender_id, sender_name, date, text,
                 has_media, crime_score, reply_to, forwarded_from)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (msg_id, channel_id, sender_id, from_name, date, text,
                 has_media, reply_to, forwarded_from))
            if cursor.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
        except sqlite3.Error:
            skipped += 1

    # Also upsert channel info
    try:
        db.execute("""INSERT OR REPLACE INTO spectra_channels
            (id, title, username, last_archived, account)
            VALUES (?, ?, '', ?, 'O07en')""",
            (channel_id, channel_name,
             datetime.now(timezone.utc).isoformat()))
    except sqlite3.Error:
        pass

    return inserted, skipped, channel_id, channel_name


def main():
    db = sqlite3.connect(str(DB_PATH), timeout=30)
    db.execute("PRAGMA busy_timeout=30000")
    db.row_factory = sqlite3.Row

    # Ensure tables exist
    db.execute("""CREATE TABLE IF NOT EXISTS dm_corpus (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account TEXT, dialog_id INTEGER, peer_id INTEGER,
        peer_username TEXT, peer_display TEXT, message_id INTEGER,
        date TEXT, sender_id INTEGER, sender_name TEXT, text TEXT,
        has_media INTEGER, media_type TEXT, reply_to_msg INTEGER,
        is_out INTEGER, ingested_at TEXT
    )""")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_dm_corpus_message
        ON dm_corpus(account, peer_id, message_id)""")
    db.execute("""CREATE TABLE IF NOT EXISTS spectra_messages (
        id INTEGER, channel_id INTEGER, sender_id INTEGER,
        sender_name TEXT, date TEXT, text TEXT, has_media INTEGER DEFAULT 0,
        crime_score INTEGER DEFAULT 0, reply_to INTEGER,
        forwarded_from INTEGER DEFAULT 0,
        PRIMARY KEY (id, channel_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS spectra_channels (
        id INTEGER PRIMARY KEY, title TEXT, username TEXT,
        members INTEGER, date TEXT, crime_score INTEGER DEFAULT 0,
        last_archived TEXT, last_msg_id INTEGER DEFAULT 0,
        joined_at TEXT, account TEXT
    )""")

    total_inserted = 0
    total_skipped = 0

    for export_path_str in EXPORTS:
        export_path = Path(export_path_str)
        result_file = export_path / "result.json"
        if not result_file.is_file():
            print(f"[skip] {export_path} - no result.json")
            continue

        print(f"\n=== Importing {export_path.name} ===")
        with open(result_file, encoding="utf-8") as f:
            data = json.load(f)

        chat_type = data.get("type", "")
        chat_name = data.get("name", "?")
        chat_id = data.get("id", "?")
        msg_count = len(data.get("messages", []))
        print(f"  type={chat_type} name={chat_name} id={chat_id} messages={msg_count}")

        if chat_type == "personal_chat":
            inserted, skipped, peer_id, peer_name = import_personal_chat(db, data, export_path)
            print(f"  inserted={inserted} skipped={skipped} peer={peer_name}({peer_id})")
            total_inserted += inserted
            total_skipped += skipped
        elif chat_type in ("private_supergroup", "public_supergroup", "saved_messages", "bot_chat"):
            inserted, skipped, channel_id, channel_name = import_group_chat(db, data, export_path)
            print(f"  inserted={inserted} skipped={skipped} channel={channel_name}({channel_id})")
            total_inserted += inserted
            total_skipped += skipped
        else:
            print(f"  [skip] unsupported type: {chat_type}")

        db.commit()

    db.commit()
    db.close()

    print(f"\n=== TOTAL: inserted={total_inserted} skipped={total_skipped} ===")


if __name__ == "__main__":
    main()
