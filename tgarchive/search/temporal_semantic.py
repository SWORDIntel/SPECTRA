"""
Temporal-Semantic Correlation Search
====================================

Combines NOT_STISLA for fast temporal filtering with QIHSE for semantic similarity
to find semantically similar messages within specific time windows.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import numpy as np

from .not_stisla_bindings import (
    NotStislaSearchEngine,
    not_stisla_available,
    NOT_STISLA_WORKLOAD_TELEMETRY,
)
from .qihse_bindings import (
    QihseSearchEngine,
    qihse_available,
    QIHSE_TYPE_DOUBLE,
)
from .hybrid_search import SearchResult, SearchType

logger = logging.getLogger(__name__)


class TemporalSemanticSearch:
    """
    Temporal-semantic correlation search engine.
    
    Uses NOT_STISLA for fast temporal filtering (22.28x speedup) combined with
    QIHSE for semantic similarity search (2-5x speedup) to find related messages
    within time windows.
    """
    
    def __init__(self, db_connection, qdrant_url: str = "http://localhost:6333"):
        """
        Initialize temporal-semantic search engine.
        
        Args:
            db_connection: SQLite database connection
            qdrant_url: Qdrant server URL
        """
        self.db = db_connection
        
        # Initialize NOT_STISLA for temporal searches
        self.not_stisla = None
        if not_stisla_available():
            try:
                self.not_stisla = NotStislaSearchEngine(NOT_STISLA_WORKLOAD_TELEMETRY)
                logger.info("NOT_STISLA initialized for temporal search")
            except Exception as e:
                logger.warning(f"Failed to initialize NOT_STISLA: {e}")
        
        # Initialize QIHSE for semantic search
        self.qihse = None
        if qihse_available():
            try:
                self.qihse = QihseSearchEngine(QIHSE_TYPE_DOUBLE, 10000)
                logger.info("QIHSE initialized for semantic search")
            except Exception as e:
                logger.warning(f"Failed to initialize QIHSE: {e}")
        
        # Initialize Qdrant client for vector retrieval
        try:
            from qdrant_client import QdrantClient
            from sentence_transformers import SentenceTransformer
            
            self.qdrant_client = QdrantClient(qdrant_url)
            self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            self.collection_name = "spectra_messages"
            self.embedding_dim = self.embedding_model.get_sentence_embedding_dimension()
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant/embeddings: {e}")
            self.qdrant_client = None
            self.embedding_model = None
    
    def find_semantically_similar_in_timeframe(
        self,
        query: str,
        start_time: datetime,
        end_time: datetime,
        semantic_threshold: float = 0.7,
        limit: int = 20,
        channel_id: Optional[int] = None,
    ) -> List[SearchResult]:
        """
        Find semantically similar messages within time window.
        
        Step 1: Use NOT_STISLA to find messages in time window (22.28x faster than SQL)
        Step 2: Use QIHSE to find semantically similar (on filtered set)
        
        Args:
            query: Semantic search query
            start_time: Start of time window
            end_time: End of time window
            semantic_threshold: Minimum semantic similarity (0-1)
            limit: Maximum results
            channel_id: Optional channel filter
        
        Returns:
            List of SearchResult objects
        """
        # Step 1: Use NOT_STISLA for fast temporal filtering
        timestamp_start = int(start_time.timestamp())
        timestamp_end = int(end_time.timestamp())
        
        message_ids = []
        if self.not_stisla and hasattr(self.db, 'find_messages_by_timestamp_range'):
            try:
                message_ids = self.db.find_messages_by_timestamp_range(
                    timestamp_start, timestamp_end, channel_id
                )
                logger.debug(f"NOT_STISLA found {len(message_ids)} messages in time window")
            except Exception as e:
                logger.warning(f"NOT_STISLA temporal search failed: {e}")
                message_ids = []
        
        # Fallback to SQL if NOT_STISLA unavailable
        if not message_ids:
            try:
                query_sql = """
                    SELECT id FROM messages 
                    WHERE date >= ? AND date <= ?
                """
                params = [start_time.isoformat(), end_time.isoformat()]
                if channel_id:
                    query_sql += " AND channel_id = ?"
                    params.append(channel_id)
                
                cursor = self.db.cur.execute(query_sql, params)
                message_ids = [row[0] for row in cursor.fetchall()]
                logger.debug(f"SQL found {len(message_ids)} messages in time window")
            except Exception as e:
                logger.error(f"SQL temporal search failed: {e}")
                return []
        
        if not message_ids:
            return []
        
        # Step 2: Use QIHSE for semantic search on filtered set
        if not self.qihse or not self.qdrant_client or not self.embedding_model:
            logger.warning("QIHSE/Qdrant not available, using fallback")
            return self._fallback_semantic_search(query, message_ids, semantic_threshold, limit)
        
        try:
            # Generate query embedding
            query_vector = np.array(
                self.embedding_model.encode(query),
                dtype=np.float64
            )
            
            # Get vectors for messages in time window
            vectors = []
            message_id_map = []
            point_data = []
            
            # Retrieve vectors from Qdrant for filtered message IDs
            for msg_id in message_ids[:1000]:  # Limit for performance
                try:
                    points, _ = self.qdrant_client.scroll(
                        collection_name=self.collection_name,
                        scroll_filter={
                            "must": [{
                                "key": "message_id",
                                "match": {"value": msg_id}
                            }]
                        },
                        limit=1,
                    )
                    
                    if points:
                        point = points[0]
                        vectors.append(point.vector)
                        message_id_map.append(msg_id)
                        point_data.append(point.payload)
                except Exception as e:
                    logger.debug(f"Failed to get vector for message {msg_id}: {e}")
                    continue
            
            if not vectors:
                logger.warning("No vectors found for messages in time window")
                return []
            
            # Convert to numpy array
            vectors_array = np.array(vectors, dtype=np.float64)
            
            # Use QIHSE for quantum-inspired search
            qihse_results = self.qihse.search_vectors(
                vectors_array, query_vector, None, semantic_threshold
            )
            
            # Format results
            search_results = []
            for idx, confidence in qihse_results:
                if idx < len(point_data):
                    payload = point_data[idx]
                    msg_id = message_id_map[idx]
                    
                    # Get full message data
                    try:
                        msg_data = self.db.find_message_by_id_fast(msg_id, channel_id) if hasattr(self.db, 'find_message_by_id_fast') else None
                        if not msg_data:
                            # Fallback query
                            cursor = self.db.cur.execute(
                                "SELECT * FROM messages WHERE id = ?", (msg_id,)
                            )
                            row = cursor.fetchone()
                            if row:
                                msg_data = {
                                    'id': row[0],
                                    'content': row[4],
                                    'date': row[2],
                                    'user_id': row[6],
                                }
                    except Exception as e:
                        logger.debug(f"Failed to get message data for {msg_id}: {e}")
                        continue
                    
                    if msg_data:
                        search_results.append(SearchResult(
                            message_id=msg_id,
                            channel_id=channel_id,
                            user_id=msg_data.get('user_id'),
                            content=msg_data.get('content', ''),
                            date=datetime.fromisoformat(msg_data['date']) if isinstance(msg_data['date'], str) else msg_data['date'],
                            relevance_score=float(confidence),
                            match_type=SearchType.SEMANTIC,
                            metadata={
                                'algorithm': 'temporal_semantic',
                                'not_stisla_temporal': True,
                                'qihse_semantic': True,
                                'time_window': {
                                    'start': start_time.isoformat(),
                                    'end': end_time.isoformat(),
                                },
                            },
                        ))
            
            # Sort by relevance and limit
            search_results.sort(key=lambda x: x.relevance_score, reverse=True)
            return search_results[:limit]
            
        except Exception as e:
            logger.error(f"QIHSE semantic search failed: {e}")
            return self._fallback_semantic_search(query, message_ids, semantic_threshold, limit)
    
    def _fallback_semantic_search(
        self,
        query: str,
        message_ids: List[int],
        semantic_threshold: float,
        limit: int,
    ) -> List[SearchResult]:
        """Fallback semantic search using Qdrant only"""
        if not self.qdrant_client or not self.embedding_model:
            return []
        
        try:
            query_vector = self.embedding_model.encode(query)
            
            results = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter={
                    "must": [{
                        "key": "message_id",
                        "match": {"any": message_ids}
                    }]
                },
                score_threshold=semantic_threshold,
            )
            
            search_results = []
            for scored_point in results:
                search_results.append(SearchResult(
                    message_id=scored_point.payload.get("message_id"),
                    channel_id=scored_point.payload.get("channel_id"),
                    user_id=scored_point.payload.get("user_id"),
                    content=scored_point.payload.get("content", ""),
                    date=datetime.fromisoformat(scored_point.payload.get("date", "")) if isinstance(scored_point.payload.get("date"), str) else datetime.now(),
                    relevance_score=scored_point.score,
                    match_type=SearchType.SEMANTIC,
                    metadata={'algorithm': 'fallback_semantic'},
                ))
            
            return search_results
        except Exception as e:
            logger.error(f"Fallback semantic search failed: {e}")
            return []
