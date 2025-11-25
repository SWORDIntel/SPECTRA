"""
Semantic Analysis Module
========================

Advanced intelligence analysis using embeddings:
- Clustering: Identify message topics/groups
- Anomaly detection: Flag unusual patterns
- Correlation: Find related conversations
- Threat scoring: Identify suspicious patterns
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Cluster:
    """Message cluster result."""
    cluster_id: int
    label: str
    size: int
    messages: List[int]
    centroid_score: float
    temporal_range: Tuple[datetime, datetime]


@dataclass
class Anomaly:
    """Anomaly detection result."""
    message_id: int
    content: str
    anomaly_score: float  # 0-1 (higher = more anomalous)
    anomaly_type: str  # "outlier", "burst", "unusual_pattern", etc.
    reasoning: str


@dataclass
class Correlation:
    """Message correlation result."""
    source_message_id: int
    target_message_id: int
    correlation_score: float  # 0-1
    relationship_type: str  # "mentions_same_entity", "temporal_proximity", etc.


class SemanticClusteringEngine:
    """
    Cluster messages into topics using semantic embeddings.

    Methods:
    - K-means clustering
    - DBSCAN for arbitrary clusters
    - Hierarchical clustering for dendrograms
    """

    def __init__(self, vector_manager):
        """
        Initialize clustering engine.

        Args:
            vector_manager: QdrantVectorManager instance
        """
        self.vector_manager = vector_manager

    def cluster_kmeans(
        self,
        n_clusters: int = 10,
        max_iter: int = 100,
    ) -> List[Cluster]:
        """
        Cluster messages using K-means algorithm.

        Args:
            n_clusters: Number of clusters
            max_iter: Maximum iterations

        Returns:
            List of Cluster objects
        """
        try:
            from sklearn.cluster import KMeans

            # Get all vectors from Qdrant
            # This is a simplified version - in production, use scrolling
            collection_info = self.vector_manager.client.get_collection(
                self.vector_manager.collection_name
            )
            total_vectors = collection_info.points_count

            # Retrieve vectors (paginated)
            vectors = []
            message_ids = []
            batch_size = 100

            for offset in range(0, total_vectors, batch_size):
                points, _ = self.vector_manager.client.scroll(
                    collection_name=self.vector_manager.collection_name,
                    limit=batch_size,
                    offset=offset,
                )

                for point in points:
                    vectors.append(point.vector)
                    message_ids.append(point.payload.get("message_id"))

            if not vectors:
                logger.warning("No vectors found for clustering")
                return []

            # Convert to numpy
            vectors = np.array(vectors)

            # Perform K-means clustering
            kmeans = KMeans(n_clusters=min(n_clusters, len(vectors)), max_iter=max_iter)
            labels = kmeans.fit_predict(vectors)

            # Create cluster objects
            clusters = []
            for cluster_id in range(n_clusters):
                cluster_indices = np.where(labels == cluster_id)[0]
                cluster_messages = [message_ids[i] for i in cluster_indices]

                if cluster_messages:
                    cluster = Cluster(
                        cluster_id=cluster_id,
                        label=f"Topic {cluster_id}",  # TODO: Generate from centroid
                        size=len(cluster_messages),
                        messages=cluster_messages,
                        centroid_score=1.0,  # TODO: Calculate distance to centroid
                        temporal_range=(datetime.now(), datetime.now()),  # TODO: Get from messages
                    )
                    clusters.append(cluster)

            logger.info(f"✓ Created {len(clusters)} clusters with K-means")
            return clusters

        except Exception as e:
            logger.error(f"K-means clustering failed: {e}")
            return []

    def cluster_dbscan(
        self,
        eps: float = 0.5,
        min_samples: int = 5,
    ) -> List[Cluster]:
        """
        Cluster messages using DBSCAN (density-based clustering).

        Advantages:
        - No need to specify number of clusters
        - Automatically identifies outliers
        - Handles arbitrary cluster shapes

        Args:
            eps: Maximum distance between neighbors
            min_samples: Minimum samples per cluster

        Returns:
            List of Cluster objects
        """
        try:
            from sklearn.cluster import DBSCAN

            # Retrieve vectors (similar to K-means)
            vectors = []
            message_ids = []
            collection_info = self.vector_manager.client.get_collection(
                self.vector_manager.collection_name
            )
            total_vectors = collection_info.points_count

            batch_size = 100
            for offset in range(0, total_vectors, batch_size):
                points, _ = self.vector_manager.client.scroll(
                    collection_name=self.vector_manager.collection_name,
                    limit=batch_size,
                    offset=offset,
                )
                for point in points:
                    vectors.append(point.vector)
                    message_ids.append(point.payload.get("message_id"))

            if not vectors:
                return []

            vectors = np.array(vectors)

            # Perform DBSCAN
            dbscan = DBSCAN(eps=eps, min_samples=min_samples, metric='cosine')
            labels = dbscan.fit_predict(vectors)

            # Create cluster objects
            clusters = []
            unique_labels = set(labels)

            for cluster_id in sorted(unique_labels):
                if cluster_id == -1:
                    continue  # Skip noise points

                cluster_indices = np.where(labels == cluster_id)[0]
                cluster_messages = [message_ids[i] for i in cluster_indices]

                if cluster_messages:
                    cluster = Cluster(
                        cluster_id=cluster_id,
                        label=f"Topic {cluster_id}",
                        size=len(cluster_messages),
                        messages=cluster_messages,
                        centroid_score=1.0,
                        temporal_range=(datetime.now(), datetime.now()),
                    )
                    clusters.append(cluster)

            logger.info(f"✓ Created {len(clusters)} clusters with DBSCAN")
            return clusters

        except Exception as e:
            logger.error(f"DBSCAN clustering failed: {e}")
            return []


class AnomalyDetectionEngine:
    """
    Detect anomalous messages using statistical and semantic methods.

    Methods:
    - Isolation Forest: Finds isolated/unusual vectors
    - Local Outlier Factor: Density-based anomaly detection
    - Statistical: Deviation from expected patterns
    """

    def __init__(self, vector_manager):
        """
        Initialize anomaly detection engine.

        Args:
            vector_manager: QdrantVectorManager instance
        """
        self.vector_manager = vector_manager

    def detect_isolation_forest(
        self,
        contamination: float = 0.1,
        random_state: int = 42,
    ) -> List[Anomaly]:
        """
        Detect anomalies using Isolation Forest algorithm.

        Args:
            contamination: Expected proportion of anomalies (0-1)
            random_state: Random seed

        Returns:
            List of Anomaly objects
        """
        try:
            from sklearn.ensemble import IsolationForest

            # Retrieve vectors
            vectors = []
            point_data = []
            collection_info = self.vector_manager.client.get_collection(
                self.vector_manager.collection_name
            )
            total_vectors = collection_info.points_count

            batch_size = 100
            for offset in range(0, total_vectors, batch_size):
                points, _ = self.vector_manager.client.scroll(
                    collection_name=self.vector_manager.collection_name,
                    limit=batch_size,
                    offset=offset,
                )
                for point in points:
                    vectors.append(point.vector)
                    point_data.append({
                        "message_id": point.payload.get("message_id"),
                        "content": point.payload.get("content", "")[:200],
                    })

            if not vectors:
                return []

            vectors = np.array(vectors)

            # Fit Isolation Forest
            iso_forest = IsolationForest(
                contamination=contamination,
                random_state=random_state,
                n_jobs=-1,
            )
            predictions = iso_forest.fit_predict(vectors)
            scores = iso_forest.score_samples(vectors)

            # Create anomaly objects
            anomalies = []
            for i, (prediction, score) in enumerate(zip(predictions, scores)):
                if prediction == -1:  # Anomaly detected
                    # Normalize score to 0-1
                    anomaly_score = 1.0 / (1.0 + np.exp(score))

                    anomaly = Anomaly(
                        message_id=point_data[i]["message_id"],
                        content=point_data[i]["content"],
                        anomaly_score=float(anomaly_score),
                        anomaly_type="isolated_vector",
                        reasoning=f"Isolation Forest detected unusual semantic pattern (score: {score:.2f})",
                    )
                    anomalies.append(anomaly)

            logger.info(f"✓ Detected {len(anomalies)} anomalies with Isolation Forest")
            return sorted(anomalies, key=lambda x: x.anomaly_score, reverse=True)

        except Exception as e:
            logger.error(f"Isolation Forest detection failed: {e}")
            return []

    def detect_lof(
        self,
        n_neighbors: int = 20,
        contamination: float = 0.1,
    ) -> List[Anomaly]:
        """
        Detect anomalies using Local Outlier Factor (LOF).

        LOF measures local density deviation - good for detecting
        local outliers that may not be global outliers.

        Args:
            n_neighbors: Number of neighbors to consider
            contamination: Expected proportion of anomalies

        Returns:
            List of Anomaly objects
        """
        try:
            from sklearn.neighbors import LocalOutlierFactor

            # Retrieve vectors (simplified)
            vectors = []
            point_data = []
            collection_info = self.vector_manager.client.get_collection(
                self.vector_manager.collection_name
            )

            # Get sample (production would paginate)
            points, _ = self.vector_manager.client.scroll(
                collection_name=self.vector_manager.collection_name,
                limit=1000,
            )

            for point in points:
                vectors.append(point.vector)
                point_data.append({
                    "message_id": point.payload.get("message_id"),
                    "content": point.payload.get("content", "")[:200],
                })

            if not vectors:
                return []

            vectors = np.array(vectors)

            # Fit LOF
            lof = LocalOutlierFactor(
                n_neighbors=min(n_neighbors, len(vectors) - 1),
                contamination=contamination,
                novelty=False,
            )
            predictions = lof.fit_predict(vectors)
            scores = lof.negative_outlier_factor_

            # Create anomaly objects
            anomalies = []
            for i, (prediction, score) in enumerate(zip(predictions, scores)):
                if prediction == -1:  # Anomaly
                    # Normalize score to 0-1
                    anomaly_score = 1.0 / (1.0 + np.exp(-score))

                    anomaly = Anomaly(
                        message_id=point_data[i]["message_id"],
                        content=point_data[i]["content"],
                        anomaly_score=float(anomaly_score),
                        anomaly_type="density_outlier",
                        reasoning=f"LOF detected low local density (score: {score:.2f})",
                    )
                    anomalies.append(anomaly)

            logger.info(f"✓ Detected {len(anomalies)} anomalies with LOF")
            return sorted(anomalies, key=lambda x: x.anomaly_score, reverse=True)

        except Exception as e:
            logger.error(f"LOF detection failed: {e}")
            return []


class CorrelationEngine:
    """
    Find correlated messages and relationships.

    Analysis types:
    - Semantic similarity: Messages with similar content
    - Temporal correlation: Messages close in time
    - User correlation: Messages from related users
    - Entity correlation: Messages mentioning same entities
    """

    def __init__(self, vector_manager, db_connection):
        """
        Initialize correlation engine.

        Args:
            vector_manager: QdrantVectorManager instance
            db_connection: SQLite connection
        """
        self.vector_manager = vector_manager
        self.db = db_connection

    def find_semantic_correlations(
        self,
        message_id: int,
        limit: int = 20,
        score_threshold: float = 0.7,
    ) -> List[Correlation]:
        """
        Find messages semantically similar to a given message.

        Args:
            message_id: Target message ID
            limit: Max results
            score_threshold: Minimum similarity score

        Returns:
            List of Correlation objects
        """
        try:
            # Get source message content
            point = self.vector_manager.client.retrieve(
                collection_name=self.vector_manager.collection_name,
                ids=[message_id],
            )

            if not point:
                logger.warning(f"Message {message_id} not found in vector store")
                return []

            source_vector = point[0].vector
            source_payload = point[0].payload

            # Search for similar messages
            results = self.vector_manager.client.search(
                collection_name=self.vector_manager.collection_name,
                query_vector=source_vector,
                limit=limit + 1,  # +1 to exclude self
                score_threshold=score_threshold,
            )

            # Create correlation objects
            correlations = []
            for scored_point in results:
                if scored_point.id == message_id:
                    continue  # Skip self-correlation

                correlation = Correlation(
                    source_message_id=message_id,
                    target_message_id=scored_point.id,
                    correlation_score=scored_point.score,
                    relationship_type="semantic_similarity",
                )
                correlations.append(correlation)

            logger.info(f"Found {len(correlations)} semantic correlations")
            return correlations

        except Exception as e:
            logger.error(f"Semantic correlation search failed: {e}")
            return []

    def find_temporal_correlations(
        self,
        message_id: int,
        time_window_hours: int = 24,
        limit: int = 20,
    ) -> List[Correlation]:
        """
        Find messages temporally close to a given message.

        Args:
            message_id: Target message ID
            time_window_hours: Time window around message
            limit: Max results

        Returns:
            List of Correlation objects
        """
        try:
            # Get source message timestamp
            result = self.db.execute(
                "SELECT date FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()

            if not result:
                logger.warning(f"Message {message_id} not found in database")
                return []

            source_date = result[0]

            # Find messages in time window
            from datetime import timedelta
            start_time = source_date - timedelta(hours=time_window_hours / 2)
            end_time = source_date + timedelta(hours=time_window_hours / 2)

            results = self.db.execute(
                """
                SELECT id FROM messages
                WHERE id != ? AND date BETWEEN ? AND ?
                LIMIT ?
                """,
                (message_id, start_time, end_time, limit),
            ).fetchall()

            # Create correlation objects
            correlations = []
            for row in results:
                correlation = Correlation(
                    source_message_id=message_id,
                    target_message_id=row[0],
                    correlation_score=0.8,  # Temporal correlation score
                    relationship_type="temporal_proximity",
                )
                correlations.append(correlation)

            logger.info(f"Found {len(correlations)} temporal correlations")
            return correlations

        except Exception as e:
            logger.error(f"Temporal correlation search failed: {e}")
            return []


class ThreatScoringEngine:
    """
    Score messages for threat/risk indicators.

    Scoring factors:
    - Anomalous patterns
    - Suspicious keywords
    - User behavior anomalies
    - Network patterns
    """

    def __init__(self, vector_manager, db_connection):
        """
        Initialize threat scoring engine.

        Args:
            vector_manager: QdrantVectorManager instance
            db_connection: SQLite connection
        """
        self.vector_manager = vector_manager
        self.db = db_connection
        self.anomaly_engine = AnomalyDetectionEngine(vector_manager)

    def calculate_threat_score(
        self,
        message_id: int,
        include_anomaly_score: bool = True,
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive threat score for a message.

        Returns:
            {
                "overall_score": 0-1,
                "factors": {
                    "anomaly_score": 0-1,
                    "keyword_score": 0-1,
                    "behavior_score": 0-1,
                    ...
                },
                "reasoning": "..."
            }
        """
        scores = {}
        reasoning = []

        try:
            # Get message content
            result = self.db.execute(
                "SELECT content, user_id FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()

            if not result:
                return {"overall_score": 0, "factors": scores, "reasoning": "Message not found"}

            content, user_id = result

            # Anomaly score
            if include_anomaly_score:
                # Check if message is in anomalies
                # This would use the anomaly detection engine results
                scores["anomaly_score"] = 0.5  # TODO: Implement

            # Keyword-based scoring
            threat_keywords = [
                "hack", "crack", "malware", "exploit", "attack",
                "ransomware", "phishing", "botnet", "ddos",
            ]
            keyword_score = 0
            for keyword in threat_keywords:
                if keyword.lower() in content.lower():
                    keyword_score += 0.1

            scores["keyword_score"] = min(keyword_score, 1.0)
            if keyword_score > 0:
                reasoning.append(f"Threat keywords detected")

            # Behavior score (based on user's typical behavior)
            # TODO: Implement user behavior analysis
            scores["behavior_score"] = 0.3

            # Calculate overall score (weighted combination)
            weights = {
                "anomaly_score": 0.4,
                "keyword_score": 0.3,
                "behavior_score": 0.3,
            }

            overall_score = sum(
                scores.get(key, 0) * weight
                for key, weight in weights.items()
            )

            return {
                "overall_score": min(overall_score, 1.0),
                "factors": scores,
                "reasoning": "; ".join(reasoning) if reasoning else "No threat indicators",
            }

        except Exception as e:
            logger.error(f"Threat scoring failed: {e}")
            return {
                "overall_score": 0,
                "factors": scores,
                "reasoning": f"Error: {str(e)}",
            }
