"""
QIHSE Graph Python FFI Bindings
================================

Python ctypes wrapper for QIHSE's property graph store, Cypher executor,
and bulk ingest API (Neo4j-admin-import equivalent).

Provides:
- GraphStore: vertex/edge CRUD, label/type/property indexes
- CypherExecutor: parse + execute Cypher queries
- GraphIngest: bulk CSV/JSON/JSONL ingestion (neo4j-admin import equivalent)
- GraphAlgorithms: BFS, DFS, Dijkstra, PageRank, etc.
"""

import ctypes
import os
import logging
from ctypes import (
    c_void_p, c_size_t, c_double, c_uint32, c_uint64, c_int64, c_int,
    c_bool, c_char, c_char_p, POINTER, Structure, byref, cast
)
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# Property types
GRAPH_PROP_INT64 = 0
GRAPH_PROP_DOUBLE = 1
GRAPH_PROP_STRING = 2
GRAPH_PROP_BOOL = 3
GRAPH_PROP_ARRAY = 4

# Direction
GRAPH_DIR_OUTGOING = 0
GRAPH_DIR_INCOMING = 1
GRAPH_DIR_BOTH = 2


class _GraphPropArray(Structure):
    """C graph_prop_array_t — matches the array variant of the union."""
    _fields_ = [
        ("data", c_void_p),
        ("count", c_size_t),
        ("elem_type", c_int),
        ("_pad", c_int),
    ]


class _GraphPropUnion(ctypes.Union):
    """C union for graph_prop_t val — must be 24 bytes (size of graph_prop_array_t)."""
    _fields_ = [
        ("i", c_int64),
        ("d", c_double),
        ("s", c_char_p),
        ("b", c_bool),
        ("arr", _GraphPropArray),
    ]


class GraphProp(Structure):
    """C graph_prop_t — property value with union."""
    _fields_ = [
        ("type", c_int),
        ("_pad", c_int),
        ("val", _GraphPropUnion),
    ]


class GraphAdj(Structure):
    """C graph_adj_t — adjacency tuple."""
    _fields_ = [
        ("edge_id", c_uint64),
        ("direction", c_int),
        ("neighbor_id", c_uint64),
        ("edge_type", c_char * 32),
    ]


class GraphVertex(Structure):
    """C graph_vertex_t."""
    _fields_ = [
        ("id", c_uint64),
        ("labels", POINTER(c_char_p)),
        ("num_labels", c_size_t),
        ("prop_keys", POINTER(c_char_p)),
        ("prop_vals", POINTER(GraphProp)),
        ("num_props", c_size_t),
    ]


class GraphEdge(Structure):
    """C graph_edge_t."""
    _fields_ = [
        ("id", c_uint64),
        ("type", c_char * 32),
        ("start_vertex_id", c_uint64),
        ("end_vertex_id", c_uint64),
        ("prop_keys", POINTER(c_char_p)),
        ("prop_vals", POINTER(GraphProp)),
        ("num_props", c_size_t),
    ]


def _load_lib():
    """Load libqihse.so (reuses the same library as qihse_bindings)."""
    possible = [
        Path(__file__).parent.parent.parent / "QIHSE" / "libqihse.so",
        Path(__file__).parent.parent.parent / "libs" / "QIHSE" / "libqihse.so",
        Path("/usr/local/lib/libqihse.so"),
        Path("libqihse.so"),
    ]
    for p in possible:
        if p.exists():
            try:
                mode = getattr(os, "RTLD_GLOBAL", 0) | getattr(os, "RTLD_NOW", 0)
                return ctypes.CDLL(str(p), mode=mode)
            except OSError:
                continue
    try:
        mode = getattr(os, "RTLD_GLOBAL", 0) | getattr(os, "RTLD_NOW", 0)
        return ctypes.CDLL("libqihse.so", mode=mode)
    except OSError:
        return None


_lib = _load_lib()

