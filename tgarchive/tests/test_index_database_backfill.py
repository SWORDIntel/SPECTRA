import json

from tgarchive.db.index_outbox import IndexOutbox
from tgarchive.db.index_projector import IndexProjector
from tgarchive.services.index_database_backfill import backfill_database_records
from tgarchive.sqlite_runtime import connect_sqlite


def test_database_backfill_is_idempotent_and_excludes_sensitive_audit_fields(tmp_path):
    database = tmp_path / "spectra.db"
    with connect_sqlite(database) as connection:
        IndexOutbox.ensure_schema(connection)
        connection.executescript(
            """
            CREATE TABLE checkpoints(
                id INTEGER PRIMARY KEY,
                last_message_id INTEGER,
                checkpoint_time TEXT,
                context TEXT
            );
            CREATE TABLE task_events(
                event_id INTEGER PRIMARY KEY,
                task_id TEXT,
                kind TEXT,
                status TEXT,
                pid INTEGER,
                event_at TEXT
            );
            CREATE TABLE operation_audit(
                audit_id TEXT PRIMARY KEY,
                source TEXT,
                actor TEXT,
                operation_id TEXT,
                status TEXT,
                started_at TEXT,
                finished_at TEXT,
                request_text TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO checkpoints VALUES (1, 42, '2026-07-29T00:00:00+00:00', 'sync')"
        )
        connection.execute(
            "INSERT INTO task_events VALUES (2, 'task-2', 'download', 'completed', 123, "
            "'2026-07-29T00:01:00+00:00')"
        )
        connection.execute(
            "INSERT INTO operation_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "audit-secret",
                "agent",
                "operator",
                "operation-1",
                "completed",
                "2026-07-29T00:00:00+00:00",
                "2026-07-29T00:01:00+00:00",
                "api_hash=must-not-enter-outbox",
            ),
        )

    first = backfill_database_records(database)
    second = backfill_database_records(database)

    assert first["scanned"] == 2
    assert first["inserted"] == 2
    assert second["inserted"] == 0
    assert second["already_present"] == 2
    events = IndexOutbox(database).events()
    serialized = json.dumps(events)
    assert {event["source_table"] for event in events} == {"checkpoints", "task_events"}
    assert "must-not-enter-outbox" not in serialized

    with IndexProjector(database) as projector:
        assert projector.drain(batch_size=10)["processed"] == 2
        assert projector.verify(projection="checkpoints", native=True)["ok"] is True
        assert projector.verify(projection="events", native=True)["ok"] is True
