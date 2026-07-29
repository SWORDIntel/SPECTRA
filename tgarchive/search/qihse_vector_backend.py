"""Safe ctypes boundary for QIHSE's persistent vector-database API."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any, Iterable


QIHSE_BACKEND_INMEMORY = 3
QIHSE_OPEN_CREATE = 1 << 0
QIHSE_OPEN_TRUNCATE = 1 << 2
QIHSE_OPEN_FILE_BACKED = 1 << 3
_LOADED: dict[str, ctypes.CDLL] = {}


class VectorResult(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint64),
        ("score", ctypes.c_float),
        ("vector", ctypes.POINTER(ctypes.c_float)),
        ("vector_dims", ctypes.c_size_t),
        ("metadata", ctypes.c_void_p),
        ("metadata_size", ctypes.c_size_t),
    ]


class VectorQuery(ctypes.Structure):
    _fields_ = [
        ("query_vector", ctypes.POINTER(ctypes.c_float)),
        ("vector_dims", ctypes.c_size_t),
        ("top_k", ctypes.c_size_t),
        ("similarity_threshold", ctypes.c_float),
        ("include_vectors", ctypes.c_bool),
        ("include_metadata", ctypes.c_bool),
        ("use_trinary_candidates", ctypes.c_bool),
        ("candidate_count", ctypes.c_size_t),
        ("query_mode", ctypes.c_int),
        ("candidate_pool_size", ctypes.c_size_t),
        ("distance_metric", ctypes.c_int),
        ("metadata_filter", ctypes.c_void_p),
        ("metadata_filter_opaque", ctypes.c_void_p),
        ("user", ctypes.c_void_p),
        ("lua_script", ctypes.c_char_p),
        ("wasm_script", ctypes.c_char_p),
        ("accelerator", ctypes.c_char_p),
    ]


def _library_candidates() -> Iterable[Path]:
    explicit = os.getenv("QIHSE_LIB_PATH")
    if explicit:
        yield Path(explicit)
    root = os.getenv("QIHSE_ROOT")
    if root:
        root_path = Path(root)
        yield root_path / "libqihse.so"
        yield root_path / "build" / "libqihse.so"
    yield Path("/fast/MainWorkspace/framewerx/native/qihse/libqihse.so")
    yield Path("/home/john/Documents/qlearn/native/qihse/libqihse.so")
    yield Path("/usr/local/lib/libqihse.so")
    yield Path("/usr/lib/libqihse.so")


def _load_library() -> tuple[ctypes.CDLL, Path]:
    for candidate in _library_candidates():
        if not candidate.exists():
            continue
        resolved = str(candidate.resolve())
        if resolved in _LOADED:
            return _LOADED[resolved], candidate
        mode = getattr(os, "RTLD_NOW", 0) | getattr(os, "RTLD_LOCAL", 0)
        mode |= getattr(os, "RTLD_DEEPBIND", 0) | getattr(os, "RTLD_NODELETE", 0)
        try:
            library = ctypes.CDLL(resolved, mode=mode)
        except OSError:
            continue
        required = (
            "qihse_vector_db_open",
            "qihse_vector_db_upsert_by_ids",
            "qihse_vector_db_search",
            "qihse_vector_db_flush",
            "qihse_vector_db_close",
            "qihse_auth_init",
            "qihse_auth_get_user",
        )
        if not all(hasattr(library, symbol) for symbol in required):
            continue
        _configure(library)
        _LOADED[resolved] = library
        return library, candidate
    raise RuntimeError("QIHSE vector database library is unavailable")


def _configure(library: ctypes.CDLL) -> None:
    library.qihse_auth_init.argtypes = []
    library.qihse_auth_init.restype = None
    library.qihse_auth_get_user.argtypes = [ctypes.c_uint32]
    library.qihse_auth_get_user.restype = ctypes.c_void_p
    if not getattr(library, "_spectra_auth_initialized", False):
        library.qihse_auth_init()
        library._spectra_auth_initialized = True
    library.qihse_vector_db_open.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    library.qihse_vector_db_open.restype = ctypes.c_void_p
    library.qihse_vector_db_upsert_by_ids.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    library.qihse_vector_db_upsert_by_ids.restype = ctypes.c_bool
    library.qihse_vector_db_flush.argtypes = [ctypes.c_void_p]
    library.qihse_vector_db_flush.restype = ctypes.c_bool
    library.qihse_vector_db_search.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(VectorQuery),
        ctypes.POINTER(VectorResult),
        ctypes.c_size_t,
    ]
    library.qihse_vector_db_search.restype = ctypes.c_int
    library.qihse_vector_db_close.argtypes = [ctypes.c_void_p]
    library.qihse_vector_db_close.restype = ctypes.c_bool


class QihseVectorIndex:
    """Persistent QIHSE vector index with idempotent external-ID upserts."""

    def __init__(self, path: Path | str, *, rebuild: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.library, self.library_path = _load_library()
        flags = QIHSE_OPEN_CREATE | QIHSE_OPEN_FILE_BACKED
        if rebuild:
            flags |= QIHSE_OPEN_TRUNCATE
        self.handle = self.library.qihse_vector_db_open(
            QIHSE_BACKEND_INMEMORY,
            None,
            str(self.path).encode("utf-8"),
            flags,
        )
        if not self.handle:
            raise RuntimeError(f"QIHSE failed to open vector index: {self.path}")

    def close(self) -> None:
        if self.handle:
            handle = self.handle
            self.handle = None
            self.library.qihse_vector_db_close(handle)

    def __enter__(self) -> "QihseVectorIndex":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def upsert(self, ids: list[int], vectors: list[list[float]]) -> dict[str, Any]:
        if not ids:
            return {"inserted": 0, "updated": 0}
        if len(ids) != len(vectors):
            raise ValueError("QIHSE ids and vectors must have the same length")
        dimensions = len(vectors[0])
        if dimensions < 1 or any(len(vector) != dimensions for vector in vectors):
            raise ValueError("QIHSE vectors must share a non-zero dimension")
        flattened = [float(value) for vector in vectors for value in vector]
        id_array = (ctypes.c_uint64 * len(ids))(*ids)
        vector_array = (ctypes.c_float * len(flattened))(*flattened)
        inserted = ctypes.c_size_t()
        updated = ctypes.c_size_t()
        ok = self.library.qihse_vector_db_upsert_by_ids(
            self.handle,
            id_array,
            vector_array,
            len(ids),
            dimensions,
            None,
            None,
            ctypes.byref(inserted),
            ctypes.byref(updated),
        )
        if not ok:
            raise RuntimeError("QIHSE vector upsert failed")
        if not self.library.qihse_vector_db_flush(self.handle):
            raise RuntimeError("QIHSE vector flush failed")
        return {"inserted": int(inserted.value), "updated": int(updated.value)}

    def search(self, vector: list[float], *, limit: int = 1) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("QIHSE search limit must be positive")
        vector_array = (ctypes.c_float * len(vector))(*vector)
        user = self.library.qihse_auth_get_user(0)
        if not user:
            raise RuntimeError("QIHSE operator identity is unavailable")
        query = VectorQuery(
            query_vector=vector_array,
            vector_dims=len(vector),
            top_k=limit,
            similarity_threshold=-1.0,
            include_vectors=False,
            include_metadata=False,
            use_trinary_candidates=False,
            candidate_count=0,
            query_mode=0,
            candidate_pool_size=0,
            distance_metric=0,
            metadata_filter=None,
            metadata_filter_opaque=None,
            user=user,
            lua_script=None,
            wasm_script=None,
            accelerator=None,
        )
        results = (VectorResult * limit)()
        count = self.library.qihse_vector_db_search(self.handle, ctypes.byref(query), results, limit)
        if count < 0:
            raise RuntimeError(f"QIHSE vector search returned {count}")
        return [{"id": int(item.id), "score": float(item.score)} for item in results[:count]]
