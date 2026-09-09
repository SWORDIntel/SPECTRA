"""
Intelligence Store — QIHSE/KEYSTONE projection for analytical evidence
=====================================================================

Records canonical intelligence objects (``AnalysisEvidence``, ``ActorHypothesis``,
``RelationshipHypothesis``, ``ModelInference``, ``Campaign``) into their SQLite
tables **and** appends them to the ``IndexOutbox`` so they flow through the
same durable outbox → IndexProjector pipeline as all other SPECTRA data.

Every object saved here is projected to:

- ``qihse.intelligence.v1``  — structured intelligence search (evidence,
  hypotheses, inferences, campaigns)
- ``qihse.content.v1``       — full-text + semantic content (all events)
- ``qihse.graph.v1``         — entity graph edges from hypotheses
- ``keystone.ids.v1``        — O(1) anchor lookup by evidence/hypothesis/inference/campaign ID

Usage (library, inside a SpectraDB transaction)::

    from tgarchive.db.intelligence_store import record_evidence
    from tgarchive.intelligence import AnalysisEvidence, EvidenceSource

    record_evidence(connection, evidence)

Usage (standalone)::

    from tgarchive.db.intelligence_store import IntelligenceStore

    with IntelligenceStore("spectra.db") as store:
        store.save_evidence(evidence)
        store.save_hypothesis(hypothesis)
        stats = store.stats()
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .index_outbox import IndexOutbox
from .schema import SCHEMA_SQL
from ..intelligence.schema import (
    SCHEMA_VERSION,
    AnalysisEvidence,
    ActorHypothesis,
    RelationshipHypothesis,
    ModelInference,
    Campaign,
    _dt_to_iso,
)

logger = logging.getLogger(__name__)

# ─── Source table names (match IndexOutbox source_table column) ────────────

EVIDENCE_SOURCE_TABLE = "intelligence_evidence"
HYPOTHESIS_SOURCE_TABLE = "intelligence_hypotheses"
INFERENCE_SOURCE_TABLE = "intelligence_inferences"
CAMPAIGN_SOURCE_TABLE = "intelligence_campaigns"
CONCLUSION_SOURCE_TABLE = "intelligence_conclusions"
PATTERN_SOURCE_TABLE = "intelligence_patterns"
IDENTITY_CLUSTER_SOURCE_TABLE = "identity_clusters"
PROVENANCE_SOURCE_TABLE = "provenance_nodes"

INTELLIGENCE_SOURCE_TABLES = (
    EVIDENCE_SOURCE_TABLE,
    HYPOTHESIS_SOURCE_TABLE,
    INFERENCE_SOURCE_TABLE,
    CAMPAIGN_SOURCE_TABLE,
    CONCLUSION_SOURCE_TABLE,
    PATTERN_SOURCE_TABLE,
    IDENTITY_CLUSTER_SOURCE_TABLE,
    PROVENANCE_SOURCE_TABLE,
)

EVIDENCE_REVISION = f"intelligence-evidence-v{SCHEMA_VERSION}"
HYPOTHESIS_REVISION = f"intelligence-hypothesis-v{SCHEMA_VERSION}"
INFERENCE_REVISION = f"intelligence-inference-v{SCHEMA_VERSION}"
CAMPAIGN_REVISION = f"intelligence-campaign-v{SCHEMA_VERSION}"
CONCLUSION_REVISION = f"intelligence-conclusion-v{SCHEMA_VERSION}"
PATTERN_REVISION = f"intelligence-pattern-v{SCHEMA_VERSION}"
IDENTITY_CLUSTER_REVISION = "identity-cluster-v2.0.0"
PROVENANCE_REVISION = "provenance-node-v1.0.0"

# SQL INSERT statements — column order must match to_sql_row() tuples ───────

_INSERT_EVIDENCE = """
INSERT OR REPLACE INTO intelligence_evidence (
    evidence_id, evidence_type, subject, object, score, confidence,
    direction, model, model_version, feature_schema_version,
    sources_json, observed_at, generated_at, metadata_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_HYPOTHESIS = """
INSERT OR REPLACE INTO intelligence_hypotheses (
    hypothesis_id, hypothesis_type, subject_a, subject_b,
    probability, confidence, supporting_evidence, contradicting_evidence,
    insufficient_flags, model, model_version, generated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_INFERENCE = """
INSERT OR REPLACE INTO intelligence_inferences (
    inference_id, inference_type, model, model_version,
    inputs_json, output_json, confidence, generated_at,
    feature_schema_version
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_CAMPAIGN = """
INSERT OR REPLACE INTO intelligence_campaigns (
    campaign_id, name, actors_json, channels_json, wallets_json,
    domains_json, message_ids_json, media_ids_json, start, end,
    confidence, evidence_ids_json, generated_at, metadata_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_CONCLUSION = """
INSERT OR REPLACE INTO intelligence_conclusions (
    conclusion_id, subject, conclusion_type, probability, confidence,
    supporting_evidence, contradicting_evidence, related_hypotheses,
    related_campaigns, graph_neighbors, evidence_breakdown,
    metadata_json, generated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_PATTERN = """
INSERT OR REPLACE INTO intelligence_patterns (
    pattern_id, pattern_type, description, entities_json, evidence_ids_json,
    frequency, confidence, metadata_json, generated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_IDENTITY_CLUSTER = """
INSERT OR REPLACE INTO identity_clusters (
    cluster_id, confidence, model_version, created_at, updated_at
) VALUES (?, ?, ?, ?, ?)
"""

_INSERT_CLUSTER_MEMBER = """
INSERT OR REPLACE INTO identity_cluster_members (
    cluster_id, candidate_type, candidate_value, candidate_id, evidence_score
) VALUES (?, ?, ?, ?, ?)
"""

_INSERT_PROVENANCE_NODE = """
INSERT OR REPLACE INTO provenance_nodes (
    node_id, node_type, algorithm, version, parameters_json,
    timestamp, input_ids_json, input_hashes_json, output_id, confidence
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


# ─── Module-level record functions (work with an existing connection) ──────


def record_evidence(
    connection: sqlite3.Connection,
    evidence: AnalysisEvidence,
) -> int | None:
    """Save an ``AnalysisEvidence`` to SQLite and append to the IndexOutbox.

    Returns the outbox sequence_id if inserted, ``None`` if deduped.
    """
    connection.execute(_INSERT_EVIDENCE, evidence.to_sql_row())
    payload = evidence.to_dict()
    payload["schema_version"] = SCHEMA_VERSION
    seq_id = IndexOutbox.append_to(
        connection,
        source_table=EVIDENCE_SOURCE_TABLE,
        source_key=evidence.evidence_id,
        event_type="save",
        payload=payload,
        source_revision=EVIDENCE_REVISION,
    )
    if seq_id:
        logger.debug(
            "Evidence recorded: %s [%s] subject=%s seq=%d",
            evidence.evidence_id, evidence.evidence_type, evidence.subject, seq_id,
        )
    return seq_id


def record_hypothesis(
    connection: sqlite3.Connection,
    hypothesis: Union[ActorHypothesis, RelationshipHypothesis],
) -> int | None:
    """Save an ``ActorHypothesis`` or ``RelationshipHypothesis`` to SQLite and
    append to the IndexOutbox.

    ``RelationshipHypothesis`` is stored in the same ``intelligence_hypotheses``
    table with ``subject_a = subject``, ``subject_b = object``, and
    ``insufficient_flags = NULL``.

    Returns the outbox sequence_id if inserted, ``None`` if deduped.
    """
    if isinstance(hypothesis, RelationshipHypothesis):
        row = _relationship_hypothesis_to_row(hypothesis)
        htype = hypothesis.hypothesis_type
        subject_a = hypothesis.subject
        subject_b = hypothesis.object
        hid = hypothesis.hypothesis_id
        payload = hypothesis.to_dict()
        # Normalise payload keys to match the unified table shape
        payload.setdefault("subject_a", subject_a)
        payload.setdefault("subject_b", subject_b)
    else:
        row = hypothesis.to_sql_row()
        htype = (
            hypothesis.hypothesis_type.value
            if isinstance(hypothesis.hypothesis_type, type(hypothesis.hypothesis_type))
            else str(hypothesis.hypothesis_type)
        )
        subject_a = hypothesis.subject_a
        subject_b = hypothesis.subject_b
        hid = hypothesis.hypothesis_id
        payload = hypothesis.to_dict()

    connection.execute(_INSERT_HYPOTHESIS, row)
    payload["schema_version"] = SCHEMA_VERSION
    payload["hypothesis_kind"] = (
        "relationship" if isinstance(hypothesis, RelationshipHypothesis) else "actor"
    )
    seq_id = IndexOutbox.append_to(
        connection,
        source_table=HYPOTHESIS_SOURCE_TABLE,
        source_key=hid,
        event_type="save",
        payload=payload,
        source_revision=HYPOTHESIS_REVISION,
    )
    if seq_id:
        logger.debug(
            "Hypothesis recorded: %s [%s] %s↔%s seq=%d",
            hid, htype, subject_a, subject_b, seq_id,
        )
    return seq_id


def record_inference(
    connection: sqlite3.Connection,
    inference: ModelInference,
) -> int | None:
    """Save a ``ModelInference`` to SQLite and append to the IndexOutbox.

    Returns the outbox sequence_id if inserted, ``None`` if deduped.
    """
    connection.execute(_INSERT_INFERENCE, inference.to_sql_row())
    payload = inference.to_dict()
    payload["schema_version"] = SCHEMA_VERSION
    seq_id = IndexOutbox.append_to(
        connection,
        source_table=INFERENCE_SOURCE_TABLE,
        source_key=inference.inference_id,
        event_type="save",
        payload=payload,
        source_revision=INFERENCE_REVISION,
    )
    if seq_id:
        logger.debug(
            "Inference recorded: %s [%s] seq=%d",
            inference.inference_id, inference.inference_type, seq_id,
        )
    return seq_id


def record_campaign(
    connection: sqlite3.Connection,
    campaign: Campaign,
) -> int | None:
    """Save a ``Campaign`` to SQLite and append to the IndexOutbox.

    Returns the outbox sequence_id if inserted, ``None`` if deduped.
    """
    connection.execute(_INSERT_CAMPAIGN, campaign.to_sql_row())
    payload = campaign.to_dict()
    payload["schema_version"] = SCHEMA_VERSION
    seq_id = IndexOutbox.append_to(
        connection,
        source_table=CAMPAIGN_SOURCE_TABLE,
        source_key=campaign.campaign_id,
        event_type="save",
        payload=payload,
        source_revision=CAMPAIGN_REVISION,
    )
    if seq_id:
        logger.debug(
            "Campaign recorded: %s [%s] seq=%d",
            campaign.campaign_id, campaign.name, seq_id,
        )
    return seq_id


def record_conclusion(
    connection: sqlite3.Connection,
    conclusion: Any,
) -> int | None:
    """Save a ``Conclusion`` to SQLite and append to the IndexOutbox.

    The ``conclusion`` argument must be a ``Conclusion`` dataclass from
    ``tgarchive.intelligence.conclusions`` (imported lazily to avoid circular
    imports).

    Returns the outbox sequence_id if inserted, ``None`` if deduped.
    """
    cdict = conclusion.to_dict()
    row = (
        cdict["conclusion_id"],
        cdict["subject"],
        cdict["conclusion_type"],
        cdict["probability"],
        cdict["confidence"],
        json.dumps(cdict.get("supporting_evidence", [])),
        json.dumps(cdict.get("contradicting_evidence", [])),
        json.dumps(cdict.get("related_hypotheses", [])),
        json.dumps(cdict.get("related_campaigns", [])),
        json.dumps(cdict.get("graph_neighbors", [])),
        json.dumps(cdict.get("evidence_breakdown", {})),
        json.dumps(cdict.get("metadata", {})),
        cdict.get("generated_at", ""),
    )
    connection.execute(_INSERT_CONCLUSION, row)
    payload = cdict
    payload["schema_version"] = SCHEMA_VERSION
    seq_id = IndexOutbox.append_to(
        connection,
        source_table=CONCLUSION_SOURCE_TABLE,
        source_key=cdict["conclusion_id"],
        event_type="save",
        payload=payload,
        source_revision=CONCLUSION_REVISION,
    )
    if seq_id:
        logger.debug(
            "Conclusion recorded: %s [%s] seq=%d",
            cdict["conclusion_id"], cdict["conclusion_type"], seq_id,
        )
    return seq_id


def record_pattern(
    connection: sqlite3.Connection,
    pattern: Any,
) -> int | None:
    """Save a ``Pattern`` to SQLite and append to the IndexOutbox.

    The ``pattern`` argument must be a ``Pattern`` dataclass from
    ``tgarchive.intelligence.patterns`` (imported lazily to avoid circular
    imports).

    Returns the outbox sequence_id if inserted, ``None`` if deduped.
    """
    pdict = pattern.to_dict()
    from datetime import datetime, timezone
    generated_at = pdict.get("generated_at") or datetime.now(timezone.utc).isoformat()
    row = (
        pdict["pattern_id"],
        pdict["pattern_type"],
        pdict.get("description", ""),
        json.dumps(pdict.get("entities", [])),
        json.dumps(pdict.get("evidence_ids", [])),
        pdict.get("frequency", 0),
        pdict.get("confidence", 0.0),
        json.dumps(pdict.get("metadata", {})),
        generated_at,
    )
    connection.execute(_INSERT_PATTERN, row)
    payload = pdict
    payload["schema_version"] = SCHEMA_VERSION
    payload["generated_at"] = generated_at
    seq_id = IndexOutbox.append_to(
        connection,
        source_table=PATTERN_SOURCE_TABLE,
        source_key=pdict["pattern_id"],
        event_type="save",
        payload=payload,
        source_revision=PATTERN_REVISION,
    )
    if seq_id:
        logger.debug(
            "Pattern recorded: %s [%s] seq=%d",
            pdict["pattern_id"], pdict["pattern_type"], seq_id,
        )
    return seq_id


def _candidate_identifier_pairs(candidate: Any) -> List[tuple]:
    """Extract (candidate_type, candidate_value) pairs from an EntityCandidate.

    Each non-None identifier field produces one pair so that
    ``query_identity_clusters`` can match on any of them.
    """
    pairs: List[tuple] = []
    if getattr(candidate, "username", None):
        pairs.append(("username", candidate.username))
    if getattr(candidate, "handle", None):
        pairs.append(("handle", candidate.handle))
    if getattr(candidate, "phone", None):
        pairs.append(("phone", candidate.phone))
    if getattr(candidate, "user_id", None) is not None:
        pairs.append(("user_id", str(candidate.user_id)))
    if getattr(candidate, "display_name", None):
        pairs.append(("display_name", candidate.display_name))
    if getattr(candidate, "source_id", None):
        pairs.append(("source_id", candidate.source_id))
    if not pairs:
        # Fall back to candidate_id so the member row is always populated.
        pairs.append(("candidate_id", candidate.candidate_id))
    return pairs


def record_identity_cluster(
    connection: sqlite3.Connection,
    cluster: Any,
) -> int | None:
    """Save an ``IdentityCluster`` to SQLite and append to the IndexOutbox.

    The ``cluster`` argument must be an ``IdentityCluster`` dataclass from
    ``tgarchive.intelligence.entity_resolver_v2`` (imported lazily to avoid
    circular imports).

    Returns the outbox sequence_id if inserted, ``None`` if deduped.
    """
    now = datetime.now(timezone.utc).isoformat()
    created_at = getattr(cluster, "created_at", None) or now
    updated_at = getattr(cluster, "updated_at", None) or now
    connection.execute(
        _INSERT_IDENTITY_CLUSTER,
        (
            cluster.cluster_id,
            cluster.confidence,
            cluster.model_version,
            created_at,
            updated_at,
        ),
    )
    for candidate in cluster.candidates:
        for ctype, cvalue in _candidate_identifier_pairs(candidate):
            connection.execute(
                _INSERT_CLUSTER_MEMBER,
                (
                    cluster.cluster_id,
                    ctype,
                    cvalue,
                    candidate.candidate_id,
                    cluster.confidence,
                ),
            )
    payload = cluster.to_dict()
    payload["schema_version"] = SCHEMA_VERSION
    seq_id = IndexOutbox.append_to(
        connection,
        source_table=IDENTITY_CLUSTER_SOURCE_TABLE,
        source_key=cluster.cluster_id,
        event_type="save",
        payload=payload,
        source_revision=IDENTITY_CLUSTER_REVISION,
    )
    if seq_id:
        logger.debug(
            "Identity cluster recorded: %s [conf=%.2f] seq=%d",
            cluster.cluster_id, cluster.confidence, seq_id,
        )
    return seq_id


def record_provenance_node(
    connection: sqlite3.Connection,
    node: Any,
) -> int | None:
    """Save a ``ProvenanceNode`` to SQLite and append to the IndexOutbox.

    The ``node`` argument must be a ``ProvenanceNode`` dataclass from
    ``tgarchive.intelligence.provenance_graph`` (imported lazily to avoid
    circular imports).

    Returns the outbox sequence_id if inserted, ``None`` if deduped.
    """
    connection.execute(
        _INSERT_PROVENANCE_NODE,
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
    payload = node.to_dict()
    payload["schema_version"] = SCHEMA_VERSION
    seq_id = IndexOutbox.append_to(
        connection,
        source_table=PROVENANCE_SOURCE_TABLE,
        source_key=node.node_id,
        event_type="save",
        payload=payload,
        source_revision=PROVENANCE_REVISION,
    )
    if seq_id:
        logger.debug(
            "Provenance node recorded: %s [%s] seq=%d",
            node.node_id, node.node_type, seq_id,
        )
    return seq_id


def _relationship_hypothesis_to_row(h: RelationshipHypothesis) -> tuple:
    """Convert a RelationshipHypothesis to a row matching intelligence_hypotheses."""
    return (
        h.hypothesis_id,
        h.hypothesis_type,
        h.subject,        # → subject_a
        h.object,         # → subject_b
        h.probability,
        h.confidence,
        json.dumps(h.supporting_evidence),
        json.dumps(h.contradicting_evidence),
        None,             # insufficient_flags — not applicable
        h.model,
        h.model_version,
        _dt_to_iso(h.generated_at),
    )


# ─── IntelligenceStore — standalone wrapper with own connection ────────────


class IntelligenceStore:
    """Standalone intelligence store managing its own SQLite connection.

    Provides convenience methods for saving and querying intelligence objects.
    For use inside SpectraDB transactions, use the module-level ``record_*``
    functions instead.
    """

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA_SQL)
            IndexOutbox.ensure_schema(self._conn)
        return self._conn

    # ── Save methods ───────────────────────────────────────────────────

    def save_evidence(self, evidence: AnalysisEvidence) -> int | None:
        conn = self._connection()
        seq = record_evidence(conn, evidence)
        conn.commit()
        return seq

    def save_hypothesis(
        self, hypothesis: Union[ActorHypothesis, RelationshipHypothesis]
    ) -> int | None:
        conn = self._connection()
        seq = record_hypothesis(conn, hypothesis)
        conn.commit()
        return seq

    def save_inference(self, inference: ModelInference) -> int | None:
        conn = self._connection()
        seq = record_inference(conn, inference)
        conn.commit()
        return seq

    def save_campaign(self, campaign: Campaign) -> int | None:
        conn = self._connection()
        seq = record_campaign(conn, campaign)
        conn.commit()
        return seq

    def save_conclusion(self, conclusion: Any) -> int | None:
        """Save a Conclusion and append to the IndexOutbox."""
        conn = self._connection()
        seq = record_conclusion(conn, conclusion)
        conn.commit()
        return seq

    def save_pattern(self, pattern: Any) -> int | None:
        """Save a Pattern and append to the IndexOutbox."""
        conn = self._connection()
        seq = record_pattern(conn, pattern)
        conn.commit()
        return seq

    def save_identity_cluster(self, cluster: Any) -> str:
        """Persist an ``IdentityCluster`` to the database.

        Saves the cluster header and all candidate member rows, then appends
        to the IndexOutbox so the cluster flows through the projection
        pipeline.

        Returns the ``cluster_id``.
        """
        conn = self._connection()
        record_identity_cluster(conn, cluster)
        conn.commit()
        return cluster.cluster_id

    def save_provenance_node(self, node: Any) -> str:
        """Persist a ``ProvenanceNode`` to the database.

        Saves the node to the ``provenance_nodes`` table and appends to the
        IndexOutbox.

        Returns the ``node_id``.
        """
        conn = self._connection()
        record_provenance_node(conn, node)
        conn.commit()
        return node.node_id

    # ── Query methods ──────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return aggregate statistics across all intelligence tables."""
        conn = self._connection()
        result: Dict[str, Any] = {}
        for table in INTELLIGENCE_SOURCE_TABLES:
            try:
                row = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()
                result[table] = int(row[0]) if row else 0
            except sqlite3.OperationalError:
                result[table] = 0
        # Outbox counts
        outbox_counts: Dict[str, int] = {}
        for table in INTELLIGENCE_SOURCE_TABLES:
            row = conn.execute(
                "SELECT COUNT(*) FROM index_outbox WHERE source_table = ?",
                (table,),
            ).fetchone()
            outbox_counts[table] = int(row[0]) if row else 0
        result["outbox"] = outbox_counts
        return result

    def query_evidence(
        self,
        *,
        evidence_type: Optional[str] = None,
        subject: Optional[str] = None,
        direction: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query evidence from the SQLite table with optional filters."""
        conn = self._connection()
        clauses: List[str] = []
        params: List[Any] = []
        if evidence_type:
            clauses.append("evidence_type = ?")
            params.append(evidence_type)
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        if direction:
            clauses.append("direction = ?")
            params.append(direction)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM intelligence_evidence{where} ORDER BY generated_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows] if rows else []

    def query_hypotheses(
        self,
        *,
        hypothesis_type: Optional[str] = None,
        subject_a: Optional[str] = None,
        min_probability: float = 0.0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query hypotheses from the SQLite table with optional filters."""
        conn = self._connection()
        clauses = ["probability >= ?"]
        params: List[Any] = [min_probability]
        if hypothesis_type:
            clauses.append("hypothesis_type = ?")
            params.append(hypothesis_type)
        if subject_a:
            clauses.append("(subject_a = ? OR subject_b = ?)")
            params.extend([subject_a, subject_a])
        where = f" WHERE {' AND '.join(clauses)}"
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM intelligence_hypotheses{where} ORDER BY probability DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows] if rows else []

    def query_campaigns(
        self,
        *,
        name: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query campaigns from the SQLite table."""
        conn = self._connection()
        if name:
            rows = conn.execute(
                "SELECT * FROM intelligence_campaigns WHERE name LIKE ? ORDER BY generated_at DESC LIMIT ?",
                (f"%{name}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM intelligence_campaigns ORDER BY generated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows] if rows else []

    def recent_evidence(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent evidence from the outbox (pre-projection)."""
        conn = self._connection()
        rows = conn.execute(
            """
            SELECT sequence_id, source_key, payload_json, created_at
            FROM index_outbox
            WHERE source_table = ?
            ORDER BY sequence_id DESC
            LIMIT ?
            """,
            (EVIDENCE_SOURCE_TABLE, limit),
        ).fetchall()
        results = []
        for row in rows:
            payload = json.loads(row[2])
            payload["sequence_id"] = row[0]
            payload["recorded_at"] = row[3]
            results.append(payload)
        return results

    def query_identity_clusters(
        self,
        entity_id: str,
        *,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Find identity clusters containing a candidate matching *entity_id*.

        Searches the ``identity_cluster_members`` table for any member whose
        ``candidate_value`` matches *entity_id* (e.g. a user_id string,
        username, handle, or canonical ID).  Returns the matching cluster
        rows joined with their members.

        Args:
            entity_id: The entity identifier to search for (user_id, username,
                handle, canonical ID, etc.).
            limit: Maximum number of clusters to return.

        Returns:
            A list of dicts, each with cluster fields and a ``members`` list.
        """
        conn = self._connection()
        # Find distinct cluster_ids whose members match the entity_id.
        try:
            cluster_rows = conn.execute(
                """
                SELECT DISTINCT c.cluster_id, c.confidence, c.model_version,
                       c.created_at, c.updated_at
                FROM identity_clusters c
                JOIN identity_cluster_members m ON m.cluster_id = c.cluster_id
                WHERE m.candidate_value = ?
                   OR m.candidate_id = ?
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (entity_id, entity_id, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        if not cluster_rows:
            return []
        results: List[Dict[str, Any]] = []
        for crow in cluster_rows:
            cid = crow["cluster_id"]
            member_rows = conn.execute(
                """
                SELECT candidate_type, candidate_value, candidate_id,
                       evidence_score
                FROM identity_cluster_members
                WHERE cluster_id = ?
                """,
                (cid,),
            ).fetchall()
            members = [dict(m) for m in member_rows]
            results.append({
                "cluster_id": cid,
                "confidence": crow["confidence"],
                "model_version": crow["model_version"],
                "created_at": crow["created_at"],
                "updated_at": crow["updated_at"],
                "members": members,
            })
        return results

    def query_provenance(
        self,
        object_id: str,
        *,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get the provenance chain for an object from the ``provenance_nodes`` table.

        Traces backwards from *object_id* through input_ids to build the full
        derivation chain, ordered from newest to oldest.

        Args:
            object_id: The ID of the object to trace.
            limit: Maximum number of nodes to return.

        Returns:
            A list of dicts representing provenance nodes.
        """
        conn = self._connection()
        chain: List[Dict[str, Any]] = []
        visited: set = set()
        queue: List[str] = [object_id]
        try:
            while queue and len(chain) < limit:
                current = queue.pop(0)
                rows = conn.execute(
                    """
                    SELECT node_id, node_type, algorithm, version,
                           parameters_json, timestamp, input_ids_json,
                           input_hashes_json, output_id, confidence
                    FROM provenance_nodes
                    WHERE output_id = ?
                    """,
                    (current,),
                ).fetchall()
                for row in rows:
                    nid = row["node_id"]
                    if nid in visited:
                        continue
                    visited.add(nid)
                    input_ids = json.loads(row["input_ids_json"]) if row["input_ids_json"] else []
                    chain.append({
                        "node_id": nid,
                        "node_type": row["node_type"],
                        "algorithm": row["algorithm"],
                        "version": row["version"],
                        "parameters": json.loads(row["parameters_json"]) if row["parameters_json"] else {},
                        "timestamp": row["timestamp"],
                        "input_ids": input_ids,
                        "input_hashes": json.loads(row["input_hashes_json"]) if row["input_hashes_json"] else [],
                        "output_id": row["output_id"],
                        "confidence": row["confidence"],
                    })
                    queue.extend(input_ids)
        except sqlite3.OperationalError:
            return []
        return chain

    # ── Lifecycle ──────────────────────────────────────────────────────

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self._connection()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
