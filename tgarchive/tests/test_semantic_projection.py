"""Tests for the semantic projection and search modules.

Covers:

* :class:`tgarchive.search.semantic_projection.EmbeddingGenerator` —
  fallback chain, dimensionality, L2 normalisation, provenance.
* :class:`tgarchive.search.semantic_projection.SemanticProjection` —
  vector storage, metadata sidecar, idempotent upserts, batch projection.
* :class:`tgarchive.search.semantic_search.SemanticSearchEngine` and
  :func:`tgarchive.search.semantic_search.semantic_search` —
  correct distance→similarity conversion, content population,
  threshold filtering, numpy fallback.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

from tgarchive.search.semantic_projection import (
    EMBEDDING_DIMENSIONS,
    EmbeddingGenerator,
    ProjectionResult,
    SemanticProjection,
    semantic_id_string,
    semantic_vector_id,
)
from tgarchive.search.semantic_search import (
    SearchResult,
    SemanticSearchEngine,
    semantic_search,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a temporary db_path for the semantic stores."""
    return tmp_path / "spectra_test.db"


@pytest.fixture
def embedder() -> EmbeddingGenerator:
    """An EmbeddingGenerator using whatever backend is available."""
    return EmbeddingGenerator()


@pytest.fixture
def projection(tmp_db_path: Path, embedder: EmbeddingGenerator) -> SemanticProjection:
    """A SemanticProjection backed by a temp db_path."""
    proj = SemanticProjection(tmp_db_path, embedding_generator=embedder)
    yield proj
    proj.close()


@pytest.fixture
def engine(tmp_db_path: Path, embedder: EmbeddingGenerator) -> SemanticSearchEngine:
    """A SemanticSearchEngine backed by a temp db_path."""
    eng = SemanticSearchEngine(tmp_db_path, embedding_generator=embedder)
    yield eng
    eng.close()


# ── EmbeddingGenerator tests ──────────────────────────────────────────────


class TestEmbeddingGenerator:
    """Tests for the embedding generator with fallback chain."""

    def test_creates_embedding_generator(self, embedder: EmbeddingGenerator):
        assert embedder.dimensions > 0
        assert embedder.backend in (
            "sentence_transformer",
            "tfidf_svd",
            "hash_bow",
        )

    def test_provenance_has_model_name_and_version(self, embedder: EmbeddingGenerator):
        prov = embedder.provenance
        assert prov.model_name
        assert prov.model_version
        assert prov.backend == embedder.backend
        assert prov.dimensions == embedder.dimensions

    def test_embed_single_returns_correct_shape(self, embedder: EmbeddingGenerator):
        vec = embedder.embed("hello world")
        assert vec.shape == (embedder.dimensions,)
        assert vec.dtype == np.float32

    def test_embed_batch_returns_correct_shape(self, embedder: EmbeddingGenerator):
        vecs = embedder.embed_batch(["hello world", "foo bar", ""])
        assert vecs.shape == (3, embedder.dimensions)
        assert vecs.dtype == np.float32

    def test_embed_empty_text_returns_zero_vector(self, embedder: EmbeddingGenerator):
        vec = embedder.embed("")
        assert vec.shape == (embedder.dimensions,)
        assert np.allclose(vec, 0.0)

    def test_embed_is_l2_normalized(self, embedder: EmbeddingGenerator):
        vec = embedder.embed("some meaningful text content here")
        norm = np.linalg.norm(vec)
        assert norm == pytest.approx(1.0, abs=1e-5)

    def test_embed_batch_l2_normalized(self, embedder: EmbeddingGenerator):
        vecs = embedder.embed_batch(["text one", "text two", "text three"])
        norms = np.linalg.norm(vecs, axis=1)
        for n in norms:
            assert n == pytest.approx(1.0, abs=1e-5)

    def test_similar_texts_produce_similar_vectors(self, embedder: EmbeddingGenerator):
        """Two semantically related texts should have higher cosine
        similarity than two unrelated texts."""
        v1 = embedder.embed("bitcoin cryptocurrency wallet")
        v2 = embedder.embed("crypto wallet bitcoin")
        v3 = embedder.embed("weather forecast rain")
        sim_related = float(np.dot(v1, v2))
        sim_unrelated = float(np.dot(v1, v3))
        assert sim_related > sim_unrelated

    def test_deterministic_embeddings(self, embedder: EmbeddingGenerator):
        """The same text must produce the same vector (reproducibility)."""
        v1 = embedder.embed("deterministic test text")
        v2 = embedder.embed("deterministic test text")
        assert np.allclose(v1, v2)

    def test_works_without_sentence_transformers(self):
        """The generator must work even when SentenceTransformer is absent."""
        import tgarchive.search.semantic_projection as mod

        original = mod._HAS_SENTENCE_TRANSFORMERS
        mod._HAS_SENTENCE_TRANSFORMERS = False
        try:
            gen = EmbeddingGenerator()
            assert gen.backend in ("tfidf_svd", "hash_bow")
            vec = gen.embed("test without sentence transformers")
            assert vec.shape == (gen.dimensions,)
        finally:
            mod._HAS_SENTENCE_TRANSFORMERS = original


