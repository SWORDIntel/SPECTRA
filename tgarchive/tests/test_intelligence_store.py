"""
Tests for the intelligence store and IndexProjector intelligence wiring.

Verifies:
- IntelligenceStore saves evidence/hypotheses/inferences/campaigns to SQLite
- Each save appends to the IndexOutbox with the correct source_table
- IndexProjector projects intelligence events to qihse.intelligence.v1
- KEYSTONE anchors are created for intelligence IDs
- Graph edges are created from ActorHypothesis and Campaign
- Query methods (stats, query_evidence, query_hypotheses, query_campaigns) work
- RelationshipHypothesis is stored in the unified hypotheses table
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from tgarchive.db.intelligence_store import (
    IntelligenceStore,
    record_evidence,
    record_hypothesis,
    record_inference,
    record_campaign,
    EVIDENCE_SOURCE_TABLE,
    HYPOTHESIS_SOURCE_TABLE,
    INFERENCE_SOURCE_TABLE,
    CAMPAIGN_SOURCE_TABLE,
)
from tgarchive.db.index_outbox import IndexOutbox
from tgarchive.db.index_projector import (
    IndexProjector,
    INTELLIGENCE_PROJECTION,
    QIHSE_PROJECTION,
    KEYSTONE_PROJECTION,
    GRAPH_PROJECTION,
    _event_in_projection,
    _projection_identity,
    _projection_numeric_key,
    _graph_records,
)
from tgarchive.intelligence.schema import (
    EvidenceSource,
    AnalysisEvidence,
    ModelInference,
    ActorHypothesis,
    RelationshipHypothesis,
    Campaign,
    EvidenceDirection,
    HypothesisType,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def now():
    return datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def source(now):
    return EvidenceSource(
        source_type="message",
        source_id="telegram:msg:123:456",
        source_table="messages",
        source_row_id=789,
        retrieved_at=now,
        raw_snapshot=None,
    )


@pytest.fixture
def evidence(now, source):
    return AnalysisEvidence(
        evidence_id="",
        evidence_type="stylometric_similarity",
        subject="telegram:user:123",
        object="telegram:user:456",
        score=0.91,
        confidence=0.78,
        direction=EvidenceDirection.SUPPORTS,
        model="spectra-stylometry",
        model_version="2.1.0",
        feature_schema_version="3",
        sources=[source],
        observed_at=now,
        generated_at=now,
        metadata={"cosine_similarity": 0.91},
    )


@pytest.fixture
def actor_hypothesis(now):
    return ActorHypothesis(
        hypothesis_id="",
        hypothesis_type=HypothesisType.SAME_ACTOR,
        subject_a="telegram:user:123",
        subject_b="telegram:user:456",
        probability=0.93,
        confidence=0.81,
        supporting_evidence=["ev1", "ev2"],
        contradicting_evidence=[],
        insufficient_evidence_flags=["temporal"],
        generated_at=now,
        model="spectra-fusion",
        model_version="1.0.0",
    )


@pytest.fixture
def rel_hypothesis(now):
    return RelationshipHypothesis(
        hypothesis_id="",
        hypothesis_type="associated_with",
        subject="telegram:user:123",
        object="telegram:channel:789",
        probability=0.87,
        confidence=0.75,
        supporting_evidence=["ev1"],
        contradicting_evidence=[],
        generated_at=now,
        model="spectra-graph",
        model_version="1.0.0",
    )


@pytest.fixture
def inference(now):
    return ModelInference(
        inference_id="",
        inference_type="threat_score",
        model="spectra-threat-scorer",
        model_version="1.0.0",
        inputs=["ev1", "ev2"],
        output={"threat_score": 7.5, "classification": "High Risk"},
        confidence=0.82,
        generated_at=now,
        feature_schema_version="1",
    )


@pytest.fixture
def campaign(now):
    return Campaign(
        campaign_id="",
        name="Op Phantom",
        actors=["telegram:user:1", "telegram:user:2"],
        channels=["telegram:channel:10"],
        wallets=["btc:1abc"],
        domains=["example.com"],
        message_ids=["telegram:msg:1:10"],
        media_ids=["telegram:media:5"],
        start=now,
        end=now,
        confidence=0.85,
        evidence_ids=["ev1", "ev2"],
        generated_at=now,
        metadata={"actor_count": 2},
    )


# ─── Store: Evidence ───────────────────────────────────────────────────────

class TestStoreEvidence:
    def test_save_evidence_to_sqlite(self, tmp_path, evidence):
        with IntelligenceStore(tmp_path / "test.db") as store:
            seq = store.save_evidence(evidence)
            assert seq is not None and seq > 0
            # Verify row in SQLite
            rows = store.query_evidence()
            assert len(rows) == 1
            assert rows[0]["evidence_type"] == "stylometric_similarity"
            assert rows[0]["subject"] == "telegram:user:123"
            assert rows[0]["evidence_id"] == evidence.evidence_id

    def test_save_evidence_appends_to_outbox(self, tmp_path, evidence):
        with IntelligenceStore(tmp_path / "test.db") as store:
            store.save_evidence(evidence)
            recent = store.recent_evidence()
            assert len(recent) == 1
            assert recent[0]["evidence_id"] == evidence.evidence_id
            assert recent[0]["evidence_type"] == "stylometric_similarity"

    def test_query_evidence_by_type(self, tmp_path, evidence, source, now):
        with IntelligenceStore(tmp_path / "test.db") as store:
            store.save_evidence(evidence)
            ev2 = AnalysisEvidence(
                evidence_id="",
                evidence_type="keyword_indicator",
                subject="telegram:user:999",
                object=None,
                score=0.5,
                confidence=0.6,
                direction=EvidenceDirection.SUPPORTS,
                model="m",
                model_version="1",
                feature_schema_version="1",
                sources=[source],
                observed_at=now,
                generated_at=now,
            )
            store.save_evidence(ev2)
            results = store.query_evidence(evidence_type="keyword_indicator")
            assert len(results) == 1
            assert results[0]["evidence_type"] == "keyword_indicator"

    def test_query_evidence_by_subject(self, tmp_path, evidence):
        with IntelligenceStore(tmp_path / "test.db") as store:
            store.save_evidence(evidence)
            results = store.query_evidence(subject="telegram:user:123")
            assert len(results) == 1
            results = store.query_evidence(subject="telegram:user:999")
            assert len(results) == 0


# ─── Store: Hypotheses ─────────────────────────────────────────────────────

class TestStoreHypotheses:
    def test_save_actor_hypothesis(self, tmp_path, actor_hypothesis):
        with IntelligenceStore(tmp_path / "test.db") as store:
            seq = store.save_hypothesis(actor_hypothesis)
            assert seq is not None and seq > 0
            results = store.query_hypotheses()
            assert len(results) == 1
            assert results[0]["hypothesis_type"] == "same_actor"
            assert results[0]["subject_a"] == "telegram:user:123"
            assert results[0]["subject_b"] == "telegram:user:456"

    def test_save_relationship_hypothesis(self, tmp_path, rel_hypothesis):
        with IntelligenceStore(tmp_path / "test.db") as store:
            seq = store.save_hypothesis(rel_hypothesis)
            assert seq is not None and seq > 0
            # RelationshipHypothesis stored in same table with subject→subject_a
            results = store.query_hypotheses()
            assert len(results) == 1
            assert results[0]["hypothesis_type"] == "associated_with"
            assert results[0]["subject_a"] == "telegram:user:123"
            assert results[0]["subject_b"] == "telegram:channel:789"

    def test_query_hypotheses_by_subject(self, tmp_path, actor_hypothesis):
        with IntelligenceStore(tmp_path / "test.db") as store:
            store.save_hypothesis(actor_hypothesis)
            # Should match either subject_a or subject_b
            results = store.query_hypotheses(subject_a="telegram:user:456")
            assert len(results) == 1
            results = store.query_hypotheses(subject_a="telegram:user:999")
            assert len(results) == 0

    def test_query_hypotheses_min_probability(self, tmp_path, actor_hypothesis):
        with IntelligenceStore(tmp_path / "test.db") as store:
            store.save_hypothesis(actor_hypothesis)
            results = store.query_hypotheses(min_probability=0.95)
            assert len(results) == 0
            results = store.query_hypotheses(min_probability=0.90)
            assert len(results) == 1


# ─── Store: Inferences ─────────────────────────────────────────────────────

class TestStoreInferences:
    def test_save_inference(self, tmp_path, inference):
        with IntelligenceStore(tmp_path / "test.db") as store:
            seq = store.save_inference(inference)
            assert seq is not None and seq > 0


# ─── Store: Campaigns ──────────────────────────────────────────────────────

class TestStoreCampaigns:
    def test_save_campaign(self, tmp_path, campaign):
        with IntelligenceStore(tmp_path / "test.db") as store:
            seq = store.save_campaign(campaign)
            assert seq is not None and seq > 0
            results = store.query_campaigns()
            assert len(results) == 1
            assert results[0]["name"] == "Op Phantom"

    def test_query_campaigns_by_name(self, tmp_path, campaign):
        with IntelligenceStore(tmp_path / "test.db") as store:
            store.save_campaign(campaign)
            results = store.query_campaigns(name="Phantom")
            assert len(results) == 1
            results = store.query_campaigns(name="Nonexistent")
            assert len(results) == 0


# ─── Store: Stats ──────────────────────────────────────────────────────────

class TestStoreStats:
    def test_stats_after_saves(self, tmp_path, evidence, actor_hypothesis, inference, campaign):
        with IntelligenceStore(tmp_path / "test.db") as store:
            store.save_evidence(evidence)
            store.save_hypothesis(actor_hypothesis)
            store.save_inference(inference)
            store.save_campaign(campaign)
            stats = store.stats()
            assert stats["intelligence_evidence"] == 1
            assert stats["intelligence_hypotheses"] == 1
            assert stats["intelligence_inferences"] == 1
            assert stats["intelligence_campaigns"] == 1
            assert stats["outbox"]["intelligence_evidence"] == 1
            assert stats["outbox"]["intelligence_hypotheses"] == 1


# ─── Projector: Intelligence Projection ────────────────────────────────────

class TestProjectorIntelligence:
    def test_intelligence_projection_accepts_evidence(self, evidence):
        event = {
            "source_table": EVIDENCE_SOURCE_TABLE,
            "source_key": evidence.evidence_id,
            "event_type": "save",
            "sequence_id": 1,
            "payload": evidence.to_dict(),
        }
        assert _event_in_projection(INTELLIGENCE_PROJECTION, event) is True
        assert _event_in_projection(QIHSE_PROJECTION, event) is True

    def test_intelligence_projection_rejects_non_intelligence(self):
        event = {
            "source_table": "messages",
            "source_key": "100",
            "event_type": "upsert",
            "sequence_id": 1,
            "payload": {"message_id": 100},
        }
        assert _event_in_projection(INTELLIGENCE_PROJECTION, event) is False

    def test_keystone_anchor_for_evidence(self, evidence):
        event = {
            "source_table": EVIDENCE_SOURCE_TABLE,
            "source_key": evidence.evidence_id,
            "event_type": "save",
            "sequence_id": 1,
            "payload": evidence.to_dict(),
        }
        identity = _projection_identity(KEYSTONE_PROJECTION, event)
        assert identity is not None
        assert identity[0] == "intel-evidence"
        assert identity[1] == evidence.evidence_id

    def test_keystone_anchor_for_hypothesis(self, actor_hypothesis):
        event = {
            "source_table": HYPOTHESIS_SOURCE_TABLE,
            "source_key": actor_hypothesis.hypothesis_id,
            "event_type": "save",
            "sequence_id": 1,
            "payload": actor_hypothesis.to_dict(),
        }
        identity = _projection_identity(KEYSTONE_PROJECTION, event)
        assert identity is not None
        assert identity[0] == "intel-hypotheses"
        assert identity[1] == actor_hypothesis.hypothesis_id

    def test_keystone_numeric_key_is_stable(self, evidence):
        event = {
            "source_table": EVIDENCE_SOURCE_TABLE,
            "source_key": evidence.evidence_id,
            "event_type": "save",
            "sequence_id": 1,
            "payload": evidence.to_dict(),
        }
        key1 = _projection_numeric_key(KEYSTONE_PROJECTION, event)
        key2 = _projection_numeric_key(KEYSTONE_PROJECTION, event)
        assert key1 is not None
        assert key1 == key2
        assert -(2**63) <= key1 < 2**63

    def test_graph_edges_from_actor_hypothesis(self, actor_hypothesis):
        event = {
            "source_table": HYPOTHESIS_SOURCE_TABLE,
            "source_key": actor_hypothesis.hypothesis_id,
            "event_type": "save",
            "sequence_id": 1,
            "payload": actor_hypothesis.to_dict(),
        }
        nodes, edges = _graph_records(event)
        assert len(edges) == 1
        assert edges[0]["edge_type"] == "SAME_ACTOR"
        assert edges[0]["metadata"]["hypothesis_id"] == actor_hypothesis.hypothesis_id
        assert edges[0]["metadata"]["probability"] == 0.93

    def test_graph_edges_from_relationship_hypothesis(self, rel_hypothesis):
        event = {
            "source_table": HYPOTHESIS_SOURCE_TABLE,
            "source_key": rel_hypothesis.hypothesis_id,
            "event_type": "save",
            "sequence_id": 1,
            "payload": rel_hypothesis.to_dict(),
        }
        nodes, edges = _graph_records(event)
        assert len(edges) == 1
        assert edges[0]["edge_type"] == "ASSOCIATED_WITH"

    def test_graph_edges_from_campaign(self, campaign):
        event = {
            "source_table": CAMPAIGN_SOURCE_TABLE,
            "source_key": campaign.campaign_id,
            "event_type": "save",
            "sequence_id": 1,
            "payload": campaign.to_dict(),
        }
        nodes, edges = _graph_records(event)
        # 2 actors + 1 channel = 3 edges
        assert len(edges) == 3
        edge_types = {e["edge_type"] for e in edges}
        assert "PART_OF_CAMPAIGN" in edge_types
        assert "CAMPAIGN_CHANNEL" in edge_types

    def test_graph_no_edges_from_evidence(self, evidence):
        event = {
            "source_table": EVIDENCE_SOURCE_TABLE,
            "source_key": evidence.evidence_id,
            "event_type": "save",
            "sequence_id": 1,
            "payload": evidence.to_dict(),
        }
        _nodes, edges = _graph_records(event)
        assert len(edges) == 0


# ─── Projector: End-to-End Projection ──────────────────────────────────────

class TestProjectorEndToEnd:
    def test_project_intelligence_evidence(self, tmp_path, evidence):
        """Save evidence via store, drain outbox, verify projection records."""
        db = tmp_path / "test.db"
        with IntelligenceStore(db) as store:
            store.save_evidence(evidence)

        projector = IndexProjector(db)
        try:
            result = projector.process(batch_size=10)
            assert result["ok"] is True
            assert result["processed"] >= 1

            # Verify intelligence projection has the record
            from tgarchive.sqlite_runtime import connect_sqlite
            with connect_sqlite(db) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM index_projection_records "
                    "WHERE projection_name = ? AND source_table = ?",
                    (INTELLIGENCE_PROJECTION, EVIDENCE_SOURCE_TABLE),
                ).fetchone()
                assert row is not None
                assert row["source_key"] == evidence.evidence_id

                # Verify QIHSE content projection also has it
                qihse_row = conn.execute(
                    "SELECT * FROM index_projection_records "
                    "WHERE projection_name = ? AND source_table = ?",
                    (QIHSE_PROJECTION, EVIDENCE_SOURCE_TABLE),
                ).fetchone()
                assert qihse_row is not None
                assert qihse_row["text_content"] is not None

                # Verify KEYSTONE anchor
                ks_row = conn.execute(
                    "SELECT * FROM index_projection_keys "
                    "WHERE projection_name = ? AND logical_key LIKE ?",
                    (KEYSTONE_PROJECTION, f'["intel-evidence","{evidence.evidence_id}"]'),
                ).fetchone()
                assert ks_row is not None
        finally:
            projector.close()

    def test_project_intelligence_hypothesis_graph(self, tmp_path, actor_hypothesis):
        """Save hypothesis via store, drain, verify graph edges created."""
        db = tmp_path / "test.db"
        with IntelligenceStore(db) as store:
            store.save_hypothesis(actor_hypothesis)

        projector = IndexProjector(db)
        try:
            result = projector.process(batch_size=10)
            assert result["ok"] is True

            from tgarchive.sqlite_runtime import connect_sqlite
            with connect_sqlite(db) as conn:
                conn.row_factory = sqlite3.Row
                # Verify graph edge
                edge = conn.execute(
                    "SELECT * FROM index_graph_edges WHERE edge_type = ?",
                    ("SAME_ACTOR",),
                ).fetchone()
                assert edge is not None

                # Verify graph nodes for both users
                node1 = conn.execute(
                    "SELECT * FROM index_graph_nodes WHERE node_type = 'user' AND external_id = '123'"
                ).fetchone()
                assert node1 is not None

                node2 = conn.execute(
                    "SELECT * FROM index_graph_nodes WHERE node_type = 'user' AND external_id = '456'"
                ).fetchone()
                assert node2 is not None
        finally:
            projector.close()

    def test_project_campaign_graph(self, tmp_path, campaign):
        """Save campaign, drain, verify campaign graph edges."""
        db = tmp_path / "test.db"
        with IntelligenceStore(db) as store:
            store.save_campaign(campaign)

        projector = IndexProjector(db)
        try:
            result = projector.process(batch_size=10)
            assert result["ok"] is True

            from tgarchive.sqlite_runtime import connect_sqlite
            with connect_sqlite(db) as conn:
                conn.row_factory = sqlite3.Row
                # Should have PART_OF_CAMPAIGN and CAMPAIGN_CHANNEL edges
                part_edges = conn.execute(
                    "SELECT * FROM index_graph_edges WHERE edge_type = 'PART_OF_CAMPAIGN'"
                ).fetchall()
                assert len(part_edges) == 2  # 2 actors

                chan_edges = conn.execute(
                    "SELECT * FROM index_graph_edges WHERE edge_type = 'CAMPAIGN_CHANNEL'"
                ).fetchall()
                assert len(chan_edges) == 1  # 1 channel
        finally:
            projector.close()

    def test_project_all_intelligence_types(self, tmp_path, evidence, actor_hypothesis, inference, campaign):
        """Save all four intelligence types, drain, verify all projections."""
        db = tmp_path / "test.db"
        with IntelligenceStore(db) as store:
            store.save_evidence(evidence)
            store.save_hypothesis(actor_hypothesis)
            store.save_inference(inference)
            store.save_campaign(campaign)

        projector = IndexProjector(db)
        try:
            result = projector.process(batch_size=10)
            assert result["ok"] is True
            assert result["processed"] >= 4

            from tgarchive.sqlite_runtime import connect_sqlite
            with connect_sqlite(db) as conn:
                conn.row_factory = sqlite3.Row
                # Intelligence projection should have all 4
                intel_rows = conn.execute(
                    "SELECT source_table FROM index_projection_records "
                    "WHERE projection_name = ?",
                    (INTELLIGENCE_PROJECTION,),
                ).fetchall()
                tables = {r["source_table"] for r in intel_rows}
                assert EVIDENCE_SOURCE_TABLE in tables
                assert HYPOTHESIS_SOURCE_TABLE in tables
                assert INFERENCE_SOURCE_TABLE in tables
                assert CAMPAIGN_SOURCE_TABLE in tables
        finally:
            projector.close()
