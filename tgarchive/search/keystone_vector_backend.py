"""KEYSTONE Vector Engine — ctypes bindings for SPECTRA.

Wraps the KEYSTONE Vector Engine (``libkeystone_vector.so``) which provides
hardware-agnostic vector similarity search with:

- LSH coarse index (random hyperplane projection) for sub-linear retrieval
- SIMD exact rerank (AVX-512 → AVX2 → AVX → SSE4.2 → NEON → scalar)
- CUDA soft-loaded backend (via dlopen)
- VPU (Myriad X) guarded backend (runtime socket probe)
- 8-level graceful fallback chain

This module mirrors the interface of :mod:`qihse_vector_backend` so it can
be used as a drop-in replacement or sibling backend for semantic search,
intelligence evidence vectors, and index projections.

Benchmark (Intel Xeon E5-2407, SSE4.2 + AVX, 384-dim float32):
    100K vectors: 2.36 ms/query, 423 q/s (30.8x faster than NumPy)
"""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# ── Constants (mirror keystone_vector_engine.h) ───────────────────────────

KEYSTONE_OK = 0
KEYSTONE_ERR_NULL = -1
KEYSTONE_ERR_PARAM = -2
KEYSTONE_ERR_DIM = -3
KEYSTONE_ERR_OOM = -4
KEYSTONE_ERR_CAPACITY = -5
KEYSTONE_ERR_IO = -6
KEYSTONE_ERR_INTERNAL = -7
KEYSTONE_ERR_BACKEND = -8

# Backend IDs
KEYSTONE_BACKEND_SCALAR = 0
KEYSTONE_BACKEND_VPU = 1
KEYSTONE_BACKEND_NEON = 2
KEYSTONE_BACKEND_SSE42 = 3
KEYSTONE_BACKEND_AVX = 4
KEYSTONE_BACKEND_AVX2 = 5
KEYSTONE_BACKEND_AVX512 = 6
KEYSTONE_BACKEND_CUDA = 7

# Metrics
KEYSTONE_METRIC_L2 = 0
KEYSTONE_METRIC_DOT = 1
KEYSTONE_METRIC_COSINE = 2

# Feature flags (from keystone_vec_detect_features)
KEYSTONE_F_SSE42 = 1 << 0
KEYSTONE_F_AVX = 1 << 1
KEYSTONE_F_AVX2 = 1 << 2
KEYSTONE_F_AVX512F = 1 << 3
KEYSTONE_F_NEON = 1 << 4
KEYSTONE_F_VPU = 1 << 5

_LOADED: dict[str, ctypes.CDLL] = {}


# ── ctypes Structures ─────────────────────────────────────────────────────


class _KeystoneVecConfig(ctypes.Structure):
    _fields_ = [
        ("dim", ctypes.c_uint32),
        ("capacity", ctypes.c_uint32),
        ("metric", ctypes.c_int),
        ("lsh_num_tables", ctypes.c_uint32),
        ("lsh_hash_bits", ctypes.c_uint32),
        ("lsh_probes", ctypes.c_uint32),
        ("rerank_k", ctypes.c_uint32),
        ("omp_threads", ctypes.c_int),
        ("force_backend", ctypes.c_int),
        ("vpu_socket_path", ctypes.c_char * 108),
        ("vpu_enabled", ctypes.c_int),
    ]


class _KeystoneVecResult(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint64),
        ("distance", ctypes.c_float),
    ]


# ── Library loading ───────────────────────────────────────────────────────


def _library_candidates() -> Iterable[Path]:
    """Yield candidate paths for libkeystone_vector.so."""
    explicit = os.getenv("KEYSTONE_VECTOR_LIB_PATH")
    if explicit:
        yield Path(explicit)

    spectra_root = Path(__file__).resolve().parent.parent.parent
    yield spectra_root / "KEYSTONE" / "vector_engine" / "libkeystone_vector.so"
    yield spectra_root / "libs" / "KEYSTONE" / "vector_engine" / "libkeystone_vector.so"
    yield Path("/usr/local/lib/libkeystone_vector.so")
    yield Path("/usr/lib/libkeystone_vector.so")
    yield Path("libkeystone_vector.so")


