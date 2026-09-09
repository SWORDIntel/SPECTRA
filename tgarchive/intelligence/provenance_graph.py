"""
SPECTRA Provenance Graph
========================

Records the full chain of transformations that produce every derived object
in the intelligence pipeline — from raw source events through evidence,
hypotheses, and conclusions.

Every derived object records its provenance::

    source_event → entity → message → evidence → hypothesis → conclusion

Each ``ProvenanceNode`` captures *what* algorithm produced an output, *which
version* of that algorithm ran, *what parameters* were used, and *which inputs*
fed into it.  This makes the entire pipeline replayable: change an algorithm,
replay the chain, and a new provenance graph is produced.

The graph is stored in-memory (dict-based) with optional SQLite persistence
so it can survive across sessions and be queried by analysts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"

# Valid node types in the provenance graph.
NODE_TYPES = frozenset(
    {
        "source_event",
        "entity",
        "media",
        "message",
        "evidence",
        "hypothesis",
        "conclusion",
    }
)


# ─── Data model ──────────────────────────────────────────────────────────────


@dataclass
class ProvenanceNode:
    """A single node in the provenance graph.

    Attributes:
        node_id: Deterministic ID for this node (== output_id).
        node_type: One of ``NODE_TYPES`` — the kind of object produced.
        algorithm: Name of the algorithm/module that produced this output.
        version: Version string of the algorithm.
        parameters: Algorithm parameters used (for replayability).
        timestamp: ISO-8601 timestamp of when the derivation was recorded.
        input_ids: IDs of the objects this output was derived from.
        input_hashes: Content hashes of the inputs (integrity check).
        output_id: The ID of the object produced by this derivation.
        confidence: Confidence score of the output, in [0, 1].
    """

    node_id: str
    node_type: str
    algorithm: str
    version: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    input_ids: List[str] = field(default_factory=list)
    input_hashes: List[str] = field(default_factory=list)
    output_id: str = ""
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if self.node_type not in NODE_TYPES:
            raise ValueError(
                f"invalid node_type {self.node_type!r}; "
                f"expected one of {sorted(NODE_TYPES)}"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        if not self.output_id:
            self.output_id = self.node_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "algorithm": self.algorithm,
            "version": self.version,
            "parameters": self.parameters,
            "timestamp": self.timestamp,
            "input_ids": self.input_ids,
            "input_hashes": self.input_hashes,
            "output_id": self.output_id,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProvenanceNode":
        return cls(
            node_id=d["node_id"],
            node_type=d["node_type"],
            algorithm=d["algorithm"],
            version=d["version"],
            parameters=d.get("parameters", {}),
            timestamp=d.get("timestamp", datetime.now(timezone.utc).isoformat()),
            input_ids=d.get("input_ids", []),
            input_hashes=d.get("input_hashes", []),
            output_id=d.get("output_id", d["node_id"]),
            confidence=d.get("confidence", 0.0),
        )


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _node_id(
    output_id: str,
    algorithm: str,
    version: str,
    input_ids: List[str],
) -> str:
    """Deterministic 16-hex-char node ID."""
    payload = "|".join(
        [output_id, algorithm, version, ",".join(sorted(input_ids))]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _content_hash(data: Any) -> str:
    """SHA-256 content hash of arbitrary JSON-serializable data."""
    try:
        payload = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    except (TypeError, ValueError):
        payload = str(data).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# ─── ProvenanceGraph ─────────────────────────────────────────────────────────


class ProvenanceGraph:
    """In-memory provenance graph with optional SQLite persistence.

    Every call to :meth:`record_derivation` creates a ``ProvenanceNode`` that
    links an output object to its inputs.  The graph can then be traversed
    backwards from any object to its source events via
    :meth:`trace_provenance`, or explained in human-readable form via
    :meth:`explain`.

    Usage::

        graph = ProvenanceGraph()
        graph.record_derivation(
            output_id="evidence:abc",
            input_ids=["message:1", "message:2"],
            algorithm="entity_resolver_v2",
            version="2.0.0",
            parameters={"threshold": 0.85},
            confidence=0.92,
            node_type="evidence",
        )
        chain = graph.trace_provenance("evidence:abc")
        print(graph.explain("evidence:abc"))
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS provenance_nodes (
        node_id TEXT PRIMARY KEY,
        node_type TEXT NOT NULL,
        algorithm TEXT NOT NULL,
        version TEXT NOT NULL,
        parameters_json TEXT,
        timestamp TEXT NOT NULL,
        input_ids_json TEXT NOT NULL,
        input_hashes_json TEXT NOT NULL,
        output_id TEXT NOT NULL,
        confidence REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_prov_output ON provenance_nodes(output_id);
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        connection: Optional[sqlite3.Connection] = None,
    ) -> None:
        """Initialize the graph.

        Args:
            db_path: Optional path to a SQLite database for persistence.
                If provided, nodes are loaded from and saved to the database.
                If ``None`` (and *connection* is also ``None``), the graph is
                purely in-memory.
            connection: Optional existing ``sqlite3.Connection`` to use for
                persistence (e.g. a shared spectra.db connection).  When
                provided, the graph writes provenance nodes to the same
                database as the rest of SPECTRA instead of a sidecar DB.
                The connection is **not** closed by the graph — the caller
                retains ownership.
        """
        self._nodes: Dict[str, ProvenanceNode] = {}
        # Reverse index: output_id → list of node_ids that produced it.
        self._by_output: Dict[str, List[str]] = {}
        self._db_path: Optional[str] = db_path
        self._connection: Optional[sqlite3.Connection] = connection
        self._owns_connection = connection is None
        if connection is not None:
            self._init_db_with_connection(connection)
            self._load_from_connection(connection)
        elif db_path:
            self._init_db(db_path)
            self._load_from_db()

    # ── public API ───────────────────────────────────────────────────────────

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> "ProvenanceGraph":
        """Create a ProvenanceGraph backed by an existing SQLite connection.

        This is the preferred way to integrate provenance tracking with the
        main SPECTRA database (spectra.db) so that provenance nodes share
        the same database as evidence, hypotheses, and conclusions.

        The connection is **not** closed by the graph — the caller retains
        ownership and is responsible for committing/closing.
        """
        return cls(connection=conn)

    def record_derivation(
        self,
        output_id: str,
        input_ids: List[str],
        algorithm: str,
        version: str,
        parameters: Optional[Dict[str, Any]] = None,
        confidence: float = 0.0,
        node_type: str = "evidence",
        input_hashes: Optional[List[str]] = None,
    ) -> ProvenanceNode:
        """Record that *output_id* was derived from *input_ids* by *algorithm*.

        Args:
            output_id: The ID of the object produced.
            input_ids: IDs of the objects this output was derived from.
            algorithm: Name of the algorithm/module that produced the output.
            version: Version string of the algorithm.
            parameters: Algorithm parameters used (for replayability).
            confidence: Confidence score of the output, in [0, 1].
            node_type: Type of the output node (one of ``NODE_TYPES``).
            input_hashes: Optional content hashes of the inputs.  If not
                provided, empty list is used.

        Returns:
            The created ``ProvenanceNode``.
        """
        if not output_id:
            raise ValueError("output_id must not be empty")
        node_id = _node_id(output_id, algorithm, version, input_ids)
        node = ProvenanceNode(
            node_id=node_id,
            node_type=node_type,
            algorithm=algorithm,
            version=version,
            parameters=parameters or {},
            input_ids=list(input_ids),
            input_hashes=input_hashes or [],
            output_id=output_id,
            confidence=confidence,
        )
        self._nodes[node_id] = node
        self._by_output.setdefault(output_id, []).append(node_id)
        if self._connection is not None:
            self._persist_node_to_connection(node)
        elif self._db_path:
            self._persist_node(node)
        return node

    def trace_provenance(self, object_id: str) -> List[ProvenanceNode]:
        """Trace the full provenance chain backwards from *object_id*.

        Performs a depth-first traversal from the given object back to its
        source events.  The returned list is ordered from the most recent
        derivation (the node that produced *object_id*) to the oldest source
        events.

        Args:
            object_id: The ID of the object to trace.

        Returns:
            A list of ``ProvenanceNode`` objects forming the provenance chain,
            ordered from newest to oldest.  Returns an empty list if the
            object has no recorded provenance.
        """
        chain: List[ProvenanceNode] = []
        visited: Set[str] = set()
        self._trace(object_id, chain, visited)
        return chain

    def explain(self, object_id: str) -> str:
        """Generate a human-readable explanation of how *object_id* was derived.

        Produces a multi-line string describing each step in the provenance
        chain, from the final output back to the original source events.

        Args:
            object_id: The ID of the object to explain.

        Returns:
            A human-readable explanation string.
        """
        chain = self.trace_provenance(object_id)
        if not chain:
            return f"No provenance recorded for object '{object_id}'."

        lines: List[str] = []
        lines.append(f"Provenance chain for '{object_id}' ({len(chain)} steps):")
        lines.append("=" * 60)
        for i, node in enumerate(chain):
            indent = "  " * min(i, 4)  # cap indentation for deep chains
            inputs_str = (
                ", ".join(node.input_ids) if node.input_ids else "(no inputs)"
            )
            lines.append(
                f"{indent}Step {i + 1}: {node.node_type} '{node.output_id}'"
            )
            lines.append(
                f"{indent}  produced by: {node.algorithm} v{node.version}"
            )
            lines.append(f"{indent}  confidence: {node.confidence:.2f}")
            lines.append(f"{indent}  inputs: {inputs_str}")
            if node.parameters:
                params_str = ", ".join(
                    f"{k}={v!r}" for k, v in node.parameters.items()
                )
                lines.append(f"{indent}  parameters: {params_str}")
            lines.append("")
        # Identify source events (nodes with no inputs).
        sources = [n for n in chain if not n.input_ids]
        if sources:
            lines.append(
                f"Source events: {', '.join(s.output_id for s in sources)}"
            )
        return "\n".join(lines)

    def get_node(self, node_id: str) -> Optional[ProvenanceNode]:
        """Retrieve a single node by its node_id."""
        return self._nodes.get(node_id)

    def get_nodes_for_output(self, output_id: str) -> List[ProvenanceNode]:
        """Return all nodes that produced the given output_id."""
        return [
            self._nodes[nid] for nid in self._by_output.get(output_id, [])
        ]

    @property
    def node_count(self) -> int:
        """Total number of nodes in the graph."""
        return len(self._nodes)

    def all_nodes(self) -> List[ProvenanceNode]:
        """Return all nodes in the graph (no particular order)."""
        return list(self._nodes.values())

    def reset(self) -> None:
        """Clear all in-memory nodes (does not touch the SQLite DB)."""
        self._nodes.clear()
        self._by_output.clear()

    # ── internals ────────────────────────────────────────────────────────────

    def _trace(
        self,
        object_id: str,
        chain: List[ProvenanceNode],
        visited: Set[str],
    ) -> None:
        """Recursive depth-first provenance traversal."""
        node_ids = self._by_output.get(object_id, [])
        for nid in node_ids:
            if nid in visited:
                continue
            visited.add(nid)
            node = self._nodes[nid]
            chain.append(node)
            for inp_id in node.input_ids:
                self._trace(inp_id, chain, visited)

    # ── SQLite persistence ───────────────────────────────────────────────────

    def _init_db(self, db_path: str) -> None:
        """Create the provenance table if it doesn't exist."""
        try:
            conn = sqlite3.connect(db_path)
            conn.executescript(self._SCHEMA)
            conn.commit()
            conn.close()
        except sqlite3.Error as exc:
            logger.error("provenance DB init failed: %s", exc)
            self._db_path = None

    def _init_db_with_connection(self, conn: sqlite3.Connection) -> None:
        """Ensure the provenance table exists on an existing connection."""
        try:
            conn.executescript(self._SCHEMA)
            conn.commit()
        except sqlite3.Error as exc:
            logger.error("provenance DB init (connection) failed: %s", exc)
            self._connection = None

    def _persist_node(self, node: ProvenanceNode) -> None:
        """Insert or replace a node in the SQLite database (db_path mode)."""
        if not self._db_path:
            return
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """INSERT OR REPLACE INTO provenance_nodes
                   (node_id, node_type, algorithm, version, parameters_json,
                    timestamp, input_ids_json, input_hashes_json, output_id, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    node.node_id,
                    node.node_type,
                    node.algorithm,
                    node.version,
                    json.dumps(node.parameters),
                    node.timestamp,
                    json.dumps(node.input_ids),
                    json.dumps(node.input_hashes),
                    node.output_id,
                    node.confidence,
                ),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as exc:
            logger.error("provenance persist failed: %s", exc)

    def _persist_node_to_connection(self, node: ProvenanceNode) -> None:
        """Insert or replace a node using the shared connection."""
        if self._connection is None:
            return
        try:
            self._connection.execute(
                """INSERT OR REPLACE INTO provenance_nodes
                   (node_id, node_type, algorithm, version, parameters_json,
                    timestamp, input_ids_json, input_hashes_json, output_id, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    node.node_id,
                    node.node_type,
                    node.algorithm,
                    node.version,
                    json.dumps(node.parameters),
                    node.timestamp,
                    json.dumps(node.input_ids),
                    json.dumps(node.input_hashes),
                    node.output_id,
                    node.confidence,
                ),
            )
            self._connection.commit()
        except sqlite3.Error as exc:
            logger.error("provenance persist (connection) failed: %s", exc)

    def _load_from_db(self) -> None:
        """Load all nodes from the SQLite database into memory."""
        if not self._db_path:
            return
        try:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                """SELECT node_id, node_type, algorithm, version, parameters_json,
                          timestamp, input_ids_json, input_hashes_json, output_id,
                          confidence
                   FROM provenance_nodes"""
            ).fetchall()
            conn.close()
        except sqlite3.Error as exc:
            logger.error("provenance load failed: %s", exc)
            return
        self._populate_nodes(rows)

    def _load_from_connection(self, conn: sqlite3.Connection) -> None:
        """Load all nodes from the shared connection into memory."""
        try:
            rows = conn.execute(
                """SELECT node_id, node_type, algorithm, version, parameters_json,
                          timestamp, input_ids_json, input_hashes_json, output_id,
                          confidence
                   FROM provenance_nodes"""
            ).fetchall()
        except sqlite3.Error as exc:
            logger.error("provenance load (connection) failed: %s", exc)
            return
        self._populate_nodes(rows)

    def _populate_nodes(self, rows) -> None:
        """Populate in-memory indices from raw DB rows."""
        for row in rows:
            try:
                node = ProvenanceNode(
                    node_id=row[0],
                    node_type=row[1],
                    algorithm=row[2],
                    version=row[3],
                    parameters=json.loads(row[4]) if row[4] else {},
                    timestamp=row[5],
                    input_ids=json.loads(row[6]) if row[6] else [],
                    input_hashes=json.loads(row[7]) if row[7] else [],
                    output_id=row[8],
                    confidence=row[9],
                )
                self._nodes[node.node_id] = node
                self._by_output.setdefault(node.output_id, []).append(
                    node.node_id
                )
            except (ValueError, json.JSONDecodeError) as exc:
                logger.warning("skipping malformed provenance row: %s", exc)


__all__ = [
    "ProvenanceNode",
    "ProvenanceGraph",
    "NODE_TYPES",
    "SCHEMA_VERSION",
]
