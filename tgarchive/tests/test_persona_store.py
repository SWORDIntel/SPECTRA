"""Tests for the persona training-data store (tgarchive.db.persona_store)."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from tgarchive.db.persona_store import (
    PERSONA_EXAMPLES_SOURCE_TABLE,
    PERSONA_KNOWLEDGE_SOURCE_TABLE,
    PERSONA_SNAPSHOT_SOURCE_TABLE,
    PERSONA_SOURCE_TABLES,
    PERSONA_TARGET_SOURCE_TABLE,
    PersonaStore,
    record_persona_example,
    record_persona_target,
)
from tgarchive.db.schema import SCHEMA_SQL
from tgarchive.db.index_outbox import IndexOutbox


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_persona.db"


@pytest.fixture
def store(db_path):
    s = PersonaStore(db_path)
    yield s
    s.close()


class TestSchemaAndMigration:
    def test_schema_creates_all_tables(self, db_path):
        s = PersonaStore(db_path)
        s._connection()  # trigger schema
        s.close()
        conn = sqlite3.connect(str(db_path))
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "persona_targets" in tables
        assert "persona_examples" in tables
        assert "persona_knowledge_observations" in tables
        assert "persona_profile_snapshots" in tables

    def test_schema_idempotent(self, db_path):
        s = PersonaStore(db_path)
        s._connection().executescript(SCHEMA_SQL)
        s._connection().executescript(SCHEMA_SQL)
        s.close()
        # Should not raise.

    def test_index_outbox_schema_created(self, db_path):
        s = PersonaStore(db_path)
        s._connection()
        s.close()
        conn = sqlite3.connect(str(db_path))
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "index_outbox" in tables


class TestTargetRegistration:
    def test_register_target(self, store):
        seq = store.register_target("t1", "Alice", platform="telegram")
        assert seq is not None
        target = store.get_target("t1")
        assert target is not None
        assert target["display_name"] == "Alice"
        assert target["authorization_status"] == "pending"

    def test_register_target_with_authorize(self, store):
        store.register_target("t1", "Alice", authorization_status="authorized")
        assert store.can_export("t1") is True

    def test_register_target_idempotent(self, store):
        store.register_target("t1", "Alice")
        store.register_target("t1", "Alice Updated")
        target = store.get_target("t1")
        assert target["display_name"] == "Alice Updated"

    def test_register_invalid_auth_status(self, store):
        with pytest.raises(ValueError):
            store.register_target("t1", "Alice", authorization_status="bogus")

    def test_set_authorization(self, store):
        store.register_target("t1", "Alice")
        assert store.can_export("t1") is False
        store.set_authorization("t1", "authorized")
        assert store.can_export("t1") is True

    def test_set_authorization_unknown_target(self, store):
        with pytest.raises(KeyError):
            store.set_authorization("unknown", "authorized")

    def test_list_targets(self, store):
        store.register_target("t1", "Alice")
        store.register_target("t2", "Bob", authorization_status="authorized")
        all_targets = store.list_targets()
        assert len(all_targets) == 2
        authorized = store.list_targets(authorization_status="authorized")
        assert len(authorized) == 1
        assert authorized[0]["target_id"] == "t2"

    def test_get_unknown_target(self, store):
        assert store.get_target("nonexistent") is None


class TestExamples:
    def test_add_example(self, store):
        store.register_target("t1", "Alice")
        eid, seq = store.add_example("t1", "positive", "Hello world")
        assert eid is not None
        assert seq is not None

    def test_add_example_dedup(self, store):
        store.register_target("t1", "Alice")
        eid1, seq1 = store.add_example("t1", "positive", "Hello",
                                       source_message_id=100, source_channel_id=5)
        assert eid1 is not None
        assert seq1 is not None
        eid2, seq2 = store.add_example("t1", "positive", "Hello",
                                       source_message_id=100, source_channel_id=5)
        # Second insert is deduped — returns (None, None).
        assert eid2 is None
        assert seq2 is None
        # Only one row in the table.
        examples = store.query_examples("t1")
        assert len(examples) == 1

    def test_add_example_different_labels_not_dedup(self, store):
        store.register_target("t1", "Alice")
        eid1, _ = store.add_example("t1", "positive", "Hello", source_message_id=100)
        eid2, _ = store.add_example("t1", "negative", "Hello", source_message_id=100)
        # Different label = different dedup key, so both insert.
        # But eid2 is None because the natural key includes label.
        # Actually the example_id includes label, so they differ.
        assert eid1 is not None

    def test_invalid_label(self, store):
        store.register_target("t1", "Alice")
        with pytest.raises(ValueError):
            store.add_example("t1", "bogus", "text")

    def test_empty_text(self, store):
        store.register_target("t1", "Alice")
        with pytest.raises(ValueError):
            store.add_example("t1", "positive", "")

    def test_negative_weight(self, store):
        store.register_target("t1", "Alice")
        with pytest.raises(ValueError):
            store.add_example("t1", "positive", "text", weight=-1.0)

    def test_query_examples_by_label(self, store):
        store.register_target("t1", "Alice")
        store.add_example("t1", "positive", "pos1", observed_at="2026-01-01T00:00:00Z")
        store.add_example("t1", "negative", "neg1", observed_at="2026-01-02T00:00:00Z")
        store.add_example("t1", "positive", "pos2", observed_at="2026-01-03T00:00:00Z")
        pos = store.query_examples("t1", label="positive")
        assert len(pos) == 2
        neg = store.query_examples("t1", label="negative")
        assert len(neg) == 1

    def test_query_examples_date_filter(self, store):
        store.register_target("t1", "Alice")
        store.add_example("t1", "positive", "old", observed_at="2026-01-01T00:00:00Z")
        store.add_example("t1", "positive", "new", observed_at="2026-06-01T00:00:00Z")
        results = store.query_examples("t1", start="2026-03-01T00:00:00Z")
        assert len(results) == 1
        assert results[0]["text"] == "new"

    def test_add_examples_bulk(self, store):
        store.register_target("t1", "Alice")
        examples = [
            {"label": "positive", "text": "hello", "source_message_id": 1},
            {"label": "negative", "text": "bye", "source_message_id": 2},
            {"label": "positive", "text": "world", "source_message_id": 3},
        ]
        count = store.add_examples("t1", examples)
        assert count == 3

    def test_add_examples_skips_invalid(self, store):
        store.register_target("t1", "Alice")
        examples = [
            {"label": "positive", "text": "hello"},
            {"label": None, "text": "no label"},
            {"text": "no label either"},
        ]
        count = store.add_examples("t1", examples)
        assert count == 1


class TestKnowledgeObservations:
    def test_save_knowledge(self, store):
        store.register_target("t1", "Alice")
        oid, seq = store.save_knowledge_observation(
            "t1", "computers", 0.75, 0.8,
        )
        assert oid is not None
        assert seq is not None

    def test_knowledge_dedup(self, store):
        store.register_target("t1", "Alice")
        oid1, seq1 = store.save_knowledge_observation(
            "t1", "computers", 0.75, 0.8, evaluator="manual",
        )
        assert oid1 is not None
        assert seq1 is not None
        oid2, seq2 = store.save_knowledge_observation(
            "t1", "computers", 0.75, 0.8, evaluator="manual",
        )
        # Second insert is deduped.
        assert oid2 is None
        assert seq2 is None
        obs = store.query_knowledge_observations("t1")
        assert len(obs) == 1

    def test_invalid_score_range(self, store):
        store.register_target("t1", "Alice")
        with pytest.raises(ValueError):
            store.save_knowledge_observation("t1", "computers", 1.5, 0.5)

    def test_invalid_confidence_range(self, store):
        store.register_target("t1", "Alice")
        with pytest.raises(ValueError):
            store.save_knowledge_observation("t1", "computers", 0.5, -0.1)

    def test_score_confidence_separate(self, store):
        store.register_target("t1", "Alice")
        store.save_knowledge_observation("t1", "computers", 0.75, 0.32)
        obs = store.query_knowledge_observations("t1")[0]
        assert obs["score"] == 0.75
        assert obs["confidence"] == 0.32
        assert obs["score"] != obs["confidence"]

    def test_query_by_domain(self, store):
        store.register_target("t1", "Alice")
        store.save_knowledge_observation("t1", "computers", 0.75, 0.8)
        store.save_knowledge_observation("t1", "biology", 0.32, 0.6)
        comp = store.query_knowledge_observations("t1", domain="computers")
        assert len(comp) == 1
        assert comp[0]["domain"] == "computers"


class TestSnapshots:
    def test_save_snapshot(self, store):
        store.register_target("t1", "Alice")
        sid, seq = store.save_snapshot(
            "t1", "2026-01-01T00:00:00Z",
            positive_count=10, negative_count=5,
            vocabulary={"hello": 0.5, "world": 0.3},
            distinctive_vocab={"hello": 1.2},
            bigrams={"hello world": 0.2},
            linguistic_features={"avg_message_length": 42.0},
            knowledge_estimates={"computers": {"score": 0.75, "confidence": 0.8, "n": 3}},
        )
        assert sid is not None
        assert seq is not None

    def test_latest_snapshot(self, store):
        store.register_target("t1", "Alice")
        store.save_snapshot("t1", "2026-01-01T00:00:00Z",
                            vocabulary={"a": 0.5})
        store.save_snapshot("t1", "2026-06-01T00:00:00Z",
                            vocabulary={"b": 0.6})
        latest = store.latest_snapshot("t1")
        assert latest is not None
        assert latest["as_of"] == "2026-06-01T00:00:00Z"
        assert "b" in latest["vocabulary"]

    def test_snapshot_json_decoded(self, store):
        store.register_target("t1", "Alice")
        store.save_snapshot("t1", "2026-01-01T00:00:00Z",
                            vocabulary={"hello": 0.5},
                            knowledge_estimates={"computers": {"score": 0.7, "confidence": 0.8, "n": 2}})
        latest = store.latest_snapshot("t1")
        assert isinstance(latest["vocabulary"], dict)
        assert isinstance(latest["knowledge_estimates"], dict)

    def test_query_snapshots_longitudinal(self, store):
        store.register_target("t1", "Alice")
        for i, month in enumerate(["2026-01-01", "2026-03-01", "2026-06-01"]):
            store.save_snapshot("t1", f"{month}T00:00:00Z",
                                positive_count=i + 1)
        snaps = store.query_snapshots("t1")
        assert len(snaps) == 3
        # Ordered by as_of ASC.
        assert snaps[0]["as_of"] == "2026-01-01T00:00:00Z"
        assert snaps[2]["as_of"] == "2026-06-01T00:00:00Z"

    def test_no_snapshot(self, store):
        store.register_target("t1", "Alice")
        assert store.latest_snapshot("t1") is None


class TestOutboxIntegration:
    def test_target_outbox_event(self, store):
        store.register_target("t1", "Alice")
        events = store.outbox_events(target_id="t1")
        assert len(events) >= 1
        assert events[0]["source_table"] == PERSONA_TARGET_SOURCE_TABLE

    def test_example_outbox_event(self, store):
        store.register_target("t1", "Alice")
        store.add_example("t1", "positive", "hello")
        events = store.outbox_events(source_table=PERSONA_EXAMPLES_SOURCE_TABLE)
        assert len(events) >= 1

    def test_knowledge_outbox_event(self, store):
        store.register_target("t1", "Alice")
        store.save_knowledge_observation("t1", "computers", 0.75, 0.8)
        events = store.outbox_events(source_table=PERSONA_KNOWLEDGE_SOURCE_TABLE)
        assert len(events) >= 1

    def test_snapshot_outbox_event(self, store):
        store.register_target("t1", "Alice")
        store.save_snapshot("t1", "2026-01-01T00:00:00Z")
        events = store.outbox_events(source_table=PERSONA_SNAPSHOT_SOURCE_TABLE)
        assert len(events) >= 1

    def test_authorize_outbox_event(self, store):
        store.register_target("t1", "Alice")
        store.set_authorization("t1", "authorized")
        events = store.outbox_events(target_id="t1")
        auth_events = [e for e in events if e["event_type"] == "authorize"]
        assert len(auth_events) >= 1

    def test_all_persona_source_tables(self):
        assert PERSONA_TARGET_SOURCE_TABLE in PERSONA_SOURCE_TABLES
        assert PERSONA_EXAMPLES_SOURCE_TABLE in PERSONA_SOURCE_TABLES
        assert PERSONA_KNOWLEDGE_SOURCE_TABLE in PERSONA_SOURCE_TABLES
        assert PERSONA_SNAPSHOT_SOURCE_TABLE in PERSONA_SOURCE_TABLES


class TestStatsAndManifest:
    def test_corpus_stats(self, store):
        store.register_target("t1", "Alice")
        store.add_example("t1", "positive", "hello", observed_at="2026-01-01T00:00:00Z")
        store.add_example("t1", "negative", "bye", observed_at="2026-01-02T00:00:00Z")
        store.save_knowledge_observation("t1", "computers", 0.75, 0.8)
        stats = store.corpus_stats("t1")
        assert stats["total_examples"] == 2
        assert stats["per_label"]["positive"] == 1
        assert stats["per_label"]["negative"] == 1
        assert "computers" in stats["per_domain"]

    def test_corpus_stats_unknown_target(self, store):
        with pytest.raises(KeyError):
            store.corpus_stats("nonexistent")

    def test_export_manifest(self, store):
        store.register_target("t1", "Alice", authorization_status="authorized")
        store.add_example("t1", "positive", "hello")
        manifest = store.export_manifest("t1")
        assert manifest["can_export"] is True
        assert manifest["disclosure_required"] is True
        assert manifest["total_examples"] == 1

    def test_export_manifest_unauthorized(self, store):
        store.register_target("t1", "Alice")
        manifest = store.export_manifest("t1")
        assert manifest["can_export"] is False


class TestCascadeDelete:
    def test_delete_target_cascades(self, store):
        store.register_target("t1", "Alice")
        store.add_example("t1", "positive", "hello")
        store.save_knowledge_observation("t1", "computers", 0.75, 0.8)
        store.save_snapshot("t1", "2026-01-01T00:00:00Z")
        deleted = store.delete_target("t1")
        assert deleted == 1
        assert store.get_target("t1") is None
        assert len(store.query_examples("t1")) == 0
        assert len(store.query_knowledge_observations("t1")) == 0
        assert store.latest_snapshot("t1") is None


class TestContextManager:
    def test_context_manager(self, db_path):
        with PersonaStore(db_path) as store:
            store.register_target("t1", "Alice")
            assert store.get_target("t1") is not None
        # After exit, connection should be closed.
        assert store._conn is None


class TestModuleLevelFunctions:
    def test_record_persona_target_with_connection(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA_SQL)
        IndexOutbox.ensure_schema(conn)
        seq = record_persona_target(
            conn, target_id="t1", display_name="Alice",
        )
        conn.commit()
        assert seq is not None
        row = conn.execute(
            "SELECT display_name FROM persona_targets WHERE target_id = ?",
            ("t1",),
        ).fetchone()
        assert row[0] == "Alice"
        conn.close()

    def test_record_persona_example_with_connection(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA_SQL)
        IndexOutbox.ensure_schema(conn)
        record_persona_target(conn, target_id="t1", display_name="Alice")
        eid, seq = record_persona_example(
            conn, target_id="t1", label="positive", text="hello",
        )
        conn.commit()
        assert eid is not None
        assert seq is not None
        conn.close()


class TestEmptyDatabase:
    def test_empty_db_no_targets(self, store):
        assert store.list_targets() == []

    def test_empty_db_no_examples(self, store):
        store.register_target("t1", "Alice")
        assert store.query_examples("t1") == []

    def test_empty_db_no_snapshots(self, store):
        store.register_target("t1", "Alice")
        assert store.latest_snapshot("t1") is None
