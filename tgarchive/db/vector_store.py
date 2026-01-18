"""
Vector Database Integration for SPECTRA

Provides high-dimensional vector storage and similarity search using QIHSE as primary backend.
Operates alongside SQLite for hybrid query capabilities.

Features:
- Semantic message search (384-2048D embeddings)
- Actor similarity detection
- Behavioral clustering
- Anomaly detection
- Quantum-inspired search acceleration

Author: SPECTRA Intelligence System
"""

import os
import logging
import sqlite3
import pickle
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)

# Try to import QIHSE (primary backend)
try:
    from ..search.qihse_bindings import (
        QihseSearchEngine,
        qihse_available,
        QIHSE_TYPE_DOUBLE,
    )
    from ..search.qihse_config import (
        create_qihse_config,
        configure_qihse_for_semantic_search,
    )
    QIHSE_AVAILABLE = True
except ImportError:
    QIHSE_AVAILABLE = False
    logger.warning("QIHSE not available. Install QIHSE library.")

# Try to import Qdrant (optional fallback)
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
    logger.debug("Qdrant not available (optional fallback)")

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
    backend: str = "qihse"  # "qihse" (primary), "qdrant", "chromadb", or "numpy"
    path: str = "./data/vector_store"
    collection_name: str = "messages"
    vector_size: int = 384  # Dimension of embeddings
    distance_metric: str = "cosine"  # "cosine", "euclidean", or "dot"
    on_disk: bool = True  # Store vectors on disk (vs memory)
    quantization: Optional[str] = None  # "scalar", "product", or None
    confidence_threshold: float = 0.95  # QIHSE confidence threshold


