#!/usr/bin/env python3
"""
SPECTRA Channel Network Mapper
================================

For each target channel:
  1. Pulls all members (from megagroups — broadcast channels don't expose members)
  2. For each member, fetches their full profile (bio, personal channel)
  3. Extracts channel mentions from bios (@usernames, t.me/ links)
  4. Resolves discovered channels and records their metadata
  5. Builds a cross-reference map: which users are in which channels
  6. Outputs a dedup-friendly channel list with overlap scores

This helps the scraper avoid re-scraping the same channels and identifies
network clusters where targets and their contacts co-occur.

Usage:
    python3 scripts/channel_network_map.py --target notprequel
    python3 scripts/channel_network_map.py --all-targets
    python3 scripts/channel_network_map.py --target notprequel --depth 2
    python3 scripts/channel_network_map.py --target notprequel --output channels.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest, GetFullChannelRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import (
    Channel, Chat, User,
    ChannelParticipantsRecent, ChannelParticipantsSearch,
)

logger = logging.getLogger("channel_network")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TZ = timezone.utc
USERNAME_RE = re.compile(r"@([a-zA-Z0-9_]{5,64})")
URL_RE = re.compile(r"https?://t\.me/([a-zA-Z0-9_]{5,64})")


def get_db_path() -> Path:
    cfg_path = PROJECT_ROOT / "spectra_config.json"
    with open(cfg_path) as f:
        cfg = json.load(f)
    db_path = cfg.get("db_path", "spectra.sqlite3")
    candidates = [
        PROJECT_ROOT / db_path,
        PROJECT_ROOT / "data" / db_path,
        PROJECT_ROOT / "data" / "spectra.db",
        PROJECT_ROOT / "spectra.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def get_config() -> dict:
    with open(PROJECT_ROOT / "spectra_config.json") as f:
        return json.load(f)


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS channel_network (
            channel_id    BIGINT PRIMARY KEY,
            channel_title TEXT,
            channel_username TEXT,
            channel_type  TEXT,
            participants  INTEGER,
            about         TEXT,
            discovered_via TEXT,
            discovered_at TEXT,
            already_scraped INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS channel_members (
            channel_id  BIGINT NOT NULL,
            user_id     BIGINT NOT NULL,
            username    TEXT,
            first_name  TEXT,
            last_name   TEXT,
            bio         TEXT,
            personal_channel_id BIGINT,
            first_seen   TEXT,
            PRIMARY KEY (channel_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_channel_members_user ON channel_members(user_id);
        CREATE INDEX IF NOT EXISTS idx_channel_members_channel ON channel_members(channel_id);
        CREATE TABLE IF NOT EXISTS user_channels (
            user_id     BIGINT NOT NULL,
            channel_id  BIGINT NOT NULL,
            discovered_via TEXT,
            PRIMARY KEY (user_id, channel_id)
        );
        CREATE INDEX IF NOT EXISTS idx_user_channels_user ON user_channels(user_id);
    """)
    conn.commit()


def extract_usernames_from_text(text: str) -> List[str]:
    found = set()
    for m in USERNAME_RE.finditer(text or ""):
        found.add(m.group(1))
    for m in URL_RE.finditer(text or ""):
        found.add(m.group(1))
    return list(found)


# ── Core logic ────────────────────────────────────────────────────────────

