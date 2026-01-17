"""
Distributed Search Coordinator
================================

Coordinates search across multiple nodes with intelligent query routing,
result aggregation, and load balancing.
"""

import logging
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
import asyncio
import hashlib
import json

from .search_node import SearchNode, NodeHealth
from .hybrid_search import SearchResult, SearchType

logger = logging.getLogger(__name__)


class DistributedSearchCoordinator:
    """
    Coordinates distributed search across multiple nodes.
    
    Features:
    - Node discovery and registration
    - Health monitoring and failover
    - Query routing based on data shards
    - Result aggregation and deduplication
    - Load balancing
    """
    
    def __init__(self, local_node: SearchNode):
        """
        Initialize distributed search coordinator.
        
        Args:
            local_node: Local search node instance
        """
        self.local_node = local_node
        self.nodes: Dict[str, SearchNode] = {local_node.node_id: local_node}
        self.node_shards: Dict[str, Dict[str, Any]] = {}
        self.failed_nodes: Set[str] = set()
        
        # Routing strategies
        self.routing_strategy = "shard_based"  # or "round_robin", "load_balanced"
    
    def register_node(
        self,
        node: SearchNode,
        shard: Optional[Dict[str, Any]] = None
    ):
        """
        Register a new search node.
        
        Args:
            node: SearchNode instance
            shard: Optional shard definition for this node
        """
        self.nodes[node.node_id] = node
        if shard:
            self.node_shards[node.node_id] = shard
        logger.info(f"Registered search node: {node.node_id}")
    
    def unregister_node(self, node_id: str):
        """Unregister a node"""
        if node_id in self.nodes:
            del self.nodes[node_id]
        if node_id in self.node_shards:
            del self.node_shards[node_id]
        self.failed_nodes.discard(node_id)
        logger.info(f"Unregistered search node: {node_id}")
    
    def get_healthy_nodes(self) -> List[SearchNode]:
        """Get list of healthy nodes"""
        healthy = []
        for node_id, node in self.nodes.items():
            if node_id not in self.failed_nodes:
                health = node.get_health()
                if health.is_healthy and node.can_handle_search():
                    healthy.append(node)
        return healthy
    
    def route_query(
        self,
        query: str,
        **kwargs
    ) -> List[SearchNode]:
        """
        Route query to appropriate nodes based on shards and load.
        
        Args:
            query: Search query
            **kwargs: Search parameters (filter_channel, date_from, etc.)
        
        Returns:
            List of nodes to query
        """
        healthy_nodes = self.get_healthy_nodes()
        
        if not healthy_nodes:
            logger.warning("No healthy nodes available, using local node only")
            return [self.local_node]
        
        # Shard-based routing
        if self.routing_strategy == "shard_based":
            selected_nodes = []
            
            # Check if query matches specific shards
            for node_id, shard in self.node_shards.items():
                if node_id not in self.nodes:
                    continue
                node = self.nodes[node_id]
                
                # Check channel filter
                if 'channel_ids' in shard and 'filter_channel' in kwargs:
                    if kwargs['filter_channel'] in shard['channel_ids']:
                        selected_nodes.append(node)
                        continue
                
                # Check date range
                if 'date_range' in shard:
                    shard_start, shard_end = shard['date_range']
                    query_start = kwargs.get('date_from')
                    query_end = kwargs.get('date_to')
                    
                    if query_start and query_end:
                        # Check overlap
                        if not (query_end < shard_start or query_start > shard_end):
                            selected_nodes.append(node)
                            continue
                
                # If no specific match, node handles general queries
                if 'general' in shard.get('types', []):
                    selected_nodes.append(node)
            
            if selected_nodes:
                return selected_nodes
        
        # Load-balanced routing
        elif self.routing_strategy == "load_balanced":
            # Sort by active searches (least loaded first)
            healthy_nodes.sort(
                key=lambda n: n.health.active_searches / max(1, n.health.search_capacity)
            )
            # Use top 3 least loaded nodes
            return healthy_nodes[:min(3, len(healthy_nodes))]
        
        # Round-robin (default)
        else:
            # Use all healthy nodes
            return healthy_nodes
    
    def search(
        self,
        query: str,
        search_type: str = "auto",
        limit: int = 20,
        **kwargs
    ) -> List[SearchResult]:
        """
        Execute distributed search across multiple nodes.
        
        Args:
            query: Search query
            search_type: Search type
            limit: Maximum results per node
            **kwargs: Additional search parameters
        
        Returns:
            Aggregated and deduplicated results
        """
        # Route query to appropriate nodes
        target_nodes = self.route_query(query, **kwargs)
        
        if not target_nodes:
            logger.warning("No nodes available for search")
            return []
        
        # Execute searches on all target nodes
        all_results = []
        for node in target_nodes:
            try:
                node_results = node.search(query, search_type, limit * 2, **kwargs)
                all_results.extend(node_results)
            except Exception as e:
                logger.error(f"Search failed on node {node.node_id}: {e}")
                self.failed_nodes.add(node.node_id)
        
        # Deduplicate results by message_id
        seen_ids = set()
        unique_results = []
        for result in all_results:
            if result.message_id not in seen_ids:
                seen_ids.add(result.message_id)
                unique_results.append(result)
        
        # Re-rank combined results
        unique_results.sort(key=lambda x: x.relevance_score, reverse=True)
        
        return unique_results[:limit]
    
    async def search_async(
        self,
        query: str,
        search_type: str = "auto",
        limit: int = 20,
        **kwargs
    ) -> List[SearchResult]:
        """Async distributed search"""
        target_nodes = self.route_query(query, **kwargs)
        
        if not target_nodes:
            return []
        
        # Execute searches in parallel
        tasks = [
            node.search_async(query, search_type, limit * 2, **kwargs)
            for node in target_nodes
        ]
        
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Aggregate results
        all_results = []
        for i, results in enumerate(results_list):
            if isinstance(results, Exception):
                logger.error(f"Search failed on node {target_nodes[i].node_id}: {results}")
                self.failed_nodes.add(target_nodes[i].node_id)
            else:
                all_results.extend(results)
        
        # Deduplicate and re-rank
        seen_ids = set()
        unique_results = []
        for result in all_results:
            if result.message_id not in seen_ids:
                seen_ids.add(result.message_id)
                unique_results.append(result)
        
        unique_results.sort(key=lambda x: x.relevance_score, reverse=True)
        return unique_results[:limit]
    
    def get_cluster_status(self) -> Dict[str, Any]:
        """Get status of all nodes in cluster"""
        status = {
            'total_nodes': len(self.nodes),
            'healthy_nodes': len(self.get_healthy_nodes()),
            'failed_nodes': list(self.failed_nodes),
            'nodes': {}
        }
        
        for node_id, node in self.nodes.items():
            health = node.get_health()
            status['nodes'][node_id] = {
                'is_healthy': health.is_healthy,
                'active_searches': health.active_searches,
                'search_capacity': health.search_capacity,
                'avg_response_time_ms': health.avg_response_time_ms,
                'error_rate': health.error_rate,
                'has_shard': node_id in self.node_shards,
            }
        
        return status
    
    def recover_failed_nodes(self):
        """Attempt to recover failed nodes"""
        recovered = []
        for node_id in list(self.failed_nodes):
            if node_id in self.nodes:
                node = self.nodes[node_id]
                health = node.get_health()
                # Check if node is healthy now
                if health.is_healthy:
                    self.failed_nodes.remove(node_id)
                    recovered.append(node_id)
                    logger.info(f"Recovered node: {node_id}")
        
        return recovered
