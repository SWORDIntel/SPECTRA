"""
Tests for the canonical intelligence evidence schema.

Verifies:
- Evidence ID determinism (same inputs → same ID)
- Evidence ID uniqueness (different inputs → different IDs)
- to_dict / from_dict round-trip for all objects
- to_sql_row produces correct tuple
- JSON serialization stability
- Canonical entity ID format
- Validation on construction
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from tgarchive.intelligence.schema import (
    SCHEMA_VERSION,
    EvidenceSource,
    AnalysisEvidence,
    ModelInference,
    ActorHypothesis,
    RelationshipHypothesis,
    Campaign,
    EvidenceDirection,
    HypothesisType,
    canonical_id,
    generate_evidence_id,
    generate_hypothesis_id,
    generate_inference_id,
    generate_campaign_id,
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
def source2(now):
    return EvidenceSource(
        source_type="message",
        source_id="telegram:msg:124:456",
        source_table="messages",
        source_row_id=790,
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
        metadata={"cosine_similarity": 0.91, "message_count_a": 50, "message_count_b": 30},
    )


# ─── Canonical ID ──────────────────────────────────────────────────────────

class TestCanonicalId:
    def test_basic_format(self):
        cid = canonical_id("telegram", "user", 123)
        assert cid == "telegram:user:123"

    def test_with_channel(self):
        cid = canonical_id("telegram", "msg", "123:456")
        assert cid == "telegram:msg:123:456"

    def test_different_platforms(self):
        assert canonical_id("telegram", "user", 1) != canonical_id("discord", "user", 1)

    def test_different_entity_types(self):
        assert canonical_id("telegram", "user", 1) != canonical_id("telegram", "channel", 1)


# ─── Evidence ID Determinism ───────────────────────────────────────────────

class TestEvidenceIdDeterminism:
    def test_same_inputs_same_id(self, source, now):
        eid1 = generate_evidence_id(
            evidence_type="stylometric_similarity",
            subject="telegram:user:123",
            object="telegram:user:456",
            model="spectra-stylometry",
            model_version="2.1.0",
            sources=[source],
        )
        eid2 = generate_evidence_id(
            evidence_type="stylometric_similarity",
            subject="telegram:user:123",
            object="telegram:user:456",
            model="spectra-stylometry",
            model_version="2.1.0",
            sources=[source],
        )
        assert eid1 == eid2

    def test_different_subjects_different_ids(self, source, now):
        eid1 = generate_evidence_id(
            evidence_type="test",
            subject="telegram:user:123",
            object=None,
            model="m",
            model_version="1",
            sources=[source],
        )
        eid2 = generate_evidence_id(
            evidence_type="test",
            subject="telegram:user:456",
            object=None,
            model="m",
            model_version="1",
            sources=[source],
        )
        assert eid1 != eid2

    def test_different_models_different_ids(self, source):
        eid1 = generate_evidence_id(
            evidence_type="test",
            subject="telegram:user:123",
            object=None,
            model="model_a",
            model_version="1",
            sources=[source],
        )
        eid2 = generate_evidence_id(
            evidence_type="test",
            subject="telegram:user:123",
            object=None,
            model="model_b",
            model_version="1",
            sources=[source],
        )
        assert eid1 != eid2

    def test_source_order_doesnt_matter(self, source, source2):
        eid1 = generate_evidence_id(
            evidence_type="test",
            subject="telegram:user:123",
            object=None,
            model="m",
            model_version="1",
            sources=[source, source2],
        )
        eid2 = generate_evidence_id(
            evidence_type="test",
            subject="telegram:user:123",
            object=None,
            model="m",
            model_version="1",
            sources=[source2, source],
        )
        assert eid1 == eid2

    def test_id_is_16_hex_chars(self, source):
        eid = generate_evidence_id(
            evidence_type="test",
            subject="telegram:user:123",
            object=None,
            model="m",
            model_version="1",
            sources=[source],
        )
        assert len(eid) == 16
        int(eid, 16)  # must be valid hex


# ─── AnalysisEvidence ──────────────────────────────────────────────────────

class TestAnalysisEvidence:
    def test_post_init_generates_id(self, evidence):
        assert evidence.evidence_id != ""
        assert len(evidence.evidence_id) == 16

    def test_to_dict_round_trip(self, evidence):
        d = evidence.to_dict()
        assert isinstance(d, dict)
        assert d["evidence_type"] == "stylometric_similarity"
        assert d["score"] == 0.91
        assert d["confidence"] == 0.78
        assert d["direction"] == "supports"
        assert len(d["sources"]) == 1
        assert d["sources"][0]["source_type"] == "message"

        restored = AnalysisEvidence.from_dict(d)
        assert restored.evidence_type == evidence.evidence_type
        assert restored.score == evidence.score
        assert restored.confidence == evidence.confidence
        assert restored.subject == evidence.subject
        assert restored.object == evidence.object
        assert restored.evidence_id == evidence.evidence_id

    def test_to_sql_row(self, evidence):
        row = evidence.to_sql_row()
        assert isinstance(row, tuple)
        assert len(row) == 14  # matches SQL schema columns
        assert row[0] == evidence.evidence_id
        assert row[1] == "stylometric_similarity"
        assert row[4] == 0.91  # score
        assert row[5] == 0.78  # confidence

    def test_json_serialization(self, evidence):
        j = json.dumps(evidence.to_dict())
        d = json.loads(j)
        restored = AnalysisEvidence.from_dict(d)
        assert restored.evidence_id == evidence.evidence_id

    def test_confidence_range_validation(self, source, now):
        with pytest.raises(ValueError):
            AnalysisEvidence(
                evidence_id="",
                evidence_type="test",
                subject="telegram:user:1",
                object=None,
                score=0.5,
                confidence=1.5,  # out of range
                direction=EvidenceDirection.SUPPORTS,
                model="m",
                model_version="1",
                feature_schema_version="1",
                sources=[source],
                observed_at=now,
                generated_at=now,
                metadata={},
            )

    def test_empty_sources_validation(self, now):
        with pytest.raises(ValueError):
            AnalysisEvidence(
                evidence_id="",
                evidence_type="test",
                subject="telegram:user:1",
                object=None,
                score=0.5,
                confidence=0.5,
                direction=EvidenceDirection.SUPPORTS,
                model="m",
                model_version="1",
                feature_schema_version="1",
                sources=[],  # empty
                observed_at=now,
                generated_at=now,
                metadata={},
            )

    def test_score_can_differ_from_confidence(self, evidence):
        assert evidence.score != evidence.confidence


# ─── ModelInference ────────────────────────────────────────────────────────

class TestModelInference:
    def test_round_trip(self, now):
        inf = ModelInference(
            inference_id="",
            inference_type="threat_score",
            model="spectra-threat-scorer",
            model_version="1.0.0",
            inputs=["ev123", "ev124"],
            output={"threat_score": 7.5, "classification": "High Risk"},
            confidence=0.82,
            generated_at=now,
            feature_schema_version="1",
        )
        assert inf.inference_id != ""

        d = inf.to_dict()
        restored = ModelInference.from_dict(d)
        assert restored.inference_type == inf.inference_type
        assert restored.output == inf.output
        assert restored.inference_id == inf.inference_id

    def test_to_sql_row(self, now):
        inf = ModelInference(
            inference_id="abc123",
            inference_type="threat_score",
            model="m",
            model_version="1",
            inputs=["ev1"],
            output={"score": 5},
            confidence=0.8,
            generated_at=now,
            feature_schema_version="1",
        )
        row = inf.to_sql_row()
        assert isinstance(row, tuple)
        assert row[0] == "abc123"


# ─── ActorHypothesis ───────────────────────────────────────────────────────

class TestActorHypothesis:
    def test_round_trip(self, now):
        h = ActorHypothesis(
            hypothesis_id="",
            hypothesis_type=HypothesisType.SAME_ACTOR,
            subject_a="telegram:user:123",
            subject_b="telegram:user:456",
            probability=0.93,
            confidence=0.81,
            supporting_evidence=["ev1", "ev2", "ev3"],
            contradicting_evidence=["ev4"],
            insufficient_evidence_flags=["temporal"],
            generated_at=now,
            model="spectra-fusion",
            model_version="1.0.0",
        )
        assert h.hypothesis_id != ""

        d = h.to_dict()
        restored = ActorHypothesis.from_dict(d)
        assert restored.hypothesis_type == h.hypothesis_type
        assert restored.probability == h.probability
        assert restored.supporting_evidence == h.supporting_evidence
        assert restored.contradicting_evidence == h.contradicting_evidence
        assert restored.hypothesis_id == h.hypothesis_id

    def test_to_sql_row(self, now):
        h = ActorHypothesis(
            hypothesis_id="hid123",
            hypothesis_type=HypothesisType.SAME_ACTOR,
            subject_a="telegram:user:1",
            subject_b="telegram:user:2",
            probability=0.9,
            confidence=0.8,
            supporting_evidence=["ev1"],
            contradicting_evidence=[],
            insufficient_evidence_flags=[],
            generated_at=now,
            model="m",
            model_version="1",
        )
        row = h.to_sql_row()
        assert isinstance(row, tuple)
        assert row[0] == "hid123"


# ─── RelationshipHypothesis ────────────────────────────────────────────────

class TestRelationshipHypothesis:
    def test_round_trip(self, now):
        h = RelationshipHypothesis(
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
        assert h.hypothesis_id != ""

        d = h.to_dict()
        restored = RelationshipHypothesis.from_dict(d)
        assert restored.hypothesis_type == h.hypothesis_type
        assert restored.hypothesis_id == h.hypothesis_id


# ─── Campaign ──────────────────────────────────────────────────────────────

class TestCampaign:
    def test_round_trip(self, now):
        c = Campaign(
            campaign_id="",
            name="CAMPAIGN-2026-00981",
            actors=["telegram:user:1", "telegram:user:2"],
            channels=["telegram:channel:10"],
            wallets=["btc:1abc..."],
            domains=["example.com"],
            message_ids=["telegram:msg:1:10", "telegram:msg:2:10"],
            media_ids=["telegram:media:5"],
            start=now,
            end=now,
            confidence=0.85,
            evidence_ids=["ev1", "ev2"],
            generated_at=now,
            metadata={"actor_count": 2},
        )
        assert c.campaign_id != ""

        d = c.to_dict()
        restored = Campaign.from_dict(d)
        assert restored.name == c.name
        assert restored.actors == c.actors
        assert restored.campaign_id == c.campaign_id

    def test_to_sql_row(self, now):
        c = Campaign(
            campaign_id="cid123",
            name="test",
            actors=["a"],
            channels=["c"],
            wallets=[],
            domains=[],
            message_ids=[],
            media_ids=[],
            start=now,
            end=now,
            confidence=0.8,
            evidence_ids=[],
            generated_at=now,
            metadata={},
        )
        row = c.to_sql_row()
        assert isinstance(row, tuple)
        assert row[0] == "cid123"


# ─── Schema Version ────────────────────────────────────────────────────────

class TestSchemaVersion:
    def test_version_exists(self):
        assert SCHEMA_VERSION is not None
        assert isinstance(SCHEMA_VERSION, str)
        # Should be semver
        parts = SCHEMA_VERSION.split(".")
        assert len(parts) == 3
