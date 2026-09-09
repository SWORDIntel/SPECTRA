"""
Conclusion Engine — Fuse all intelligence about an entity into conclusions
=========================================================================

Given a canonical entity ID (e.g. ``telegram:user:123``), gathers all evidence,
hypotheses, campaigns, and graph context, then produces a fused conclusion
with probability, confidence, and full provenance.

Usage (library)::

    from tgarchive.intelligence.conclusions import draw_conclusions

    conclusion = draw_conclusions("spectra.db", entity_id=123, entity_type="user")
    print(conclusion.probability)
    print(conclusion.supporting_evidence)

Usage (CLI)::

    spectra intel conclude 123 --type user
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import (
    SCHEMA_VERSION,
    AnalysisEvidence,
    ActorHypothesis,
    EvidenceDirection,
    HypothesisType,
    canonical_id,
)

logger = logging.getLogger(__name__)


# ─── Conclusion dataclass ──────────────────────────────────────────────────


@dataclass
class Conclusion:
    """A fused conclusion about an entity, with full provenance."""

    conclusion_id: str
    subject: str                    # canonical entity ID
    conclusion_type: str            # "actor_identity", "threat_assessment", "campaign_membership", "relationship"
    probability: float              # 0-1 posterior probability
    confidence: float               # 0-1 confidence in the probability estimate
    supporting_evidence: List[str] = field(default_factory=list)   # evidence_ids
    contradicting_evidence: List[str] = field(default_factory=list)
    related_hypotheses: List[str] = field(default_factory=list)    # hypothesis_ids
    related_campaigns: List[str] = field(default_factory=list)     # campaign_ids
    graph_neighbors: List[str] = field(default_factory=list)
    evidence_breakdown: Dict[str, int] = field(default_factory=dict)  # evidence_type → count
    metadata: Dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not self.conclusion_id:
            self.conclusion_id = generate_conclusion_id(
                self.subject,
                self.conclusion_type,
                self.supporting_evidence,
                self.contradicting_evidence,
            )
        if not (0.0 <= self.probability <= 1.0):
            raise ValueError(f"probability must be in [0.0, 1.0], got {self.probability}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conclusion_id": self.conclusion_id,
            "subject": self.subject,
            "conclusion_type": self.conclusion_type,
            "probability": self.probability,
            "confidence": self.confidence,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "related_hypotheses": self.related_hypotheses,
            "related_campaigns": self.related_campaigns,
            "graph_neighbors": self.graph_neighbors,
            "evidence_breakdown": self.evidence_breakdown,
            "metadata": self.metadata,
            "generated_at": self.generated_at.isoformat(),
        }


def generate_conclusion_id(
    subject: str,
    conclusion_type: str,
    supporting: List[str],
    contradicting: List[str],
) -> str:
    """Deterministic 16-hex-char conclusion ID."""
    source = "\0".join([
        subject,
        conclusion_type,
        ",".join(sorted(supporting)),
        ",".join(sorted(contradicting)),
    ])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


# ─── Conclusion Engine ─────────────────────────────────────────────────────


def _run_entity_resolver_v2(
    db_path: Path | str,
    *,
    entity_id: int,
    entity_type: str,
    platform: str,
    canonical: str,
    evidence_ids: List[str],
    conclusion: "Conclusion",
) -> List[Dict[str, Any]]:
    """Run EntityResolverV2 for an entity and persist results.

    Creates a ``Mention`` from the entity, resolves it against any existing
    clusters in the database, persists the resulting cluster via
    ``IntelligenceStore``, and records provenance via ``ProvenanceGraph``
    (using the spectra.db connection, not a sidecar).

    Returns a list of cluster-info dicts suitable for inclusion in conclusion
    metadata.  Returns an empty list if the resolver is unavailable or no
    clusters are produced.
    """
    try:
        from .entity_resolver_v2 import (
            EntityResolverV2,
            IdentityCluster,
            Mention,
            MODEL_VERSION as V2_MODEL_VERSION,
        )
    except Exception as exc:
        logger.debug("EntityResolverV2 unavailable, skipping: %s", exc)
        return []

    try:
        from ..db.intelligence_store import IntelligenceStore
        from .provenance_graph import ProvenanceGraph, SCHEMA_VERSION as PROV_VERSION
    except Exception as exc:
        logger.debug("IntelligenceStore/ProvenanceGraph unavailable: %s", exc)
        return []

    try:
        resolver = EntityResolverV2()
        mention = Mention(
            raw_text=str(entity_id),
            mention_type="user_id",
            source_id=canonical,
            metadata={"user_id": entity_id},
        )

        # Query existing clusters from the DB for this entity.
        store = IntelligenceStore(db_path)
        existing_cluster_dicts = store.query_identity_clusters(str(entity_id))

        # Reconstruct lightweight IdentityCluster objects for the resolver.
        existing_clusters: List[IdentityCluster] = []
        from .entity_resolver_v2 import EntityCandidate
        for cd in existing_cluster_dicts:
            candidates: List[EntityCandidate] = []
            for m in cd.get("members", []):
                cand = EntityCandidate(
                    candidate_id=m.get("candidate_id", ""),
                    username=m.get("candidate_value") if m.get("candidate_type") == "username" else None,
                    user_id=int(m["candidate_value"]) if m.get("candidate_type") == "user_id" and m.get("candidate_value", "").isdigit() else None,
                    source_id=m.get("candidate_value") if m.get("candidate_type") == "source_id" else None,
                )
                candidates.append(cand)
            cluster = IdentityCluster(
                cluster_id=cd["cluster_id"],
                candidates=candidates,
                confidence=cd.get("confidence", 0.0),
                model_version=cd.get("model_version", V2_MODEL_VERSION),
                created_at=cd.get("created_at", ""),
                updated_at=cd.get("updated_at", ""),
            )
            existing_clusters.append(cluster)

        # Resolve the mention against existing clusters.
        result = resolver.resolve(mention, existing_clusters)

        # Persist the resulting cluster.
        cluster = result.cluster
        store.save_identity_cluster(cluster)

        # Record provenance for the conclusion via ProvenanceGraph (spectra.db).
        conn = store._connection()
        prov_graph = ProvenanceGraph.from_connection(conn)
        prov_graph.record_derivation(
            output_id=conclusion.conclusion_id or canonical,
            input_ids=evidence_ids,
            algorithm="entity_resolver_v2",
            version=V2_MODEL_VERSION,
            parameters={
                "entity_id": entity_id,
                "entity_type": entity_type,
                "platform": platform,
                "action": result.action,
                "probability": result.probability,
            },
            confidence=conclusion.confidence,
            node_type="conclusion",
        )

        # Also persist the provenance node through the store for outbox flow.
        from .provenance_graph import ProvenanceNode
        prov_nodes = prov_graph.get_nodes_for_output(
            conclusion.conclusion_id or canonical
        )
        for pn in prov_nodes:
            store.save_provenance_node(pn)

        store.close()

        cluster_info: List[Dict[str, Any]] = []
        # Include the newly resolved cluster.
        cluster_info.append({
            "cluster_id": cluster.cluster_id,
            "confidence": cluster.confidence,
            "action": result.action,
            "probability": result.probability,
            "candidate_count": len(cluster.candidates),
            "model_version": cluster.model_version,
        })
        # Include any pre-existing clusters that matched.
        for cd in existing_cluster_dicts:
            cluster_info.append({
                "cluster_id": cd["cluster_id"],
                "confidence": cd.get("confidence", 0.0),
                "action": "existing",
                "candidate_count": len(cd.get("members", [])),
                "model_version": cd.get("model_version", ""),
            })
        return cluster_info
    except Exception as exc:
        logger.debug("EntityResolverV2 integration failed: %s", exc)
        return []


def _compute_fused_probability(
    evidence: List[Dict[str, Any]],
    hypotheses: List[Dict[str, Any]],
) -> tuple[float, float]:
    """Compute a fused probability and confidence from evidence + hypotheses.

    Uses a simple Bayesian-inspired fusion:
    - Each supporting evidence contributes log-odds proportional to its confidence
    - Each contradicting evidence subtracts log-odds
    - Existing hypotheses' probabilities are averaged in as priors
    """
    import math

    log_odds = 0.0
    total_weight = 0.0

    for ev in evidence:
        confidence = float(ev.get("confidence", 0.5))
        score = float(ev.get("score", 0.5))
        direction = ev.get("direction", "supports")
        # Normalize score to 0-1 if it appears to be on a 0-10 scale
        if score > 1.0:
            score = min(score / 10.0, 1.0)
        # Weight by confidence
        weight = confidence
        if direction == "supports":
            log_odds += weight * math.log(max(score, 0.01) / max(1.0 - score, 0.01))
        elif direction == "contradicts":
            log_odds -= weight * math.log(max(score, 0.01) / max(1.0 - score, 0.01))
        total_weight += weight

    # Incorporate existing hypotheses as priors
    for hyp in hypotheses:
        prob = float(hyp.get("probability", 0.5))
        conf = float(hyp.get("confidence", 0.5))
        if prob > 0 and prob < 1:
            log_odds += conf * math.log(prob / (1.0 - prob))
            total_weight += conf

    if total_weight == 0:
        return 0.5, 0.0

    # Convert log-odds back to probability
    probability = 1.0 / (1.0 + math.exp(-log_odds / max(total_weight, 1.0)))

    # Confidence is based on total evidence weight (capped at 1.0)
    confidence = min(total_weight / 10.0, 1.0)

    return probability, confidence


def _classify_conclusion(
    evidence: List[Dict[str, Any]],
    hypotheses: List[Dict[str, Any]],
) -> str:
    """Determine the conclusion type from the evidence and hypotheses."""
    hyp_types = {h.get("hypothesis_type", "") for h in hypotheses}
    ev_types = {e.get("evidence_type", "") for e in evidence}

    if "same_actor" in hyp_types or "different_actor" in hyp_types:
        return "actor_identity"
    if any("threat" in t for t in ev_types):
        return "threat_assessment"
    if any("classification" in t or "caas" in t for t in ev_types):
        return "actor_classification"
    if any("wallet" in t or "domain" in t for t in ev_types):
        return "infrastructure_link"
    if any("temporal" in t for t in ev_types):
        return "temporal_pattern"
    if hyp_types:
        return "relationship"
    return "general"


def draw_conclusions(
    db_path: Path | str,
    *,
    entity_id: int,
    entity_type: str = "user",
    platform: str = "telegram",
) -> List[Conclusion]:
    """Draw conclusions about an entity from all available intelligence.

    Gathers all evidence, hypotheses, campaigns, and graph context for the
    entity, then produces one or more fused conclusions.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        entity_id: The entity's numeric ID.
        entity_type: "user", "channel", "message", or "media".
        platform: Platform prefix (default "telegram").

    Returns:
        List of Conclusion objects, one per conclusion type detected.
    """
    from ..services.cross_index import cross_index_intelligence

    intel = cross_index_intelligence(
        db_path,
        entity_id=entity_id,
        entity_type=entity_type,
        platform=platform,
    )

    evidence = intel.get("evidence", [])
    hypotheses = intel.get("hypotheses", [])
    campaigns = intel.get("campaigns", [])
    graph = intel.get("graph", {})
    canonical = intel["canonical_id"]

    if not evidence and not hypotheses:
        return []

    # Group evidence by conclusion type
    conclusion_type = _classify_conclusion(evidence, hypotheses)

    # Split evidence into supporting and contradicting
    supporting = [
        e["evidence_id"] for e in evidence
        if e.get("direction", "supports") == "supports"
    ]
    contradicting = [
        e["evidence_id"] for e in evidence
        if e.get("direction", "supports") == "contradicts"
    ]

    # Compute fused probability
    probability, confidence = _compute_fused_probability(evidence, hypotheses)

    # Evidence breakdown by type
    evidence_breakdown: Dict[str, int] = {}
    for e in evidence:
        etype = e.get("evidence_type", "unknown")
        evidence_breakdown[etype] = evidence_breakdown.get(etype, 0) + 1

    # Gather related IDs
    hypothesis_ids = [h["hypothesis_id"] for h in hypotheses]
    campaign_ids = [c["campaign_id"] for c in campaigns]
    graph_neighbors = graph.get("neighbors", [])

    conclusion = Conclusion(
        conclusion_id="",
        subject=canonical,
        conclusion_type=conclusion_type,
        probability=probability,
        confidence=confidence,
        supporting_evidence=supporting,
        contradicting_evidence=contradicting,
        related_hypotheses=hypothesis_ids,
        related_campaigns=campaign_ids,
        graph_neighbors=graph_neighbors,
        evidence_breakdown=evidence_breakdown,
        metadata={
            "evidence_count": len(evidence),
            "hypothesis_count": len(hypotheses),
            "campaign_count": len(campaigns),
            "schema_version": SCHEMA_VERSION,
        },
    )

    # ── Entity Resolver v2 integration ────────────────────────────────────
    # Run the probabilistic entity resolver to find/create identity clusters
    # for this entity, persist them, and record provenance.
    cluster_info = _run_entity_resolver_v2(
        db_path,
        entity_id=entity_id,
        entity_type=entity_type,
        platform=platform,
        canonical=canonical,
        evidence_ids=supporting + contradicting,
        conclusion=conclusion,
    )
    if cluster_info:
        conclusion.metadata["identity_clusters"] = cluster_info

    # If there are multiple distinct hypothesis types, produce additional
    # conclusions for each
    conclusions = [conclusion]
    hyp_type_groups: Dict[str, List[Dict[str, Any]]] = {}
    for h in hypotheses:
        htype = h.get("hypothesis_type", "unknown")
        hyp_type_groups.setdefault(htype, []).append(h)

    if len(hyp_type_groups) > 1:
        for htype, group_hyps in hyp_type_groups.items():
            # Filter evidence to only that referenced by this hypothesis group
            group_ev_ids = set()
            for h in group_hyps:
                group_ev_ids.update(h.get("supporting_evidence", []))
                group_ev_ids.update(h.get("contradicting_evidence", []))
            group_evidence = [e for e in evidence if e["evidence_id"] in group_ev_ids]
            if not group_evidence and not group_hyps:
                continue
            group_supporting = [e["evidence_id"] for e in group_evidence if e.get("direction") == "supports"]
            group_contradicting = [e["evidence_id"] for e in group_evidence if e.get("direction") == "contradicts"]
            group_prob, group_conf = _compute_fused_probability(group_evidence, group_hyps)
            sub_conclusion = Conclusion(
                conclusion_id="",
                subject=canonical,
                conclusion_type=f"{conclusion_type}:{htype}",
                probability=group_prob,
                confidence=group_conf,
                supporting_evidence=group_supporting,
                contradicting_evidence=group_contradicting,
                related_hypotheses=[h["hypothesis_id"] for h in group_hyps],
                related_campaigns=campaign_ids,
                graph_neighbors=graph_neighbors,
                evidence_breakdown={
                    etype: sum(1 for e in group_evidence if e.get("evidence_type") == etype)
                    for etype in {e.get("evidence_type", "") for e in group_evidence}
                },
                metadata={
                    "hypothesis_type": htype,
                    "evidence_count": len(group_evidence),
                    "schema_version": SCHEMA_VERSION,
                },
            )
            conclusions.append(sub_conclusion)

    return conclusions


def conclude_actor(
    db_path: Path | str,
    user_id: int,
    *,
    platform: str = "telegram",
) -> Dict[str, Any]:
    """Draw conclusions about an actor — specialized for user entities.

    Returns a dict with:
    - actor_conclusions: list of Conclusion dicts
    - same_actor_hypotheses: hypotheses about this user being the same as another
    - threat_indicators: evidence types indicating threat level
    - campaign_memberships: campaigns this actor is part of
    - network_position: graph neighbors and edge types
    """
    conclusions = draw_conclusions(
        db_path,
        entity_id=user_id,
        entity_type="user",
        platform=platform,
    )

    from ..services.cross_index import cross_index_intelligence
    intel = cross_index_intelligence(
        db_path,
        entity_id=user_id,
        entity_type="user",
        platform=platform,
    )

    hypotheses = intel.get("hypotheses", [])
    same_actor_hyps = [h for h in hypotheses if h.get("hypothesis_type") == "same_actor"]
    evidence = intel.get("evidence", [])
    threat_ev = [e for e in evidence if "threat" in e.get("evidence_type", "").lower()
                 or "indicator" in e.get("evidence_type", "").lower()]
    campaigns = intel.get("campaigns", [])
    graph = intel.get("graph", {})

    # Summarize network position
    edge_types: Dict[str, int] = {}
    for edge in graph.get("edges", []):
        etype = edge.get("edge_type", "unknown")
        edge_types[etype] = edge_types.get(etype, 0) + 1

    return {
        "user_id": user_id,
        "canonical_id": intel["canonical_id"],
        "conclusions": [c.to_dict() for c in conclusions],
        "same_actor_hypotheses": same_actor_hyps,
        "threat_indicators": threat_ev,
        "campaign_memberships": campaigns,
        "network_position": {
            "neighbors": graph.get("neighbors", []),
            "edge_types": edge_types,
            "total_edges": len(graph.get("edges", [])),
        },
        "summary": intel["summary"],
    }


__all__ = [
    "Conclusion",
    "generate_conclusion_id",
    "draw_conclusions",
    "conclude_actor",
]