class QIHSEVectorStore:
    """
    QIHSE-based vector storage (primary backend).
    
    Stores vectors directly using SQLite for persistence and QIHSE for quantum-inspired search.
    Replaces Qdrant as the primary vector storage backend.
    """

    def __init__(self, config: VectorStoreConfig):
        if not QIHSE_AVAILABLE or not qihse_available():
            raise ImportError("QIHSE not available. Install QIHSE library.")

        self.config = config
        self.db_path = Path(config.path) / f"{config.collection_name}.db"
        self.vectors_path = Path(config.path) / f"{config.collection_name}_vectors.npy"
        
        # Create directory if needed
        Path(config.path).mkdir(parents=True, exist_ok=True)
        
        # Initialize QIHSE search engine
        self.qihse_engine = QihseSearchEngine(QIHSE_TYPE_DOUBLE, 10000)
        configure_qihse_for_semantic_search(
            self.qihse_engine.config, config.vector_size, config.confidence_threshold
        )
        
        # Initialize SQLite for metadata
        self._init_database()
        
        # Load vectors into memory (for QIHSE search)
        self._load_vectors()

    def _init_database(self):
        """Initialize SQLite database for vector metadata."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vectors (
                id TEXT PRIMARY KEY,
                message_id INTEGER,
                metadata TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_id ON vectors(message_id)
        """)
        conn.commit()
        conn.close()

    def _load_vectors(self):
        """Load vectors from disk into memory."""
        if self.vectors_path.exists():
            try:
                data = np.load(self.vectors_path, allow_pickle=True).item()
                self.vectors = data.get("vectors", {})
                self.vector_ids = data.get("ids", [])
                logger.info(f"Loaded {len(self.vectors)} vectors from {self.vectors_path}")
            except Exception as e:
                logger.warning(f"Failed to load vectors: {e}")
                self.vectors = {}
                self.vector_ids = []
        else:
            self.vectors = {}
            self.vector_ids = []

    def _save_vectors(self):
        """Save vectors to disk."""
        try:
            data = {
                "vectors": self.vectors,
                "ids": self.vector_ids
            }
            np.save(self.vectors_path, data, allow_pickle=True)
        except Exception as e:
            logger.error(f"Failed to save vectors: {e}")

    def upsert(self, id: str, vector: List[float], payload: Dict[str, Any]):
        """Insert or update a vector with metadata."""
        import json
        
        # Store vector in memory
        self.vectors[id] = np.array(vector, dtype=np.float64)
        if id not in self.vector_ids:
            self.vector_ids.append(id)
        
        # Store metadata in SQLite
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT OR REPLACE INTO vectors (id, message_id, metadata, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            id,
            payload.get("message_id"),
            json.dumps(payload),
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()
        
        # Save vectors to disk periodically (could be optimized with batching)
        if len(self.vectors) % 100 == 0:
            self._save_vectors()

    def upsert_batch(self, points: List[Tuple[str, List[float], Dict[str, Any]]]):
        """Batch insert/update vectors."""
        import json
        
        conn = sqlite3.connect(self.db_path)
        for id, vector, payload in points:
            # Store vector in memory
            self.vectors[id] = np.array(vector, dtype=np.float64)
            if id not in self.vector_ids:
                self.vector_ids.append(id)
            
            # Store metadata
            conn.execute("""
                INSERT OR REPLACE INTO vectors (id, message_id, metadata, created_at)
                VALUES (?, ?, ?, ?)
            """, (
                id,
                payload.get("message_id"),
                json.dumps(payload),
                datetime.now().isoformat()
            ))
        
        conn.commit()
        conn.close()
        self._save_vectors()

    def search(
        self,
        vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None
    ) -> List[SearchResult]:
        """
        Search for similar vectors using QIHSE.
        
        Args:
            vector: Query vector
            limit: Max results to return
            filters: Metadata filters (e.g., {"threat_score": {"gte": 7.0}})
            score_threshold: Minimum similarity score
            
        Returns:
            List of SearchResult objects
        """
        if not self.vectors:
            return []
        
        # Apply filters to get candidate IDs
        candidate_ids = self._filter_ids(filters) if filters else list(self.vector_ids)
        
        if not candidate_ids:
            return []
        
        # Get candidate vectors in order
        candidate_vectors_list = []
        valid_ids = []
        for vector_id in candidate_ids:
            if vector_id in self.vectors:
                candidate_vectors_list.append(self.vectors[vector_id])
                valid_ids.append(vector_id)
        
        if not candidate_vectors_list:
            return []
        
        # Convert to numpy array
        candidate_vectors = np.array(candidate_vectors_list, dtype=np.float64)
        query_vector = np.array(vector, dtype=np.float64)
        
        # Use QIHSE for search
        try:
            threshold = score_threshold or self.config.confidence_threshold
            results = self.qihse_engine.search_vectors(
                candidate_vectors,
                query_vector,
                None,
                threshold
            )
        except Exception as e:
            logger.error(f"QIHSE search failed: {e}")
            # Fallback to cosine similarity
            return self._fallback_search(vector, valid_ids, limit, score_threshold)
        
        # Format results
        search_results = []
        for idx, confidence in results:
            if idx >= len(valid_ids):
                continue
            
            vector_id = valid_ids[idx]
            if score_threshold and confidence < score_threshold:
                continue
            
            # Get metadata
            payload = self._get_metadata(vector_id)
            
            search_results.append(SearchResult(
                id=vector_id,
                score=float(confidence),
                payload=payload
            ))
        
        # Sort by score and limit
        search_results.sort(key=lambda x: x.score, reverse=True)
        return search_results[:limit]

    def _filter_ids(self, filters: Dict[str, Any]) -> List[str]:
        """Filter vector IDs by metadata."""
        import json
        
        conn = sqlite3.connect(self.db_path)
        query = "SELECT id FROM vectors WHERE 1=1"
        params = []
        
        for key, value in filters.items():
            if isinstance(value, dict):
                # Range filter
                if "gte" in value:
                    query += f" AND json_extract(metadata, '$.{key}') >= ?"
                    params.append(value["gte"])
                if "lte" in value:
                    query += f" AND json_extract(metadata, '$.{key}') <= ?"
                    params.append(value["lte"])
            else:
                # Exact match
                query += f" AND json_extract(metadata, '$.{key}') = ?"
                params.append(value)
        
        cursor = conn.execute(query, params)
        ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        return ids

    def _get_metadata(self, vector_id: str) -> Dict[str, Any]:
        """Get metadata for a vector ID."""
        import json
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT metadata FROM vectors WHERE id = ?", (vector_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return json.loads(row[0])
        return {}

    def _fallback_search(
        self,
        vector: List[float],
        candidate_ids: List[str],
        limit: int,
        score_threshold: Optional[float]
    ) -> List[SearchResult]:
        """Fallback to cosine similarity if QIHSE fails."""
        query_vec = np.array(vector, dtype=np.float64)
        candidate_vectors = np.array([self.vectors[id] for id in candidate_ids], dtype=np.float64)
        
        # Cosine similarity
        query_norm = np.linalg.norm(query_vec)
        candidate_norms = np.linalg.norm(candidate_vectors, axis=1)
        similarities = np.dot(candidate_vectors, query_vec) / (candidate_norms * query_norm)
        
        # Sort and filter
        indices = np.argsort(similarities)[::-1][:limit]
        
        results = []
        for idx in indices:
            score = float(similarities[idx])
            if score_threshold and score < score_threshold:
                continue
            
            vector_id = candidate_ids[idx]
            payload = self._get_metadata(vector_id)
            
            results.append(SearchResult(
                id=vector_id,
                score=score,
                payload=payload
            ))
        
        return results

    def delete(self, id: str):
        """Delete a vector by ID."""
        # Remove from memory
        self.vectors.pop(id, None)
        if id in self.vector_ids:
            self.vector_ids.remove(id)
        
        # Remove from SQLite
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM vectors WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        
        self._save_vectors()

    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM vectors")
        count = cursor.fetchone()[0]
        conn.close()
        
        return {
            "points_count": count,
            "vector_size": self.config.vector_size,
            "backend": "qihse",
            "memory_vectors": len(self.vectors)
        }


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
    1. QIHSE (primary, preferred)
    2. Qdrant (optional fallback)
    3. ChromaDB (optional fallback)
    4. Numpy (testing only)
    """

    def __init__(self, config: Optional[VectorStoreConfig] = None):
        self.config = config or VectorStoreConfig()

        # Select backend based on config
        if self.config.backend == "qihse" and QIHSE_AVAILABLE and qihse_available():
            try:
                self.store = QIHSEVectorStore(self.config)
                logger.info("Using QIHSE vector store (primary backend)")
            except Exception as e:
                logger.warning(f"QIHSE initialization failed: {e}, trying fallback...")
                self._select_fallback()
        elif self.config.backend == "qdrant" and QDRANT_AVAILABLE:
            self.store = QdrantVectorStore(self.config)
            logger.info("Using Qdrant vector store")
        elif self.config.backend == "chromadb" and CHROMADB_AVAILABLE:
            self.store = ChromaDBVectorStore(self.config)
            logger.info("Using ChromaDB vector store")
        elif self.config.backend == "numpy":
            self.store = NumpyVectorStore(self.config)
            logger.warning("Using Numpy vector store (not scalable)")
        else:
            # Auto-select fallback (QIHSE first, then Qdrant, then ChromaDB, then Numpy)
            self._select_fallback()

    def _select_fallback(self):
        """Select fallback backend when primary is unavailable."""
        if QIHSE_AVAILABLE and qihse_available():
            try:
                self.store = QIHSEVectorStore(self.config)
                logger.info("Auto-selected QIHSE vector store (primary)")
            except Exception as e:
                logger.warning(f"QIHSE auto-select failed: {e}, trying Qdrant...")
                if QDRANT_AVAILABLE:
                    self.store = QdrantVectorStore(self.config)
                    logger.info("Auto-selected Qdrant vector store (fallback)")
                elif CHROMADB_AVAILABLE:
                    self.store = ChromaDBVectorStore(self.config)
                    logger.info("Auto-selected ChromaDB vector store (fallback)")
                else:
                    self.store = NumpyVectorStore(self.config)
                    logger.warning("No vector DB available, using Numpy fallback")
        elif QDRANT_AVAILABLE:
            self.store = QdrantVectorStore(self.config)
            logger.info("Auto-selected Qdrant vector store (fallback)")
        elif CHROMADB_AVAILABLE:
            self.store = ChromaDBVectorStore(self.config)
            logger.info("Auto-selected ChromaDB vector store (fallback)")
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
        if not self.vectors:
            return []
        
        # Get all vectors for this channel
        channel_vector_ids = []
        channel_vectors_list = []
        
        for vector_id in self.vector_ids:
            metadata = self._get_metadata(vector_id)
            if metadata.get("channel_id") == channel_id and vector_id in self.vectors:
                channel_vector_ids.append(vector_id)
                channel_vectors_list.append(self.vectors[vector_id])
        
        if len(channel_vectors_list) < 2:
            # Need at least 2 messages to compute a profile
            return []
        
        # Compute channel embedding profile (mean/centroid)
        channel_vectors = np.array(channel_vectors_list, dtype=np.float64)
        channel_profile = np.mean(channel_vectors, axis=0)
        channel_profile_norm = np.linalg.norm(channel_profile)
        
        if channel_profile_norm == 0:
            return []
        
        # Compute similarity of each message to channel profile
        anomalies = []
        for i, vector_id in enumerate(channel_vector_ids):
            message_vector = channel_vectors[i]
            message_norm = np.linalg.norm(message_vector)
            
            if message_norm == 0:
                continue
            
            # Cosine similarity to channel profile
            similarity = np.dot(message_vector, channel_profile) / (message_norm * channel_profile_norm)
            
            # Flag as anomaly if similarity is below threshold
            if similarity < threshold:
                metadata = self._get_metadata(vector_id)
                anomalies.append(SearchResult(
                    id=vector_id,
                    score=float(similarity),
                    payload=metadata
                ))
        
        # Sort by similarity (lowest = most anomalous)
        anomalies.sort(key=lambda x: x.score)
        
        return anomalies

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
        backend="qihse",  # Primary: "qihse", fallback: "qdrant", "chromadb", "numpy"
        path="./data/vector_test",
        vector_size=384,
        distance_metric="cosine",
        confidence_threshold=0.95
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