# ── ID helper tests ───────────────────────────────────────────────────────


class TestIdHelpers:
    """Tests for stable vector ID generation."""

    def test_vector_id_is_stable(self):
        vid1 = semantic_vector_id("messages", 123)
        vid2 = semantic_vector_id("messages", 123)
        assert vid1 == vid2

    def test_vector_id_differs_by_table(self):
        vid1 = semantic_vector_id("messages", 123)
        vid2 = semantic_vector_id("users", 123)
        assert vid1 != vid2

    def test_vector_id_differs_by_source_id(self):
        vid1 = semantic_vector_id("messages", 123)
        vid2 = semantic_vector_id("messages", 456)
        assert vid1 != vid2

    def test_vector_id_is_positive_int64(self):
        vid = semantic_vector_id("messages", 999999)
        assert isinstance(vid, int)
        assert 0 < vid < (1 << 63)

    def test_semantic_id_string_format(self):
        sid = semantic_id_string("messages", 42)
        assert sid == "semantic:messages:42"


# ── SemanticProjection tests ─────────────────────────────────────────────


class TestSemanticProjection:
    """Tests for the semantic projection (vector + metadata storage)."""

    def test_project_single_text(self, projection: SemanticProjection):
        vid = projection.project(
            text="hello world",
            source_table="messages",
            source_id=1,
        )
        assert vid is not None
        assert isinstance(vid, int)
        assert projection.vector_count == 1

    def test_project_empty_text_returns_none(self, projection: SemanticProjection):
        vid = projection.project(
            text="",
            source_table="messages",
            source_id=1,
        )
        assert vid is None
        assert projection.vector_count == 0

    def test_project_stores_content_in_metadata(self, projection: SemanticProjection):
        text = "important message content"
        vid = projection.project(text=text, source_table="messages", source_id=5)
        assert vid is not None
        meta = projection.fetch_metadata([vid])
        assert vid in meta
        assert meta[vid]["content"] == text
        assert meta[vid]["text"] == text

    def test_project_stores_provenance(self, projection: SemanticProjection):
        vid = projection.project(
            text="provenance test", source_table="messages", source_id=10
        )
        assert vid is not None
        meta = projection.fetch_metadata([vid])
        assert "model_name" in meta[vid]
        assert "model_version" in meta[vid]
        assert "backend" in meta[vid]

    def test_project_is_idempotent(self, projection: SemanticProjection):
        """Re-projecting the same source should upsert, not duplicate."""
        vid1 = projection.project(
            text="first version", source_table="messages", source_id=20
        )
        vid2 = projection.project(
            text="second version", source_table="messages", source_id=20
        )
        assert vid1 == vid2
        assert projection.vector_count == 1
        meta = projection.fetch_metadata([vid1])
        assert meta[vid1]["content"] == "second version"

    def test_project_batch(self, projection: SemanticProjection):
        result = projection.project_batch(
            texts=["text one", "text two", "text three"],
            source_table="messages",
            source_ids=[1, 2, 3],
        )
        assert isinstance(result, ProjectionResult)
        assert result.projected == 3
        assert result.skipped == 0
        assert len(result.vector_ids) == 3
        assert projection.vector_count == 3

    def test_project_batch_skips_empty(self, projection: SemanticProjection):
        result = projection.project_batch(
            texts=["text one", "", "text three"],
            source_table="messages",
            source_ids=[1, 2, 3],
        )
        assert result.projected == 2
        assert result.skipped == 1
        assert len(result.vector_ids) == 2

    def test_project_batch_mismatched_lengths_raises(self, projection: SemanticProjection):
        with pytest.raises(ValueError):
            projection.project_batch(
                texts=["a", "b"],
                source_table="messages",
                source_ids=[1],
            )

    def test_project_extra_metadata_preserved(self, projection: SemanticProjection):
        vid = projection.project(
            text="metadata test",
            source_table="messages",
            source_id=30,
            metadata={"channel_id": 42, "user_id": 99},
        )
        assert vid is not None
        meta = projection.fetch_metadata([vid])
        assert meta[vid]["channel_id"] == 42
        assert meta[vid]["user_id"] == 99

    def test_load_all_vectors(self, projection: SemanticProjection):
        projection.project_batch(
            texts=["alpha", "beta", "gamma"],
            source_table="messages",
            source_ids=[1, 2, 3],
        )
        vectors, ids, metas = projection.load_all_vectors()
        assert vectors.shape == (3, projection.embedder.dimensions)
        assert len(ids) == 3
        assert len(metas) == 3
        for m in metas:
            assert "content" in m

    def test_project_events(self, projection: SemanticProjection):
        events = [
            {
                "source_table": "messages",
                "source_key": 100,
                "payload": {"content": "event message one"},
            },
            {
                "source_table": "messages",
                "source_key": 101,
                "payload": {"content": "event message two"},
            },
        ]
        result = projection.project_events(events)
        assert result.projected == 2
        assert projection.vector_count == 2


