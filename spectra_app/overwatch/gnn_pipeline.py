from typing import List, Dict, Any
import json
from datetime import datetime
from spectra_app.overwatch.models import IntelligenceNode, RelationalEdge

class GNNIngestionPipeline:
    """
    Ingests high-velocity telemetry to prepare structural data for the GNN predictive engine.
    This component bridges raw ingestion from QIHSE with the mathematical matrix formulation.
    """

    def __init__(self, use_npu_acceleration: bool = True):
        self.use_npu_acceleration = use_npu_acceleration
        self.node_registry: Dict[str, IntelligenceNode] = {}
        self.edge_registry: List[RelationalEdge] = []

    def ingest_telemetry_batch(self, telemetry_batch: List[Dict[str, Any]]) -> dict:
        """
        Process a batch of Telegram telemetry (messages, user profiles, infrastructure mentions)
        into normalized GNN nodes and edges.

        Args:
            telemetry_batch: List of JSON/Dict objects containing scraped data.
        Returns:
            Dictionary with counts of newly discovered nodes and edges.
        """
        new_nodes_count = 0
        new_edges_count = 0

        for item in telemetry_batch:
            # Example heuristic extraction of nodes
            if 'actor_id' in item:
                actor_id = item['actor_id']
                if actor_id not in self.node_registry:
                    self.node_registry[actor_id] = IntelligenceNode(
                        node_id=actor_id,
                        node_type='actor',
                        metadata={"username": item.get('username', 'unknown')}
                    )
                    new_nodes_count += 1

            # Extract shared infrastructure (e.g., Panel URLs or Crypto Wallets)
            if 'infrastructure_link' in item and 'actor_id' in item:
                infra_id = item['infrastructure_link']
                if infra_id not in self.node_registry:
                    self.node_registry[infra_id] = IntelligenceNode(
                        node_id=infra_id,
                        node_type='infrastructure'
                    )
                    new_nodes_count += 1

                # Create relational edge
                edge = RelationalEdge(
                    source_id=item['actor_id'],
                    target_id=infra_id,
                    relation_type='shares_infrastructure',
                    evidence_references=[item.get('message_id', 'unknown_msg')]
                )
                self.edge_registry.append(edge)
                new_edges_count += 1

        return {
            "status": "success",
            "nodes_added": new_nodes_count,
            "edges_added": new_edges_count,
            "total_nodes": len(self.node_registry),
            "total_edges": len(self.edge_registry)
        }

    def export_graph_matrix(self) -> dict:
        """
        Serializes the current relational state for OpenVINO/NPU inference execution.
        """
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "nodes": [node.__dict__ for node in self.node_registry.values()],
            "edges": [edge.__dict__ for edge in self.edge_registry],
            "npu_target": "Meteor_Lake_OpenVINO" if self.use_npu_acceleration else "CPU"
        }
