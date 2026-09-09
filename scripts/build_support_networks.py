#!/usr/bin/env python3
"""
SPECTRA Support Network Builder
================================

Auto-builds contact/support networks for ALL users we have scraped.
Every user we pull gets stored in QIHSE, and we build up their support
network by:

  1. Finding all channels a user is in (from messages + channel_members)
  2. Finding all co-members in those channels (their support network)
  3. Computing overlap scores between users (shared channels = support link)
  4. Storing the network graph in SQLite + IndexOutbox → QIHSE graph projection

This runs offline (no Telethon needed) — it works purely from data already
in the SQLite database. It can be run after every crawl batch to keep
networks up to date.

Schema:
  support_network_nodes   — one row per user with aggregate stats
  support_network_edges   — one row per (user_a, user_b) co-channel link
  support_network_channels — one row per (user, channel) membership

Usage:
    python3 scripts/build_support_networks.py                    # build for all
    python3 scripts/build_support_networks.py --user 925719843   # build for one
    python3 scripts/build_support_networks.py --min-shared 2     # only edges with 2+ shared channels
    python3 scripts/build_support_networks.py --stats            # show network stats
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("support_network")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
TZ = timezone.utc

DB_PATH = PROJECT_ROOT / "data" / "spectra.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS support_network_nodes (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    channel_count INTEGER DEFAULT 0,
    co_member_count INTEGER DEFAULT 0,
    edge_count INTEGER DEFAULT 0,
    is_primary_target INTEGER DEFAULT 0,
    target_id TEXT,
    first_seen TEXT,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS support_network_edges (
    user_a INTEGER NOT NULL,
    user_b INTEGER NOT NULL,
    shared_channels INTEGER NOT NULL DEFAULT 0,
    shared_channel_ids TEXT,
    edge_weight REAL DEFAULT 0.0,
    first_seen TEXT,
    last_updated TEXT,
    PRIMARY KEY (user_a, user_b)
);

CREATE TABLE IF NOT EXISTS support_network_channels (
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    channel_title TEXT,
    channel_username TEXT,
    channel_type TEXT,
    message_count INTEGER DEFAULT 0,
    first_seen TEXT,
    last_updated TEXT,
    PRIMARY KEY (user_id, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_sne_a ON support_network_edges(user_a);
CREATE INDEX IF NOT EXISTS idx_sne_b ON support_network_edges(user_b);
CREATE INDEX IF NOT EXISTS idx_snc_uid ON support_network_channels(user_id);
CREATE INDEX IF NOT EXISTS idx_snc_cid ON support_network_channels(channel_id);
"""


# Primary targets — flagged in the network
PRIMARY_TARGETS = {
    71115026: {"target_id": "notprequel", "username": "notprequel"},
    8000000005: {"target_id": "example_target", "username": "example_target"},
    925719843: {"target_id": "notdurandal", "username": "notdurandal"},
}


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create support network tables if they don't exist."""
    conn.executescript(SCHEMA)
    conn.commit()