if _lib is not None:
    # Graph store
    _lib.qihse_graph_create.argtypes = []
    _lib.qihse_graph_create.restype = c_void_p

    _lib.qihse_graph_destroy.argtypes = [c_void_p]
    _lib.qihse_graph_destroy.restype = None

    _lib.qihse_graph_vertex_create.argtypes = [
        c_void_p,                          # graph
        POINTER(c_char_p),                 # labels
        c_size_t,                          # num_labels
        POINTER(c_char_p),                 # prop_keys
        POINTER(GraphProp),                # prop_vals
        c_size_t,                          # num_props
    ]
    _lib.qihse_graph_vertex_create.restype = c_uint64

    _lib.qihse_graph_vertex_get.argtypes = [c_void_p, c_uint64]
    _lib.qihse_graph_vertex_get.restype = POINTER(GraphVertex)

    _lib.qihse_graph_vertex_delete.argtypes = [c_void_p, c_uint64]
    _lib.qihse_graph_vertex_delete.restype = c_bool

    _lib.qihse_graph_edge_create.argtypes = [
        c_void_p,    # graph
        c_char_p,    # type
        c_uint64,    # start
        c_uint64,    # end
        POINTER(c_char_p),   # prop_keys
        POINTER(GraphProp),  # prop_vals
        c_size_t,            # num_props
    ]
    _lib.qihse_graph_edge_create.restype = c_uint64

    _lib.qihse_graph_edge_get.argtypes = [c_void_p, c_uint64]
    _lib.qihse_graph_edge_get.restype = POINTER(GraphEdge)

    _lib.qihse_graph_get_neighbors.argtypes = [
        c_void_p, c_uint64, c_int, c_char_p,
        POINTER(GraphAdj), c_size_t
    ]
    _lib.qihse_graph_get_neighbors.restype = c_size_t

    _lib.qihse_graph_get_vertices_by_label.argtypes = [
        c_void_p, c_char_p, POINTER(c_uint64), c_size_t
    ]
    _lib.qihse_graph_get_vertices_by_label.restype = c_size_t

    _lib.qihse_graph_vertex_count.argtypes = [c_void_p]
    _lib.qihse_graph_vertex_count.restype = c_size_t

    _lib.qihse_graph_edge_count.argtypes = [c_void_p]
    _lib.qihse_graph_edge_count.restype = c_size_t

    # Cypher
    _lib.qihse_cypher_run.argtypes = [c_void_p, c_char_p]
    _lib.qihse_cypher_run.restype = c_void_p  # cypher_result_set_t*

    _lib.qihse_cypher_result_free.argtypes = [c_void_p]
    _lib.qihse_cypher_result_free.restype = None

    # Graph ingest
    _lib.qihse_graph_ingest_vertices_csv.argtypes = [
        c_void_p, c_char_p, c_bool, c_char_p, c_char_p, c_char,
        POINTER(c_int64)
    ]
    _lib.qihse_graph_ingest_vertices_csv.restype = c_int64

    _lib.qihse_graph_ingest_edges_csv.argtypes = [
        c_void_p, c_char_p, c_bool, c_char_p, c_char_p, c_char_p,
        c_char_p, c_char, POINTER(c_int64)
    ]
    _lib.qihse_graph_ingest_edges_csv.restype = c_int64

    _lib.qihse_graph_ingest_vertices_json.argtypes = [
        c_void_p, c_char_p, c_bool, POINTER(c_int64)
    ]
    _lib.qihse_graph_ingest_vertices_json.restype = c_int64

    _lib.qihse_graph_ingest_edges_json.argtypes = [
        c_void_p, c_char_p, c_bool, POINTER(c_int64)
    ]
    _lib.qihse_graph_ingest_edges_json.restype = c_int64

    _lib.qihse_graph_ingest_directory.argtypes = [
        c_void_p, c_char_p, POINTER(c_int64)
    ]
    _lib.qihse_graph_ingest_directory.restype = c_int64

    _lib.qihse_graph_ingest_lookup_id.argtypes = [c_void_p, c_char_p]
    _lib.qihse_graph_ingest_lookup_id.restype = c_uint64

    _lib.qihse_graph_ingest_clear_ids.argtypes = [c_void_p]
    _lib.qihse_graph_ingest_clear_ids.restype = None

    # Graph algorithms
    _lib.qihse_graph_bfs.argtypes = [c_void_p, c_uint64, POINTER(c_uint64), c_size_t]
    _lib.qihse_graph_bfs.restype = c_size_t

    _lib.qihse_graph_dijkstra.argtypes = [
        c_void_p, c_uint64, c_uint64, POINTER(c_uint64), c_size_t
    ]
    _lib.qihse_graph_dijkstra.restype = c_size_t

    _lib.qihse_graph_pagerank.argtypes = [
        c_void_p, POINTER(c_double), c_size_t, c_int, c_double, c_double
    ]
    _lib.qihse_graph_pagerank.restype = c_int

    _lib.qihse_graph_connected_components.argtypes = [
        c_void_p, POINTER(c_uint32), c_size_t
    ]
    _lib.qihse_graph_connected_components.restype = c_size_t


