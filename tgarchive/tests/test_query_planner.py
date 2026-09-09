"""
Tests for the unified query planner, SearchCandidate, EvidenceBundle, and RRF.
"""
from __future__ import annotations

import asyncio
from typing import List

import pytest

from tgarchive.search.search_candidate import SearchCandidate, VALID_OBJECT_TYPES
from tgarchive.search.evidence_bundle import EvidenceBundle
from tgarchive.search.rank_fusion import reciprocal_rank_fusion, DEFAULT_K
from tgarchive.search.query_planner import QueryPlanner, ALL_SUBSYSTEMS


# ── SearchCandidate ────────────────────────────────────────────────────────


class TestSearchCandidate:
    def test_minimal_construction(self):
        c = SearchCandidate(object_id="media:1", object_type="media")
        assert c.object_id == "media:1"
        assert c.object_type == "media"
        assert c.score == 0.0
        assert c.matched_by == []
        assert c.sources == []
        assert c.context == []
        assert c.provenance == []

    def test_full_construction(self):
        c = SearchCandidate(
            object_id="message:42",
            object_type="message",
            score=0.75,
            matched_by=["semantic"],
            sources=[{"k": "v"}],
            context=[{"kind": "channel"}],
            provenance=[{"subsystem": "semantic_search"}],
        )
        assert c.score == 0.75
        assert c.matched_by == ["semantic"]
        assert c.sources == [{"k": "v"}]

    @pytest.mark.parametrize("bad_type", ["", "foo", "Media", "msg"])
    def test_invalid_object_type_raises(self, bad_type):
        with pytest.raises(ValueError):
            SearchCandidate(object_id="x:1", object_type=bad_type)

    def test_empty_object_id_raises(self):
        with pytest.raises(ValueError):
            SearchCandidate(object_id="", object_type="media")

    @pytest.mark.parametrize("bad_score", [-0.01, 1.01, 2.0, -1])
    def test_score_out_of_range_raises(self, bad_score):
        with pytest.raises(ValueError):
            SearchCandidate(object_id="media:1", object_type="media", score=bad_score)

    def test_valid_object_types(self):
        for ot in VALID_OBJECT_TYPES:
            c = SearchCandidate(object_id="x:1", object_type=ot)
            assert c.object_type == ot

    def test_merge_from_dedupes_matched_by(self):
        a = SearchCandidate(
            object_id="message:1", object_type="message",
            matched_by=["semantic"], sources=[{"a": 1}],
        )
        b = SearchCandidate(
            object_id="message:1", object_type="message",
            matched_by=["semantic", "keyword"], sources=[{"b": 2}],
        )
        a.merge_from(b)
        assert a.matched_by == ["semantic", "keyword"]
        assert a.sources == [{"a": 1}, {"b": 2}]

    def test_to_dict_and_from_dict_roundtrip(self):
        c = SearchCandidate(
            object_id="media:7", object_type="media", score=0.5,
            matched_by=["filename_fuzzy"], sources=[{"x": 1}],
            context=[{"kind": "msg"}], provenance=[{"sub": "file_search"}],
        )
        d = c.to_dict()
        c2 = SearchCandidate.from_dict(d)
        assert c2 == c

    def test_add_helpers(self):
        c = SearchCandidate(object_id="media:1", object_type="media")
        c.add_source({"s": 1})
        c.add_context({"k": "ctx"})
        c.add_provenance({"sub": "x"})
        assert c.sources == [{"s": 1}]
        assert c.context == [{"k": "ctx"}]
        assert c.provenance == [{"sub": "x"}]


# ── EvidenceBundle ─────────────────────────────────────────────────────────


