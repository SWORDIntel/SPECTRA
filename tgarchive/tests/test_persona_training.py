"""Tests for the persona training-data model (tgarchive.intelligence.persona_training)."""

import json
import sqlite3
from pathlib import Path

import pytest

from tgarchive.intelligence.persona_training import (
    DEFAULT_DOMAIN_LEXICONS,
    PersonaTrainingModel,
)
from tgarchive.db.persona_store import PersonaStore


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_ptm.db"


@pytest.fixture
def store(db_path):
    s = PersonaStore(db_path)
    yield s
    s.close()


class TestBuildExample:
    def test_build_positive_example(self):
        ex = PersonaTrainingModel.build_example("t1", "positive", "hello world")
        assert ex["label"] == "positive"
        assert ex["text"] == "hello world"
        assert ex["weight"] == 1.0

    def test_build_negative_example(self):
        ex = PersonaTrainingModel.build_example("t1", "negative", "bye")
        assert ex["label"] == "negative"

    def test_build_review_example(self):
        ex = PersonaTrainingModel.build_example("t1", "review", "maybe")
        assert ex["label"] == "review"

    def test_invalid_label(self):
        with pytest.raises(ValueError):
            PersonaTrainingModel.build_example("t1", "bogus", "text")

    def test_empty_text(self):
        with pytest.raises(ValueError):
            PersonaTrainingModel.build_example("t1", "positive", "")

    def test_negative_weight(self):
        with pytest.raises(ValueError):
            PersonaTrainingModel.build_example("t1", "positive", "text", weight=-1)

    def test_deterministic_fields(self):
        ex = PersonaTrainingModel.build_example(
            "t1", "positive", "hello",
            source_message_id=42, source_channel_id=7,
            observed_at="2026-01-01T00:00:00Z",
        )
        assert ex["source_message_id"] == 42
        assert ex["source_channel_id"] == 7
        assert ex["observed_at"] == "2026-01-01T00:00:00Z"


class TestBuildKnowledgeObservation:
    def test_build_observation(self):
        obs = PersonaTrainingModel.build_knowledge_observation(
            "t1", "computers", 0.75, 0.32,
        )
        assert obs["domain"] == "computers"
        assert obs["score"] == 0.75
        assert obs["confidence"] == 0.32
        assert obs["score"] != obs["confidence"]

    def test_invalid_score(self):
        with pytest.raises(ValueError):
            PersonaTrainingModel.build_knowledge_observation("t1", "comp", 1.5, 0.5)

    def test_invalid_confidence(self):
        with pytest.raises(ValueError):
            PersonaTrainingModel.build_knowledge_observation("t1", "comp", 0.5, -0.1)

    def test_empty_domain(self):
        with pytest.raises(ValueError):
            PersonaTrainingModel.build_knowledge_observation("t1", "", 0.5, 0.5)


class TestEstimateKnowledge:
    def test_single_observation(self):
        obs = [{"domain": "computers", "score": 0.75, "confidence": 0.8}]
        est = PersonaTrainingModel.estimate_knowledge(obs)
        assert "computers" in est
        assert est["computers"]["score"] == 0.75
        assert est["computers"]["n"] == 1

    def test_confidence_weighted_mean(self):
        obs = [
            {"domain": "computers", "score": 0.9, "confidence": 0.9},
            {"domain": "computers", "score": 0.1, "confidence": 0.1},
        ]
        est = PersonaTrainingModel.estimate_knowledge(obs)
        # Weighted toward 0.9 since it has higher confidence.
        assert est["computers"]["score"] > 0.5

    def test_confidence_rises_with_n(self):
        single = [{"domain": "d", "score": 0.5, "confidence": 0.5}]
        many = [{"domain": "d", "score": 0.5, "confidence": 0.5} for _ in range(20)]
        est_single = PersonaTrainingModel.estimate_knowledge(single)
        est_many = PersonaTrainingModel.estimate_knowledge(many)
        assert est_many["d"]["confidence"] > est_single["d"]["confidence"]

    def test_contradictory_evidence_lowers_confidence(self):
        consistent = [{"domain": "d", "score": 0.5, "confidence": 0.5} for _ in range(10)]
        contradictory = [{"domain": "d", "score": s, "confidence": 0.5}
                         for s in [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0]]
        est_cons = PersonaTrainingModel.estimate_knowledge(consistent)
        est_cont = PersonaTrainingModel.estimate_knowledge(contradictory)
        assert est_cont["d"]["confidence"] < est_cons["d"]["confidence"]

    def test_confidence_bounded(self):
        obs = [{"domain": "d", "score": 0.5, "confidence": 1.0} for _ in range(100)]
        est = PersonaTrainingModel.estimate_knowledge(obs)
        assert 0.0 <= est["d"]["confidence"] <= 1.0

    def test_multiple_domains(self):
        obs = [
            {"domain": "computers", "score": 0.75, "confidence": 0.8},
            {"domain": "biology", "score": 0.32, "confidence": 0.6},
        ]
        est = PersonaTrainingModel.estimate_knowledge(obs)
        assert "computers" in est
        assert "biology" in est

    def test_empty_observations(self):
        est = PersonaTrainingModel.estimate_knowledge([])
        assert est == {}