# ── SemanticSearchEngine tests ───────────────────────────────────────────


class TestSemanticSearchEngine:
    """Tests for the semantic search engine."""

    def _index_corpus(self, engine: SemanticSearchEngine) -> None:
        """Index a small corpus of texts for search tests."""
        corpus = [
            ("bitcoin cryptocurrency wallet", "messages", 1),
            ("ethereum blockchain defi", "messages", 2),
            ("weather forecast rain sunny", "messages", 3),
            ("python programming code", "messages", 4),
            ("crypto exchange trading", "messages", 5),
        ]
        for text, table, sid in corpus:
            engine.index(text, table, sid)

    def test_index_single(self, engine: SemanticSearchEngine):
        vid = engine.index("test message", "messages", 1)
        assert vid is not None
        assert engine.stats["vector_count"] == 1

    def test_search_returns_results(self, engine: SemanticSearchEngine):
        self._index_corpus(engine)
        results = engine.search("bitcoin wallet", top_k=5, threshold=0.0)
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_content_is_populated(self, engine: SemanticSearchEngine):
        """FIX: SearchResult.content must not be empty (legacy bug)."""
        self._index_corpus(engine)
        results = engine.search("bitcoin", top_k=5, threshold=0.0)
        assert len(results) > 0
        for r in results:
            assert r.content  # must be non-empty
            assert isinstance(r.content, str)

    def test_search_score_is_similarity_not_distance(self, engine: SemanticSearchEngine):
        """FIX: score must be a similarity (higher = better), not a distance.

        The legacy implementation exposed cosine distance directly as the
        score, meaning identical texts got score ~0 and unrelated texts
        got higher scores.  The fix ensures score is a similarity in
        [0, 1] where 1.0 = identical.
        """
        self._index_corpus(engine)
        results = engine.search("bitcoin cryptocurrency wallet", top_k=5, threshold=0.0)
        assert len(results) > 0
        # The top result should be the exact match with high similarity.
        top = results[0]
        assert top.score > 0.5  # similarity, not distance
        assert top.content == "bitcoin cryptocurrency wallet"
        # All scores in [0, 1].
        for r in results:
            assert 0.0 <= r.score <= 1.0

    def test_search_results_sorted_by_score_desc(self, engine: SemanticSearchEngine):
        self._index_corpus(engine)
        results = engine.search("crypto", top_k=5, threshold=0.0)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_threshold_filters(self, engine: SemanticSearchEngine):
        self._index_corpus(engine)
        # Very high threshold → few or no results.
        results = engine.search("bitcoin", top_k=10, threshold=0.99)
        high = len(results)
        # Low threshold → more results.
        results = engine.search("bitcoin", top_k=10, threshold=0.0)
        low = len(results)
        assert low >= high

    def test_search_empty_query_returns_empty(self, engine: SemanticSearchEngine):
        self._index_corpus(engine)
        assert engine.search("", top_k=5) == []
        assert engine.search("   ", top_k=5) == []

    def test_search_on_empty_store_returns_empty(self, engine: SemanticSearchEngine):
        results = engine.search("anything", top_k=5, threshold=0.0)
        assert results == []

    def test_search_metadata_contains_provenance(self, engine: SemanticSearchEngine):
        self._index_corpus(engine)
        results = engine.search("bitcoin", top_k=5, threshold=0.0)
        assert len(results) > 0
        for r in results:
            assert "model_name" in r.metadata
            assert "model_version" in r.metadata

    def test_search_top_result_is_most_similar(self, engine: SemanticSearchEngine):
        """The most semantically similar text should rank first."""
        self._index_corpus(engine)
        results = engine.search("bitcoin cryptocurrency", top_k=5, threshold=0.0)
        assert len(results) > 0
        assert results[0].content == "bitcoin cryptocurrency wallet"

    def test_stats(self, engine: SemanticSearchEngine):
        engine.index("test", "messages", 1)
        stats = engine.stats
        assert "vector_count" in stats
        assert "qihse_available" in stats
        assert "embedding_backend" in stats
        assert stats["vector_count"] == 1


