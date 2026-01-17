"""
SPECTRA Hybrid Search & Semantic Analysis Module
=================================================

Combines SQLite FTS5 (full-text search) with Qdrant (vector database)
for comprehensive message discovery and intelligence analysis.

Architecture:
┌─────────────────────────────────────────────────────────────────┐
│                   Hybrid Search Architecture                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Messages (SQLite)                                              │
│       │                                                         │
│       ├──→ FTS5 Index    ───────┐                              │
│       │   (Keyword Search)      │                              │
│       │                         │                              │
│       └──→ Embeddings (Qdrant)──┤ Hybrid Search Engine        │
│           (Semantic Search)     │ ├─ Combine Results          │
│                                 │ ├─ Normalize Scores         │
│                                 │ └─ Rank by Relevance        │
│                                 │                              │
│                                 └──→ Semantic Analysis         │
│                                     ├─ Clustering              │
│                                     ├─ Anomaly Detection       │
│                                     ├─ Correlation             │
│                                     └─ Threat Scoring          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

Key Components:
1. SQLiteFTS5IndexManager - Full-text search with BM25 ranking
2. QdrantVectorManager - Vector embeddings and semantic search
3. HybridSearchEngine - Unified search combining both methods
4. SemanticClusteringEngine - Topic clustering (K-means, DBSCAN)
5. AnomalyDetectionEngine - Outlier detection (Isolation Forest, LOF)
6. CorrelationEngine - Find related messages
7. ThreatScoringEngine - Intelligence scoring

Features:
✓ Full-text search (keyword matching)
✓ Semantic search (similarity matching)
✓ Hybrid search (combined keyword + semantic)
✓ Message clustering (group by topic)
✓ Anomaly detection (find unusual patterns)
✓ Correlation analysis (find relationships)
✓ Threat scoring (intelligence assessment)

Usage:
    from tgarchive.search import HybridSearchEngine

    engine = HybridSearchEngine(db_connection, qdrant_url="http://localhost:6333")

    # Simple search (hybrid)
    results = engine.search("target user activity")

    # Keyword-only search
    results = engine.search(query, search_type=SearchType.KEYWORD)

    # Semantic search
    results = engine.search(query, search_type=SearchType.SEMANTIC)

    # Advanced clustering
    from tgarchive.search import SemanticClusteringEngine
    clustering = SemanticClusteringEngine(engine.vector)
    clusters = clustering.cluster_kmeans(n_clusters=10)

    # Anomaly detection
    from tgarchive.search import AnomalyDetectionEngine
    anomalies = AnomalyDetectionEngine(engine.vector)
    results = anomalies.detect_isolation_forest(contamination=0.1)
"""

from .hybrid_search import (
    HybridSearchEngine,
    SQLiteFTS5IndexManager,
    QdrantVectorManager,
    SearchType,
    SearchResult,
)

from .semantic_analysis import (
    SemanticClusteringEngine,
    AnomalyDetectionEngine,
    CorrelationEngine,
    ThreatScoringEngine,
    Cluster,
    Anomaly,
    Correlation,
)

from .distributed_search import DistributedSearchCoordinator
from .search_node import SearchNode
from .cache_manager import CacheManager
from .unified_search import UnifiedSearchEngine
from .temporal_semantic import TemporalSemanticSearch

__all__ = [
    # Hybrid Search
    "HybridSearchEngine",
    "SQLiteFTS5IndexManager",
    "QdrantVectorManager",
    "SearchType",
    "SearchResult",
    # Analysis
    "SemanticClusteringEngine",
    "AnomalyDetectionEngine",
    "CorrelationEngine",
    "ThreatScoringEngine",
    # Data Classes
    "Cluster",
    "Anomaly",
    "Correlation",
    # Distributed & Caching
    "DistributedSearchCoordinator",
    "SearchNode",
    "CacheManager",
    "UnifiedSearchEngine",
    "TemporalSemanticSearch",
]
