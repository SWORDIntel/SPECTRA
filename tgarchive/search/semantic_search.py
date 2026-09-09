"""Semantic search over the QIHSE vector store.

Replaces the legacy ChromaDB/numpy ``semantic_search`` implementation.
Queries the QIHSE vector database (``spectra.db.semantic.qdb``) and
converts results into :class:`SearchResult` objects with **correct**
distance/similarity semantics.

Bug fixes vs. the legacy implementation
---------------------------------------
The old ``tgarchive/ai/semantic_search.py`` had two correctness bugs:

1. **Distance exposed as score.**  ChromaDB returns *cosine distance*
   (0 = identical, 2 = opposite) but the old code used it directly as
   ``SearchResult.score``, producing *lower* scores for *better* matches.
   This module ensures ``score`` is always a **similarity** in ``[0, 1]``
   (1.0 = identical, 0.0 = orthogonal).  When a backend returns a
   distance, it is converted via ``similarity = 1.0 - distance``.

2. **Empty content.**  The old code populated ``SearchResult.content``
   from ``metadata["content"]`` but never *wrote* ``content`` into the
   metadata, so results always had empty content.  This module stores
   ``content`` (and ``text``) in the metadata sidecar on every
   projection, so search results always carry their source text.

Graceful degradation
--------------------
If the QIHSE vector backend is unavailable (missing library, open
failure), the engine falls back to an in-memory numpy cosine-similarity
index loaded from the metadata sidecar.  The numpy fallback uses the
**same** metadata model and the **same** correct distance→similarity
conversion, so behaviour is consistent across backends.

Usage
-----
::

    from tgarchive.search.semantic_search import semantic_search

    for result in semantic_search("crypto wallet", "spectra.db", limit=20):
        print(result.id, result.score, result.content[:80])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .semantic_projection import (
    EmbeddingGenerator,
    SemanticProjection,
    semantic_id_string,
)

logger = logging.getLogger(__name__)


# ── SearchResult ──────────────────────────────────────────────────────────


@dataclass
class SearchResult:
    """A single semantic search result.

    Attributes:
        id: Vector identifier (the integer QIHSE vector ID or the
            canonical ``semantic:<table>:<id>`` string).
        content: The source text that was embedded (truncated to 500
            chars at projection time).
        score: Cosine **similarity** in ``[0, 1]`` — higher is better.
            This is *not* a distance; the legacy bug of exposing raw
            distance as the score has been fixed.
        metadata: Full metadata dict including ``source_table``,
            ``source_id``, ``model_name``, ``model_version``, etc.
    """

    id: Any
    content: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (JSON-safe)."""
        return {
            "id": self.id,
            "content": self.content,
            "score": float(self.score),
            "metadata": self.metadata,
        }


# ── SemanticSearchEngine ─────────────────────────────────────────────────