def get_all_users(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Get all users from the users table."""
    rows = conn.execute(
        "SELECT id, username, first_name, last_name FROM users ORDER BY id"
    ).fetchall()
    return [
        {"user_id": r[0], "username": r[1], "first_name": r[2], "last_name": r[3]}
        for r in rows
    ]


def get_user_channels_from_messages(
    conn: sqlite3.Connection, user_id: int
) -> Dict[int, Dict[str, Any]]:
    """Get channels a user has posted in, from the messages table."""
    rows = conn.execute(
        """
        SELECT m.channel_id, COUNT(*) as msg_count,
               MIN(m.date) as first_seen, MAX(m.date) as last_seen
        FROM messages m
        WHERE m.user_id = ? AND m.channel_id IS NOT NULL
        GROUP BY m.channel_id
        """,
        (user_id,),
    ).fetchall()

    channels = {}
    for r in rows:
        ch_id = r[0]
        # Get channel info
        ch_info = conn.execute(
            "SELECT channel_title, channel_username, channel_type FROM channel_network WHERE channel_id = ?",
            (ch_id,),
        ).fetchone()
        channels[ch_id] = {
            "channel_id": ch_id,
            "channel_title": ch_info[0] if ch_info else f"channel_{ch_id}",
            "channel_username": ch_info[1] if ch_info else None,
            "channel_type": ch_info[2] if ch_info else "unknown",
            "message_count": r[1],
            "first_seen": r[2],
            "last_seen": r[3],
        }
    return channels


def get_user_channels_from_members(
    conn: sqlite3.Connection, user_id: int
) -> Dict[int, Dict[str, Any]]:
    """Get channels a user is a member of, from channel_members table."""
    try:
        rows = conn.execute(
            """
            SELECT channel_id, first_seen
            FROM channel_members
            WHERE user_id = ? AND channel_id IS NOT NULL AND channel_id != 0
            """,
            (user_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}

    channels = {}
    for r in rows:
        ch_id = r[0]
        ch_info = conn.execute(
            "SELECT channel_title, channel_username, channel_type FROM channel_network WHERE channel_id = ?",
            (ch_id,),
        ).fetchone()
        channels[ch_id] = {
            "channel_id": ch_id,
            "channel_title": ch_info[0] if ch_info else f"channel_{ch_id}",
            "channel_username": ch_info[1] if ch_info else None,
            "channel_type": ch_info[2] if ch_info else "unknown",
            "message_count": 0,
            "first_seen": r[1],
            "last_seen": r[1],
        }
    return channels


def get_channel_members_from_db(
    conn: sqlite3.Connection, channel_id: int
) -> Set[int]:
    """Get all known members of a channel from channel_members + messages."""
    members = set()
    try:
        for r in conn.execute(
            "SELECT DISTINCT user_id FROM channel_members WHERE channel_id = ? AND user_id IS NOT NULL",
            (channel_id,),
        ).fetchall():
            members.add(r[0])
    except sqlite3.OperationalError:
        pass
    for r in conn.execute(
        "SELECT DISTINCT user_id FROM messages WHERE channel_id = ? AND user_id IS NOT NULL",
        (channel_id,),
    ).fetchall():
        members.add(r[0])
    return members


def build_network_for_user(
    conn: sqlite3.Connection,
    user_id: int,
    min_shared: int = 1,
) -> Dict[str, Any]:
    """Build the support network for a single user.

    Returns stats about what was built.
    """
    now = datetime.now(TZ).isoformat()

    # 1. Get all channels this user is in
    msg_channels = get_user_channels_from_messages(conn, user_id)
    member_channels = get_user_channels_from_members(conn, user_id)

    # Merge — member_channels may overlap with msg_channels
    all_channels = {}
    all_channels.update(msg_channels)
    for ch_id, ch in member_channels.items():
        if ch_id in all_channels:
            all_channels[ch_id]["first_seen"] = min(
                all_channels[ch_id]["first_seen"] or ch["first_seen"],
                ch["first_seen"],
            ) if all_channels[ch_id].get("first_seen") and ch.get("first_seen") else (
                all_channels[ch_id]["first_seen"] or ch["first_seen"]
            )
        else:
            all_channels[ch_id] = ch

    # 2. Store user-channel memberships
    for ch_id, ch in all_channels.items():
        conn.execute(
            """
            INSERT INTO support_network_channels
                (user_id, channel_id, channel_title, channel_username, channel_type,
                 message_count, first_seen, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, channel_id) DO UPDATE SET
                channel_title=excluded.channel_title,
                channel_username=excluded.channel_username,
                channel_type=excluded.channel_type,
                message_count=excluded.message_count,
                last_updated=excluded.last_updated
            """,
            (user_id, ch_id, ch["channel_title"], ch["channel_username"],
             ch["channel_type"], ch["message_count"], ch["first_seen"], now),
        )

    # 3. For each channel, find co-members → build edges
    # Collect all co-members and their shared channel counts
    co_member_shared: Dict[int, List[int]] = defaultdict(list)  # co_uid → [ch_ids]

    for ch_id in all_channels:
        members = get_channel_members_from_db(conn, ch_id)
        for m_uid in members:
            if m_uid == user_id:
                continue
            co_member_shared[m_uid].append(ch_id)

    # 4. Store edges (only those with >= min_shared shared channels)
    edges_built = 0
    co_members = 0
    for co_uid, shared_chs in co_member_shared.items():
        if len(shared_chs) < min_shared:
            continue
        co_members += 1

        # Edge weight = shared channel count (could be weighted by channel size later)
        weight = float(len(shared_chs))

        # Ensure user_a < user_b for canonical edge
        a, b = (user_id, co_uid) if user_id < co_uid else (co_uid, user_id)

        conn.execute(
            """
            INSERT INTO support_network_edges
                (user_a, user_b, shared_channels, shared_channel_ids,
                 edge_weight, first_seen, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_a, user_b) DO UPDATE SET
                shared_channels=excluded.shared_channels,
                shared_channel_ids=excluded.shared_channel_ids,
                edge_weight=MAX(excluded.edge_weight, support_network_edges.edge_weight),
                last_updated=excluded.last_updated
            """,
            (a, b, len(shared_chs), json.dumps(shared_chs), weight, now, now),
        )
        edges_built += 1

    # 5. Store/update the node
    is_target = user_id in PRIMARY_TARGETS
    target_id = PRIMARY_TARGETS.get(user_id, {}).get("target_id")

    user_info = conn.execute(
        "SELECT username, first_name, last_name FROM users WHERE id = ?", (user_id,)
    ).fetchone()

    conn.execute(
        """
        INSERT INTO support_network_nodes
            (user_id, username, first_name, last_name, channel_count,
             co_member_count, edge_count, is_primary_target, target_id,
             first_seen, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            channel_count=excluded.channel_count,
            co_member_count=excluded.co_member_count,
            edge_count=excluded.edge_count,
            is_primary_target=excluded.is_primary_target,
            target_id=excluded.target_id,
            last_updated=excluded.last_updated
        """,
        (user_id,
         user_info[0] if user_info else None,
         user_info[1] if user_info else None,
         user_info[2] if user_info else None,
         len(all_channels), co_members, edges_built,
         1 if is_target else 0, target_id, now, now),
    )

    return {
        "user_id": user_id,
        "channels": len(all_channels),
        "co_members": co_members,
        "edges": edges_built,
    }


def build_all_networks(
    conn: sqlite3.Connection,
    min_shared: int = 1,
    batch_size: int = 2000,
    limit: int | None = None,
) -> Dict[str, Any]:
    """Build support networks for all users in the database.

    Bulk approach: loads user→channel and channel→members maps into memory
    once, then builds all networks in a single pass. This avoids O(n²) DB
    queries and runs in seconds instead of hours.
    """
    now = datetime.now(TZ).isoformat()
    conn.execute("PRAGMA busy_timeout=300000")

    # === Phase 1: Load all data into memory ===
    logger.info("Loading channel metadata...")
    channel_info: Dict[int, Dict[str, Any]] = {}
    for r in conn.execute(
        "SELECT channel_id, channel_title, channel_username, channel_type FROM channel_network"
    ).fetchall():
        channel_info[r[0]] = {
            "channel_title": r[1],
            "channel_username": r[2],
            "channel_type": r[3],
        }
    logger.info(f"  {len(channel_info)} channels loaded")

    logger.info("Loading user→channel map from messages...")
    user_channels: Dict[int, Dict[int, Dict[str, Any]]] = defaultdict(dict)
    for r in conn.execute(
        """
        SELECT user_id, channel_id, COUNT(*) as msg_count,
               MIN(date) as first_seen, MAX(date) as last_seen
        FROM messages
        WHERE user_id IS NOT NULL AND channel_id IS NOT NULL
        GROUP BY user_id, channel_id
        """
    ).fetchall():
        uid, ch_id = r[0], r[1]
        ch = channel_info.get(ch_id, {})
        user_channels[uid][ch_id] = {
            "channel_id": ch_id,
            "channel_title": ch.get("channel_title", f"channel_{ch_id}"),
            "channel_username": ch.get("channel_username"),
            "channel_type": ch.get("channel_type", "unknown"),
            "message_count": r[2],
            "first_seen": r[3],
            "last_seen": r[4],
        }
    logger.info(f"  {len(user_channels)} users with channels from messages")

    logger.info("Loading user→channel map from channel_members...")
    try:
        for r in conn.execute(
            "SELECT user_id, channel_id, first_seen FROM channel_members WHERE user_id IS NOT NULL AND channel_id IS NOT NULL AND channel_id != 0"
        ).fetchall():
            uid, ch_id = r[0], r[1]
            ch = channel_info.get(ch_id, {})
            if ch_id not in user_channels[uid]:
                user_channels[uid][ch_id] = {
                    "channel_id": ch_id,
                    "channel_title": ch.get("channel_title", f"channel_{ch_id}"),
                    "channel_username": ch.get("channel_username"),
                    "channel_type": ch.get("channel_type", "unknown"),
                    "message_count": 0,
                    "first_seen": r[2],
                    "last_seen": r[2],
                }
            else:
                existing = user_channels[uid][ch_id]
                if not existing.get("first_seen") and r[2]:
                    existing["first_seen"] = r[2]
        logger.info(f"  channel_members merged")
    except sqlite3.OperationalError:
        logger.info("  channel_members table not available")

    logger.info("Loading channel→members map...")
    channel_members: Dict[int, Set[int]] = defaultdict(set)
    for r in conn.execute(
        "SELECT DISTINCT channel_id, user_id FROM messages WHERE channel_id IS NOT NULL AND user_id IS NOT NULL"
    ).fetchall():
        channel_members[r[0]].add(r[1])
    try:
        for r in conn.execute(
            "SELECT DISTINCT channel_id, user_id FROM channel_members WHERE channel_id IS NOT NULL AND user_id IS NOT NULL AND channel_id != 0"
        ).fetchall():
            channel_members[r[0]].add(r[1])
    except sqlite3.OperationalError:
        pass
    logger.info(f"  {len(channel_members)} channels with members")

    logger.info("Loading user metadata...")
    user_meta: Dict[int, Tuple] = {}
    for r in conn.execute("SELECT id, username, first_name, last_name FROM users"):
        user_meta[r[0]] = (r[1], r[2], r[3])
    logger.info(f"  {len(user_meta)} users loaded")

    # === Phase 2: Build channel memberships + edges in memory ===
    user_list = sorted(user_channels.keys())
    # Always include primary targets
    for uid in PRIMARY_TARGETS:
        if uid not in user_channels:
            user_list.append(uid)
            user_channels[uid] = {}
    user_list = sorted(set(user_list))
    if limit:
        user_list = user_list[:limit]

    total = len(user_list)
    logger.info(f"Building support networks for {total} users (min_shared={min_shared})")

    # Build edges: for each user, find co-members in their channels
    # edge_map[(a,b)] = set of shared channel_ids
    edge_map: Dict[Tuple[int, int], Set[int]] = defaultdict(set)
    node_channels_count: Dict[int, int] = {}
    node_co_members: Dict[int, int] = {}

    for i, uid in enumerate(user_list):
        uch = user_channels.get(uid, {})
        node_channels_count[uid] = len(uch)
        co_members = set()
        for ch_id in uch:
            for m in channel_members.get(ch_id, set()):
                if m != uid:
                    co_members.add(m)
                    a, b = (uid, m) if uid < m else (m, uid)
                    edge_map[(a, b)].add(ch_id)
        node_co_members[uid] = len(co_members)

        if (i + 1) % 5000 == 0:
            logger.info(f"  Phase 2 progress: {i+1}/{total} users, {len(edge_map)} edges so far")

    logger.info(f"  Phase 2 done: {len(edge_map)} raw edges")

    # Filter edges by min_shared
    filtered_edges = {
        (a, b): chs for (a, b), chs in edge_map.items() if len(chs) >= min_shared
    }
    logger.info(f"  {len(filtered_edges)} edges after min_shared={min_shared} filter")

    # === Phase 3: Write to DB in batches ===
    logger.info("Writing channel memberships...")
    ch_batch = []
    for uid in user_list:
        uch = user_channels.get(uid, {})
        for ch_id, ch in uch.items():
            ch_batch.append((
                uid, ch_id, ch["channel_title"], ch["channel_username"],
                ch["channel_type"], ch["message_count"], ch["first_seen"], now,
            ))
        if len(ch_batch) >= 5000:
            conn.executemany(
                """
                INSERT INTO support_network_channels
                    (user_id, channel_id, channel_title, channel_username, channel_type,
                     message_count, first_seen, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, channel_id) DO UPDATE SET
                    channel_title=excluded.channel_title,
                    channel_username=excluded.channel_username,
                    channel_type=excluded.channel_type,
                    message_count=excluded.message_count,
                    last_updated=excluded.last_updated
                """,
                ch_batch,
            )
            conn.commit()
            ch_batch = []
    if ch_batch:
        conn.executemany(
            """
            INSERT INTO support_network_channels
                (user_id, channel_id, channel_title, channel_username, channel_type,
                 message_count, first_seen, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, channel_id) DO UPDATE SET
                channel_title=excluded.channel_title,
                channel_username=excluded.channel_username,
                channel_type=excluded.channel_type,
                message_count=excluded.message_count,
                last_updated=excluded.last_updated
            """,
            ch_batch,
        )
        conn.commit()
    logger.info(f"  Channel memberships written")

    logger.info("Writing edges...")
    edge_batch = []
    for (a, b), chs in filtered_edges.items():
        edge_batch.append((
            a, b, len(chs), json.dumps(sorted(chs)),
            float(len(chs)), now, now,
        ))
        if len(edge_batch) >= 5000:
            conn.executemany(
                """
                INSERT INTO support_network_edges
                    (user_a, user_b, shared_channels, shared_channel_ids,
                     edge_weight, first_seen, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_a, user_b) DO UPDATE SET
                    shared_channels=excluded.shared_channels,
                    shared_channel_ids=excluded.shared_channel_ids,
                    edge_weight=MAX(excluded.edge_weight, support_network_edges.edge_weight),
                    last_updated=excluded.last_updated
                """,
                edge_batch,
            )
            conn.commit()
            edge_batch = []
    if edge_batch:
        conn.executemany(
            """
            INSERT INTO support_network_edges
                (user_a, user_b, shared_channels, shared_channel_ids,
                 edge_weight, first_seen, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_a, user_b) DO UPDATE SET
                shared_channels=excluded.shared_channels,
                shared_channel_ids=excluded.shared_channel_ids,
                edge_weight=MAX(excluded.edge_weight, support_network_edges.edge_weight),
                last_updated=excluded.last_updated
            """,
            edge_batch,
        )
        conn.commit()
    logger.info(f"  Edges written")

    logger.info("Writing nodes...")
    # Precompute edge counts per user (avoid O(n²) iteration)
    user_edge_counts: Dict[int, int] = defaultdict(int)
    for (a, b) in filtered_edges:
        user_edge_counts[a] += 1
        user_edge_counts[b] += 1

    node_batch = []
    for uid in user_list:
        meta = user_meta.get(uid, (None, None, None))
        is_target = uid in PRIMARY_TARGETS
        target_id = PRIMARY_TARGETS.get(uid, {}).get("target_id")
        edge_count = user_edge_counts.get(uid, 0)
        node_batch.append((
            uid, meta[0], meta[1], meta[2],
            node_channels_count.get(uid, 0),
            node_co_members.get(uid, 0),
            edge_count,
            1 if is_target else 0, target_id, now, now,
        ))
        if len(node_batch) >= 5000:
            conn.executemany(
                """
                INSERT INTO support_network_nodes
                    (user_id, username, first_name, last_name, channel_count,
                     co_member_count, edge_count, is_primary_target, target_id,
                     first_seen, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    channel_count=excluded.channel_count,
                    co_member_count=excluded.co_member_count,
                    edge_count=excluded.edge_count,
                    is_primary_target=excluded.is_primary_target,
                    target_id=excluded.target_id,
                    last_updated=excluded.last_updated
                """,
                node_batch,
            )
            conn.commit()
            node_batch = []
    if node_batch:
        conn.executemany(
            """
            INSERT INTO support_network_nodes
                (user_id, username, first_name, last_name, channel_count,
                 co_member_count, edge_count, is_primary_target, target_id,
                 first_seen, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                channel_count=excluded.channel_count,
                co_member_count=excluded.co_member_count,
                edge_count=excluded.edge_count,
                is_primary_target=excluded.is_primary_target,
                target_id=excluded.target_id,
                last_updated=excluded.last_updated
            """,
            node_batch,
        )
        conn.commit()
    logger.info(f"  Nodes written")

    stats = {
        "total_users": total,
        "processed": total,
        "total_channels": sum(node_channels_count.values()),
        "total_edges": len(filtered_edges),
        "total_co_members": sum(node_co_members.values()),
        "errors": 0,
    }
    logger.info(
        f"Done: {stats['processed']}/{total} users, "
        f"{stats['total_channels']} channel memberships, "
        f"{stats['total_edges']} edges"
    )
    return stats


def push_to_index_outbox(conn: sqlite3.Connection) -> int:
    """Push support network nodes + edges to IndexOutbox for QIHSE projection."""
    try:
        from tgarchive.db.index_outbox import IndexOutbox
    except ImportError:
        logger.warning("IndexOutbox not available — skipping QIHSE projection")
        return 0

    IndexOutbox.ensure_schema(conn)
    now = datetime.now(TZ).isoformat()
    pushed = 0

    # Push nodes
    for r in conn.execute("SELECT user_id, username, first_name, last_name, channel_count, edge_count, is_primary_target, target_id FROM support_network_nodes").fetchall():
        payload = {
            "user_id": r[0],
            "username": r[1],
            "first_name": r[2],
            "last_name": r[3],
            "channel_count": r[4],
            "edge_count": r[5],
            "is_primary_target": bool(r[6]),
            "target_id": r[7],
        }
        try:
            seq = IndexOutbox.append_to(
                conn,
                source_table="support_network_nodes",
                source_key=str(r[0]),
                event_type="upsert",
                payload=payload,
                source_revision=f"snn-{r[0]}-{r[4]}-{r[5]}",
            )
            if seq is not None:
                pushed += 1
        except Exception:
            pass

    # Push edges (sample — there can be millions)
    edge_count = conn.execute("SELECT COUNT(*) FROM support_network_edges").fetchone()[0]
    logger.info(f"  Pushing {min(edge_count, 50000)} edges to IndexOutbox (of {edge_count} total)")

    edge_pushed = 0
    for r in conn.execute(
        "SELECT user_a, user_b, shared_channels, edge_weight FROM support_network_edges ORDER BY edge_weight DESC LIMIT 50000"
    ).fetchall():
        payload = {
            "user_a": r[0],
            "user_b": r[1],
            "shared_channels": r[2],
            "edge_weight": r[3],
        }
        try:
            seq = IndexOutbox.append_to(
                conn,
                source_table="support_network_edges",
                source_key=f"{r[0]}-{r[1]}",
                event_type="upsert",
                payload=payload,
                source_revision=f"sne-{r[0]}-{r[1]}-{r[2]}",
            )
            if seq is not None:
                edge_pushed += 1
        except Exception:
            pass

    conn.commit()
    logger.info(f"  Pushed {pushed} nodes + {edge_pushed} edges to IndexOutbox")
    return pushed + edge_pushed


def show_stats(conn: sqlite3.Connection) -> None:
    """Print network statistics."""
    nodes = conn.execute("SELECT COUNT(*) FROM support_network_nodes").fetchone()[0]
    edges = conn.execute("SELECT COUNT(*) FROM support_network_edges").fetchone()[0]
    channels = conn.execute("SELECT COUNT(*) FROM support_network_channels").fetchone()[0]
    targets = conn.execute("SELECT COUNT(*) FROM support_network_nodes WHERE is_primary_target=1").fetchone()[0]

    print(f"\n═══ Support Network Stats ═══")
    print(f"  Nodes (users):     {nodes}")
    print(f"  Edges (links):     {edges}")
    print(f"  Channel memberships: {channels}")
    print(f"  Primary targets:   {targets}")

    # Top connected users
    print(f"\n  Top 10 most-connected users:")
    rows = conn.execute(
        """
        SELECT n.user_id, n.username, n.first_name, n.channel_count, n.edge_count, n.is_primary_target
        FROM support_network_nodes n
        ORDER BY n.edge_count DESC
        LIMIT 10
        """
    ).fetchall()
    for r in rows:
        flag = " ⚡TARGET" if r[5] else ""
        print(f"    @{r[1] or '?'} ({r[2] or '?'}): {r[3]} channels, {r[4]} edges{flag}")

    # Top shared-channel pairs
    print(f"\n  Top 10 strongest links (most shared channels):")
    rows = conn.execute(
        """
        SELECT e.user_a, e.user_b, e.shared_channels, e.edge_weight,
               na.username, nb.username
        FROM support_network_edges e
        LEFT JOIN support_network_nodes na ON e.user_a = na.user_id
        LEFT JOIN support_network_nodes nb ON e.user_b = nb.user_id
        ORDER BY e.shared_channels DESC
        LIMIT 10
        """
    ).fetchall()
    for r in rows:
        print(f"    @{r[4] or '?'} ↔ @{r[5] or '?'}: {r[2]} shared channels (weight={r[3]:.1f})")

    # Primary target networks
    print(f"\n  Primary target networks:")
    for uid, info in PRIMARY_TARGETS.items():
        r = conn.execute(
            "SELECT channel_count, edge_count, co_member_count FROM support_network_nodes WHERE user_id = ?",
            (uid,),
        ).fetchone()
        if r:
            print(f"    {info['target_id']} (@{info['username']}): {r[0]} channels, {r[1]} edges, {r[2]} co-members")
        else:
            print(f"    {info['target_id']} (@{info['username']}): NOT BUILT YET")


def main():
    parser = argparse.ArgumentParser(description="SPECTRA Support Network Builder")
    parser.add_argument("--user", type=int, help="Build network for a single user ID")
    parser.add_argument("--min-shared", type=int, default=1,
                        help="Minimum shared channels to create an edge (default: 1)")
    parser.add_argument("--limit", type=int, help="Limit number of users to process")
    parser.add_argument("--stats", action="store_true", help="Show network statistics")
    parser.add_argument("--push-qihse", action="store_true",
                        help="Push network to IndexOutbox for QIHSE projection")
    parser.add_argument("--db", help="Database path")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DB_PATH
    conn = sqlite3.connect(str(db_path), timeout=300)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    ensure_schema(conn)

    if args.stats:
        show_stats(conn)
        conn.close()
        return

    if args.user:
        logger.info(f"Building network for user {args.user}...")
        result = build_network_for_user(conn, args.user, min_shared=args.min_shared)
        conn.commit()
        print(f"\n  User {args.user}: {result['channels']} channels, "
              f"{result['co_members']} co-members, {result['edges']} edges")

        if args.push_qihse:
            push_to_index_outbox(conn)
    else:
        stats = build_all_networks(conn, min_shared=args.min_shared, limit=args.limit)

        if args.push_qihse:
            push_to_index_outbox(conn)

        show_stats(conn)

    conn.close()


if __name__ == "__main__":
    main()
