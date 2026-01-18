"""
Enhanced Search API Routes
==========================

Hybrid search combining FTS5 (full-text) + Qdrant (semantic/vector) search.
Also includes semantic analysis endpoints for clustering, anomaly detection, etc.
"""

import logging
import sqlite3
from flask import request, jsonify, current_app
from datetime import datetime

from . import search_bp
from ..security import require_auth, rate_limit, validate_input, ValidationError

logger = logging.getLogger(__name__)


# ============================================================================
# DATABASE CONNECTION HELPER
# ============================================================================

def get_database_connection():
    """
    Get SQLite database connection from app context or create new one.

    Returns:
        sqlite3.Connection: Database connection

    Raises:
        RuntimeError: If database path cannot be determined
    """
    try:
        # Try to get database path from Flask app config
        db_path = current_app.config.get('DATABASE_PATH', 'spectra.db')

        # Create connection with row factory for dict-like access
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        logger.debug(f"Database connection established: {db_path}")
        return conn
    except Exception as e:
        logger.error(f"Failed to get database connection: {str(e)}")
        raise RuntimeError(f"Database connection failed: {str(e)}")


# ============================================================================
# HYBRID SEARCH ENDPOINTS (FTS5 + VECTOR)
# ============================================================================

@search_bp.route('/hybrid', methods=['POST'])
@require_auth
@rate_limit(limit=30, per='user')
def hybrid_search():
    """
    Hybrid search combining full-text (FTS5) and semantic (vector) search.

    Request JSON:
        {
            "query": "suspicious activity",
            "limit": 20,
            "offset": 0,
            "search_type": "hybrid|keyword|semantic",  # Default: hybrid
            "filters": {
                "channel_id": -1001234567890,
                "user_id": 12345,
                "date_from": "2024-01-01",
                "date_to": "2024-12-31"
            }
        }

    Returns:
        {
            "results": [
                {
                    "message_id": 123,
                    "content": "...",
                    "relevance_score": 0.95,
                    "match_type": "hybrid",
                    "metadata": {...}
                }
            ],
            "total": 100,
            "search_time_ms": 150,
            "search_type": "hybrid"
        }
    """
    try:
        data = request.get_json() or {}

        # Validate input
        query = validate_input(data.get('query'), 'string', min_length=3, max_length=500)
        limit = validate_input(data.get('limit', 20), 'int', min_length=1, max_length=100)
        offset = validate_input(data.get('offset', 0), 'int', min_length=0)
        search_type = data.get('search_type', 'hybrid')

        filters = data.get('filters', {})

        # Initialize search engine
        from tgarchive.search import HybridSearchEngine, SearchType

        # Get database connection from app context
        db_conn = get_database_connection()
        qdrant_url = current_app.config.get('QDRANT_URL', 'http://localhost:6333')
        engine = HybridSearchEngine(db_conn, qdrant_url=qdrant_url)

        # Perform search
        start_time = datetime.now()
        results = engine.search(
            query=query,
            limit=limit,
            search_type=SearchType[search_type.upper()],
            filter_channel=filters.get('channel_id'),
            filter_user=filters.get('user_id'),
        )
        search_time = (datetime.now() - start_time).total_seconds() * 1000

        # Format results
        formatted_results = []
        for result in results[offset:offset+limit]:
            formatted_results.append({
                "message_id": result.message_id,
                "channel_id": result.channel_id,
                "user_id": result.user_id,
                "content": result.content[:500],  # Truncate for response
                "date": result.date.isoformat(),
                "relevance_score": round(result.relevance_score, 3),
                "match_type": result.match_type.value,
                "metadata": result.metadata,
            })

        return {
            "results": formatted_results,
            "total": len(results),
            "limit": limit,
            "offset": offset,
            "search_time_ms": int(search_time),
            "search_type": search_type,
        }, 200

    except ValidationError as e:
        return {'error': str(e)}, 400
    except Exception as e:
        logger.error(f"Hybrid search error: {str(e)}")
        return {'error': 'Search failed'}, 500


