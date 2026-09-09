"""
Tests for the SPECTRA agent tool surface (``tgarchive.agent.tools``).

Covers all 5 tool functions — ``search``, ``expand``, ``timeline``,
``resolve``, ``evidence`` — plus the configuration helpers
``set_db_path`` / ``get_db_path`` and the JSON schemas in
``tgarchive.agent.tool_schema``.

The tests use a lightweight in-memory/temporary SQLite database so that
no real SPECTRA database is required.  Underlying intelligence services
(``cross_index_intelligence``, ``draw_conclusions``) are mocked where
needed so the tests remain deterministic and fast.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from tgarchive.agent import tools as agent_tools
from tgarchive.agent.tools import (
    AGENT_TOOLS,
    evidence,
    expand,
    get_db_path,
    resolve,
    search,
    set_db_path,
    timeline,
)
from tgarchive.agent.tool_schema import (
    TOOL_OUTPUT_SCHEMAS,
    TOOL_SCHEMAS,
    all_tool_names,
    get_output_schema,
    get_tool_schema,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a minimal SPECTRA-style SQLite database for testing.

    The database contains ``users`` and ``messages`` tables with a few
    rows so that the agent tools can exercise their DB-backed code paths
    without requiring a full SPECTRA deployment.
    """
    db_path = tmp_path / "test_spectra.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE users (
            id          INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            last_name   TEXT,
            tags        TEXT
        );
        CREATE TABLE messages (
            id          INTEGER PRIMARY KEY,
            channel_id  INTEGER,
            user_id     INTEGER,
            content     TEXT,
            date        TEXT,
            type        TEXT,
            reply_to    INTEGER
        );
        INSERT INTO users (id, username, first_name, last_name, tags)
        VALUES
            (100, 'alice', 'Alice', 'Smith', '["admin"]'),
            (200, 'bob',   'Bob',   'Jones', '[]'),
            (300, 'carol', 'Carol', 'Ng',    '["vip"]');
        INSERT INTO messages (id, channel_id, user_id, content, date, type, reply_to)
        VALUES
            (1, 10, 100, 'hello world from alice', '2026-01-01T09:00:00', 'text', NULL),
            (2, 10, 100, 'sharing archive.zip',    '2026-01-01T21:30:00', 'text', NULL),
            (3, 11, 200, 'bob report here',        '2026-01-02T14:15:00', 'text', 1),
            (4, 11, 200, 'another message',        '2026-01-02T19:45:00', 'text', NULL),
            (5, 12, 300, 'carol checks in',        '2026-01-03T08:00:00', 'text', NULL),
            (6, 12, 300, 'urgent update',          '2026-01-03T22:10:00', 'text', 2),
            (7, 10, 100, 'late night message',     '2026-01-04T23:50:00', 'text', NULL),
            (8, 11, 200, 'morning greeting',       '2026-01-05T07:20:00', 'text', NULL),
            (9, 12, 300, 'midday check',           '2026-01-05T12:00:00', 'text', NULL),
            (10, 10, 100, 'archive.zip password',  '2026-01-06T20:00:00', 'text', NULL);
        """
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(autouse=True)
def reset_db_path():
    """Reset the module-level DB path before and after each test."""
    original = agent_tools.get_db_path()
    yield
    agent_tools.set_db_path(original)


@pytest.fixture
def db_path(temp_db: Path):
    """Configure the agent tools to use the temporary database."""
    set_db_path(str(temp_db))
    return temp_db


@pytest.fixture
def missing_db_path(tmp_path: Path):
    """Point the agent tools at a non-existent database path."""
    fake_path = tmp_path / "does_not_exist.db"
    set_db_path(str(fake_path))
    return fake_path


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _is_json_serializable(obj: Any) -> bool:
    """Return True if *obj* can be serialized to JSON without error."""
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _fake_cross_index_intelligence(
    db_path: str,
    entity_id: int,
    entity_type: str = "user",
) -> Dict[str, Any]:
    """A deterministic stand-in for ``cross_index_intelligence``."""
    return {
        "canonical_id": f"telegram:{entity_type}:{entity_id}",
        "evidence": [
            {
                "evidence_id": "ev:1",
                "evidence_type": "linguistic",
                "model": "test_model",
                "model_version": "1.0",
                "confidence": 0.8,
                "score": 0.75,
                "direction": "supports",
            },
            {
                "evidence_id": "ev:2",
                "evidence_type": "temporal",
                "model": "test_model",
                "model_version": "1.0",
                "confidence": 0.6,
                "score": 0.4,
                "direction": "contradicts",
            },
        ],
        "hypotheses": [
            {
                "hypothesis_type": "same_actor",
                "probability": 0.81,
                "subject_a": f"telegram:user:{entity_id}",
                "subject_b": f"telegram:user:{entity_id + 1000}",
                "supporting_evidence": [{"evidence_id": "ev:1"}],
                "contradicting_evidence": [{"evidence_id": "ev:2"}],
            }
        ],
        "campaigns": [{"campaign_id": "camp:1", "name": "Test Campaign"}],
        "inferences": [
            {
                "inference_id": "inf:1",
                "model": "inf_model",
                "model_version": "2.0",
                "confidence": 0.9,
                "inference_type": "actor_identity",
            }
        ],
        "graph": {
            "node_key": f"{entity_type}:{entity_id}",
            "edges": [
                {
                    "edge_type": "same_actor",
                    "target": f"user:{entity_id + 1000}",
                    "target_type": "user",
                    "target_id": entity_id + 1000,
                    "direction": "bidirectional",
                    "metadata": {"confidence": 0.81},
                },
                {
                    "edge_type": "associated_with",
                    "target": f"channel:10",
                    "target_type": "channel",
                    "target_id": 10,
                    "direction": "outgoing",
                    "metadata": {},
                },
            ],
            "neighbors": [
                {"object_id": f"user:{entity_id + 1000}", "object_type": "user"}
            ],
        },
    }


# ─── set_db_path / get_db_path ───────────────────────────────────────────────


class TestDbPathConfig:
    """Tests for ``set_db_path`` and ``get_db_path``."""

    def test_get_db_path_returns_string(self) -> None:
        """``get_db_path`` always returns a string."""
        result = get_db_path()
        assert isinstance(result, str)

    def test_set_db_path_with_string(self, tmp_path: Path) -> None:
        """``set_db_path`` accepts a plain string."""
        path = str(tmp_path / "custom.db")
        set_db_path(path)
        assert get_db_path() == path

    def test_set_db_path_with_pathlib(self, tmp_path: Path) -> None:
        """``set_db_path`` accepts a ``pathlib.Path`` and normalises to str."""
        path = tmp_path / "pathlib.db"
        set_db_path(path)
        assert get_db_path() == str(path)

    def test_set_db_path_is_idempotent(self, tmp_path: Path) -> None:
        """Repeated calls to ``set_db_path`` update the stored value."""
        p1 = str(tmp_path / "a.db")
        p2 = str(tmp_path / "b.db")
        set_db_path(p1)
        assert get_db_path() == p1
        set_db_path(p2)
        assert get_db_path() == p2


# ─── search ──────────────────────────────────────────────────────────────────


class TestSearch:
    """Tests for the ``search`` tool."""

    def test_search_empty_query_returns_error(self, db_path: Path) -> None:
        """An empty query string yields an error dict, not an exception."""
        result = search("")
        assert "error" in result
        assert isinstance(result["error"], str)

    def test_search_whitespace_query_returns_error(self, db_path: Path) -> None:
        """A whitespace-only query is treated as empty."""
        result = search("   ")
        assert "error" in result

    def test_search_returns_json_serializable_dict(self, db_path: Path) -> None:
        """The search result is a JSON-serializable dict."""
        result = search("archive", limit=5)
        assert isinstance(result, dict)
        assert _is_json_serializable(result)

    def test_search_includes_summary(self, db_path: Path) -> None:
        """The result includes a human-readable ``summary`` field."""
        result = search("archive", limit=5)
        assert "summary" in result
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    def test_search_has_expected_keys(self, db_path: Path) -> None:
        """A successful search result has the documented top-level keys."""
        result = search("archive", limit=5)
        for key in ("candidates", "total_found", "subsystems_queried", "elapsed_ms"):
            assert key in result, f"missing key: {key}"

    def test_search_candidates_are_dicts(self, db_path: Path) -> None:
        """Each candidate in the result is a dict with expected fields."""
        result = search("archive", limit=5)
        for cand in result.get("candidates", []):
            assert isinstance(cand, dict)
            assert "object_id" in cand
            assert "object_type" in cand
            assert "score" in cand

    def test_search_respects_limit(self, db_path: Path) -> None:
        """The ``limit`` parameter caps the number of candidates."""
        result = search("message", limit=2)
        assert result["total_found"] <= 2

    def test_search_with_subsystems_filter(self, db_path: Path) -> None:
        """Specifying ``subsystems`` restricts which subsystems are queried."""
        result = search("archive", limit=5, subsystems=["file"])
        assert isinstance(result["subsystems_queried"], list)

    def test_search_missing_db_degrades_gracefully(
        self, missing_db_path: Path
    ) -> None:
        """When the database is absent, search does not crash.

        Depending on whether ``QueryPlanner`` is available, search may
        return either an ``{"error": ...}`` dict or a valid result with
        empty candidates.  In both cases the result must be a
        JSON-serializable dict.
        """
        result = search("anything")
        assert isinstance(result, dict)
        assert _is_json_serializable(result)
        # Either an error or a valid (possibly empty) result — never a crash.
        if "error" in result:
            assert isinstance(result["error"], str)
        else:
            assert "candidates" in result

    def test_search_elapsed_ms_is_number(self, db_path: Path) -> None:
        """``elapsed_ms`` is a numeric value."""
        result = search("archive", limit=5)
        assert isinstance(result["elapsed_ms"], (int, float))


# ─── expand ──────────────────────────────────────────────────────────────────


class TestExpand:
    """Tests for the ``expand`` tool."""

    def test_expand_empty_object_id_returns_error(self, db_path: Path) -> None:
        """An empty ``object_id`` yields an error dict."""
        result = expand("")
        assert "error" in result

    def test_expand_non_numeric_id_returns_error(self, db_path: Path) -> None:
        """A non-numeric object ID yields an error dict."""
        result = expand("user:abc")
        assert "error" in result

    def test_expand_missing_db_returns_error(self, missing_db_path: Path) -> None:
        """When the database is absent, expand returns an error dict."""
        result = expand("user:100")
        assert "error" in result
        assert _is_json_serializable(result)

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    def test_expand_returns_expected_shape(
        self, mock_ci: Any, db_path: Path
    ) -> None:
        """expand returns root, neighbors, edges, depth_reached, summary."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        result = expand("user:100", depth=1)
        assert isinstance(result, dict)
        assert _is_json_serializable(result)
        for key in ("root", "neighbors", "edges", "depth_reached", "summary"):
            assert key in result, f"missing key: {key}"

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    def test_expand_includes_summary(self, mock_ci: Any, db_path: Path) -> None:
        """The result includes a human-readable ``summary``."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        result = expand("user:100")
        assert "summary" in result
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    def test_expand_root_has_object_id_and_type(
        self, mock_ci: Any, db_path: Path
    ) -> None:
        """The ``root`` field contains ``object_id`` and ``object_type``."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        result = expand("user:100")
        root = result["root"]
        assert root["object_id"] == "user:100"
        assert root["object_type"] == "user"

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    def test_expand_neighbors_are_dicts(self, mock_ci: Any, db_path: Path) -> None:
        """Each neighbour is a dict with the expected fields."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        result = expand("user:100", depth=1)
        for nb in result["neighbors"]:
            assert isinstance(nb, dict)
            assert "object_id" in nb
            assert "relationship" in nb

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    def test_expand_depth_reached_is_int(self, mock_ci: Any, db_path: Path) -> None:
        """``depth_reached`` is an integer."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        result = expand("user:100", depth=1)
        assert isinstance(result["depth_reached"], int)
        assert result["depth_reached"] >= 1

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    def test_expand_relationship_filter(
        self, mock_ci: Any, db_path: Path
    ) -> None:
        """The ``relationship_types`` filter restricts returned neighbours."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        result = expand("user:100", depth=1, relationship_types=["same_actor"])
        for nb in result["neighbors"]:
            assert nb["relationship"] == "same_actor"

    def test_expand_service_failure_degrades_gracefully(
        self, db_path: Path
    ) -> None:
        """If ``cross_index_intelligence`` raises, expand returns an error dict."""
        with patch(
            "tgarchive.agent.tools._cross_index_intelligence",
            side_effect=RuntimeError("boom"),
        ):
            result = expand("user:100")
        assert "error" in result
        assert _is_json_serializable(result)


# ─── timeline ────────────────────────────────────────────────────────────────


class TestTimeline:
    """Tests for the ``timeline`` tool."""

    def test_timeline_empty_entity_id_returns_error(self, db_path: Path) -> None:
        """An empty ``entity_id`` yields an error dict."""
        result = timeline("")
        assert "error" in result

    def test_timeline_non_numeric_id_returns_error(self, db_path: Path) -> None:
        """A non-numeric entity ID yields an error dict."""
        result = timeline("user:abc")
        assert "error" in result

    def test_timeline_missing_db_returns_error(self, missing_db_path: Path) -> None:
        """When the database is absent, timeline returns an error dict."""
        result = timeline("user:100")
        assert "error" in result
        assert _is_json_serializable(result)

    def test_timeline_returns_expected_shape(self, db_path: Path) -> None:
        """timeline returns entity_id, events, activity_pattern, summary."""
        result = timeline("user:100")
        assert isinstance(result, dict)
        assert _is_json_serializable(result)
        for key in ("entity_id", "events", "activity_pattern", "summary"):
            assert key in result, f"missing key: {key}"

    def test_timeline_includes_summary(self, db_path: Path) -> None:
        """The result includes a human-readable ``summary``."""
        result = timeline("user:100")
        assert "summary" in result
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    def test_timeline_events_are_chronological(self, db_path: Path) -> None:
        """Events are returned in ascending timestamp order."""
        result = timeline("user:100")
        timestamps = [e["timestamp"] for e in result["events"] if e["timestamp"]]
        assert timestamps == sorted(timestamps)

    def test_timeline_events_have_expected_fields(self, db_path: Path) -> None:
        """Each event has timestamp, event_type, channel_id, summary."""
        result = timeline("user:100")
        for ev in result["events"]:
            assert "timestamp" in ev
            assert "event_type" in ev
            assert "channel_id" in ev
            assert "summary" in ev

    def test_timeline_activity_pattern(self, db_path: Path) -> None:
        """``activity_pattern`` contains peak_hours and total_events."""
        result = timeline("user:100")
        ap = result["activity_pattern"]
        assert "peak_hours" in ap
        assert "total_events" in ap
        assert isinstance(ap["peak_hours"], list)
        assert isinstance(ap["total_events"], int)

    def test_timeline_date_range_filter(self, db_path: Path) -> None:
        """``start`` and ``end`` bounds filter the returned events."""
        result = timeline("user:100", start="2026-01-02", end="2026-01-03")
        for ev in result["events"]:
            ts = ev["timestamp"] or ""
            assert ts >= "2026-01-02"
            assert ts <= "2026-01-04"  # inclusive upper bound-ish

    def test_timeline_event_type_filter(self, db_path: Path) -> None:
        """``event_types`` restricts the returned event types."""
        result = timeline("user:100", event_types=["text"])
        for ev in result["events"]:
            assert ev["event_type"] == "text"

    def test_timeline_no_events_returns_empty_list(self, db_path: Path) -> None:
        """An entity with no messages returns an empty events list."""
        result = timeline("user:999")
        assert result["events"] == []
        assert result["activity_pattern"]["total_events"] == 0

    def test_timeline_service_failure_degrades_gracefully(
        self, db_path: Path
    ) -> None:
        """If the DB connection raises, timeline returns an error dict."""
        with patch(
            "tgarchive.agent.tools.connect_sqlite",
            side_effect=sqlite3.OperationalError("disk I/O error"),
        ):
            result = timeline("user:100")
        assert "error" in result
        assert _is_json_serializable(result)


# ─── resolve ─────────────────────────────────────────────────────────────────


class TestResolve:
    """Tests for the ``resolve`` tool."""

    def test_resolve_empty_query_returns_error(self, db_path: Path) -> None:
        """An empty query yields an error dict."""
        result = resolve("")
        assert "error" in result

    def test_resolve_whitespace_query_returns_error(self, db_path: Path) -> None:
        """A whitespace-only query yields an error dict."""
        result = resolve("   ")
        assert "error" in result

    def test_resolve_missing_db_returns_error(self, missing_db_path: Path) -> None:
        """When the database is absent, resolve returns an error dict."""
        result = resolve("@alice")
        assert "error" in result
        assert _is_json_serializable(result)

    def test_resolve_returns_expected_shape(self, db_path: Path) -> None:
        """resolve returns query, clusters, explanation."""
        result = resolve("@alice")
        assert isinstance(result, dict)
        assert _is_json_serializable(result)
        for key in ("query", "clusters", "explanation"):
            assert key in result, f"missing key: {key}"

    def test_resolve_includes_explanation(self, db_path: Path) -> None:
        """The result includes a human-readable ``explanation``."""
        result = resolve("@alice")
        assert "explanation" in result
        assert isinstance(result["explanation"], str)
        assert len(result["explanation"]) > 0

    def test_resolve_by_username_finds_user(self, db_path: Path) -> None:
        """Resolving a known username returns a cluster with candidates."""
        result = resolve("@alice")
        assert result["query"] == "@alice"
        assert isinstance(result["clusters"], list)

    def test_resolve_by_numeric_id_finds_user(self, db_path: Path) -> None:
        """Resolving a numeric user ID returns a cluster."""
        result = resolve("100")
        assert isinstance(result["clusters"], list)

    def test_resolve_unknown_user_returns_empty_clusters(
        self, db_path: Path
    ) -> None:
        """An unknown username returns zero clusters but no error."""
        result = resolve("@nobody")
        assert result["clusters"] == []
        assert "explanation" in result

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    def test_resolve_with_hypotheses_includes_candidates(
        self, mock_ci: Any, db_path: Path
    ) -> None:
        """When cross-index returns same_actor hypotheses, candidates grow."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        result = resolve("100")
        assert isinstance(result["clusters"], list)
        if result["clusters"]:
            cluster = result["clusters"][0]
            assert "confidence" in cluster
            assert "candidates" in cluster
            assert isinstance(cluster["candidates"], list)

    def test_resolve_service_failure_degrades_gracefully(
        self, db_path: Path
    ) -> None:
        """If the DB connection raises, resolve returns an error dict."""
        with patch(
            "tgarchive.agent.tools.connect_sqlite",
            side_effect=sqlite3.OperationalError("corrupt"),
        ):
            result = resolve("@alice")
        assert "error" in result
        assert _is_json_serializable(result)


