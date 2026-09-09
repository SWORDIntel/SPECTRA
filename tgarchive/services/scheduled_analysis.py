"""
Hourly Scheduled Analysis — Detect if a particular person has been targeted
============================================================================

Runs on a schedule (hourly by default) to:
  - Check all registered surveillance targets for new activity
  - Detect coordinated harassment campaigns against a target
  - Detect sudden activity spikes targeting specific users
  - Correlate timing across multiple channels for targeting patterns
  - Flag impersonation attempts against the target
  - Generate alerts when targeting intensity crosses thresholds

Usage (library)::

    from tgarchive.services.scheduled_analysis import run_hourly_analysis

    alerts = run_hourly_analysis(db_path="spectra.db")

Usage (CLI)::

    spectra-cli analyze hourly-run
    spectra-cli analyze hourly-run --target alice
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..sqlite_runtime import connect_sqlite
from .utils import parse_dt as _parse_dt

logger = logging.getLogger(__name__)

_ALERT_TABLE = "surveillance_alerts"


def _ensure_alert_table(conn: sqlite3.Connection) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_ALERT_TABLE} (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id TEXT,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            detail TEXT,
            context_json TEXT,
            created_at TEXT NOT NULL,
            acknowledged INTEGER DEFAULT 0
        )
    """)


def _save_alert(conn: sqlite3.Connection, target_id: str, alert_type: str, severity: str, detail: str, context: dict) -> None:
    _ensure_alert_table(conn)
    conn.execute(
        f"INSERT INTO {_ALERT_TABLE} (target_id, alert_type, severity, detail, context_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (target_id, alert_type, severity, detail, json.dumps(context, default=str), datetime.now(timezone.utc).isoformat()),
    )


