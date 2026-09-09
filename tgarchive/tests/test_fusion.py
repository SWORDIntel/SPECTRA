"""
Tests for the evidence fusion engine.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tgarchive.intelligence.fusion import (
    EvidenceFusionEngine,
    FusionResult,
    HYPOTHESES,
    DEFAULT_PRIORS,
)
from tgarchive.intelligence.schema import (
    AnalysisEvidence,
    EvidenceDirection,
    EvidenceSource,
    HypothesisType,
)


@pytest.fixture
def now():
    return datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def source(now):
    return EvidenceSource(
        source_type="message",
        source_id="telegram:msg:100:1",
        source_table="messages",
        source_row_id=1,
        retrieved_at=now,
    )


@pytest.fixture
def source2(now):
    return EvidenceSource(
        source_type="message",
        source_id="telegram:msg:100:2",
        source_table="messages",
        source_row_id=2,
        retrieved_at=now,
    )


def make_evidence(
    evidence_type, score, confidence, direction, sources, subject="telegram:user:1", obj="telegram:user:2", now=None
):
    now = now or datetime.now(timezone.utc)
    return AnalysisEvidence(
        evidence_id="",
        evidence_type=evidence_type,
        subject=subject,
        object=obj,
        score=score,
        confidence=confidence,
        direction=direction,
        model="test",
        model_version="1.0",
        feature_schema_version="1",
        sources=sources,
        observed_at=now,
        generated_at=now,
    )


class TestEvidenceFusionEngine:
    def test_empty_evidence(self):
        engine = EvidenceFusionEngine()
        result = engine.fuse([], "telegram:user:1", "telegram:user:2")
        assert result.best_hypothesis is None
        assert "all" in result.insufficient_evidence

    def test_single_supporting_evidence(self, source):
        engine = EvidenceFusionEngine()
        ev = make_evidence(
            "linguistic_similarity", 0.9, 0.8, EvidenceDirection.SUPPORTS, [source]
        )
        result = engine.fuse([ev], "telegram:user:1", "telegram:user:2")
        assert result.best_hypothesis is not None
        assert result.best_hypothesis.probability > 0
        assert len(result.hypotheses) == len(HYPOTHESES)

    def test_same_actor_high_score(self, source, source2):
        """High scores across multiple families should favor same_actor."""
        engine = EvidenceFusionEngine()
        evs = [
            make_evidence("linguistic_similarity", 0.95, 0.85, EvidenceDirection.SUPPORTS, [source]),
            make_evidence("temporal_similarity", 0.88, 0.75, EvidenceDirection.SUPPORTS, [source2]),
            make_evidence("infrastructure_similarity", 0.92, 0.90, EvidenceDirection.SUPPORTS, [source]),
        ]
        result = engine.fuse(evs, "telegram:user:1", "telegram:user:2")
        # Same actor should be the top hypothesis
        assert result.best_hypothesis.hypothesis_type == HypothesisType.SAME_ACTOR
        assert result.best_hypothesis.probability > 0.5

    def test_contradicting_evidence_lowers_same_actor(self, source, source2):
        """Contradicting evidence should lower same_actor probability."""
        engine = EvidenceFusionEngine()
        evs = [
            make_evidence("linguistic_similarity", 0.3, 0.8, EvidenceDirection.CONTRADICTS, [source]),
            make_evidence("temporal_similarity", 0.2, 0.75, EvidenceDirection.CONTRADICTS, [source2]),
        ]
        result = engine.fuse(evs, "telegram:user:1", "telegram:user:2")
        same_actor_h = [h for h in result.hypotheses if h.hypothesis_type == HypothesisType.SAME_ACTOR][0]
        # Same actor should have low probability
        assert same_actor_h.probability < 0.5

    def test_anti_double_counting(self, source):
        """Correlated evidence should be merged, not double-counted."""
        engine = EvidenceFusionEngine(correlation_threshold=0.5)
        # Two evidence items with same sources → correlated
        ev1 = make_evidence("infrastructure_similarity", 0.9, 0.8, EvidenceDirection.SUPPORTS, [source])
        ev2 = make_evidence("infrastructure_similarity", 0.85, 0.7, EvidenceDirection.SUPPORTS, [source])
        result = engine.fuse([ev1, ev2], "telegram:user:1", "telegram:user:2")
        assert result.correlated_evidence_merged > 0
        assert len(result.evidence_used) == 1  # Only one survived dedup

    def test_no_double_counting_inflation(self, source, source2):
        """Five correlated weak scores should not inflate probability to 96%."""
        engine = EvidenceFusionEngine(correlation_threshold=0.3)
        # Five evidence items all from the same source (correlated)
        evs = [
            make_evidence("heuristic_1", 0.42, 0.3, EvidenceDirection.SUPPORTS, [source]),
            make_evidence("heuristic_2", 0.42, 0.3, EvidenceDirection.SUPPORTS, [source]),
            make_evidence("heuristic_3", 0.42, 0.3, EvidenceDirection.SUPPORTS, [source]),
            make_evidence("heuristic_4", 0.42, 0.3, EvidenceDirection.SUPPORTS, [source]),
            make_evidence("heuristic_5", 0.42, 0.3, EvidenceDirection.SUPPORTS, [source]),
        ]
        result = engine.fuse(evs, "telegram:user:1", "telegram:user:2")
        # After dedup, only 1 evidence survives → probability should be moderate
        assert result.correlated_evidence_merged >= 4
        if result.best_hypothesis:
            # Should NOT jump to 96% from 42% scores
            assert result.best_hypothesis.probability < 0.95

    def test_all_hypotheses_present(self, source):
        engine = EvidenceFusionEngine()
        ev = make_evidence("linguistic_similarity", 0.7, 0.8, EvidenceDirection.SUPPORTS, [source])
        result = engine.fuse([ev], "telegram:user:1", "telegram:user:2")
        h_types = {h.hypothesis_type for h in result.hypotheses}
        assert HypothesisType.SAME_ACTOR in h_types
        assert HypothesisType.DIFFERENT_ACTOR in h_types
        assert HypothesisType.SHARED_ORGANIZATION in h_types
        assert HypothesisType.AUTOMATION in h_types
        assert HypothesisType.COPIED_CONTENT in h_types
        assert HypothesisType.COMPROMISED_ACCOUNT in h_types

    def test_hypotheses_sorted_by_probability(self, source):
        engine = EvidenceFusionEngine()
        ev = make_evidence("linguistic_similarity", 0.9, 0.8, EvidenceDirection.SUPPORTS, [source])
        result = engine.fuse([ev], "telegram:user:1", "telegram:user:2")
        probs = [h.probability for h in result.hypotheses]
        assert probs == sorted(probs, reverse=True)

    def test_fusion_result_serializable(self, source):
        engine = EvidenceFusionEngine()
        ev = make_evidence("linguistic_similarity", 0.7, 0.8, EvidenceDirection.SUPPORTS, [source])
        result = engine.fuse([ev], "telegram:user:1", "telegram:user:2")
        d = result.to_dict()
        import json
        json.dumps(d)  # Must not raise

    def test_custom_priors(self, source):
        custom_priors = {
            HypothesisType.SAME_ACTOR: 0.5,
            HypothesisType.DIFFERENT_ACTOR: 0.2,
            HypothesisType.SHARED_ORGANIZATION: 0.1,
            HypothesisType.AUTOMATION: 0.05,
            HypothesisType.COPIED_CONTENT: 0.1,
            HypothesisType.COMPROMISED_ACCOUNT: 0.05,
        }
        engine = EvidenceFusionEngine(priors=custom_priors)
        ev = make_evidence("linguistic_similarity", 0.5, 0.5, EvidenceDirection.SUPPORTS, [source])
        result = engine.fuse([ev], "telegram:user:1", "telegram:user:2")
        # With higher prior for same_actor, it should be favored even with neutral evidence
        same_actor = [h for h in result.hypotheses if h.hypothesis_type == HypothesisType.SAME_ACTOR][0]
        different = [h for h in result.hypotheses if h.hypothesis_type == HypothesisType.DIFFERENT_ACTOR][0]
        assert same_actor.probability > different.probability
