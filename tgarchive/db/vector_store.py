"""
Vector Database Integration for SPECTRA

Provides high-dimensional vector storage and similarity search using Qdrant.
Operates alongside SQLite for hybrid query capabilities.

Features:
- Semantic message search (384-2048D embeddings)
- Actor similarity detection
- Behavioral clustering
- Anomaly detection
- Scalable to billions of vectors

Author: SPECTRA Intelligence System
"""

import os
import logging
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)

# Try to import Qdrant (optional dependency)
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        VectorParams, Distance, PointStruct,
        Filter, FieldCondition, Range, MatchValue,
        SearchRequest, CollectionInfo
    )
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    logger.warning("Qdrant not available. Install with: pip install qdrant-client")

# Fallback to ChromaDB if available
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False


@dataclass
class SearchResult:
    """Vector search result."""
    id: str
    score: float
    payload: Dict[str, Any]


@dataclass
class VectorStoreConfig:
    """Configuration for vector store."""
    backend: str = "qdrant"  # "qdrant", "chromadb", or "numpy"
    path: str = "./data/vector_store"
    collection_name: str = "messages"
    vector_size: int = 384  # Dimension of embeddings
    distance_metric: str = "cosine"  # "cosine", "euclidean", or "dot"
    on_disk: bool = True  # Store vectors on disk (vs memory)
    quantization: Optional[str] = None  # "scalar", "product", or None


