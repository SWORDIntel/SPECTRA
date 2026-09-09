#!/usr/bin/env python3
"""SPECTRA dual-account archiver with crime keyword prioritization and @example_target tracking."""
import asyncio
import sqlite3
import json
import time
from datetime import datetime, timezone
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest, GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from continuous_monitor import load_accounts

DB = "/fast/home/john/SPECTRA/spectra.db"
ATKLIB_ID = 8000000005

ACCOUNTS = load_accounts()

CRIME_KEYWORDS = [
    "leak", "breach", "exploit", "malware", "ransomware", "stealer", "botnet",
    "ddos", "hack", "hacking", "crack", "carding", "fraud", "scam", "phish",
    "credential", "dump", "database", "exfil", "rat", "trojan", "backdoor",
    "crypter", "loader", "miner", "cryptojack", "wallet", "drainer",
    "swat", "bomb", "drug", "weapon", "counterfeit", "forgery",
    "blackhat", "underground", "0day", "zeroday", "cve", "apt",
    "cartel", "cjng", "gang", "cybercrime", "opsec", "dox", "osint",
    "sniff", "intercept", "mitm", "spyware", "stalkerware", "rootkit",
    "keylogger", "formgrabber", "webinject", "banker", "grabber",
    "combolist", "combo", "checking", "cracking", "proxy", "vpn",
    "meth", "fent", "opioid", "narcotic", "traffick",
    "market", "marketplace", "vendor", "seller", "shop", "store",
    "weapon", "firearm", "ammo", "silencer", "serial",
    "counterfeit", "fake id", "passport", "identity",
    "hitman", "assassin", "murder", "kill",
    "launder", "mixer", "tumbler", "cashout", "cash out",
]

def init_db():
    db = sqlite3.connect(DB)
    db.execute("""CREATE TABLE IF NOT EXISTS spectra_messages (
        id INTEGER, channel_id INTEGER, sender_id INTEGER,
        sender_name TEXT, date TEXT, text TEXT, has_media INTEGER DEFAULT 0,
        crime_score INTEGER DEFAULT 0,
        PRIMARY KEY (id, channel_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS spectra_channels (
        id INTEGER PRIMARY KEY, title TEXT, username TEXT,
        members INTEGER, date TEXT, crime_score INTEGER DEFAULT 0,
        last_archived TEXT
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS spectra_users (
        id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        last_name TEXT, bio TEXT, premium INTEGER, scam INTEGER,
        first_seen TEXT, last_seen TEXT
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS example_target_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER, channel_id INTEGER, channel_title TEXT,
        date TEXT, text TEXT, has_media INTEGER, media_type TEXT,
        recorded_at TEXT
    )""")
    for col, stmt in [
        ("sender_name", "ALTER TABLE spectra_messages ADD COLUMN sender_name TEXT DEFAULT ''"),
        ("crime_score", "ALTER TABLE spectra_messages ADD COLUMN crime_score INTEGER DEFAULT 0"),
        ("crime_score_ch", "ALTER TABLE spectra_channels ADD COLUMN crime_score INTEGER DEFAULT 0"),
        ("last_archived", "ALTER TABLE spectra_channels ADD COLUMN last_archived TEXT DEFAULT ''"),
    ]:
        try:
            db.execute(stmt)
        except sqlite3.OperationalError:
            pass
    db.execute("""CREATE INDEX IF NOT EXISTS idx_example_target_date ON example_target_activity(date)""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_msg_sender ON spectra_messages(sender_id)""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_msg_crime ON spectra_messages(crime_score)""")
    db.commit()
    db.close()

def score_text(text, keywords=CRIME_KEYWORDS):
    if not text:
        return 0
    t = text.lower()
    return sum(1 for kw in keywords if kw in t)

async def get_channel_list(client, label):
    result = await client(GetDialogsRequest(offset_date=None, offset_id=0, offset_peer=InputPeerEmpty(), limit=500, hash=0))
    channels = {}
    for chat in result.chats:
        if hasattr(chat, 'title'):
            cid = chat.id
            title = chat.title or ""
            title_lower = title.lower()
            username = getattr(chat, 'username', '') or ''
            members = getattr(chat, 'participants_count', 0) or 0
            score = sum(1 for kw in CRIME_KEYWORDS if kw in title_lower)
            channels[cid] = {
                'id': cid, 'title': title, 'username': username,
                'members': members, 'score': score, 'account': label,
            }
    return channels