class TestBuildSnapshot:
    def _make_examples(self):
        return [
            {"label": "positive", "text": "hello world from the server",
             "observed_at": "2026-01-01T00:00:00Z"},
            {"label": "positive", "text": "hello again from the server",
             "observed_at": "2026-01-02T00:00:00Z"},
            {"label": "negative", "text": "goodbye from the client",
             "observed_at": "2026-01-01T00:00:00Z"},
        ]

    def test_snapshot_counts(self):
        snap = PersonaTrainingModel.build_snapshot(
            "t1", self._make_examples(), [], as_of="2026-12-01T00:00:00Z",
        )
        assert snap["positive_count"] == 2
        assert snap["negative_count"] == 1
        assert snap["review_count"] == 0

    def test_temporal_cutoff(self):
        examples = self._make_examples() + [
            {"label": "positive", "text": "future message",
             "observed_at": "2026-12-01T00:00:00Z"},
        ]
        snap = PersonaTrainingModel.build_snapshot(
            "t1", examples, [], as_of="2026-06-01T00:00:00Z",
        )
        # Future example should be excluded.
        assert snap["positive_count"] == 2

    def test_vocabulary_from_positives(self):
        snap = PersonaTrainingModel.build_snapshot(
            "t1", self._make_examples(), [], as_of="2026-12-01T00:00:00Z",
        )
        assert "hello" in snap["vocabulary"]
        assert "server" in snap["vocabulary"]

    def test_distinctive_vocab(self):
        snap = PersonaTrainingModel.build_snapshot(
            "t1", self._make_examples(), [], as_of="2026-12-01T00:00:00Z",
        )
        # "hello" appears in positives but not negatives → high log-odds.
        assert "hello" in snap["distinctive_vocab"]
        assert snap["distinctive_vocab"]["hello"] > 0

    def test_bigrams(self):
        snap = PersonaTrainingModel.build_snapshot(
            "t1", self._make_examples(), [], as_of="2026-12-01T00:00:00Z",
        )
        assert isinstance(snap["bigrams"], dict)

    def test_linguistic_features(self):
        snap = PersonaTrainingModel.build_snapshot(
            "t1", self._make_examples(), [], as_of="2026-12-01T00:00:00Z",
        )
        assert "avg_message_length" in snap["linguistic_features"]
        assert "lexical_richness_ttr" in snap["linguistic_features"]

    def test_knowledge_estimates_in_snapshot(self):
        obs = [{"domain": "computers", "score": 0.75, "confidence": 0.8}]
        snap = PersonaTrainingModel.build_snapshot(
            "t1", self._make_examples(), obs, as_of="2026-12-01T00:00:00Z",
        )
        assert "computers" in snap["knowledge_estimates"]

    def test_empty_examples(self):
        snap = PersonaTrainingModel.build_snapshot("t1", [], [], as_of="2026-01-01T00:00:00Z")
        assert snap["positive_count"] == 0
        assert snap["vocabulary"] == {}

    def test_review_not_treated_as_positive(self):
        examples = [
            {"label": "review", "text": "uncertain text", "observed_at": "2026-01-01T00:00:00Z"},
            {"label": "positive", "text": "definite text", "observed_at": "2026-01-01T00:00:00Z"},
        ]
        snap = PersonaTrainingModel.build_snapshot(
            "t1", examples, [], as_of="2026-12-01T00:00:00Z",
        )
        assert snap["positive_count"] == 1
        assert snap["review_count"] == 1
        # "uncertain" should not appear in vocabulary (from positives only).
        assert "uncertain" not in snap["vocabulary"]

    def test_model_name(self):
        snap = PersonaTrainingModel.build_snapshot("t1", [], [], as_of="2026-01-01T00:00:00Z")
        assert snap["model"] == "persona-v2"
        assert snap["model_version"] == "2.0"


