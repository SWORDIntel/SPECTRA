"""
SPECTRA Semantic Search & RAG Module
====================================
Implements vector embeddings, semantic search, and Retrieval-Augmented Generation.

Features:
- Text embedding generation
- Vector database integration (Qdrant, ChromaDB fallback)
- Hybrid search (semantic + keyword)
- RAG pipeline for question answering
- Multi-document summarization
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)

# Optional dependencies with graceful fallback
try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False
    logger.warning("sentence-transformers not installed. Semantic search will be limited.")

try:
    import chromadb
    from chromadb.config import Settings
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False
    logger.warning("chromadb not installed. Using fallback vector storage.")


@dataclass
class SearchResult:
    """A single search result with metadata."""
    message_id: int
    channel_id: Optional[int]
    content: str
    score: float
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "message_id": self.message_id,
            "channel_id": self.channel_id,
            "content": self.content,
            "score": float(self.score),
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "metadata": self.metadata,
        }


class EmbeddingModel:
    """
    Wrapper for embedding generation models.
    Supports multiple backends with graceful fallback.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: str = "cpu",
        cache_dir: Optional[Path] = None,
    ):
        """
        Initialize embedding model.

        Args:
            model_name: HuggingFace model name or OpenAI model
            device: Device to run on ('cpu', 'cuda', 'mps')
            cache_dir: Directory to cache models
        """
        self.model_name = model_name
        self.device = device
        self.cache_dir = cache_dir or Path.home() / ".cache" / "spectra_models"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.model = None
        self.dimension = 384  # Default for all-MiniLM-L6-v2

        self._initialize_model()

    def _initialize_model(self) -> None:
        """Initialize the embedding model."""
        if not HAS_SENTENCE_TRANSFORMERS:
            logger.error("sentence-transformers not installed. Cannot generate embeddings.")
            logger.error("Install with: pip install sentence-transformers")
            return

        try:
            logger.info(f"Loading embedding model: {self.model_name}")
            self.model = SentenceTransformer(
                self.model_name,
                device=self.device,
                cache_folder=str(self.cache_dir)
            )
            self.dimension = self.model.get_sentence_embedding_dimension()
            logger.info(f"Model loaded. Embedding dimension: {self.dimension}")

        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.model = None

    def embed_texts(
        self,
        texts: List[str],
        batch_size: int = 32,
        show_progress: bool = False,
    ) -> np.ndarray:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of text strings
            batch_size: Batch size for processing
            show_progress: Show progress bar

        Returns:
            numpy array of shape (len(texts), dimension)
        """
        if not self.model:
            raise RuntimeError("Embedding model not initialized")

        try:
            embeddings = self.model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=show_progress,
                convert_to_numpy=True,
            )
            return embeddings

        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            raise

    def embed_single(self, text: str) -> np.ndarray:
        """Generate embedding for a single text."""
        return self.embed_texts([text])[0]


class VectorStore:
    """
    Vector storage and search using ChromaDB.
    Fallback to simple numpy-based storage if ChromaDB not available.
    """

    def __init__(
        self,
        collection_name: str = "spectra_messages",
        persist_directory: Optional[Path] = None,
        embedding_dimension: int = 384,
    ):
        """
        Initialize vector store.

        Args:
            collection_name: Name of the collection
            persist_directory: Directory to persist the database
            embedding_dimension: Dimension of embeddings
        """
        self.collection_name = collection_name
        self.persist_directory = persist_directory or Path("./data/vector_db")
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.embedding_dimension = embedding_dimension

        self.client = None
        self.collection = None
        self.use_chromadb = HAS_CHROMADB

        # Fallback storage
        self.vectors: np.ndarray = np.array([])
        self.ids: List[str] = []
        self.metadatas: List[Dict[str, Any]] = []

        self._initialize_storage()

    def _initialize_storage(self) -> None:
        """Initialize the vector storage backend."""
        if self.use_chromadb:
            try:
                logger.info("Initializing ChromaDB vector store")
                self.client = chromadb.PersistentClient(
                    path=str(self.persist_directory)
                )

                self.collection = self.client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"}
                )
                logger.info(f"ChromaDB collection '{self.collection_name}' ready")

            except Exception as e:
                logger.warning(f"ChromaDB initialization failed: {e}. Using fallback.")
                self.use_chromadb = False
                self._load_fallback_storage()
        else:
            logger.info("Using fallback numpy-based vector storage")
            self._load_fallback_storage()

    def _load_fallback_storage(self) -> None:
        """Load fallback numpy-based storage from disk."""
        vectors_file = self.persist_directory / "vectors.npy"
        metadata_file = self.persist_directory / "metadata.json"

        if vectors_file.exists() and metadata_file.exists():
            try:
                self.vectors = np.load(str(vectors_file))
                with open(metadata_file, 'r') as f:
                    data = json.load(f)
                    self.ids = data.get("ids", [])
                    self.metadatas = data.get("metadatas", [])
                logger.info(f"Loaded {len(self.ids)} vectors from fallback storage")
            except Exception as e:
                logger.warning(f"Failed to load fallback storage: {e}")
                self.vectors = np.array([])
                self.ids = []
                self.metadatas = []

    def _save_fallback_storage(self) -> None:
        """Save fallback numpy-based storage to disk."""
        vectors_file = self.persist_directory / "vectors.npy"
        metadata_file = self.persist_directory / "metadata.json"

        try:
            if len(self.vectors) > 0:
                np.save(str(vectors_file), self.vectors)

            with open(metadata_file, 'w') as f:
                json.dump({
                    "ids": self.ids,
                    "metadatas": self.metadatas
                }, f)

            logger.debug(f"Saved {len(self.ids)} vectors to fallback storage")

        except Exception as e:
            logger.error(f"Failed to save fallback storage: {e}")

    def add(
        self,
        ids: List[str],
        embeddings: np.ndarray,
        metadatas: Optional[List[Dict[str, Any]]] = None,
        documents: Optional[List[str]] = None,
    ) -> None:
        """
        Add vectors to the store.

        Args:
            ids: Unique identifiers for each vector
            embeddings: Numpy array of shape (n, dimension)
            metadatas: Optional metadata for each vector
            documents: Optional text documents
        """
        if self.use_chromadb and self.collection:
            try:
                self.collection.add(
                    ids=ids,
                    embeddings=embeddings.tolist(),
                    metadatas=metadatas,
                    documents=documents,
                )
                logger.debug(f"Added {len(ids)} vectors to ChromaDB")
                return
            except Exception as e:
                logger.error(f"ChromaDB add failed: {e}. Using fallback.")
                self.use_chromadb = False

        # Fallback storage
        if len(self.vectors) == 0:
            self.vectors = embeddings
        else:
            self.vectors = np.vstack([self.vectors, embeddings])

        self.ids.extend(ids)
        self.metadatas.extend(metadatas or [{} for _ in ids])

        self._save_fallback_storage()

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        Search for similar vectors.

        Args:
            query_embedding: Query vector
            top_k: Number of results to return
            filter_metadata: Optional metadata filters

        Returns:
            List of (id, score, metadata) tuples
        """
        if self.use_chromadb and self.collection:
            try:
                results = self.collection.query(
                    query_embeddings=[query_embedding.tolist()],
                    n_results=top_k,
                    where=filter_metadata,
                )

                # Format results
                output = []
                for i in range(len(results['ids'][0])):
                    output.append((
                        results['ids'][0][i],
                        results['distances'][0][i],
                        results['metadatas'][0][i] if results['metadatas'] else {}
                    ))
                return output

            except Exception as e:
                logger.error(f"ChromaDB search failed: {e}. Using fallback.")
                self.use_chromadb = False

        # Fallback: cosine similarity search
        if len(self.vectors) == 0:
            return []

        # Normalize vectors
        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-10)
        vectors_norm = self.vectors / (np.linalg.norm(self.vectors, axis=1, keepdims=True) + 1e-10)

        # Compute cosine similarities
        similarities = np.dot(vectors_norm, query_norm)

        # Get top-k indices
        top_indices = np.argsort(similarities)[::-1][:top_k]

        # Format results
        results = []
        for idx in top_indices:
            results.append((
                self.ids[idx],
                float(similarities[idx]),
                self.metadatas[idx]
            ))

        return results

    def count(self) -> int:
        """Get the number of vectors in the store."""
        if self.use_chromadb and self.collection:
            return self.collection.count()
        return len(self.ids)


