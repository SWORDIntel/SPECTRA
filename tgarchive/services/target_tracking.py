"""
Target Tracking System — Close surveillance of persons of interest
===================================================================

Given usernames or aliases, establishes a comprehensive surveillance dossier:
  - Alias resolution: find all accounts matching a username/alias across channels
  - Contact network: map everyone the target interacts with (replies, mentions)
  - Timing correlation: compare the target's posting times against other posters
    to detect coordinated activity or shared operators
  - Channel footprint: all channels where the target is active
  - Activity timeline: chronological message history with event annotations
  - Writing style fingerprint: stylometric profile for cross-identity matching
  - Risk indicators: suspicious patterns (multi-channel coordination, impersonation,
    bot-like behavior, steganographic media)

Usage (library)::

    from tgarchive.services.target_tracking import build_target_dossier

    dossier = build_target_dossier(db_path="spectra.db", aliases=["alice", "alice_smith"])

Usage (CLI)::

    spectra-cli target add alice "alice_smith" "alice.tg"
    spectra-cli target dossier alice
    spectra-cli target network alice
    spectra-cli target timing alice --correlate
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..sqlite_runtime import connect_sqlite
from .utils import parse_dt as _parse_dt

logger = logging.getLogger(__name__)

_TARGET_TABLE = "surveillance_targets"
_TARGET_ALIAS_TABLE = "surveillance_aliases"


def _ensure_target_tables(conn: sqlite3.Connection) -> None:
    """Create target tracking tables if they don't exist."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_TARGET_TABLE} (
            target_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_TARGET_ALIAS_TABLE} (
            target_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            alias_type TEXT NOT NULL DEFAULT 'username',
            resolved_user_id INTEGER,
            first_seen TEXT,
            last_seen TEXT,
            PRIMARY KEY (target_id, alias)
        )
    """)


def add_target(
    db_path: Path | str,
    target_id: str,
    label: str,
    aliases: List[str],
    notes: str = "",
) -> Dict[str, Any]:
    """Register a surveillance target with aliases.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        target_id: Unique identifier for the target (e.g., "alice").
        label: Human-readable label (e.g., "Alice Smith — primary suspect").
        aliases: List of usernames/aliases to track.
        notes: Free-text notes about the target.
    """
    db_path = Path(db_path).expanduser().resolve()
    now = datetime.now(timezone.utc).isoformat()

    with connect_sqlite(db_path) as conn:
        _ensure_target_tables(conn)
        conn.execute(
            f"INSERT OR REPLACE INTO {_TARGET_TABLE} (target_id, label, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (target_id, label, notes, now, now),
        )
        for alias in aliases:
            conn.execute(
                f"INSERT OR REPLACE INTO {_TARGET_ALIAS_TABLE} (target_id, alias, alias_type, first_seen, last_seen) VALUES (?, ?, 'username', ?, ?)",
                (target_id, alias, now, now),
            )
        conn.commit()

    return {"target_id": target_id, "label": label, "aliases": aliases, "notes": notes}


def list_targets(db_path: Path | str) -> List[Dict[str, Any]]:
    """List all registered surveillance targets."""
    db_path = Path(db_path).expanduser().resolve()
    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_target_tables(conn)
        targets = conn.execute(
            f"SELECT t.target_id, t.label, t.notes, t.created_at, t.updated_at, "
            f"GROUP_CONCAT(a.alias) as aliases "
            f"FROM {_TARGET_TABLE} t LEFT JOIN {_TARGET_ALIAS_TABLE} a ON t.target_id = a.target_id "
            f"GROUP BY t.target_id ORDER BY t.updated_at DESC"
        ).fetchall()
        return [
            {
                "target_id": t["target_id"],
                "label": t["label"],
                "notes": t["notes"],
                "aliases": t["aliases"].split(",") if t["aliases"] else [],
                "created_at": t["created_at"],
                "updated_at": t["updated_at"],
            }
            for t in targets
        ]


def remove_target(db_path: Path | str, target_id: str) -> Dict[str, Any]:
    """Remove a surveillance target and its aliases."""
    db_path = Path(db_path).expanduser().resolve()
    with connect_sqlite(db_path) as conn:
        _ensure_target_tables(conn)
        conn.execute(f"DELETE FROM {_TARGET_ALIAS_TABLE} WHERE target_id = ?", (target_id,))
        conn.execute(f"DELETE FROM {_TARGET_TABLE} WHERE target_id = ?", (target_id,))
        conn.commit()
    return {"removed": target_id}


def _resolve_aliases(conn: sqlite3.Connection, aliases: List[str]) -> List[Dict[str, Any]]:
    """Resolve aliases to user IDs by matching usernames and display names."""
    resolved: List[Dict[str, Any]] = []

    for alias in aliases:
        alias_lower = alias.lower()
        # Match by username
        try:
            rows = conn.execute(
                "SELECT id, username, first_name, last_name, avatar FROM users WHERE LOWER(username) = ?",
                (alias_lower,),
            ).fetchall()
            for row in rows:
                resolved.append({
                    "alias": alias,
                    "user_id": row["id"],
                    "username": row["username"],
                    "display_name": f"{row['first_name'] or ''} {row['last_name'] or ''}".strip(),
                    "match_type": "exact_username",
                    "confidence": 1.0,
                })
        except sqlite3.OperationalError:
            pass

        # Fuzzy match on username (if no exact match)
        if not any(r["alias"] == alias for r in resolved):
            try:
                rows = conn.execute(
                    "SELECT id, username, first_name, last_name FROM users WHERE username IS NOT NULL"
                ).fetchall()
                for row in rows:
                    if row["username"]:
                        sim = SequenceMatcher(None, alias_lower, row["username"].lower()).ratio()
                        if sim >= 0.8:
                            resolved.append({
                                "alias": alias,
                                "user_id": row["id"],
                                "username": row["username"],
                                "display_name": f"{row['first_name'] or ''} {row['last_name'] or ''}".strip(),
                                "match_type": "fuzzy_username",
                                "confidence": round(sim, 4),
                            })
            except sqlite3.OperationalError:
                pass

        # Match by display name
        try:
            rows = conn.execute(
                "SELECT id, username, first_name, last_name FROM users WHERE first_name IS NOT NULL OR last_name IS NOT NULL"
            ).fetchall()
            for row in rows:
                display = f"{row['first_name'] or ''} {row['last_name'] or ''}".strip().lower()
                if display and (alias_lower in display or display in alias_lower):
                    if not any(r["user_id"] == row["id"] for r in resolved):
                        resolved.append({
                            "alias": alias,
                            "user_id": row["id"],
                            "username": row["username"],
                            "display_name": f"{row['first_name'] or ''} {row['last_name'] or ''}".strip(),
                            "match_type": "display_name",
                            "confidence": 0.7,
                        })
        except sqlite3.OperationalError:
            pass

    return resolved


def build_contact_network(
    conn: sqlite3.Connection,
    user_ids: List[int],
    depth: int = 1,
) -> Dict[str, Any]:
    """Build the contact network for target users.

    Maps everyone the targets interact with (reply chains, mentions).
    """
    contacts: Dict[int, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    for uid in user_ids:
        # Who does this user reply to?
        try:
            rows = conn.execute(
                """
                SELECT m2.user_id as contact_id, COUNT(*) as interaction_count,
                       MIN(m1.date) as first_interaction, MAX(m1.date) as last_interaction
                FROM messages m1
                JOIN messages m2 ON m1.reply_to = m2.id
                WHERE m1.user_id = ? AND m2.user_id IS NOT NULL AND m2.user_id != ?
                GROUP BY m2.user_id ORDER BY interaction_count DESC
                """,
                (uid, uid),
            ).fetchall()
            for row in rows:
                cid = row["contact_id"]
                if cid not in contacts:
                    contacts[cid] = {"user_id": cid, "interaction_count": 0, "first_seen": None, "last_seen": None}
                contacts[cid]["interaction_count"] += row["interaction_count"]
                if contacts[cid]["first_seen"] is None or (row["first_interaction"] and row["first_interaction"] < contacts[cid]["first_seen"]):
                    contacts[cid]["first_seen"] = row["first_interaction"]
                if contacts[cid]["last_seen"] is None or (row["last_interaction"] and row["last_interaction"] > contacts[cid]["last_seen"]):
                    contacts[cid]["last_seen"] = row["last_interaction"]
                edges.append({
                    "source": uid,
                    "target": cid,
                    "type": "reply_to",
                    "count": row["interaction_count"],
                })
        except sqlite3.OperationalError:
            pass

        # Who replies to this user?
        try:
            rows = conn.execute(
                """
                SELECT m1.user_id as contact_id, COUNT(*) as interaction_count,
                       MIN(m1.date) as first_interaction, MAX(m1.date) as last_interaction
                FROM messages m1
                JOIN messages m2 ON m1.reply_to = m2.id
                WHERE m2.user_id = ? AND m1.user_id IS NOT NULL AND m1.user_id != ?
                GROUP BY m1.user_id ORDER BY interaction_count DESC
                """,
                (uid, uid),
            ).fetchall()
            for row in rows:
                cid = row["contact_id"]
                if cid not in contacts:
                    contacts[cid] = {"user_id": cid, "interaction_count": 0, "first_seen": None, "last_seen": None}
                contacts[cid]["interaction_count"] += row["interaction_count"]
                if contacts[cid]["first_seen"] is None or (row["first_interaction"] and row["first_interaction"] < contacts[cid]["first_seen"]):
                    contacts[cid]["first_seen"] = row["first_interaction"]
                if contacts[cid]["last_seen"] is None or (row["last_interaction"] and row["last_interaction"] > contacts[cid]["last_seen"]):
                    contacts[cid]["last_seen"] = row["last_interaction"]
                edges.append({
                    "source": cid,
                    "target": uid,
                    "type": "replies_to_target",
                    "count": row["interaction_count"],
                })
        except sqlite3.OperationalError:
            pass

    # Get contact user info
    contact_list = []
    for cid, info in sorted(contacts.items(), key=lambda x: x[1]["interaction_count"], reverse=True):
        try:
            row = conn.execute(
                "SELECT username, first_name, last_name FROM users WHERE id = ?", (cid,)
            ).fetchone()
            contact_list.append({
                **info,
                "username": row["username"] if row else None,
                "display_name": f"{row['first_name'] or ''} {row['last_name'] or ''}".strip() if row else None,
            })
        except sqlite3.OperationalError:
            contact_list.append(info)

    return {
        "nodes": [{"user_id": uid} for uid in user_ids] + contact_list,
        "edges": edges,
        "contact_count": len(contacts),
        "total_interactions": sum(c["interaction_count"] for c in contacts.values()),
    }


def correlate_timing(
    conn: sqlite3.Connection,
    target_user_ids: List[int],
    window_seconds: int = 60,
) -> Dict[str, Any]:
    """Correlate target's posting times against other posters.

    Detects:
    - Coordinated posting (multiple users posting within seconds of each other)
    - Shared operator suspicion (same person behind multiple accounts)
    - Response patterns (who consistently responds shortly after the target)
    """
    # Get target message timestamps
    target_times: List[datetime] = []
    for uid in target_user_ids:
        rows = conn.execute(
            "SELECT date FROM messages WHERE user_id = ? AND date IS NOT NULL ORDER BY date", (uid,)
        ).fetchall()
        for r in rows:
            dt = _parse_dt(r["date"])
            if dt:
                target_times.append(dt)

    if len(target_times) < 5:
        return {"coordinated_posts": [], "correlated_users": [], "detail": "Insufficient target messages"}

    # For each target message, find other users who posted within the window
    correlated_users: Dict[int, List[float]] = defaultdict(list)

    for target_dt in target_times:
        window_start = (target_dt - timedelta(seconds=window_seconds)).isoformat()
        window_end = (target_dt + timedelta(seconds=window_seconds)).isoformat()
        rows = conn.execute(
            """
            SELECT user_id, date FROM messages
            WHERE date BETWEEN ? AND ? AND user_id IS NOT NULL
            """,
            (window_start, window_end),
        ).fetchall()
        for r in rows:
            other_uid = r["user_id"]
            if other_uid in target_user_ids:
                continue
            other_dt = _parse_dt(r["date"])
            if other_dt:
                offset = (other_dt - target_dt).total_seconds()
                correlated_users[other_uid].append(offset)

    # Rank correlated users
    correlated_list = []
    for uid, offsets in correlated_users.items():
        if len(offsets) < 3:
            continue
        avg_offset = sum(offsets) / len(offsets)
        # Users who consistently post shortly after the target (positive offset)
        # or shortly before (negative offset) are suspicious
        consistent_after = sum(1 for o in offsets if 0 < o < window_seconds)
        consistent_before = sum(1 for o in offsets if -window_seconds < o < 0)
        simultaneous = sum(1 for o in offsets if abs(o) < 5)

        try:
            row = conn.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()
            username = row["username"] if row else None
        except sqlite3.OperationalError:
            username = None

        correlated_list.append({
            "user_id": uid,
            "username": username,
            "correlation_count": len(offsets),
            "avg_offset_seconds": round(avg_offset, 2),
            "simultaneous_count": simultaneous,
            "posts_after_target": consistent_after,
            "posts_before_target": consistent_before,
            "suspicion": "high" if simultaneous > 5 else "medium" if len(offsets) > 10 else "low",
        })

    correlated_list.sort(key=lambda x: x["correlation_count"], reverse=True)

    return {
        "correlated_users": correlated_list[:50],
        "target_message_count": len(target_times),
        "window_seconds": window_seconds,
    }


def build_target_dossier(
    db_path: Path | str,
    aliases: List[str],
    *,
    timing_window: int = 60,
    include_writing_style: bool = True,
) -> Dict[str, Any]:
    """Build a comprehensive surveillance dossier for a target.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        aliases: List of usernames/aliases to track.
        timing_window: Window in seconds for timing correlation.
        include_writing_style: If True, compute stylometric fingerprint.

    Returns:
        Dict with: identity_resolution, activity_summary, contact_network,
        timing_correlation, channel_footprint, writing_style, risk_indicators
    """
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # 1. Alias resolution
        resolved = _resolve_aliases(conn, aliases)
        resolved_user_ids = list({r["user_id"] for r in resolved})

        if not resolved_user_ids:
            return {
                "aliases": aliases,
                "identity_resolution": [],
                "error": "No users found matching the provided aliases",
            }

        # 2. Activity summary
        activity = {}
        for uid in resolved_user_ids:
            stats = conn.execute(
                "SELECT COUNT(*) as count, MIN(date) as first, MAX(date) as last FROM messages WHERE user_id = ?",
                (uid,),
            ).fetchone()
            activity[uid] = {
                "message_count": stats["count"] if stats else 0,
                "first_message": stats["first"] if stats else None,
                "last_message": stats["last"] if stats else None,
            }

        # 3. Channel footprint
        channels: List[Dict[str, Any]] = []
        try:
            for uid in resolved_user_ids:
                chan_rows = conn.execute(
                    """
                    SELECT channel_id, COUNT(*) as msg_count, MIN(date) as first, MAX(date) as last
                    FROM channel_messages WHERE user_id = ?
                    GROUP BY channel_id ORDER BY msg_count DESC
                    """,
                    (uid,),
                ).fetchall()
                for r in chan_rows:
                    channels.append({
                        "user_id": uid,
                        "channel_id": r["channel_id"],
                        "message_count": r["msg_count"],
                        "first_message": r["first"],
                        "last_message": r["last"],
                    })
        except sqlite3.OperationalError:
            pass

        # 4. Contact network
        contact_network = build_contact_network(conn, resolved_user_ids)

        # 5. Timing correlation
        timing = correlate_timing(conn, resolved_user_ids, window_seconds=timing_window)

        # 6. Writing style fingerprint
        writing_style: Dict[str, Any] = {}
        if include_writing_style:
            try:
                from ..threat.attribution import AttributionEngine
                engine = AttributionEngine()
                for uid in resolved_user_ids:
                    msgs = conn.execute(
                        "SELECT id, content, date FROM messages WHERE user_id = ? AND content IS NOT NULL ORDER BY date LIMIT 500",
                        (uid,),
                    ).fetchall()
                    if len(msgs) >= 10:
                        msg_list = [{"id": m["id"], "text": m["content"], "date": m["date"]} for m in msgs]
                        profile = engine.analyze_writing_style(msg_list)
                        writing_style[uid] = {
                            "vocabulary_size": profile.vocabulary_size,
                            "avg_sentence_length": profile.avg_sentence_length,
                            "avg_word_length": profile.avg_word_length,
                            "punctuation_density": profile.punctuation_density,
                            "emoji_density": profile.emoji_density,
                            "technical_density": profile.technical_density,
                            "uppercase_ratio": profile.uppercase_ratio,
                            "language": profile.language,
                            "proficiency_level": profile.proficiency_level,
                            "fingerprint_vector": profile.to_vector(),
                        }
            except Exception as e:
                writing_style = {"error": str(e)}

        # 7. Risk indicators
        risk_indicators: List[Dict[str, Any]] = []

        # Multi-channel presence
        target_channels = {c["channel_id"] for c in channels}
        if len(target_channels) >= 3:
            risk_indicators.append({
                "indicator": "multi_channel_presence",
                "severity": "medium",
                "detail": f"Target active in {len(target_channels)} channels",
            })

        # Coordinated posting
        high_correlation = [c for c in timing.get("correlated_users", []) if c["suspicion"] == "high"]
        if high_correlation:
            risk_indicators.append({
                "indicator": "coordinated_posting",
                "severity": "high",
                "detail": f"{len(high_correlation)} users with simultaneous posting patterns — possible shared operator",
            })

        # 24/7 activity
        all_target_times: List[datetime] = []
        for uid in resolved_user_ids:
            rows = conn.execute("SELECT date FROM messages WHERE user_id = ? AND date IS NOT NULL", (uid,)).fetchall()
            for r in rows:
                dt = _parse_dt(r["date"])
                if dt:
                    all_target_times.append(dt)
        if all_target_times:
            hour_counts = Counter(ts.hour for ts in all_target_times)
            active_hours = len([h for h in range(24) if hour_counts.get(h, 0) > 0])
            if active_hours >= 23:
                risk_indicators.append({
                    "indicator": "continuous_activity",
                    "severity": "medium",
                    "detail": f"Active in {active_hours}/24 hours — no sleep cycle detected",
                })

        # Large contact network
        if contact_network["contact_count"] >= 20:
            risk_indicators.append({
                "indicator": "large_contact_network",
                "severity": "low",
                "detail": f"{contact_network['contact_count']} unique contacts — extensive network",
            })

    return {
        "aliases": aliases,
        "identity_resolution": resolved,
        "resolved_user_ids": resolved_user_ids,
        "activity_summary": activity,
        "channel_footprint": channels,
        "contact_network": contact_network,
        "timing_correlation": timing,
        "writing_style": writing_style,
        "risk_indicators": risk_indicators,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "add_target",
    "list_targets",
    "remove_target",
    "build_target_dossier",
    "build_contact_network",
    "correlate_timing",
]
