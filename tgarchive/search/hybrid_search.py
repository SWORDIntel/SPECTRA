"""
Hybrid Search Architecture with SQLite FTS5 + Qdrant Vector Database
====================================================================

This module implements a unified search system that combines:
1. SQLite FTS5 - Full-text keyword search
2. Qdrant - Vector/semantic search
3. Hybrid search - Combined results with ranking

Storage Architecture:
- SQLite: Plain text messages, metadata, FTS5 indexes
- Qdrant: Vector embeddings, semantic relationships
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
import numpy as np

# ── QIHSE Integration ─────────────────────────────────────────────────────
try:
    from .qihse_bindings import (
        QihseSearchEngine,
        qihse_available,
        QIHSE_TYPE_DOUBLE,
    )
    from .qihse_config import (
        create_qihse_config,
        configure_qihse_for_semantic_search,
    )
    QIHSE_ENABLED = True
except ImportError:
    QIHSE_ENABLED = False
    logger = logging.getLogger(__name__)
    logger.warning("QIHSE bindings not available. Using Qdrant only.")

logger = logging.getLogger(__name__)


class SearchType(Enum):
    """Search types supported."""
    KEYWORD = "keyword"      # FTS5 full-text search
    SEMANTIC = "semantic"    # Vector/embedding search
    HYBRID = "hybrid"        # Combined keyword + semantic


@dataclass
class SearchResult:
    """Unified search result."""
    message_id: int
    channel_id: int
    user_id: Optional[int]
    content: str
    date: datetime
    relevance_score: float  # 0-1 (higher = more relevant)
    match_type: SearchType
    metadata: Dict[str, Any]


class SQLiteFTS5IndexManager:
    """
    Manages SQLite FTS5 (Full-Text Search 5) indexes for fast keyword search.

    FTS5 Features:
    - Tokenization with language-specific support
    - Phrase queries and proximity search
    - Field-specific search
    - Ranking with BM25 algorithm
    """

    FTS5_INIT_SQL = """
    -- Create FTS5 virtual table for messages
    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
        message_id UNINDEXED,
        content,
        user_id UNINDEXED,
        channel_id UNINDEXED,
        date UNINDEXED,
        content='messages',           -- Shadow table: messages_content
        content_rowid='id'            -- Link to main table
    );

    -- Create trigger to sync FTS5 on INSERT
    CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, message_id, content, user_id, channel_id, date)
        VALUES (new.id, new.id, new.content, new.user_id, new.channel_id, new.date);
    END;

    -- Create trigger to sync FTS5 on UPDATE
    CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, message_id, content, user_id, channel_id, date)
        VALUES('delete', old.id, old.id, old.content, old.user_id, old.channel_id, old.date);
        INSERT INTO messages_fts(rowid, message_id, content, user_id, channel_id, date)
        VALUES (new.id, new.id, new.content, new.user_id, new.channel_id, new.date);
    END;

    -- Create trigger to sync FTS5 on DELETE
    CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, message_id, content, user_id, channel_id, date)
        VALUES('delete', old.id, old.id, old.content, old.user_id, old.channel_id, old.date);
    END;

    -- Create FTS5 table for user metadata
    CREATE VIRTUAL TABLE IF NOT EXISTS users_fts USING fts5(
        user_id UNINDEXED,
        username,
        first_name,
        last_name,
        content='users',
        content_rowid='id'
    );
    """

    def __init__(self, db_connection):
        """
        Initialize FTS5 indexes.

        Args:
            db_connection: SQLite connection with FTS5 extension loaded
        """
        self.conn = db_connection
        self._initialize_fts5()

    def _initialize_fts5(self):
        """Create FTS5 tables and triggers."""
        try:
            self.conn.executescript(self.FTS5_INIT_SQL)
            self.conn.commit()
            logger.info("✓ FTS5 indexes initialized successfully")
        except Exception as e:
            logger.error(f"✗ FTS5 initialization failed: {e}")
            raise

    def search_messages(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        filter_channel: Optional[int] = None,
        filter_user: Optional[int] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search messages using FTS5 keyword search.

        Supports:
        - Simple queries: "word1 word2"
        - Phrase queries: '"exact phrase"'
        - Boolean: "word1 OR word2", "word1 AND word2", "NOT word1"
        - Proximity: 'word1 NEAR word2'
        - Wildcards: 'word*'

        Args:
            query: FTS5 search query
            limit: Max results to return
            offset: Result offset for pagination
            filter_channel: Filter by channel ID
            filter_user: Filter by user ID
            date_from: Filter messages from this date
            date_to: Filter messages until this date

        Returns:
            List of matching messages with relevance scores
        """
        sql = """
        SELECT
            m.id,
            m.channel_id,
            m.user_id,
            m.content,
            m.date,
            m.type,
            -- BM25 ranking: higher = more relevant
            rank * -1 as relevance_score
        FROM messages_fts
        INNER JOIN messages m ON messages_fts.rowid = m.id
        WHERE messages_fts MATCH ?
        """

        params = [query]

        # Add optional filters
        if filter_channel is not None:
            sql += " AND messages_fts.channel_id = ?"
            params.append(filter_channel)

        if filter_user is not None:
            sql += " AND messages_fts.user_id = ?"
            params.append(filter_user)

        if date_from:
            sql += " AND m.date >= ?"
            params.append(date_from.isoformat())

        if date_to:
            sql += " AND m.date <= ?"
            params.append(date_to.isoformat())

        sql += " ORDER BY rank LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        try:
            results = self.conn.execute(sql, params).fetchall()
            logger.debug(f"FTS5 search returned {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"FTS5 search failed: {e}")
            return []

    def rebuild_indexes(self):
        """Rebuild all FTS5 indexes (expensive operation)."""
        try:
            self.conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild');")
            self.conn.execute("INSERT INTO users_fts(users_fts) VALUES('rebuild');")
            self.conn.commit()
            logger.info("✓ FTS5 indexes rebuilt successfully")
        except Exception as e:
            logger.error(f"✗ FTS5 rebuild failed: {e}")

    def get_statistics(self) -> Dict[str, int]:
        """Get FTS5 index statistics."""
        stats = {}
        try:
            # Count indexed messages
            result = self.conn.execute(
                "SELECT COUNT(*) FROM messages_fts"
            ).fetchone()
            stats['indexed_messages'] = result[0] if result else 0

            # Count indexed users
            result = self.conn.execute(
                "SELECT COUNT(*) FROM users_fts"
            ).fetchone()
            stats['indexed_users'] = result[0] if result else 0

            logger.info(f"FTS5 Statistics: {stats}")
            return stats
        except Exception as e:
            logger.error(f"Failed to get FTS5 stats: {e}")
            return {}


class QIHSEVectorManager:
    """
    Manages QIHSE vector database for semantic search (primary backend).

    Features:
    - Direct vector storage using QIHSE
    - Automatic embedding generation using SentenceTransformers
    - Quantum-inspired semantic similarity search
    - Metadata filtering
    - Replaces Qdrant as primary storage
    """

    def __init__(
        self,
        vector_store_path: str = "./data/qihse_vectors",
        collection_name: str = "spectra_messages",
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        """
        Initialize QIHSE vector manager.

        Args:
            vector_store_path: Path to store QIHSE vectors
            collection_name: Collection name
            embedding_model: HuggingFace model for embeddings
        """
        from sentence_transformers import SentenceTransformer
        from ..db.vector_store import VectorStoreManager, VectorStoreConfig

        self.model = SentenceTransformer(embedding_model)
        self.collection_name = collection_name
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        
        # Initialize QIHSE vector store (primary backend)
        config = VectorStoreConfig(
            backend="qihse",
            path=vector_store_path,
            collection_name=collection_name,
            vector_size=self.embedding_dim,
            confidence_threshold=0.95
        )
        
        try:
            self.vector_store = VectorStoreManager(config)
            logger.info("QIHSE vector store initialized (primary backend)")
        except Exception as e:
            logger.error(f"Failed to initialize QIHSE vector store: {e}")
            raise

    def _initialize_collection(self):
        """Initialize QIHSE collection (no-op, handled by VectorStoreManager)."""
        # Collection is automatically initialized by VectorStoreManager
        pass

    def embed_message(self, content: str) -> List[float]:
        """
        Generate embedding for message content.

        Args:
            content: Message text

        Returns:
            Embedding vector (384 dimensions default)
        """
        embedding = self.model.encode(content)
        return embedding.tolist()

    def index_message(
        self,
        message_id: int,
        content: str,
        channel_id: int,
        user_id: Optional[int],
        date: datetime,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Index a message in Qdrant.

        Args:
            message_id: Unique message ID
            content: Message text
            channel_id: Channel ID
            user_id: User ID
            date: Message timestamp
            metadata: Additional metadata
        """
        from qdrant_client.models import PointStruct

        try:
            # Generate embedding
            vector = self.embed_message(content)

            # Prepare metadata
            payload = {
                "message_id": message_id,
                "content": content[:500],  # Store first 500 chars
                "channel_id": channel_id,
                "user_id": user_id,
                "date": date.isoformat(),
            }
            if metadata:
                payload.update(metadata)

            # Upsert point in Qdrant
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(id=message_id, vector=vector, payload=payload)
                ],
            )
            logger.debug(f"Indexed message {message_id} in Qdrant")

        except Exception as e:
            logger.error(f"Failed to index message {message_id}: {e}")

    def search_semantic(
        self,
        query: str,
        limit: int = 20,
        filter_channel: Optional[int] = None,
        filter_user: Optional[int] = None,
        score_threshold: float = 0.3,
        use_qihse: Optional[bool] = None,  # Deprecated, QIHSE is always used
    ) -> List[Dict[str, Any]]:
        """
        Semantic search using QIHSE quantum-inspired vector similarity.

        Args:
            query: Natural language search query
            limit: Max results
            filter_channel: Filter by channel
            filter_user: Filter by user
            score_threshold: Minimum similarity score (0-1)
            use_qihse: Deprecated (QIHSE is always used)

        Returns:
            List of similar messages with scores
        """
        try:
            # Generate query embedding
            query_embedding = self.embed_message(query)

            # Build filters
            filters = {}
            if filter_channel is not None:
                filters["channel_id"] = filter_channel
            if filter_user is not None:
                filters["user_id"] = filter_user

            # Search QIHSE vector store
            results = self.vector_store.semantic_search(
                query_embedding=np.array(query_embedding),
                top_k=limit,
                filters=filters if filters else None,
                min_score=score_threshold
            )

            # Format results
            search_results = []
            for result in results:
                search_results.append({
                    "message_id": result.payload.get("message_id"),
                    "content": result.payload.get("content"),
                    "channel_id": result.payload.get("channel_id"),
                    "user_id": result.payload.get("user_id"),
                    "date": result.payload.get("date"),
                    "relevance_score": result.score,
                    "match_type": SearchType.SEMANTIC,
                })

            logger.debug(f"QIHSE semantic search returned {len(search_results)} results")
            return search_results

        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []
    
    def _search_semantic_qihse(
        self,
        query: str,
        limit: int,
        filter_channel: Optional[int],
        filter_user: Optional[int],
        score_threshold: float,
    ) -> List[Dict[str, Any]]:
        """Semantic search using QIHSE quantum-inspired algorithm"""
        # Generate query embedding
        query_vector = np.array(self.embed_message(query), dtype=np.float64)
        
        # Get all vectors from Qdrant matching filters
        collection_info = self.client.get_collection(self.collection_name)
        total_vectors = collection_info.points_count
        
        # Retrieve vectors with filters
        vectors = []
        message_ids = []
        point_data = []
        batch_size = 1000
        
        for offset in range(0, min(total_vectors, 10000), batch_size):  # Limit for performance
            points, _ = self.client.scroll(
                collection_name=self.collection_name,
                limit=batch_size,
                offset=offset,
            )
            
            for point in points:
                # Apply filters
                if filter_channel is not None:
                    if point.payload.get("channel_id") != filter_channel:
                        continue
                if filter_user is not None:
                    if point.payload.get("user_id") != filter_user:
                        continue
                
                vectors.append(point.vector)
                message_ids.append(point.payload.get("message_id"))
                point_data.append(point.payload)
        
        if not vectors:
            return []
        
        # Convert to numpy array
        vectors_array = np.array(vectors, dtype=np.float64)
        
        # Use QIHSE for quantum-inspired search
        results = self.qihse_engine.search_vectors(
            vectors_array, query_vector, None, score_threshold
        )
        
        # Format results
        search_results = []
        for idx, confidence in results:
            if idx < len(point_data):
                payload = point_data[idx]
                search_results.append({
                    "message_id": payload.get("message_id"),
                    "content": payload.get("content"),
                    "channel_id": payload.get("channel_id"),
                    "user_id": payload.get("user_id"),
                    "date": payload.get("date"),
                    "relevance_score": float(confidence),
                    "match_type": SearchType.SEMANTIC,
                })
        
        # Sort by relevance and limit
        search_results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return search_results[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        """Get vector database statistics."""
        try:
            collection_info = self.client.get_collection(self.collection_name)
            return {
                "indexed_vectors": collection_info.points_count,
                "embedding_dimension": self.embedding_dim,
                "collection_name": self.collection_name,
            }
        except Exception as e:
            logger.error(f"Failed to get Qdrant stats: {e}")
            return {}


class HybridSearchEngine:
    """
    Enhanced hybrid search engine combining NOT_STISLA + QIHSE + FTS5.

    Strategy:
    1. Execute NOT_STISLA for structured data (timestamps, IDs)
    2. Execute QIHSE for semantic/vector searches
    3. Execute FTS5 for keyword searches
    4. Intelligently combine and rank results
    5. Return unified result set with algorithm metadata
    """

    def __init__(
        self,
        db_connection,
        vector_store_path: str = "./data/qihse_vectors",
        use_not_stisla: bool = True,
        use_qihse: bool = True,  # QIHSE is primary, always enabled
        cache_manager=None,
    ):
        """
        Initialize enhanced hybrid search engine.

        Args:
            db_connection: SQLite connection
            vector_store_path: Path to QIHSE vector store
            use_not_stisla: Enable NOT_STISLA optimizations
            use_qihse: Enable QIHSE (always True, QIHSE is primary)
            cache_manager: Optional CacheManager instance
        """
        self.fts5 = SQLiteFTS5IndexManager(db_connection)
        self.vector = QIHSEVectorManager(vector_store_path=vector_store_path)
        self.cache = cache_manager
        
        # Initialize NOT_STISLA engines
        self.not_stisla_timestamp = None
        self.not_stisla_message_id = None
        if use_not_stisla:
            try:
                from .not_stisla_bindings import (
                    NotStislaSearchEngine,
                    not_stisla_available,
                    NOT_STISLA_WORKLOAD_TELEMETRY,
                    NOT_STISLA_WORKLOAD_IDS,
                )
                if not_stisla_available():
                    self.not_stisla_timestamp = NotStislaSearchEngine(NOT_STISLA_WORKLOAD_TELEMETRY)
                    self.not_stisla_message_id = NotStislaSearchEngine(NOT_STISLA_WORKLOAD_IDS)
                    logger.info("NOT_STISLA engines initialized for hybrid search")
            except ImportError:
                logger.warning("NOT_STISLA not available for hybrid search")

    def search(
        self,
        query: str,
        limit: int = 20,
        search_type: SearchType = SearchType.HYBRID,
        filter_channel: Optional[int] = None,
        filter_user: Optional[int] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> List[SearchResult]:
        """
        Enhanced hybrid search with NOT_STISLA + QIHSE + FTS5.

        Args:
            query: Search query (handles keyword, semantic, timestamp, ID)
            limit: Max results
            search_type: KEYWORD, SEMANTIC, or HYBRID
            filter_channel: Filter by channel
            filter_user: Filter by user
            date_from: Start date for temporal filtering
            date_to: End date for temporal filtering

        Returns:
            Ranked list of SearchResult objects with algorithm metadata
        """
        # Check cache first
        if self.cache:
            cache_key_params = {
                'query': query,
                'search_type': search_type.value if isinstance(search_type, SearchType) else search_type,
                'limit': limit,
                'filter_channel': filter_channel,
                'filter_user': filter_user,
                'date_from': date_from.isoformat() if date_from else None,
                'date_to': date_to.isoformat() if date_to else None,
            }
            cached_results = self.cache.get_cached_search_result(
                query, cache_key_params['search_type'], **{k: v for k, v in cache_key_params.items() if k not in ['query', 'search_type']}
            )
            if cached_results:
                logger.debug("Cache hit for search query")
                return cached_results
        
        results = {}

        # 1. NOT_STISLA for structured data (timestamps, IDs)
        if (date_from or date_to) and self.not_stisla_timestamp:
            try:
                from ..db import SpectraDB
                if isinstance(self.fts5.db, SpectraDB):
                    start_ts = int(date_from.timestamp()) if date_from else None
                    end_ts = int(date_to.timestamp()) if date_to else None
                    
                    if start_ts and end_ts:
                        message_ids = self.fts5.db.find_messages_by_timestamp_range(
                            start_ts, end_ts, filter_channel
                        )
                        
                        # Get message data and add to results
                        for msg_id in message_ids[:limit * 2]:
                            msg_data = self.fts5.db.find_message_by_id_fast(msg_id, filter_channel)
                            if msg_data:
                                results[msg_id] = {
                                    "message_id": msg_data['id'],
                                    "channel_id": filter_channel,
                                    "user_id": msg_data.get('user_id'),
                                    "content": msg_data.get('content', ''),
                                    "date": msg_data['date'],
                                    "not_stisla_score": 1.0,  # Perfect match for temporal
                                }
            except Exception as e:
                logger.debug(f"NOT_STISLA temporal search failed: {e}")

        # Message ID lookup with NOT_STISLA
        if query.isdigit() and self.not_stisla_message_id:
            try:
                from ..db import SpectraDB
                if isinstance(self.fts5.db, SpectraDB):
                    msg_id = int(query)
                    msg_data = self.fts5.db.find_message_by_id_fast(msg_id, filter_channel)
                    if msg_data:
                        results[msg_id] = {
                            "message_id": msg_data['id'],
                            "channel_id": filter_channel,
                            "user_id": msg_data.get('user_id'),
                            "content": msg_data.get('content', ''),
                            "date": msg_data['date'],
                            "not_stisla_score": 1.0,
                        }
            except Exception as e:
                logger.debug(f"NOT_STISLA ID search failed: {e}")

        # 2. FTS5 keyword search
        if search_type in (SearchType.KEYWORD, SearchType.HYBRID):
            fts5_results = self.fts5.search_messages(
                query,
                limit=limit * 2,
                filter_channel=filter_channel,
                filter_user=filter_user,
            )

            for row in fts5_results:
                msg_id = row[0]
                if msg_id in results:
                    results[msg_id]["keyword_score"] = abs(row[6])
                else:
                    results[msg_id] = {
                        "message_id": row[0],
                        "channel_id": row[1],
                        "user_id": row[2],
                        "content": row[3],
                        "date": row[4],
                        "type": row[5],
                        "keyword_score": abs(row[6]),
                    }

        # 3. QIHSE/Qdrant semantic search
        if search_type in (SearchType.SEMANTIC, SearchType.HYBRID):
            vector_results = self.vector.search_semantic(
                query,
                limit=limit * 2,
                filter_channel=filter_channel,
                filter_user=filter_user,
                use_qihse=True,  # Use QIHSE acceleration
            )

            for result in vector_results:
                msg_id = result["message_id"]
                if msg_id in results:
                    results[msg_id]["qihse_score"] = result["relevance_score"]
                else:
                    results[msg_id] = result.copy()
                    results[msg_id]["qihse_score"] = result["relevance_score"]

        # Combine and rank results with intelligent weighting
        combined = []
        for msg_id, data in results.items():
            # Normalize scores
            not_stisla_score = data.get("not_stisla_score", 0) * 0.2
            keyword_score = data.get("keyword_score", 0) / 100.0 * 0.3
            qihse_score = data.get("qihse_score", 0) * 0.5

            # Combined relevance score
            combined_score = not_stisla_score + keyword_score + qihse_score

            combined.append(SearchResult(
                message_id=data["message_id"],
                channel_id=data.get("channel_id"),
                user_id=data.get("user_id"),
                content=data.get("content", ""),
                date=datetime.fromisoformat(data["date"]) if isinstance(data["date"], str) else data["date"],
                relevance_score=combined_score,
                match_type=search_type,
                metadata={
                    "not_stisla_score": not_stisla_score,
                    "keyword_score": keyword_score,
                    "qihse_score": qihse_score,
                    "algorithms": [
                        "not_stisla" if data.get("not_stisla_score") else None,
                        "fts5" if data.get("keyword_score") else None,
                        "qihse" if data.get("qihse_score") else None,
                    ],
                },
            ))

        # Sort by combined relevance and return top results
        combined.sort(key=lambda x: x.relevance_score, reverse=True)
        final_results = combined[:limit]
        
        # Cache results
        if self.cache:
            cache_key_params = {
                'query': query,
                'search_type': search_type.value if isinstance(search_type, SearchType) else search_type,
                'limit': limit,
                'filter_channel': filter_channel,
                'filter_user': filter_user,
                'date_from': date_from.isoformat() if date_from else None,
                'date_to': date_to.isoformat() if date_to else None,
            }
            self.cache.cache_search_result(
                query, cache_key_params['search_type'], final_results,
                ttl=1800,  # 30 minutes
                **{k: v for k, v in cache_key_params.items() if k not in ['query', 'search_type']}
            )
        
        return final_results

    def search_batch(
        self,
        queries: List[str],
        limit_per_query: int = 10,
        search_type: SearchType = SearchType.HYBRID,
        filter_channel: Optional[int] = None,
        filter_user: Optional[int] = None,
    ) -> Dict[str, List[SearchResult]]:
        """
        Batch search using NOT_STISLA parallel search for timestamp queries
        and QIHSE batch search for semantic queries.
        
        Args:
            queries: List of search queries
            limit_per_query: Max results per query
            search_type: Search type
            filter_channel: Channel filter
            filter_user: User filter
        
        Returns:
            Dict mapping query -> list of SearchResult objects
        """
        results = {}
        
        # Separate queries by type
        timestamp_queries = []
        semantic_queries = []
        keyword_queries = []
        
        for query in queries:
            # Detect query type
            if query.isdigit() or 'date' in query.lower() or 'timestamp' in query.lower():
                timestamp_queries.append(query)
            elif any(word in query.lower() for word in ['similar', 'related', 'like', 'semantic']):
                semantic_queries.append(query)
            else:
                keyword_queries.append(query)
        
        # Process timestamp queries with NOT_STISLA parallel search
        if timestamp_queries and self.not_stisla_timestamp:
            try:
                from ..db import SpectraDB
                if isinstance(self.fts5.db, SpectraDB):
                    # Get sorted timestamps
                    query_sql = "SELECT id, date FROM messages ORDER BY date"
                    if filter_channel:
                        query_sql = "SELECT id, date FROM messages WHERE channel_id = ? ORDER BY date"
                    
                    rows = self.fts5.db.cur.execute(
                        query_sql, (filter_channel,) if filter_channel else ()
                    ).fetchall()
                    
                    timestamps = []
                    message_ids = []
                    for row_id, date_str in rows:
                        try:
                            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            timestamps.append(int(dt.timestamp()))
                            message_ids.append(row_id)
                        except:
                            continue
                    
                    # Use NOT_STISLA batch parallel search
                    for query in timestamp_queries:
                        try:
                            if query.isdigit():
                                target = int(query)
                            else:
                                # Parse timestamp from query string
                                try:
                                    dt = datetime.fromisoformat(query.replace('Z', '+00:00'))
                                    target = int(dt.timestamp())
                                except (ValueError, AttributeError):
                                    target = int(datetime.now().timestamp())
                            
                            # Use parallel batch search
                            batch_results = self.not_stisla_timestamp.search_parallel(
                                timestamps, [target], num_threads=0
                            )
                            
                            query_results = []
                            for idx in batch_results:
                                if idx is not None and idx < len(message_ids):
                                    msg_id = message_ids[idx]
                                    msg_data = self.fts5.db.find_message_by_id_fast(msg_id, filter_channel)
                                    if msg_data:
                                        query_results.append(SearchResult(
                                            message_id=msg_id,
                                            channel_id=filter_channel,
                                            user_id=msg_data.get('user_id'),
                                            content=msg_data.get('content', ''),
                                            date=datetime.fromisoformat(msg_data['date']) if isinstance(msg_data['date'], str) else msg_data['date'],
                                            relevance_score=1.0,
                                            match_type=SearchType.KEYWORD,
                                            metadata={'algorithm': 'not_stisla_batch'},
                                        ))
                            
                            results[query] = query_results[:limit_per_query]
                        except Exception as e:
                            logger.debug(f"NOT_STISLA batch search failed for {query}: {e}")
                            results[query] = []
            except Exception as e:
                logger.warning(f"NOT_STISLA batch processing failed: {e}")
        
        # Process semantic queries with QIHSE batch search
        if semantic_queries:
            try:
                # Use QIHSE vector store for batch search
                # Batch search processes queries individually
                # QIHSEVectorStore supports batch operations via batch_search_vectors when available
                for query in semantic_queries:
                    query_results = self.vector.search_semantic(
                        query,
                        limit=limit_per_query,
                        filter_channel=filter_channel,
                        filter_user=filter_user,
                    )
                    
                    # Convert to SearchResult format
                    formatted_results = []
                    for result in query_results:
                        formatted_results.append(SearchResult(
                            message_id=result.get("message_id"),
                            channel_id=result.get("channel_id"),
                            user_id=result.get("user_id"),
                            content=result.get("content", ""),
                            date=datetime.fromisoformat(result.get("date", "")) if isinstance(result.get("date"), str) else datetime.now(),
                            relevance_score=result.get("relevance_score", 0.0),
                            match_type=SearchType.SEMANTIC,
                            metadata={'algorithm': 'qihse'},
                        ))
                    
                    results[query] = formatted_results
            except Exception as e:
                logger.warning(f"QIHSE batch processing failed: {e}")
        
        # Process keyword queries normally
        for query in keyword_queries:
            results[query] = self.search(query, limit_per_query, search_type, filter_channel, filter_user)
        
        return results
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get search engine statistics."""
        stats = {
            "fts5": self.fts5.get_statistics(),
            "vector": self.vector.get_statistics(),
        }
        
        if self.not_stisla_timestamp:
            stats["not_stisla_timestamp"] = self.not_stisla_timestamp.get_stats()
        if self.not_stisla_message_id:
            stats["not_stisla_message_id"] = self.not_stisla_message_id.get_stats()
        
        return stats
