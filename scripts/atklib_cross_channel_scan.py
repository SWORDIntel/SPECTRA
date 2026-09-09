#!/usr/bin/env python3
"""
SPECTRA Cross-Channel Scan — find ALL channels where a target user has posted.

For a given target user_id, iterates through every dialog/channel the account
has access to and searches for messages authored by that user. Records any
channel where the target is found into target_channels, then does a full
historical backfill of those channels.

Usage:
    python3 scripts/atklib_cross_channel_scan.py --target atklib --limit 50000
    python3 scripts/atklib_cross_channel_scan.py --target atklib --scan-only
    python3 scripts/atklib_cross_channel_scan.py --target atklib --backfill-only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel, Chat, User

logger = logging.getLogger("cross_channel_scan")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
TZ = timezone.utc

# Import helpers from target_collect
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from target_collect import (
    get_db_path,
    get_config,
    ensure_target_tables,
    get_targets,
    get_surveillance_aliases,
    get_collected_channels,
    record_channel,
    update_collection_progress,
    store_message,
    store_user,
    get_last_message_id,
    _safe_commit,
    collect_persona_examples,
)


def _retry_db(fn, *, max_retries: int = 5, base_delay: float = 1.0):
    for attempt in range(max_retries):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" in str(e) or "busy" in str(e):
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    _time.sleep(delay)
                else:
                    raise
            else:
                raise
    return None


async def scan_all_dialogs_for_user(
    client: TelegramClient,
    target_uid: int,
    conn: sqlite3.Connection,
    target_id: str,
    search_limit: int = 100,
) -> List[Dict[str, Any]]:
    """Scan all dialogs for messages from target_uid.

    For each dialog, uses iter_messages with from_user filter to check if the
    target has posted there. Returns list of discovered channel dicts.
    """
    discovered: Dict[int, Dict[str, Any]] = {}
    already_known = get_collected_channels(conn, target_id)
    already_known_ids = set(already_known.keys())

    logger.info(f"  Getting all dialogs...")
    dialogs = await client.get_dialogs()
    logger.info(f"  Total dialogs: {len(dialogs)}")

    scanned = 0
    for d in dialogs:
        e = d.entity
        if isinstance(e, User):
            continue  # skip DMs for now

        if isinstance(e, (Channel, Chat)):
            ch_id = e.id
            title = e.title
            username = getattr(e, "username", None)
            if isinstance(e, Channel):
                ch_type = "broadcast" if e.broadcast else "megagroup"
            else:
                ch_type = "small_group"
            participants = getattr(e, "participants_count", 0) or 0
        else:
            continue

        scanned += 1

        # Skip channels we already know about (unless we want to recheck)
        if ch_id in already_known_ids:
            logger.debug(f"  [{scanned}] {title} — already in target_channels, skipping scan")
            continue

        # Search for messages from the target user in this channel
        try:
            target_entity = await client.get_entity(target_uid)
            found_count = 0
            async for msg in client.iter_messages(
                e, limit=search_limit, from_user=target_entity
            ):
                found_count += 1
                if found_count >= 1:
                    break

            if found_count > 0:
                logger.info(f"  [{scanned}] FOUND: {title} (@{username}, {ch_type}, "
                           f"{participants} members) — target has posted here")

                # Get full channel info
                about = ""
                try:
                    full = await client(GetFullChannelRequest(e))
                    about = full.full_chat.about or ""
                    participants = full.full_chat.participants_count or participants
                except Exception:
                    pass

                discovered[ch_id] = {
                    "id": ch_id,
                    "title": title,
                    "username": username,
                    "type": ch_type,
                    "participants": participants,
                    "about": about,
                    "discovered_via": "cross_channel_scan",
                }
            else:
                if scanned % 50 == 0:
                    logger.info(f"  [{scanned}/{len(dialogs)}] scanned, no target posts found so far")

        except Exception as e_err:
            logger.debug(f"  [{scanned}] Error scanning {title}: {e_err}")

    logger.info(f"  Scan complete: {scanned} dialogs scanned, {len(discovered)} new channels found")
    return list(discovered.values())


async def backfill_channel_history(
    client: TelegramClient,
    conn: sqlite3.Connection,
    target: dict,
    channel: dict,
    limit: int = 50000,
    batch_size: int = 500,
) -> Tuple[int, int]:
    """Full historical backfill of a channel — pull ALL messages from the beginning.

    Returns (total_stored, target_messages_stored).
    """
    ch_id = channel["id"] if "id" in channel else channel["channel_id"]
    target_uid = int(target["platform_user_id"]) if target.get("platform_user_id") else None
    title = channel.get("title", channel.get("channel_title", str(ch_id)))

    # For backfill, we start from the beginning (offset_id=0)
    # But check if we already have messages — if so, get the min message ID
    # and pull everything before it
    try:
        row = conn.execute(
            "SELECT MIN(id) FROM messages WHERE channel_id = ?", (ch_id,)
        ).fetchone()
        existing_min_global = row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        existing_min_global = None

    # Convert global ID back to channel msg_id
    existing_min_msg = None
    if existing_min_global:
        existing_min_msg = existing_min_global % 1_000_000_000

    logger.info(f"  Backfilling '{title}' (ch={ch_id}, limit={limit})"
                + (f", existing min msg_id={existing_min_msg}" if existing_min_msg else ", full from start"))

    total_stored = 0
    target_msgs = 0
    last_msg_id = 0

    try:
        entity = await client.get_entity(ch_id)
    except Exception as e:
        logger.error(f"  Cannot access channel {ch_id} ({title}): {e}")
        return 0, 0

    kwargs = {
        "limit": limit,
        "reverse": True,  # oldest first
        "wait_time": 2,
    }
    # Use incremental offset if we already have messages (skip already-collected)
    if existing_min_global:
        # We already have messages — continue from the max msg_id we have
        row_max = conn.execute(
            "SELECT MAX(id) FROM messages WHERE channel_id = ?", (ch_id,)
        ).fetchone()
        existing_max_global = row_max[0] if row_max and row_max[0] else None
        if existing_max_global:
            existing_max_msg = existing_max_global % 1_000_000_000
            kwargs["offset_id"] = existing_max_msg
            logger.info(f"  Using incremental offset_id={existing_max_msg} (skipping already-collected)")

    batch_count = 0
    try:
        async for msg in client.iter_messages(entity, **kwargs):
            msg_date = msg.date.astimezone(TZ).isoformat() if msg.date else None
            edit_date = msg.edit_date.astimezone(TZ).isoformat() if msg.edit_date else None

            msg_data = {
                "id": msg.id,
                "user_id": msg.sender_id,
                "date": msg_date,
                "edit_date": edit_date,
                "content": msg.message,
                "reply_to": msg.reply_to_msg_id,
                "channel_id": ch_id,
            }

            is_new = store_message(conn, msg_data)
            if is_new:
                total_stored += 1

                if msg.sender:
                    store_user(conn, {
                        "id": msg.sender_id,
                        "username": getattr(msg.sender, "username", None),
                        "first_name": getattr(msg.sender, "first_name", None),
                        "last_name": getattr(msg.sender, "last_name", None),
                        "avatar_path": None,
                    })

                # Track target-authored messages
                is_target_msg = False
                if target_uid and msg.sender_id == target_uid:
                    is_target_msg = True
                elif channel.get("discovered_via") == "personal_channel":
                    is_target_msg = True

                if is_target_msg:
                    target_msgs += 1

            last_msg_id = max(last_msg_id, msg.id)
            batch_count += 1

            if batch_count % batch_size == 0:
                _safe_commit(conn)
                logger.info(f"    ... {batch_count} messages processed ({total_stored} new, {target_msgs} target)")

    except Exception as e:
        logger.error(f"  Error backfilling '{title}': {e}")

    _safe_commit(conn)
    update_collection_progress(conn, target["target_id"], ch_id, last_msg_id, total_stored)
    logger.info(f"  Done: {total_stored} new messages ({target_msgs} by target) from '{title}'")
    return total_stored, target_msgs


async def main():
    parser = argparse.ArgumentParser(description="SPECTRA Cross-Channel Scan for target user")
    parser.add_argument("--target", "-t", required=True, help="Target ID (e.g. atklib)")
    parser.add_argument("--limit", "-l", type=int, default=50000, help="Max messages per channel backfill")
    parser.add_argument("--scan-limit", type=int, default=100,
                        help="Max messages to search per dialog during scan (default 100)")
    parser.add_argument("--scan-only", "-s", action="store_true",
                        help="Only scan for channels, don't backfill")
    parser.add_argument("--backfill-only", "-b", action="store_true",
                        help="Only backfill already-discovered channels (skip scan)")
    parser.add_argument("--account", type=int, default=0,
                        help="Account index to use (default 0)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--db", help="Database path (default: from config)")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else get_db_path()
    cfg = get_config()

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path, timeout=300)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=300000")
    ensure_target_tables(conn)

    # Also ensure SPECTRA schema
    try:
        from tgarchive.db.schema import SCHEMA_SQL
        conn.executescript(SCHEMA_SQL)
        _safe_commit(conn)
    except Exception:
        pass

    # Get target
    targets = get_targets(conn, args.target)
    if not targets:
        logger.error(f"Target '{args.target}' not found in persona_targets")
        sys.exit(1)

    target = targets[0]
    target_uid = int(target["platform_user_id"])
    target_id = target["target_id"]

    logger.info(f"═══ Cross-Channel Scan: {target_id} (uid={target_uid}) ═══")

    # Use specified account
    acc = cfg["accounts"][args.account]
    session_path = f"{acc.get('session_dir', '.')}/{acc['session_name']}"

    result = {
        "target_id": target_id,
        "platform_user_id": target_uid,
        "channels_scanned": 0,
        "channels_discovered": 0,
        "channels_backfilled": 0,
        "messages_stored": 0,
        "target_messages": 0,
        "persona_examples_collected": 0,
        "discovered_channels": [],
        "errors": [],
    }

    all_channels: List[Dict[str, Any]] = []

    async with TelegramClient(
        session_path, acc["api_id"], acc["api_hash"]
    ) as client:
        await client.connect()
        if not await client.is_user_authorized():
            logger.error(f"  Account not authorized: {acc['session_name']}")
            result["errors"].append("account_not_authorized")
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            conn.close()
            return

        # ── Phase 1: Scan ──
        if not args.backfill_only:
            logger.info("  Phase 1: Scanning all dialogs for target messages...")
            discovered = await scan_all_dialogs_for_user(
                client, target_uid, conn, target_id, search_limit=args.scan_limit
            )
            result["channels_discovered"] = len(discovered)

            for ch in discovered:
                logger.info(f"    → {ch['title']} (@{ch.get('username')}, {ch['type']}, "
                           f"{ch['participants']} members, via {ch['discovered_via']})")
                record_channel(
                    conn, target_id, ch["id"], ch["title"], ch.get("username"),
                    ch["type"], ch["participants"], ch.get("about", ""), ch["discovered_via"],
                )
                result["discovered_channels"].append({
                    "id": ch["id"],
                    "title": ch["title"],
                    "username": ch.get("username"),
                    "type": ch["type"],
                    "participants": ch["participants"],
                    "discovered_via": ch["discovered_via"],
                })
                all_channels.append(ch)

        # Also include already-known channels from target_channels
        known = get_collected_channels(conn, target_id)
        for ch_id, ch_info in known.items():
            if ch_id not in {c["id"] for c in all_channels}:
                all_channels.append({
                    "id": ch_id,
                    "title": ch_info.get("channel_title", str(ch_id)),
                    "username": ch_info.get("channel_username"),
                    "type": ch_info.get("channel_type", "unknown"),
                    "participants": ch_info.get("participants", 0),
                    "about": ch_info.get("about", ""),
                    "discovered_via": ch_info.get("discovered_via", "existing"),
                })

        # Also check channels where atklib has messages but isn't in target_channels
        try:
            rows = conn.execute(
                "SELECT channel_id, COUNT(*) c FROM messages WHERE user_id = ? "
                "AND channel_id IS NOT NULL AND channel_id != 0 "
                "GROUP BY channel_id ORDER BY c DESC",
                (target_uid,),
            ).fetchall()
            for row in rows:
                ch_id = row["channel_id"]
                if ch_id not in {c["id"] for c in all_channels}:
                    # Get channel info from channel_network
                    cn = conn.execute(
                        "SELECT * FROM channel_network WHERE channel_id = ?", (ch_id,)
                    ).fetchone()
                    if cn:
                        ch_dict = {
                            "id": ch_id,
                            "title": cn["channel_title"],
                            "username": cn["channel_username"],
                            "type": cn["channel_type"],
                            "participants": cn["participants"],
                            "about": cn["about"],
                            "discovered_via": "existing_messages",
                        }
                        logger.info(f"    → {ch_dict['title']} (found via existing messages, "
                                   f"{row['c']} target msgs)")
                        record_channel(
                            conn, target_id, ch_id, ch_dict["title"], ch_dict.get("username"),
                            ch_dict["type"], ch_dict["participants"], ch_dict.get("about", ""),
                            "existing_messages",
                        )
                        all_channels.append(ch_dict)
                        result["channels_discovered"] += 1
                        result["discovered_channels"].append({
                            "id": ch_id,
                            "title": ch_dict["title"],
                            "username": ch_dict.get("username"),
                            "type": ch_dict["type"],
                            "participants": ch_dict["participants"],
                            "discovered_via": "existing_messages",
                        })
        except Exception as e:
            logger.debug(f"  Error checking existing messages: {e}")

        result["channels_scanned"] = len(all_channels)

        # ── Phase 2: Backfill ──
        if not args.scan_only:
            logger.info(f"  Phase 2: Backfilling {len(all_channels)} channels...")
            for i, ch in enumerate(all_channels):
                logger.info(f"  [{i+1}/{len(all_channels)}] Backfilling '{ch['title']}'")
                try:
                    stored, target_msgs = await backfill_channel_history(
                        client, conn, target, ch, limit=args.limit
                    )
                    result["messages_stored"] += stored
                    result["target_messages"] += target_msgs
                    result["channels_backfilled"] += 1
                except Exception as e:
                    logger.error(f"  Error backfilling '{ch['title']}': {e}")
                    result["errors"].append(f"{ch['title']}: {e}")

    # ── Phase 3: Collect persona examples ──
    if not args.scan_only:
        logger.info("  Phase 3: Collecting persona examples from all channels...")
        examples = collect_persona_examples(conn, target, all_channels)
        result["persona_examples_collected"] = examples
        logger.info(f"  Collected {examples} persona examples")

    conn.close()

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"\n═══ Cross-Channel Scan Summary ═══")
        print(f"  Target: {result['target_id']} (uid={result['platform_user_id']})")
        print(f"  Channels discovered: {result['channels_discovered']}")
        print(f"  Channels backfilled: {result['channels_backfilled']}")
        print(f"  Messages stored:     {result['messages_stored']}")
        print(f"  Target messages:     {result['target_messages']}")
        print(f"  Persona examples:    {result['persona_examples_collected']}")
        if result["discovered_channels"]:
            print(f"\n  Discovered channels:")
            for ch in result["discovered_channels"]:
                uname = f"@{ch['username']}" if ch.get("username") else "(private)"
                print(f"    {uname:<25} {ch['type']:<12} {ch['participants']:>7} subs  {ch['title']}")
        if result["errors"]:
            print(f"\n  Errors: {len(result['errors'])}")
            for e in result["errors"][:10]:
                print(f"    - {e}")


if __name__ == "__main__":
    asyncio.run(main())