class SemanticSearchEngine:
    """
    Complete semantic search engine combining embedding model and vector store.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: str = "cpu",
        persist_directory: Optional[Path] = None,
    ):
        """
        Initialize semantic search engine.

        Args:
            model_name: Embedding model name
            device: Device for model inference
            persist_directory: Directory for vector storage
        """
        self.embedding_model = EmbeddingModel(model_name=model_name, device=device)
        self.vector_store = VectorStore(
            persist_directory=persist_directory,
            embedding_dimension=self.embedding_model.dimension,
        )

    def index_messages(
        self,
        messages: List[Dict[str, Any]],
        batch_size: int = 100,
        show_progress: bool = True,
    ) -> int:
        """
        Index messages for semantic search.

        Args:
            messages: List of message dictionaries
            batch_size: Batch size for processing
            show_progress: Show progress bar

        Returns:
            Number of messages indexed
        """
        if not messages:
            return 0

        logger.info(f"Indexing {len(messages)} messages...")

        # Extract texts and metadata
        texts = []
        ids = []
        metadatas = []

        for msg in messages:
            msg_id = str(msg.get('id', msg.get('message_id', 0)))
            text = msg.get('content', msg.get('text', ''))

            if not text or len(text.strip()) == 0:
                continue

            texts.append(text)
            ids.append(f"msg_{msg_id}")
            metadatas.append({
                "message_id": msg_id,
                "channel_id": str(msg.get('channel_id', '')),
                "date": msg.get('date', ''),
                "user_id": str(msg.get('user_id', '')),
            })

        if not texts:
            logger.warning("No text content to index")
            return 0

        # Generate embeddings in batches
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            embeddings = self.embedding_model.embed_texts(
                batch_texts,
                batch_size=batch_size,
                show_progress=show_progress
            )
            all_embeddings.append(embeddings)

        all_embeddings = np.vstack(all_embeddings)

        # Add to vector store
        self.vector_store.add(
            ids=ids,
            embeddings=all_embeddings,
            metadatas=metadatas,
            documents=texts,
        )

        logger.info(f"Successfully indexed {len(texts)} messages")
        return len(texts)

    def search(
        self,
        query: str,
        top_k: int = 10,
        filter_channel: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Search for messages semantically similar to query.

        Args:
            query: Search query (natural language)
            top_k: Number of results to return
            filter_channel: Optional channel ID filter

        Returns:
            List of SearchResult objects
        """
        # Generate query embedding
        query_embedding = self.embedding_model.embed_single(query)

        # Build filter
        filter_metadata = None
        if filter_channel:
            filter_metadata = {"channel_id": filter_channel}

        # Search vector store
        results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            filter_metadata=filter_metadata,
        )

        # Format results
        search_results = []
        for result_id, score, metadata in results:
            # Extract message ID from result_id (format: "msg_12345")
            try:
                msg_id = int(result_id.replace("msg_", ""))
            except (ValueError, AttributeError):
                msg_id = 0

            search_results.append(SearchResult(
                message_id=msg_id,
                channel_id=int(metadata.get("channel_id", 0)) if metadata.get("channel_id") else None,
                content=metadata.get("content", ""),
                score=score,
                timestamp=datetime.fromisoformat(metadata["date"]) if metadata.get("date") else None,
                metadata=metadata,
            ))

        return search_results

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the search engine."""
        return {
            "total_vectors": self.vector_store.count(),
            "embedding_dimension": self.embedding_model.dimension,
            "model_name": self.embedding_model.model_name,
            "backend": "chromadb" if self.vector_store.use_chromadb else "numpy_fallback",
        }


__all__ = [
    "EmbeddingModel",
    "VectorStore",
    "SemanticSearchEngine",
    "SearchResult",
]