async def archive_channel(client, ch_info, db, limit=5000):
    cid = ch_info['id']
    try:
        ch = await client.get_entity(cid)
    except Exception as e:
        print(f"  [{ch_info['title']}] SKIP: {e}", flush=True)
        return 0

    title = getattr(ch, 'title', ch_info['title'])
    members = getattr(ch, 'participants_count', 0) or 0
    username = getattr(ch, 'username', '') or ''
    crime_score = ch_info['score']

    print(f"  [{title}] ({members}m, cs={crime_score}) archiving...", flush=True)

    all_msgs = []
    offset_id = 0
    while len(all_msgs) < limit:
        try:
            msgs = await client(GetHistoryRequest(
                peer=ch, offset_id=offset_id, offset_date=None,
                add_offset=0, limit=100, max_id=0, min_id=0, hash=0
            ))
        except Exception as e:
            print(f"  [{title}] history error: {e}", flush=True)
            break
        if not msgs.messages:
            break
        all_msgs.extend(msgs.messages)
        offset_id = msgs.messages[-1].id
        if len(all_msgs) % 1000 == 0:
            print(f"    {len(all_msgs)} msgs...", flush=True)
        await asyncio.sleep(0.3)

    stored = 0
    example_target_count = 0
    for m in all_msgs:
        text = m.message or ""
        msg_crime = score_text(text)
        sender_id = m.sender_id or 0

        sender_name = ""
        if m.sender:
            sender_name = f"{getattr(m.sender, 'first_name', '') or ''} {getattr(m.sender, 'last_name', '') or ''}".strip()
            if getattr(m.sender, 'username', None):
                sender_name += f" @{m.sender.username}"

        try:
            db.execute(
                "INSERT OR REPLACE INTO spectra_messages (id, channel_id, sender_id, sender_name, date, text, has_media, crime_score) VALUES (?,?,?,?,?,?,?,?)",
                (m.id, cid, sender_id, sender_name, str(m.date), text, 1 if m.media else 0, msg_crime)
            )
            stored += 1
        except Exception:
            pass

        if sender_id == ATKLIB_ID:
            media_type = ""
            if m.media:
                media_type = type(m.media).__name__
            try:
                db.execute(
                    "INSERT OR REPLACE INTO example_target_activity (message_id, channel_id, channel_title, date, text, has_media, media_type, recorded_at) VALUES (?,?,?,?,?,?,?,?)",
                    (m.id, cid, title, str(m.date), text, 1 if m.media else 0, media_type, datetime.now(timezone.utc).isoformat())
                )
                example_target_count += 1
            except Exception:
                pass

    db.execute(
        "INSERT OR REPLACE INTO spectra_channels (id, title, username, members, date, crime_score, last_archived) VALUES (?,?,?,?,?,?,?)",
        (cid, title, username, members, str(getattr(ch, 'date', '')), crime_score, datetime.now(timezone.utc).isoformat())
    )
    db.commit()
    print(f"  [{title}] stored {stored}, @example_target: {example_target_count}", flush=True)
    return stored

