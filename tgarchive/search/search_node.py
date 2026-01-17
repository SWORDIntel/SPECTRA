"""
Search Node Implementation
==========================

Individual search node for distributed search architecture.
Each node handles a subset of the data and can execute searches independently.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import asyncio

from .hybrid_search import HybridSearchEngine, SearchResult, SearchType
from .unified_search import UnifiedSearchEngine

logger = logging.getLogger(__name__)


@dataclass
class NodeHealth:
    """Node health status"""
    node_id: str
    is_healthy: bool
    last_heartbeat: datetime
    search_capacity: int  # Concurrent searches
    active_searches: int
    avg_response_time_ms: float
    error_rate: float


class SearchNode:
    """
    Individual search node in distributed architecture.
    
    Each node manages:
    - Local database connection
    - Search engines (NOT_STISLA, QIHSE, FTS5)
    - Node-specific data shard
    - Health monitoring
    """
    
    def __init__(
        self,
        node_id: str,
        db_connection,
        qdrant_url: str = "http://localhost:6333",
        data_shard: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize search node.
        
        Args:
            node_id: Unique node identifier
            db_connection: SQLite database connection for this node
            qdrant_url: Qdrant server URL
            data_shard: Optional shard definition (channel_ids, date_ranges, etc.)
        """
        self.node_id = node_id
        self.db = db_connection
        self.qdrant_url = qdrant_url
        self.data_shard = data_shard or {}
        
        # Initialize search engines
        self.hybrid_engine = HybridSearchEngine(
            db_connection, qdrant_url, use_not_stisla=True, use_qihse=True
        )
        self.unified_engine = UnifiedSearchEngine(db_connection, qdrant_url)
        
        # Health tracking
        self.health = NodeHealth(
            node_id=node_id,
            is_healthy=True,
            last_heartbeat=datetime.now(),
            search_capacity=100,
            active_searches=0,
            avg_response_time_ms=0.0,
            error_rate=0.0,
        )
        
        # Performance tracking
        self.search_count = 0
        self.total_response_time_ms = 0.0
        self.error_count = 0
    
    def search(
        self,
        query: str,
        search_type: str = "auto",
        limit: int = 20,
        **kwargs
    ) -> List[SearchResult]:
        """
        Execute search on this node.
        
        Args:
            query: Search query
            search_type: Search type (auto, not_stisla, qihse, fts5, hybrid)
            limit: Maximum results
            **kwargs: Additional search parameters
        
        Returns:
            List of SearchResult objects
        """
        start_time = datetime.now()
        self.health.active_searches += 1
        self.search_count += 1
        
        try:
            # Apply shard filters if defined
            if self.data_shard:
                if 'channel_ids' in self.data_shard:
                    if 'filter_channel' not in kwargs:
                        # Node only handles specific channels
                        if kwargs.get('filter_channel') not in self.data_shard['channel_ids']:
                            return []
                
                if 'date_range' in self.data_shard:
                    shard_start, shard_end = self.data_shard['date_range']
                    if 'date_from' in kwargs:
                        if kwargs['date_from'] > shard_end:
                            return []
                    if 'date_to' in kwargs:
                        if kwargs['date_to'] < shard_start:
                            return []
            
            # Execute search using unified engine
            results = self.unified_engine.search(
                query, search_type, limit, **kwargs
            )
            
            # Update health metrics
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            self.total_response_time_ms += elapsed_ms
            self.health.avg_response_time_ms = (
                self.total_response_time_ms / self.search_count
            )
            
            return results
            
        except Exception as e:
            self.error_count += 1
            self.health.error_rate = self.error_count / max(1, self.search_count)
            logger.error(f"Search failed on node {self.node_id}: {e}")
            return []
        finally:
            self.health.active_searches -= 1
            self.health.last_heartbeat = datetime.now()
    
    async def search_async(
        self,
        query: str,
        search_type: str = "auto",
        limit: int = 20,
        **kwargs
    ) -> List[SearchResult]:
        """Async version of search"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.search, query, search_type, limit, **kwargs
        )
    
    def get_health(self) -> NodeHealth:
        """Get current node health status"""
        return self.health
    
    def update_capacity(self, new_capacity: int):
        """Update search capacity"""
        self.health.search_capacity = new_capacity
    
    def can_handle_search(self) -> bool:
        """Check if node can handle another search"""
        return (
            self.health.is_healthy and
            self.health.active_searches < self.health.search_capacity
        )