class TestCollectFromDatabase:
    def _setup_db(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                type TEXT NOT NULL,
                date TEXT NOT NULL,
                content TEXT,
                user_id INTEGER
            );
        """)
        # Target user messages (positives).
        conn.execute("INSERT INTO messages (id, type, date, content, user_id) VALUES (1, 'text', '2026-01-01T00:00:00Z', 'hello world', 100)")
        conn.execute("INSERT INTO messages (id, type, date, content, user_id) VALUES (2, 'text', '2026-01-02T00:00:00Z', 'server code', 100)")
        conn.execute("INSERT INTO messages (id, type, date, content, user_id) VALUES (3, 'text', '2026-01-03T00:00:00Z', '', 100)")  # empty
        # Other user messages (negatives).
        conn.execute("INSERT INTO messages (id, type, date, content, user_id) VALUES (4, 'text', '2026-01-01T00:00:00Z', 'goodbye', 200)")
        conn.execute("INSERT INTO messages (id, type, date, content, user_id) VALUES (5, 'text', '2026-01-02T00:00:00Z', 'client side', 200)")
        conn.execute("INSERT INTO messages (id, type, date, content, user_id) VALUES (6, 'text', '2026-01-03T00:00:00Z', 'another', 300)")
        conn.commit()
        conn.close()

    def test_collect_positives(self, db_path):
        self._setup_db(db_path)
        examples = PersonaTrainingModel.collect_from_database(db_path, 100, limit=100)
        positives = [e for e in examples if e["label"] == "positive"]
        assert len(positives) == 2  # empty message excluded
        assert all(e["source_user_id"] == 100 for e in positives)

    def test_collect_negatives(self, db_path):
        self._setup_db(db_path)
        examples = PersonaTrainingModel.collect_from_database(db_path, 100, limit=100)
        negatives = [e for e in examples if e["label"] == "negative"]
        assert len(negatives) > 0
        assert all(e["source_user_id"] != 100 for e in negatives)

    def test_deterministic_collection(self, db_path):
        self._setup_db(db_path)
        ex1 = PersonaTrainingModel.collect_from_database(db_path, 100, seed=42)
        ex2 = PersonaTrainingModel.collect_from_database(db_path, 100, seed=42)
        assert len(ex1) == len(ex2)
        for a, b in zip(ex1, ex2):
            assert a["text"] == b["text"]
            assert a["label"] == b["label"]

    def test_date_filter(self, db_path):
        self._setup_db(db_path)
        examples = PersonaTrainingModel.collect_from_database(
            db_path, 100, start="2026-01-02T00:00:00Z", limit=100,
        )
        positives = [e for e in examples if e["label"] == "positive"]
        assert all(e["observed_at"] >= "2026-01-02T00:00:00Z" for e in positives)

    def test_negative_ratio(self, db_path):
        self._setup_db(db_path)
        ex1 = PersonaTrainingModel.collect_from_database(db_path, 100, negative_ratio=0.5)
        ex2 = PersonaTrainingModel.collect_from_database(db_path, 100, negative_ratio=2.0)
        neg1 = [e for e in ex1 if e["label"] == "negative"]
        neg2 = [e for e in ex2 if e["label"] == "negative"]
        assert len(neg2) >= len(neg1)

    def test_no_negatives_available(self, tmp_path):
        db_path = tmp_path / "no_neg.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE messages (id INTEGER PRIMARY KEY, type TEXT, date TEXT, content TEXT, user_id INTEGER);
            INSERT INTO messages VALUES (1, 'text', '2026-01-01', 'only target', 100);
        """)
        conn.commit()
        conn.close()
        examples = PersonaTrainingModel.collect_from_database(db_path, 100)
        positives = [e for e in examples if e["label"] == "positive"]
        negatives = [e for e in examples if e["label"] == "negative"]
        assert len(positives) == 1
        assert len(negatives) == 0

    def test_empty_database(self, tmp_path):
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE messages (id INTEGER PRIMARY KEY, type TEXT, date TEXT, content TEXT, user_id INTEGER);
        """)
        conn.commit()
        conn.close()
        examples = PersonaTrainingModel.collect_from_database(db_path, 100)
        assert examples == []

    def test_no_content_column(self, tmp_path):
        db_path = tmp_path / "nocontent.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE messages (id INTEGER PRIMARY KEY, type TEXT, date TEXT, user_id INTEGER);
        """)
        conn.commit()
        conn.close()
        examples = PersonaTrainingModel.collect_from_database(db_path, 100)
        assert examples == []


