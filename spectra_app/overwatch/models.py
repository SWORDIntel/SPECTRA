from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime

# ==========================================
# KEYSTONE Models: High-Velocity Relational Graphs
# ==========================================

@dataclass
class IntelligenceNode:
    """Represents a node in the GNN predictive engine (e.g., Target, Wallet, Infrastructure)."""
    node_id: str
    node_type: str # 'actor', 'wallet', 'infrastructure', 'channel'
    metadata: Dict = field(default_factory=dict)
    first_seen: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)
    confidence_score: float = 0.0

@dataclass
class RelationalEdge:
    """Represents an interaction or shared infrastructure link between nodes."""
    source_id: str
    target_id: str
    relation_type: str # 'transacts_with', 'shares_infrastructure', 'forwards_from'
    weight: float = 1.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    evidence_references: List[str] = field(default_factory=list)

@dataclass
class GNNPredictionEvent:
    """Represents a mathematically deduced unobserved link."""
    prediction_id: str
    probability: float
    model_version: str
    predicted_edge: RelationalEdge
    generated_at: datetime = field(default_factory=datetime.utcnow)


# ==========================================
# MEMSHADOW Models: Federated Context
# ==========================================

@dataclass
class FederatedState:
    """Represents the shared operational memory across isolated SPECTRA deployments."""
    state_id: str
    origin_node_id: str
    relational_graph_hash: str
    snapshot_timestamp: datetime = field(default_factory=datetime.utcnow)
    known_nodes: List[str] = field(default_factory=list)
    quarantined_data: bool = False

    def serialize(self) -> dict:
        return {
            "state_id": self.state_id,
            "origin_node_id": self.origin_node_id,
            "snapshot_timestamp": self.snapshot_timestamp.isoformat(),
            "relational_graph_hash": self.relational_graph_hash,
            "known_nodes": self.known_nodes,
            "quarantined_data": self.quarantined_data
        }

@dataclass
class QuarantineLog:
    """Tier-2 staging area for data ingested by active probes to prevent poisoning."""
    log_id: str
    source_persona_id: str
    raw_telemetry: str
    ingested_at: datetime = field(default_factory=datetime.utcnow)
    flagged_anomalous: bool = False
    review_status: str = 'pending' # 'pending', 'approved', 'rejected'
