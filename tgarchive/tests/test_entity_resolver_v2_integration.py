"""
Integration tests for EntityResolverV2 → IntelligenceStore → Conclusions pipeline.

Verifies that:
- identity_clusters / identity_cluster_members tables exist after apply_migrations()
- IntelligenceStore.save_identity_cluster() persists clusters + members
- query_identity_clusters() finds clusters by entity identifier
- draw_conclusions() includes cluster info when EntityResolverV2 runs
- provenance nodes are persisted to spectra.db (not a sidecar)
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tgarchive.db.intelligence_store import IntelligenceStore
from tgarchive.db.schema import SCHEMA_SQL, apply_migrations
from tgarchive.intelligence.entity_resolver_v2 import (
    MODEL_VERSION,
    EntityCandidate,
    EntityResolverV2,
    IdentityCluster,
    Mention,
)
from tgarchive.intelligence.provenance_graph import (
    ProvenanceGraph,
    ProvenanceNode,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path) -> Path:
    """A fresh spectra.db with the full schema applied."""
    p = tmp_path / "spectra.db"
    conn = sqlite3.connect(str(p))
    conn.executescript(SCHEMA_SQL)
    apply_migrations(conn)
    conn.commit()
    conn.close()
    return p


@pytest.fixture
def store(db_path) -> IntelligenceStore:
    """An IntelligenceStore backed by the fresh db."""
    s = IntelligenceStore(db_path)
    yield s
    s.close()


@pytest.fixture
def resolver() -> EntityResolverV2:
    return EntityResolverV2()


@pytest.fixture
def base_time() -> datetime:
    return datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc)


@pytest.fixture
def sample_cluster(base_time) -> IdentityCluster:
    """A cluster with two candidates (same actor, different sources)."""
    c1 = EntityCandidate(
        candidate_id="cand_a",
        username="darkvendor",
        handle="@darkvendor",
        user_id=12345,
        display_name="Dark Vendor",
        source_id="telegram:user:12345",
    )
    c2 = EntityCandidate(
        candidate_id="cand_b",
        username="darkvendor",
        handle="@darkvendor",
        user_id=12345,
        source_id="telegram:msg:100:1",
    )
    return IdentityCluster(
        cluster_id="cluster_abc123",
        candidates=[c1, c2],
        confidence=0.92,
        model_version=MODEL_VERSION,
    )


# ─── Schema tests ────────────────────────────────────────────────────────────


class TestSchemaTables:
    """Verify the new tables exist after schema application."""

    def test_identity_clusters_table_exists(self, db_path):
        conn = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "identity_clusters" in tables

    def test_identity_cluster_members_table_exists(self, db_path):
        conn = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "identity_cluster_members" in tables

    def test_provenance_nodes_table_exists(self, db_path):
        conn = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "provenance_nodes" in tables

    def test_identity_clusters_columns(self, db_path):
        conn = sqlite3.connect(str(db_path))
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(identity_clusters)").fetchall()
        }
        conn.close()
        assert {"cluster_id", "confidence", "model_version", "created_at", "updated_at"} <= cols

    def test_identity_cluster_members_columns(self, db_path):
        conn = sqlite3.connect(str(db_path))
        cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(identity_cluster_members)"
            ).fetchall()
        }
        conn.close()
        assert {
            "cluster_id",
            "candidate_type",
            "candidate_value",
            "candidate_id",
            "evidence_score",
        } <= cols

    def test_provenance_nodes_columns(self, db_path):
        conn = sqlite3.connect(str(db_path))
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(provenance_nodes)").fetchall()
        }
        conn.close()
        assert {
            "node_id",
            "node_type",
            "algorithm",
            "version",
            "parameters_json",
            "timestamp",
            "input_ids_json",
            "input_hashes_json",
            "output_id",
            "confidence",
        } <= cols

    def test_apply_migrations_idempotent(self, db_path):
        """Calling apply_migrations again should not error."""
        conn = sqlite3.connect(str(db_path))
        apply_migrations(conn)
        # Tables should still exist.
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "identity_clusters" in tables
        assert "provenance_nodes" in tables


# ─── IntelligenceStore.save_identity_cluster tests ───────────────────────────


class TestSaveIdentityCluster:
    """Tests for IntelligenceStore.save_identity_cluster()."""

    def test_save_returns_cluster_id(self, store, sample_cluster):
        cid = store.save_identity_cluster(sample_cluster)
        assert cid == sample_cluster.cluster_id

    def test_cluster_row_persisted(self, store, sample_cluster):
        store.save_identity_cluster(sample_cluster)
        conn = store._connection()
        row = conn.execute(
            "SELECT cluster_id, confidence, model_version FROM identity_clusters WHERE cluster_id = ?",
            (sample_cluster.cluster_id,),
        ).fetchone()
        assert row is not None
        assert row["cluster_id"] == sample_cluster.cluster_id
        assert abs(row["confidence"] - 0.92) < 0.001
        assert row["model_version"] == MODEL_VERSION

    def test_members_persisted(self, store, sample_cluster):
        store.save_identity_cluster(sample_cluster)
        conn = store._connection()
        rows = conn.execute(
            "SELECT candidate_type, candidate_value, candidate_id FROM identity_cluster_members WHERE cluster_id = ?",
            (sample_cluster.cluster_id,),
        ).fetchall()
        # Each candidate has multiple identifiers (username, handle, user_id, etc.)
        assert len(rows) > 0
        values = {r["candidate_value"] for r in rows}
        assert "darkvendor" in values  # username
        assert "@darkvendor" in values  # handle
        assert "12345" in values  # user_id

    def test_save_is_idempotent(self, store, sample_cluster):
        """Saving the same cluster twice should not duplicate rows."""
        store.save_identity_cluster(sample_cluster)
        store.save_identity_cluster(sample_cluster)
        conn = store._connection()
        count = conn.execute(
            "SELECT COUNT(*) FROM identity_clusters WHERE cluster_id = ?",
            (sample_cluster.cluster_id,),
        ).fetchone()[0]
        assert count == 1

    def test_save_appends_to_outbox(self, store, sample_cluster):
        store.save_identity_cluster(sample_cluster)
        conn = store._connection()
        row = conn.execute(
            "SELECT COUNT(*) FROM index_outbox WHERE source_table = 'identity_clusters' AND source_key = ?",
            (sample_cluster.cluster_id,),
        ).fetchone()
        assert row[0] >= 1


# ─── IntelligenceStore.query_identity_clusters tests ─────────────────────────


class TestQueryIdentityClusters:
    """Tests for IntelligenceStore.query_identity_clusters()."""

    def test_query_by_user_id(self, store, sample_cluster):
        store.save_identity_cluster(sample_cluster)
        results = store.query_identity_clusters("12345")
        assert len(results) >= 1
        assert results[0]["cluster_id"] == sample_cluster.cluster_id
        assert len(results[0]["members"]) > 0

    def test_query_by_username(self, store, sample_cluster):
        store.save_identity_cluster(sample_cluster)
        results = store.query_identity_clusters("darkvendor")
        assert len(results) >= 1
        assert results[0]["cluster_id"] == sample_cluster.cluster_id

    def test_query_by_handle(self, store, sample_cluster):
        store.save_identity_cluster(sample_cluster)
        results = store.query_identity_clusters("@darkvendor")
        assert len(results) >= 1

    def test_query_no_match_returns_empty(self, store, sample_cluster):
        store.save_identity_cluster(sample_cluster)
        results = store.query_identity_clusters("nonexistent_user")
        assert results == []

    def test_query_includes_members(self, store, sample_cluster):
        store.save_identity_cluster(sample_cluster)
        results = store.query_identity_clusters("12345")
        members = results[0]["members"]
        member_types = {m["candidate_type"] for m in members}
        assert "username" in member_types
        assert "user_id" in member_types

    def test_query_empty_db_returns_empty(self, store):
        results = store.query_identity_clusters("12345")
        assert results == []


# ─── IntelligenceStore.save_provenance_node tests ────────────────────────────


class TestSaveProvenanceNode:
    """Tests for IntelligenceStore.save_provenance_node()."""

    def test_save_returns_node_id(self, store):
        node = ProvenanceNode(
            node_id="prov_001",
            node_type="conclusion",
            algorithm="entity_resolver_v2",
            version="2.0.0",
            output_id="conclusion:abc",
            confidence=0.9,
        )
        nid = store.save_provenance_node(node)
        assert nid == "prov_001"

    def test_node_row_persisted(self, store):
        node = ProvenanceNode(
            node_id="prov_002",
            node_type="evidence",
            algorithm="entity_resolver_v2",
            version="2.0.0",
            parameters={"threshold": 0.85},
            input_ids=["msg:1", "msg:2"],
            input_hashes=["h1", "h2"],
            output_id="evidence:ev1",
            confidence=0.92,
        )
        store.save_provenance_node(node)
        conn = store._connection()
        row = conn.execute(
            "SELECT * FROM provenance_nodes WHERE node_id = ?",
            ("prov_002",),
        ).fetchone()
        assert row is not None
        assert row["node_type"] == "evidence"
        assert row["algorithm"] == "entity_resolver_v2"
        assert row["output_id"] == "evidence:ev1"

    def test_provenance_appends_to_outbox(self, store):
        node = ProvenanceNode(
            node_id="prov_003",
            node_type="conclusion",
            algorithm="test_algo",
            version="1.0",
            output_id="out:1",
            confidence=0.5,
        )
        store.save_provenance_node(node)
        conn = store._connection()
        count = conn.execute(
            "SELECT COUNT(*) FROM index_outbox WHERE source_table = 'provenance_nodes' AND source_key = ?",
            ("prov_003",),
        ).fetchone()[0]
        assert count >= 1


# ─── IntelligenceStore.query_provenance tests ────────────────────────────────


class TestQueryProvenance:
    """Tests for IntelligenceStore.query_provenance()."""

    def test_query_returns_chain(self, store):
        # Create a simple chain: source → evidence → conclusion
        n1 = ProvenanceNode(
            node_id="n1",
            node_type="source_event",
            algorithm="crawler",
            version="1.0",
            input_ids=[],
            output_id="source:1",
            confidence=1.0,
        )
        n2 = ProvenanceNode(
            node_id="n2",
            node_type="evidence",
            algorithm="resolver",
            version="2.0",
            input_ids=["source:1"],
            output_id="evidence:1",
            confidence=0.9,
        )
        n3 = ProvenanceNode(
            node_id="n3",
            node_type="conclusion",
            algorithm="fusion",
            version="1.0",
            input_ids=["evidence:1"],
            output_id="conclusion:1",
            confidence=0.85,
        )
        store.save_provenance_node(n1)
        store.save_provenance_node(n2)
        store.save_provenance_node(n3)

        chain = store.query_provenance("conclusion:1")
        assert len(chain) == 3
        # First node should be the conclusion (newest).
        assert chain[0]["output_id"] == "conclusion:1"
        # Should include the source event.
        output_ids = [n["output_id"] for n in chain]
        assert "source:1" in output_ids

    def test_query_unknown_object_returns_empty(self, store):
        chain = store.query_provenance("nonexistent")
        assert chain == []

    def test_query_includes_parameters(self, store):
        node = ProvenanceNode(
            node_id="n_params",
            node_type="evidence",
            algorithm="test",
            version="1.0",
            parameters={"key": "value", "threshold": 0.9},
            output_id="out:params",
            confidence=0.7,
        )
        store.save_provenance_node(node)
        chain = store.query_provenance("out:params")
        assert len(chain) == 1
        assert chain[0]["parameters"]["key"] == "value"
        assert chain[0]["parameters"]["threshold"] == 0.9


# ─── ProvenanceGraph connection-mode tests ───────────────────────────────────


class TestProvenanceGraphConnection:
    """Tests for ProvenanceGraph using an existing sqlite3 connection."""

    def test_from_connection_persists(self, db_path):
        conn = sqlite3.connect(str(db_path))
        graph = ProvenanceGraph.from_connection(conn)
        node = graph.record_derivation(
            output_id="ev:1",
            input_ids=["msg:1"],
            algorithm="entity_resolver_v2",
            version="2.0.0",
            confidence=0.9,
        )
        conn.commit()
        # Verify the node was written to the DB via the connection.
        row = conn.execute(
            "SELECT node_id, output_id, algorithm FROM provenance_nodes WHERE output_id = ?",
            ("ev:1",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == node.node_id
        assert row[1] == "ev:1"
        assert row[2] == "entity_resolver_v2"

    def test_from_connection_loads_existing(self, db_path):
        conn = sqlite3.connect(str(db_path))
        # Write a node directly.
        graph1 = ProvenanceGraph.from_connection(conn)
        graph1.record_derivation(
            output_id="ev:2",
            input_ids=["m1"],
            algorithm="algo",
            version="1.0",
            confidence=0.8,
        )
        conn.commit()

        # New graph on same connection should load existing nodes.
        graph2 = ProvenanceGraph.from_connection(conn)
        assert graph2.node_count >= 1
        chain = graph2.trace_provenance("ev:2")
        assert len(chain) >= 1
        conn.close()

    def test_in_memory_still_works(self):
        """Backward compat: no db_path and no connection = in-memory."""
        graph = ProvenanceGraph()
        graph.record_derivation(
            output_id="ev:3",
            input_ids=["m1"],
            algorithm="algo",
            version="1.0",
            confidence=0.5,
        )
        assert graph.node_count == 1
        assert graph._db_path is None
        assert graph._connection is None


# ─── draw_conclusions integration tests ──────────────────────────────────────


class TestDrawConclusionsIntegration:
    """Tests that draw_conclusions() includes cluster info from EntityResolverV2."""

    def _setup_evidence_db(self, db_path: Path, user_id: int = 12345):
        """Set up a minimal DB with evidence so draw_conclusions produces output."""
        from tgarchive.intelligence.schema import (
            AnalysisEvidence,
            EvidenceDirection,
            EvidenceSource,
        )
        from tgarchive.db.intelligence_store import IntelligenceStore

        store = IntelligenceStore(db_path)
        now = datetime.now(timezone.utc)
        canonical = f"telegram:user:{user_id}"
        ev = AnalysisEvidence(
            evidence_id="",
            evidence_type="threat_indicator",
            subject=canonical,
            object="infrastructure:darkweb.onion",
            score=0.8,
            confidence=0.9,
            direction=EvidenceDirection.SUPPORTS,
            model="test_model",
            model_version="1.0.0",
            feature_schema_version="1",
            sources=[
                EvidenceSource(
                    source_type="message",
                    source_id="telegram:msg:1:1",
                    source_table="messages",
                    source_row_id=1,
                    retrieved_at=now,
                )
            ],
            observed_at=now,
            generated_at=now,
            metadata={"indicator": "darkweb_link"},
        )
        store.save_evidence(ev)
        store.close()
        return canonical

    def test_draw_conclusions_includes_cluster_info(self, db_path):
        """draw_conclusions should include identity_clusters in metadata."""
        self._setup_evidence_db(db_path, user_id=12345)

        from tgarchive.intelligence.conclusions import draw_conclusions

        conclusions = draw_conclusions(
            db_path,
            entity_id=12345,
            entity_type="user",
        )
        assert len(conclusions) >= 1
        # The primary conclusion should have identity_clusters in metadata.
        primary = conclusions[0]
        assert "identity_clusters" in primary.metadata
        clusters = primary.metadata["identity_clusters"]
        assert isinstance(clusters, list)
        assert len(clusters) >= 1
        assert "cluster_id" in clusters[0]
        assert "action" in clusters[0]

    def test_draw_conclusions_persists_cluster(self, db_path):
        """draw_conclusions should persist the cluster to the DB."""
        self._setup_evidence_db(db_path, user_id=67890)

        from tgarchive.intelligence.conclusions import draw_conclusions

        draw_conclusions(db_path, entity_id=67890, entity_type="user")

        # Verify a cluster was persisted.
        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM identity_clusters"
        ).fetchone()[0]
        conn.close()
        assert count >= 1

    def test_draw_conclusions_persists_provenance(self, db_path):
        """draw_conclusions should persist provenance nodes to spectra.db."""
        self._setup_evidence_db(db_path, user_id=11111)

        from tgarchive.intelligence.conclusions import draw_conclusions

        draw_conclusions(db_path, entity_id=11111, entity_type="user")

        # Verify provenance nodes were persisted.
        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM provenance_nodes"
        ).fetchone()[0]
        conn.close()
        assert count >= 1

    def test_draw_conclusions_cluster_queryable_after(self, db_path):
        """After draw_conclusions, the cluster should be queryable."""
        self._setup_evidence_db(db_path, user_id=22222)

        from tgarchive.intelligence.conclusions import draw_conclusions

        draw_conclusions(db_path, entity_id=22222, entity_type="user")

        store = IntelligenceStore(db_path)
        results = store.query_identity_clusters("22222")
        store.close()
        assert len(results) >= 1

    def test_draw_conclusions_no_evidence_returns_empty(self, db_path):
        """With no evidence, draw_conclusions returns empty list."""
        from tgarchive.intelligence.conclusions import draw_conclusions

        conclusions = draw_conclusions(
            db_path,
            entity_id=99999,
            entity_type="user",
        )
        assert conclusions == []

    def test_draw_conclusions_provenance_in_spectra_db(self, db_path):
        """Provenance must be in spectra.db, not a sidecar file."""
        self._setup_evidence_db(db_path, user_id=33333)

        from tgarchive.intelligence.conclusions import draw_conclusions

        draw_conclusions(db_path, entity_id=33333, entity_type="user")

        # No sidecar provenance DB should be created.
        sidecar = db_path.parent / "provenance.db"
        assert not sidecar.exists()

        # Provenance should be in spectra.db.
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT algorithm FROM provenance_nodes"
        ).fetchall()
        conn.close()
        algorithms = [r[0] for r in rows]
        assert "entity_resolver_v2" in algorithms
