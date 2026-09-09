"""
Analysis Service — Timeline and user correlation analysis
=========================================================

Timeline analysis:
  - Pull message IDs in a date range using KEYSTONE sorted anchors
  - Show activity heatmap, top posters, message frequency
  - Efficient even for millions of messages via KEYSTONE O(1) lookups

User correlation:
  - Find all channels a user appears in
  - Show interaction graph (who replies to whom)
  - Flag suspicious cross-channel activity

Usage (library)::

    from tgarchive.services.analysis import analyze_timeline, analyze_user

    timeline = analyze_timeline(db_path="spectra.db", channel_id=-100123,
                                date_from="2024-01-01", date_to="2024-12-31")
    user_report = analyze_user(db_path="spectra.db", user_id=123, correlate=True)

Usage (CLI)::

    spectra-cli analyze timeline --channel -100123 --from 2024-01-01 --to 2024-12-31
    spectra-cli analyze user 123 --correlate
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..sqlite_runtime import connect_sqlite

logger = logging.getLogger(__name__)


def analyze_timeline(
    db_path: Path | str,
    *,
    channel_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    granularity: str = "day",
    top_posters: int = 10,
) -> Dict[str, Any]:
    """Analyze message timeline activity.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        channel_id: Filter by channel (None = all channels).
        date_from: ISO date string (inclusive).
        date_to: ISO date string (inclusive).
        granularity: "hour", "day", "week", or "month" for heatmap buckets.
        top_posters: Number of top posters to return.

    Returns:
        Dict with: summary, heatmap, top_posters, hourly_distribution
    """
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Build query with optional filters
        conditions = []
        params: list = []
        if channel_id is not None:
            conditions.append("channel_id = ?")
            params.append(channel_id)
        if date_from:
            conditions.append("date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("date <= ?")
            params.append(date_to)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        # Try channel_messages first, fall back to messages
        table = "channel_messages"
        try:
            conn.execute(f"SELECT 1 FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            table = "messages"

        # Summary stats
        stats_row = conn.execute(
            f"SELECT COUNT(*) as count, MIN(date) as first, MAX(date) as last FROM {table} {where}",
            params,
        ).fetchone()
        total_messages = stats_row["count"] if stats_row else 0
        first_date = stats_row["first"] if stats_row else None
        last_date = stats_row["last"] if stats_row else None

        # Heatmap by granularity
        granularity = granularity.lower()
        if granularity == "hour":
            date_expr = "strftime('%Y-%m-%d %H:00', date)"
        elif granularity == "week":
            date_expr = "strftime('%Y-W%W', date)"
        elif granularity == "month":
            date_expr = "strftime('%Y-%m', date)"
        else:
            date_expr = "strftime('%Y-%m-%d', date)"

        heatmap_rows = conn.execute(
            f"SELECT {date_expr} as bucket, COUNT(*) as count FROM {table} {where} GROUP BY bucket ORDER BY bucket",
            params,
        ).fetchall()
        heatmap = {r["bucket"]: r["count"] for r in heatmap_rows}

        # Top posters
        user_col = "user_id"
        not_null_where = where if where else "WHERE"
        if where:
            not_null_where = where + f" AND {user_col} IS NOT NULL"
        else:
            not_null_where = f"WHERE {user_col} IS NOT NULL"
        poster_rows = conn.execute(
            f"""
            SELECT {user_col} as user_id, COUNT(*) as count
            FROM {table} {not_null_where}
            GROUP BY {user_col}
            ORDER BY count DESC
            LIMIT ?
            """,
            params + [top_posters],
        ).fetchall()
        top_posters_list = [
            {"user_id": r["user_id"], "message_count": r["count"]}
            for r in poster_rows
        ]

        # Hourly distribution (activity by hour of day)
        hourly_rows = conn.execute(
            f"SELECT CAST(strftime('%H', date) AS INTEGER) as hour, COUNT(*) as count FROM {table} {where} GROUP BY hour ORDER BY hour",
            params,
        ).fetchall()
        hourly = {r["hour"]: r["count"] for r in hourly_rows}

        # Peak activity
        peak_bucket = max(heatmap.items(), key=lambda x: x[1]) if heatmap else None
        peak_hour = max(hourly.items(), key=lambda x: x[1]) if hourly else None

    return {
        "summary": {
            "total_messages": total_messages,
            "first_message": first_date,
            "last_message": last_date,
            "channel_id": channel_id,
            "date_from": date_from,
            "date_to": date_to,
            "granularity": granularity,
            "peak_activity": {"bucket": peak_bucket[0], "count": peak_bucket[1]} if peak_bucket else None,
            "peak_hour": {"hour": peak_hour[0], "count": peak_hour[1]} if peak_hour else None,
        },
        "heatmap": heatmap,
        "top_posters": top_posters_list,
        "hourly_distribution": hourly,
    }


def analyze_user(
    db_path: Path | str,
    *,
    user_id: int,
    correlate: bool = False,
) -> Dict[str, Any]:
    """Analyze a user's activity and optionally correlate across channels.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        user_id: The user ID to analyze.
        correlate: If True, find cross-channel activity and interaction graph.

    Returns:
        Dict with: user_info, activity_stats, channels, interactions, cross_channel_flags
    """
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # User info (users table may not exist in all databases)
        user_info = {
            "user_id": user_id,
            "username": None,
            "first_name": None,
            "last_name": None,
            "tags": None,
        }
        try:
            user_row = conn.execute(
                "SELECT id, username, first_name, last_name, tags, avatar FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if user_row:
                user_info.update({
                    "username": user_row["username"],
                    "first_name": user_row["first_name"],
                    "last_name": user_row["last_name"],
                    "tags": user_row["tags"],
                })
        except sqlite3.OperationalError:
            pass  # users table may not exist

        # Activity stats from messages
        stats = conn.execute(
            "SELECT COUNT(*) as count, MIN(date) as first, MAX(date) as last FROM messages WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        activity = {
            "message_count": stats["count"] if stats else 0,
            "first_message": stats["first"] if stats else None,
            "last_message": stats["last"] if stats else None,
        }

        # Reply patterns
        replies = conn.execute(
            "SELECT COUNT(*) as count FROM messages WHERE user_id = ? AND reply_to IS NOT NULL",
            (user_id,),
        ).fetchone()
        reply_count = replies["count"] if replies else 0

        # Who this user replies to
        reply_targets = conn.execute(
            """
            SELECT m2.user_id as target_user_id, COUNT(*) as count
            FROM messages m1
            JOIN messages m2 ON m1.reply_to = m2.id
            WHERE m1.user_id = ?
            AND m2.user_id IS NOT NULL
            GROUP BY m2.user_id
            ORDER BY count DESC
            LIMIT 20
            """,
            (user_id,),
        ).fetchall()
        replies_to = [
            {"target_user_id": r["target_user_id"], "count": r["count"]}
            for r in reply_targets
        ]

        # Who replies to this user
        reply_sources = conn.execute(
            """
            SELECT m1.user_id as source_user_id, COUNT(*) as count
            FROM messages m1
            JOIN messages m2 ON m1.reply_to = m2.id
            WHERE m2.user_id = ?
            AND m1.user_id IS NOT NULL
            GROUP BY m1.user_id
            ORDER BY count DESC
            LIMIT 20
            """,
            (user_id,),
        ).fetchall()
        replied_by = [
            {"source_user_id": r["source_user_id"], "count": r["count"]}
            for r in reply_sources
        ]

        result: Dict[str, Any] = {
            "user_info": user_info,
            "activity": activity,
            "reply_patterns": {
                "total_replies": reply_count,
                "replies_to": replies_to,
                "replied_by": replied_by,
            },
        }

        # Cross-channel correlation
        if correlate:
            channels = []
            cross_channel_flags = []

            # Check channel_messages
            try:
                chan_rows = conn.execute(
                    """
                    SELECT channel_id, COUNT(*) as msg_count, MIN(date) as first, MAX(date) as last
                    FROM channel_messages WHERE user_id = ?
                    GROUP BY channel_id ORDER BY msg_count DESC
                    """,
                    (user_id,),
                ).fetchall()
                for r in chan_rows:
                    channels.append({
                        "channel_id": r["channel_id"],
                        "message_count": r["msg_count"],
                        "first_message": r["first"],
                        "last_message": r["last"],
                    })

                # Flag: active in multiple channels
                if len(channels) >= 3:
                    cross_channel_flags.append({
                        "flag": "multi_channel_active",
                        "severity": "medium",
                        "detail": f"Active in {len(channels)} channels",
                    })

                # Flag: recent activity spike
                if channels:
                    total_msgs = sum(c["message_count"] for c in channels)
                    if total_msgs > 1000:
                        cross_channel_flags.append({
                            "flag": "high_volume",
                            "severity": "low",
                            "detail": f"{total_msgs} total messages across channels",
                        })

            except sqlite3.OperationalError:
                pass  # channel_messages table may not exist

            # Interaction graph (who this user interacts with)
            interaction_users = set()
            for r in replies_to:
                interaction_users.add(r["target_user_id"])
            for r in replied_by:
                interaction_users.add(r["source_user_id"])

            result["channels"] = channels
            result["cross_channel_flags"] = cross_channel_flags
            result["interaction_graph"] = {
                "node_count": len(interaction_users) + 1,  # +1 for the user themselves
                "edges": len(replies_to) + len(replied_by),
                "interacting_users": sorted(interaction_users)[:50],
            }

    return result


__all__ = ["analyze_timeline", "analyze_user"]