def _load_library() -> tuple[ctypes.CDLL, Path]:
    """Load and configure the KEYSTONE vector engine shared library.

    Uses RTLD_GLOBAL so the engine's dlsym(RTLD_DEFAULT, ...) calls can
    find kernel symbols (keystone_kernels_avx, etc.) that were compiled
    with different ISA flags in separate translation units.

    Raises:
        RuntimeError: if the library cannot be found or loaded.
    """
    for candidate in _library_candidates():
        if not candidate.exists():
            continue
        resolved = str(candidate.resolve())
        if resolved in _LOADED:
            return _LOADED[resolved], candidate
        # RTLD_GLOBAL is critical: the engine uses dlsym(RTLD_DEFAULT, ...)
        # to find SIMD kernel tables at runtime. Without GLOBAL, those
        # symbols are local to the .so and dlsym can't see them.
        mode = getattr(os, "RTLD_NOW", 0) | getattr(os, "RTLD_GLOBAL", 0)
        mode |= getattr(os, "RTLD_NODELETE", 0)
        try:
            library = ctypes.CDLL(resolved, mode=mode)
        except OSError as exc:
            logger.debug("Failed to load %s: %s", candidate, exc)
            continue
        required = (
            "keystone_vec_engine_create",
            "keystone_vec_engine_destroy",
            "keystone_vec_upsert_batch",
            "keystone_vec_search",
            "keystone_vec_search_batch",
            "keystone_vec_engine_count",
            "keystone_vec_engine_dim",
        )
        if not all(hasattr(library, sym) for sym in required):
            logger.debug("%s missing required symbols", candidate)
            continue
        _configure(library)
        _LOADED[resolved] = library
        logger.info("Loaded KEYSTONE vector engine from %s", candidate)
        return library, candidate
    raise RuntimeError("KEYSTONE vector engine library (libkeystone_vector.so) is unavailable")


def _configure(library: ctypes.CDLL) -> None:
    """Set up ctypes function signatures."""
    library.keystone_vec_detect_features.restype = ctypes.c_uint32
    library.keystone_vec_detect_features.argtypes = []

    library.keystone_vec_backend_name.restype = ctypes.c_char_p
    library.keystone_vec_backend_name.argtypes = [ctypes.c_int]

    library.keystone_vec_engine_create.restype = ctypes.c_int
    library.keystone_vec_engine_create.argtypes = [
        ctypes.POINTER(_KeystoneVecConfig),
        ctypes.POINTER(ctypes.c_void_p),
    ]

    library.keystone_vec_engine_destroy.restype = None
    library.keystone_vec_engine_destroy.argtypes = [ctypes.c_void_p]

    library.keystone_vec_engine_get_backend.restype = ctypes.c_int
    library.keystone_vec_engine_get_backend.argtypes = [ctypes.c_void_p]

    library.keystone_vec_upsert_batch.restype = ctypes.c_int
    library.keystone_vec_upsert_batch.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_uint32,
    ]

    library.keystone_vec_search.restype = ctypes.c_int
    library.keystone_vec_search.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_uint32,
        ctypes.POINTER(_KeystoneVecResult),
    ]

    library.keystone_vec_search_batch.restype = ctypes.c_int
    library.keystone_vec_search_batch.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(_KeystoneVecResult),
    ]

    library.keystone_vec_engine_dim.restype = ctypes.c_uint32
    library.keystone_vec_engine_dim.argtypes = [ctypes.c_void_p]

    library.keystone_vec_engine_count.restype = ctypes.c_uint64
    library.keystone_vec_engine_count.argtypes = [ctypes.c_void_p]

    if hasattr(library, "keystone_vec_save"):
        library.keystone_vec_save.restype = ctypes.c_int
        library.keystone_vec_save.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

    if hasattr(library, "keystone_vec_load"):
        library.keystone_vec_load.restype = ctypes.c_int
        library.keystone_vec_load.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_char_p,
        ]


