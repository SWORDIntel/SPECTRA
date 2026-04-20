from pathlib import Path

from tgarchive.db import SpectraDB
from tgarchive.osint.caas.queue_worker import process_queue
from tgarchive.osint.caas.schema import (
    add_or_update_invite_list,
    ensure_schema,
    enqueue_profile_candidate,
    upsert_tracked_target,
    upsert_flagged_channel,
)


def _count(db: SpectraDB, sql: str, params=()):
    row = db.conn.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def test_flagged_channel_logs_messages(tmp_path: Path):
    db_path = tmp_path / "caas.db"
    db = SpectraDB(db_path)
    ensure_schema(db)

    upsert_flagged_channel(db, channel_id=1001, reason="manual review", active=True)
    enqueue_profile_candidate(
        db,
        channel_id=1001,
        message_id=501,
        topic_id=None,
        sender_id=42,
        sender_username="tester",
        date="2026-01-01T00:00:00",
        content="Need fresh logs 500 usd",
    )

    processed = process_queue(db_path=db_path, batch_size=100, once=True)
    assert processed == 1

    assert _count(db, "SELECT COUNT(*) FROM caas_flagged_message_log") == 1
    assert _count(db, "SELECT COUNT(*) FROM caas_flagged_message_log WHERE trigger_type='channel'") == 1


def test_flagged_invite_list_logs_messages(tmp_path: Path):
    db_path = tmp_path / "caas.db"
    db = SpectraDB(db_path)
    ensure_schema(db)

    add_or_update_invite_list(
        db,
        list_name="incident-alpha",
        channels=[2001, 2002],
        source_invite="https://t.me/+example",
        reason="list-wide surveillance",
        flagged=True,
    )
    enqueue_profile_candidate(
        db,
        channel_id=2002,
        message_id=777,
        topic_id=None,
        sender_id=88,
        sender_username="source",
        date="2026-01-01T00:00:00",
        content="panel access monthly $250",
    )

    processed = process_queue(db_path=db_path, batch_size=100, once=True)
    assert processed == 1

    assert _count(db, "SELECT COUNT(*) FROM caas_flagged_message_log") == 1
    assert _count(db, "SELECT COUNT(*) FROM caas_flagged_message_log WHERE trigger_type='invite_list'") == 1


def test_tracked_channel_logs_messages(tmp_path: Path):
    db_path = tmp_path / "caas.db"
    db = SpectraDB(db_path)
    ensure_schema(db)

    upsert_tracked_target(
        db,
        target_type="channel_id",
        channel_id=3001,
        reason="watch channel 3001",
        active=True,
    )
    enqueue_profile_candidate(
        db,
        channel_id=3001,
        message_id=1001,
        topic_id=None,
        sender_id=1,
        sender_username="sender",
        date="2026-01-01T00:00:00",
        content="hello from tracked channel",
    )

    processed = process_queue(db_path=db_path, batch_size=100, once=True)
    assert processed == 1
    assert _count(db, "SELECT COUNT(*) FROM caas_flagged_message_log WHERE trigger_type='tracked_channel'") == 1


def test_tracked_actor_username_logs_messages(tmp_path: Path):
    db_path = tmp_path / "caas.db"
    db = SpectraDB(db_path)
    ensure_schema(db)

    upsert_tracked_target(
        db,
        target_type="actor_username",
        actor_username="@target_actor",
        reason="watch actor",
        active=True,
    )
    enqueue_profile_candidate(
        db,
        channel_id=4001,
        message_id=1002,
        topic_id=None,
        sender_id=2,
        sender_username="target_actor",
        date="2026-01-01T00:00:00",
        content="actor message",
    )

    processed = process_queue(db_path=db_path, batch_size=100, once=True)
    assert processed == 1
    assert _count(db, "SELECT COUNT(*) FROM caas_flagged_message_log WHERE trigger_type='tracked_actor'") == 1