# ── Module-level function tests ──────────────────────────────────────────


class TestSemanticSearchFunction:
    """Tests for the module-level semantic_search() function."""

    def test_semantic_search_function(self, tmp_db_path: Path):
        # Index some texts first.
        with SemanticSearchEngine(tmp_db_path) as eng:
            eng.index_batch(
                texts=["machine learning model", "deep neural network"],
                source_table="messages",
                source_ids=[1, 2],
            )
        # Search via the module-level function.
        results = semantic_search(
            "machine learning", tmp_db_path, limit=10, threshold=0.0
        )
        assert len(results) > 0
        assert isinstance(results[0], SearchResult)
        assert results[0].content  # content populated (bug fix)

    def test_semantic_search_function_empty_store(self, tmp_db_path: Path):
        results = semantic_search("query", tmp_db_path, limit=10)
        assert results == []

    def test_semantic_search_function_threshold(self, tmp_db_path: Path):
        with SemanticSearchEngine(tmp_db_path) as eng:
            eng.index("bitcoin wallet crypto", "messages", 1)
            eng.index("weather rain forecast", "messages", 2)
        # High threshold should filter out dissimilar results.
        results = semantic_search(
            "bitcoin cryptocurrency", tmp_db_path, limit=10, threshold=0.9
        )
        for r in results:
            assert r.score >= 0.9


# ── Numpy fallback tests ─────────────────────────────────────────────────


class TestNumpyFallback:
    """Tests that the numpy fallback path works correctly."""

    def test_numpy_fallback_search(self, tmp_db_path: Path, embedder: EmbeddingGenerator):
        """Force the numpy fallback by constructing a projection whose
        QIHSE index is unavailable, then verify search still works."""
        # Index via a normal projection (stores BLOBs in sidecar).
        with SemanticProjection(tmp_db_path, embedding_generator=embedder) as proj:
            proj.project_batch(
                texts=["alpha beta gamma", "delta epsilon zeta"],
                source_table="messages",
                source_ids=[1, 2],
            )

        # Build an engine and force numpy fallback by disabling QIHSE.
        engine = SemanticSearchEngine(tmp_db_path, embedding_generator=embedder)
        engine._projection._qihse_available = False
        engine._projection._qihse_index = None
        try:
            results = engine.search("alpha beta", top_k=5, threshold=0.0)
            assert len(results) > 0
            assert results[0].content  # content populated
            assert results[0].score > 0.0  # similarity, not distance
        finally:
            engine.close()

    def test_numpy_fallback_score_is_similarity(self, tmp_db_path: Path):
        """In numpy fallback, identical text should have score ~1.0."""
        with SemanticSearchEngine(tmp_db_path) as eng:
            eng.index("exact duplicate text", "messages", 1)
            eng._projection._qihse_available = False
            eng._projection._qihse_index = None
            results = eng.search("exact duplicate text", top_k=5, threshold=0.0)
            assert len(results) > 0
            assert results[0].score > 0.9  # near-identical → high similarity


# ── Integration: distance vs similarity regression ───────────────────────


class TestDistanceSimilarityRegression:
    """Regression tests for the distance/similarity bug fix."""

    def test_identical_text_has_high_score(self, tmp_db_path: Path):
        """Searching for the exact indexed text must return score ~1.0,
        not ~0.0 (which would indicate distance was used as score)."""
        text = "unique searchable content for regression test"
        with SemanticSearchEngine(tmp_db_path) as eng:
            eng.index(text, "messages", 1)
            results = eng.search(text, top_k=5, threshold=0.0)
            assert len(results) > 0
            assert results[0].score > 0.8, (
                f"Expected high similarity score for identical text, "
                f"got {results[0].score} (distance/similarity bug?)"
            )

    def test_dissimilar_text_has_lower_score(self, tmp_db_path: Path):
        """A dissimilar query should produce a lower score than a similar one."""
        with SemanticSearchEngine(tmp_db_path) as eng:
            eng.index("bitcoin cryptocurrency wallet", "messages", 1)
            similar = eng.search("bitcoin crypto wallet", top_k=1, threshold=0.0)
            dissimilar = eng.search("weather forecast rain", top_k=1, threshold=0.0)
            if similar and dissimilar:
                assert similar[0].score > dissimilar[0].score