class SemanticSearchEngine:
    """Semantic search engine backed by the QIHSE vector store.

    The engine embeds the query using the same
    :class:`EmbeddingGenerator` used at projection time, searches the
    QIHSE vector store for the top-*k* nearest vectors, fetches their
    metadata from the SQLite sidecar, and returns :class:`SearchResult`
    objects with correct similarity scores.

    Args:
        db_path: Path to the main SPECTRA SQLite database.  The QIHSE
            vector DB and metadata sidecar are derived from this path
            (``<db_path>.semantic.qdb`` and
            ``<db_path>.semantic.meta.db``).
        embedding_generator: Optional pre-built :class:`EmbeddingGenerator`.
            A default one is created if omitted.
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        embedding_generator: Optional[EmbeddingGenerator] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.embedder = embedding_generator or EmbeddingGenerator()
        self._projection = SemanticProjection(
            self.db_path,
            embedding_generator=self.embedder,
        )

    # -- indexing -----------------------------------------------------------

    def index(
        self,
        text: str,
        source_table: str,
        source_id: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """Index a single text for semantic search.

        Delegates to :class:`SemanticProjection.project`.

        Returns:
            The vector ID, or ``None`` if the text was empty.
        """
        return self._projection.project(
            text=text,
            source_table=source_table,
            source_id=source_id,
            metadata=metadata,
        )

    def index_batch(
        self,
        texts: List[str],
        source_table: str,
        source_ids: List[Any],
        metadata_list: Optional[List[Optional[Dict[str, Any]]]] = None,
    ) -> int:
        """Index a batch of texts. Returns the number successfully projected."""
        result = self._projection.project_batch(
            texts=texts,
            source_table=source_table,
            source_ids=source_ids,
            metadata_list=metadata_list,
        )
        return result.projected

    # -- search -------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 50,
        threshold: float = 0.5,
    ) -> List[SearchResult]:
        """Search for texts semantically similar to *query*.

        Args:
            query: Natural-language search query.
            top_k: Maximum number of results to return.
            threshold: Minimum cosine similarity (in ``[0, 1]``) for a
                result to be included.  Results below this are filtered
                out.

        Returns:
            List of :class:`SearchResult` sorted by score descending.
            Each result's ``score`` is a **similarity** (higher = better),
            fixing the legacy bug where distance was exposed as score.
            Each result's ``content`` is populated from stored metadata,
            fixing the legacy bug where content was always empty.
        """
        if not query or not query.strip():
            return []
        if top_k < 1:
            return []

        query_vector = self.embedder.embed(query)
        if not np.any(query_vector):
            return []

        if self._projection.qihse_available:
            raw_results, is_distance = self._search_qihse(query_vector, top_k)
        elif self._projection.keystone_available:
            raw_results, is_distance = self._search_keystone(query_vector, top_k)
        else:
            raw_results, is_distance = self._search_numpy(query_vector, top_k)

        # Convert to SearchResult with correct similarity scores.
        # FIX (legacy bug): the old implementation exposed raw distance
        # directly as the score.  We explicitly convert distance→similarity
        # (1.0 - distance for cosine) when the backend returns a distance,
        # and clamp the final value to [0, 1].
        results: List[SearchResult] = []
        for vid, score, meta in raw_results:
            similarity = _to_similarity(score, is_distance=is_distance)
            if similarity < threshold:
                continue
            content = meta.get("content") or meta.get("text") or ""
            results.append(
                SearchResult(
                    id=vid,
                    content=content,
                    score=float(similarity),
                    metadata=meta,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    # -- backends -----------------------------------------------------------

    def _search_qihse(
        self,
        query_vector: np.ndarray,
        top_k: int,
    ) -> tuple[List[tuple[int, float, Dict[str, Any]]], bool]:
        """Search via the QIHSE vector backend.

        QIHSE's :meth:`QihseVectorIndex.search` returns a cosine
        **similarity** score directly (confirmed empirically: ~1.0 for
        identical vectors).  We therefore return ``is_distance=False``
        so :func:`_to_similarity` uses the value as-is.

        Returns:
            Tuple of ``(results, is_distance)``.
        """
        assert self._projection._qihse_index is not None
        try:
            hits = self._projection._qihse_index.search(
                [float(x) for x in query_vector],
                limit=top_k,
            )
        except Exception as exc:
            logger.warning("QIHSE search failed (%s); falling back to numpy.", exc)
            return self._search_numpy(query_vector, top_k)
        if not hits:
            return [], False
        ids = [int(h["id"]) for h in hits]
        scores = [float(h["score"]) for h in hits]
        meta_map = self._projection.fetch_metadata(ids)
        results: List[tuple[int, float, Dict[str, Any]]] = []
        for vid, score in zip(ids, scores):
            meta = meta_map.get(vid, {})
            if not meta:
                # No metadata in sidecar — construct a minimal record.
                meta = {"content": "", "text": ""}
            results.append((vid, score, meta))
        return results, False  # QIHSE returns similarity, not distance

    def _search_keystone(
        self,
        query_vector: np.ndarray,
        top_k: int,
    ) -> tuple[List[tuple[int, float, Dict[str, Any]]], bool]:
        """Search via the KEYSTONE vector engine (LSH + SIMD rerank).

        KEYSTONE's :meth:`KeystoneVectorIndex.search` returns cosine
        **similarity** (converted from distance at the ctypes layer).
        We return ``is_distance=False`` so :func:`_to_similarity` uses
        the value as-is.

        Falls back to numpy if KEYSTONE search fails.
        """
        assert self._projection._keystone_index is not None
        try:
            hits = self._projection._keystone_index.search(
                [float(x) for x in query_vector],
                limit=top_k,
            )
        except Exception as exc:
            logger.warning("KEYSTONE vector search failed (%s); falling back to numpy.", exc)
            return self._search_numpy(query_vector, top_k)
        if not hits:
            return [], False
        ids = [int(h["id"]) for h in hits]
        scores = [float(h["score"]) for h in hits]
        meta_map = self._projection.fetch_metadata(ids)
        results: List[tuple[int, float, Dict[str, Any]]] = []
        for vid, score in zip(ids, scores):
            meta = meta_map.get(vid, {})
            if not meta:
                meta = {"content": "", "text": ""}
            results.append((vid, score, meta))
        return results, False  # KEYSTONE returns similarity, not distance

    def _search_numpy(
        self,
        query_vector: np.ndarray,
        top_k: int,
    ) -> tuple[List[tuple[int, float, Dict[str, Any]]], bool]:
        """Brute-force cosine-similarity search over the numpy fallback store.

        Computes cosine **similarity** directly (dot product of
        L2-normalised vectors), which is already a similarity in
        ``[-1, 1]``.  We return ``is_distance=False`` so
        :func:`_to_similarity` clamps rather than inverting.

        Returns:
            Tuple of ``(results, is_distance)``.
        """
        vectors, ids, metas = self._projection.load_all_vectors()
        if vectors.size == 0 or not ids:
            return [], False
        query_norm = query_vector / (np.linalg.norm(query_vector) + 1e-10)
        vec_norms = vectors / (
            np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10
        )
        similarities = vec_norms @ query_norm  # (n,) cosine similarities
        top_indices = np.argsort(similarities)[::-1][:top_k]
        results: List[tuple[int, float, Dict[str, Any]]] = []
        for idx in top_indices:
            results.append((ids[int(idx)], float(similarities[int(idx)]), metas[int(idx)]))
        return results, False  # numpy computes similarity directly

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Close the underlying projection resources."""
        self._projection.close()

    def __enter__(self) -> "SemanticSearchEngine":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def stats(self) -> Dict[str, Any]:
        """Return engine statistics."""
        return {
            "vector_count": self._projection.vector_count,
            "qihse_available": self._projection.qihse_available,
            "keystone_available": self._projection.keystone_available,
            "vector_backend": self._projection.vector_backend,
            "embedding_backend": self.embedder.backend,
            "embedding_dimensions": self.embedder.dimensions,
            "model_name": self.embedder.provenance.model_name,
            "model_version": self.embedder.provenance.model_version,
        }