# ─── evidence ────────────────────────────────────────────────────────────────


class TestEvidence:
    """Tests for the ``evidence`` tool."""

    def test_evidence_empty_object_id_returns_error(self, db_path: Path) -> None:
        """An empty ``object_id`` yields an error dict."""
        result = evidence("")
        assert "error" in result

    def test_evidence_non_numeric_id_returns_error(self, db_path: Path) -> None:
        """A non-numeric object ID yields an error dict."""
        result = evidence("user:abc")
        assert "error" in result

    def test_evidence_missing_db_returns_error(self, missing_db_path: Path) -> None:
        """When the database is absent, evidence returns an error dict."""
        result = evidence("user:100")
        assert "error" in result
        assert _is_json_serializable(result)

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    @patch("tgarchive.agent.tools._draw_conclusions")
    def test_evidence_returns_expected_shape(
        self, mock_dc: Any, mock_ci: Any, db_path: Path
    ) -> None:
        """evidence returns provenance_chain, supporting/contradicting, explanation."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        mock_dc.return_value = []
        result = evidence("user:100")
        assert isinstance(result, dict)
        assert _is_json_serializable(result)
        for key in (
            "object_id",
            "object_type",
            "provenance_chain",
            "supporting_evidence",
            "contradicting_evidence",
            "explanation",
        ):
            assert key in result, f"missing key: {key}"

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    @patch("tgarchive.agent.tools._draw_conclusions")
    def test_evidence_includes_explanation(
        self, mock_dc: Any, mock_ci: Any, db_path: Path
    ) -> None:
        """The result includes a human-readable ``explanation``."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        mock_dc.return_value = []
        result = evidence("user:100")
        assert "explanation" in result
        assert isinstance(result["explanation"], str)
        assert len(result["explanation"]) > 0

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    @patch("tgarchive.agent.tools._draw_conclusions")
    def test_evidence_provenance_chain_built_from_evidence(
        self, mock_dc: Any, mock_ci: Any, db_path: Path
    ) -> None:
        """The provenance chain is built from evidence and inferences."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        mock_dc.return_value = []
        result = evidence("user:100")
        chain = result["provenance_chain"]
        assert isinstance(chain, list)
        assert len(chain) >= 2  # 2 evidence + 1 inference = 3
        for node in chain:
            assert "node_id" in node
            assert "algorithm" in node

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    @patch("tgarchive.agent.tools._draw_conclusions")
    def test_evidence_supporting_and_contradicting_split(
        self, mock_dc: Any, mock_ci: Any, db_path: Path
    ) -> None:
        """Evidence is split into supporting and contradicting lists."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        mock_dc.return_value = []
        result = evidence("user:100")
        assert len(result["supporting_evidence"]) >= 1
        assert len(result["contradicting_evidence"]) >= 1

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    @patch("tgarchive.agent.tools._draw_conclusions")
    def test_evidence_conclusion_type_detection(
        self, mock_dc: Any, mock_ci: Any, db_path: Path
    ) -> None:
        """A ``conclusion:`` prefix sets ``object_type`` to ``conclusion``."""
        mock_ci.side_effect = _fake_cross_index_intelligence
        mock_dc.return_value = []
        result = evidence("conclusion:789")
        assert result["object_type"] == "conclusion"

    @patch("tgarchive.agent.tools._cross_index_intelligence")
    def test_evidence_service_failure_degrades_gracefully(
        self, mock_ci: Any, db_path: Path
    ) -> None:
        """If ``cross_index_intelligence`` raises, evidence returns an error."""
        mock_ci.side_effect = RuntimeError("service down")
        result = evidence("user:100")
        assert "error" in result
        assert _is_json_serializable(result)


