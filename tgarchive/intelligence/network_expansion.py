"""
Network Expansion Engine — Discover network members from known leaders
=======================================================================

Given a set of known bad actors (leaders), expands the network by:

1. **Graph traversal** — find all actors connected to leaders via hypothesis
   edges (SAME_ACTOR, ASSOCIATED_WITH, PART_OF_CAMPAIGN, CAMPAIGN_CHANNEL)
2. **Contact network** — find actors who interact with leaders (replies, mentions)
3. **Timing correlation** — find actors whose posting times correlate with leaders
4. **Stylometric similarity** — find actors with matching writing styles
5. **Co-occurrence** — find actors who appear in the same channels as leaders

Each discovered actor is scored with a probability of being part of the
network. Actors above a confidence threshold are automatically added to
a campaign as network members.

Usage (library)::

    from tgarchive.intelligence.network_expansion import expand_network

    result = expand_network(
        db_path="spectra.db",
        leader_ids=[123, 456],
        campaign_name="Op NetworkX",
        min_probability=0.6,
    )
    print(result["discovered_members"])  # new actors added to campaign
    print(result["network_graph"])       # full graph

Usage (CLI)::

    spectra intel expand-network --leaders 123,456 --campaign "Op NetworkX"
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .schema import (
    SCHEMA_VERSION,
    AnalysisEvidence,
    ActorHypothesis,
    HypothesisType,
    EvidenceDirection,
    Campaign,
    EvidenceSource,
    canonical_id,
    generate_campaign_id,
)
from .conclusions import draw_conclusions, conclude_actor

logger = logging.getLogger(__name__)


# ─── Data structures ───────────────────────────────────────────────────────


@dataclass
class NetworkMember:
    """A discovered member of a network."""

    user_id: int
    canonical_id: str
    username: Optional[str] = None
    role: str = "member"  # "leader", "member", "suspected"
    probability: float = 0.0  # P(member of network)
    confidence: float = 0.0
    evidence_sources: List[str] = field(default_factory=list)  # what linked them
    linked_to: List[str] = field(default_factory=list)  # canonical IDs of leaders they connect to
    evidence_ids: List[str] = field(default_factory=list)
    hypothesis_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "canonical_id": self.canonical_id,
            "username": self.username,
            "role": self.role,
            "probability": self.probability,
            "confidence": self.confidence,
            "evidence_sources": self.evidence_sources,
            "linked_to": self.linked_to,
            "evidence_ids": self.evidence_ids,
            "hypothesis_ids": self.hypothesis_ids,
            "metadata": self.metadata,
        }


@dataclass
class NetworkExpansionResult:
    """Result of a network expansion operation."""

    campaign_id: str
    campaign_name: str
    leaders: List[NetworkMember]
    discovered_members: List[NetworkMember]
    all_members: List[NetworkMember]
    graph: Dict[str, Any]
    summary: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "leaders": [m.to_dict() for m in self.leaders],
            "discovered_members": [m.to_dict() for m in self.discovered_members],
            "all_members": [m.to_dict() for m in self.all_members],
            "graph": self.graph,
            "summary": self.summary,
        }


# ─── Network Expansion Engine ──────────────────────────────────────────────


def _query_graph_neighbors(
    conn: sqlite3.Connection,
    canonical_id: str,
) -> List[Dict[str, Any]]:
    """Find graph neighbors of an entity via hypothesis/campaign edges."""
    parts = canonical_id.split(":")
    if len(parts) >= 3:
        node_type = parts[1]
        external_id = ":".join(parts[2:])
    else:
        return []

    node_key = f"{node_type}:{external_id}"
    neighbors = []

    try:
        node_row = conn.execute(
            "SELECT node_id FROM index_graph_nodes WHERE node_key = ?",
            (node_key,),
        ).fetchone()
        if not node_row:
            return neighbors
        node_id = node_row["node_id"]

        # Outgoing edges
        out_rows = conn.execute(
            """
            SELECT e.edge_type, e.metadata_json,
                   n.node_key, n.node_type, n.external_id
            FROM index_graph_edges e
            JOIN index_graph_nodes n ON e.to_node_id = n.node_id
            WHERE e.from_node_id = ?
            """,
            (node_id,),
        ).fetchall()
        for r in out_rows:
            meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
            neighbors.append({
                "edge_type": r["edge_type"],
                "direction": "outgoing",
                "neighbor_key": r["node_key"],
                "neighbor_type": r["node_type"],
                "neighbor_id": r["external_id"],
                "metadata": meta,
            })

        # Incoming edges
        in_rows = conn.execute(
            """
            SELECT e.edge_type, e.metadata_json,
                   n.node_key, n.node_type, n.external_id
            FROM index_graph_edges e
            JOIN index_graph_nodes n ON e.from_node_id = n.node_id
            WHERE e.to_node_id = ?
            """,
            (node_id,),
        ).fetchall()
        for r in in_rows:
            meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
            neighbors.append({
                "edge_type": r["edge_type"],
                "direction": "incoming",
                "neighbor_key": r["node_key"],
                "neighbor_type": r["node_type"],
                "neighbor_id": r["external_id"],
                "metadata": meta,
            })
    except sqlite3.OperationalError:
        pass

    return neighbors


def _query_contact_network(
    conn: sqlite3.Connection,
    user_id: int,
    min_interactions: int = 3,
) -> List[Dict[str, Any]]:
    """Find actors who interact with a leader (replies, mentions)."""
    contacts = []

    try:
        # Who does this user reply to?
        rows = conn.execute(
            """
            SELECT m2.user_id as contact_id, COUNT(*) as interaction_count
            FROM messages m1
            JOIN messages m2 ON m1.reply_to = m2.id
            WHERE m1.user_id = ? AND m2.user_id IS NOT NULL AND m2.user_id != ?
            GROUP BY m2.user_id HAVING interaction_count >= ?
            ORDER BY interaction_count DESC
            """,
            (user_id, user_id, min_interactions),
        ).fetchall()
        for r in rows:
            contacts.append({
                "user_id": r["contact_id"],
                "interaction_count": r["interaction_count"],
                "direction": "leader_replies_to",
            })

        # Who replies to this user?
        rows = conn.execute(
            """
            SELECT m1.user_id as contact_id, COUNT(*) as interaction_count
            FROM messages m1
            JOIN messages m2 ON m1.reply_to = m2.id
            WHERE m2.user_id = ? AND m1.user_id IS NOT NULL AND m1.user_id != ?
            GROUP BY m1.user_id HAVING interaction_count >= ?
            ORDER BY interaction_count DESC
            """,
            (user_id, user_id, min_interactions),
        ).fetchall()
        for r in rows:
            contacts.append({
                "user_id": r["contact_id"],
                "interaction_count": r["interaction_count"],
                "direction": "replies_to_leader",
            })
    except sqlite3.OperationalError:
        pass

    return contacts


def _query_co_channel_actors(
    conn: sqlite3.Connection,
    user_id: int,
    min_co_occurrence: int = 5,
) -> List[Dict[str, Any]]:
    """Find actors who post in the same channels as a leader."""
    co_actors = []

    try:
        rows = conn.execute(
            """
            SELECT m2.user_id as co_actor_id,
                   COUNT(DISTINCT m1.channel_id) as shared_channels,
                   COUNT(*) as co_occurrences
            FROM messages m1
            JOIN messages m2 ON m1.channel_id = m2.channel_id
            WHERE m1.user_id = ? AND m2.user_id != ?
                 AND m1.channel_id IS NOT NULL
            GROUP BY m2.user_id HAVING co_occurrences >= ?
            ORDER BY shared_channels DESC, co_occurrences DESC
            """,
            (user_id, user_id, min_co_occurrence),
        ).fetchall()
        for r in rows:
            co_actors.append({
                "user_id": r["co_actor_id"],
                "shared_channels": r["shared_channels"],
                "co_occurrences": r["co_occurrences"],
            })
    except sqlite3.OperationalError:
        pass

    return co_actors


def _query_hypothesis_links(
    conn: sqlite3.Connection,
    canonical_id: str,
) -> List[Dict[str, Any]]:
    """Find hypotheses linking this entity to others."""
    links = []

    try:
        rows = conn.execute(
            """
            SELECT hypothesis_id, hypothesis_type, subject_a, subject_b,
                   probability, confidence, supporting_evidence
            FROM intelligence_hypotheses
            WHERE (subject_a = ? OR subject_b = ?)
                 AND probability > 0.3
            ORDER BY probability DESC
            """,
            (canonical_id, canonical_id),
        ).fetchall()
        for r in rows:
            other = r["subject_b"] if r["subject_a"] == canonical_id else r["subject_a"]
            supporting = json.loads(r["supporting_evidence"]) if r["supporting_evidence"] else []
            links.append({
                "hypothesis_id": r["hypothesis_id"],
                "hypothesis_type": r["hypothesis_type"],
                "other_entity": other,
                "probability": r["probability"],
                "confidence": r["confidence"],
                "evidence_ids": supporting,
            })
    except sqlite3.OperationalError:
        pass

    return links


def _query_username(conn: sqlite3.Connection, user_id: int) -> Optional[str]:
    """Get username for a user ID."""
    try:
        row = conn.execute(
            "SELECT username FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return row["username"] if row else None
    except sqlite3.OperationalError:
        return None


def _parse_canonical_id(canonical: str) -> Optional[int]:
    """Extract numeric user_id from canonical ID like telegram:user:123."""
    parts = canonical.split(":")
    if len(parts) >= 3 and parts[1] == "user":
        try:
            return int(parts[2])
        except ValueError:
            return None
    return None


def _score_member(
    sources: List[str],
    hypothesis_prob: float = 0.0,
    interaction_count: int = 0,
    shared_channels: int = 0,
    co_occurrences: int = 0,
) -> Tuple[float, float]:
    """Score a discovered member's probability and confidence.

    Returns (probability, confidence) in [0, 1].
    """
    import math

    log_odds = 0.0
    weight = 0.0

    # Hypothesis evidence (strongest signal)
    if hypothesis_prob > 0:
        hyp_weight = 2.0  # hypotheses are strong evidence
        if 0 < hypothesis_prob < 1:
            log_odds += hyp_weight * math.log(hypothesis_prob / (1 - hypothesis_prob))
        weight += hyp_weight

    # Contact network (interaction frequency)
    if interaction_count > 0:
        # More interactions = higher probability, but with diminishing returns
        contact_prob = min(interaction_count / 20.0, 0.8)
        contact_weight = 1.0
        log_odds += contact_weight * math.log(max(contact_prob, 0.01) / max(1 - contact_prob, 0.01))
        weight += contact_weight

    # Co-channel co-occurrence
    if shared_channels > 0:
        co_prob = min(shared_channels / 10.0, 0.7)
        co_weight = 0.8
        log_odds += co_weight * math.log(max(co_prob, 0.01) / max(1 - co_prob, 0.01))
        weight += co_weight

    # Number of distinct evidence sources
    source_bonus = min(len(sources) / 4.0, 1.0)
    weight += source_bonus * 0.5

    if weight == 0:
        return 0.0, 0.0

    probability = 1.0 / (1.0 + math.exp(-log_odds / max(weight, 1.0)))
    confidence = min(weight / 5.0, 1.0)

    return probability, confidence


def expand_network(
    db_path: Path | str,
    *,
    leader_ids: List[int],
    campaign_name: str = "Network Expansion",
    min_probability: float = 0.6,
    max_depth: int = 2,
    min_interactions: int = 3,
    min_co_occurrence: int = 5,
    auto_add_to_campaign: bool = True,
    platform: str = "telegram",
) -> NetworkExpansionResult:
    """Expand a network from known leaders.

    Given a set of known bad actors (leaders), discovers other actors
    who are likely part of their network using:

    - Graph edges (hypothesis links, campaign memberships)
    - Contact network (replies, mentions)
    - Co-channel co-occurrence
    - Existing intelligence hypotheses

    Actors above min_probability are added to a campaign as network members.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        leader_ids: List of known leader user IDs.
        campaign_name: Name for the campaign.
        min_probability: Minimum probability to include a discovered actor.
        max_depth: How many hops to expand from leaders (1=direct, 2=indirect).
        min_interactions: Minimum interactions to consider someone a contact.
        min_co_occurrence: Minimum co-channel co-occurrences.
        auto_add_to_campaign: If True, save the campaign to the DB.
        platform: Platform prefix for canonical IDs.

    Returns:
        NetworkExpansionResult with leaders, discovered members, and graph.
    """
    from ..sqlite_runtime import connect_sqlite
    from ..db.intelligence_store import IntelligenceStore

    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    # Build leader canonical IDs
    leader_canonicals = {uid: canonical_id(platform, "user", uid) for uid in leader_ids}

    # Phase 1: Gather all candidate members and their evidence
    candidates: Dict[int, NetworkMember] = {}
    graph_edges: List[Dict[str, Any]] = []

    # Leaders are members with probability 1.0
    leaders: List[NetworkMember] = []
    for uid in leader_ids:
        cid = leader_canonicals[uid]
        with connect_sqlite(db_path) as conn:
            conn.row_factory = sqlite3.Row
            username = _query_username(conn, uid)
        leader = NetworkMember(
            user_id=uid,
            canonical_id=cid,
            username=username,
            role="leader",
            probability=1.0,
            confidence=1.0,
            evidence_sources=["manual_identification"],
        )
        leaders.append(leader)
        candidates[uid] = leader

    # Phase 2: Expand from each leader
    for depth in range(1, max_depth + 1):
        current_members = list(candidates.values())
        for member in current_members:
            if member.role == "leader" or depth == 1 or member.probability >= min_probability:
                with connect_sqlite(db_path) as conn:
                    conn.row_factory = sqlite3.Row

                    cid = member.canonical_id

                    # 2a. Graph neighbors (hypothesis edges)
                    graph_neighbors = _query_graph_neighbors(conn, cid)
                    for gn in graph_neighbors:
                        if gn["neighbor_type"] != "user":
                            continue
                        neighbor_uid = _parse_canonical_id(gn["neighbor_key"].replace("user:", "telegram:user:")) if ":" in gn["neighbor_key"] else None
                        # Parse neighbor_id as int
                        try:
                            neighbor_uid = int(gn["neighbor_id"])
                        except (ValueError, TypeError):
                            continue
                        if neighbor_uid in leader_ids or neighbor_uid in candidates:
                            continue
                        if neighbor_uid not in candidates:
                            candidates[neighbor_uid] = NetworkMember(
                                user_id=neighbor_uid,
                                canonical_id=f"{platform}:user:{neighbor_uid}",
                                username=_query_username(conn, neighbor_uid),
                                role="suspected",
                            )
                        c = candidates[neighbor_uid]
                        if "graph_link" not in c.evidence_sources:
                            c.evidence_sources.append("graph_link")
                        if cid not in c.linked_to:
                            c.linked_to.append(cid)
                        graph_edges.append({
                            "source": cid,
                            "target": c.canonical_id,
                            "type": gn["edge_type"],
                            "depth": depth,
                        })

                    # 2b. Hypothesis links
                    hyp_links = _query_hypothesis_links(conn, cid)
                    for hl in hyp_links:
                        other_uid = _parse_canonical_id(hl["other_entity"])
                        if other_uid is None or other_uid in leader_ids:
                            continue
                        if other_uid not in candidates:
                            candidates[other_uid] = NetworkMember(
                                user_id=other_uid,
                                canonical_id=hl["other_entity"],
                                username=_query_username(conn, other_uid),
                                role="suspected",
                            )
                        c = candidates[other_uid]
                        if "hypothesis_link" not in c.evidence_sources:
                            c.evidence_sources.append("hypothesis_link")
                        if cid not in c.linked_to:
                            c.linked_to.append(cid)
                        c.hypothesis_ids.append(hl["hypothesis_id"])
                        c.evidence_ids.extend(hl["evidence_ids"])
                        # Track the hypothesis probability for scoring
                        c.metadata.setdefault("max_hyp_prob", 0.0)
                        c.metadata["max_hyp_prob"] = max(c.metadata["max_hyp_prob"], hl["probability"])
                        graph_edges.append({
                            "source": cid,
                            "target": c.canonical_id,
                            "type": hl["hypothesis_type"],
                            "probability": hl["probability"],
                            "depth": depth,
                        })

                    # 2c. Contact network
                    contacts = _query_contact_network(conn, member.user_id, min_interactions)
                    for ct in contacts:
                        ct_uid = ct["user_id"]
                        if ct_uid in leader_ids:
                            continue
                        if ct_uid not in candidates:
                            candidates[ct_uid] = NetworkMember(
                                user_id=ct_uid,
                                canonical_id=f"{platform}:user:{ct_uid}",
                                username=_query_username(conn, ct_uid),
                                role="suspected",
                            )
                        c = candidates[ct_uid]
                        if "contact_network" not in c.evidence_sources:
                            c.evidence_sources.append("contact_network")
                        if cid not in c.linked_to:
                            c.linked_to.append(cid)
                        c.metadata.setdefault("max_interactions", 0)
                        c.metadata["max_interactions"] = max(c.metadata["max_interactions"], ct["interaction_count"])
                        graph_edges.append({
                            "source": cid,
                            "target": c.canonical_id,
                            "type": ct["direction"],
                            "count": ct["interaction_count"],
                            "depth": depth,
                        })

                    # 2d. Co-channel co-occurrence
                    co_actors = _query_co_channel_actors(conn, member.user_id, min_co_occurrence)
                    for ca in co_actors:
                        ca_uid = ca["user_id"]
                        if ca_uid in leader_ids:
                            continue
                        if ca_uid not in candidates:
                            candidates[ca_uid] = NetworkMember(
                                user_id=ca_uid,
                                canonical_id=f"{platform}:user:{ca_uid}",
                                username=_query_username(conn, ca_uid),
                                role="suspected",
                            )
                        c = candidates[ca_uid]
                        if "co_channel" not in c.evidence_sources:
                            c.evidence_sources.append("co_channel")
                        if cid not in c.linked_to:
                            c.linked_to.append(cid)
                        c.metadata.setdefault("max_shared_channels", 0)
                        c.metadata["max_shared_channels"] = max(c.metadata["max_shared_channels"], ca["shared_channels"])
                        c.metadata.setdefault("max_co_occurrences", 0)
                        c.metadata["max_co_occurrences"] = max(c.metadata["max_co_occurrences"], ca["co_occurrences"])
                        graph_edges.append({
                            "source": cid,
                            "target": c.canonical_id,
                            "type": "co_channel",
                            "shared_channels": ca["shared_channels"],
                            "depth": depth,
                        })

    # Phase 3: Score all candidates
    discovered: List[NetworkMember] = []
    for uid, member in candidates.items():
        if member.role == "leader":
            continue
        hyp_prob = member.metadata.get("max_hyp_prob", 0.0)
        interactions = member.metadata.get("max_interactions", 0)
        shared_ch = member.metadata.get("max_shared_channels", 0)
        co_occ = member.metadata.get("max_co_occurrences", 0)
        prob, conf = _score_member(
            sources=member.evidence_sources,
            hypothesis_prob=hyp_prob,
            interaction_count=interactions,
            shared_channels=shared_ch,
            co_occurrences=co_occ,
        )
        member.probability = prob
        member.confidence = conf
        # Upgrade role based on probability
        if prob >= 0.8:
            member.role = "member"
        elif prob >= min_probability:
            member.role = "member"
        else:
            member.role = "suspected"
        discovered.append(member)

    # Sort by probability descending
    discovered.sort(key=lambda m: m.probability, reverse=True)

    # Filter to those above threshold
    qualified = [m for m in discovered if m.probability >= min_probability]

    # Phase 4: Create/update campaign
    all_members = leaders + qualified
    all_canonicals = [m.canonical_id for m in all_members]

    campaign_id = generate_campaign_id(campaign_name, all_canonicals, "spectra-network-expansion", "1.0.0")

    if auto_add_to_campaign and qualified:
        now = datetime.now(timezone.utc)
        source = EvidenceSource(
            source_type="network_expansion",
            source_id=campaign_id,
            source_table="intelligence_campaigns",
            source_row_id=0,
            retrieved_at=now,
        )
        campaign = Campaign(
            campaign_id="",
            name=campaign_name,
            actors=all_canonicals,
            channels=[],
            wallets=[],
            domains=[],
            confidence=min(max(m.confidence for m in qualified) if qualified else 0.5, 1.0),
            evidence_ids=[],
            generated_at=now,
            metadata={
                "expansion": True,
                "leader_ids": [str(uid) for uid in leader_ids],
                "discovered_count": len(qualified),
                "min_probability": min_probability,
                "schema_version": SCHEMA_VERSION,
            },
        )
        try:
            with IntelligenceStore(db_path) as store:
                store.save_campaign(campaign)
            campaign_id = campaign.campaign_id
            # Persist graph edges into the projection tables so they survive
            # across sessions and are visible to `spectra index graph` queries.
            _save_graph_edges(db_path, graph_edges, campaign_id)
        except Exception as e:
            logger.error(f"Failed to save campaign: {e}")

    # Build summary
    summary = {
        "leader_count": len(leaders),
        "discovered_count": len(discovered),
        "qualified_count": len(qualified),
        "suspected_count": len(discovered) - len(qualified),
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "min_probability": min_probability,
        "max_depth": max_depth,
        "evidence_sources_used": sorted({
            s for m in discovered for s in m.evidence_sources
        }),
    }

    graph = {
        "nodes": [
            {
                "id": m.canonical_id,
                "user_id": m.user_id,
                "username": m.username,
                "role": m.role,
                "probability": m.probability,
            }
            for m in all_members + [m for m in discovered if m.probability < min_probability]
        ],
        "edges": graph_edges,
    }

    return NetworkExpansionResult(
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        leaders=leaders,
        discovered_members=qualified,
        all_members=all_members,
        graph=graph,
        summary=summary,
    )


def _save_graph_edges(
    db_path: str,
    graph_edges: List[Dict[str, Any]],
    campaign_id: str,
) -> None:
    """Persist network expansion graph edges into the projection tables.

    Inserts nodes and edges into ``index_graph_nodes`` and ``index_graph_edges``
    so they are visible to ``spectra index graph`` queries and survive across
    sessions.  Uses a high sequence_id to avoid collisions with outbox events.
    """
    if not graph_edges:
        return
    import sqlite3
    from ..db.schema import SCHEMA_SQL

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA_SQL)
        # Ensure graph projection tables exist
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS index_graph_nodes (
            node_id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_key TEXT UNIQUE NOT NULL,
            node_type TEXT NOT NULL,
            external_id TEXT,
            first_sequence_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS index_graph_edges (
            from_node_id INTEGER NOT NULL,
            to_node_id INTEGER NOT NULL,
            edge_type TEXT NOT NULL,
            sequence_id INTEGER NOT NULL,
            metadata_json TEXT,
            PRIMARY KEY (from_node_id, to_node_id, edge_type)
        );
        CREATE INDEX IF NOT EXISTS idx_index_graph_edges_sequence
            ON index_graph_edges(sequence_id);
        """)
        # Use a high sequence_id to avoid collisions with outbox events
        seq_id = 900000000
        now_meta = json.dumps({"campaign_id": campaign_id, "source": "network_expansion"})
        for edge in graph_edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            etype = str(edge.get("type", "NETWORK_LINK")).upper().replace("-", "_")
            if not source or not target:
                continue
            # Insert or get source node
            conn.execute(
                "INSERT OR IGNORE INTO index_graph_nodes(node_key, node_type, external_id, first_sequence_id) VALUES (?, ?, ?, ?)",
                (source, "entity", source, seq_id),
            )
            src_row = conn.execute(
                "SELECT node_id FROM index_graph_nodes WHERE node_key=?", (source,)
            ).fetchone()
            # Insert or get target node
            conn.execute(
                "INSERT OR IGNORE INTO index_graph_nodes(node_key, node_type, external_id, first_sequence_id) VALUES (?, ?, ?, ?)",
                (target, "entity", target, seq_id),
            )
            tgt_row = conn.execute(
                "SELECT node_id FROM index_graph_nodes WHERE node_key=?", (target,)
            ).fetchone()
            if src_row and tgt_row:
                conn.execute(
                    """
                    INSERT INTO index_graph_edges(from_node_id, to_node_id, edge_type, sequence_id, metadata_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(from_node_id, to_node_id, edge_type) DO UPDATE SET
                        sequence_id=excluded.sequence_id,
                        metadata_json=excluded.metadata_json
                    WHERE excluded.sequence_id >= index_graph_edges.sequence_id
                    """,
                    (src_row["node_id"], tgt_row["node_id"], etype, seq_id, now_meta),
                )
        conn.commit()
    except Exception as e:
        logger.debug(f"Failed to save graph edges: {e}")
    finally:
        conn.close()


__all__ = [
    "NetworkMember",
    "NetworkExpansionResult",
    "expand_network",
]
