"""Crash-isolated ctypes adapter for QIHSE persistent graph edges."""

from __future__ import annotations

import ctypes
import json
from pathlib import Path
from typing import Any

from .qihse_vector_backend import (
    QIHSE_BACKEND_INMEMORY,
    QIHSE_OPEN_CREATE,
    QIHSE_OPEN_FILE_BACKED,
    QIHSE_OPEN_TRUNCATE,
    _load_library,
)


QIHSE_OPEN_READ_ONLY = 1 << 1
EDGE_OUTGOING = 0
EDGE_INCOMING = 1
EDGE_BOTH = 2
EDGE_TYPE_BYTES = 32


class EdgeInput(ctypes.Structure):
    _fields_ = [
        ("from_id", ctypes.c_uint64),
        ("to_id", ctypes.c_uint64),
        ("edge_type", ctypes.c_char_p),
        ("metadata", ctypes.c_void_p),
        ("metadata_size", ctypes.c_size_t),
    ]


class EdgeResult(ctypes.Structure):
    _fields_ = [
        ("from_id", ctypes.c_uint64),
        ("to_id", ctypes.c_uint64),
        ("edge_type", ctypes.c_char * EDGE_TYPE_BYTES),
        ("metadata", ctypes.c_void_p),
        ("metadata_size", ctypes.c_size_t),
    ]


def _configure_graph(library: ctypes.CDLL) -> None:
    required = (
        "qihse_vector_db_add_edges",
        "qihse_vector_db_replace_edge",
        "qihse_vector_db_get_edge_records",
        "qihse_vector_db_free_edge_records",
        "qihse_vector_db_checkpoint",
    )
    if not all(hasattr(library, symbol) for symbol in required):
        raise RuntimeError("QIHSE graph capability is unavailable in the selected library")
    library.qihse_vector_db_add_edges.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(EdgeInput),
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    library.qihse_vector_db_add_edges.restype = ctypes.c_bool
    library.qihse_vector_db_replace_edge.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    library.qihse_vector_db_replace_edge.restype = ctypes.c_bool
    library.qihse_vector_db_get_edge_records.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint64,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.POINTER(EdgeResult),
        ctypes.c_size_t,
    ]
    library.qihse_vector_db_get_edge_records.restype = ctypes.c_int
    library.qihse_vector_db_free_edge_records.argtypes = [
        ctypes.POINTER(EdgeResult),
        ctypes.c_size_t,
    ]
    library.qihse_vector_db_free_edge_records.restype = None
    library.qihse_vector_db_checkpoint.argtypes = [ctypes.c_void_p]
    library.qihse_vector_db_checkpoint.restype = ctypes.c_bool