def keystone_vector_available() -> bool:
    """Check if the KEYSTONE vector engine library is available."""
    try:
        _load_library()
        return True
    except RuntimeError:
        return False


def detect_features() -> dict[str, bool]:
    """Detect available hardware features for vector search."""
    try:
        lib, _ = _load_library()
    except RuntimeError:
        return {}
    flags = lib.keystone_vec_detect_features()
    return {
        "sse42": bool(flags & KEYSTONE_F_SSE42),
        "avx": bool(flags & KEYSTONE_F_AVX),
        "avx2": bool(flags & KEYSTONE_F_AVX2),
        "avx512f": bool(flags & KEYSTONE_F_AVX512F),
        "neon": bool(flags & KEYSTONE_F_NEON),
        "vpu": bool(flags & KEYSTONE_F_VPU),
    }


# ── KeystoneVectorIndex ───────────────────────────────────────────────────


class KeystoneVectorIndex:
    """KEYSTONE vector index with LSH + SIMD rerank.

    Mirrors the interface of :class:`QihseVectorIndex` so it can be used
    as a drop-in replacement in SemanticProjection, SemanticSearchEngine,
    IndexProjector, and IntelligenceVectorIndex.

    The KEYSTONE vector engine is hardware-agnostic: the scalar path
    always works, and SIMD backends are runtime-dispatched via CPUID +
    dlsym. CUDA is soft-loaded via dlopen. VPU (Myriad X) is guarded by
    a runtime socket probe.

    Args:
        path: Path for save/load persistence (the engine is in-memory
            by default; call :meth:`save` to persist).
        dim: Vector dimensionality (default 384 for all-MiniLM-L6-v2).
        capacity: Initial vector capacity (grows automatically).
        metric: Distance metric — KEYSTONE_METRIC_COSINE, _L2, or _DOT.
        rebuild: If True, don't load from saved state.
        force_backend: Force a specific backend (-1 = auto-detect).
        vpu_enabled: Enable VPU (Myriad X) backend if available.
        vpu_socket_path: Path to the VPU embedding server socket.
        lsh_num_tables: Number of LSH hash tables (default 8).
        lsh_hash_bits: Bits per LSH hash (default 12).
        lsh_probes: Multi-probe LSH neighbors per table (default 4).
        rerank_k: Max LSH candidates to rerank (default 256).
    """

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        dim: int = 384,
        capacity: int = 1_000_000,
        metric: int = KEYSTONE_METRIC_COSINE,
        rebuild: bool = False,
        force_backend: int = -1,
        vpu_enabled: bool = False,
        vpu_socket_path: str = "",
        lsh_num_tables: int = 8,
        lsh_hash_bits: int = 12,
        lsh_probes: int = 4,
        rerank_k: int = 256,
    ) -> None:
        self.path = Path(path) if path else None
        self._dim = dim
        self.library, self.library_path = _load_library()

        # Try loading from saved state first
        if self.path and not rebuild and self.path.exists():
            handle = ctypes.c_void_p()
            rc = self.library.keystone_vec_load(
                ctypes.byref(handle),
                str(self.path).encode("utf-8"),
            )
            if rc == KEYSTONE_OK and handle.value:
                self.handle = handle
                self._dim = self.library.keystone_vec_engine_dim(self.handle)
                logger.info(
                    "Loaded KEYSTONE vector index from %s (dim=%d, count=%d, backend=%s)",
                    self.path,
                    self._dim,
                    self.count,
                    self.backend,
                )
                return
            logger.warning("Failed to load from %s (rc=%d), creating new engine", self.path, rc)

        # Create new engine
        cfg = _KeystoneVecConfig(
            dim=dim,
            capacity=capacity,
            metric=metric,
            lsh_num_tables=lsh_num_tables,
            lsh_hash_bits=lsh_hash_bits,
            lsh_probes=lsh_probes,
            rerank_k=rerank_k,
            omp_threads=0,  # 0 = auto
            force_backend=force_backend,
            vpu_socket_path=vpu_socket_path.encode() if vpu_socket_path else b"",
            vpu_enabled=1 if vpu_enabled else 0,
        )
        self.handle = ctypes.c_void_p()
        rc = self.library.keystone_vec_engine_create(
            ctypes.byref(cfg),
            ctypes.byref(self.handle),
        )
        if rc != KEYSTONE_OK:
            raise RuntimeError(f"KEYSTONE vector engine create failed: error {rc}")
        if not self.handle.value:
            raise RuntimeError("KEYSTONE vector engine returned null handle")

        logger.info(
            "Created KEYSTONE vector index (dim=%d, capacity=%d, backend=%s)",
            dim,
            capacity,
            self.backend,
        )

    # -- Properties ---------------------------------------------------------

    @property
    def backend(self) -> str:
        """Current backend name (e.g. 'avx', 'scalar', 'cuda', 'vpu')."""
        b = self.library.keystone_vec_engine_get_backend(self.handle)
        name = self.library.keystone_vec_backend_name(b)
        return name.decode("utf-8") if name else "unknown"

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def count(self) -> int:
        return int(self.library.keystone_vec_engine_count(self.handle))

    # -- Upsert (mirrors QihseVectorIndex) ----------------------------------

    def upsert(self, ids: list[int], vectors: list[list[float]]) -> dict[str, Any]:
        """Upsert vectors and persist (legacy single-batch interface)."""
        changes = self.upsert_no_flush(ids, vectors)
        self.flush()
        return changes

    def upsert_no_flush(self, ids: list[int], vectors: list[list[float]]) -> dict[str, Any]:
        """Upsert vectors without flushing — caller must call flush() periodically.

        This is the high-throughput path for batched drain loops. The
        KEYSTONE vector engine is in-memory, so "flush" means saving to
        disk via :meth:`save`. Multiple upsert_no_flush calls accumulate
        in memory; a single save() call persists the entire state.
        """
        if not ids:
            return {"inserted": 0, "updated": 0}
        if len(ids) != len(vectors):
            raise ValueError("ids and vectors must have the same length")
        dimensions = len(vectors[0])
        if dimensions < 1 or any(len(v) != dimensions for v in vectors):
            raise ValueError("vectors must share a non-zero dimension")
        if dimensions != self._dim:
            raise ValueError(f"vector dim {dimensions} != engine dim {self._dim}")

        # numpy zero-copy path
        try:
            import numpy as np
            vec_arr = np.ascontiguousarray(vectors, dtype=np.float32)
            id_arr = np.ascontiguousarray(ids, dtype=np.uint64)
            id_ptr = id_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64))
            vec_ptr = vec_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        except (ImportError, ValueError):
            flattened = [float(x) for v in vectors for x in v]
            id_ptr = (ctypes.c_uint64 * len(ids))(*ids)
            vec_ptr = (ctypes.c_float * len(flattened))(*flattened)

        rc = self.library.keystone_vec_upsert_batch(
            self.handle,
            id_ptr,
            vec_ptr,
            len(ids),
        )
        if rc != KEYSTONE_OK:
            raise RuntimeError(f"KEYSTONE vector upsert failed: error {rc}")
        # KEYSTONE upsert is idempotent by ID; we don't track inserted vs
        # updated separately at the C level. Return a reasonable estimate.
        return {"inserted": len(ids), "updated": 0}

    def flush(self) -> None:
        """Flush accumulated state to disk.

        For KEYSTONE, this saves the entire engine state (vectors + LSH
        index) to the path specified at construction time. If no path
        was given, this is a no-op.
        """
        if self.path and hasattr(self.library, "keystone_vec_save"):
            rc = self.library.keystone_vec_save(
                self.handle,
                str(self.path).encode("utf-8"),
            )
            if rc != KEYSTONE_OK:
                raise RuntimeError(f"KEYSTONE vector save failed: error {rc}")

    def save(self, path: Path | str | None = None) -> None:
        """Explicitly save the engine state to disk."""
        save_path = path or self.path
        if not save_path:
            raise ValueError("No path specified for save")
        if not hasattr(self.library, "keystone_vec_save"):
            raise RuntimeError("Save not supported by this library version")
        rc = self.library.keystone_vec_save(
            self.handle,
            str(save_path).encode("utf-8"),
        )
        if rc != KEYSTONE_OK:
            raise RuntimeError(f"KEYSTONE vector save failed: error {rc}")

    # -- Search (mirrors QihseVectorIndex) ----------------------------------

    def search(self, vector: list[float], *, limit: int = 1) -> list[dict[str, Any]]:
        """Search for the top-k most similar vectors.

        Returns:
            List of ``{"id": int, "score": float}`` dicts sorted by
            similarity descending. For cosine metric, score is the cosine
            **similarity** (1.0 = identical, 0.0 = orthogonal), matching
            the QIHSE backend's semantics.
        """
        if limit < 1:
            raise ValueError("search limit must be positive")
        if len(vector) != self._dim:
            raise ValueError(f"query dim {len(vector)} != engine dim {self._dim}")

        vec_arr = (ctypes.c_float * len(vector))(*vector)
        results = (_KeystoneVecResult * limit)()
        rc = self.library.keystone_vec_search(
            self.handle,
            vec_arr,
            limit,
            results,
        )
        if rc != KEYSTONE_OK:
            raise RuntimeError(f"KEYSTONE vector search failed: error {rc}")

        # KEYSTONE returns cosine distance (1.0 - similarity for cosine).
        # Convert to similarity to match QIHSE's interface.
        hits = []
        for r in results[:limit]:
            if r.id == 0 and r.distance == 0.0:
                continue  # empty slot
            # For cosine metric: distance = 1.0 - dot_product (since
            # vectors are L2-normalized, dot = cosine similarity).
            # So similarity = 1.0 - distance.
            similarity = 1.0 - float(r.distance)
            hits.append({"id": int(r.id), "score": similarity})
        return hits

    def search_batch(
        self,
        queries: list[list[float]],
        *,
        limit: int = 10,
    ) -> list[list[dict[str, Any]]]:
        """Batch search — multiple queries, each returning top-k results.

        Returns:
            List of result lists, one per query.
        """
        if limit < 1:
            raise ValueError("search limit must be positive")
        if not queries:
            return []

        import numpy as np
        q_arr = np.ascontiguousarray(queries, dtype=np.float32)
        nq = len(queries)
        out = (_KeystoneVecResult * (nq * limit))()
        rc = self.library.keystone_vec_search_batch(
            self.handle,
            q_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            nq,
            limit,
            out,
        )
        if rc != KEYSTONE_OK:
            raise RuntimeError(f"KEYSTONE batch search failed: error {rc}")

        all_results = []
        for q_idx in range(nq):
            hits = []
            for k in range(limit):
                r = out[q_idx * limit + k]
                if r.id == 0 and r.distance == 0.0:
                    continue
                similarity = 1.0 - float(r.distance)
                hits.append({"id": int(r.id), "score": similarity})
            all_results.append(hits)
        return all_results

    # -- Lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Close the engine and release all resources."""
        if self.handle:
            handle = self.handle
            self.handle = None
            try:
                self.library.keystone_vec_engine_destroy(handle)
            except Exception:
                pass

    def __enter__(self) -> "KeystoneVectorIndex":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self):
        self.close()

    def __repr__(self) -> str:
        return (
            f"KeystoneVectorIndex(dim={self._dim}, count={self.count}, "
            f"backend='{self.backend}')"
        )


__all__ = [
    "KeystoneVectorIndex",
    "keystone_vector_available",
    "detect_features",
    "KEYSTONE_METRIC_COSINE",
    "KEYSTONE_METRIC_L2",
    "KEYSTONE_METRIC_DOT",
    "KEYSTONE_BACKEND_SCALAR",
    "KEYSTONE_BACKEND_VPU",
    "KEYSTONE_BACKEND_NEON",
    "KEYSTONE_BACKEND_SSE42",
    "KEYSTONE_BACKEND_AVX",
    "KEYSTONE_BACKEND_AVX2",
    "KEYSTONE_BACKEND_AVX512",
    "KEYSTONE_BACKEND_CUDA",
]