async def track_example_target(client, db):
    try:
        atk = await client.get_entity("example_target")
        from telethon.tl.functions.users import GetFullUserRequest
        full = await client(GetFullUserRequest(atk.id))
        u = full.users[0]
        bio = full.full_user.about if hasattr(full, 'full_user') else None
        db.execute(
            "INSERT OR REPLACE INTO spectra_users (id, username, first_name, last_name, bio, premium, scam, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?)",
            (u.id, u.username, u.first_name, u.last_name, bio, u.premium, u.scam, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
        )
        db.commit()
        print(f"@example_target: {u.first_name} (@{u.username}) bio='{bio}'", flush=True)
    except Exception as e:
        print(f"@example_target track error: {e}", flush=True)

async def scan_example_target_in_channels(client, db, channel_ids):
    print(f"\n=== @example_target scan: {len(channel_ids)} channels ===", flush=True)
    total = 0
    for cid in channel_ids:
        try:
            ch = await client.get_entity(cid)
            msgs = await client.get_messages(ch, from_user=ATKLIB_ID, limit=100)
            if msgs:
                title = getattr(ch, 'title', str(cid))
                print(f"  [{title}] {len(msgs)} @example_target msgs", flush=True)
                for m in msgs:
                    media_type = type(m.media).__name__ if m.media else ""
                    db.execute(
                        "INSERT OR REPLACE INTO example_target_activity (message_id, channel_id, channel_title, date, text, has_media, media_type, recorded_at) VALUES (?,?,?,?,?,?,?,?)",
                        (m.id, cid, title, str(m.date), m.message or "", 1 if m.media else 0, media_type, datetime.now(timezone.utc).isoformat())
                    )
                    total += 1
                db.commit()
        except Exception:
            pass
        await asyncio.sleep(0.2)
    print(f"  Total @example_target: {total}", flush=True)

async def worker(account, channels_to_archive, db_lock):
    session, api_id, api_hash, label = account
    client = TelegramClient(session, api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print(f"[{label}] NOT AUTHORIZED", flush=True)
        await client.disconnect()
        return
    me = await client.get_me()
    print(f"[{label}] Connected as {me.first_name} (@{me.username})", flush=True)
    db = sqlite3.connect(DB, timeout=30)
    total = 0
    for ch_info in channels_to_archive:
        try:
            n = await archive_channel(client, ch_info, db, limit=5000)
            total += n
        except Exception as e:
            print(f"  [{ch_info['title']}] ERROR: {e}", flush=True)
        await asyncio.sleep(1)
    await track_example_target(client, db)
    db.close()
    await client.disconnect()
    print(f"[{label}] Done. Total: {total}", flush=True)

async def main():
    init_db()
    print("=== SPECTRA Dual-Account Archiver ===", flush=True)

    all_channels = {}
    for session, api_id, api_hash, label in ACCOUNTS:
        client = TelegramClient(session, api_id, api_hash)
        await client.connect()
        if await client.is_user_authorized():
            chs = await get_channel_list(client, label)
            for cid, info in chs.items():
                if cid not in all_channels or info['score'] > all_channels[cid]['score']:
                    all_channels[cid] = info
        await client.disconnect()

    ranked = sorted(all_channels.values(), key=lambda x: (x['score'], x['members']), reverse=True)
    print(f"Total channels: {len(ranked)}", flush=True)
    print(f"\n=== Priority queue (top 25) ===", flush=True)
    for i, ch in enumerate(ranked[:25]):
        print(f"  {i+1:3}. [s={ch['score']}] {ch['title']} ({ch['members']}m) @{ch['username'] or '—'} via {ch['account']}", flush=True)

    seen = set()
    john_final = []
    j_final = []
    for ch in ranked:
        if ch['id'] in seen:
            continue
        seen.add(ch['id'])
        if ch['account'] == 'John':
            john_final.append(ch)
        else:
            j_final.append(ch)

    print(f"\nJohn: {len(john_final)} channels, J: {len(j_final)} channels", flush=True)

    db_lock = asyncio.Lock()
    await asyncio.gather(
        worker(ACCOUNTS[0], john_final, db_lock),
        worker(ACCOUNTS[1], j_final, db_lock),
    )

    print("\n=== @example_target deep scan ===", flush=True)
    client = TelegramClient(ACCOUNTS[0][0], ACCOUNTS[0][1], ACCOUNTS[0][2])
    await client.connect()
    if await client.is_user_authorized():
        db = sqlite3.connect(DB, timeout=30)
        all_cids = [ch['id'] for ch in ranked]
        await scan_example_target_in_channels(client, db, all_cids)
        db.close()
    await client.disconnect()

    db = sqlite3.connect(DB, timeout=30)
    total_msgs = db.execute("SELECT COUNT(*) FROM spectra_messages").fetchone()[0]
    total_channels = db.execute("SELECT COUNT(*) FROM spectra_channels").fetchone()[0]
    example_target_msgs = db.execute("SELECT COUNT(*) FROM example_target_activity").fetchone()[0]
    high_crime = db.execute("SELECT COUNT(*) FROM spectra_messages WHERE crime_score > 0").fetchone()[0]
    print(f"\n=== SUMMARY ===", flush=True)
    print(f"  Channels: {total_channels}", flush=True)
    print(f"  Messages: {total_msgs}", flush=True)
    print(f"  Crime-flagged: {high_crime}", flush=True)
    print(f"  @example_target tracked: {example_target_msgs}", flush=True)
    print(f"\n=== @example_target recent ===", flush=True)
    for row in db.execute("SELECT channel_title, date, substr(text,1,80) FROM example_target_activity ORDER BY date DESC LIMIT 15"):
        print(f"  [{row[1][:19]}] {row[0]}: {row[2]}", flush=True)
    db.close()
    print("\nDone!", flush=True)

asyncio.run(main())