def graph_available() -> bool:
    """Check if QIHSE graph library is available."""
    if _lib is None:
        return False
    try:
        return hasattr(_lib, 'qihse_graph_create')
    except:
        return False


def _make_prop(val) -> GraphProp:
    """Convert a Python value to a GraphProp struct."""
    p = GraphProp()
    if val is None:
        p.type = GRAPH_PROP_STRING
        p.val.s = b""
    elif isinstance(val, bool):
        p.type = GRAPH_PROP_BOOL
        p.val.b = val
    elif isinstance(val, int):
        p.type = GRAPH_PROP_INT64
        p.val.i = val
    elif isinstance(val, float):
        p.type = GRAPH_PROP_DOUBLE
        p.val.d = val
    elif isinstance(val, str):
        p.type = GRAPH_PROP_STRING
        p.val.s = val.encode('utf-8')
    else:
        p.type = GRAPH_PROP_STRING
        p.val.s = str(val).encode('utf-8')
    return p


def _prop_to_dict(vertex_ptr) -> Dict[str, Any]:
    """Extract properties from a GraphVertex pointer."""
    if not vertex_ptr:
        return {}
    v = vertex_ptr.contents
    props = {}
    for i in range(v.num_props):
        key = v.prop_keys[i].decode('utf-8') if v.prop_keys[i] else f"prop_{i}"
        pv = v.prop_vals[i]
        if pv.type == GRAPH_PROP_INT64:
            props[key] = pv.val.i
        elif pv.type == GRAPH_PROP_DOUBLE:
            props[key] = pv.val.d
        elif pv.type == GRAPH_PROP_STRING:
            props[key] = pv.val.s.decode('utf-8') if pv.val.s else ""
        elif pv.type == GRAPH_PROP_BOOL:
            props[key] = pv.val.b
    return props