class QihseGraphIndex:
    """Persistent QIHSE graph with stable caller-owned node IDs."""

    def __init__(self, path: Path | str, *, rebuild: bool = False, read_only: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.library, self.library_path = _load_library()
        _configure_graph(self.library)
        flags = QIHSE_OPEN_FILE_BACKED | QIHSE_OPEN_CREATE
        if rebuild:
            flags |= QIHSE_OPEN_TRUNCATE
        if read_only:
            flags = QIHSE_OPEN_FILE_BACKED | QIHSE_OPEN_READ_ONLY
        self.handle = self.library.qihse_vector_db_open(
            QIHSE_BACKEND_INMEMORY,
            None,
            str(self.path).encode("utf-8"),
            flags,
        )
        if not self.handle:
            raise RuntimeError(f"QIHSE failed to open graph index: {self.path}")

    def close(self) -> None:
        if self.handle:
            handle = self.handle
            self.handle = None
            self.library.qihse_vector_db_close(handle)

    def __enter__(self) -> "QihseGraphIndex":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def sync(self, node_ids: list[int], edges: list[dict[str, Any]]) -> dict[str, int]:
        inserted = 0
        updated = 0
        if node_ids:
            ids = (ctypes.c_uint64 * len(node_ids))(*node_ids)
            vectors = (ctypes.c_float * len(node_ids))(*([1.0] * len(node_ids)))
            inserted_count = ctypes.c_size_t()
            updated_count = ctypes.c_size_t()
            ok = self.library.qihse_vector_db_upsert_by_ids(
                self.handle,
                ids,
                vectors,
                len(node_ids),
                1,
                None,
                None,
                ctypes.byref(inserted_count),
                ctypes.byref(updated_count),
            )
            if not ok:
                raise RuntimeError("QIHSE graph node upsert failed")
            inserted = int(inserted_count.value)
            updated = int(updated_count.value)
        changed = ctypes.c_size_t()
        if edges:
            edge_types: list[bytes] = []
            metadata_values: list[bytes] = []
            metadata_buffers: list[Any] = []
            inputs = (EdgeInput * len(edges))()
            for index, edge in enumerate(edges):
                edge_type = str(edge["edge_type"]).encode("ascii")
                if not edge_type or len(edge_type) >= EDGE_TYPE_BYTES:
                    raise ValueError("QIHSE edge types must contain 1-31 ASCII bytes")
                metadata = json.dumps(
                    edge.get("metadata", {}),
                    default=str,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                edge_types.append(edge_type)
                metadata_values.append(metadata)
                buffer = ctypes.create_string_buffer(metadata) if metadata else None
                metadata_buffers.append(buffer)
                inputs[index] = EdgeInput(
                    from_id=int(edge["from_node_id"]),
                    to_id=int(edge["to_node_id"]),
                    edge_type=edge_types[-1],
                    metadata=ctypes.cast(buffer, ctypes.c_void_p) if buffer is not None else None,
                    metadata_size=len(metadata),
                )
            if not self.library.qihse_vector_db_add_edges(
                self.handle,
                inputs,
                len(edges),
                ctypes.byref(changed),
            ):
                raise RuntimeError("QIHSE graph edge upsert failed")
            for index, edge in enumerate(edges):
                buffer = metadata_buffers[index]
                if not self.library.qihse_vector_db_replace_edge(
                    self.handle,
                    int(edge["from_node_id"]),
                    int(edge["to_node_id"]),
                    edge_types[index],
                    ctypes.cast(buffer, ctypes.c_void_p) if buffer is not None else None,
                    len(metadata_values[index]),
                ):
                    raise RuntimeError("QIHSE graph edge metadata replacement failed")
        if not self.library.qihse_vector_db_checkpoint(self.handle):
            raise RuntimeError("QIHSE graph checkpoint failed")
        return {
            "nodes_inserted": inserted,
            "nodes_updated": updated,
            "edges_changed": int(changed.value),
        }

    def edge_records(
        self,
        node_id: int,
        *,
        edge_type: str | None = None,
        direction: int = EDGE_BOTH,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("graph result limit must be positive")
        results = (EdgeResult * limit)()
        encoded_type = edge_type.encode("ascii") if edge_type else None
        count = self.library.qihse_vector_db_get_edge_records(
            self.handle,
            node_id,
            encoded_type,
            direction,
            results,
            limit,
        )
        if count < 0:
            raise RuntimeError("QIHSE graph lookup failed")
        records: list[dict[str, Any]] = []
        try:
            for result in results[:count]:
                metadata_bytes = (
                    ctypes.string_at(result.metadata, result.metadata_size)
                    if result.metadata and result.metadata_size
                    else b"{}"
                )
                records.append({
                    "from_node_id": int(result.from_id),
                    "to_node_id": int(result.to_id),
                    "edge_type": bytes(result.edge_type).split(b"\0", 1)[0].decode("ascii"),
                    "metadata": json.loads(metadata_bytes),
                })
        finally:
            self.library.qihse_vector_db_free_edge_records(results, max(count, 0))
        return records


__all__ = [
    "EDGE_BOTH",
    "EDGE_INCOMING",
    "EDGE_OUTGOING",
    "QihseGraphIndex",
]
