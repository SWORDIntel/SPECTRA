"""Tests for intelligence cross-index, vectors, patterns, conclusions, and network expansion."""

import os
import sqlite3
import pytest
from datetime import datetime, timezone

from tgarchive.db.intelligence_store import IntelligenceStore
from tgarchive.db.schema import SCHEMA_SQL
from tgarchive.intelligence.schema import (
    AnalysisEvidence,
    EvidenceSource,
    EvidenceDirection,
    ActorHypothesis,
    HypothesisType,
    Campaign,
)
from tgarchive.services.cross_index import (
    cross_index,
    cross_index_intelligence,
)
from tgarchive.intelligence.vectors import (
    IntelligenceVectorIndex,
    evidence_to_vector,
    INTELLIGENCE_VECTOR_DIMENSIONS,
)
from tgarchive.intelligence.patterns import (
    Pattern,
    PatternMatcher,
    generate_pattern_id,
)
from tgarchive.intelligence.conclusions import (
    Conclusion,
    draw_conclusions,
    conclude_actor,
    generate_conclusion_id,
)
from tgarchive.intelligence.network_expansion import (
    NetworkMember,
    NetworkExpansionResult,
    expand_network,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database with intelligence data."""
    db = str(tmp_path / "test_intel_xidx.db")
    # Clean up any leftover qdb files
    for ext in [".intelligence.qdb", ".qihse.qdb", ".graph.qdb"]:
        p = db + ext
        if os.path.exists(p):
            os.unlink(p)

    now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
    source = EvidenceSource("message", "telegram:msg:1:10", "messages", 1, now)

    ev1 = AnalysisEvidence(
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
        metadata={"cosine": 0.91},
    )
    ev2 = AnalysisEvidence(
        evidence_id="",
        evidence_type="temporal_overlap",
        subject="telegram:user:123",
        object="telegram:user:456",
        score=0.85,
        confidence=0.72,
        direction=EvidenceDirection.SUPPORTS,
        model="spectra-temporal",
        model_version="1.0.0",
        feature_schema_version="1",
        sources=[source],
        observed_at=now,
        generated_at=now,
    )
    ev3 = AnalysisEvidence(
        evidence_id="",
        evidence_type="threat_indicator",
        subject="telegram:user:123",
        object=None,
        score=7.5,
        confidence=0.80,
        direction=EvidenceDirection.SUPPORTS,
        model="spectra-threat",
        model_version="1.0.0",
        feature_schema_version="1",
        sources=[source],
        observed_at=now,
        generated_at=now,
    )
    ev4 = AnalysisEvidence(
        evidence_id="",
        evidence_type="stylometric_similarity",
        subject="telegram:user:789",
        object="telegram:user:999",
        score=0.88,
        confidence=0.75,
        direction=EvidenceDirection.SUPPORTS,
        model="spectra-stylometry",
        model_version="2.1.0",
        feature_schema_version="3",
        sources=[source],
        observed_at=now,
        generated_at=now,
    )

    hyp = ActorHypothesis(
        hypothesis_id="",
        hypothesis_type=HypothesisType.SAME_ACTOR,
        subject_a="telegram:user:123",
        subject_b="telegram:user:456",
        probability=0.93,
        confidence=0.81,
        supporting_evidence=[ev1.evidence_id, ev2.evidence_id],
        generated_at=now,
        model="spectra-fusion",
        model_version="1.0.0",
    )

    campaign = Campaign(
        campaign_id="",
        name="Op Test",
        actors=["telegram:user:123", "telegram:user:456"],
        channels=["telegram:channel:10"],
        confidence=0.85,
        evidence_ids=[ev1.evidence_id],
        generated_at=now,
    )

    with IntelligenceStore(db) as store:
        store.save_evidence(ev1)
        store.save_evidence(ev2)
        store.save_evidence(ev3)
        store.save_evidence(ev4)
        store.save_hypothesis(hyp)
        store.save_campaign(campaign)

    # Store evidence IDs for tests
    return db, {
        "ev1": ev1.evidence_id,
        "ev2": ev2.evidence_id,
        "ev3": ev3.evidence_id,
        "ev4": ev4.evidence_id,
        "hyp": hyp.hypothesis_id,
        "campaign": campaign.campaign_id,
    }


# ─── Cross-Index Tests ─────────────────────────────────────────────────────


class TestCrossIndexIntelligence:
    def test_finds_evidence_about_entity(self, db_path):
        db, ids = db_path
        result = cross_index_intelligence(db, entity_id=123, entity_type="user")
        assert result["summary"]["evidence_count"] == 3
        evidence_ids = {e["evidence_id"] for e in result["evidence"]}
        assert ids["ev1"] in evidence_ids
        assert ids["ev2"] in evidence_ids
        assert ids["ev3"] in evidence_ids

    def test_finds_evidence_as_object(self, db_path):
        db, ids = db_path
        result = cross_index_intelligence(db, entity_id=456, entity_type="user")
        # ev1 and ev2 have user:456 as object
        assert result["summary"]["evidence_count"] >= 2

    def test_finds_hypotheses(self, db_path):
        db, ids = db_path
        result = cross_index_intelligence(db, entity_id=123, entity_type="user")
        assert result["summary"]["hypothesis_count"] == 1
        assert result["hypotheses"][0]["hypothesis_id"] == ids["hyp"]

    def test_finds_campaigns(self, db_path):
        db, ids = db_path
        result = cross_index_intelligence(db, entity_id=123, entity_type="user")
        assert result["summary"]["campaign_count"] == 1
        assert result["campaigns"][0]["name"] == "Op Test"

    def test_canonical_id_format(self, db_path):
        db, _ = db_path
        result = cross_index_intelligence(db, entity_id=123, entity_type="user")
        assert result["canonical_id"] == "telegram:user:123"

    def test_channel_entity(self, db_path):
        db, _ = db_path
        result = cross_index_intelligence(db, entity_id=10, entity_type="channel")
        assert result["canonical_id"] == "telegram:channel:10"
        # Campaign mentions this channel
        assert result["summary"]["campaign_count"] == 1

    def test_nonexistent_entity_returns_empty(self, db_path):
        db, _ = db_path
        result = cross_index_intelligence(db, entity_id=99999, entity_type="user")
        assert result["summary"]["evidence_count"] == 0
        assert result["summary"]["hypothesis_count"] == 0

    def test_evidence_types_in_summary(self, db_path):
        db, _ = db_path
        result = cross_index_intelligence(db, entity_id=123, entity_type="user")
        assert "stylometric_similarity" in result["summary"]["evidence_types"]
        assert "temporal_overlap" in result["summary"]["evidence_types"]
        assert "threat_indicator" in result["summary"]["evidence_types"]

    def test_evidence_role_field(self, db_path):
        db, _ = db_path
        result = cross_index_intelligence(db, entity_id=123, entity_type="user")
        for ev in result["evidence"]:
            if ev["subject"] == "telegram:user:123":
                assert ev["role"] == "subject"
            else:
                assert ev["role"] == "object"

    def test_cross_index_includes_intelligence(self, db_path):
        """The main cross_index() should include intelligence data."""
        db, _ = db_path
        # cross_index requires a messages/users table, so create a minimal user
        import sqlite3
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO users (id, username) VALUES (123, 'testuser')"
            )
            conn.commit()

        result = cross_index(db, entity_id=123, entity_type="user")
        assert "intelligence" in result
        assert result["summary"]["intelligence"]["evidence_count"] == 3


# ─── Vector Tests ──────────────────────────────────────────────────────────


class TestIntelligenceVectors:
    def test_vector_dimensions(self):
        assert INTELLIGENCE_VECTOR_DIMENSIONS == 64

    def test_evidence_to_vector_dimensions(self, db_path):
        db, ids = db_path
        from tgarchive.db.intelligence_store import IntelligenceStore

        with IntelligenceStore(db) as store:
            rows = store.query_evidence(limit=100)
            ev_row = rows[0]
            from tgarchive.intelligence.schema import (
                AnalysisEvidence,
                EvidenceSource,
                EvidenceDirection,
            )
            import json
            sources = [EvidenceSource.from_dict(s) for s in json.loads(ev_row["sources_json"])]
            ev = AnalysisEvidence(
                evidence_id=ev_row["evidence_id"],
                evidence_type=ev_row["evidence_type"],
                subject=ev_row["subject"],
                object=ev_row["object"],
                score=ev_row["score"],
                confidence=ev_row["confidence"],
                direction=EvidenceDirection(ev_row["direction"]),
                model=ev_row["model"],
                model_version=ev_row["model_version"],
                feature_schema_version="1",
                sources=sources,
                observed_at=datetime.now(timezone.utc),
                generated_at=datetime.now(timezone.utc),
            )
            vec = evidence_to_vector(ev)
            assert len(vec) == 64

    def test_evidence_to_vector_normalized(self):
        """Vectors should be L2-normalized (unit length)."""
        now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
        source = EvidenceSource("message", "telegram:msg:1:10", "messages", 1, now)
        ev = AnalysisEvidence(
            evidence_id="",
            evidence_type="test_type",
            subject="telegram:user:1",
            object="telegram:user:2",
            score=0.5,
            confidence=0.5,
            direction=EvidenceDirection.SUPPORTS,
            model="test-model",
            model_version="1.0",
            feature_schema_version="1",
            sources=[source],
            observed_at=now,
            generated_at=now,
        )
        vec = evidence_to_vector(ev)
        norm = sum(v * v for v in vec) ** 0.5
        assert abs(norm - 1.0) < 0.01

    def test_vector_index_upsert_and_search(self, tmp_path):
        db = str(tmp_path / "test_vec.db")
        for ext in [".intelligence.qdb"]:
            p = db + ext
            if os.path.exists(p):
                os.unlink(p)

        now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
        source = EvidenceSource("message", "telegram:msg:1:10", "messages", 1, now)

        ev1 = AnalysisEvidence(
            evidence_id="",
            evidence_type="stylometric_similarity",
            subject="telegram:user:1",
            object="telegram:user:2",
            score=0.9,
            confidence=0.8,
            direction=EvidenceDirection.SUPPORTS,
            model="spectra-stylometry",
            model_version="2.1.0",
            feature_schema_version="3",
            sources=[source],
            observed_at=now,
            generated_at=now,
        )
        ev2 = AnalysisEvidence(
            evidence_id="",
            evidence_type="stylometric_similarity",
            subject="telegram:user:3",
            object="telegram:user:4",
            score=0.88,
            confidence=0.75,
            direction=EvidenceDirection.SUPPORTS,
            model="spectra-stylometry",
            model_version="2.1.0",
            feature_schema_version="3",
            sources=[source],
            observed_at=now,
            generated_at=now,
        )

        with IntelligenceVectorIndex(db) as idx:
            idx.upsert_evidence(ev1, sequence_id=1)
            idx.upsert_evidence(ev2, sequence_id=2)
            results = idx.search_similar(ev1, limit=5)
            assert len(results) >= 1
            # The most similar should be ev1 itself (id=1) with score ~1.0
            top = results[0]
            assert top["id"] == 1
            assert top["score"] > 0.99

    def test_different_evidence_types_have_different_vectors(self):
        """Evidence with different types should produce different vectors."""
        now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
        source = EvidenceSource("message", "telegram:msg:1:10", "messages", 1, now)
        common = dict(
            evidence_id="",
            subject="telegram:user:1",
            object="telegram:user:2",
            score=0.5,
            confidence=0.5,
            direction=EvidenceDirection.SUPPORTS,
            model="test",
            model_version="1.0",
            feature_schema_version="1",
            sources=[source],
            observed_at=now,
            generated_at=now,
        )
        ev_a = AnalysisEvidence(evidence_type="type_a", **common)
        ev_b = AnalysisEvidence(evidence_type="type_b", **common)
        vec_a = evidence_to_vector(ev_a)
        vec_b = evidence_to_vector(ev_b)
        # Vectors should differ
        diff = sum(abs(a - b) for a, b in zip(vec_a, vec_b))
        assert diff > 0.01


# ─── Pattern Matching Tests ────────────────────────────────────────────────


class TestPatternMatching:
    def test_detect_recurring_patterns(self, db_path):
        db, _ = db_path
        matcher = PatternMatcher(db)
        try:
            # stylometric_similarity appears for user:123 and user:789
            patterns = matcher.detect_recurring_patterns(min_cluster_size=2)
            assert len(patterns) >= 1
            stylo_patterns = [p for p in patterns if "stylometric" in p.description]
            assert len(stylo_patterns) >= 1
            assert stylo_patterns[0].frequency >= 2
        finally:
            matcher.close()

    def test_cluster_evidence_by_type(self, db_path):
        db, _ = db_path
        matcher = PatternMatcher(db)
        try:
            clusters = matcher.cluster_evidence_by_type()
            assert len(clusters) >= 1
            stylo = [c for c in clusters if c["evidence_type"] == "stylometric_similarity"]
            assert len(stylo) == 1
            assert stylo[0]["count"] == 2
        finally:
            matcher.close()

    def test_cluster_evidence_filtered_by_entity(self, db_path):
        db, _ = db_path
        matcher = PatternMatcher(db)
        try:
            clusters = matcher.cluster_evidence_by_type("telegram:user:123")
            # user:123 has stylometric_similarity, temporal_overlap, threat_indicator
            types = {c["evidence_type"] for c in clusters}
            assert "stylometric_similarity" in types
            assert "temporal_overlap" in types
            assert "threat_indicator" in types
        finally:
            matcher.close()

    def test_find_similar_evidence(self, db_path):
        db, _ = db_path
        matcher = PatternMatcher(db)
        try:
            now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
            source = EvidenceSource("message", "telegram:msg:1:10", "messages", 1, now)
            target = AnalysisEvidence(
                evidence_id="",
                evidence_type="stylometric_similarity",
                subject="telegram:user:1",
                object="telegram:user:2",
                score=0.9,
                confidence=0.8,
                direction=EvidenceDirection.SUPPORTS,
                model="spectra-stylometry",
                model_version="2.1.0",
                feature_schema_version="3",
                sources=[source],
                observed_at=now,
                generated_at=now,
            )
            similar = matcher.find_similar_evidence(target, limit=10)
            assert len(similar) >= 1
            assert all(s["similarity"] >= 0 for s in similar)
        finally:
            matcher.close()

    def test_find_evidence_clusters(self, db_path):
        db, _ = db_path
        matcher = PatternMatcher(db)
        try:
            clusters = matcher.find_evidence_clusters("telegram:user:123")
            assert len(clusters) >= 1
            # The cluster should include user:123 and user:456 (connected via evidence)
            all_entities = set()
            for c in clusters:
                all_entities.update(c["entities"])
            assert "telegram:user:123" in all_entities
        finally:
            matcher.close()

    def test_pattern_id_deterministic(self):
        pid1 = generate_pattern_id("test", ["a", "b"], ["e1", "e2"])
        pid2 = generate_pattern_id("test", ["b", "a"], ["e2", "e1"])
        assert pid1 == pid2
        assert len(pid1) == 16

    def test_pattern_to_dict_roundtrip(self):
        p = Pattern(
            pattern_id="abc123",
            pattern_type="test",
            description="Test pattern",
            entities=["a", "b"],
            evidence_ids=["e1", "e2"],
            frequency=2,
            confidence=0.8,
            metadata={"key": "value"},
        )
        d = p.to_dict()
        p2 = Pattern.from_dict(d)
        assert p2.pattern_id == p.pattern_id
        assert p2.pattern_type == p.pattern_type
        assert p2.entities == p.entities
        assert p2.evidence_ids == p.evidence_ids
        assert p2.frequency == p.frequency
        assert p2.confidence == p.confidence


# ─── Conclusion Engine Tests ───────────────────────────────────────────────


class TestConclusionEngine:
    def test_draw_conclusions_returns_conclusions(self, db_path):
        db, _ = db_path
        conclusions = draw_conclusions(db, entity_id=123, entity_type="user")
        assert len(conclusions) >= 1
        assert all(isinstance(c, Conclusion) for c in conclusions)

    def test_conclusion_probability_in_range(self, db_path):
        db, _ = db_path
        conclusions = draw_conclusions(db, entity_id=123, entity_type="user")
        for c in conclusions:
            assert 0.0 <= c.probability <= 1.0
            assert 0.0 <= c.confidence <= 1.0

    def test_conclusion_has_supporting_evidence(self, db_path):
        db, ids = db_path
        conclusions = draw_conclusions(db, entity_id=123, entity_type="user")
        assert len(conclusions) >= 1
        c = conclusions[0]
        assert len(c.supporting_evidence) >= 1

    def test_conclusion_type_detected(self, db_path):
        db, _ = db_path
        conclusions = draw_conclusions(db, entity_id=123, entity_type="user")
        # With same_actor hypothesis, should be actor_identity
        assert any("actor" in c.conclusion_type for c in conclusions)

    def test_conclusion_evidence_breakdown(self, db_path):
        db, _ = db_path
        conclusions = draw_conclusions(db, entity_id=123, entity_type="user")
        c = conclusions[0]
        assert "stylometric_similarity" in c.evidence_breakdown
        assert c.evidence_breakdown["stylometric_similarity"] >= 1

    def test_conclusion_to_dict(self, db_path):
        db, _ = db_path
        conclusions = draw_conclusions(db, entity_id=123, entity_type="user")
        d = conclusions[0].to_dict()
        assert "conclusion_id" in d
        assert "probability" in d
        assert "confidence" in d
        assert "supporting_evidence" in d
        assert "evidence_breakdown" in d

    def test_conclude_actor(self, db_path):
        db, _ = db_path
        result = conclude_actor(db, 123)
        assert result["user_id"] == 123
        assert result["canonical_id"] == "telegram:user:123"
        assert len(result["conclusions"]) >= 1
        assert len(result["same_actor_hypotheses"]) >= 1
        assert len(result["campaign_memberships"]) >= 1

    def test_conclusion_id_deterministic(self):
        cid1 = generate_conclusion_id("telegram:user:1", "actor_identity", ["e1"], ["e2"])
        cid2 = generate_conclusion_id("telegram:user:1", "actor_identity", ["e1"], ["e2"])
        assert cid1 == cid2
        assert len(cid1) == 16

    def test_conclusion_id_different_for_different_inputs(self):
        cid1 = generate_conclusion_id("telegram:user:1", "actor_identity", ["e1"], [])
        cid2 = generate_conclusion_id("telegram:user:2", "actor_identity", ["e1"], [])
        assert cid1 != cid2

    def test_no_conclusions_for_empty_entity(self, db_path):
        db, _ = db_path
        conclusions = draw_conclusions(db, entity_id=99999, entity_type="user")
        assert len(conclusions) == 0


# ─── Network Expansion Tests ───────────────────────────────────────────────


@pytest.fixture
def network_db(tmp_path):
    """Create a DB with leaders, contacts, and hypothesis links."""
    db = str(tmp_path / "test_network_expand.db")
    for ext in [".intelligence.qdb", ".qihse.qdb", ".graph.qdb"]:
        p = db + ext
        if os.path.exists(p):
            os.unlink(p)

    now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)

    # Create schema + users + messages
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_SQL)
    for uid, uname in [(100, "leader_a"), (200, "leader_b"),
                       (300, "contact_c"), (400, "contact_d"), (500, "contact_e")]:
        conn.execute("INSERT OR REPLACE INTO users (id, username) VALUES (?, ?)", (uid, uname))
    # Leader 100 interacts with 300 (10 times) and 400 (5 times)
    for i in range(10):
        conn.execute(
            "INSERT INTO messages (id, type, date, content, reply_to, user_id) VALUES (?,?,?,?,?,?)",
            (i + 1, "text", "2026-01-01 12:00:00", "msg", i + 100, 300),
        )
        conn.execute(
            "INSERT INTO messages (id, type, date, content, reply_to, user_id) VALUES (?,?,?,?,?,?)",
            (i + 100, "text", "2026-01-01 12:01:00", "reply", i + 1, 100),
        )
    for i in range(5):
        conn.execute(
            "INSERT INTO messages (id, type, date, content, reply_to, user_id) VALUES (?,?,?,?,?,?)",
            (i + 200, "text", "2026-01-01 12:02:00", "msg", i + 300, 400),
        )
        conn.execute(
            "INSERT INTO messages (id, type, date, content, reply_to, user_id) VALUES (?,?,?,?,?,?)",
            (i + 300, "text", "2026-01-01 12:03:00", "reply", i + 200, 100),
        )
    # Leader 200 interacts with 500 (5 times)
    for i in range(5):
        conn.execute(
            "INSERT INTO messages (id, type, date, content, reply_to, user_id) VALUES (?,?,?,?,?,?)",
            (i + 400, "text", "2026-01-01 12:04:00", "msg", i + 500, 500),
        )
        conn.execute(
            "INSERT INTO messages (id, type, date, content, reply_to, user_id) VALUES (?,?,?,?,?,?)",
            (i + 500, "text", "2026-01-01 12:05:00", "reply", i + 400, 200),
        )
    conn.commit()
    conn.close()

    # Add hypothesis linking leader 100 to contact 300
    source = EvidenceSource("message", "telegram:msg:1:10", "messages", 1, now)
    ev = AnalysisEvidence(
        evidence_id="",
        evidence_type="stylometric_similarity",
        subject="telegram:user:100",
        object="telegram:user:300",
        score=0.92,
        confidence=0.85,
        direction=EvidenceDirection.SUPPORTS,
        model="spectra-stylometry",
        model_version="2.1.0",
        feature_schema_version="3",
        sources=[source],
        observed_at=now,
        generated_at=now,
    )
    hyp = ActorHypothesis(
        hypothesis_id="",
        hypothesis_type=HypothesisType.SAME_ACTOR,
        subject_a="telegram:user:100",
        subject_b="telegram:user:300",
        probability=0.88,
        confidence=0.80,
        supporting_evidence=[ev.evidence_id],
        generated_at=now,
        model="spectra-fusion",
        model_version="1.0.0",
    )
    with IntelligenceStore(db) as store:
        store.save_evidence(ev)
        store.save_hypothesis(hyp)

    return db


class TestNetworkExpansion:
    def test_expand_returns_leaders(self, network_db):
        result = expand_network(
            network_db, leader_ids=[100, 200],
            campaign_name="Test", min_probability=0.5,
            auto_add_to_campaign=False,
        )
        assert len(result.leaders) == 2
        leader_ids = {m.user_id for m in result.leaders}
        assert 100 in leader_ids
        assert 200 in leader_ids

    def test_expand_discovers_contacts(self, network_db):
        result = expand_network(
            network_db, leader_ids=[100, 200],
            campaign_name="Test", min_probability=0.3,
            min_interactions=3,
            auto_add_to_campaign=False,
        )
        # Should discover users 300, 400, 500
        discovered_ids = {m.user_id for m in result.discovered_members}
        assert 300 in discovered_ids

    def test_hypothesis_link_boosts_probability(self, network_db):
        result = expand_network(
            network_db, leader_ids=[100],
            campaign_name="Test", min_probability=0.0,
            min_interactions=3,
            auto_add_to_campaign=False,
        )
        # User 300 has both hypothesis + contact evidence → higher probability
        member_300 = next(m for m in result.discovered_members if m.user_id == 300)
        member_400 = next(m for m in result.discovered_members if m.user_id == 400)
        assert member_300.probability > member_400.probability
        assert "hypothesis_link" in member_300.evidence_sources
        assert "contact_network" in member_300.evidence_sources

    def test_min_probability_filters(self, network_db):
        result = expand_network(
            network_db, leader_ids=[100, 200],
            campaign_name="Test", min_probability=0.9,
            auto_add_to_campaign=False,
        )
        # With 0.9 threshold, only hypothesis-linked members pass
        # User 300 has P~0.77, so might not pass at 0.9
        assert all(m.probability >= 0.9 for m in result.discovered_members)

    def test_campaign_saved_to_db(self, network_db):
        result = expand_network(
            network_db, leader_ids=[100, 200],
            campaign_name="Op TestCampaign", min_probability=0.3,
            min_interactions=3,
            auto_add_to_campaign=True,
        )
        # Verify campaign was saved
        with IntelligenceStore(network_db) as store:
            campaigns = store.query_campaigns(name="Op TestCampaign")
        assert len(campaigns) >= 1

    def test_dry_run_doesnt_save(self, network_db):
        expand_network(
            network_db, leader_ids=[100],
            campaign_name="DryRunTest", min_probability=0.3,
            auto_add_to_campaign=False,
        )
        with IntelligenceStore(network_db) as store:
            campaigns = store.query_campaigns(name="DryRunTest")
        assert len(campaigns) == 0

    def test_graph_edges_built(self, network_db):
        result = expand_network(
            network_db, leader_ids=[100, 200],
            campaign_name="Test", min_probability=0.0,
            min_interactions=3,
            auto_add_to_campaign=False,
        )
        assert len(result.graph["edges"]) > 0
        # Should have edges from leaders to contacts
        edge_types = {e["type"] for e in result.graph["edges"]}
        assert "reply_to" in edge_types or "replies_to_target" in edge_types or "leader_replies_to" in edge_types

    def test_summary_has_counts(self, network_db):
        result = expand_network(
            network_db, leader_ids=[100, 200],
            campaign_name="Test", min_probability=0.0,
            min_interactions=3,
            auto_add_to_campaign=False,
        )
        s = result.summary
        assert s["leader_count"] == 2
        assert s["discovered_count"] >= 1
        assert "evidence_sources_used" in s

    def test_to_dict_serialization(self, network_db):
        result = expand_network(
            network_db, leader_ids=[100],
            campaign_name="Test", min_probability=0.5,
            auto_add_to_campaign=False,
        )
        d = result.to_dict()
        assert "campaign_id" in d
        assert "leaders" in d
        assert "discovered_members" in d
        assert "graph" in d
        assert "summary" in d

    def test_nonexistent_db_raises(self):
        with pytest.raises(FileNotFoundError):
            expand_network("/nonexistent/path.db", leader_ids=[1])
