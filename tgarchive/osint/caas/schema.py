from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

CAAS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS caas_profile_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    topic_id INTEGER,
    sender_id INTEGER,
    sender_username TEXT,
    date TEXT NOT NULL,
    content TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    error TEXT,
    UNIQUE(channel_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_caas_queue_status ON caas_profile_queue(status);

CREATE TABLE IF NOT EXISTS caas_channel_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER UNIQUE NOT NULL,
    channel_link TEXT,
    title TEXT,
    discovered_at TEXT NOT NULL,
    last_scanned_at TEXT,
    caas_likelihood REAL NOT NULL DEFAULT 0.0,
    bot_shop_likelihood REAL NOT NULL DEFAULT 0.0,
    critical_alert_score REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'candidate',
    inferred_categories TEXT,
    enterprise_model TEXT,
    geo_signals TEXT,
    urgency_signals TEXT,
    raw_evidence_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_caas_channel_priority ON caas_channel_profile(caas_likelihood DESC, critical_alert_score DESC);

CREATE TABLE IF NOT EXISTS caas_message_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    detected_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    service_categories TEXT,
    enterprise_model TEXT,
    seller_aliases TEXT,
    delivery_model TEXT,
    payment_methods TEXT,
    raw_json TEXT,
    UNIQUE(channel_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_caas_msg_detected ON caas_message_profile(detected_at);

CREATE TABLE IF NOT EXISTS actor_entity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL DEFAULT 'telegram',
    canonical_handle TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    bot_likelihood REAL NOT NULL DEFAULT 0.0,
    caas_severity REAL NOT NULL DEFAULT 0.0,
    aggregated_intel_json TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(platform, canonical_handle)
);

CREATE TABLE IF NOT EXISTS caas_alert (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    severity TEXT NOT NULL,
    channel_id INTEGER,
    actor_id INTEGER,
    alert_type TEXT NOT NULL,
    score REAL NOT NULL,
    summary TEXT NOT NULL,
    evidence_json TEXT,
    status TEXT NOT NULL DEFAULT 'new'
);

CREATE TABLE IF NOT EXISTS caas_flagged_channel (
    channel_id INTEGER PRIMARY KEY,
    reason TEXT,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS caas_invite_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_name TEXT NOT NULL UNIQUE,
    source_invite TEXT,
    reason TEXT,
    flagged INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS caas_invite_list_channel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL REFERENCES caas_invite_list(id) ON DELETE CASCADE,
    channel_id INTEGER NOT NULL,
    channel_ref TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(list_id, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_caas_invite_list_channel_id ON caas_invite_list_channel(channel_id);

CREATE TABLE IF NOT EXISTS caas_flagged_message_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    list_id INTEGER REFERENCES caas_invite_list(id),
    list_name TEXT,
    trigger_type TEXT NOT NULL,
    reason TEXT,
    content TEXT
);
CREATE INDEX IF NOT EXISTS idx_caas_flagged_message_log_channel_id ON caas_flagged_message_log(channel_id);
CREATE INDEX IF NOT EXISTS idx_caas_flagged_message_log_message_id ON caas_flagged_message_log(message_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_caas_flagged_message_log_dedupe
ON caas_flagged_message_log(channel_id, message_id, trigger_type, ifnull(list_id, -1));

CREATE TABLE IF NOT EXISTS caas_tracked_target (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL CHECK(target_type IN ('actor_username', 'channel_id')),
    actor_username TEXT,
    channel_id INTEGER,
    reason TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(
        (target_type = 'actor_username' AND actor_username IS NOT NULL AND channel_id IS NULL)
        OR
        (target_type = 'channel_id' AND channel_id IS NOT NULL AND actor_username IS NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_caas_tracked_target_actor
ON caas_tracked_target(target_type, actor_username);
CREATE UNIQUE INDEX IF NOT EXISTS idx_caas_tracked_target_channel
ON caas_tracked_target(target_type, channel_id);
"""


def ensure_schema(db: Any) -> None:
    db.conn.executescript(CAAS_SCHEMA_SQL)
    db.conn.commit()


def enqueue_profile_candidate(db: Any, *, channel_id: int, message_id: int, topic_id: Optional[int], sender_id: Optional[int], sender_username: Optional[str], date: str, content: str) -> None:
    ensure_schema(db)
    db.conn.execute(
        """
        INSERT OR IGNORE INTO caas_profile_queue
        (channel_id, message_id, topic_id, sender_id, sender_username, date, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (channel_id, message_id, topic_id, sender_id, sender_username, date, content, datetime.utcnow().isoformat()),
    )
    db.conn.commit()


def upsert_channel_profile(db: Any, *, channel_id: int, channel_link: Optional[str], title: Optional[str], triage_result: dict[str, Any]) -> None:
    ensure_schema(db)
    now = datetime.utcnow().isoformat()
    db.conn.execute(
        """
        INSERT INTO caas_channel_profile
        (channel_id, channel_link, title, discovered_at, last_scanned_at, caas_likelihood, bot_shop_likelihood, critical_alert_score, inferred_categories, enterprise_model, geo_signals, urgency_signals, raw_evidence_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            channel_link=excluded.channel_link,
            title=excluded.title,
            last_scanned_at=excluded.last_scanned_at,
            caas_likelihood=excluded.caas_likelihood,
            bot_shop_likelihood=excluded.bot_shop_likelihood,
            critical_alert_score=excluded.critical_alert_score,
            inferred_categories=excluded.inferred_categories,
            enterprise_model=excluded.enterprise_model,
            geo_signals=excluded.geo_signals,
            urgency_signals=excluded.urgency_signals,
            raw_evidence_json=excluded.raw_evidence_json
        """,
        (
            channel_id,
            channel_link,
            title,
            now,
            now,
            triage_result.get("caas_likelihood", 0.0),
            triage_result.get("bot_shop_likelihood", 0.0),
            triage_result.get("critical_alert_score", 0.0),
            json.dumps(triage_result.get("criminal_categories", [])),
            json.dumps(triage_result.get("enterprise_model", [])),
            json.dumps(triage_result.get("geo_signals", [])),
            json.dumps(triage_result.get("urgency_signals", [])),
            triage_result.get("evidence_json", "{}"),
        ),
    )
    db.conn.commit()


def upsert_flagged_channel(db: Any, *, channel_id: int, reason: Optional[str] = None, active: bool = True) -> None:
    ensure_schema(db)
    now = datetime.utcnow().isoformat()
    db.conn.execute(
        """
        INSERT INTO caas_flagged_channel(channel_id, reason, created_at, active)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            reason=excluded.reason,
            active=excluded.active
        """,
        (channel_id, reason, now, 1 if active else 0),
    )
    db.conn.commit()


def add_or_update_invite_list(
    db: Any,
    *,
    list_name: str,
    channels: list[int],
    source_invite: Optional[str] = None,
    reason: Optional[str] = None,
    flagged: bool = False,
) -> int:
    ensure_schema(db)
    now = datetime.utcnow().isoformat()
    db.conn.execute(
        """
        INSERT INTO caas_invite_list(list_name, source_invite, reason, flagged, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(list_name) DO UPDATE SET
            source_invite=excluded.source_invite,
            reason=excluded.reason,
            flagged=excluded.flagged,
            updated_at=excluded.updated_at
        """,
        (list_name, source_invite, reason, 1 if flagged else 0, now, now),
    )
    row = db.conn.execute("SELECT id FROM caas_invite_list WHERE list_name = ?", (list_name,)).fetchone()
    if not row:
        raise RuntimeError(f"Failed to load invite list id for {list_name}")
    list_id = int(row[0])

    for channel_id in channels:
        db.conn.execute(
            """
            INSERT INTO caas_invite_list_channel(list_id, channel_id, channel_ref, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(list_id, channel_id) DO UPDATE SET
                channel_ref=excluded.channel_ref
            """,
            (list_id, int(channel_id), str(channel_id), now),
        )

    db.conn.commit()
    return list_id


def upsert_tracked_target(
    db: Any,
    *,
    target_type: str,
    actor_username: Optional[str] = None,
    channel_id: Optional[int] = None,
    reason: Optional[str] = None,
    active: bool = True,
) -> int:
    ensure_schema(db)
    if target_type not in {"actor_username", "channel_id"}:
        raise ValueError("target_type must be one of: actor_username, channel_id")

    now = datetime.utcnow().isoformat()
    if target_type == "actor_username":
        if not actor_username:
            raise ValueError("actor_username is required for actor_username tracking")
        normalized_username = actor_username.strip().lstrip("@").lower()
        db.conn.execute(
            """
            INSERT INTO caas_tracked_target(target_type, actor_username, channel_id, reason, active, created_at, updated_at)
            VALUES (?, ?, NULL, ?, ?, ?, ?)
            ON CONFLICT(target_type, actor_username) DO UPDATE SET
                reason=excluded.reason,
                active=excluded.active,
                updated_at=excluded.updated_at
            """,
            (target_type, normalized_username, reason, 1 if active else 0, now, now),
        )
        row = db.conn.execute(
            "SELECT id FROM caas_tracked_target WHERE target_type = ? AND actor_username = ?",
            (target_type, normalized_username),
        ).fetchone()
    else:
        if channel_id is None:
            raise ValueError("channel_id is required for channel_id tracking")
        db.conn.execute(
            """
            INSERT INTO caas_tracked_target(target_type, actor_username, channel_id, reason, active, created_at, updated_at)
            VALUES (?, NULL, ?, ?, ?, ?, ?)
            ON CONFLICT(target_type, channel_id) DO UPDATE SET
                reason=excluded.reason,
                active=excluded.active,
                updated_at=excluded.updated_at
            """,
            (target_type, int(channel_id), reason, 1 if active else 0, now, now),
        )
        row = db.conn.execute(
            "SELECT id FROM caas_tracked_target WHERE target_type = ? AND channel_id = ?",
            (target_type, int(channel_id)),
        ).fetchone()

    if not row:
        raise RuntimeError("Failed to resolve tracked target id")
    db.conn.commit()
    return int(row[0])
