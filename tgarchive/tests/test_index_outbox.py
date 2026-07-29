import json
import multiprocessing
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from tgarchive.db.index_outbox import IndexOutbox, OutboxLeaseLostError
from tgarchive.db.index_projector import (
    ARCHIVE_MEMBER_PROJECTION,
    CHECKPOINT_PROJECTION,
    EVENT_PROJECTION,
    EXPORT_RECORD_PROJECTION,
    IndexProjector,
    QIHSE_PROJECTION,
    _native_sync_timeout,
    keystone_compound_key,
    keystone_record_key,
)
from tgarchive.db.native_store_lock import NativeStoreLock
from tgarchive.sqlite_runtime import connect_sqlite


def _native_sync_interval_worker(database, store_kind, ready, start, results):
    from tgarchive.db import index_projector as projector_module

    projector = IndexProjector(database)

    def delayed_native_run(command, **_kwargs):
        entered = time.monotonic()
        time.sleep(0.2)
        exited = time.monotonic()
        results.put(("interval", os.getpid(), entered, exited))
        return subprocess.CompletedProcess(
            command,
            0,
            'SPECTRA_NATIVE_PROBE={"available":true,"ok":true}\n',
            "",
        )

    projector_module.subprocess.run = delayed_native_run
    ready.put(os.getpid())
    start.wait(5)
    try:
        if store_kind == "qihse":
            result = projector._sync_qihse([], rebuild=True, timeout_limit=5)
        else:
            result = projector._sync_graph([], rebuild=True, timeout_limit=5)
        results.put(("result", os.getpid(), result["ok"]))
    finally:
        projector.close()


def _native_lock_holder(store_path, acquired, release, *, crash=False):
    with NativeStoreLock(store_path, timeout=2):
        acquired.set()
        if crash:
            os._exit(23)
        release.wait(5)


def _ordered_projector_worker(
    database,
    *,
    pause_after_claim,
    claimed,
    release,
    started,
    results,
):
    projector = IndexProjector(database)
    projector._sync_qihse = lambda _rows, **_kwargs: {
        "available": True,
        "ok": True,
    }
    projector._sync_graph = lambda _rows, **_kwargs: {
        "available": True,
        "ok": True,
    }
    original_claim = projector.outbox.claim

    def observed_claim(**kwargs):
        events = original_claim(**kwargs)
        claimed.set()
        if pause_after_claim:
            if not release.wait(10):
                raise TimeoutError("test worker release timed out")
        return events

    projector.outbox.claim = observed_claim
    started.set()
    try:
        result = projector.process(batch_size=1, lease_seconds=10)
        results.put((os.getpid(), result))
    finally:
        projector.close()