class QdrantVectorStore:
    """
    Qdrant-based vector storage.

    High-performance vector database with advanced filtering and quantization.
    Recommended for production use.
    """

    def __init__(self, config: VectorStoreConfig):
        if not QDRANT_AVAILABLE:
            raise ImportError("Qdrant not installed. Install with: pip install qdrant-client")

        self.config = config
        self.client = QdrantClient(path=config.path)

        # Create collection if it doesn't exist
        self._ensure_collection()

    def _ensure_collection(self):
        """Create collection if it doesn't exist."""
        try:
            self.client.get_collection(self.config.collection_name)
            logger.info(f"Collection '{self.config.collection_name}' already exists")
        except Exception:
            # Collection doesn't exist, create it
            logger.info(f"Creating collection '{self.config.collection_name}'")

            # Map distance metric
            distance_map = {
                "cosine": Distance.COSINE,
                "euclidean": Distance.EUCLID,
                "dot": Distance.DOT
            }
            distance = distance_map.get(self.config.distance_metric, Distance.COSINE)

            self.client.create_collection(
                collection_name=self.config.collection_name,
                vectors_config=VectorParams(
                    size=self.config.vector_size,
                    distance=distance,
                    on_disk=self.config.on_disk
                )
            )

            logger.info(f"Collection created: {self.config.collection_name}")

    def upsert(self, id: str, vector: List[float], payload: Dict[str, Any]):
        """Insert or update a vector with metadata."""
        point = PointStruct(
            id=id,
            vector=vector,
            payload=payload
        )

        self.client.upsert(
            collection_name=self.config.collection_name,
            points=[point]
        )

    def upsert_batch(self, points: List[Tuple[str, List[float], Dict[str, Any]]]):
        """Batch insert/update vectors."""
        qdrant_points = [
            PointStruct(id=id, vector=vector, payload=payload)
            for id, vector, payload in points
        ]

        self.client.upsert(
            collection_name=self.config.collection_name,
            points=qdrant_points,
            wait=True
        )

    def search(
        self,
        vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None
    ) -> List[SearchResult]:
        """
        Search for similar vectors.

        Args:
            vector: Query vector
            limit: Max results to return
            filters: Metadata filters (e.g., {"threat_score": {"gte": 7.0}})
            score_threshold: Minimum similarity score

        Returns:
            List of SearchResult objects
        """
        # Build filter
        qdrant_filter = self._build_filter(filters) if filters else None

        # Search
        results = self.client.search(
            collection_name=self.config.collection_name,
            query_vector=vector,
            limit=limit,
            query_filter=qdrant_filter,
            score_threshold=score_threshold
        )

        return [
            SearchResult(
                id=str(r.id),
                score=r.score,
                payload=r.payload
            )
            for r in results
        ]

    def _build_filter(self, filters: Dict[str, Any]) -> Filter:
        """Build Qdrant filter from dict."""
        conditions = []

        for field, value in filters.items():
            if isinstance(value, dict):
                # Range filter: {"gte": 7.0, "lte": 10.0}
                if "gte" in value or "lte" in value or "gt" in value or "lt" in value:
                    conditions.append(FieldCondition(
                        key=field,
                        range=Range(
                            gte=value.get("gte"),
                            lte=value.get("lte"),
                            gt=value.get("gt"),
                            lt=value.get("lt")
                        )
                    ))
            else:
                # Exact match
                conditions.append(FieldCondition(
                    key=field,
                    match=MatchValue(value=value)
                ))

        return Filter(must=conditions) if conditions else None

    def delete(self, id: str):
        """Delete a vector by ID."""
        self.client.delete(
            collection_name=self.config.collection_name,
            points_selector=[id]
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        info: CollectionInfo = self.client.get_collection(self.config.collection_name)
        return {
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
            "status": info.status,
            "vector_size": self.config.vector_size
        }


class ChromaDBVectorStore:
    """
    ChromaDB-based vector storage (fallback option).

    Simpler than Qdrant but less scalable. Good for development.
    """

    def __init__(self, config: VectorStoreConfig):
        if not CHROMADB_AVAILABLE:
            raise ImportError("ChromaDB not installed. Install with: pip install chromadb")

        self.config = config
        self.client = chromadb.PersistentClient(path=config.path)
        self.collection = self.client.get_or_create_collection(
            name=config.collection_name,
            metadata={"hnsw:space": config.distance_metric}
        )

    def upsert(self, id: str, vector: List[float], payload: Dict[str, Any]):
        """Insert or update a vector with metadata."""
        self.collection.upsert(
            ids=[id],
            embeddings=[vector],
            metadatas=[payload]
        )

    def upsert_batch(self, points: List[Tuple[str, List[float], Dict[str, Any]]]):
        """Batch insert/update vectors."""
        ids, vectors, payloads = zip(*points)
        self.collection.upsert(
            ids=list(ids),
            embeddings=list(vectors),
            metadatas=list(payloads)
        )

    def search(
        self,
        vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None
    ) -> List[SearchResult]:
        """Search for similar vectors."""
        # ChromaDB filtering is more limited
        where = {}
        if filters:
            for k, v in filters.items():
                if isinstance(v, dict) and "gte" in v:
                    where[k] = {"$gte": v["gte"]}
                else:
                    where[k] = v

        results = self.collection.query(
            query_embeddings=[vector],
            n_results=limit,
            where=where if where else None
        )

        if not results or not results["ids"]:
            return []

        search_results = []
        for i in range(len(results["ids"][0])):
            score = 1.0 - results["distances"][0][i]  # Convert distance to similarity
            if score_threshold and score < score_threshold:
                continue

            search_results.append(SearchResult(
                id=results["ids"][0][i],
                score=score,
                payload=results["metadatas"][0][i] if results["metadatas"] else {}
            ))

        return search_results

    def delete(self, id: str):
        """Delete a vector by ID."""
        self.collection.delete(ids=[id])

    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        return {
            "points_count": self.collection.count(),
            "vector_size": self.config.vector_size
        }


class NumpyVectorStore:
    """
    In-memory numpy-based vector storage (fallback).

    Simple but not scalable. For small datasets or testing only.
    """

    def __init__(self, config: VectorStoreConfig):
        self.config = config
        self.vectors: Dict[str, np.ndarray] = {}
        self.payloads: Dict[str, Dict[str, Any]] = {}

    def upsert(self, id: str, vector: List[float], payload: Dict[str, Any]):
        """Insert or update a vector with metadata."""
        self.vectors[id] = np.array(vector, dtype=np.float32)
        self.payloads[id] = payload

    def upsert_batch(self, points: List[Tuple[str, List[float], Dict[str, Any]]]):
        """Batch insert/update vectors."""
        for id, vector, payload in points:
            self.upsert(id, vector, payload)

    def search(
        self,
        vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None
    ) -> List[SearchResult]:
        """Search for similar vectors (brute force)."""
        if not self.vectors:
            return []

        query_vec = np.array(vector, dtype=np.float32)

        # Apply filters
        candidate_ids = list(self.vectors.keys())
        if filters:
            candidate_ids = [
                id for id in candidate_ids
                if self._matches_filter(self.payloads[id], filters)
            ]

        if not candidate_ids:
            return []

        # Compute similarities
        candidate_vectors = np.array([self.vectors[id] for id in candidate_ids])

        if self.config.distance_metric == "cosine":
            # Cosine similarity
            query_norm = np.linalg.norm(query_vec)
            candidate_norms = np.linalg.norm(candidate_vectors, axis=1)
            similarities = np.dot(candidate_vectors, query_vec) / (candidate_norms * query_norm)
        elif self.config.distance_metric == "dot":
            similarities = np.dot(candidate_vectors, query_vec)
        else:  # euclidean
            distances = np.linalg.norm(candidate_vectors - query_vec, axis=1)
            similarities = 1.0 / (1.0 + distances)

        # Sort and filter by threshold
        indices = np.argsort(similarities)[::-1][:limit]

        results = []
        for idx in indices:
            score = float(similarities[idx])
            if score_threshold and score < score_threshold:
                continue

            results.append(SearchResult(
                id=candidate_ids[idx],
                score=score,
                payload=self.payloads[candidate_ids[idx]]
            ))

        return results

    def _matches_filter(self, payload: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if payload matches filters."""
        for key, value in filters.items():
            if key not in payload:
                return False

            if isinstance(value, dict):
                # Range filter
                if "gte" in value and payload[key] < value["gte"]:
                    return False
                if "lte" in value and payload[key] > value["lte"]:
                    return False
            else:
                # Exact match
                if payload[key] != value:
                    return False

        return True

    def delete(self, id: str):
        """Delete a vector by ID."""
        self.vectors.pop(id, None)
        self.payloads.pop(id, None)

    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        return {
            "points_count": len(self.vectors),
            "vector_size": self.config.vector_size,
            "memory_mb": sum(v.nbytes for v in self.vectors.values()) / 1024 / 1024
        }


class VectorStoreManager:
    """
    Unified interface for vector storage.

    Automatically selects best available backend:
    1. Qdrant (preferred)
    2. ChromaDB (fallback)
    3. Numpy (testing only)
    """

    def __init__(self, config: Optional[VectorStoreConfig] = None):
        self.config = config or VectorStoreConfig()

        # Select backend
        if self.config.backend == "qdrant" and QDRANT_AVAILABLE:
            self.store = QdrantVectorStore(self.config)
            logger.info("Using Qdrant vector store")
        elif self.config.backend == "chromadb" and CHROMADB_AVAILABLE:
            self.store = ChromaDBVectorStore(self.config)
            logger.info("Using ChromaDB vector store")
        elif self.config.backend == "numpy":
            self.store = NumpyVectorStore(self.config)
            logger.warning("Using Numpy vector store (not scalable)")
        else:
            # Auto-select fallback
            if QDRANT_AVAILABLE:
                self.store = QdrantVectorStore(self.config)
                logger.info("Auto-selected Qdrant vector store")
            elif CHROMADB_AVAILABLE:
                self.store = ChromaDBVectorStore(self.config)
                logger.info("Auto-selected ChromaDB vector store")
            else:
                self.store = NumpyVectorStore(self.config)
                logger.warning("No vector DB available, using Numpy fallback")

    def index_message(
        self,
        message_id: int,
        embedding: np.ndarray,
        metadata: Dict[str, Any]
    ):
        """
        Index a message embedding with metadata.

        Args:
            message_id: Unique message ID (references SQLite)
            embedding: Vector embedding (numpy array)
            metadata: Metadata to store (user_id, threat_score, date, etc.)
        """
        id = f"msg_{message_id}"
        vector = embedding.tolist() if isinstance(embedding, np.ndarray) else embedding

        # Add message_id to metadata for back-reference
        payload = {
            "message_id": message_id,
            **metadata
        }

        self.store.upsert(id, vector, payload)

    def index_messages_batch(
        self,
        message_data: List[Tuple[int, np.ndarray, Dict[str, Any]]]
    ):
        """Batch index multiple messages."""
        points = [
            (f"msg_{msg_id}", emb.tolist() if isinstance(emb, np.ndarray) else emb, {"message_id": msg_id, **meta})
            for msg_id, emb, meta in message_data
        ]

        self.store.upsert_batch(points)

    def semantic_search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        min_score: Optional[float] = None
    ) -> List[SearchResult]:
        """
        Search for semantically similar messages.

        Args:
            query_embedding: Query vector
            top_k: Number of results to return
            filters: Metadata filters (e.g., {"threat_score": {"gte": 7.0}})
            min_score: Minimum similarity score (0-1)

        Returns:
            List of search results with scores and metadata
        """
        vector = query_embedding.tolist() if isinstance(query_embedding, np.ndarray) else query_embedding

        return self.store.search(
            vector=vector,
            limit=top_k,
            filters=filters,
            score_threshold=min_score
        )

    def find_similar_actors(
        self,
        actor_id: int,
        actor_embedding: np.ndarray,
        top_k: int = 10,
        exclude_same_actor: bool = True
    ) -> List[SearchResult]:
        """
        Find actors with similar behavioral patterns.

        Args:
            actor_id: User ID to find similar actors for
            actor_embedding: Aggregated embedding representing actor's behavior
            top_k: Number of similar actors to return
            exclude_same_actor: Filter out messages from the same actor

        Returns:
            List of similar actors
        """
        results = self.semantic_search(
            query_embedding=actor_embedding,
            top_k=top_k * 2  # Get more to filter
        )

        if exclude_same_actor:
            results = [r for r in results if r.payload.get("user_id") != actor_id]

        return results[:top_k]

    def detect_anomalies(
        self,
        channel_id: int,
        threshold: float = 0.5
    ) -> List[SearchResult]:
        """
        Detect anomalous messages in a channel.

        Messages with low similarity to channel norm are flagged as anomalies.

        Args:
            channel_id: Channel to analyze
            threshold: Similarity threshold (lower = more anomalous)

        Returns:
            List of anomalous messages
        """
        # This would require computing channel embedding profile
        # For now, return placeholder
        logger.warning("Anomaly detection not fully implemented yet")
        return []

    def delete_message(self, message_id: int):
        """Remove a message from the vector store."""
        self.store.delete(f"msg_{message_id}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get vector store statistics."""
        return self.store.get_stats()


# Example usage
if __name__ == "__main__":
    # Initialize vector store
    config = VectorStoreConfig(
        backend="qdrant",  # or "chromadb", "numpy"
        path="./data/vector_test",
        vector_size=384,
        distance_metric="cosine"
    )

    store = VectorStoreManager(config)

    # Index some example messages
    example_embeddings = np.random.rand(5, 384).astype(np.float32)

    for i, emb in enumerate(example_embeddings):
        store.index_message(
            message_id=i + 1,
            embedding=emb,
            metadata={
                "user_id": 1000 + (i % 3),
                "threat_score": 5.0 + i,
                "date": "2024-06-15",
                "channel_id": 5000
            }
        )

    print("✓ Indexed 5 messages")

    # Search for similar messages
    query = np.random.rand(384).astype(np.float32)
    results = store.semantic_search(
        query_embedding=query,
        top_k=3,
        filters={"threat_score": {"gte": 7.0}}
    )

    print(f"\n✓ Found {len(results)} similar high-threat messages:")
    for r in results:
        print(f"  - Message {r.payload['message_id']}: score={r.score:.3f}, "
              f"threat={r.payload['threat_score']}")

    # Statistics
    stats = store.get_statistics()
    print(f"\n✓ Vector store stats: {stats}")
