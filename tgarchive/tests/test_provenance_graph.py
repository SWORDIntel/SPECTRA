"""
Tests for the ProvenanceGraph — provenance chain tracking.

Covers node creation, backward tracing, human-readable explanations,
SQLite persistence, and replayability.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

import pytest

from tgarchive.intelligence.provenance_graph import (
    NODE_TYPES,
    ProvenanceGraph,
    ProvenanceNode,
    SCHEMA_VERSION,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def graph() -> ProvenanceGraph:
    """A fresh in-memory provenance graph."""
    return ProvenanceGraph()


@pytest.fixture
def tmp_db_path(tmp_path) -> str:
    """A temporary SQLite database path."""
    return str(tmp_path / "test_provenance.db")


@pytest.fixture
def chained_graph(graph: ProvenanceGraph) -> ProvenanceGraph:
    """A graph with a multi-step derivation chain.

    Chain:
        source_event:msg1 → entity:user1 → evidence:ev1 → hypothesis:hyp1
    """
    graph.record_derivation(
        output_id="source_event:msg1",
        input_ids=[],
        algorithm="telegram_crawler",
        version="1.0.0",
        node_type="source_event",
        confidence=1.0,
    )
    graph.record_derivation(
        output_id="entity:user1",
        input_ids=["source_event:msg1"],
        algorithm="entity_extractor",
        version="1.2.0",
        parameters={"extract_mode": "aggressive"},
        node_type="entity",
        confidence=0.9,
    )
    graph.record_derivation(
        output_id="evidence:ev1",
        input_ids=["entity:user1", "source_event:msg1"],
        algorithm="entity_resolver_v2",
        version="2.0.0",
        parameters={"threshold": 0.85},
        node_type="evidence",
        confidence=0.92,
    )
    graph.record_derivation(
        output_id="hypothesis:hyp1",
        input_ids=["evidence:ev1"],
        algorithm="evidence_fusion",
        version="1.0.0",
        node_type="hypothesis",
        confidence=0.88,
    )
    return graph


# ─── ProvenanceNode dataclass tests ──────────────────────────────────────────


class TestProvenanceNode:
    """Tests for the ProvenanceNode dataclass."""

    def test_valid_node_creation(self):
        node = ProvenanceNode(
            node_id="n1",
            node_type="evidence",
            algorithm="entity_resolver_v2",
            version="2.0.0",
            output_id="evidence:ev1",
            confidence=0.9,
        )
        assert node.node_id == "n1"
        assert node.node_type == "evidence"
        assert node.output_id == "evidence:ev1"

    def test_output_id_defaults_to_node_id(self):
        node = ProvenanceNode(
            node_id="n1",
            node_type="source_event",
            algorithm="crawler",
            version="1.0",
        )
        assert node.output_id == "n1"

    def test_invalid_node_type_raises(self):
        with pytest.raises(ValueError, match="invalid node_type"):
            ProvenanceNode(
                node_id="n1",
                node_type="invalid_type",
                algorithm="test",
                version="1.0",
            )

    def test_invalid_confidence_raises(self):
        with pytest.raises(ValueError, match="confidence"):
            ProvenanceNode(
                node_id="n1",
                node_type="evidence",
                algorithm="test",
                version="1.0",
                confidence=1.5,
            )

    def test_to_dict_roundtrip(self):
        node = ProvenanceNode(
            node_id="n1",
            node_type="hypothesis",
            algorithm="fusion",
            version="1.0",
            parameters={"key": "value"},
            input_ids=["a", "b"],
            input_hashes=["h1", "h2"],
            output_id="hyp1",
            confidence=0.8,
        )
        d = node.to_dict()
        restored = ProvenanceNode.from_dict(d)
        assert restored.node_id == node.node_id
        assert restored.node_type == node.node_type
        assert restored.algorithm == node.algorithm
        assert restored.parameters == node.parameters
        assert restored.input_ids == node.input_ids
        assert restored.confidence == node.confidence

    def test_all_node_types_valid(self):
        for nt in NODE_TYPES:
            node = ProvenanceNode(
                node_id=f"n_{nt}",
                node_type=nt,
                algorithm="test",
                version="1.0",
            )
            assert node.node_type == nt


# ─── ProvenanceGraph.record_derivation tests ─────────────────────────────────


class TestRecordDerivation:
    """Tests for recording derivations."""

    def test_record_simple_derivation(self, graph):
        node = graph.record_derivation(
            output_id="evidence:ev1",
            input_ids=["message:1"],
            algorithm="entity_resolver_v2",
            version="2.0.0",
            confidence=0.9,
            node_type="evidence",
        )
        assert node.output_id == "evidence:ev1"
        assert node.algorithm == "entity_resolver_v2"
        assert node.input_ids == ["message:1"]
        assert node.node_type == "evidence"
        assert graph.node_count == 1

    def test_record_with_parameters(self, graph):
        node = graph.record_derivation(
            output_id="evidence:ev1",
            input_ids=["message:1"],
            algorithm="entity_resolver_v2",
            version="2.0.0",
            parameters={"threshold": 0.85, "fuzzy": True},
            confidence=0.9,
        )
        assert node.parameters == {"threshold": 0.85, "fuzzy": True}

    def test_record_with_input_hashes(self, graph):
        node = graph.record_derivation(
            output_id="evidence:ev1",
            input_ids=["message:1"],
            algorithm="test",
            version="1.0",
            input_hashes=["hash1", "hash2"],
            confidence=0.5,
        )
        assert node.input_hashes == ["hash1", "hash2"]

    def test_record_empty_output_id_raises(self, graph):
        with pytest.raises(ValueError, match="output_id"):
            graph.record_derivation(
                output_id="",
                input_ids=[],
                algorithm="test",
                version="1.0",
            )

    def test_deterministic_node_id(self, graph):
        n1 = graph.record_derivation(
            output_id="ev1",
            input_ids=["m1", "m2"],
            algorithm="algo",
            version="1.0",
        )
        n2 = graph.record_derivation(
            output_id="ev1",
            input_ids=["m1", "m2"],
            algorithm="algo",
            version="1.0",
        )
        assert n1.node_id == n2.node_id

    def test_get_node(self, graph):
        node = graph.record_derivation(
            output_id="ev1",
            input_ids=["m1"],
            algorithm="algo",
            version="1.0",
        )
        retrieved = graph.get_node(node.node_id)
        assert retrieved is not None
        assert retrieved.output_id == "ev1"

    def test_get_nodes_for_output(self, graph):
        graph.record_derivation(
            output_id="ev1",
            input_ids=["m1"],
            algorithm="algo_a",
            version="1.0",
        )
        graph.record_derivation(
            output_id="ev1",
            input_ids=["m2"],
            algorithm="algo_b",
            version="1.0",
        )
        nodes = graph.get_nodes_for_output("ev1")
        assert len(nodes) == 2


# ─── ProvenanceGraph.trace_provenance tests ──────────────────────────────────


class TestTraceProvenance:
    """Tests for backward provenance tracing."""

    def test_trace_full_chain(self, chained_graph):
        chain = chained_graph.trace_provenance("hypothesis:hyp1")
        # Should trace: hyp1 → ev1 → user1 → msg1 (4 nodes)
        assert len(chain) == 4
        # First node should be the hypothesis (newest).
        assert chain[0].output_id == "hypothesis:hyp1"
        # Last node should be the source event (oldest).
        assert chain[-1].output_id == "source_event:msg1"
        assert chain[-1].node_type == "source_event"

    def test_trace_single_node(self, graph):
        graph.record_derivation(
            output_id="source:1",
            input_ids=[],
            algorithm="crawler",
            version="1.0",
            node_type="source_event",
        )
        chain = graph.trace_provenance("source:1")
        assert len(chain) == 1
        assert chain[0].output_id == "source:1"

    def test_trace_unknown_object_returns_empty(self, graph):
        chain = graph.trace_provenance("nonexistent")
        assert chain == []

    def test_trace_preserves_order(self, chained_graph):
        chain = chained_graph.trace_provenance("hypothesis:hyp1")
        outputs = [n.output_id for n in chain]
        # Each node's inputs should appear later in the chain (or not at all
        # for source events).
        for i, node in enumerate(chain):
            for inp in node.input_ids:
                if inp in outputs:
                    assert outputs.index(inp) > i or outputs.index(inp) == i

    def test_trace_handles_cycles(self, graph):
        """Cycles in provenance should not cause infinite loops."""
        graph.record_derivation(
            output_id="a",
            input_ids=["b"],
            algorithm="algo",
            version="1.0",
        )
        graph.record_derivation(
            output_id="b",
            input_ids=["a"],
            algorithm="algo",
            version="1.0",
        )
        chain = graph.trace_provenance("a")
        # Should terminate and include both nodes.
        assert len(chain) <= 2
        assert len(chain) >= 1


# ─── ProvenanceGraph.explain tests ───────────────────────────────────────────


class TestExplain:
    """Tests for human-readable explanations."""

    def test_explain_returns_string(self, chained_graph):
        explanation = chained_graph.explain("hypothesis:hyp1")
        assert isinstance(explanation, str)
        assert "hypothesis:hyp1" in explanation
        assert "4 steps" in explanation

    def test_explain_includes_algorithm(self, chained_graph):
        explanation = chained_graph.explain("hypothesis:hyp1")
        assert "evidence_fusion" in explanation
        assert "entity_resolver_v2" in explanation

    def test_explain_includes_parameters(self, chained_graph):
        explanation = chained_graph.explain("evidence:ev1")
        assert "threshold" in explanation

    def test_explain_includes_source_events(self, chained_graph):
        explanation = chained_graph.explain("hypothesis:hyp1")
        assert "Source events" in explanation
        assert "source_event:msg1" in explanation

    def test_explain_unknown_object(self, graph):
        explanation = graph.explain("nonexistent")
        assert "No provenance" in explanation
        assert "nonexistent" in explanation

    def test_explain_includes_confidence(self, chained_graph):
        explanation = chained_graph.explain("hypothesis:hyp1")
        assert "confidence" in explanation


# ─── SQLite persistence tests ────────────────────────────────────────────────


class TestPersistence:
    """Tests for SQLite persistence."""

    def test_persist_and_reload(self, tmp_db_path):
        graph1 = ProvenanceGraph(db_path=tmp_db_path)
        graph1.record_derivation(
            output_id="ev1",
            input_ids=["msg1"],
            algorithm="algo",
            version="1.0",
            parameters={"key": "val"},
            confidence=0.9,
        )
        assert graph1.node_count == 1

        # Create a new graph pointing at the same DB — should load nodes.
        graph2 = ProvenanceGraph(db_path=tmp_db_path)
        assert graph2.node_count == 1
        chain = graph2.trace_provenance("ev1")
        assert len(chain) == 1
        assert chain[0].output_id == "ev1"
        assert chain[0].parameters == {"key": "val"}

    def test_persist_multiple_nodes(self, tmp_db_path):
        graph1 = ProvenanceGraph(db_path=tmp_db_path)
        graph1.record_derivation(
            output_id="a",
            input_ids=[],
            algorithm="crawler",
            version="1.0",
            node_type="source_event",
        )
        graph1.record_derivation(
            output_id="b",
            input_ids=["a"],
            algorithm="extractor",
            version="1.0",
            node_type="entity",
        )
        graph1.record_derivation(
            output_id="c",
            input_ids=["b"],
            algorithm="resolver",
            version="2.0",
            node_type="evidence",
        )

        graph2 = ProvenanceGraph(db_path=tmp_db_path)
        assert graph2.node_count == 3
        chain = graph2.trace_provenance("c")
        assert len(chain) == 3

    def test_in_memory_graph_no_db(self):
        graph = ProvenanceGraph()
        graph.record_derivation(
            output_id="ev1",
            input_ids=["m1"],
            algorithm="algo",
            version="1.0",
        )
        assert graph.node_count == 1
        # No DB file should be created.
        assert graph._db_path is None

    def test_reset_clears_memory(self, graph):
        graph.record_derivation(
            output_id="ev1",
            input_ids=["m1"],
            algorithm="algo",
            version="1.0",
        )
        assert graph.node_count == 1
        graph.reset()
        assert graph.node_count == 0


# ─── Replayability tests ─────────────────────────────────────────────────────


class TestReplayability:
    """Tests for provenance replay (change algorithm → new chain)."""

    def test_same_inputs_different_algorithm_different_node(self, graph):
        n1 = graph.record_derivation(
            output_id="ev1",
            input_ids=["m1"],
            algorithm="algo_v1",
            version="1.0",
        )
        n2 = graph.record_derivation(
            output_id="ev1",
            input_ids=["m1"],
            algorithm="algo_v2",
            version="2.0",
        )
        assert n1.node_id != n2.node_id
        # Both should be retrievable.
        assert graph.get_node(n1.node_id) is not None
        assert graph.get_node(n2.node_id) is not None

    def test_replay_preserves_parameters(self, graph):
        graph.record_derivation(
            output_id="ev1",
            input_ids=["m1"],
            algorithm="algo",
            version="1.0",
            parameters={"threshold": 0.8},
        )
        graph.record_derivation(
            output_id="ev1",
            input_ids=["m1"],
            algorithm="algo",
            version="2.0",
            parameters={"threshold": 0.9},
        )
        nodes = graph.get_nodes_for_output("ev1")
        assert len(nodes) == 2
        params = {n.version: n.parameters["threshold"] for n in nodes}
        assert params["1.0"] == 0.8
        assert params["2.0"] == 0.9