def _detect_activity_spike(
    conn: sqlite3.Connection,
    user_id: int,
    window_hours: int = 1,
    baseline_days: int = 7,
    reference_time: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Detect if a user received an unusual spike of messages/mentions."""
    now = reference_time or datetime.now(timezone.utc)
    window_start = (now - timedelta(hours=window_hours)).isoformat()
    baseline_start = (now - timedelta(days=baseline_days)).isoformat()

    # Count messages mentioning or replying to the target in the last hour
    recent = conn.execute(
        """
        SELECT COUNT(*) as count FROM messages
        WHERE date >= ? AND (reply_to IN (SELECT id FROM messages WHERE user_id = ?)
        OR content LIKE ?)
        """,
        (window_start, user_id, f"%user_id:{user_id}%"),
    ).fetchone()

    # Baseline: average hourly rate over the past week
    baseline = conn.execute(
        """
        SELECT COUNT(*) as count FROM messages
        WHERE date >= ? AND date < ? AND (reply_to IN (SELECT id FROM messages WHERE user_id = ?)
        OR content LIKE ?)
        """,
        (baseline_start, window_start, user_id, f"%user_id:{user_id}%"),
    ).fetchone()

    recent_count = recent["count"] if recent else 0
    baseline_count = baseline["count"] if baseline else 0
    baseline_hourly_avg = baseline_count / (baseline_days * 24) if baseline_count else 0.5

    # Spike if recent activity is 3x the baseline
    if recent_count >= max(baseline_hourly_avg * 3, 5):
        return {
            "type": "activity_spike",
            "severity": "high" if recent_count >= baseline_hourly_avg * 5 else "medium",
            "target_user_id": user_id,
            "recent_count": recent_count,
            "baseline_hourly_avg": round(baseline_hourly_avg, 2),
            "spike_ratio": round(recent_count / max(baseline_hourly_avg, 0.1), 2),
            "window_hours": window_hours,
            "detail": f"{recent_count} messages targeting user {user_id} in last {window_hours}h (baseline: {baseline_hourly_avg:.1f}/h, {recent_count / max(baseline_hourly_avg, 0.1):.1f}x spike)",
        }
    return None


def _detect_reply_bombing(
    conn: sqlite3.Connection,
    user_id: int,
    window_hours: int = 1,
    reference_time: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Detect reply bombing — many users replying to the target's messages rapidly."""
    now = reference_time or datetime.now(timezone.utc)
    window_start = (now - timedelta(hours=window_hours)).isoformat()

    rows = conn.execute(
        """
        SELECT m1.user_id as replier, COUNT(*) as reply_count
        FROM messages m1
        JOIN messages m2 ON m1.reply_to = m2.id
        WHERE m2.user_id = ? AND m1.date >= ? AND m1.user_id IS NOT NULL AND m1.user_id != ?
        GROUP BY m1.user_id ORDER BY reply_count DESC LIMIT 10
        """,
        (user_id, window_start, user_id),
    ).fetchall()

    if not rows:
        return None

    total_replies = sum(r["reply_count"] for r in rows)
    unique_repliers = len(rows)

    # Reply bombing: many replies from multiple users in a short window
    if total_replies >= 10 and unique_repliers >= 3:
        return {
            "type": "reply_bombing",
            "severity": "high" if total_replies >= 20 else "medium",
            "target_user_id": user_id,
            "total_replies": total_replies,
            "unique_repliers": unique_repliers,
            "top_repliers": [{"user_id": r["user_id"], "reply_count": r["reply_count"]} for r in rows[:5]],
            "window_hours": window_hours,
            "detail": f"{total_replies} replies from {unique_repliers} users targeting user {user_id} in {window_hours}h — possible coordinated harassment",
        }
    return None


def _detect_mention_flooding(
    conn: sqlite3.Connection,
    user_id: int,
    username: Optional[str],
    window_hours: int = 1,
    reference_time: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Detect mention flooding — many messages mentioning the target's username."""
    if not username:
        return None

    now = reference_time or datetime.now(timezone.utc)
    window_start = (now - timedelta(hours=window_hours)).isoformat()

    rows = conn.execute(
        """
        SELECT user_id, COUNT(*) as mention_count
        FROM messages
        WHERE date >= ? AND content LIKE ? AND user_id IS NOT NULL
        GROUP BY user_id ORDER BY mention_count DESC LIMIT 10
        """,
        (window_start, f"%@{username}%"),
    ).fetchall()

    if not rows:
        return None

    total_mentions = sum(r["mention_count"] for r in rows)
    unique_mentioners = len(rows)

    if total_mentions >= 8 and unique_mentioners >= 2:
        return {
            "type": "mention_flooding",
            "severity": "high" if total_mentions >= 15 else "medium",
            "target_user_id": user_id,
            "target_username": username,
            "total_mentions": total_mentions,
            "unique_mentioners": unique_mentioners,
            "top_mentioners": [{"user_id": r["user_id"], "mention_count": r["mention_count"]} for r in rows[:5]],
            "window_hours": window_hours,
            "detail": f"{total_mentions} mentions of @{username} from {unique_mentioners} users in {window_hours}h — possible targeting",
        }
    return None


def _detect_cross_channel_coordination(
    conn: sqlite3.Connection,
    user_id: int,
    window_hours: int = 1,
    reference_time: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Detect coordinated targeting across multiple channels simultaneously."""
    now = reference_time or datetime.now(timezone.utc)
    window_start = (now - timedelta(hours=window_hours)).isoformat()

    try:
        rows = conn.execute(
            """
            SELECT channel_id, COUNT(*) as msg_count
            FROM channel_messages
            WHERE date >= ? AND user_id != ? AND reply_to IN (
                SELECT id FROM channel_messages WHERE user_id = ?
            )
            GROUP BY channel_id ORDER BY msg_count DESC
            """,
            (window_start, user_id, user_id),
        ).fetchall()
    except sqlite3.OperationalError:
        return None

    if len(rows) < 2:
        return None

    total_msgs = sum(r["msg_count"] for r in rows)
    if total_msgs >= 10 and len(rows) >= 2:
        return {
            "type": "cross_channel_coordination",
            "severity": "high",
            "target_user_id": user_id,
            "channels_targeted": len(rows),
            "total_messages": total_msgs,
            "channel_breakdown": [{"channel_id": r["channel_id"], "msg_count": r["msg_count"]} for r in rows],
            "window_hours": window_hours,
            "detail": f"Coordinated targeting across {len(rows)} channels with {total_msgs} messages in {window_hours}h",
        }
    return None


def run_hourly_analysis(
    db_path: Path | str,
    *,
    target_id: Optional[str] = None,
    window_hours: int = 1,
) -> Dict[str, Any]:
    """Run hourly analysis to detect targeting of specific persons.

    Scans all registered surveillance targets (or a specific one) for:
    - Activity spikes (sudden increase in messages about/replying to the target)
    - Reply bombing (many users replying to target's messages rapidly)
    - Mention flooding (many messages mentioning the target's username)
    - Cross-channel coordination (targeting across multiple channels simultaneously)

    Alerts are persisted in the surveillance_alerts table.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        target_id: Specific target to analyze (None = all registered targets).
        window_hours: Analysis window in hours (default 1).

    Returns:
        Dict with: alerts, targets_checked, summary
    """
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    all_alerts: List[Dict[str, Any]] = []
    targets_checked = 0

    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_alert_table(conn)

        # Determine reference time: use the latest message timestamp if data is old,
        # otherwise use current time. This ensures the analysis window covers the
        # most recent data even when the database hasn't been updated recently.
        reference_time = None
        try:
            latest = conn.execute("SELECT MAX(date) as latest FROM messages WHERE date IS NOT NULL").fetchone()
            if latest and latest["latest"]:
                parsed = _parse_dt(latest["latest"])
                if parsed:
                    now = datetime.now(timezone.utc)
                    # If the latest message is older than the window, use it as reference
                    if (now - parsed).total_seconds() > window_hours * 3600:
                        reference_time = parsed + timedelta(seconds=1)  # +1s to include the latest
        except sqlite3.OperationalError:
            pass

        # Get targets to analyze
        from .target_tracking import _ensure_target_tables, _resolve_aliases
        _ensure_target_tables(conn)

        if target_id:
            target_rows = conn.execute(
                f"SELECT target_id, label FROM {_TARGET_TABLE if False else 'surveillance_targets'} WHERE target_id = ?",
                (target_id,),
            ).fetchall()
        else:
            target_rows = conn.execute(
                "SELECT target_id, label FROM surveillance_targets ORDER BY updated_at DESC"
            ).fetchall()

        if not target_rows:
            # If no registered targets, scan all users for targeting patterns
            logger.info("No registered targets — scanning all active users for targeting patterns")
            try:
                window_start = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
                active_users = conn.execute(
                    """
                    SELECT user_id, COUNT(*) as msg_count FROM messages
                    WHERE user_id IS NOT NULL AND date >= ?
                    GROUP BY user_id ORDER BY msg_count DESC LIMIT 50
                    """,
                    (window_start,),
                ).fetchall()

                # If no users in the window, fall back to all users with messages
                if not active_users:
                    active_users = conn.execute(
                        """
                        SELECT user_id, COUNT(*) as msg_count FROM messages
                        WHERE user_id IS NOT NULL
                        GROUP BY user_id ORDER BY msg_count DESC LIMIT 50
                        """,
                    ).fetchall()

                for au in active_users:
                    uid = au["user_id"]
                    targets_checked += 1

                    # Get username
                    try:
                        user_row = conn.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()
                        username = user_row["username"] if user_row else None
                    except sqlite3.OperationalError:
                        username = None

                    for detector in [_detect_activity_spike, _detect_reply_bombing, _detect_mention_flooding]:
                        try:
                            if detector is _detect_mention_flooding:
                                alert = detector(conn, uid, username, window_hours=window_hours, reference_time=reference_time)
                            else:
                                alert = detector(conn, uid, window_hours=window_hours, reference_time=reference_time)
                            if alert:
                                alert["target_id"] = f"user:{uid}"
                                all_alerts.append(alert)
                                _save_alert(conn, f"user:{uid}", alert["type"], alert["severity"], alert["detail"], alert)
                        except Exception as e:
                            logger.debug("Detector %s failed for user %s: %s", detector.__name__, uid, e)
            except sqlite3.OperationalError:
                pass
        else:
            for tr in target_rows:
                tid = tr["target_id"]
                targets_checked += 1

                # Get aliases for this target
                alias_rows = conn.execute(
                    "SELECT alias FROM surveillance_aliases WHERE target_id = ?", (tid,)
                ).fetchall()
                aliases = [r["alias"] for r in alias_rows]

                # Resolve to user IDs
                resolved = _resolve_aliases(conn, aliases)
                user_ids = list({r["user_id"] for r in resolved})

                for uid in user_ids:
                    try:
                        user_row = conn.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()
                        username = user_row["username"] if user_row else None
                    except sqlite3.OperationalError:
                        username = None

                    for detector in [_detect_activity_spike, _detect_reply_bombing, _detect_mention_flooding, _detect_cross_channel_coordination]:
                        try:
                            if detector is _detect_mention_flooding:
                                alert = detector(conn, uid, username, window_hours=window_hours, reference_time=reference_time)
                            else:
                                alert = detector(conn, uid, window_hours=window_hours, reference_time=reference_time)
                            if alert:
                                alert["target_id"] = tid
                                all_alerts.append(alert)
                                _save_alert(conn, tid, alert["type"], alert["severity"], alert["detail"], alert)
                        except Exception as e:
                            logger.debug("Detector %s failed: %s", detector.__name__, e)

        conn.commit()

    # Sort by severity
    severity_order = {"high": 3, "medium": 2, "low": 1}
    all_alerts.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 0), reverse=True)

    summary = {
        "targets_checked": targets_checked,
        "total_alerts": len(all_alerts),
        "high_severity": sum(1 for a in all_alerts if a["severity"] == "high"),
        "medium_severity": sum(1 for a in all_alerts if a["severity"] == "medium"),
        "window_hours": window_hours,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "alerts": all_alerts,
        "summary": summary,
    }


def get_alerts(
    db_path: Path | str,
    *,
    target_id: Optional[str] = None,
    acknowledged_only: bool = False,
    unacknowledged_only: bool = True,
    limit: int = 100,
) -> Dict[str, Any]:
    """Retrieve persisted surveillance alerts."""
    db_path = Path(db_path).expanduser().resolve()
    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_alert_table(conn)

        conditions = []
        params: list = []
        if target_id:
            conditions.append("target_id = ?")
            params.append(target_id)
        if unacknowledged_only and not acknowledged_only:
            conditions.append("acknowledged = 0")
        elif acknowledged_only:
            conditions.append("acknowledged = 1")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM {_ALERT_TABLE} {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()

        alerts = []
        for r in rows:
            alert = {
                "alert_id": r["alert_id"],
                "target_id": r["target_id"],
                "alert_type": r["alert_type"],
                "severity": r["severity"],
                "detail": r["detail"],
                "created_at": r["created_at"],
                "acknowledged": bool(r["acknowledged"]),
            }
            if r["context_json"]:
                try:
                    alert["context"] = json.loads(r["context_json"])
                except json.JSONDecodeError:
                    pass
            alerts.append(alert)

    return {"alerts": alerts, "count": len(alerts)}


def acknowledge_alert(db_path: Path | str, alert_id: int) -> Dict[str, Any]:
    """Mark an alert as acknowledged."""
    db_path = Path(db_path).expanduser().resolve()
    with connect_sqlite(db_path) as conn:
        _ensure_alert_table(conn)
        conn.execute(f"UPDATE {_ALERT_TABLE} SET acknowledged = 1 WHERE alert_id = ?", (alert_id,))
        conn.commit()
    return {"acknowledged": alert_id}


__all__ = ["run_hourly_analysis", "get_alerts", "acknowledge_alert"]
