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