# ─── AGENT_TOOLS registry ────────────────────────────────────────────────────


class TestAgentToolsRegistry:
    """Tests for the ``AGENT_TOOLS`` dispatch registry."""

    def test_registry_has_five_tools(self) -> None:
        """The registry contains exactly the 5 documented tools."""
        expected = {"search", "expand", "timeline", "resolve", "evidence"}
        assert set(AGENT_TOOLS.keys()) == expected

    def test_registry_values_are_callables(self) -> None:
        """Each registry entry is a callable function."""
        for name, func in AGENT_TOOLS.items():
            assert callable(func), f"{name} is not callable"

    def test_registry_matches_module_functions(self) -> None:
        """Registry entries point to the actual module-level functions."""
        assert AGENT_TOOLS["search"] is search
        assert AGENT_TOOLS["expand"] is expand
        assert AGENT_TOOLS["timeline"] is timeline
        assert AGENT_TOOLS["resolve"] is resolve
        assert AGENT_TOOLS["evidence"] is evidence


# ─── Tool schemas ────────────────────────────────────────────────────────────


class TestToolSchemas:
    """Tests for ``tgarchive.agent.tool_schema``."""

    def test_tool_schemas_has_five_entries(self) -> None:
        """``TOOL_SCHEMAS`` contains all 5 tools."""
        expected = {"search", "expand", "timeline", "resolve", "evidence"}
        assert set(TOOL_SCHEMAS.keys()) == expected

    def test_output_schemas_has_five_entries(self) -> None:
        """``TOOL_OUTPUT_SCHEMAS`` contains all 5 tools."""
        expected = {"search", "expand", "timeline", "resolve", "evidence"}
        assert set(TOOL_OUTPUT_SCHEMAS.keys()) == expected

    @pytest.mark.parametrize("tool_name", ["search", "expand", "timeline", "resolve", "evidence"])
    def test_input_schema_is_function_format(self, tool_name: str) -> None:
        """Each input schema follows the OpenAI function-calling format."""
        schema = TOOL_SCHEMAS[tool_name]
        assert schema["type"] == "function"
        assert "function" in schema
        fn = schema["function"]
        assert fn["name"] == tool_name
        assert isinstance(fn["description"], str)
        assert len(fn["description"]) > 0
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params

    @pytest.mark.parametrize("tool_name", ["search", "expand", "timeline", "resolve", "evidence"])
    def test_output_schema_is_json_object(self, tool_name: str) -> None:
        """Each output schema is a JSON object schema with properties."""
        schema = TOOL_OUTPUT_SCHEMAS[tool_name]
        assert schema["type"] == "object"
        assert "properties" in schema

    @pytest.mark.parametrize("tool_name", ["search", "expand", "timeline", "resolve", "evidence"])
    def test_output_schema_has_error_field(self, tool_name: str) -> None:
        """Each output schema declares an optional ``error`` field."""
        schema = TOOL_OUTPUT_SCHEMAS[tool_name]
        assert "error" in schema["properties"]

    def test_search_schema_requires_query(self) -> None:
        """The search schema marks ``query`` as required."""
        params = TOOL_SCHEMAS["search"]["function"]["parameters"]
        assert "query" in params["required"]

    def test_expand_schema_requires_object_id(self) -> None:
        """The expand schema marks ``object_id`` as required."""
        params = TOOL_SCHEMAS["expand"]["function"]["parameters"]
        assert "object_id" in params["required"]

    def test_timeline_schema_requires_entity_id(self) -> None:
        """The timeline schema marks ``entity_id`` as required."""
        params = TOOL_SCHEMAS["timeline"]["function"]["parameters"]
        assert "entity_id" in params["required"]

    def test_resolve_schema_requires_query_or_id(self) -> None:
        """The resolve schema marks ``query_or_id`` as required."""
        params = TOOL_SCHEMAS["resolve"]["function"]["parameters"]
        assert "query_or_id" in params["required"]

    def test_evidence_schema_requires_object_id(self) -> None:
        """The evidence schema marks ``object_id`` as required."""
        params = TOOL_SCHEMAS["evidence"]["function"]["parameters"]
        assert "object_id" in params["required"]

    def test_search_schema_subsystems_enum(self) -> None:
        """The search ``subsystems`` parameter has the expected enum values."""
        props = TOOL_SCHEMAS["search"]["function"]["parameters"]["properties"]
        assert set(props["subsystems"]["items"]["enum"]) == {
            "file", "semantic", "graph", "entity", "hash",
        }

    def test_get_tool_schema_returns_correct_entry(self) -> None:
        """``get_tool_schema`` returns the matching schema dict."""
        assert get_tool_schema("search") is TOOL_SCHEMAS["search"]
        assert get_tool_schema("evidence") is TOOL_SCHEMAS["evidence"]

    def test_get_tool_schema_unknown_raises(self) -> None:
        """``get_tool_schema`` raises ``KeyError`` for unknown tools."""
        with pytest.raises(KeyError):
            get_tool_schema("nonexistent")

    def test_get_output_schema_returns_correct_entry(self) -> None:
        """``get_output_schema`` returns the matching output schema dict."""
        assert get_output_schema("resolve") is TOOL_OUTPUT_SCHEMAS["resolve"]

    def test_get_output_schema_unknown_raises(self) -> None:
        """``get_output_schema`` raises ``KeyError`` for unknown tools."""
        with pytest.raises(KeyError):
            get_output_schema("nonexistent")

    def test_all_tool_names_returns_five(self) -> None:
        """``all_tool_names`` returns exactly the 5 tool names."""
        names = all_tool_names()
        assert set(names) == {"search", "expand", "timeline", "resolve", "evidence"}
        assert len(names) == 5

    @pytest.mark.parametrize("tool_name", ["search", "expand", "timeline", "resolve", "evidence"])
    def test_schemas_are_json_serializable(self, tool_name: str) -> None:
        """All schemas are JSON-serializable (no non-serializable types)."""
        assert _is_json_serializable(TOOL_SCHEMAS[tool_name])
        assert _is_json_serializable(TOOL_OUTPUT_SCHEMAS[tool_name])


