"""
SPECTRA Threat Network Tracker
===============================
Tracks interactions and builds threat actor networks.

Features:
- Interaction tracking (replies, mentions, same channel)
- Network graph construction
- Association scoring (guilt by association)
- Community detection (threat clusters)
- Network metrics (centrality, influence)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Optional: NetworkX for advanced graph analysis
try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False
    logger.warning("networkx not installed. Advanced network analysis unavailable.")


class InteractionType:
    """Types of interactions between actors."""
    DIRECT_REPLY = "direct_reply"
    MENTION = "mention"
    SAME_THREAD = "same_thread"
    SAME_CHANNEL = "same_channel"
    FORWARDED = "forwarded"
    MEDIA_SHARE = "media_share"


# Interaction weights for association scoring
INTERACTION_WEIGHTS = {
    InteractionType.DIRECT_REPLY: 1.0,
    InteractionType.MENTION: 0.8,
    InteractionType.FORWARDED: 0.9,
    InteractionType.MEDIA_SHARE: 0.7,
    InteractionType.SAME_THREAD: 0.6,
    InteractionType.SAME_CHANNEL: 0.3,
}


@dataclass
class Interaction:
    """A single interaction between two actors."""
    source_id: int
    target_id: int
    interaction_type: str
    weight: float
    timestamp: datetime
    message_id: Optional[int] = None
    channel_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.interaction_type,
            "weight": self.weight,
            "timestamp": self.timestamp.isoformat(),
            "message_id": self.message_id,
            "channel_id": self.channel_id,
        }


@dataclass
class ActorRelationship:
    """Aggregated relationship between two actors."""
    source_id: int
    target_id: int
    interaction_count: int = 0
    total_weight: float = 0.0
    interaction_types: Dict[str, int] = field(default_factory=dict)
    first_interaction: Optional[datetime] = None
    last_interaction: Optional[datetime] = None
    channels: Set[int] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "interaction_count": self.interaction_count,
            "total_weight": round(self.total_weight, 2),
            "avg_weight": round(self.total_weight / max(self.interaction_count, 1), 2),
            "interaction_types": self.interaction_types,
            "first_interaction": self.first_interaction.isoformat() if self.first_interaction else None,
            "last_interaction": self.last_interaction.isoformat() if self.last_interaction else None,
            "channel_count": len(self.channels),
        }


class ThreatNetworkTracker:
    """
    Tracks interactions and builds threat actor networks.
    """

    def __init__(self):
        """Initialize network tracker."""
        self.interactions: List[Interaction] = []
        self.relationships: Dict[Tuple[int, int], ActorRelationship] = {}

        # NetworkX graph (if available)
        if HAS_NETWORKX:
            self.graph = nx.DiGraph()
        else:
            self.graph = None

    def add_interaction(
        self,
        source_id: int,
        target_id: int,
        interaction_type: str,
        timestamp: datetime,
        message_id: Optional[int] = None,
        channel_id: Optional[int] = None,
    ) -> None:
        """
        Add an interaction to the network.

        Args:
            source_id: User ID of source actor
            target_id: User ID of target actor
            interaction_type: Type of interaction
            timestamp: When the interaction occurred
            message_id: Optional message ID
            channel_id: Optional channel ID
        """
        if source_id == target_id:
            return  # Ignore self-interactions

        # Create interaction
        weight = INTERACTION_WEIGHTS.get(interaction_type, 0.5)

        interaction = Interaction(
            source_id=source_id,
            target_id=target_id,
            interaction_type=interaction_type,
            weight=weight,
            timestamp=timestamp,
            message_id=message_id,
            channel_id=channel_id,
        )

        self.interactions.append(interaction)

        # Update relationship
        key = (source_id, target_id)
        if key not in self.relationships:
            self.relationships[key] = ActorRelationship(
                source_id=source_id,
                target_id=target_id,
            )

        rel = self.relationships[key]
        rel.interaction_count += 1
        rel.total_weight += weight
        rel.interaction_types[interaction_type] = rel.interaction_types.get(interaction_type, 0) + 1

        if not rel.first_interaction or timestamp < rel.first_interaction:
            rel.first_interaction = timestamp
        if not rel.last_interaction or timestamp > rel.last_interaction:
            rel.last_interaction = timestamp

        if channel_id:
            rel.channels.add(channel_id)

        # Update graph
        if self.graph is not None:
            if not self.graph.has_edge(source_id, target_id):
                self.graph.add_edge(source_id, target_id, weight=weight)
            else:
                # Update edge weight
                current_weight = self.graph[source_id][target_id].get('weight', 0)
                self.graph[source_id][target_id]['weight'] = current_weight + weight

    def get_actor_associates(
        self,
        user_id: int,
        min_interactions: int = 1,
    ) -> List[Tuple[int, ActorRelationship]]:
        """
        Get all associates of an actor.

        Args:
            user_id: User ID
            min_interactions: Minimum interactions required

        Returns:
            List of (associate_id, relationship) tuples
        """
        associates = []

        # Outgoing relationships
        for (source, target), rel in self.relationships.items():
            if source == user_id and rel.interaction_count >= min_interactions:
                associates.append((target, rel))

        # Incoming relationships (bidirectional)
        for (source, target), rel in self.relationships.items():
            if target == user_id and rel.interaction_count >= min_interactions:
                # Create reversed relationship
                rev_rel = ActorRelationship(
                    source_id=target,
                    target_id=source,
                    interaction_count=rel.interaction_count,
                    total_weight=rel.total_weight,
                    interaction_types=rel.interaction_types,
                    first_interaction=rel.first_interaction,
                    last_interaction=rel.last_interaction,
                    channels=rel.channels,
                )
                if (target, source) not in [(a[0], a[1].source_id) for a in associates]:
                    associates.append((source, rev_rel))

        # Sort by total weight (strongest relationships first)
        associates.sort(key=lambda x: x[1].total_weight, reverse=True)

        return associates

    def calculate_network_threat_score(
        self,
        user_id: int,
        actor_threat_scores: Dict[int, float],
        max_depth: int = 2,
    ) -> float:
        """
        Calculate threat score based on network associations.
        "You are who you associate with" principle.

        Args:
            user_id: User ID to calculate score for
            actor_threat_scores: Dict mapping user_id -> threat_score
            max_depth: Maximum network depth to consider

        Returns:
            Network-based threat score (0-5 range)
        """
        if user_id not in actor_threat_scores:
            return 0.0

        associates = self.get_actor_associates(user_id, min_interactions=3)

        if not associates:
            return 0.0

        # Calculate weighted average of associate threat scores
        total_weighted_score = 0.0
        total_weight = 0.0

        for associate_id, relationship in associates:
            if associate_id in actor_threat_scores:
                associate_score = actor_threat_scores[associate_id]
                interaction_weight = relationship.total_weight

                total_weighted_score += associate_score * interaction_weight
                total_weight += interaction_weight

        if total_weight == 0:
            return 0.0

        # Average association score
        avg_score = total_weighted_score / total_weight

        # Boost for high-threat associations
        high_threat_associates = [
            a for a, r in associates
            if a in actor_threat_scores and actor_threat_scores[a] >= 7.0
        ]

        boost = len(high_threat_associates) * 0.5

        return min(5.0, avg_score + boost)

    def detect_communities(self) -> Dict[int, int]:
        """
        Detect communities (clusters) in the threat network.

        Returns:
            Dict mapping user_id -> community_id
        """
        if not HAS_NETWORKX or self.graph is None:
            logger.warning("NetworkX not available. Cannot detect communities.")
            return {}

        if self.graph.number_of_nodes() == 0:
            return {}

        try:
            # Convert to undirected for community detection
            undirected = self.graph.to_undirected()

            # Try Louvain algorithm
            try:
                import community as community_louvain
                communities = community_louvain.best_partition(undirected)
                logger.info(f"Detected {max(communities.values()) + 1} communities using Louvain")
                return communities

            except ImportError:
                # Fallback to label propagation
                from networkx.algorithms import community
                communities_sets = community.label_propagation_communities(undirected)

                communities = {}
                for i, comm_set in enumerate(communities_sets):
                    for node in comm_set:
                        communities[node] = i

                logger.info(f"Detected {len(communities_sets)} communities using label propagation")
                return communities

        except Exception as e:
            logger.error(f"Community detection failed: {e}")
            return {}

    def get_network_metrics(
        self,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        Get network metrics for an actor.

        Args:
            user_id: User ID

        Returns:
            Dict of network metrics
        """
        if not HAS_NETWORKX or self.graph is None:
            logger.warning("NetworkX not available. Limited metrics.")
            associates = self.get_actor_associates(user_id)
            return {
                "degree": len(associates),
                "associate_count": len(associates),
            }

        if user_id not in self.graph:
            return {
                "degree": 0,
                "associate_count": 0,
            }

        metrics = {}

        # Degree centrality
        metrics["degree"] = self.graph.degree(user_id)

        # In-degree and out-degree
        metrics["in_degree"] = self.graph.in_degree(user_id)
        metrics["out_degree"] = self.graph.out_degree(user_id)

        # PageRank (influence)
        try:
            pagerank_scores = nx.pagerank(self.graph)
            metrics["pagerank"] = pagerank_scores.get(user_id, 0.0)
        except Exception as e:
            logger.debug(f"PageRank calculation failed: {e}")
            metrics["pagerank"] = 0.0

        # Betweenness centrality (bridge position)
        try:
            betweenness_scores = nx.betweenness_centrality(self.graph)
            metrics["betweenness"] = betweenness_scores.get(user_id, 0.0)
        except Exception as e:
            logger.debug(f"Betweenness calculation failed: {e}")
            metrics["betweenness"] = 0.0

        return metrics

    def get_stats(self) -> Dict[str, Any]:
        """Get overall network statistics."""
        stats = {
            "total_interactions": len(self.interactions),
            "total_relationships": len(self.relationships),
            "total_actors": len(set(
                [i.source_id for i in self.interactions] +
                [i.target_id for i in self.interactions]
            )),
        }

        if HAS_NETWORKX and self.graph is not None:
            stats["graph_nodes"] = self.graph.number_of_nodes()
            stats["graph_edges"] = self.graph.number_of_edges()

            if stats["graph_nodes"] > 0:
                stats["density"] = nx.density(self.graph)
                stats["is_connected"] = nx.is_weakly_connected(self.graph)

        return stats


__all__ = [
    "InteractionType",
    "Interaction",
    "ActorRelationship",
    "ThreatNetworkTracker",
]