def test_shared_sqlite_policy_enables_wal_and_busy_timeout(tmp_path):
    database = tmp_path / "spectra.db"
    with connect_sqlite(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 60000
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_outbox_is_idempotent_and_tracks_processing(tmp_path):
    outbox = IndexOutbox(tmp_path / "spectra.db")
    event = {
        "source_table": "messages",
        "source_key": "123",
        "event_type": "upsert",
        "payload": {"message_id": 123, "text": "hello"},
        "source_revision": "v1",
    }

    sequence_id = outbox.append(**event)
    assert sequence_id is not None
    assert outbox.append(**event) is None
    claimed = outbox.claim(batch_size=1)
    assert claimed[0]["sequence_id"] == sequence_id
    assert claimed[0]["payload"] == event["payload"]
    assert outbox.status()["outbox"] == {"total": 1, "pending": 0, "claimed": 1, "processed": 0, "failed": 0}

    outbox.complete(sequence_id, claim_token=claimed[0]["claim_token"])
    assert outbox.status()["outbox"] == {"total": 1, "pending": 0, "claimed": 0, "processed": 1, "failed": 0}


def test_outbox_rejects_invalid_claim_and_sequence(tmp_path):
    outbox = IndexOutbox(tmp_path / "spectra.db")
    with pytest.raises(ValueError):
        outbox.claim(batch_size=0)
    with pytest.raises(ValueError):
        outbox.complete(0, claim_token="lease")


def test_outbox_completes_mixed_batch_in_one_call(tmp_path):
    outbox = IndexOutbox(tmp_path / "spectra.db")
    first = outbox.append(
        source_table="messages",
        source_key="1",
        event_type="upsert",
        payload={"message_id": 1},
    )
    second = outbox.append(
        source_table="messages",
        source_key="2",
        event_type="upsert",
        payload={"message_id": 2},
    )
    claimed = outbox.claim(batch_size=2)

    outbox.complete_batch(
        {int(first): None, int(second): "projection failed"},
        claim_tokens={
            int(event["sequence_id"]): event["claim_token"]
            for event in claimed
        },
    )

    rows = outbox.events()
    assert rows[0]["processed_at"] is not None
    assert rows[0]["error"] is None
    assert rows[1]["processed_at"] is None
    assert rows[1]["claimed_at"] is None
    assert rows[1]["error"] == "projection failed"


def test_outbox_claim_lease_prevents_duplicate_delivery(tmp_path):
    outbox = IndexOutbox(tmp_path / "spectra.db")
    outbox.append(
        source_table="messages",
        source_key="1",
        event_type="upsert",
        payload={"message_id": 1},
        source_revision="v1",
    )

    assert len(outbox.claim()) == 1
    assert outbox.claim() == []


def test_outbox_reclaims_expired_lease_after_worker_crash(tmp_path):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    sequence_id = outbox.append(
        source_table="messages",
        source_key="1",
        event_type="upsert",
        payload={"message_id": 1},
        source_revision="v1",
    )
    assert outbox.claim(lease_seconds=1)[0]["sequence_id"] == sequence_id
    with connect_sqlite(database) as connection:
        connection.execute(
            "UPDATE index_outbox SET claimed_at='1970-01-01T00:00:00+00:00' WHERE sequence_id=?",
            (sequence_id,),
        )

    reclaimed = outbox.claim(lease_seconds=1)

    assert reclaimed[0]["sequence_id"] == sequence_id
    assert outbox.events()[0]["attempts"] == 2


def test_reclaimed_event_rejects_stale_worker_acknowledgement(tmp_path):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    sequence_id = outbox.append(
        source_table="messages",
        source_key="1",
        event_type="upsert",
        payload={"message_id": 1},
        source_revision="v1",
    )
    stale = outbox.claim(lease_seconds=1)[0]
    with connect_sqlite(database) as connection:
        connection.execute(
            "UPDATE index_outbox SET claimed_at='1970-01-01T00:00:00+00:00' WHERE sequence_id=?",
            (sequence_id,),
        )
    current = outbox.claim(lease_seconds=1)[0]

    with pytest.raises(OutboxLeaseLostError):
        outbox.complete(
            int(sequence_id),
            claim_token=stale["claim_token"],
            error="stale worker failure",
        )

    row = outbox.events()[0]
    assert row["processed_at"] is None
    assert row["claim_token"] == current["claim_token"]
    assert row["error"] is None

    outbox.complete(int(sequence_id), claim_token=current["claim_token"])
    assert outbox.events()[0]["processed_at"] is not None


def test_concurrent_outbox_writers_do_not_lose_events_or_raise_locks(tmp_path):
    outbox = IndexOutbox(tmp_path / "spectra.db")

    def write_event(message_id: int):
        return outbox.append(
            source_table="messages",
            source_key=str(message_id),
            event_type="upsert",
            payload={"message_id": message_id, "text": f"message {message_id}"},
            source_revision="v1",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        sequence_ids = list(executor.map(write_event, range(200)))

    assert all(sequence_id is not None for sequence_id in sequence_ids)
    assert outbox.status()["outbox"]["pending"] == 200


def test_projector_process_verify_and_rebuild(tmp_path):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    outbox.append(
        source_table="messages",
        source_key="100",
        event_type="upsert",
        payload={"message_id": 100, "channel_id": 10, "text": "alpha beta"},
        source_revision="v1",
    )
    outbox.append(
        source_table="tasks",
        source_key="task-a",
        event_type="status",
        payload={"status": "running"},
        source_revision="v1",
    )
    projector = IndexProjector(database)

    processed = projector.process(batch_size=10)
    assert processed["ok"] is True
    assert processed["processed"] == 2
    verified = projector.verify(native=False)
    assert verified["ok"] is True
    projections = {item["projection"]: item for item in verified["projections"]}
    assert projections["keystone.ids.v1"]["actual_rows"] == 1
    assert projections["keystone.media_manifest.v1"]["actual_rows"] == 0
    assert projections["qihse.content.v1"]["actual_rows"] == 2
    assert projections["fts.messages.v1"]["actual_rows"] == 1
    assert projections["qihse.graph.v1"]["actual_rows"] == 1
    fulltext = projector.fulltext_search("alpha", channel_id=10)
    assert len(fulltext) == 1
    assert fulltext[0]["payload"]["message_id"] == 100
    graph = projector.graph_neighbors(
        node_type="message",
        external_id="10:100",
        edge_type="IN_CHANNEL",
        direction="outgoing",
    )
    assert graph["found"] is True
    assert graph["records"][0]["to_node"]["node_key"] == "channel:10"

    with connect_sqlite(database) as connection:
        connection.execute(
            "UPDATE index_projection_records SET content_hash='drift' WHERE projection_name='qihse.content.v1'"
        )
    assert projector.verify(projection="qihse", native=False)["ok"] is False

    rebuilt = projector.rebuild(projection="qihse")
    assert rebuilt["ok"] is True
    assert rebuilt["events"] == 2
    assert projector.verify(projection="qihse", native=False)["ok"] is True


def test_projector_drain_consumes_multiple_batches(tmp_path):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    for message_id in range(5):
        outbox.append(
            source_table="messages",
            source_key=str(message_id),
            event_type="upsert",
            payload={"message_id": message_id, "text": f"message {message_id}"},
            source_revision="v1",
        )

    result = IndexProjector(database).drain(batch_size=2)

    assert result["ok"] is True
    assert result["drained"] is True
    assert result["processed"] == 5
    assert result["batches"] == 4


def test_native_sync_failure_is_bounded_and_not_acknowledged(tmp_path, monkeypatch):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    outbox.append(
        source_table="messages",
        source_key="1",
        event_type="upsert",
        payload={"message_id": 1, "text": "native failure"},
        source_revision="v1",
    )
    projector = IndexProjector(database)
    monkeypatch.setattr(
        projector,
        "_sync_qihse",
        lambda rows, **kwargs: {"available": False, "ok": False, "error": "native unavailable"},
    )

    for _ in range(5):
        result = projector.process()
        assert result["ok"] is False
        assert result["processed"] == 0
        assert result["failed"] == 1

    assert projector.process()["claimed"] == 0
    assert outbox.status()["outbox"]["pending"] == 0
    assert outbox.status()["outbox"]["processed"] == 0
    assert outbox.status()["outbox"]["failed"] == 1


def test_drain_and_rebuild_report_native_failures(tmp_path, monkeypatch):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    outbox.append(
        source_table="messages",
        source_key="1",
        event_type="upsert",
        payload={"channel_id": 10, "message_id": 1, "text": "native failure"},
        source_revision="v1",
    )
    projector = IndexProjector(database)
    failure = {
        "available": False,
        "ok": False,
        "error": "native unavailable",
    }
    monkeypatch.setattr(projector, "_sync_qihse", lambda _rows, **_kwargs: failure)

    drained = projector.drain(batch_size=1, max_batches=1)

    assert drained["ok"] is False
    assert drained["drained"] is False
    assert drained["failed"] == 1
    assert drained["last_batch"]["ok"] is False

    monkeypatch.setattr(
        projector,
        "_sync_qihse",
        lambda _rows, **_kwargs: {"available": True, "ok": True},
    )
    monkeypatch.setattr(
        projector,
        "_sync_graph",
        lambda _rows, **_kwargs: {"available": True, "ok": True},
    )
    assert projector.process(batch_size=1)["ok"] is True
    monkeypatch.setattr(projector, "_sync_graph", lambda _rows, **_kwargs: failure)

    rebuilt = projector.rebuild(projection="graph")

    assert rebuilt["ok"] is False
    assert rebuilt["graph_native"]["ok"] is False
    with connect_sqlite(database) as connection:
        state = connection.execute(
            "SELECT last_error FROM index_projection_state WHERE projection_name=?",
            ("qihse.graph.v1",),
        ).fetchone()
    assert state[0] == "native unavailable"


def test_process_converts_malformed_native_response_to_failure_result(
    tmp_path,
    monkeypatch,
):
    from tgarchive.db import index_projector as projector_module

    database = tmp_path / "spectra.db"
    IndexOutbox(database).append(
        source_table="messages",
        source_key="1",
        event_type="upsert",
        payload={"channel_id": 10, "message_id": 1, "text": "invalid native"},
        source_revision="v1",
    )
    projector = IndexProjector(database)

    def invalid_native(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            "SPECTRA_NATIVE_PROBE=not-json\n",
            "",
        )

    monkeypatch.setattr(projector_module, "_run_native_command", invalid_native)

    result = projector.process()

    assert result["ok"] is False
    assert result["processed"] == 0
    assert result["failed"] == 1
    assert result["qihse_native"]["ok"] is False
    assert result["graph_native"]["ok"] is False
    assert "invalid QIHSE" in result["failures"][0]["error"]


def test_incremental_native_sync_receives_only_current_batch(tmp_path, monkeypatch):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    projector = IndexProjector(database)
    synchronized: list[list[int]] = []

    def record_sync(rows, **kwargs):
        synchronized.append([int(row["sequence_id"]) for row in rows])
        return {"available": True, "ok": True}

    monkeypatch.setattr(projector, "_sync_qihse", record_sync)
    for message_id in (1, 2):
        outbox.append(
            source_table="messages",
            source_key=str(message_id),
            event_type="upsert",
            payload={"message_id": message_id, "text": f"message {message_id}"},
            source_revision="v1",
        )
        assert projector.process(batch_size=1)["processed"] == 1

    assert synchronized == [[1], [2]]


def test_persistent_keystone_lookup_server_reloads_after_projection_advance(tmp_path):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    projector = IndexProjector(database)
    try:
        outbox.append(
            source_table="channel_messages",
            source_key="-100123:1",
            event_type="download",
            payload={"channel_id": -100123, "message_id": 1, "text": "first"},
            source_revision="v1",
        )
        assert projector.process()["processed"] == 1
        first = projector.lookup(channel_id=-100123, message_id=1)
        assert first["native"]["found"] is True
        first_generation = first["native"]["generation"]

        outbox.append(
            source_table="channel_messages",
            source_key="-100123:2",
            event_type="download",
            payload={"channel_id": -100123, "message_id": 2, "text": "second"},
            source_revision="v1",
        )
        assert projector.process()["processed"] == 1
        second = projector.lookup(channel_id=-100123, message_id=2)

        assert second["found"] is True
        assert second["native"]["found"] is True
        assert second["native"]["generation"] != first_generation
    finally:
        projector.close()


def test_persistent_keystone_lookup_server_reloads_changed_keys_with_same_max_sequence(tmp_path):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    projector = IndexProjector(database)
    original_key = keystone_compound_key(-100123, 1)
    replacement_key = keystone_compound_key(-100123, 2)
    try:
        outbox.append(
            source_table="channel_messages",
            source_key="-100123:1",
            event_type="download",
            payload={"channel_id": -100123, "message_id": 1, "text": "first"},
            source_revision="v1",
        )
        assert projector.process()["processed"] == 1
        first = projector._keystone_lookup(original_key)
        assert first["found"] is True

        with connect_sqlite(database) as connection:
            before = connection.execute(
                """
                SELECT MAX(sequence_id)
                FROM index_projection_records
                WHERE projection_name='keystone.ids.v1'
                """
            ).fetchone()[0]
            connection.execute(
                """
                UPDATE index_projection_records
                SET numeric_key=?
                WHERE projection_name='keystone.ids.v1' AND sequence_id=?
                """,
                (replacement_key, before),
            )
            after = connection.execute(
                """
                SELECT MAX(sequence_id)
                FROM index_projection_records
                WHERE projection_name='keystone.ids.v1'
                """
            ).fetchone()[0]

        second = projector._keystone_lookup(replacement_key)
        old = projector._keystone_lookup(original_key)

        assert before == after == 1
        assert second["found"] is True
        assert old["found"] is False
        assert second["generation"] != first["generation"]
        assert old["generation"] == second["generation"]
    finally:
        projector.close()


def test_keystone_server_startup_timeout_is_bounded(tmp_path, monkeypatch):
    projector = IndexProjector(tmp_path / "spectra.db")
    real_popen = subprocess.Popen

    def sleeping_worker(*_args, **kwargs):
        return real_popen(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            **kwargs,
        )

    monkeypatch.setattr("tgarchive.db.index_projector.subprocess.Popen", sleeping_worker)
    monkeypatch.setattr("tgarchive.db.index_projector._KEYSTONE_START_TIMEOUT_SECONDS", 0.05)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="did not respond"):
            projector._start_keystone_server()
    finally:
        projector.close()
    assert time.monotonic() - started < 2


def test_keystone_lookup_timeout_restarts_once_then_fails(tmp_path, monkeypatch):
    projector = IndexProjector(tmp_path / "spectra.db")
    real_popen = subprocess.Popen
    script = (
        "import sys,time\n"
        "print('SPECTRA_NATIVE_SERVER={\"ok\": true}', flush=True)\n"
        "for line in sys.stdin:\n"
        "    sys.stdout.write('SPECTRA_NATIVE_RESPONSE={')\n"
        "    sys.stdout.flush()\n"
        "    time.sleep(10)\n"
    )

    def stalled_worker(*_args, **kwargs):
        return real_popen([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr("tgarchive.db.index_projector.subprocess.Popen", stalled_worker)
    monkeypatch.setattr("tgarchive.db.index_projector._KEYSTONE_LOOKUP_TIMEOUT_SECONDS", 0.05)
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="failed after restart"):
            projector._keystone_lookup(123)
    finally:
        projector.close()
    assert time.monotonic() - started < 2


def test_typed_keystone_record_projections_support_native_lookup(tmp_path):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    records = [
        (
            "checkpoints",
            "7",
            "save",
            {
                "checkpoint_id": 7,
                "last_message_id": 99,
                "context": "sync",
                "checkpoint_time": "2026-07-29T00:00:00+00:00",
            },
            CHECKPOINT_PROJECTION,
            "checkpoints",
            "checkpoints",
            "7",
        ),
        (
            "task_events",
            "12",
            "completed",
            {
                "event_id": 12,
                "task_id": "task-abc",
                "status": "completed",
                "event_at": "2026-07-29T00:00:00+00:00",
            },
            EVENT_PROJECTION,
            "events",
            "task_events",
            "12",
        ),
        (
            "channel_messages",
            "-100123:42",
            "download",
            {
                "export_id": "export-abc",
                "record_ordinal": 3,
                "channel_id": -100123,
                "message_id": 42,
                "media_manifest": {
                    "manifest_path": "/exports/channel/media_manifest.jsonl",
                    "byte_offset": 10,
                    "byte_length": 20,
                    "record_sha256": "a" * 64,
                },
            },
            EXPORT_RECORD_PROJECTION,
            "exports",
            "export-abc",
            "3",
        ),
        (
            "archive_members",
            "member-abc",
            "index",
            {
                "archive_member": {
                    "member_id": "member-abc",
                    "archive_id": "archive-abc",
                    "member_index": 4,
                    "canonical_member_name": "member.txt",
                    "archive_path": "/exports/archive.zip",
                    "member_name": "member.txt",
                    "header_offset": 100,
                    "data_offset": 130,
                },
            },
            ARCHIVE_MEMBER_PROJECTION,
            "archive-members",
            "archive-abc",
            "4",
        ),
    ]
    for (
        source_table,
        source_key,
        event_type,
        payload,
        _projection,
        _alias,
        _namespace,
        _external_id,
    ) in records:
        assert outbox.append(
            source_table=source_table,
            source_key=source_key,
            event_type=event_type,
            payload=payload,
            source_revision="v1",
        ) is not None

    with IndexProjector(database) as projector:
        assert projector.drain(batch_size=10)["processed"] == len(records)
        for (
            _source_table,
            _source_key,
            _event_type,
            _payload,
            projection,
            alias,
            namespace,
            external_id,
        ) in records:
            result = projector.lookup_record(
                projection=alias,
                namespace=namespace,
                external_id=external_id,
            )
            assert result["projection"] == projection
            assert result["numeric_key"] == keystone_record_key(
                projection,
                namespace,
                external_id,
            )
            assert result["found"] is True
            assert result["native"]["found"] is True

        verified = projector.verify(projection="keystone", native=True, sample_size=8)
        by_name = {item["projection"]: item for item in verified["projections"]}
        assert all(by_name[name]["ok"] for name in (
            CHECKPOINT_PROJECTION,
            EVENT_PROJECTION,
            EXPORT_RECORD_PROJECTION,
            ARCHIVE_MEMBER_PROJECTION,
        ))


def test_save_checkpoint_commits_matching_outbox_event(tmp_path):
    from tgarchive.db import SpectraDB

    database = tmp_path / "spectra.db"
    with SpectraDB(database) as spectra:
        spectra.save_checkpoint(321, context="channel:-100123")

    events = IndexOutbox(database).events()
    checkpoint = next(event for event in events if event["source_table"] == "checkpoints")
    assert checkpoint["source_key"] == str(checkpoint["payload"]["checkpoint_id"])
    assert checkpoint["payload"]["last_message_id"] == 321
    assert checkpoint["payload"]["context"] == "channel:-100123"


def test_raw_event_id_does_not_enter_telegram_message_projection(tmp_path):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    outbox.append(
        source_table="messages",
        source_key="-100123:1",
        event_type="index",
        payload={"channel_id": -100123, "message_id": 1, "content": "message"},
        source_revision="message-v1",
    )
    outbox.append(
        source_table="operation_events",
        source_key="1",
        event_type="progress",
        payload={
            "event_id": 1,
            "operation_id": "operation-1",
            "event": "progress",
            "timestamp": "2026-07-29T00:00:00+00:00",
        },
        source_revision="event-v1",
    )

    with IndexProjector(database) as projector:
        assert projector.drain(batch_size=10)["processed"] == 2
        verified = projector.verify(projection="keystone", native=True)
        by_name = {item["projection"]: item for item in verified["projections"]}

    assert by_name["keystone.ids.v1"]["actual_rows"] == 1
    assert by_name[EVENT_PROJECTION]["actual_rows"] == 1
    assert verified["ok"] is True


def test_atomic_identity_map_rejects_forced_keystone_collision(tmp_path, monkeypatch):
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    for event_id in (1, 2):
        outbox.append(
            source_table="task_events",
            source_key=str(event_id),
            event_type="completed",
            payload={
                "event_id": event_id,
                "task_id": f"task-{event_id}",
                "status": "completed",
                "event_at": f"2026-07-29T00:00:0{event_id}+00:00",
            },
            source_revision="v1",
        )

    monkeypatch.setattr(
        "tgarchive.db.index_projector.keystone_record_key",
        lambda *_args: 123,
    )
    projector = IndexProjector(database)
    try:
        result = projector.process(batch_size=2)
    finally:
        projector.close()

    assert result["processed"] == 1
    assert result["failed"] == 1
    assert "KEYSTONE key collision" in result["failures"][0]["error"]


@pytest.mark.parametrize(
    ("projection", "namespace", "external_id", "expected"),
    [
        (EVENT_PROJECTION, "task_events", "31", 952485041063902881),
        (CHECKPOINT_PROJECTION, "checkpoints", "7", -6695257016984398062),
        (EXPORT_RECORD_PROJECTION, "export-abc", "3", -7172718875542362405),
        (ARCHIVE_MEMBER_PROJECTION, "archive-abc", "4", -2047899453176726458),
    ],
)
def test_keystone_record_key_golden_vectors(
    projection,
    namespace,
    external_id,
    expected,
):
    assert keystone_record_key(projection, namespace, external_id) == expected


def test_native_sync_timeout_is_adaptive_and_respects_lease_budget():
    assert _native_sync_timeout(1) == 60
    assert _native_sync_timeout(1000) == 250
    assert _native_sync_timeout(100_000) == 900
    assert _native_sync_timeout(1000, timeout_limit=120) == 120


def test_two_projector_workers_preserve_monotonic_graph_revision_order(tmp_path):
    context = multiprocessing.get_context("spawn")
    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    first_sequence = outbox.append(
        source_table="messages",
        source_key="10:1",
        event_type="upsert",
        payload={"channel_id": 10, "message_id": 1, "text": "old"},
        source_revision="v1",
    )
    second_sequence = outbox.append(
        source_table="messages",
        source_key="10:1",
        event_type="upsert",
        payload={"channel_id": 10, "message_id": 1, "text": "new"},
        source_revision="v2",
    )
    assert first_sequence is not None and second_sequence is not None

    first_claimed = context.Event()
    release_first = context.Event()
    first_started = context.Event()
    second_started = context.Event()
    second_claimed = context.Event()
    unused_release = context.Event()
    results = context.Queue()
    first = context.Process(
        target=_ordered_projector_worker,
        args=(database,),
        kwargs={
            "pause_after_claim": True,
            "claimed": first_claimed,
            "release": release_first,
            "started": first_started,
            "results": results,
        },
    )
    second = context.Process(
        target=_ordered_projector_worker,
        args=(database,),
        kwargs={
            "pause_after_claim": False,
            "claimed": second_claimed,
            "release": unused_release,
            "started": second_started,
            "results": results,
        },
    )
    first.start()
    try:
        assert first_started.wait(10)
        assert first_claimed.wait(10)
        second.start()
        assert second_started.wait(10)
        assert second_claimed.wait(0.2) is False
        release_first.set()
        assert second_claimed.wait(10)
        worker_results = [results.get(timeout=15) for _ in range(2)]
    finally:
        release_first.set()
        for process in (first, second):
            if process.pid is None:
                continue
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert all(result["ok"] for _pid, result in worker_results)
    assert all(result["processed"] == 1 for _pid, result in worker_results)
    with connect_sqlite(database) as connection:
        edge = connection.execute(
            "SELECT sequence_id, metadata_json FROM index_graph_edges"
        ).fetchone()
    assert int(edge[0]) == second_sequence
    assert json.loads(edge[1])["sequence_id"] == second_sequence
    assert outbox.status()["outbox"]["processed"] == 2


@pytest.mark.parametrize("store_kind", ("qihse", "graph"))
def test_native_store_operations_are_serialized_across_processes(tmp_path, store_kind):
    context = multiprocessing.get_context("spawn")
    database = tmp_path / "spectra.db"
    IndexProjector(database).close()
    ready = context.Queue()
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_native_sync_interval_worker,
            args=(database, store_kind, ready, start, results),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    try:
        assert {ready.get(timeout=10) for _ in processes} == {
            process.pid for process in processes
        }
        start.set()
        messages = [results.get(timeout=10) for _ in range(4)]
    finally:
        start.set()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    assert all(process.exitcode == 0 for process in processes)
    assert [message[2] for message in messages if message[0] == "result"] == [True, True]
    intervals = sorted(
        (message[2], message[3])
        for message in messages
        if message[0] == "interval"
    )
    assert len(intervals) == 2
    assert intervals[1][0] >= intervals[0][1]


def test_native_store_lock_timeout_is_bounded_and_skips_child(tmp_path, monkeypatch):
    context = multiprocessing.get_context("spawn")
    database = tmp_path / "spectra.db"
    projector = IndexProjector(database)
    acquired = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_native_lock_holder,
        args=(projector.qihse_path, acquired, release),
    )
    holder.start()
    assert acquired.wait(10)
    child_called = False

    def unexpected_run(*_args, **_kwargs):
        nonlocal child_called
        child_called = True
        raise AssertionError("native child must not start without the store lock")

    monkeypatch.setattr("tgarchive.db.index_projector.subprocess.run", unexpected_run)
    monkeypatch.setattr(
        "tgarchive.db.index_projector._NATIVE_STORE_LOCK_TIMEOUT_SECONDS",
        0.1,
    )
    started = time.monotonic()
    try:
        result = projector._sync_qihse([], rebuild=True, timeout_limit=1)
    finally:
        release.set()
        holder.join(timeout=10)
        if holder.is_alive():
            holder.terminate()
            holder.join(timeout=5)
        projector.close()

    assert holder.exitcode == 0
    assert result["ok"] is False
    assert "native store lock timed out" in result["error"]
    assert child_called is False
    assert time.monotonic() - started < 1


def test_native_store_lock_is_released_when_owner_process_crashes(tmp_path):
    context = multiprocessing.get_context("spawn")
    store_path = tmp_path / "index.qihse.qdb"
    acquired = context.Event()
    unused_release = context.Event()
    holder = context.Process(
        target=_native_lock_holder,
        args=(store_path, acquired, unused_release),
        kwargs={"crash": True},
    )
    holder.start()
    assert acquired.wait(10)
    holder.join(timeout=10)

    assert holder.exitcode == 23
    with NativeStoreLock(store_path, timeout=1):
        assert True


def test_empty_native_projections_probe_qihse_and_keystone_capabilities(
    tmp_path,
    monkeypatch,
):
    from tgarchive.search import keystone_bindings

    monkeypatch.setattr(keystone_bindings, "keystone_available", lambda: False)
    keystone = IndexProjector.verify_native_in_process(
        CHECKPOINT_PROJECTION,
        [],
        sample_size=2,
    )

    class UnavailableVectorIndex:
        def __init__(self, _path):
            raise RuntimeError("QIHSE capability unavailable")

    monkeypatch.setattr(
        "tgarchive.search.qihse_vector_backend.QihseVectorIndex",
        UnavailableVectorIndex,
    )
    qihse = IndexProjector.verify_native_in_process(
        QIHSE_PROJECTION,
        [],
        sample_size=2,
        qihse_path=tmp_path / "empty.qdb",
    )

    assert keystone["ok"] is False
    assert keystone["available"] is False
    assert qihse["ok"] is False
    assert qihse["available"] is False


def test_empty_graph_projection_probes_native_store(tmp_path, monkeypatch):
    from tgarchive.db import index_projector as projector_module

    projector = IndexProjector(tmp_path / "spectra.db")
    calls = []

    def unavailable_probe(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "graph capability unavailable")

    monkeypatch.setattr(projector_module, "_run_native_command", unavailable_probe)

    result = projector._verify_graph(sample_size=4)

    assert result["ok"] is False
    assert result["available"] is False
    assert result["samples"] == 0
    assert len(calls) == 1
    assert "--node-id" in calls[0]


def test_graph_native_verification_checks_all_samples_and_metadata(
    tmp_path,
    monkeypatch,
):
    from tgarchive.db import index_projector as projector_module

    database = tmp_path / "spectra.db"
    outbox = IndexOutbox(database)
    for message_id in range(1, 4):
        outbox.append(
            source_table="messages",
            source_key=f"10:{message_id}",
            event_type="upsert",
            payload={
                "channel_id": 10,
                "message_id": message_id,
                "text": f"message {message_id}",
            },
            source_revision="v1",
        )
    projector = IndexProjector(database)
    monkeypatch.setattr(
        projector,
        "_sync_qihse",
        lambda _rows, **_kwargs: {"available": True, "ok": True},
    )
    monkeypatch.setattr(
        projector,
        "_sync_graph",
        lambda _rows, **_kwargs: {"available": True, "ok": True},
    )
    assert projector.drain(batch_size=10)["ok"] is True
    calls = []
    corrupt_metadata = False

    def graph_probe(command, **_kwargs):
        nonlocal corrupt_metadata
        calls.append(command)
        node_id = int(command[command.index("--node-id") + 1])
        edge_type = command[command.index("--edge-type") + 1]
        with connect_sqlite(database) as connection:
            rows = connection.execute(
                """
                SELECT from_node_id, to_node_id, edge_type, metadata_json
                FROM index_graph_edges
                WHERE from_node_id=? AND edge_type=?
                ORDER BY to_node_id
                """,
                (node_id, edge_type),
            ).fetchall()
        records = [
            {
                "from_node_id": int(row[0]),
                "to_node_id": int(row[1]),
                "edge_type": str(row[2]),
                "metadata": json.loads(row[3]),
            }
            for row in rows
        ]
        if corrupt_metadata and records:
            records[0]["metadata"]["sequence_id"] = -1
        payload = json.dumps(
            {"available": True, "ok": True, "records": records},
            sort_keys=True,
        )
        return subprocess.CompletedProcess(
            command,
            0,
            f"SPECTRA_NATIVE_PROBE={payload}\n",
            "",
        )

    monkeypatch.setattr(projector_module, "_run_native_command", graph_probe)

    verified = projector._verify_graph(sample_size=3)

    assert verified["ok"] is True
    assert verified["samples"] == 3
    assert len(calls) == 3

    calls.clear()
    corrupt_metadata = True
    corrupted = projector._verify_graph(sample_size=3)

    assert corrupted["ok"] is False
    assert corrupted["available"] is True
    assert corrupted["samples"] >= 1
    assert "metadata mismatch" in corrupted["error"]


def test_qihse_native_verification_accepts_duplicate_vectors_with_exact_identities(
    tmp_path,
    monkeypatch,
):
    rows = [
        {
            "sequence_id": 1,
            "source_table": "messages",
            "source_key": "channel:1",
            "vector_json": "[0.25,0.75]",
        },
        {
            "sequence_id": 2,
            "source_table": "messages",
            "source_key": "channel:2",
            "vector_json": "[0.25,0.75]",
        },
    ]

    class DuplicateAwareIndex:
        library_path = tmp_path / "libqihse.so"

        def __init__(self, _path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            pass

        def search(self, _vector, *, limit):
            return [
                {"id": 1, "score": 1.0},
                {"id": 2, "score": 1.0},
            ][:limit]

    monkeypatch.setattr(
        "tgarchive.search.qihse_vector_backend.QihseVectorIndex",
        DuplicateAwareIndex,
    )

    result = IndexProjector.verify_native_in_process(
        QIHSE_PROJECTION,
        rows,
        sample_size=2,
        qihse_path=tmp_path / "index.qdb",
    )

    assert result["ok"] is True
    assert result["samples"] == 2


def test_qihse_native_verification_rejects_other_equal_vector_identity(
    tmp_path,
    monkeypatch,
):
    rows = [
        {
            "sequence_id": 1,
            "source_table": "messages",
            "source_key": "channel:1",
            "vector_json": "[0.25,0.75]",
        },
        {
            "sequence_id": 2,
            "source_table": "messages",
            "source_key": "channel:2",
            "vector_json": "[0.25,0.75]",
        },
    ]

    class WrongIdentityIndex:
        library_path = tmp_path / "libqihse.so"

        def __init__(self, _path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            pass

        def search(self, _vector, *, limit):
            assert limit == 2
            return [{"id": 1, "score": 1.0}]

    monkeypatch.setattr(
        "tgarchive.search.qihse_vector_backend.QihseVectorIndex",
        WrongIdentityIndex,
    )

    result = IndexProjector.verify_native_in_process(
        QIHSE_PROJECTION,
        rows,
        sample_size=2,
        qihse_path=tmp_path / "index.qdb",
    )

    assert result["ok"] is False
    assert result["available"] is True
    assert result["samples"] == 2