class TestInferKnowledge:
    def test_infer_computers(self):
        examples = [
            {"text": "I love python and docker and git and ssh"},
            {"text": "the server runs linux with a compiled kernel"},
        ]
        obs = PersonaTrainingModel.infer_knowledge_observations("t1", examples)
        domains = {o["domain"] for o in obs}
        assert "computers" in domains

    def test_infer_biology(self):
        examples = [{"text": "the cell membrane and dna replication"}]
        obs = PersonaTrainingModel.infer_knowledge_observations("t1", examples)
        domains = {o["domain"] for o in obs}
        assert "biology" in domains

    def test_no_evidence_no_claim(self):
        examples = [{"text": "hello world how are you today"}]
        obs = PersonaTrainingModel.infer_knowledge_observations("t1", examples)
        # No domain terms → no observations.
        assert len(obs) == 0

    def test_score_in_range(self):
        examples = [{"text": "python docker git server linux kernel code"}]
        obs = PersonaTrainingModel.infer_knowledge_observations("t1", examples)
        for o in obs:
            assert 0.0 <= o["score"] <= 1.0
            assert 0.0 <= o["confidence"] <= 1.0

    def test_confidence_rises_with_hits(self):
        few = [{"text": "python"}]
        many = [{"text": "python docker git server linux kernel code ssh regex"}]
        obs_few = PersonaTrainingModel.infer_knowledge_observations("t1", few)
        obs_many = PersonaTrainingModel.infer_knowledge_observations("t1", many)
        comp_few = [o for o in obs_few if o["domain"] == "computers"]
        comp_many = [o for o in obs_many if o["domain"] == "computers"]
        if comp_few and comp_many:
            assert comp_many[0]["confidence"] >= comp_few[0]["confidence"]

    def test_custom_lexicons(self):
        custom = {"custom_domain": frozenset({"widget", "gadget"})}
        examples = [{"text": "I love the widget and gadget"}]
        obs = PersonaTrainingModel.infer_knowledge_observations(
            "t1", examples, domain_lexicons=custom,
        )
        domains = {o["domain"] for o in obs}
        assert "custom_domain" in domains
        assert "computers" not in domains

    def test_empty_examples(self):
        obs = PersonaTrainingModel.infer_knowledge_observations("t1", [])
        assert obs == []

    def test_default_lexicons_present(self):
        assert "computers" in DEFAULT_DOMAIN_LEXICONS
        assert "biology" in DEFAULT_DOMAIN_LEXICONS
        assert "finance" in DEFAULT_DOMAIN_LEXICONS
        assert "security" in DEFAULT_DOMAIN_LEXICONS
        assert "medicine" in DEFAULT_DOMAIN_LEXICONS


class TestExportJsonl:
    def test_export_refused_unauthorized(self, tmp_path):
        examples = [{"label": "positive", "text": "hello", "target_id": "t1"}]
        snapshot = PersonaTrainingModel.build_snapshot("t1", examples, [])
        with pytest.raises(PermissionError):
            PersonaTrainingModel.export_jsonl(
                examples, snapshot, tmp_path / "out.jsonl",
                require_authorized=True, authorized=False,
            )

    def test_export_authorized(self, tmp_path):
        examples = [{"label": "positive", "text": "hello", "target_id": "t1",
                     "observed_at": "2026-01-01T00:00:00Z"}]
        snapshot = PersonaTrainingModel.build_snapshot("t1", examples, [])
        out = tmp_path / "out.jsonl"
        count = PersonaTrainingModel.export_jsonl(
            examples, snapshot, out, require_authorized=True, authorized=True,
        )
        assert count == 1
        assert out.exists()

    def test_export_force(self, tmp_path):
        examples = [{"label": "negative", "text": "bye", "target_id": "t1"}]
        snapshot = PersonaTrainingModel.build_snapshot("t1", examples, [])
        out = tmp_path / "out.jsonl"
        count = PersonaTrainingModel.export_jsonl(
            examples, snapshot, out, require_authorized=False, authorized=False,
        )
        assert count == 1

    def test_jsonl_format(self, tmp_path):
        examples = [
            {"label": "positive", "text": "hello", "target_id": "t1",
             "observed_at": "2026-01-01T00:00:00Z", "source_message_id": 1},
            {"label": "negative", "text": "bye", "target_id": "t1",
             "observed_at": "2026-01-02T00:00:00Z", "source_message_id": 2},
        ]
        snapshot = PersonaTrainingModel.build_snapshot("t1", examples, [])
        out = tmp_path / "out.jsonl"
        count = PersonaTrainingModel.export_jsonl(
            examples, snapshot, out, require_authorized=False,
        )
        assert count == 2
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            record = json.loads(line)
            assert "label" in record
            assert "text" in record
            assert "target_id" in record
            assert "persona_snapshot_id" in record
            assert record["disclosure_required"] is True

    def test_deterministic_order(self, tmp_path):
        examples = [
            {"label": "negative", "text": "z", "target_id": "t1",
             "observed_at": "2026-02-01T00:00:00Z"},
            {"label": "positive", "text": "a", "target_id": "t1",
             "observed_at": "2026-01-01T00:00:00Z"},
            {"label": "positive", "text": "b", "target_id": "t1",
             "observed_at": "2026-01-02T00:00:00Z"},
        ]
        snapshot = PersonaTrainingModel.build_snapshot("t1", examples, [])
        out = tmp_path / "out.jsonl"
        PersonaTrainingModel.export_jsonl(examples, snapshot, out, require_authorized=False)
        lines = out.read_text().strip().split("\n")
        records = [json.loads(l) for l in lines]
        # Sorted by observed_at then label.
        assert records[0]["text"] == "a"
        assert records[1]["text"] == "b"
        assert records[2]["text"] == "z"

    def test_empty_export(self, tmp_path):
        snapshot = PersonaTrainingModel.build_snapshot("t1", [], [])
        out = tmp_path / "out.jsonl"
        count = PersonaTrainingModel.export_jsonl(
            [], snapshot, out, require_authorized=False,
        )
        assert count == 0
        assert out.read_text().strip() == ""