class TestEvidenceBundle:
    def test_minimal(self):
        b = EvidenceBundle(query="hello")
        assert b.query == "hello"
        assert b.candidates == []
        assert b.total_found == 0
        assert b.fusion_method == "rrf"
        assert b.subsystems_queried == []
        assert b.is_empty
        assert b.top_candidate is None

    def test_empty_query_raises(self):
        with pytest.raises(ValueError):
            EvidenceBundle(query="")

    def test_negative_total_raises(self):
        with pytest.raises(ValueError):
            EvidenceBundle(query="q", total_found=-1)

    def test_total_less_than_candidates_raises(self):
        c = SearchCandidate(object_id="m:1", object_type="media")
        with pytest.raises(ValueError):
            EvidenceBundle(query="q", candidates=[c], total_found=0)

    def test_top_candidate_and_object_ids(self):
        c1 = SearchCandidate(object_id="m:1", object_type="media", score=0.9)
        c2 = SearchCandidate(object_id="m:2", object_type="media", score=0.5)
        b = EvidenceBundle(query="q", candidates=[c1, c2], total_found=2)
        assert b.top_candidate is c1
        assert b.object_ids() == ["m:1", "m:2"]
        assert not b.is_empty

    def test_by_type(self):
        c1 = SearchCandidate(object_id="m:1", object_type="media")
        c2 = SearchCandidate(object_id="msg:2", object_type="message")
        b = EvidenceBundle(query="q", candidates=[c1, c2], total_found=2)
        assert b.by_type("media") == [c1]
        assert b.by_type("message") == [c2]

    def test_roundtrip(self):
        c = SearchCandidate(object_id="m:1", object_type="media", score=0.8)
        b = EvidenceBundle(
            query="q", candidates=[c], total_found=1,
            subsystems_queried=["file_search"], elapsed_ms=12.3,
        )
        d = b.to_dict()
        b2 = EvidenceBundle.from_dict(d)
        assert b2.query == "q"
        assert b2.candidates == [c]
        assert b2.subsystems_queried == ["file_search"]


# ── RRF ────────────────────────────────────────────────────────────────────


class TestRRF:
    def test_empty_returns_empty(self):
        assert reciprocal_rank_fusion({}) == []

    def test_single_subsystem_preserves_rank_order(self):
        cands = [
            SearchCandidate(object_id=f"m:{i}", object_type="media", score=1.0 / (i + 1))
            for i in range(5)
        ]
        fused = reciprocal_rank_fusion({"file": cands})
        assert len(fused) == 5
        # rank 1 → highest RRF score → normalized to 1.0
        assert fused[0].object_id == "m:0"
        assert fused[0].score == pytest.approx(1.0)
        # strictly decreasing
        scores = [c.score for c in fused]
        assert scores == sorted(scores, reverse=True)

    def test_top_candidate_normalized_to_one(self):
        cands = [SearchCandidate(object_id=f"m:{i}", object_type="media") for i in range(3)]
        fused = reciprocal_rank_fusion({"s": cands})
        assert fused[0].score == pytest.approx(1.0)
        assert all(0.0 <= c.score <= 1.0 for c in fused)

    def test_candidate_in_multiple_subsystems_scores_higher(self):
        only_a = [SearchCandidate(object_id="m:1", object_type="media")]
        both = [
            SearchCandidate(object_id="m:1", object_type="media", matched_by=["s1"]),
            SearchCandidate(object_id="m:2", object_type="media"),
        ]
        fused = reciprocal_rank_fusion({"a": only_a, "b": both})
        # m:1 appears in both subsystems → higher fused score than m:2
        assert fused[0].object_id == "m:1"
        assert fused[0].score == pytest.approx(1.0)
        m2 = next(c for c in fused if c.object_id == "m:2")
        m1 = next(c for c in fused if c.object_id == "m:1")
        assert m1.score > m2.score

    def test_matched_by_merged_across_subsystems(self):
        a = [SearchCandidate(object_id="m:1", object_type="media", matched_by=["filename_fuzzy"])]
        b = [SearchCandidate(object_id="m:1", object_type="media", matched_by=["semantic"])]
        fused = reciprocal_rank_fusion({"file": a, "sem": b})
        assert fused[0].matched_by == ["filename_fuzzy", "semantic"]

    def test_sources_merged(self):
        a = [SearchCandidate(object_id="m:1", object_type="media", sources=[{"src": "a"}])]
        b = [SearchCandidate(object_id="m:1", object_type="media", sources=[{"src": "b"}])]
        fused = reciprocal_rank_fusion({"file": a, "sem": b})
        assert fused[0].sources == [{"src": "a"}, {"src": "b"}]

    def test_limit_truncates(self):
        cands = [SearchCandidate(object_id=f"m:{i}", object_type="media") for i in range(10)]
        fused = reciprocal_rank_fusion({"s": cands}, limit=3)
        assert len(fused) == 3

    def test_does_not_mutate_inputs(self):
        a = [SearchCandidate(object_id="m:1", object_type="media", matched_by=["x"], score=0.5)]
        reciprocal_rank_fusion({"s": a})
        assert a[0].matched_by == ["x"]
        assert a[0].score == 0.5

    def test_invalid_k_raises(self):
        with pytest.raises(ValueError):
            reciprocal_rank_fusion({}, k=0)

    def test_invalid_limit_raises(self):
        with pytest.raises(ValueError):
            reciprocal_rank_fusion({}, limit=0)

    def test_rrf_formula_value(self):
        # Single subsystem, k=60: rank 1 → 1/61, normalized to 1.0
        cands = [SearchCandidate(object_id="m:1", object_type="media")]
        fused = reciprocal_rank_fusion({"s": cands}, k=60)
        assert fused[0].score == pytest.approx(1.0)
        # Two subsystems, same candidate rank 1 in both: 2/61 normalized → 1.0
        fused2 = reciprocal_rank_fusion({"s": cands, "t": cands}, k=60)
        assert fused2[0].score == pytest.approx(1.0)

    def test_empty_subsystem_list_skipped(self):
        cands = [SearchCandidate(object_id="m:1", object_type="media")]
        fused = reciprocal_rank_fusion({"s": cands, "empty": []})
        assert len(fused) == 1


