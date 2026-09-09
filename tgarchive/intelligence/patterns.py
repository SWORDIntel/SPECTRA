"""
Pattern Matching Engine — Detect recurring patterns, clusters, and cross-actor signatures
========================================================================================

Analyzes intelligence evidence and hypotheses to identify:
- Similar evidence items based on score proximity within evidence types
- Evidence clusters sharing common subjects/objects (connected components)
- Recurring behavioral patterns across multiple distinct actors
- Cross-actor patterns derived from strong same-actor hypotheses

Usage (library)::

    from tgarchive.intelligence.patterns import PatternMatcher

    with PatternMatcher("spectra.db") as matcher:
        patterns = matcher.detect_recurring_patterns(min_cluster_size=3)
        clusters = matcher.find_evidence_clusters("telegram:user:123")
        cross = matcher.find_cross_actor_patterns()
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..db.schema import SCHEMA_SQL
from ..db.index_outbox import IndexOutbox
from .schema import AnalysisEvidence, EvidenceDirection, canonical_id

logger = logging.getLogger(__name__)

# Source table names (avoid circular import from intelligence_store)
EVIDENCE_SOURCE_TABLE = "intelligence_evidence"
HYPOTHESIS_SOURCE_TABLE = "intelligence_hypotheses"
CAMPAIGN_SOURCE_TABLE = "intelligence_campaigns"


# ─── Pattern ID Generator ───────────────────────────────────────────────────


def generate_pattern_id(
    pattern_type: str,
    entities: List[str],
    evidence_ids: List[str],
) -> str:
    """Generate a deterministic 16-hex-char pattern ID from sorted inputs."""
    sorted_entities = sorted(str(e) for e in entities)
    sorted_evidence = sorted(str(e) for e in evidence_ids)
    payload = (
        pattern_type
        + "|"
        + ",".join(sorted_entities)
        + "|"
        + ",".join(sorted_evidence)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ─── Pattern Dataclass ──────────────────────────────────────────────────────


@dataclass
class Pattern:
    """A detected pattern or behavioral signature across intelligence entities."""

    pattern_id: str
    pattern_type: str
    description: str
    entities: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    frequency: int = 0
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.pattern_id:
            self.pattern_id = generate_pattern_id(
                self.pattern_type,
                self.entities,
                self.evidence_ids,
            )
        if not (0.0 <= self.confidence <= 1.0):
            self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "description": self.description,
            "entities": self.entities,
            "evidence_ids": self.evidence_ids,
            "frequency": self.frequency,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Pattern:
        return cls(
            pattern_id=d.get("pattern_id", ""),
            pattern_type=d["pattern_type"],
            description=d.get("description", ""),
            entities=d.get("entities", []),
            evidence_ids=d.get("evidence_ids", []),
            frequency=d.get("frequency", 0),
            confidence=d.get("confidence", 0.0),
            metadata=d.get("metadata", {}),
        )


# ─── PatternMatcher Engine ──────────────────────────────────────────────────


class PatternMatcher:
    """Pattern matching engine over intelligence evidence and hypotheses."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA_SQL)
            IndexOutbox.ensure_schema(self._conn)
        return self._conn

    def find_similar_evidence(
        self, evidence: AnalysisEvidence, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Find evidence similar to the given evidence.

        Tries the QIHSE intelligence vector index first (semantic similarity
        on 64-dim feature vectors). Falls back to SQL score-proximity search
        if the vector index is unavailable or empty.

        Returns a list of dicts with:
        evidence_id, evidence_type, subject, object, score, confidence, similarity.
        """
        # ── Try QIHSE vector index first ────────────────────────────────
        try:
            from .vectors import IntelligenceVectorIndex
            index = IntelligenceVectorIndex(self.db_path)
            try:
                hits = index.search_similar(evidence, limit=limit)
                if hits:
                    return self._resolve_vector_hits(hits, limit)
            finally:
                index.close()
        except Exception:
            pass  # Fall back to SQL

        # ── Fallback: SQL score-proximity search ────────────────────────
        conn = self._connection()
        try:
            target_score = float(evidence.score)
            rows = conn.execute(
                f"""
                SELECT evidence_id, evidence_type, subject, object, score, confidence
                FROM {EVIDENCE_SOURCE_TABLE}
                WHERE evidence_type = ? AND ABS(score - ?) < 0.2
                ORDER BY ABS(score - ?)
                LIMIT ?
                """,
                (evidence.evidence_type, target_score, target_score, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        results: List[Dict[str, Any]] = []
        for row in rows:
            score = float(row["score"]) if row["score"] is not None else 0.0
            conf = (
                float(row["confidence"])
                if row["confidence"] is not None
                else 0.0
            )
            sim = max(0.0, min(1.0, 1.0 - abs(score - target_score)))
            results.append(
                {
                    "evidence_id": row["evidence_id"],
                    "evidence_type": row["evidence_type"],
                    "subject": row["subject"],
                    "object": row["object"],
                    "score": score,
                    "confidence": conf,
                    "similarity": sim,
                }
            )
        return results

    def _resolve_vector_hits(
        self, hits: List[Dict[str, Any]], limit: int
    ) -> List[Dict[str, Any]]:
        """Resolve QIHSE vector search hits back to evidence rows.

        Each hit has 'id' (sequence_id) and 'score' (cosine similarity).
        We look up the evidence by matching the outbox sequence_id, then
        fetch the full evidence row.
        """
        conn = self._connection()
        results: List[Dict[str, Any]] = []
        for hit in hits[:limit]:
            seq_id = int(hit.get("id", 0))
            score = float(hit.get("score", 0.0))
            # Look up evidence_id from the outbox by sequence_id
            try:
                row = conn.execute(
                    f"""
                    SELECT source_key FROM index_outbox
                    WHERE sequence_id = ? AND source_table = ?
                    """,
                    (seq_id, EVIDENCE_SOURCE_TABLE),
                ).fetchone()
                if not row:
                    continue
                evidence_id = row["source_key"]
                ev_row = conn.execute(
                    f"""
                    SELECT evidence_id, evidence_type, subject, object, score, confidence
                    FROM {EVIDENCE_SOURCE_TABLE}
                    WHERE evidence_id = ?
                    """,
                    (evidence_id,),
                ).fetchone()
                if ev_row:
                    results.append({
                        "evidence_id": ev_row["evidence_id"],
                        "evidence_type": ev_row["evidence_type"],
                        "subject": ev_row["subject"],
                        "object": ev_row["object"],
                        "score": float(ev_row["score"]) if ev_row["score"] else 0.0,
                        "confidence": float(ev_row["confidence"]) if ev_row["confidence"] else 0.0,
                        "similarity": max(0.0, min(1.0, score)),
                    })
            except sqlite3.OperationalError:
                continue
        return results

    def cluster_evidence_by_type(
        self, entity_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Group evidence by evidence_type.

        If entity_id is provided, filter WHERE subject = ? OR object = ?.
        Returns a list of dicts with:
        evidence_type, count, avg_score, avg_confidence, subjects, evidence_ids.
        """
        conn = self._connection()
        try:
            if entity_id:
                rows = conn.execute(
                    f"""
                    SELECT evidence_id, evidence_type, subject, object, score, confidence
                    FROM {EVIDENCE_SOURCE_TABLE}
                    WHERE subject = ? OR object = ?
                    """,
                    (entity_id, entity_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT evidence_id, evidence_type, subject, object, score, confidence
                    FROM {EVIDENCE_SOURCE_TABLE}
                    """
                ).fetchall()
        except sqlite3.OperationalError:
            return []

        groups: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            etype = row["evidence_type"]
            if etype not in groups:
                groups[etype] = {
                    "evidence_type": etype,
                    "scores": [],
                    "confidences": [],
                    "subjects": set(),
                    "evidence_ids": [],
                }
            if row["score"] is not None:
                groups[etype]["scores"].append(float(row["score"]))
            if row["confidence"] is not None:
                groups[etype]["confidences"].append(float(row["confidence"]))
            if row["subject"]:
                groups[etype]["subjects"].add(row["subject"])
            groups[etype]["evidence_ids"].append(row["evidence_id"])

        results: List[Dict[str, Any]] = []
        for etype, data in groups.items():
            scores = data["scores"]
            confidences = data["confidences"]
            count = len(data["evidence_ids"])
            avg_score = sum(scores) / len(scores) if scores else 0.0
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            results.append(
                {
                    "evidence_type": etype,
                    "count": count,
                    "avg_score": avg_score,
                    "avg_confidence": avg_conf,
                    "subjects": sorted(data["subjects"]),
                    "evidence_ids": data["evidence_ids"],
                }
            )
        return results

    def detect_recurring_patterns(
        self, min_cluster_size: int = 3
    ) -> List[Pattern]:
        """Find evidence_types appearing across multiple distinct actors.

        Query: SELECT evidence_type, COUNT(DISTINCT subject) as actor_count, COUNT(*) as freq
        FROM intelligence_evidence GROUP BY evidence_type HAVING actor_count >= min_cluster_size.
        For each, gather all subjects and evidence_ids.
        Create Pattern with confidence = min(actor_count / freq, 1.0).
        """
        conn = self._connection()
        try:
            rows = conn.execute(
                f"""
                SELECT evidence_type, COUNT(DISTINCT subject) as actor_count, COUNT(*) as freq
                FROM {EVIDENCE_SOURCE_TABLE}
                GROUP BY evidence_type
                HAVING actor_count >= ?
                """,
                (min_cluster_size,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        patterns: List[Pattern] = []
        for row in rows:
            etype = row["evidence_type"]
            actor_count = int(row["actor_count"])
            freq = int(row["freq"])

            try:
                ev_rows = conn.execute(
                    f"""
                    SELECT evidence_id, subject, object
                    FROM {EVIDENCE_SOURCE_TABLE}
                    WHERE evidence_type = ?
                    """,
                    (etype,),
                ).fetchall()
            except sqlite3.OperationalError:
                continue

            subjects = sorted(
                {r["subject"] for r in ev_rows if r["subject"]}
            )
            evidence_ids = [r["evidence_id"] for r in ev_rows]
            confidence = (
                min(float(actor_count) / float(freq), 1.0) if freq > 0 else 0.0
            )

            pattern = Pattern(
                pattern_id="",
                pattern_type=f"recurring:{etype}",
                description=(
                    f"Evidence type '{etype}' observed across {actor_count} "
                    f"distinct subjects ({freq} occurrences)"
                ),
                entities=subjects,
                evidence_ids=evidence_ids,
                frequency=freq,
                confidence=confidence,
                metadata={
                    "evidence_type": etype,
                    "actor_count": actor_count,
                    "frequency": freq,
                },
            )
            patterns.append(pattern)

        return patterns

    def find_evidence_clusters(self, entity_id: str) -> List[Dict[str, Any]]:
        """Find connected components of evidence sharing subjects/objects.

        Start with evidence WHERE subject = entity_id OR object = entity_id.
        Then BFS: for each evidence's subject and object, find more evidence.
        Build adjacency graph. Return list of:
        {cluster_id, entities, evidence_ids, evidence_types, size}.
        """
        conn = self._connection()
        try:
            initial_rows = conn.execute(
                f"""
                SELECT evidence_id, evidence_type, subject, object
                FROM {EVIDENCE_SOURCE_TABLE}
                WHERE subject = ? OR object = ?
                """,
                (entity_id, entity_id),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        if not initial_rows:
            return []

        visited_entities = {entity_id}
        queue = [entity_id]
        collected_evidence: Dict[str, sqlite3.Row] = {}

        while queue:
            curr_entity = queue.pop(0)
            try:
                rows = conn.execute(
                    f"""
                    SELECT evidence_id, evidence_type, subject, object
                    FROM {EVIDENCE_SOURCE_TABLE}
                    WHERE subject = ? OR object = ?
                    """,
                    (curr_entity, curr_entity),
                ).fetchall()
            except sqlite3.OperationalError:
                break

            for r in rows:
                ev_id = r["evidence_id"]
                collected_evidence[ev_id] = r
                for ent in (r["subject"], r["object"]):
                    if ent and ent not in visited_entities:
                        visited_entities.add(ent)
                        queue.append(ent)

        if not collected_evidence:
            return []

        ev_types = sorted(
            {
                r["evidence_type"]
                for r in collected_evidence.values()
                if r["evidence_type"]
            }
        )
        ev_ids = sorted(collected_evidence.keys())
        entities_list = sorted(visited_entities)
        cluster_id = generate_pattern_id("cluster", entities_list, ev_ids)

        return [
            {
                "cluster_id": cluster_id,
                "entities": entities_list,
                "evidence_ids": ev_ids,
                "evidence_types": ev_types,
                "size": len(ev_ids),
            }
        ]

    def find_cross_actor_patterns(self) -> List[Pattern]:
        """Query intelligence_hypotheses WHERE hypothesis_type = 'same_actor' AND probability > 0.5.

        For each, gather evidence_ids from supporting_evidence (JSON array).
        Group by shared evidence types. Create Patterns for groups with >= 2 distinct subjects.
        """
        conn = self._connection()
        try:
            hyp_rows = conn.execute(
                f"""
                SELECT hypothesis_id, subject_a, subject_b, probability, confidence, supporting_evidence
                FROM {HYPOTHESIS_SOURCE_TABLE}
                WHERE hypothesis_type = 'same_actor' AND probability > 0.5
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        if not hyp_rows:
            return []

        all_ev_ids: set[str] = set()
        hyp_list: List[tuple[sqlite3.Row, List[str]]] = []
        for row in hyp_rows:
            supp = row["supporting_evidence"]
            if isinstance(supp, str):
                try:
                    e_ids = json.loads(supp)
                except (json.JSONDecodeError, TypeError):
                    e_ids = []
            elif isinstance(supp, list):
                e_ids = supp
            else:
                e_ids = []

            if e_ids:
                all_ev_ids.update(e_ids)
                hyp_list.append((row, e_ids))

        evidence_map: Dict[str, sqlite3.Row] = {}
        if all_ev_ids:
            placeholders = ",".join(["?"] * len(all_ev_ids))
            try:
                ev_rows = conn.execute(
                    f"""
                    SELECT evidence_id, evidence_type, subject, object, score, confidence
                    FROM {EVIDENCE_SOURCE_TABLE}
                    WHERE evidence_id IN ({placeholders})
                    """,
                    list(all_ev_ids),
                ).fetchall()
                for er in ev_rows:
                    evidence_map[er["evidence_id"]] = er
            except sqlite3.OperationalError:
                pass

        # Group by shared evidence types
        type_groups: Dict[str, Dict[str, Any]] = {}
        for hyp_row, e_ids in hyp_list:
            prob = (
                float(hyp_row["probability"])
                if hyp_row["probability"] is not None
                else 0.0
            )
            conf = (
                float(hyp_row["confidence"])
                if hyp_row["confidence"] is not None
                else 0.0
            )
            subj_a = hyp_row["subject_a"]
            subj_b = hyp_row["subject_b"]

            for eid in e_ids:
                ev_info = evidence_map.get(eid)
                if ev_info:
                    etype = ev_info["evidence_type"]
                else:
                    etype = "unknown"

                if etype not in type_groups:
                    type_groups[etype] = {
                        "evidence_type": etype,
                        "entities": set(),
                        "evidence_ids": set(),
                        "probabilities": [],
                        "confidences": [],
                    }

                if subj_a:
                    type_groups[etype]["entities"].add(subj_a)
                if subj_b:
                    type_groups[etype]["entities"].add(subj_b)
                if ev_info:
                    if ev_info["subject"]:
                        type_groups[etype]["entities"].add(ev_info["subject"])
                    if ev_info["object"]:
                        type_groups[etype]["entities"].add(ev_info["object"])

                type_groups[etype]["evidence_ids"].add(eid)
                type_groups[etype]["probabilities"].append(prob)
                type_groups[etype]["confidences"].append(conf)

        patterns: List[Pattern] = []
        for etype, data in type_groups.items():
            entities_list = sorted(data["entities"])
            if len(entities_list) < 2:
                continue

            ev_ids_list = sorted(data["evidence_ids"])
            probs = data["probabilities"]
            confs = data["confidences"]
            avg_conf = sum(confs) / len(confs) if confs else 0.0
            avg_prob = sum(probs) / len(probs) if probs else 0.0

            confidence = (
                min(max(avg_prob * avg_conf, 0.0), 1.0)
                if (probs and confs)
                else avg_conf
            )

            pattern = Pattern(
                pattern_id="",
                pattern_type=f"cross_actor:{etype}",
                description=(
                    f"Shared '{etype}' evidence supporting same-actor hypotheses "
                    f"across {len(entities_list)} distinct actors"
                ),
                entities=entities_list,
                evidence_ids=ev_ids_list,
                frequency=len(ev_ids_list),
                confidence=confidence,
                metadata={
                    "evidence_type": etype,
                    "actor_count": len(entities_list),
                    "evidence_count": len(ev_ids_list),
                    "avg_probability": avg_prob,
                    "avg_confidence": avg_conf,
                },
            )
            patterns.append(pattern)

        return patterns

    def close(self) -> None:
        """Close the SQLite database connection if open."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> PatternMatcher:
        self._connection()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# ─── Exports ────────────────────────────────────────────────────────────────

__all__ = [
    "Pattern",
    "PatternMatcher",
    "generate_pattern_id",
]