async def get_channel_members(
    client: TelegramClient,
    channel_id: int,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Get members from a megagroup. Returns list of user dicts."""
    try:
        entity = await client.get_entity(channel_id)
    except Exception as e:
        logger.warning(f"  Cannot resolve channel {channel_id}: {e}")
        return []

    if getattr(entity, "broadcast", False):
        logger.info(f"  Channel {channel_id} is broadcast — members not accessible")
        return []

    members = []
    offset = 0
    batch = 200

    while offset < limit:
        try:
            result = await client(GetParticipantsRequest(
                channel=entity,
                filter=ChannelParticipantsRecent(),
                offset=offset,
                limit=min(batch, limit - offset),
                hash=0,
            ))
            if not result.users:
                break
            for u in result.users:
                members.append({
                    "user_id": u.id,
                    "username": u.username,
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                })
            offset += len(result.users)
            if len(result.users) < batch:
                break
            await asyncio.sleep(1)  # rate limit
        except Exception as e:
            logger.warning(f"  Error getting participants at offset {offset}: {e}")
            break

    return members


async def get_user_bio_and_channels(
    client: TelegramClient,
    user_id: int,
) -> Dict[str, Any]:
    """Get a user's bio and personal channel."""
    info = {"bio": None, "personal_channel_id": None, "bio_channels": []}
    try:
        entity = await client.get_entity(user_id)
        full = await client(GetFullUserRequest(entity))
        info["bio"] = full.full_user.about
        info["personal_channel_id"] = full.full_user.personal_channel_id

        # Extract channel mentions from bio
        if info["bio"]:
            for uname in extract_usernames_from_text(info["bio"]):
                info["bio_channels"].append(uname)
    except Exception as e:
        logger.debug(f"  Could not get full user {user_id}: {e}")

    return info


async def resolve_channel(
    client: TelegramClient,
    identifier: Any,
) -> Optional[Dict[str, Any]]:
    """Resolve a channel by ID or username. Returns channel dict or None."""
    try:
        entity = await client.get_entity(identifier)
        if not isinstance(entity, (Channel, Chat)):
            return None

        ch_id = entity.id
        title = entity.title
        username = entity.username
        ch_type = "broadcast" if getattr(entity, "broadcast", False) else "megagroup"

        # Get full info
        about = ""
        participants = getattr(entity, "participants_count", 0) or 0
        try:
            full = await client(GetFullChannelRequest(entity))
            about = full.full_chat.about or ""
            participants = full.full_chat.participants_count or participants
        except Exception:
            pass

        return {
            "id": ch_id,
            "title": title,
            "username": username,
            "type": ch_type,
            "participants": participants,
            "about": about,
        }
    except Exception as e:
        logger.debug(f"  Could not resolve channel {identifier}: {e}")
        return None


def store_channel(conn: sqlite3.Connection, ch: Dict[str, Any], discovered_via: str) -> None:
    now = datetime.now(TZ).isoformat()
    conn.execute("""
        INSERT OR IGNORE INTO channel_network
        (channel_id, channel_title, channel_username, channel_type,
         participants, about, discovered_via, discovered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (ch["id"], ch["title"], ch.get("username"), ch["type"],
          ch["participants"], ch.get("about", ""), discovered_via, now))
    conn.commit()


def store_member(conn: sqlite3.Connection, channel_id: int, user: Dict[str, Any],
                 bio: str, personal_ch: Optional[int]) -> None:
    now = datetime.now(TZ).isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO channel_members
        (channel_id, user_id, username, first_name, last_name, bio,
         personal_channel_id, first_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (channel_id, user["user_id"], user.get("username"),
          user.get("first_name"), user.get("last_name"), bio, personal_ch, now))
    conn.commit()


def store_user_channel(conn: sqlite3.Connection, user_id: int, channel_id: int, via: str) -> None:
    conn.execute("""
        INSERT OR IGNORE INTO user_channels
        (user_id, channel_id, discovered_via) VALUES (?, ?, ?)
    """, (user_id, channel_id, via))
    conn.commit()


async def map_target_network(
    client: TelegramClient,
    conn: sqlite3.Connection,
    target_id: str,
    target_channels: List[Dict[str, Any]],
    member_limit: int = 500,
    resolve_bios: bool = True,
) -> Dict[str, Any]:
    """
    Map the channel network for a target.

    1. Get members from each target channel (megagroups only)
    2. For each member, get their bio + personal channel
    3. Resolve discovered channels
    4. Build cross-reference map
    """
    result = {
        "target_id": target_id,
        "seed_channels": len(target_channels),
        "members_found": 0,
        "bios_checked": 0,
        "channels_discovered": 0,
        "overlap_map": {},
    }

    all_members: Dict[int, Dict[str, Any]] = {}  # user_id → user info
    member_channels: Dict[int, Set[int]] = defaultdict(set)  # user_id → channel IDs

    # Phase 1: Get members from each seed channel
    for ch in target_channels:
        ch_id = ch["id"]
        logger.info(f"  Getting members from '{ch['title']}' (ch={ch_id})...")

        # Store the seed channel
        store_channel(conn, ch, f"seed:{target_id}")

        members = await get_channel_members(client, ch_id, limit=member_limit)
        logger.info(f"    Found {len(members)} members")

        for m in members:
            all_members[m["user_id"]] = m
            member_channels[m["user_id"]].add(ch_id)
            store_member(conn, ch_id, m, None, None)
            store_user_channel(conn, m["user_id"], ch_id, f"seed:{target_id}")

        result["members_found"] += len(members)

    # Phase 2: Get bios + personal channels for each member
    if resolve_bios:
        logger.info(f"  Resolving bios for {len(all_members)} members...")
        discovered_channels: Dict[int, Dict[str, Any]] = {}

        for i, (uid, user) in enumerate(all_members.items()):
            if (i + 1) % 50 == 0:
                logger.info(f"    ... {i+1}/{len(all_members)} bios checked")

            try:
                info = await get_user_bio_and_channels(client, uid)
                result["bios_checked"] += 1

                # Store bio
                store_member(conn, 0, user, info["bio"], info.get("personal_channel_id"))
                # Update existing record
                for ch_id in member_channels[uid]:
                    conn.execute("""
                        UPDATE channel_members SET bio = ?, personal_channel_id = ?
                        WHERE channel_id = ? AND user_id = ?
                    """, (info["bio"], info.get("personal_channel_id"), ch_id, uid))
                conn.commit()

                # Personal channel
                if info.get("personal_channel_id"):
                    pch_id = info["personal_channel_id"]
                    if pch_id not in discovered_channels:
                        pch = await resolve_channel(client, pch_id)
                        if pch:
                            discovered_channels[pch_id] = pch
                            store_channel(conn, pch, f"personal_channel:{uid}")
                            logger.info(f"    New channel from @{user.get('username', uid)}: {pch['title']}")
                    store_user_channel(conn, uid, pch_id, "personal_channel")

                # Bio-mentioned channels
                for uname in info.get("bio_channels", []):
                    ch = await resolve_channel(client, uname)
                    if ch and ch["id"] not in discovered_channels:
                        discovered_channels[ch["id"]] = ch
                        store_channel(conn, ch, f"bio:{uid}:{uname}")
                        logger.info(f"    New channel from @{user.get('username', uid)} bio: {ch['title']}")
                    if ch:
                        store_user_channel(conn, uid, ch["id"], f"bio:{uname}")

                await asyncio.sleep(0.5)  # rate limit

            except Exception as e:
                logger.debug(f"    Error processing user {uid}: {e}")

        result["channels_discovered"] = len(discovered_channels)

    # Phase 3: Build overlap map — which channels share members
    logger.info("  Building channel overlap map...")
    channel_users: Dict[int, Set[int]] = defaultdict(set)
    for uid, ch_ids in member_channels.items():
        for ch_id in ch_ids:
            channel_users[ch_id].add(uid)

    # Find channels that share members with seed channels
    overlap: Dict[int, int] = {}  # channel_id → shared_member_count
    seed_ch_ids = {ch["id"] for ch in target_channels}
    for uid, ch_ids in member_channels.items():
        for ch_id in ch_ids:
            if ch_id not in seed_ch_ids:
                overlap[ch_id] = overlap.get(ch_id, 0) + 1

    result["overlap_map"] = {str(k): v for k, v in sorted(overlap.items(), key=lambda x: -x[1])}

    return result


async def main():
    parser = argparse.ArgumentParser(description="SPECTRA Channel Network Mapper")
    parser.add_argument("--target", "-t", help="Specific target ID")
    parser.add_argument("--all-targets", "-a", action="store_true", help="Map all targets")
    parser.add_argument("--member-limit", "-m", type=int, default=500, help="Max members to pull per channel")
    parser.add_argument("--no-bios", action="store_true", help="Skip bio resolution (faster)")
    parser.add_argument("--output", "-o", help="Output JSON file for channel list")
    parser.add_argument("--db", help="Database path")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else get_db_path()
    cfg = get_config()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_tables(conn)

    # Get target channels from target_channels table
    if args.target:
        rows = conn.execute(
            "SELECT * FROM target_channels WHERE target_id = ?", (args.target,)
        ).fetchall()
    elif args.all_targets:
        rows = conn.execute("SELECT * FROM target_channels").fetchall()
    else:
        parser.error("Specify --target or --all-targets")

    if not rows:
        logger.error("No target channels found. Run target_collect.py first.")
        sys.exit(1)

    # Group channels by target
    target_channels: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        target_channels[r["target_id"]].append(dict(r))

    logger.info(f"Found {len(target_channels)} target(s) with {sum(len(v) for v in target_channels.values())} channels")

    # Use first account
    acc = cfg["accounts"][0]
    session_path = f"{acc.get('session_dir', '.')}/{acc['session_name']}"

    all_results = []
    all_discovered = []

    async with TelegramClient(session_path, acc["api_id"], acc["api_hash"]) as client:
        await client.connect()
        if not await client.is_user_authorized():
            logger.error("Account not authorized")
            sys.exit(1)

        for target_id, channels in target_channels.items():
            logger.info(f"═══ Mapping network for: {target_id} ═══")

            # Convert target_channels rows to channel dicts
            ch_list = []
            for ch in channels:
                ch_list.append({
                    "id": ch["channel_id"],
                    "title": ch["channel_title"],
                    "username": ch.get("channel_username"),
                    "type": ch.get("channel_type", "megagroup"),
                    "participants": ch.get("participants", 0),
                    "about": ch.get("about", ""),
                })

            result = await map_target_network(
                client, conn, target_id, ch_list,
                member_limit=args.member_limit,
                resolve_bios=not args.no_bios,
            )
            all_results.append(result)

    # Build final channel list for dedup
    logger.info("\n═══ Channel Network Summary ═══")

    # Get all discovered channels
    ch_rows = conn.execute("""
        SELECT * FROM channel_network ORDER BY participants DESC
    """).fetchall()

    channels_list = []
    for r in ch_rows:
        channels_list.append({
            "channel_id": r["channel_id"],
            "title": r["channel_title"],
            "username": r["channel_username"],
            "type": r["channel_type"],
            "participants": r["participants"],
            "about": r["about"],
            "discovered_via": r["discovered_via"],
            "already_scraped": bool(r["already_scraped"]),
        })

    # Get overlap stats
    overlap_rows = conn.execute("""
        SELECT channel_id, COUNT(DISTINCT user_id) as member_count
        FROM channel_members
        WHERE channel_id != 0
        GROUP BY channel_id
        ORDER BY member_count DESC
    """).fetchall()

    overlap_map = {r["channel_id"]: r["member_count"] for r in overlap_rows}

    # Get user → channel mapping
    user_ch_rows = conn.execute("""
        SELECT user_id, channel_id, discovered_via FROM user_channels
    """).fetchall()

    user_channels_map = defaultdict(list)
    for r in user_ch_rows:
        user_channels_map[r["user_id"]].append({
            "channel_id": r["channel_id"],
            "via": r["discovered_via"],
        })

    # Print summary
    print(f"\n{'='*70}")
    print(f"CHANNEL NETWORK MAP — {len(channels_list)} channels discovered")
    print(f"{'='*70}")
    print(f"{'Channel':<40} {'Type':<12} {'Members':<10} {'Scraped':<8} {'Via'}")
    print(f"{'-'*40} {'-'*12} {'-'*10} {'-'*8} {'-'*20}")
    for ch in channels_list:
        title = ch["title"][:38] if ch["title"] else str(ch["channel_id"])
        uname = f"@{ch['username']}" if ch["username"] else ""
        print(f"{title:<40} {ch['type']:<12} {ch['participants']:<10} {'yes' if ch['already_scraped'] else 'no':<8} {ch['discovered_via'][:20]}")
        if uname:
            print(f"  {uname}")

    print(f"\n{'='*70}")
    print(f"MEMBER OVERLAP — channels ranked by shared members")
    print(f"{'='*70}")
    for ch_id, count in sorted(overlap_map.items(), key=lambda x: -x[1])[:20]:
        ch_info = next((c for c in channels_list if c["channel_id"] == ch_id), None)
        if ch_info:
            print(f"  {ch_info['title']:<40} {count} shared members  @{ch_info.get('username', '-')}")

    print(f"\n{'='*70}")
    print(f"USER CHANNELS — top users by channel count")
    print(f"{'='*70}")
    top_users = sorted(user_channels_map.items(), key=lambda x: len(x[1]), reverse=True)[:20]
    for uid, chs in top_users:
        # Get user info
        user_row = conn.execute(
            "SELECT username, first_name FROM channel_members WHERE user_id = ? LIMIT 1",
            (uid,)
        ).fetchone()
        if user_row and user_row["username"]:
            name = f"@{user_row['username']}"
        else:
            name = f"uid={uid}"
        fname = (user_row["first_name"] if user_row and user_row["first_name"] else "") or ""
        print(f"  {name:<25} {fname:<15} {len(chs)} channels")

    # Output JSON if requested
    if args.output:
        output_data = {
            "timestamp": datetime.now(TZ).isoformat(),
            "targets": all_results,
            "channels": channels_list,
            "overlap_map": {str(k): v for k, v in overlap_map.items()},
            "user_channels": {str(k): v for k, v in user_channels_map.items()},
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2, default=str)
        logger.info(f"Channel list written to {args.output}")

    # Also save a dedup-friendly channel list for the scraper
    dedup_path = PROJECT_ROOT / "data" / "channel_dedup_list.json"
    dedup_data = {
        "generated_at": datetime.now(TZ).isoformat(),
        "total_channels": len(channels_list),
        "channels": [
            {
                "channel_id": ch["channel_id"],
                "username": ch["username"],
                "title": ch["title"],
                "type": ch["type"],
                "participants": ch["participants"],
                "already_scraped": ch["already_scraped"],
                "shared_members": overlap_map.get(ch["channel_id"], 0),
            }
            for ch in channels_list
        ],
    }
    with open(dedup_path, "w") as f:
        json.dump(dedup_data, f, indent=2, default=str)
    logger.info(f"Dedup channel list: {dedup_path}")

    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
