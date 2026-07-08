"""
Unified Search Engine with Intelligent Algorithm Selection
=========================================================

Intelligently selects optimal search algorithm (KEYSTONE, QIHSE, FTS5, or hybrid)
based on query characteristics for maximum performance.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from enum import Enum

from .hybrid_search import (
    HybridSearchEngine,
    SQLiteFTS5IndexManager,
    QIHSEVectorManager,
    SearchResult,
    SearchType,
)

QdrantVectorManager = QIHSEVectorManager
from .keystone_bindings import (
    KeystoneSearchEngine,
    keystone_available,
    KEYSTONE_WORKLOAD_TELEMETRY,
    KEYSTONE_WORKLOAD_IDS,
)
from .qihse_bindings import (
    QihseSearchEngine,
    qihse_available,
)

logger = logging.getLogger(__name__)


class SearchAlgorithm(Enum):
    """Available search algorithms"""
    KEYSTONE = "keystone"
    QIHSE = "qihse"
    FTS5 = "fts5"
    HYBRID = "hybrid"
    AUTO = "auto"


class UnifiedSearchEngine:
    """
    Intelligent search engine that automatically selects optimal algorithm.
    
    Selection logic:
    - KEYSTONE: Sorted numeric data (timestamps, IDs, offsets)
    - QIHSE: Vector/semantic queries
    - FTS5: Keyword/text queries
    - Hybrid: Complex multi-criteria queries
    """
    
    def __init__(self, db_connection, qdrant_url: str = "http://localhost:6333", cache_manager=None):
        """
        Initialize unified search engine.
        
        Args:
            db_connection: SQLite database connection
            qdrant_url: Qdrant server URL
            cache_manager: Optional CacheManager instance
        """
        self.db = db_connection
        self.cache = cache_manager
        
        vector_store_path = os.getenv(
            "SPECTRA_QIHSE_VECTOR_PATH",
            os.path.join(os.getenv("QIHSE_INDEX_ROOT", "/data/indexes/qihse-api"), "spectra_vectors"),
        )
        if qdrant_url and not qdrant_url.startswith(("http://", "https://")):
            vector_store_path = qdrant_url

        # Initialize search engines with cache
        self.fts5 = SQLiteFTS5IndexManager(db_connection)
        self.vector = QIHSEVectorManager(vector_store_path=vector_store_path)
        self.hybrid = HybridSearchEngine(db_connection, vector_store_path=vector_store_path, cache_manager=cache_manager)
        
        # Initialize KEYSTONE engines
        self.keystone_timestamp = None
        self.keystone_message_id = None
        if keystone_available():
            try:
                self.keystone_timestamp = KeystoneSearchEngine(KEYSTONE_WORKLOAD_TELEMETRY)
                self.keystone_message_id = KeystoneSearchEngine(KEYSTONE_WORKLOAD_IDS)
                logger.info("KEYSTONE engines initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize KEYSTONE: {e}")
        
        # Initialize QIHSE engine
        self.qihse = None
        if qihse_available():
            try:
                self.qihse = QihseSearchEngine()
                logger.info("QIHSE engine initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize QIHSE: {e}")
    
    def search(self, query: str, search_type: str = "auto", limit: int = 20, **kwargs) -> List[SearchResult]:
        """
        Unified search with automatic algorithm selection.
        
        Args:
            query: Search query
            search_type: Algorithm to use ("auto", "keystone", "qihse", "fts5", "hybrid")
            limit: Maximum results
            **kwargs: Additional filters (date_from, date_to, channel_id, user_id, etc.)
        
        Returns:
            List of SearchResult objects
        """
        # Check cache first
        if self.cache:
            cache_params = {'query': query, 'search_type': search_type, 'limit': limit, **kwargs}
            cached = self.cache.get_cached_search_result(query, search_type, **kwargs)
            if cached:
                logger.debug("Cache hit for unified search")
                return cached
        
        # Auto-detect optimal algorithm
        if search_type == "auto":
            search_type = self._detect_optimal_algorithm(query, kwargs)
        
        logger.debug(f"Using search algorithm: {search_type}")
        
        # Route to appropriate algorithm
        if search_type == "keystone" or search_type == "timestamp":
            return self._search_keystone(query, limit, **kwargs)
        
        elif search_type == "qihse" or search_type == "semantic":
            return self._search_qihse(query, limit, **kwargs)
        
        elif search_type == "hybrid":
            return self._search_hybrid(query, limit, **kwargs)
        
        else:  # "fts5" or "keyword"
            results = self._search_fts5(query, limit, **kwargs)
        
        # Cache results
        if self.cache and results:
            self.cache.cache_search_result(query, search_type, results, ttl=1800, **kwargs)
        
        return results
    
    def _detect_optimal_algorithm(self, query: str, filters: dict) -> str:
        """
        Detect best algorithm based on query characteristics.
        
        Args:
            query: Search query
            filters: Query filters
        
        Returns:
            Algorithm name
        """
        # Check for timestamp filters (KEYSTONE)
        if 'date_from' in filters or 'date_to' in filters or 'timestamp' in query.lower():
            return "keystone"
        
        # Check for message ID lookup (KEYSTONE)
        if 'message_id' in filters or query.isdigit():
            return "keystone"
        
        # Check for semantic intent (QIHSE)
        semantic_keywords = ['similar', 'related', 'like', 'find similar', 'semantic', 'meaning']
        if any(keyword in query.lower() for keyword in semantic_keywords):
            return "qihse"
        
        # Check for complex multi-criteria (Hybrid)
        if len(filters) > 2 or ('date_from' in filters and len(query.split()) > 2):
            return "hybrid"
        
        # Default to keyword search (FTS5)
        return "fts5"
    
    def _search_keystone(self, query: str, limit: int, **kwargs) -> List[SearchResult]:
        """Search using KEYSTONE for sorted numeric data"""
        results = []
        
        # Timestamp range search
        if 'date_from' in kwargs or 'date_to' in kwargs:
            start_time = kwargs.get('date_from')
            end_time = kwargs.get('date_to')
            
            if isinstance(start_time, datetime):
                start_timestamp = int(start_time.timestamp())
            elif isinstance(start_time, (int, float)):
                start_timestamp = int(start_time)
            else:
                start_timestamp = None
            
            if isinstance(end_time, datetime):
                end_timestamp = int(end_time.timestamp())
            elif isinstance(end_time, (int, float)):
                end_timestamp = int(end_time)
            else:
                end_timestamp = None
            
            if start_timestamp and end_timestamp and self.keystone_timestamp:
                # Use KEYSTONE for fast timestamp range search
                from ..db import SpectraDB
                if isinstance(self.db, SpectraDB):
                    message_ids = self.db.find_messages_by_timestamp_range(
                        start_timestamp, end_timestamp, kwargs.get('channel_id')
                    )
                    
                    # Get full message data
                    for msg_id in message_ids[:limit]:
                        msg_data = self.db.find_message_by_id_fast(msg_id, kwargs.get('channel_id'))
                        if msg_data:
                            results.append(SearchResult(
                                message_id=msg_data['id'],
                                channel_id=kwargs.get('channel_id'),
                                user_id=msg_data.get('user_id'),
                                content=msg_data.get('content', ''),
                                date=datetime.fromisoformat(msg_data['date']) if isinstance(msg_data['date'], str) else msg_data['date'],
                                relevance_score=1.0,
                                match_type=SearchType.KEYWORD,
                                metadata={'algorithm': 'keystone', 'search_type': 'timestamp_range'},
                            ))
        
        # Message ID lookup
        elif query.isdigit() and self.keystone_message_id:
            msg_id = int(query)
            from ..db import SpectraDB
            if isinstance(self.db, SpectraDB):
                msg_data = self.db.find_message_by_id_fast(msg_id, kwargs.get('channel_id'))
                if msg_data:
                    results.append(SearchResult(
                        message_id=msg_data['id'],
                        channel_id=kwargs.get('channel_id'),
                        user_id=msg_data.get('user_id'),
                        content=msg_data.get('content', ''),
                        date=datetime.fromisoformat(msg_data['date']) if isinstance(msg_data['date'], str) else msg_data['date'],
                        relevance_score=1.0,
                        match_type=SearchType.KEYWORD,
                        metadata={'algorithm': 'keystone', 'search_type': 'message_id'},
                    ))
        
        return results
    
    def _search_qihse(self, query: str, limit: int, **kwargs) -> List[SearchResult]:
        """Search using QIHSE for semantic/vector queries"""
        if not self.qihse:
            # Fallback to Qdrant
            return self.vector.search_semantic(query, limit, **kwargs)
        
        # Use QIHSE-accelerated semantic search
        return self.vector.search_semantic(
            query, limit, 
            use_qihse=True,
            **kwargs
        )
    
    def _search_fts5(self, query: str, limit: int, **kwargs) -> List[SearchResult]:
        """Search using FTS5 for keyword queries"""
        fts5_results = self.fts5.search_messages(query, limit=limit, **kwargs)
        
        results = []
        for row in fts5_results:
            results.append(SearchResult(
                message_id=row[0],
                channel_id=row[1],
                user_id=row[2],
                content=row[3],
                date=datetime.fromisoformat(row[4]) if isinstance(row[4], str) else row[4],
                relevance_score=abs(row[6]) / 100.0,
                match_type=SearchType.KEYWORD,
                metadata={'algorithm': 'fts5'},
            ))
        
        return results
    
    def _search_hybrid(self, query: str, limit: int, **kwargs) -> List[SearchResult]:
        """Hybrid search combining multiple algorithms"""
        return self.hybrid.search(query, limit=limit, search_type=SearchType.HYBRID, **kwargs)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics from all search engines"""
        stats = {
            'fts5': self.fts5.get_statistics(),
            'vector': self.vector.get_statistics(),
        }
        
        if self.keystone_timestamp:
            stats['keystone_timestamp'] = self.keystone_timestamp.get_stats()
        if self.keystone_message_id:
            stats['keystone_message_id'] = self.keystone_message_id.get_stats()
        if self.qihse:
            stats['qihse'] = self.qihse.get_performance_stats()
        
        return stats
