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


class QdrantVectorManager:
    """
    Manages Qdrant vector database for semantic search.

    Features:
    - Automatic embedding generation using SentenceTransformers
    - Semantic similarity search
    - Metadata filtering
    - Scalable to billions of vectors
    """

    def __init__(
        self,
        qdrant_url: str = "http://localhost:6333",
        collection_name: str = "spectra_messages",
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        """
        Initialize Qdrant vector manager.

        Args:
            qdrant_url: Qdrant server URL
            collection_name: Collection name in Qdrant
            embedding_model: HuggingFace model for embeddings
        """
        from qdrant_client import QdrantClient
        from sentence_transformers import SentenceTransformer

        self.client = QdrantClient(qdrant_url)
        self.model = SentenceTransformer(embedding_model)
        self.collection_name = collection_name
        self.embedding_dim = self.model.get_sentence_embedding_dimension()

        self._initialize_collection()

    def _initialize_collection(self):
        """Create Qdrant collection if it doesn't exist."""
        from qdrant_client.models import Distance, VectorParams

        try:
            # Check if collection exists
            collections = self.client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self.collection_name not in collection_names:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_dim,
                        distance=Distance.COSINE
                    ),
                )
                logger.info(f"✓ Created Qdrant collection: {self.collection_name}")
            else:
                logger.info(f"✓ Using existing Qdrant collection: {self.collection_name}")

        except Exception as e:
            logger.error(f"✗ Qdrant initialization failed: {e}")
            raise

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
    ) -> List[Dict[str, Any]]:
        """
        Semantic search using vector similarity.

        Args:
            query: Natural language search query
            limit: Max results
            filter_channel: Filter by channel
            filter_user: Filter by user
            score_threshold: Minimum similarity score (0-1)

        Returns:
            List of similar messages with scores
        """
        try:
            # Generate query embedding
            query_vector = self.embed_message(query)

            # Build filter
            must_conditions = []
            if filter_channel is not None:
                must_conditions.append({
                    "key": "channel_id",
                    "match": {"value": filter_channel}
                })
            if filter_user is not None:
                must_conditions.append({
                    "key": "user_id",
                    "match": {"value": filter_user}
                })

            filter_obj = None
            if must_conditions:
                filter_obj = {"must": must_conditions}

            # Search Qdrant
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=filter_obj,
                score_threshold=score_threshold,
            )

            # Format results
            search_results = []
            for scored_point in results:
                search_results.append({
                    "message_id": scored_point.payload.get("message_id"),
                    "content": scored_point.payload.get("content"),
                    "channel_id": scored_point.payload.get("channel_id"),
                    "user_id": scored_point.payload.get("user_id"),
                    "date": scored_point.payload.get("date"),
                    "relevance_score": scored_point.score,
                    "match_type": SearchType.SEMANTIC,
                })

            logger.debug(f"Semantic search returned {len(search_results)} results")
            return search_results

        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []

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
    Unified search engine combining FTS5 and Qdrant.

    Strategy:
    1. Execute both FTS5 (keyword) and semantic (vector) searches in parallel
    2. Normalize and combine scores
    3. Rank results by combined relevance
    4. Return unified result set
    """

    def __init__(
        self,
        db_connection,
        qdrant_url: str = "http://localhost:6333",
    ):
        """
        Initialize hybrid search engine.

        Args:
            db_connection: SQLite connection
            qdrant_url: Qdrant server URL
        """
        self.fts5 = SQLiteFTS5IndexManager(db_connection)
        self.vector = QdrantVectorManager(qdrant_url)

    def search(
        self,
        query: str,
        limit: int = 20,
        search_type: SearchType = SearchType.HYBRID,
        filter_channel: Optional[int] = None,
        filter_user: Optional[int] = None,
    ) -> List[SearchResult]:
        """
        Perform hybrid search.

        Args:
            query: Search query (handles both keyword and semantic)
            limit: Max results
            search_type: KEYWORD, SEMANTIC, or HYBRID
            filter_channel: Filter by channel
            filter_user: Filter by user

        Returns:
            Ranked list of SearchResult objects
        """
        results = {}

        if search_type in (SearchType.KEYWORD, SearchType.HYBRID):
            # FTS5 keyword search
            fts5_results = self.fts5.search_messages(
                query,
                limit=limit * 2,  # Get more for ranking
                filter_channel=filter_channel,
                filter_user=filter_user,
            )

            for row in fts5_results:
                msg_id = row[0]
                results[msg_id] = {
                    "message_id": row[0],
                    "channel_id": row[1],
                    "user_id": row[2],
                    "content": row[3],
                    "date": row[4],
                    "type": row[5],
                    "keyword_score": abs(row[6]),  # Normalize BM25 score
                }

        if search_type in (SearchType.SEMANTIC, SearchType.HYBRID):
            # Vector semantic search
            vector_results = self.vector.search_semantic(
                query,
                limit=limit * 2,
                filter_channel=filter_channel,
                filter_user=filter_user,
            )

            for result in vector_results:
                msg_id = result["message_id"]
                if msg_id in results:
                    results[msg_id]["semantic_score"] = result["relevance_score"]
                else:
                    results[msg_id] = result.copy()
                    results[msg_id]["semantic_score"] = result["relevance_score"]

        # Combine and rank results
        combined = []
        for msg_id, data in results.items():
            # Calculate combined relevance
            keyword_score = data.get("keyword_score", 0) / 100.0  # Normalize
            semantic_score = data.get("semantic_score", 0)

            # Weighted combination (favor semantic for this use case)
            combined_score = (keyword_score * 0.3) + (semantic_score * 0.7)

            combined.append(SearchResult(
                message_id=data["message_id"],
                channel_id=data["channel_id"],
                user_id=data.get("user_id"),
                content=data.get("content", ""),
                date=datetime.fromisoformat(data["date"]) if isinstance(data["date"], str) else data["date"],
                relevance_score=combined_score,
                match_type=search_type,
                metadata={
                    "keyword_score": keyword_score,
                    "semantic_score": semantic_score,
                },
            ))

        # Sort by combined relevance and return top results
        combined.sort(key=lambda x: x.relevance_score, reverse=True)
        return combined[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        """Get search engine statistics."""
        return {
            "fts5": self.fts5.get_statistics(),
            "vector": self.vector.get_statistics(),
        }