# ── Module-level convenience function ────────────────────────────────────


def semantic_search(
    query: str,
    db_path: Path | str,
    limit: int = 50,
    threshold: float = 0.5,
) -> List[SearchResult]:
    """Perform a semantic search against the QIHSE vector store.

    This is the primary module-level entry point.  It creates a
    short-lived :class:`SemanticSearchEngine`, executes the query, and
    closes the engine.

    Args:
        query: Natural-language search query.
        db_path: Path to the SPECTRA SQLite database.
        limit: Maximum number of results (default 50).
        threshold: Minimum cosine similarity in ``[0, 1]`` (default 0.5).

    Returns:
        List of :class:`SearchResult` sorted by similarity descending.
        ``score`` is a similarity (higher = better), **not** a distance.
        ``content`` is populated from stored metadata.
    """
    with SemanticSearchEngine(db_path) as engine:
        return engine.search(query, top_k=limit, threshold=threshold)


# ── Helpers ───────────────────────────────────────────────────────────────


def _to_similarity(score: float, *, is_distance: bool = False) -> float:
    """Normalise a raw score into a cosine similarity in ``[0, 1]``.

    The legacy implementation exposed cosine **distance** (where 0 means
    identical) directly as the score, inverting the interpretation: lower
    scores meant better matches.  This function fixes that:

    * If *is_distance* is ``True``, the value is treated as a cosine
      distance and converted via ``similarity = 1.0 - distance``.
    * If *is_distance* is ``False``, the value is already a similarity
      and is used directly.
    * The result is always clamped to ``[0, 1]``.

    Both the QIHSE backend (which returns similarity directly, confirmed
    empirically: ~1.0 for identical vectors) and the numpy fallback
    (which computes cosine similarity directly) pass
    ``is_distance=False``.  The ``is_distance=True`` path is available
    for any future backend that returns raw cosine distance, ensuring the
    distance→similarity fix is always applied correctly.
    """
    if is_distance:
        similarity = 1.0 - score
    else:
        similarity = score
    return max(0.0, min(1.0, similarity))


__all__ = [
    "SearchResult",
    "SemanticSearchEngine",
    "semantic_search",
]