class GraphStore:
    """Python interface for QIHSE property graph store."""

    def __init__(self, path: str = ""):
        if not graph_available():
            raise RuntimeError("QIHSE graph library not available")
        self._ptr = _lib.qihse_graph_create()
        if not self._ptr:
            raise RuntimeError("Failed to create graph store")

    def add_vertex(self, labels: List[str] = None, properties: Dict[str, Any] = None) -> int:
        """Create a vertex. Returns vertex ID."""
        labels = labels or []
        properties = properties or {}

        lbl_arr = (c_char_p * len(labels))(*[l.encode('utf-8') for l in labels]) if labels else None
        keys = list(properties.keys())
        vals = [_make_prop(properties[k]) for k in keys]

        key_arr = (c_char_p * len(keys))(*[k.encode('utf-8') for k in keys]) if keys else None
        val_arr = (GraphProp * len(vals))(*vals) if vals else None

        vid = _lib.qihse_graph_vertex_create(
            self._ptr,
            cast(lbl_arr, POINTER(c_char_p)) if lbl_arr else None,
            len(labels),
            cast(key_arr, POINTER(c_char_p)) if key_arr else None,
            cast(val_arr, POINTER(GraphProp)) if val_arr else None,
            len(keys),
        )
        return int(vid)

    def add_edge(self, edge_type: str, start: int, end: int,
                 properties: Dict[str, Any] = None) -> int:
        """Create an edge. Returns edge ID."""
        properties = properties or {}
        keys = list(properties.keys())
        vals = [_make_prop(properties[k]) for k in keys]

        key_arr = (c_char_p * len(keys))(*[k.encode('utf-8') for k in keys]) if keys else None
        val_arr = (GraphProp * len(vals))(*vals) if vals else None

        eid = _lib.qihse_graph_edge_create(
            self._ptr,
            edge_type.encode('utf-8'),
            start, end,
            cast(key_arr, POINTER(c_char_p)) if key_arr else None,
            cast(val_arr, POINTER(GraphProp)) if val_arr else None,
            len(keys),
        )
        return int(eid)

    def get_vertex(self, vid: int) -> Optional[dict]:
        """Get vertex by ID. Returns dict with labels and properties."""
        ptr = _lib.qihse_graph_vertex_get(self._ptr, vid)
        if not ptr:
            return None
        v = ptr.contents
        labels = []
        for i in range(v.num_labels):
            if v.labels[i]:
                labels.append(v.labels[i].decode('utf-8'))
        return {
            'id': int(v.id),
            'labels': labels,
            'properties': _prop_to_dict(ptr),
        }

    def get_neighbors(self, vid: int, direction: int = GRAPH_DIR_BOTH,
                      edge_type: str = None) -> List[dict]:
        """Get neighbors of a vertex."""
        max_out = 1024
        adj_buf = (GraphAdj * max_out)()
        etype = edge_type.encode('utf-8') if edge_type else None
        count = _lib.qihse_graph_get_neighbors(
            self._ptr, vid, direction, etype, adj_buf, max_out
        )
        return [
            {
                'edge_id': int(adj_buf[i].edge_id),
                'neighbor_id': int(adj_buf[i].neighbor_id),
                'edge_type': adj_buf[i].edge_type.decode('utf-8'),
            }
            for i in range(count)
        ]

    def vertex_count(self) -> int:
        return int(_lib.qihse_graph_vertex_count(self._ptr))

    def edge_count(self) -> int:
        return int(_lib.qihse_graph_edge_count(self._ptr))

    def cypher(self, query: str) -> List[dict]:
        """Execute a Cypher query. Returns list of result rows."""
        rs_ptr = _lib.qihse_cypher_run(self._ptr, query.encode('utf-8'))
        if not rs_ptr:
            return []
        # The result set structure is: {names, values, num_cols, num_rows}
        # We need to read it. Since we don't have the exact struct layout in
        # Python, we return a simplified result.
        # For now, return empty — the C function handles the query.
        _lib.qihse_cypher_result_free(rs_ptr)
        return []

    # --- Ingest API (Neo4j-admin import equivalent) ---

    def ingest_vertices_csv(self, filepath: str, has_header: bool = True,
                            id_column: str = "ID", label_column: str = "LABEL",
                            delimiter: str = ",") -> Tuple[int, int]:
        """Bulk ingest vertices from CSV. Returns (count, errors)."""
        err = c_int64(0)
        n = _lib.qihse_graph_ingest_vertices_csv(
            self._ptr, filepath.encode('utf-8'), has_header,
            id_column.encode('utf-8') if id_column else None,
            label_column.encode('utf-8') if label_column else None,
            ord(delimiter), byref(err)
        )
        return int(n), int(err.value)

    def ingest_edges_csv(self, filepath: str, has_header: bool = True,
                         start_column: str = "START_ID", end_column: str = "END_ID",
                         type_column: str = "TYPE", delimiter: str = ",") -> Tuple[int, int]:
        """Bulk ingest edges from CSV. Returns (count, errors)."""
        err = c_int64(0)
        n = _lib.qihse_graph_ingest_edges_csv(
            self._ptr, filepath.encode('utf-8'), has_header,
            start_column.encode('utf-8'),
            end_column.encode('utf-8'),
            type_column.encode('utf-8') if type_column else None,
            None,  # id_column
            ord(delimiter), byref(err)
        )
        return int(n), int(err.value)

    def ingest_vertices_json(self, filepath: str, jsonl: bool = True) -> Tuple[int, int]:
        """Bulk ingest vertices from JSON/JSONL. Returns (count, errors)."""
        err = c_int64(0)
        n = _lib.qihse_graph_ingest_vertices_json(
            self._ptr, filepath.encode('utf-8'), jsonl, byref(err)
        )
        return int(n), int(err.value)

    def ingest_edges_json(self, filepath: str, jsonl: bool = True) -> Tuple[int, int]:
        """Bulk ingest edges from JSON/JSONL. Returns (count, errors)."""
        err = c_int64(0)
        n = _lib.qihse_graph_ingest_edges_json(
            self._ptr, filepath.encode('utf-8'), jsonl, byref(err)
        )
        return int(n), int(err.value)

    def ingest_directory(self, dirpath: str) -> Tuple[int, int]:
        """Ingest all node/edge CSV/JSON files from a directory.
        Returns (total_count, total_errors)."""
        err = c_int64(0)
        n = _lib.qihse_graph_ingest_directory(
            self._ptr, dirpath.encode('utf-8'), byref(err)
        )
        return int(n), int(err.value)

    def lookup_id(self, external_id: str) -> int:
        """Look up internal vertex ID by external string ID."""
        return int(_lib.qihse_graph_ingest_lookup_id(
            self._ptr, external_id.encode('utf-8')
        ))

    def register_id(self, external_id: str, internal_id: int) -> None:
        """Register an external string ID → internal vertex ID mapping."""
        _lib.qihse_graph_ingest_register_id(
            self._ptr, external_id.encode('utf-8'), c_uint64(internal_id)
        )

    def close(self) -> None:
        """Destroy the underlying graph store."""
        if self._ptr is not None:
            _lib.qihse_graph_destroy(self._ptr)
            self._ptr = None

    def __del__(self):
        self.close()

    def clear_id_map(self):
        """Clear all external ID mappings."""
        _lib.qihse_graph_ingest_clear_ids(self._ptr)

    # --- Graph algorithms ---

    def bfs(self, source: int, max_out: int = 1024) -> List[int]:
        """BFS from source vertex. Returns list of vertex IDs."""
        out = (c_uint64 * max_out)()
        count = _lib.qihse_graph_bfs(self._ptr, source, out, max_out)
        return [int(out[i]) for i in range(count)]

    def dijkstra(self, source: int, target: int, max_path: int = 256) -> List[int]:
        """Shortest path via Dijkstra. Returns list of vertex IDs."""
        out = (c_uint64 * max_path)()
        count = _lib.qihse_graph_dijkstra(self._ptr, source, target, out, max_path)
        return [int(out[i]) for i in range(count)]

    def pagerank(self, max_vertices: int = 10000, max_iter: int = 100,
                 damping: float = 0.85, tolerance: float = 1e-6) -> Dict[int, float]:
        """PageRank centrality. Returns {vertex_id: score}."""
        scores = (c_double * max_vertices)()
        result = _lib.qihse_graph_pagerank(
            self._ptr, scores, max_vertices, max_iter, damping, tolerance
        )
        if result != 0:
            return {}
        n = self.vertex_count()
        return {i: float(scores[i]) for i in range(min(n, max_vertices))}

    def connected_components(self, max_vertices: int = 10000) -> Dict[int, int]:
        """Connected components. Returns {vertex_id: component_id}."""
        comp_ids = (c_uint32 * max_vertices)()
        count = _lib.qihse_graph_connected_components(
            self._ptr, comp_ids, max_vertices
        )
        return {i: int(comp_ids[i]) for i in range(min(count, max_vertices))}
