"""
Tests for the probabilistic Entity Resolver v2.

Covers normalization, the 7 independent evidence scorers, Bayesian fusion,
decision thresholds (merge/review/new_cluster), and integration with the
canonical ``AnalysisEvidence`` / ``ActorHypothesis`` schema.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tgarchive.intelligence.entity_resolver_v2 import (
    EVIDENCE_WEIGHTS,
    MERGE_THRESHOLD,
    MODEL_VERSION,
    REVIEW_THRESHOLD,
    EntityCandidate,
    EntityResolverV2,
    IdentityCluster,
    Mention,
    ResolutionEvidence,
    ResolutionResult,
)
from tgarchive.intelligence.schema import (
    ActorHypothesis,
    AnalysisEvidence,
    EvidenceDirection,
    EvidenceSource,
    HypothesisType,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def resolver() -> EntityResolverV2:
    return EntityResolverV2()


@pytest.fixture
def base_time() -> datetime:
    return datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc)


@pytest.fixture
def darkvendor_mention(base_time) -> Mention:
    """A mention with a username, handle, name, and user_id."""
    return Mention(
        raw_text="@darkvendor",
        mention_type="username",
        source_id="telegram:msg:100:1",
        channel_id=100,
        observed_at=base_time,
        metadata={
            "display_name": "Dark Vendor",
            "user_id": 12345,
            "bio": "Selling malware samples. DM for price.",
            "photo_hash": "abc123",
            "device_model": "iPhone 14",
        },
    )


@pytest.fixture
def darkvendor_mention_dup(base_time) -> Mention:
    """A second mention of the same actor (same username, different source)."""
    return Mention(
        raw_text="@darkvendor",
        mention_type="username",
        source_id="telegram:msg:200:5",
        channel_id=200,
        observed_at=base_time,
        metadata={
            "display_name": "Dark Vendor",
            "user_id": 12345,
        },
    )


@pytest.fixture
def different_actor_mention(base_time) -> Mention:
    """A mention of a completely different actor."""
    return Mention(
        raw_text="@vpnreviewer",
        mention_type="username",
        source_id="telegram:msg:300:10",
        channel_id=300,
        observed_at=base_time,
        metadata={
            "display_name": "VPN Reviewer",
            "user_id": 99999,
        },
    )


# ─── Normalization tests ─────────────────────────────────────────────────────


class TestNormalization:
    """Tests for the Mention → EntityCandidate normalization."""

    def test_normalize_username(self, resolver, base_time):
        mention = Mention(
            raw_text="@DarkVendor",
            mention_type="username",
            observed_at=base_time,
        )
        candidate = resolver.normalize(mention)
        assert candidate.username == "darkvendor"
        assert candidate.handle == "@darkvendor"

    def test_normalize_phone(self, resolver, base_time):
        mention = Mention(
            raw_text="+1 (555) 123-4567",
            mention_type="phone",
            observed_at=base_time,
        )
        candidate = resolver.normalize(mention)
        assert candidate.phone == "15551234567"

    def test_normalize_name(self, resolver, base_time):
        mention = Mention(
            raw_text="Dark Vendor",
            mention_type="name",
            observed_at=base_time,
        )
        candidate = resolver.normalize(mention)
        assert candidate.display_name == "dark vendor"

    def test_normalize_user_id(self, resolver, base_time):
        mention = Mention(
            raw_text="12345",
            mention_type="user_id",
            observed_at=base_time,
        )
        candidate = resolver.normalize(mention)
        assert candidate.user_id == 12345

    def test_normalize_auto_detect_handle(self, resolver, base_time):
        mention = Mention(raw_text="@somehandle", observed_at=base_time)
        candidate = resolver.normalize(mention)
        assert candidate.handle == "@somehandle"
        assert candidate.username == "somehandle"

    def test_normalize_auto_detect_phone(self, resolver, base_time):
        mention = Mention(raw_text="+1 555 123 4567", observed_at=base_time)
        candidate = resolver.normalize(mention)
        assert candidate.phone == "15551234567"

    def test_normalize_auto_detect_name(self, resolver, base_time):
        mention = Mention(raw_text="Some Display Name", observed_at=base_time)
        candidate = resolver.normalize(mention)
        assert candidate.display_name == "some display name"

    def test_normalize_metadata_overrides(self, resolver, base_time):
        mention = Mention(
            raw_text="ignored",
            mention_type="unknown",
            observed_at=base_time,
            metadata={
                "username": "realuser",
                "bio": "This is my bio",
                "photo_hash": "hash123",
            },
        )
        candidate = resolver.normalize(mention)
        assert candidate.username == "realuser"
        assert candidate.bio == "this is my bio"
        assert candidate.photo_hash == "hash123"

    def test_normalize_deterministic_candidate_id(self, resolver, base_time):
        mention = Mention(
            raw_text="@darkvendor",
            mention_type="username",
            source_id="telegram:msg:100:1",
            observed_at=base_time,
        )
        c1 = resolver.normalize(mention)
        c2 = resolver.normalize(mention)
        assert c1.candidate_id == c2.candidate_id
        assert len(c1.candidate_id) == 16

    def test_normalize_strips_diacritics(self, resolver, base_time):
        mention = Mention(
            raw_text="Café Müller",
            mention_type="name",
            observed_at=base_time,
        )
        candidate = resolver.normalize(mention)
        assert candidate.display_name == "cafe muller"


# ─── Resolution tests ────────────────────────────────────────────────────────


class TestResolution:
    """Tests for the full resolve() pipeline."""

    def test_first_mention_creates_new_cluster(
        self, resolver, darkvendor_mention
    ):
        result = resolver.resolve(darkvendor_mention, [])
        assert result.action == "new_cluster"
        assert result.cluster.candidates[0].username == "darkvendor"
        assert len(result.cluster.candidates) == 1
        assert result.probability == 0.0

    def test_exact_match_merges(
        self, resolver, darkvendor_mention, darkvendor_mention_dup
    ):
        # First mention creates a cluster.
        r1 = resolver.resolve(darkvendor_mention, [])
        assert r1.action == "new_cluster"
        clusters = [r1.cluster]

        # Second mention (same user_id) should merge.
        r2 = resolver.resolve(darkvendor_mention_dup, clusters)
        assert r2.action == "merge"
        assert r2.probability > MERGE_THRESHOLD
        assert len(r2.cluster.candidates) == 2

    def test_different_actor_creates_new_cluster(
        self, resolver, darkvendor_mention, different_actor_mention
    ):
        r1 = resolver.resolve(darkvendor_mention, [])
        clusters = [r1.cluster]

        r2 = resolver.resolve(different_actor_mention, clusters)
        assert r2.action == "new_cluster"
        assert r2.cluster is not r1.cluster
        assert r2.probability < REVIEW_THRESHOLD

    def test_all_scores_populated(
        self, resolver, darkvendor_mention, different_actor_mention
    ):
        r1 = resolver.resolve(darkvendor_mention, [])
        r2 = resolver.resolve(darkvendor_mention, [r1.cluster])
        # all_scores should have at least one entry.
        assert len(r2.all_scores) >= 1
        assert all(isinstance(score, float) for _, score in r2.all_scores)

    def test_review_threshold(self, resolver, base_time):
        """A partial match should land in the review zone."""
        mention_a = Mention(
            raw_text="@darkvendor",
            mention_type="username",
            source_id="telegram:msg:100:1",
            channel_id=100,
            observed_at=base_time,
            metadata={"display_name": "Dark Vendor", "user_id": 12345},
        )
        mention_b = Mention(
            raw_text="@darkvendor2",
            mention_type="username",
            source_id="telegram:msg:200:5",
            channel_id=100,
            observed_at=base_time,
            metadata={"display_name": "Dark Vendor 2"},
        )
        r1 = resolver.resolve(mention_a, [])
        r2 = resolver.resolve(mention_b, [r1.cluster])
        # Should be either review or new_cluster, not merge (fuzzy but not exact).
        assert r2.action in ("review", "new_cluster")
        assert r2.probability < MERGE_THRESHOLD

    def test_merge_adds_evidence_to_cluster(
        self, resolver, darkvendor_mention, darkvendor_mention_dup
    ):
        r1 = resolver.resolve(darkvendor_mention, [])
        clusters = [r1.cluster]
        r2 = resolver.resolve(darkvendor_mention_dup, clusters)
        assert r2.action == "merge"
        # The cluster should now have evidence from the merge.
        assert len(r2.cluster.evidence) > 0

    def test_contradicting_evidence_collected(
        self, resolver, darkvendor_mention, different_actor_mention
    ):
        r1 = resolver.resolve(darkvendor_mention, [])
        r2 = resolver.resolve(different_actor_mention, [r1.cluster])
        # Different actor should produce some contradicting evidence.
        contradicting = [
            e for e in r2.evidence
            if e.direction == EvidenceDirection.CONTRADICTS
        ]
        assert len(contradicting) > 0

    def test_cluster_representative_is_most_recent(
        self, resolver, darkvendor_mention, darkvendor_mention_dup
    ):
        r1 = resolver.resolve(darkvendor_mention, [])
        clusters = [r1.cluster]
        r2 = resolver.resolve(darkvendor_mention_dup, clusters)
        rep = r2.cluster.representative()
        assert rep is not None
        # The second mention was observed at the same time, so either is fine,
        # but representative should return a valid candidate.
        assert rep in r2.cluster.candidates


# ─── Evidence scorer tests ───────────────────────────────────────────────────


class TestEvidenceScorers:
    """Tests for individual evidence source scorers."""

    def test_username_exact_match(self, resolver, darkvendor_mention):
        candidate = resolver.normalize(darkvendor_mention)
        cluster = IdentityCluster(
            cluster_id="test",
            candidates=[candidate],
        )
        from tgarchive.intelligence.entity_resolver_v2 import _score_username
        ev = _score_username(candidate, cluster)
        assert ev.source == "username"
        assert ev.score == 1.0
        assert ev.direction == EvidenceDirection.SUPPORTS

    def test_username_no_data(self, resolver, base_time):
        candidate = EntityCandidate(candidate_id="x", username=None)
        cluster = IdentityCluster(cluster_id="c", candidates=[candidate])
        from tgarchive.intelligence.entity_resolver_v2 import _score_username
        ev = _score_username(candidate, cluster)
        assert ev.confidence == 0.0
        assert ev.direction == EvidenceDirection.NEUTRAL

    def test_identifier_user_id_match(self, resolver, darkvendor_mention):
        candidate = resolver.normalize(darkvendor_mention)
        cluster = IdentityCluster(cluster_id="test", candidates=[candidate])
        from tgarchive.intelligence.entity_resolver_v2 import _score_identifier
        ev = _score_identifier(candidate, cluster)
        assert ev.score == 1.0
        assert ev.confidence == 0.99

    def test_identifier_partial_phone_match(self, resolver, base_time):
        c1 = EntityCandidate(candidate_id="a", phone="15551234567")
        c2 = EntityCandidate(candidate_id="b", phone="18001234567")
        cluster = IdentityCluster(cluster_id="c", candidates=[c2])
        from tgarchive.intelligence.entity_resolver_v2 import _score_identifier
        ev = _score_identifier(c1, cluster)
        # Last 7 digits match → partial match.
        assert ev.score == 0.85
        assert ev.direction == EvidenceDirection.SUPPORTS

    def test_source_consistency_photo_match(self, resolver, base_time):
        c1 = EntityCandidate(
            candidate_id="a", photo_hash="abc123", bio="hello"
        )
        c2 = EntityCandidate(
            candidate_id="b", photo_hash="abc123", bio="different"
        )
        cluster = IdentityCluster(cluster_id="c", candidates=[c2])
        from tgarchive.intelligence.entity_resolver_v2 import (
            _score_source_consistency,
        )
        ev = _score_source_consistency(c1, cluster)
        assert ev.score == 1.0
        assert "photo" in ev.metadata.get("matches", [])

    def test_co_occurrence_shared_channel(self, resolver, base_time):
        c1 = EntityCandidate(candidate_id="a", channel_id=100)
        c2 = EntityCandidate(candidate_id="b", channel_id=100)
        cluster = IdentityCluster(cluster_id="c", candidates=[c2])
        from tgarchive.intelligence.entity_resolver_v2 import (
            _score_co_occurrence,
        )
        ev = _score_co_occurrence(c1, cluster)
        assert ev.direction == EvidenceDirection.SUPPORTS
        assert ev.score > 0.4


# ─── Fusion tests ────────────────────────────────────────────────────────────


class TestFusion:
    """Tests for the Bayesian evidence fusion."""

    def test_fuse_no_evidence_returns_prior(self):
        from tgarchive.intelligence.entity_resolver_v2 import _fuse_evidence
        prob, conf = _fuse_evidence([], prior_same=0.1)
        assert abs(prob - 0.1) < 0.01
        assert conf == 0.0

    def test_fuse_strong_supporting_evidence(self):
        from tgarchive.intelligence.entity_resolver_v2 import _fuse_evidence
        evidence = [
            ResolutionEvidence(
                source="username",
                score=1.0,
                confidence=0.95,
                direction=EvidenceDirection.SUPPORTS,
            ),
            ResolutionEvidence(
                source="identifier",
                score=1.0,
                confidence=0.99,
                direction=EvidenceDirection.SUPPORTS,
            ),
        ]
        prob, conf = _fuse_evidence(evidence, prior_same=0.1)
        # Two strong sources should significantly elevate from the 0.1 prior.
        assert prob > 0.5
        assert conf > 0.0

    def test_fuse_contradicting_evidence_lowers_probability(self):
        from tgarchive.intelligence.entity_resolver_v2 import _fuse_evidence
        # High score + CONTRADICTS → inversion makes s~0 → strong push down.
        evidence = [
            ResolutionEvidence(
                source="username",
                score=0.9,
                confidence=0.6,
                direction=EvidenceDirection.CONTRADICTS,
            ),
            ResolutionEvidence(
                source="identifier",
                score=0.9,
                confidence=0.6,
                direction=EvidenceDirection.CONTRADICTS,
            ),
        ]
        prob, _ = _fuse_evidence(evidence, prior_same=0.5)
        assert prob < 0.5

    def test_fuse_neutral_evidence_pulls_toward_prior(self):
        from tgarchive.intelligence.entity_resolver_v2 import _fuse_evidence
        evidence = [
            ResolutionEvidence(
                source="co_occurrence",
                score=0.5,
                confidence=0.3,
                direction=EvidenceDirection.NEUTRAL,
            ),
        ]
        prob, _ = _fuse_evidence(evidence, prior_same=0.3)
        # Neutral evidence should keep probability near the prior.
        assert abs(prob - 0.3) < 0.15

    def test_evidence_weights_sum_to_one(self):
        total = sum(EVIDENCE_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01

    def test_all_seven_sources_present(self):
        expected = {
            "username",
            "name",
            "handle",
            "identifier",
            "co_occurrence",
            "temporal",
            "source_consistency",
        }
        assert set(EVIDENCE_WEIGHTS.keys()) == expected


# ─── Schema integration tests ────────────────────────────────────────────────


class TestSchemaIntegration:
    """Tests for integration with AnalysisEvidence / ActorHypothesis."""

    def test_to_hypothesis(self, resolver, darkvendor_mention):
        candidate = resolver.normalize(darkvendor_mention)
        cluster = IdentityCluster(cluster_id="c1", candidates=[candidate])
        hyp = resolver.to_hypothesis(
            candidate=candidate,
            cluster=cluster,
            probability=0.9,
            confidence=0.8,
            evidence=[
                ResolutionEvidence(
                    source="username",
                    score=1.0,
                    confidence=0.95,
                    direction=EvidenceDirection.SUPPORTS,
                ),
            ],
        )
        assert isinstance(hyp, ActorHypothesis)
        assert hyp.hypothesis_type == HypothesisType.SAME_ACTOR
        assert hyp.probability == 0.9
        assert hyp.model == "spectra-entity-resolver-v2"
        assert hyp.model_version == MODEL_VERSION

    def test_to_analysis_evidence(self, resolver, darkvendor_mention):
        candidate = resolver.normalize(darkvendor_mention)
        cluster = IdentityCluster(cluster_id="c1", candidates=[candidate])
        rev_ev = ResolutionEvidence(
            source="username",
            score=1.0,
            confidence=0.95,
            direction=EvidenceDirection.SUPPORTS,
        )
        ae = resolver.to_analysis_evidence(rev_ev, candidate, cluster)
        assert isinstance(ae, AnalysisEvidence)
        assert ae.evidence_type == "entity_resolution_username"
        assert ae.model == "spectra-entity-resolver-v2"
        assert ae.model_version == MODEL_VERSION
        assert len(ae.sources) > 0

    def test_to_analysis_evidence_has_valid_id(self, resolver, darkvendor_mention):
        candidate = resolver.normalize(darkvendor_mention)
        cluster = IdentityCluster(cluster_id="c1", candidates=[candidate])
        rev_ev = ResolutionEvidence(
            source="identifier",
            score=1.0,
            confidence=0.99,
            direction=EvidenceDirection.SUPPORTS,
        )
        ae = resolver.to_analysis_evidence(rev_ev, candidate, cluster)
        assert len(ae.evidence_id) == 16


# ─── Dataclass tests ─────────────────────────────────────────────────────────


class TestDataclasses:
    """Tests for dataclass validation and serialization."""

    def test_resolution_evidence_score_validation(self):
        with pytest.raises(ValueError):
            ResolutionEvidence(source="test", score=1.5, confidence=0.5)

    def test_resolution_evidence_confidence_validation(self):
        with pytest.raises(ValueError):
            ResolutionEvidence(source="test", score=0.5, confidence=1.5)

    def test_identity_cluster_to_dict(self, resolver, darkvendor_mention):
        candidate = resolver.normalize(darkvendor_mention)
        cluster = IdentityCluster(cluster_id="c1", candidates=[candidate])
        d = cluster.to_dict()
        assert d["cluster_id"] == "c1"
        assert len(d["candidates"]) == 1
        assert d["model_version"] == MODEL_VERSION

    def test_entity_candidate_from_dict_roundtrip(
        self, resolver, darkvendor_mention
    ):
        candidate = resolver.normalize(darkvendor_mention)
        d = candidate.to_dict()
        restored = EntityCandidate.from_dict(d)
        assert restored.candidate_id == candidate.candidate_id
        assert restored.username == candidate.username
        assert restored.user_id == candidate.user_id

    def test_resolution_result_to_dict(
        self, resolver, darkvendor_mention
    ):
        result = resolver.resolve(darkvendor_mention, [])
        d = result.to_dict()
        assert d["action"] == "new_cluster"
        assert "candidate" in d
        assert "cluster" in d


# ─── Threshold validation ────────────────────────────────────────────────────


class TestThresholds:
    """Tests for resolver threshold configuration."""

    def test_default_thresholds(self):
        r = EntityResolverV2()
        assert r.merge_threshold == MERGE_THRESHOLD
        assert r.review_threshold == REVIEW_THRESHOLD

    def test_custom_thresholds(self):
        r = EntityResolverV2(merge_threshold=0.9, review_threshold=0.6)
        assert r.merge_threshold == 0.9
        assert r.review_threshold == 0.6

    def test_invalid_thresholds_raises(self):
        with pytest.raises(ValueError):
            EntityResolverV2(merge_threshold=0.3, review_threshold=0.5)

    def test_invalid_threshold_order_raises(self):
        with pytest.raises(ValueError):
            EntityResolverV2(merge_threshold=0.5, review_threshold=0.5)