# ── QueryPlanner ───────────────────────────────────────────────────────────


def _make_candidate(oid: str, score: float = 0.5, matched_by=None) -> SearchCandidate:
    return SearchCandidate(
        object_id=oid,
        object_type="media" if oid.startswith("media:") else "message",
        score=score,
        matched_by=matched_by or ["test"],
    )


class FakePlanner(QueryPlanner):
    """A QueryPlanner subclass with in-memory fake adapters for testing."""

    def __init__(self, subsystem_results, *, timeout=10.0, rrf_k=60):
        super().__init__(default_timeout=timeout, rrf_k=rrf_k)
        self._fake_results = subsystem_results
        self._adapter_calls: list[str] = []

    def _adapter_for(self, name):
        # Override dispatch to return fake adapters.
        if name not in self._fake_results:
            return None
        return lambda q, lim: self._fake_adapter(name, q, lim)

    def _select_subsystems(self, query, subsystems):
        # Allow tests to use custom subsystem names (e.g. "slow", "fast").
        if subsystems is None:
            return self._infer_subsystems(query)
        if subsystems == "all":
            return list(self._fake_results.keys()) or list(ALL_SUBSYSTEMS)
        if isinstance(subsystems, str):
            subsystems = [subsystems]
        return list(subsystems)

    def _fake_adapter(self, name, query, limit) -> List[SearchCandidate]:
        self._adapter_calls.append(name)
        cands = list(self._fake_results.get(name, []))
        return cands[:limit]