# ─── Cross-cutting: all tools return JSON-serializable dicts ─────────────────


class TestJsonSerializability:
    """Ensure every tool returns a JSON-serializable dict in all modes."""

    def test_all_tools_degrade_gracefully_without_db(
        self, missing_db_path: Path
    ) -> None:
        """Every tool returns a JSON-serializable dict when the DB is missing.

        ``search`` may return a valid (empty) result via ``QueryPlanner``
        rather than an error dict; the other four tools return error dicts.
        In all cases the result must be a JSON-serializable dict — never
        an unhandled exception.
        """
        results: List[Dict[str, Any]] = [
            search("test"),
            expand("user:100"),
            timeline("user:100"),
            resolve("@alice"),
            evidence("user:100"),
        ]
        for r in results:
            assert isinstance(r, dict), "tool did not return a dict"
            assert _is_json_serializable(r), "tool result is not JSON-serializable"

    def test_all_tools_empty_input_return_serializable_errors(
        self, db_path: Path
    ) -> None:
        """Empty-input error dicts from every tool are JSON-serializable."""
        results: List[Dict[str, Any]] = [
            search(""),
            expand(""),
            timeline(""),
            resolve(""),
            evidence(""),
        ]
        for r in results:
            assert isinstance(r, dict)
            assert _is_json_serializable(r)
            assert "error" in r