class TestSummary:
    def test_summary(self):
        examples = [
            {"label": "positive", "text": "hello"},
            {"label": "negative", "text": "bye"},
            {"label": "review", "text": "maybe"},
        ]
        snapshot = PersonaTrainingModel.build_snapshot("t1", examples, [])
        summary = PersonaTrainingModel.summary(examples, snapshot)
        assert summary["total_examples"] == 3
        assert summary["label_counts"]["positive"] == 1
        assert summary["label_counts"]["negative"] == 1
        assert summary["label_counts"]["review"] == 1

    def test_summary_empty(self):
        snapshot = PersonaTrainingModel.build_snapshot("t1", [], [])
        summary = PersonaTrainingModel.summary([], snapshot)
        assert summary["total_examples"] == 0
        assert summary["vocabulary_size"] == 0


class TestIntegrationWithStore:
    def test_full_pipeline(self, store):
        # Register target.
        store.register_target("t1", "Alice", authorization_status="authorized")
        assert store.can_export("t1")

        # Add examples.
        store.add_example("t1", "positive", "hello from the server",
                          observed_at="2026-01-01T00:00:00Z")
        store.add_example("t1", "positive", "code compile run",
                          observed_at="2026-01-02T00:00:00Z")
        store.add_example("t1", "negative", "goodbye from the client",
                          observed_at="2026-01-01T00:00:00Z")

        # Record knowledge.
        store.save_knowledge_observation("t1", "computers", 0.75, 0.8)
        store.save_knowledge_observation("t1", "biology", 0.32, 0.6)

        # Build snapshot.
        examples = store.query_examples("t1")
        observations = store.query_knowledge_observations("t1")
        snapshot = PersonaTrainingModel.build_snapshot(
            "t1", examples, observations, as_of="2026-12-01T00:00:00Z",
        )
        sid, _ = store.save_snapshot(
            "t1", snapshot["as_of"],
            positive_count=snapshot["positive_count"],
            negative_count=snapshot["negative_count"],
            review_count=snapshot["review_count"],
            vocabulary=snapshot["vocabulary"],
            distinctive_vocab=snapshot["distinctive_vocab"],
            bigrams=snapshot["bigrams"],
            linguistic_features=snapshot["linguistic_features"],
            knowledge_estimates=snapshot["knowledge_estimates"],
        )
        assert sid is not None

        # Verify snapshot persisted.
        latest = store.latest_snapshot("t1")
        assert latest is not None
        assert latest["positive_count"] == 2

        # Verify stats.
        stats = store.corpus_stats("t1")
        assert stats["total_examples"] == 3
        assert "computers" in stats["per_domain"]

    def test_export_gate_with_store(self, store, tmp_path):
        store.register_target("t1", "Alice")  # pending, not authorized
        store.add_example("t1", "positive", "hello")
        examples = store.query_examples("t1")
        snapshot = PersonaTrainingModel.build_snapshot("t1", examples, [])
        out = tmp_path / "out.jsonl"
        with pytest.raises(PermissionError):
            PersonaTrainingModel.export_jsonl(
                examples, snapshot, out, require_authorized=True, authorized=False,
            )
        # After authorization.
        store.set_authorization("t1", "authorized")
        count = PersonaTrainingModel.export_jsonl(
            examples, snapshot, out, require_authorized=True, authorized=True,
        )
        assert count == 1