class TestQueryPlanner:
    def test_plan_returns_evidence_bundle(self):
        planner = FakePlanner(
            {"file_search": [_make_candidate("media:1", 0.9, ["filename_fuzzy"])]}
        )
        b = planner.plan("invoice.pdf", limit=10)
        assert isinstance(b, EvidenceBundle)
        assert b.query == "invoice.pdf"
        assert b.fusion_method == "rrf"
        assert b.total_found == 1
        assert len(b.candidates) == 1
        assert b.candidates[0].object_id == "media:1"

    def test_plan_fuses_multiple_subsystems(self):
        planner = FakePlanner(
            {
                "file_search": [
                    _make_candidate("media:1", 0.9, ["filename_fuzzy"]),
                    _make_candidate("media:2", 0.7, ["filename_fuzzy"]),
                ],
                "hybrid_search": [
                    _make_candidate("message:2", 0.8, ["keyword"]),
                    _make_candidate("message:1", 0.6, ["keyword"]),
                ],
            }
        )
        b = planner.plan("report", limit=10, subsystems=["file_search", "hybrid_search"])
        ids = b.object_ids()
        # Both subsystems queried
        assert set(b.subsystems_queried) == {"file_search", "hybrid_search"}
        assert len(b.candidates) == 4
        # Top candidate normalized to 1.0
        assert b.candidates[0].score == pytest.approx(1.0)
        # Scores descending
        scores = [c.score for c in b.candidates]
        assert scores == sorted(scores, reverse=True)

    def test_plan_limit_truncates(self):
        cands = [_make_candidate(f"media:{i}") for i in range(20)]
        planner = FakePlanner({"file_search": cands})
        b = planner.plan("x", limit=5, subsystems=["file_search"])
        assert len(b.candidates) == 5
        assert b.total_found == 20

    def test_plan_empty_results(self):
        planner = FakePlanner({"file_search": []})
        b = planner.plan("nothing", limit=10)
        assert b.is_empty
        assert b.total_found == 0
        assert b.candidates == []

    def test_plan_graceful_degradation_missing_subsystem(self):
        # Only file_search has results; hybrid_search not in fake_results → skipped.
        planner = FakePlanner(
            {"file_search": [_make_candidate("media:1", 0.9)]}
        )
        b = planner.plan("file.zip", limit=10)
        assert "file_search" in b.subsystems_queried
        assert "hybrid_search" not in b.subsystems_queried
        assert len(b.candidates) == 1

    def test_plan_records_errors_on_adapter_exception(self):
        class ErrorPlanner(FakePlanner):
            def _fake_adapter(self, name, query, limit):
                self._adapter_calls.append(name)
                raise RuntimeError("boom")

        planner = ErrorPlanner({"file_search": [_make_candidate("media:1")]})
        b = planner.plan("x", limit=10, subsystems=["file_search"])
        assert b.is_empty
        assert len(b.errors) == 1
        assert b.errors[0]["subsystem"] == "file_search"
        assert "boom" in b.errors[0]["error"]

    def test_plan_async_runs_in_parallel(self):
        import time as _time

        class SlowPlanner(FakePlanner):
            def _fake_adapter(self, name, query, limit):
                self._adapter_calls.append(name)
                _time.sleep(0.2)
                return [_make_candidate(f"{name}:1")]

        planner = SlowPlanner(
            {"file_search": [], "hybrid_search": [], "semantic_search": []}
        )
        start = _time.perf_counter()
        b = planner.plan("q", limit=10, subsystems="all")
        elapsed = _time.perf_counter() - start
        # 3 subsystems × 0.2s each, parallel → well under 0.5s
        assert elapsed < 0.5
        assert len(b.subsystems_queried) == 3

    def test_plan_timeout_skips_slow_subsystem(self):
        import time as _time

        class TimeoutPlanner(FakePlanner):
            def _fake_adapter(self, name, query, limit):
                self._adapter_calls.append(name)
                if name == "slow":
                    _time.sleep(2.0)
                    return [_make_candidate("slow:1")]
                return [_make_candidate("fast:1")]

        planner = TimeoutPlanner(
            {"slow": [], "fast": []}, timeout=0.3
        )
        b = planner.plan("q", limit=10, subsystems=["slow", "fast"])
        # slow timed out → only fast in results
        assert "fast" in b.subsystems_queried
        assert "slow" not in b.subsystems_queried
        assert any(e["subsystem"] == "slow" for e in b.errors)
        assert len(b.candidates) == 1

    def test_infer_subsystems_filename(self):
        planner = FakePlanner({})
        assert "file_search" in planner._infer_subsystems("invoice.pdf")

    def test_infer_subsystems_hash(self):
        planner = FakePlanner({})
        subs = planner._infer_subsystems("a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
        assert "file_search" in subs

    def test_infer_subsystems_text(self):
        planner = FakePlanner({})
        subs = planner._infer_subsystems("find messages about crypto")
        assert "semantic_search" in subs
        assert "hybrid_search" in subs

    def test_select_subsystems_explicit(self):
        planner = FakePlanner({})
        assert planner._select_subsystems("q", ["file_search"]) == ["file_search"]

    def test_select_subsystems_all(self):
        planner = FakePlanner({})
        subs = planner._select_subsystems("text", "all")
        assert "semantic_search" in subs

    def test_select_subsystems_invalid_falls_back(self):
        planner = FakePlanner({})
        subs = planner._select_subsystems("text", ["bogus"])
        # Falls back to inference
        assert len(subs) > 0

    def test_plan_empty_query_raises(self):
        planner = FakePlanner({})
        with pytest.raises(ValueError):
            planner.plan("")

    def test_plan_invalid_limit_raises(self):
        planner = FakePlanner({})
        with pytest.raises(ValueError):
            planner.plan("q", limit=0)

    def test_all_subsystems_constant(self):
        assert set(ALL_SUBSYSTEMS) == {"file_search", "hybrid_search", "semantic_search"}

    def test_plan_elapsed_ms_positive(self):
        planner = FakePlanner({"file_search": [_make_candidate("media:1")]})
        b = planner.plan("x", limit=10)
        assert b.elapsed_ms >= 0.0

    def test_plan_matched_by_merged_when_same_id_in_two_subsystems(self):
        planner = FakePlanner(
            {
                "file_search": [
                    SearchCandidate(
                        object_id="media:1", object_type="media",
                        score=0.9, matched_by=["filename_fuzzy"],
                        sources=[{"subsystem": "file_search"}],
                    )
                ],
                "hybrid_search": [
                    SearchCandidate(
                        object_id="media:1", object_type="media",
                        score=0.8, matched_by=["keyword"],
                        sources=[{"subsystem": "hybrid_search"}],
                    )
                ],
            }
        )
        b = planner.plan("shared", limit=10, subsystems=["file_search", "hybrid_search"])
        # Same object_id → merged into one candidate
        assert len(b.candidates) == 1
        assert set(b.candidates[0].matched_by) == {"filename_fuzzy", "keyword"}
        assert len(b.candidates[0].sources) == 2
