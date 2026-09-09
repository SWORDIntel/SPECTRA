"""Semantic embedding projection for the QIHSE vector store.

Generates dense vector embeddings from text and projects them into the
QIHSE vector database (``spectra.db.semantic.qdb``) with a SQLite
metadata sidecar (``spectra.db.semantic.meta.db``).  This module is the
projection half of the durable indexing pipeline::

    Message/Media saved -> IndexOutbox
      -> IndexProjector
        -> SemanticProjection.project()
          -> EmbeddingGenerator produces 384-dim vector
            -> QIHSE vector store (spectra.db.semantic.qdb)
            -> metadata sidecar  (spectra.db.semantic.meta.db)

Embedding generation degrades gracefully so the projection works on
air-gapped, CPU-only, dependency-light hosts:

1. **SentenceTransformer** (``all-MiniLM-L6-v2``, 384 dims) — best
   quality, requires the ``sentence-transformers`` package and a model
   download (fits under the 2 GB VRAM ceiling).
2. **TF-IDF + random projection** (``scikit-learn`` + ``numpy``, 384
   dims) — deterministic, stateless, CPU-only.  A
   :class:`~sklearn.feature_extraction.text.HashingVectorizer` produces
   TF-IDF-style sparse features which are projected to 384 dimensions via
   a fixed Gaussian random matrix (the Johnson-Lindenstrauss transform
   that :class:`~sklearn.decomposition.TruncatedSVD` approximates).
3. **Hash-based bag-of-words** (``numpy`` only, 384 dims) — zero
   external dependencies.  Tokens are hashed into 384 buckets with sign
   alternation, then L2-normalised.

The active model name and version are stored as provenance metadata on
every projected vector so projections can be replayed and audited.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import logging

import numpy as np

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

EMBEDDING_DIMENSIONS = 384
SEMANTIC_ID_PREFIX = "semantic"
_PROJECTION_VERSION = "1.0"
_TOKEN_RE = re.compile(r"[A-Za-z0-9_@.+-]+")
# Memoized token → (bucket, sign) cache for _embed_hash_bow. Token vocabulary
# is small and massively repetitive across events, so caching avoids redundant
# blake2b calls. Uses digest_size=8 (matching the original implementation).
_TOKEN_HASH_SEM_CACHE: dict[str, tuple[int, float]] = {}
_TOKEN_HASH_SEM_CACHE_MAX = 1_000_000


def _token_hash_sem(token: str, dimensions: int) -> tuple[int, float]:
    """Memoized token → (bucket, sign) for semantic hash-bow embeddings.

    Uses digest_size=8 and h[:4] for position, matching the original
    inline implementation exactly (bit-identical vectors).
    """
    entry = _TOKEN_HASH_SEM_CACHE.get(token)
    if entry is None:
        h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        entry = (
            int.from_bytes(h[:4], "little") % dimensions,
            1.0 if (h[4] & 1) == 0 else -1.0,
        )
        if len(_TOKEN_HASH_SEM_CACHE) < _TOKEN_HASH_SEM_CACHE_MAX:
            _TOKEN_HASH_SEM_CACHE[token] = entry
    return entry

# ── Optional dependencies (graceful fallback) ──────────────────────────────

try:  # pragma: no cover - exercised only when the package is installed
    from sentence_transformers import SentenceTransformer  # type: ignore

    _HAS_SENTENCE_TRANSFORMERS = True
except Exception:  # pragma: no cover
    _HAS_SENTENCE_TRANSFORMERS = False

try:  # pragma: no cover
    from sklearn.feature_extraction.text import HashingVectorizer  # type: ignore

    _HAS_SKLEARN = True
except Exception:  # pragma: no cover
    _HAS_SKLEARN = False

# Allow forcing a backend via env var (e.g. for tests that need fast,
# deterministic embeddings without model downloads).
_FORCE_BACKEND = os.environ.get("SPECTRA_EMBEDDING_BACKEND", "").strip().lower()
if _FORCE_BACKEND == "hash_bow":
    _HAS_SENTENCE_TRANSFORMERS = False
    _HAS_SKLEARN = False
elif _FORCE_BACKEND == "tfidf_svd":
    _HAS_SENTENCE_TRANSFORMERS = False
elif _FORCE_BACKEND == "sentence_transformer":
    _HAS_SKLEARN = False  # force ST even if sklearn is available


# ── Embedding generator ────────────────────────────────────────────────────


@dataclass(frozen=True)
class EmbeddingProvenance:
    """Provenance metadata describing how an embedding was produced.

    Attributes:
        model_name: Human-readable model identifier.
        model_version: Version string for replayability/auditing.
        backend: One of ``"sentence_transformer"``, ``"tfidf_svd"``,
            ``"hash_bow"``.
        dimensions: Dimensionality of the produced vectors.
    """

    model_name: str
    model_version: str
    backend: str
    dimensions: int = EMBEDDING_DIMENSIONS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "backend": self.backend,
            "dimensions": self.dimensions,
        }


class EmbeddingGenerator:
    """Generate 384-dimensional L2-normalised embeddings with graceful fallback.

    The generator selects the best available backend at construction time
    and reuses it for all subsequent calls.  Backend selection order:

    1. ``sentence_transformer`` — requires ``sentence-transformers``.
    2. ``tfidf_svd`` — requires ``scikit-learn``.
    3. ``hash_bow`` — requires only ``numpy``.

    All backends produce vectors of shape ``(EMBEDDING_DIMENSIONS,)`` that
    are L2-normalised to unit length, ensuring cosine-similarity search
    works correctly regardless of the active backend.

    Args:
        model_name: HuggingFace model name for the SentenceTransformer
            backend (ignored by other backends).
        device: Device for SentenceTransformer inference (``"cpu"`` by
            default — no GPU required).
        dimensions: Output dimensionality (default 384).
        cache_dir: Optional model cache directory for SentenceTransformer.
        st_batch_size: Mini-batch size for SentenceTransformer ``encode()``
            (default 32). Larger values use more memory but improve
            throughput on CPU/GPU.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: str = "cpu",
        dimensions: int = EMBEDDING_DIMENSIONS,
        cache_dir: Optional[Path] = None,
        st_batch_size: int = 32,
    ) -> None:
        self._requested_model = model_name
        self._device = device
        self._dimensions = dimensions
        self._cache_dir = cache_dir
        self._st_batch_size = st_batch_size
        self._st_model: Any = None
        self._hashing_vectorizer: Any = None
        self._projection_matrix: Optional[np.ndarray] = None
        self._backend: str = ""
        self._provenance = self._select_backend()

    # -- public API ---------------------------------------------------------

    @property
    def provenance(self) -> EmbeddingProvenance:
        """Provenance describing the active embedding backend."""
        return self._provenance

    @property
    def backend(self) -> str:
        """Active backend identifier."""
        return self._backend

    @property
    def dimensions(self) -> int:
        """Dimensionality of produced vectors."""
        return self._dimensions

    def embed(self, text: str) -> np.ndarray:
        """Embed a single text into a 1-D float32 vector of length ``dimensions``.

        Args:
            text: Input text.

        Returns:
            L2-normalised ``np.ndarray`` of shape ``(dimensions,)``.
        """
        if not text or not text.strip():
            return np.zeros(self._dimensions, dtype=np.float32)
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        """Embed multiple texts into a 2-D float32 array.

        Args:
            texts: Sequence of input strings.

        Returns:
            ``np.ndarray`` of shape ``(len(texts), dimensions)``,
            L2-normalised along axis 1.
        """
        cleaned = [t if t else "" for t in texts]
        if self._backend == "sentence_transformer":
            vectors = self._embed_sentence_transformer(cleaned)
        elif self._backend == "tfidf_svd":
            vectors = self._embed_tfidf_svd(cleaned)
        else:
            vectors = self._embed_hash_bow(cleaned)
        return self._l2_normalize(vectors).astype(np.float32)

    # -- backend selection --------------------------------------------------

    def _select_backend(self) -> EmbeddingProvenance:
        """Pick the best available backend and initialise it."""
        if _HAS_SENTENCE_TRANSFORMERS:
            try:
                self._st_model = SentenceTransformer(
                    self._requested_model,
                    device=self._device,
                    cache_folder=str(self._cache_dir) if self._cache_dir else None,
                )
                # sentence-transformers >=6.0 renamed this method; support both.
                get_dims = getattr(
                    self._st_model,
                    "get_embedding_dimension",
                    None,
                ) or getattr(self._st_model, "get_sentence_embedding_dimension")
                actual_dims = get_dims()
                if actual_dims != self._dimensions:
                    logger.info(
                        "SentenceTransformer model %s produces %d dims; "
                        "using model-native dimensionality.",
                        self._requested_model,
                        actual_dims,
                    )
                    self._dimensions = actual_dims
                self._backend = "sentence_transformer"
                logger.info("EmbeddingGenerator: using SentenceTransformer backend")
                return EmbeddingProvenance(
                    model_name=self._requested_model,
                    model_version="st-1.0",
                    backend="sentence_transformer",
                    dimensions=self._dimensions,
                )
            except Exception as exc:  # pragma: no cover - model download failure
                logger.warning(
                    "SentenceTransformer init failed (%s); falling back.", exc
                )
                self._st_model = None

        if _HAS_SKLEARN:
            self._hashing_vectorizer = HashingVectorizer(
                n_features=4096,
                alternate_sign=True,
                norm=None,
                ngram_range=(1, 1),
                lowercase=True,
            )
            rng = np.random.default_rng(seed=20240101)
            self._projection_matrix = (
                rng.standard_normal((4096, self._dimensions)).astype(np.float32)
                / np.sqrt(self._dimensions)
            )
            self._backend = "tfidf_svd"
            logger.info("EmbeddingGenerator: using TF-IDF + random projection backend")
            return EmbeddingProvenance(
                model_name="tfidf-rp-384",
                model_version="1.0",
                backend="tfidf_svd",
                dimensions=self._dimensions,
            )

        self._backend = "hash_bow"
        logger.info("EmbeddingGenerator: using hash bag-of-words backend")
        return EmbeddingProvenance(
            model_name="hash-bow-384",
            model_version="1.0",
            backend="hash_bow",
            dimensions=self._dimensions,
        )

    # -- backend implementations -------------------------------------------

    def _embed_sentence_transformer(self, texts: List[str]) -> np.ndarray:
        assert self._st_model is not None
        return np.asarray(
            self._st_model.encode(
                texts,
                batch_size=self._st_batch_size,
                convert_to_numpy=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )

    def _embed_tfidf_svd(self, texts: List[str]) -> np.ndarray:
        assert self._hashing_vectorizer is not None
        assert self._projection_matrix is not None
        sparse = self._hashing_vectorizer.transform(texts)
        # sparse: (n, 4096) CSR; project to (n, dimensions)
        projected = sparse @ self._projection_matrix
        return np.asarray(projected, dtype=np.float32)

    def _embed_hash_bow(self, texts: List[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self._dimensions), dtype=np.float32)
        for i, text in enumerate(texts):
            if not text:
                continue
            row = vectors[i]
            for token in _TOKEN_RE.findall(text.lower()):
                idx, sign = _token_hash_sem(token, self._dimensions)
                row[idx] += sign
        return vectors

    # -- utilities ----------------------------------------------------------

    @staticmethod
    def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
        """L2-normalise along axis 1, guarding against zero-norm rows."""
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return vectors / norms


# ── ID helpers ─────────────────────────────────────────────────────────────


def semantic_vector_id(source_table: str, source_id: Any) -> int:
    """Map a (source_table, source_id) pair to a stable positive int64 key.

    Uses BLAKE2b so identical inputs always produce the same vector ID,
    enabling idempotent upserts into the QIHSE store.
    """
    raw = f"{SEMANTIC_ID_PREFIX}:{source_table}:{source_id}".encode("utf-8")
    digest = hashlib.blake2b(raw, digest_size=8, person=b"SPECTRA-SID").digest()
    value = int.from_bytes(digest, "big", signed=False)
    return value & ((1 << 63) - 1)  # keep within signed int64 positive range


def semantic_id_string(source_table: str, source_id: Any) -> str:
    """Return the canonical ``semantic:<table>:<id>`` identifier string."""
    return f"{SEMANTIC_ID_PREFIX}:{source_table}:{source_id}"


# ── Metadata sidecar ──────────────────────────────────────────────────────


_SIDECAR_SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_vectors (
    vector_id      INTEGER PRIMARY KEY,
    semantic_id    TEXT NOT NULL UNIQUE,
    content        TEXT NOT NULL,
    source_table   TEXT,
    source_id      TEXT,
    model_name     TEXT,
    model_version  TEXT,
    backend        TEXT,
    dimensions     INTEGER,
    vector_blob    BLOB,
    metadata_json  TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_semantic_vectors_source
    ON semantic_vectors(source_table, source_id);
"""


def _connect_sidecar(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    # Performance PRAGMAs — critical for bulk drain throughput.
    # Default SQLite uses journal_mode=delete + synchronous=FULL which
    # does an fsync per INSERT. WAL + NORMAL is ~10x faster for writes.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-65536")  # 64MB cache (negative = kibibytes)
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
    conn.executescript(_SIDECAR_SCHEMA)
    conn.commit()
    return conn


# ── Semantic projection ───────────────────────────────────────────────────


@dataclass
class ProjectionResult:
    """Outcome of a projection batch.

    Attributes:
        projected: Number of vectors successfully projected.
        skipped: Number of inputs skipped (empty text).
        errors: List of error messages for failed projections.
        vector_ids: List of integer vector IDs that were upserted.
    """

    projected: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)
    vector_ids: List[int] = field(default_factory=list)


class SemanticProjection:
    """Project text into the QIHSE vector store as semantic embeddings.

    Each projection generates a 384-dimensional embedding via
    :class:`EmbeddingGenerator`, upserts the vector into the QIHSE vector
    database, and records metadata (content, source, model provenance) in
    a SQLite sidecar so that search results can reconstruct full context.

    If the QIHSE vector backend is unavailable, vectors are persisted as
    numpy BLOBs in the sidecar so that the numpy fallback search path in
    :mod:`tgarchive.search.semantic_search` can still operate.

    Args:
        db_path: Path to the main SPECTRA SQLite database.  The QIHSE
            vector DB and metadata sidecar are derived from this path.
        vector_db_path: Optional explicit path for the QIHSE ``.qdb``
            file.  Defaults to ``<db_path>.semantic.qdb``.
        meta_db_path: Optional explicit path for the metadata sidecar.
            Defaults to ``<db_path>.semantic.meta.db``.
        embedding_generator: Optional pre-built :class:`EmbeddingGenerator`.
            A default one is created if omitted.
        rebuild: If ``True``, truncate the QIHSE vector store on open.
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        vector_db_path: Optional[Path | str] = None,
        meta_db_path: Optional[Path | str] = None,
        embedding_generator: Optional[EmbeddingGenerator] = None,
        rebuild: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.vector_db_path = Path(vector_db_path) if vector_db_path else (
            self.db_path.parent / f"{self.db_path.name}.semantic.qdb"
        )
        self.meta_db_path = Path(meta_db_path) if meta_db_path else (
            self.db_path.parent / f"{self.db_path.name}.semantic.meta.db"
        )
        self.embedder = embedding_generator or EmbeddingGenerator()
        self._qihse_index: Any = None
        self._qihse_available = False
        self._keystone_index: Any = None
        self._keystone_available = False
        try:
            from .qihse_vector_backend import QihseVectorIndex

            self._qihse_index = QihseVectorIndex(self.vector_db_path, rebuild=rebuild)
            self._qihse_available = True
            logger.info("SemanticProjection: QIHSE vector store at %s", self.vector_db_path)
        except Exception as exc:
            logger.warning(
                "SemanticProjection: QIHSE vector backend unavailable (%s); "
                "trying KEYSTONE vector engine.",
                exc,
            )
            self._qihse_index = None
            self._qihse_available = False

        # KEYSTONE Vector Engine — LSH + SIMD, hardware-agnostic fallback
        # Used when QIHSE is unavailable, or as a parallel backend for
        # faster similarity search (30x faster than numpy at 100K vectors).
        if not self._qihse_available:
            keystone_vec_path = self.db_path.parent / f"{self.db_path.name}.keystone_vec.bin"
            try:
                from .keystone_vector_backend import KeystoneVectorIndex

                self._keystone_index = KeystoneVectorIndex(
                    keystone_vec_path,
                    dim=self.embedder.dimensions,
                    rebuild=rebuild,
                )
                self._keystone_available = True
                logger.info(
                    "SemanticProjection: KEYSTONE vector engine at %s (backend=%s)",
                    keystone_vec_path,
                    self._keystone_index.backend,
                )
            except Exception as exc:
                logger.warning(
                    "SemanticProjection: KEYSTONE vector engine unavailable (%s); "
                    "using numpy BLOB sidecar only.",
                    exc,
                )
                self._keystone_index = None
                self._keystone_available = False

        self._sidecar = _connect_sidecar(self.meta_db_path)
        self._batch_sidecar_rows: list[tuple] = []

    # -- public API ---------------------------------------------------------

    def project(
        self,
        text: str,
        source_table: str,
        source_id: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """Project a single text into the vector store.

        Args:
            text: Text to embed and store.
            source_table: Originating table name (e.g. ``"messages"``).
            source_id: Originating record ID.
            metadata: Optional extra metadata to persist alongside.

        Returns:
            The integer vector ID, or ``None`` if the text was empty.
        """
        result = self.project_batch(
            texts=[text],
            source_table=source_table,
            source_ids=[source_id],
            metadata_list=[metadata] if metadata else None,
        )
        return result.vector_ids[0] if result.vector_ids else None

    def project_batch(
        self,
        texts: Sequence[str],
        source_table: str,
        source_ids: Sequence[Any],
        metadata_list: Optional[Sequence[Optional[Dict[str, Any]]]] = None,
    ) -> ProjectionResult:
        """Project a batch of texts into the vector store.

        Args:
            texts: Texts to embed.
            source_table: Originating table name for all texts.
            source_ids: Originating record IDs (same length as *texts*).
            metadata_list: Optional per-text metadata.

        Returns:
            :class:`ProjectionResult` with counts and vector IDs.
        """
        if len(texts) != len(source_ids):
            raise ValueError("texts and source_ids must have the same length")
        if metadata_list is not None and len(metadata_list) != len(texts):
            raise ValueError("metadata_list must have the same length as texts")

        result = ProjectionResult()
        now = _utc_now()

        # Partition into non-empty texts for embedding.
        indices: List[int] = []
        clean_texts: List[str] = []
        for i, text in enumerate(texts):
            if not text or not str(text).strip():
                result.skipped += 1
                continue
            indices.append(i)
            clean_texts.append(str(text))

        if not clean_texts:
            return result

        try:
            vectors = self.embedder.embed_batch(clean_texts)
        except Exception as exc:
            result.errors.append(f"embedding failed: {exc}")
            return result

        prov = self.embedder.provenance
        meta_iter = metadata_list or [None] * len(texts)

        # Collect vectors for a single batch QIHSE upsert (avoids per-vector
        # container open/close overhead).
        batch_vector_ids: List[int] = []
        batch_vectors: List[List[float]] = []

        # Bulk blob serialization: convert the entire vector batch to bytes
        # once, then slice per-row. Avoids N separate np.asarray().tobytes()
        # calls and N small allocations.
        vec_arr = np.ascontiguousarray(vectors, dtype=np.float32)
        row_bytes = vec_arr.shape[1] * 4  # dimensions * sizeof(float32)
        vec_buf = vec_arr.tobytes()

        for local_idx, global_idx in enumerate(indices):
            text = clean_texts[local_idx]
            source_id = source_ids[global_idx]
            extra = meta_iter[global_idx] or {}
            vid = semantic_vector_id(source_table, source_id)
            sid = semantic_id_string(source_table, source_id)
            stored_metadata: Dict[str, Any] = {
                "text": text[:500],
                "content": text[:500],
                "source_table": source_table,
                "source_id": str(source_id),
                "model_name": prov.model_name,
                "model_version": prov.model_version,
                "backend": prov.backend,
                "dimensions": prov.dimensions,
            }
            stored_metadata.update(extra)
            try:
                # Collect for batch sidecar insert (deferred below)
                batch_vector_ids.append(vid)
                batch_vectors.append([float(x) for x in vectors[local_idx]])
                result.vector_ids.append(vid)
                result.projected += 1
                # Slice the pre-serialized vector buffer (byte-identical to
                # np.asarray(vectors[local_idx]).tobytes()).
                blob = vec_buf[local_idx * row_bytes:(local_idx + 1) * row_bytes]
                self._batch_sidecar_rows.append((
                    vid, sid, text[:500], source_table, str(source_id),
                    prov.model_name, prov.model_version, prov.backend,
                    prov.dimensions,
                    blob,
                    json.dumps(stored_metadata, default=str),
                    now,
                ))
            except Exception as exc:
                result.errors.append(f"store failed for {sid}: {exc}")

        # Batch sidecar insert — single executemany instead of per-vector INSERT
        if self._batch_sidecar_rows:
            try:
                self._sidecar.executemany(
                    """
                    INSERT INTO semantic_vectors
                        (vector_id, semantic_id, content, source_table, source_id,
                         model_name, model_version, backend, dimensions,
                         vector_blob, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(vector_id) DO UPDATE SET
                        semantic_id   = excluded.semantic_id,
                        content       = excluded.content,
                        source_table  = excluded.source_table,
                        source_id     = excluded.source_id,
                        model_name    = excluded.model_name,
                        model_version = excluded.model_version,
                        backend       = excluded.backend,
                        dimensions    = excluded.dimensions,
                        vector_blob   = excluded.vector_blob,
                        metadata_json = excluded.metadata_json,
                        created_at    = excluded.created_at
                    """,
                    self._batch_sidecar_rows,
                )
                self._batch_sidecar_rows.clear()
            except Exception as exc:
                result.errors.append(f"batch sidecar insert failed: {exc}")
                self._batch_sidecar_rows.clear()

        # Single batch QIHSE upsert for all vectors in this batch
        if batch_vector_ids and self._qihse_available and self._qihse_index is not None:
            try:
                self._qihse_index.upsert_no_flush(batch_vector_ids, batch_vectors)
            except Exception as exc:
                result.errors.append(f"batch QIHSE upsert failed: {exc}")

        # KEYSTONE vector engine upsert (fallback when QIHSE unavailable)
        if batch_vector_ids and self._keystone_available and self._keystone_index is not None:
            try:
                self._keystone_index.upsert_no_flush(batch_vector_ids, batch_vectors)
            except Exception as exc:
                result.errors.append(f"batch KEYSTONE vector upsert failed: {exc}")

        return result

    def project_events(
        self,
        events: Sequence[Dict[str, Any]],
    ) -> ProjectionResult:
        """Project outbox-style events into the vector store.

        Each event dict should contain ``source_table``, ``source_key``
        (or ``source_id``), and a ``payload`` dict with a ``content`` or
        ``text`` field.

        Args:
            events: Sequence of event dictionaries.

        Returns:
            :class:`ProjectionResult`.
        """
        texts: List[str] = []
        source_ids: List[Any] = []
        metadata_list: List[Optional[Dict[str, Any]]] = []
        source_table = "messages"
        for event in events:
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}
            text = payload.get("content") or payload.get("text") or ""
            sid = event.get("source_key", event.get("source_id"))
            st = event.get("source_table", source_table)
            if not texts:
                source_table = st
            texts.append(str(text))
            source_ids.append(sid)
            metadata_list.append(payload)
        return self.project_batch(
            texts=texts,
            source_table=source_table,
            source_ids=source_ids,
            metadata_list=metadata_list,
        )

    def close(self) -> None:
        """Close all open resources — flushes pending writes first."""
        if self._qihse_index is not None:
            try:
                self._qihse_index.flush()
            except Exception:
                pass
            try:
                self._qihse_index.close()
            except Exception:
                pass
            self._qihse_index = None
        if self._keystone_index is not None:
            try:
                self._keystone_index.flush()
            except Exception:
                pass
            try:
                self._keystone_index.close()
            except Exception:
                pass
            self._keystone_index = None
        try:
            self._sidecar.commit()
        except Exception:
            pass
        try:
            self._sidecar.close()
        except Exception:
            pass

    def flush(self) -> None:
        """Flush the underlying vector index (QIHSE WAL → snapshot, or KEYSTONE save)."""
        if self._qihse_available and self._qihse_index is not None:
            self._qihse_index.flush()
        if self._keystone_available and self._keystone_index is not None:
            self._keystone_index.flush()
        try:
            self._sidecar.commit()
        except Exception:
            pass

    def __enter__(self) -> "SemanticProjection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -- internals ----------------------------------------------------------

    def _store_vector(
        self,
        *,
        vector_id: int,
        semantic_id: str,
        content: str,
        source_table: str,
        source_id: str,
        vector: np.ndarray,
        metadata: Dict[str, Any],
        provenance: EmbeddingProvenance,
        created_at: str,
    ) -> None:
        """Persist a vector to QIHSE or KEYSTONE (if available) and metadata to the sidecar."""
        vector_list = [float(x) for x in vector]
        if self._qihse_available and self._qihse_index is not None:
            self._qihse_index.upsert_no_flush([vector_id], [vector_list])
        elif self._keystone_available and self._keystone_index is not None:
            self._keystone_index.upsert_no_flush([vector_id], [vector_list])
        # Always store the BLOB so the numpy fallback can reconstruct.
        blob = np.asarray(vector, dtype=np.float32).tobytes()
        self._sidecar.execute(
            """
            INSERT INTO semantic_vectors
                (vector_id, semantic_id, content, source_table, source_id,
                 model_name, model_version, backend, dimensions,
                 vector_blob, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(vector_id) DO UPDATE SET
                semantic_id   = excluded.semantic_id,
                content       = excluded.content,
                source_table  = excluded.source_table,
                source_id     = excluded.source_id,
                model_name    = excluded.model_name,
                model_version = excluded.model_version,
                backend       = excluded.backend,
                dimensions    = excluded.dimensions,
                vector_blob   = excluded.vector_blob,
                metadata_json = excluded.metadata_json,
                created_at    = excluded.created_at
            """,
            (
                vector_id,
                semantic_id,
                content[:500],
                source_table,
                source_id,
                provenance.model_name,
                provenance.model_version,
                provenance.backend,
                provenance.dimensions,
                blob,
                json.dumps(metadata, default=str),
                created_at,
            ),
        )
        self._sidecar.commit()

    def _store_vector_metadata_only(
        self,
        *,
        vector_id: int,
        semantic_id: str,
        content: str,
        source_table: str,
        source_id: str,
        vector: np.ndarray,
        metadata: Dict[str, Any],
        provenance: EmbeddingProvenance,
        created_at: str,
    ) -> None:
        """Persist vector metadata to the sidecar only (no QIHSE upsert).

        Used by ``project_batch`` to write sidecar metadata per-vector while
        deferring the QIHSE upsert to a single batch call.
        """
        blob = np.asarray(vector, dtype=np.float32).tobytes()
        self._sidecar.execute(
            """
            INSERT INTO semantic_vectors
                (vector_id, semantic_id, content, source_table, source_id,
                 model_name, model_version, backend, dimensions,
                 vector_blob, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(vector_id) DO UPDATE SET
                semantic_id   = excluded.semantic_id,
                content       = excluded.content,
                source_table  = excluded.source_table,
                source_id     = excluded.source_id,
                model_name    = excluded.model_name,
                model_version = excluded.model_version,
                backend       = excluded.backend,
                dimensions    = excluded.dimensions,
                vector_blob   = excluded.vector_blob,
                metadata_json = excluded.metadata_json,
                created_at    = excluded.created_at
            """,
            (
                vector_id,
                semantic_id,
                content[:500],
                source_table,
                source_id,
                provenance.model_name,
                provenance.model_version,
                provenance.backend,
                provenance.dimensions,
                blob,
                json.dumps(metadata, default=str),
                created_at,
            ),
        )

    # -- query helpers (used by semantic_search) ----------------------------

    def fetch_metadata(self, vector_ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
        """Fetch metadata for a set of vector IDs from the sidecar.

        Returns a mapping ``{vector_id: metadata_dict}`` where each
        metadata dict includes ``content``, ``source_table``,
        ``source_id``, and all stored provenance fields.
        """
        if not vector_ids:
            return {}
        placeholders = ",".join("?" * len(vector_ids))
        rows = self._sidecar.execute(
            f"""
            SELECT vector_id, content, source_table, source_id,
                   model_name, model_version, backend, dimensions,
                   metadata_json
              FROM semantic_vectors
             WHERE vector_id IN ({placeholders})
            """,
            tuple(vector_ids),
        ).fetchall()
        result: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            vid, content, st, sid, mn, mv, backend, dims, mjson = row
            meta: Dict[str, Any] = {}
            if mjson:
                try:
                    meta = json.loads(mjson)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
            meta.setdefault("content", content)
            meta.setdefault("text", content)
            meta.setdefault("source_table", st)
            meta.setdefault("source_id", sid)
            meta.setdefault("model_name", mn)
            meta.setdefault("model_version", mv)
            meta.setdefault("backend", backend)
            meta.setdefault("dimensions", dims)
            result[vid] = meta
        return result

    def load_all_vectors(self) -> tuple[np.ndarray, List[int], List[Dict[str, Any]]]:
        """Load all vectors and metadata from the sidecar (numpy fallback).

        Returns:
            Tuple of ``(vectors_array, vector_ids, metadatas)``.
        """
        rows = self._sidecar.execute(
            "SELECT vector_id, vector_blob, content, metadata_json "
            "FROM semantic_vectors WHERE vector_blob IS NOT NULL"
        ).fetchall()
        if not rows:
            return np.array([], dtype=np.float32), [], []
        ids: List[int] = []
        metas: List[Dict[str, Any]] = []
        vecs: List[np.ndarray] = []
        for vid, blob, content, mjson in rows:
            vec = np.frombuffer(blob, dtype=np.float32)
            vecs.append(vec)
            ids.append(vid)
            meta: Dict[str, Any] = {}
            if mjson:
                try:
                    meta = json.loads(mjson)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
            meta.setdefault("content", content)
            meta.setdefault("text", content)
            metas.append(meta)
        return np.vstack(vecs), ids, metas

    @property
    def qihse_available(self) -> bool:
        """Whether the QIHSE vector backend is active."""
        return self._qihse_available

    @property
    def keystone_available(self) -> bool:
        """Whether the KEYSTONE vector engine backend is active."""
        return self._keystone_available

    @property
    def vector_backend(self) -> str:
        """Active vector backend name: 'qihse', 'keystone', or 'numpy'."""
        if self._qihse_available:
            return "qihse"
        if self._keystone_available:
            return "keystone"
        return "numpy"

    @property
    def vector_count(self) -> int:
        """Total number of vectors in the sidecar."""
        row = self._sidecar.execute(
            "SELECT COUNT(*) FROM semantic_vectors"
        ).fetchone()
        return int(row[0]) if row else 0


# ── Helpers ───────────────────────────────────────────────────────────────


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "EmbeddingGenerator",
    "EmbeddingProvenance",
    "SemanticProjection",
    "ProjectionResult",
    "semantic_vector_id",
    "semantic_id_string",
    "EMBEDDING_DIMENSIONS",
]