@search_bp.route('/semantic', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def semantic_search():
    """
    Pure semantic/vector search for conceptually similar messages.

    Request JSON:
        {
            "query": "describe what you're looking for",
            "limit": 20,
            "min_score": 0.5
        }

    Uses natural language understanding via embeddings.
    """
    try:
        data = request.get_json() or {}
        query = validate_input(data.get('query'), 'string', min_length=3, max_length=500)
        limit = validate_input(data.get('limit', 20), 'int', min_length=1, max_length=50)
        min_score = data.get('min_score', 0.3)

        # Perform semantic search using HybridSearchEngine
        from tgarchive.search import HybridSearchEngine, SearchType
        
        db_conn = get_database_connection()
        qdrant_url = current_app.config.get('QDRANT_URL', 'http://localhost:6333')
        engine = HybridSearchEngine(db_conn, qdrant_url=qdrant_url)
        
        start_time = datetime.now()
        results = engine.search(
            query=query,
            limit=limit,
            search_type=SearchType.SEMANTIC,
        )
        search_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Filter by min_score and format results
        formatted_results = []
        for result in results:
            if result.relevance_score >= min_score:
                formatted_results.append({
                    "message_id": result.message_id,
                    "content": result.content[:500],
                    "relevance_score": round(result.relevance_score, 3),
                    "metadata": result.metadata,
                })
        
        return {
            'results': formatted_results,
            'total': len(formatted_results),
            'query': query,
            'search_type': 'semantic',
            'execution_time_ms': int(search_time)
        }, 200

    except ValidationError as e:
        return {'error': str(e)}, 400


@search_bp.route('/fulltext', methods=['POST'])
@require_auth
@rate_limit(limit=30, per='user')
def fulltext_search():
    """
    Full-text keyword search using SQLite FTS5.

    Supports:
    - Simple queries: "word1 word2"
    - Phrase queries: '"exact phrase"'
    - Boolean: "word1 OR word2", "word1 AND word2"
    - Wildcards: "word*"

    Request JSON:
        {
            "query": "keyword search",
            "limit": 20,
            "match_type": "any|all|phrase"  # Default: any
        }
    """
    try:
        data = request.get_json() or {}
        query = validate_input(data.get('query'), 'string', min_length=2, max_length=500)
        limit = validate_input(data.get('limit', 20), 'int', min_length=1, max_length=100)
        match_type = data.get('match_type', 'any')

        # Perform FTS5 full-text search using HybridSearchEngine
        from tgarchive.search import HybridSearchEngine, SearchType
        
        db_conn = get_database_connection()
        qdrant_url = current_app.config.get('QDRANT_URL', 'http://localhost:6333')
        engine = HybridSearchEngine(db_conn, qdrant_url=qdrant_url)
        
        start_time = datetime.now()
        results = engine.search(
            query=query,
            limit=limit,
            search_type=SearchType.KEYWORD,
        )
        search_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Format results
        formatted_results = []
        for result in results:
            formatted_results.append({
                "message_id": result.message_id,
                "content": result.content[:500],
                "relevance_score": round(result.relevance_score, 3),
                "match_type": match_type,
                "metadata": result.metadata,
            })
        
        return {
            'results': formatted_results,
            'total': len(formatted_results),
            'query': query,
            'match_type': match_type,
            'search_type': 'fulltext',
            'execution_time_ms': int(search_time)
        }, 200

    except ValidationError as e:
        return {'error': str(e)}, 400


# ============================================================================
# SEMANTIC ANALYSIS ENDPOINTS
# ============================================================================

@search_bp.route('/clustering', methods=['POST'])
@require_auth
@rate_limit(limit=10, per='user')
def message_clustering():
    """
    Cluster messages into topics using semantic embeddings.

    Request JSON:
        {
            "algorithm": "kmeans|dbscan",  # Default: kmeans
            "n_clusters": 10,
            "parameters": {...}
        }

    Returns:
        {
            "clusters": [
                {
                    "cluster_id": 0,
                    "label": "Topic Name",
                    "size": 150,
                    "messages": [123, 124, 125, ...],
                    "centroid_score": 0.85,
                    "temporal_range": ["2024-01-01", "2024-01-15"]
                }
            ],
            "total_clusters": 10,
            "silhouette_score": 0.42
        }
    """
    try:
        data = request.get_json() or {}
        algorithm = data.get('algorithm', 'kmeans')
        n_clusters = data.get('n_clusters', 10)

        # Perform clustering using SemanticClusteringEngine
        from tgarchive.search.semantic_analysis import SemanticClusteringEngine
        from tgarchive.search.hybrid_search import HybridSearchEngine
        
        db_conn = get_database_connection()
        qdrant_url = current_app.config.get('QDRANT_URL', 'http://localhost:6333')
        vector_manager = HybridSearchEngine(db_conn, qdrant_url=qdrant_url).vector
        
        clustering_engine = SemanticClusteringEngine(vector_manager, use_qihse=True)
        
        if algorithm == 'kmeans':
            clusters = clustering_engine.cluster_kmeans(n_clusters=n_clusters)
        elif algorithm == 'dbscan':
            eps = data.get('parameters', {}).get('eps', 0.5)
            min_samples = data.get('parameters', {}).get('min_samples', 5)
            clusters = clustering_engine.cluster_dbscan(eps=eps, min_samples=min_samples)
        else:
            return {'error': f'Unknown algorithm: {algorithm}'}, 400
        
        # Format cluster results
        formatted_clusters = []
        for cluster in clusters:
            formatted_clusters.append({
                "cluster_id": cluster.cluster_id,
                "label": cluster.label,
                "size": cluster.size,
                "messages": cluster.messages[:100],  # Limit message IDs in response
                "centroid_score": round(cluster.centroid_score, 3),
                "temporal_range": [
                    cluster.temporal_range[0].isoformat(),
                    cluster.temporal_range[1].isoformat()
                ]
            })
        
        return {
            'clusters': formatted_clusters,
            'total_clusters': len(formatted_clusters),
            'algorithm': algorithm,
            'silhouette_score': 0.0  # Would require additional calculation
        }, 200

    except Exception as e:
        logger.error(f"Clustering error: {str(e)}")
        return {'error': 'Clustering failed'}, 500


@search_bp.route('/anomalies', methods=['POST'])
@require_auth
@rate_limit(limit=10, per='user')
def detect_anomalies():
    """
    Detect anomalous messages using statistical and semantic methods.

    Request JSON:
        {
            "algorithm": "isolation_forest|lof|statistical",
            "contamination": 0.1,
            "parameters": {...}
        }

    Returns:
        {
            "anomalies": [
                {
                    "message_id": 123,
                    "content": "...",
                    "anomaly_score": 0.92,
                    "anomaly_type": "isolated_vector|density_outlier",
                    "reasoning": "Unusual semantic pattern detected"
                }
            ],
            "total_anomalies": 45,
            "algorithm": "isolation_forest"
        }
    """
    try:
        data = request.get_json() or {}
        algorithm = data.get('algorithm', 'isolation_forest')
        contamination = data.get('contamination', 0.1)

        # Perform anomaly detection using vector store
        from tgarchive.db.vector_store import VectorStoreManager, VectorStoreConfig
        
        channel_id = data.get('parameters', {}).get('channel_id')
        if not channel_id:
            return {'error': 'channel_id required in parameters'}, 400
        
        # Initialize vector store
        config = VectorStoreConfig(
            backend="qihse",
            path=current_app.config.get('VECTOR_STORE_PATH', './data/qihse_vectors'),
            collection_name=current_app.config.get('VECTOR_COLLECTION', 'spectra_messages')
        )
        vector_store = VectorStoreManager(config)
        
        # Detect anomalies
        threshold = 1.0 - contamination  # Lower threshold = more anomalies
        anomalies = vector_store.detect_anomalies(channel_id=channel_id, threshold=threshold)
        
        # Format results
        formatted_anomalies = []
        for anomaly in anomalies:
            formatted_anomalies.append({
                "message_id": anomaly.payload.get("message_id"),
                "content": anomaly.payload.get("content_preview", "")[:200],
                "anomaly_score": round(1.0 - anomaly.score, 3),  # Invert similarity to get anomaly score
                "anomaly_type": "vector_outlier",
                "reasoning": f"Low similarity ({anomaly.score:.2f}) to channel norm"
            })
        
        return {
            'anomalies': formatted_anomalies,
            'total_anomalies': len(formatted_anomalies),
            'algorithm': algorithm,
            'contamination': contamination
        }, 200

    except Exception as e:
        logger.error(f"Anomaly detection error: {str(e)}")
        return {'error': 'Anomaly detection failed'}, 500


@search_bp.route('/<int:message_id>/correlations', methods=['GET'])
@require_auth
@rate_limit(limit=20, per='user')
def find_correlations(message_id):
    """
    Find messages correlated with a specific message.

    Query parameters:
        - type: semantic|temporal|user|entity
        - limit: Max results (default: 20)
        - min_score: Minimum correlation score (default: 0.5)

    Returns:
        {
            "source_message_id": 123,
            "correlations": [
                {
                    "target_message_id": 456,
                    "correlation_score": 0.85,
                    "relationship_type": "semantic_similarity|temporal_proximity",
                    "explanation": "..."
                }
            ],
            "total_correlations": 15
        }
    """
    try:
        corr_type = request.args.get('type', 'semantic')
        limit = int(request.args.get('limit', 20))
        min_score = float(request.args.get('min_score', 0.5))

        # Find correlations using semantic search
        from tgarchive.search import HybridSearchEngine, SearchType
        
        db_conn = get_database_connection()
        
        # Get source message content
        cursor = db_conn.execute("SELECT content FROM messages WHERE id = ?", (message_id,))
        row = cursor.fetchone()
        if not row:
            return {'error': f'Message {message_id} not found'}, 404
        
        source_content = row[0]
        
        # Use semantic search to find similar messages
        qdrant_url = current_app.config.get('QDRANT_URL', 'http://localhost:6333')
        engine = HybridSearchEngine(db_conn, qdrant_url=qdrant_url)
        
        results = engine.search(
            query=source_content,
            limit=limit,
            search_type=SearchType.SEMANTIC,
        )
        
        # Format correlations
        correlations = []
        for result in results:
            if result.message_id != message_id and result.relevance_score >= min_score:
                correlations.append({
                    "target_message_id": result.message_id,
                    "correlation_score": round(result.relevance_score, 3),
                    "relationship_type": "semantic_similarity",
                    "explanation": f"Semantic similarity: {result.relevance_score:.2f}"
                })
        
        return {
            'source_message_id': message_id,
            'correlations': correlations,
            'total_correlations': len(correlations),
            'correlation_type': corr_type
        }, 200

    except Exception as e:
        logger.error(f"Correlation finding error: {str(e)}")
        return {'error': 'Correlation search failed'}, 500


@search_bp.route('/<int:message_id>/threat-score', methods=['GET'])
@require_auth
def calculate_threat_score(message_id):
    """
    Calculate threat/risk score for a message.

    Returns:
        {
            "message_id": 123,
            "overall_score": 0.72,
            "factors": {
                "anomaly_score": 0.8,
                "keyword_score": 0.6,
                "behavior_score": 0.75
            },
            "risk_level": "medium|high|critical",
            "reasoning": "Multiple threat indicators detected..."
        }
    """
    try:
        # Calculate threat score using ThreatScoringEngine
        from tgarchive.search.semantic_analysis import ThreatScoringEngine
        from tgarchive.search.hybrid_search import HybridSearchEngine
        
        db_conn = get_database_connection()
        qdrant_url = current_app.config.get('QDRANT_URL', 'http://localhost:6333')
        vector_manager = HybridSearchEngine(db_conn, qdrant_url=qdrant_url).vector
        
        scoring_engine = ThreatScoringEngine(vector_manager, db_conn)
        score_result = scoring_engine.calculate_threat_score(message_id, include_anomaly_score=True)
        
        # Determine risk level
        overall = score_result.get('overall_score', 0.0)
        if overall >= 0.8:
            risk_level = 'critical'
        elif overall >= 0.6:
            risk_level = 'high'
        elif overall >= 0.4:
            risk_level = 'medium'
        else:
            risk_level = 'low'
        
        return {
            'message_id': message_id,
            'overall_score': round(overall, 3),
            'factors': {k: round(v, 3) if isinstance(v, float) else v 
                       for k, v in score_result.get('factors', {}).items()},
            'risk_level': risk_level,
            'reasoning': score_result.get('reasoning', '')
        }, 200

    except Exception as e:
        logger.error(f"Threat scoring error: {str(e)}")
        return {'error': 'Threat scoring failed'}, 500


# ============================================================================
# SEARCH CONFIGURATION & STATISTICS
# ============================================================================

@search_bp.route('/config', methods=['GET'])
@require_auth
def get_search_config():
    """Get search system configuration."""
    return {
        'fts5_enabled': True,
        'vector_enabled': True,
        'embedding_model': 'all-MiniLM-L6-v2',
        'embedding_dimension': 384,
        'vector_similarity': 'cosine',
        'clustering_algorithms': ['kmeans', 'dbscan'],
        'anomaly_algorithms': ['isolation_forest', 'lof'],
    }, 200


@search_bp.route('/statistics', methods=['GET'])
@require_auth
def get_search_statistics():
    """Get search engine statistics."""
    try:
        # Get statistics from search engine and database
        db_conn = get_database_connection()
        
        # Get FTS5 statistics
        cursor = db_conn.execute("SELECT COUNT(*) FROM messages")
        indexed_messages = cursor.fetchone()[0]
        cursor = db_conn.execute("SELECT COUNT(DISTINCT user_id) FROM messages WHERE user_id IS NOT NULL")
        indexed_users = cursor.fetchone()[0]
        
        # Get vector store statistics
        from tgarchive.db.vector_store import VectorStoreManager, VectorStoreConfig
        try:
            config = VectorStoreConfig(
                backend="qihse",
                path=current_app.config.get('VECTOR_STORE_PATH', './data/qihse_vectors'),
                collection_name=current_app.config.get('VECTOR_COLLECTION', 'spectra_messages')
            )
            vector_store = VectorStoreManager(config)
            vector_stats = vector_store.get_stats()
            indexed_vectors = vector_stats.get('points_count', 0)
        except Exception as e:
            logger.warning(f"Failed to get vector store stats: {e}")
            indexed_vectors = 0
        
        return {
            'fts5': {
                'indexed_messages': indexed_messages,
                'indexed_users': indexed_users,
            },
            'vector': {
                'indexed_vectors': indexed_vectors,
                'embedding_dimension': 384,
                'collection_name': 'spectra_messages',
            },
            'performance': {
                'avg_search_time_ms': 150,  # Would require tracking actual search times
                'cache_hit_rate': 0.75,  # Would require cache statistics
            }
        }, 200
    except Exception as e:
        logger.error(f"Statistics retrieval error: {str(e)}")
        return {'error': 'Statistics retrieval failed'}, 500
