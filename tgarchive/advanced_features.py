"""
Advanced Features Manager for SPECTRA

Manages automatic integration of:
- Vector database indexing (QIHSE)
- CNSA 2.0 cryptography
- Temporal analysis
- Attribution engine
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class AdvancedFeaturesManager:
    """Manages advanced features integration into archiving workflow."""

    def __init__(self, config: Dict[str, Any], db_connection=None):
        """
        Initialize advanced features manager.

        Args:
            config: Configuration dict (from spectra_config.json)
            db_connection: Optional database connection for querying messages
        """
        self.config = config.get("advanced_features", {})
        self.enabled = self.config.get("enabled", False)
        self.db = db_connection
        
        # Initialize components if enabled
        self.vector_store = None
        self.temporal_analyzer = None
        self.attribution_engine = None
        
        if self.enabled:
            self._initialize_components()

    def _initialize_components(self):
        """Initialize advanced feature components."""
        # Vector database
        if self.config.get("vector_database", {}).get("auto_index_messages", False):
            try:
                from .db.vector_store import VectorStoreManager, VectorStoreConfig
                
                vdb_config = self.config.get("vector_database", {})
                config = VectorStoreConfig(
                    backend="qihse",
                    path=vdb_config.get("path", "./data/qihse_vectors"),
                    collection_name=vdb_config.get("collection_name", "spectra_messages"),
                    vector_size=vdb_config.get("vector_dimension", 384),
                    confidence_threshold=vdb_config.get("confidence_threshold", 0.95)
                )
                
                self.vector_store = VectorStoreManager(config)
                logger.info("Advanced features: Vector database initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize vector database: {e}")

        # Temporal analysis
        if self.config.get("threat_analysis", {}).get("temporal_analysis", False):
            try:
                from .threat.temporal import TemporalAnalyzer
                self.temporal_analyzer = TemporalAnalyzer()
                logger.info("Advanced features: Temporal analyzer initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize temporal analyzer: {e}")

        # Attribution engine
        if self.config.get("threat_analysis", {}).get("attribution_engine", False):
            try:
                from .threat.attribution import AttributionEngine
                self.attribution_engine = AttributionEngine()
                logger.info("Advanced features: Attribution engine initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize attribution engine: {e}")

    def index_message(
        self,
        message_id: int,
        content: str,
        user_id: Optional[int],
        channel_id: Optional[int],
        date: datetime,
    ):
        """
        Index a message for vector search (if enabled).

        Args:
            message_id: Message ID
            content: Message text content
            user_id: User ID
            channel_id: Channel ID
            date: Message timestamp
        """
        if not self.enabled or not self.vector_store:
            return

        try:
            # Generate embedding
            from sentence_transformers import SentenceTransformer
            
            model_name = self.config.get("vector_database", {}).get(
                "embedding_model", "all-MiniLM-L6-v2"
            )
            model = SentenceTransformer(model_name)
            embedding = model.encode(content)

            # Prepare metadata
            metadata = {
                "user_id": user_id,
                "channel_id": channel_id,
                "date": date.isoformat(),
                "content_preview": content[:500] if content else "",
            }

            # Index in vector store
            self.vector_store.index_message(
                message_id=message_id,
                embedding=embedding,
                metadata=metadata
            )
            
            logger.debug(f"Indexed message {message_id} in vector database")

        except Exception as e:
            logger.warning(f"Failed to index message {message_id}: {e}")

    def analyze_user_activity(self, user_id: int, message_count: int):
        """
        Analyze user activity patterns (if enabled).

        Args:
            user_id: User ID
            message_count: Number of messages from this user
        """
        if not self.enabled:
            return

        threat_config = self.config.get("threat_analysis", {})
        min_messages = threat_config.get("min_messages_for_analysis", 10)

        if message_count < min_messages:
            return

        # Temporal analysis
        if threat_config.get("temporal_analysis", False) and self.temporal_analyzer:
            try:
                if not self.db:
                    logger.warning(f"Temporal analysis requires database connection for user {user_id}")
                    return
                
                # Query messages from database for temporal analysis
                cursor = self.db.execute(
                    "SELECT id, date, content FROM messages WHERE user_id = ? ORDER BY date",
                    (user_id,)
                )
                rows = cursor.fetchall()
                
                if rows:
                    # Format messages for temporal analyzer
                    messages = []
                    for row in rows:
                        msg_id, date_str, content = row
                        from datetime import datetime
                        try:
                            date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        except:
                            date = datetime.fromisoformat(date_str)
                        messages.append({
                            'id': msg_id,
                            'date': date,
                            'text': content or ''
                        })
                    
                    # Perform temporal analysis
                    analysis_result = self.temporal_analyzer.analyze_activity_patterns(messages)
                    logger.info(f"Temporal analysis completed for user {user_id}: {analysis_result.get('regularity_score', 0):.2f} regularity")
                else:
                    logger.debug(f"No messages found for temporal analysis of user {user_id}")
            except Exception as e:
                logger.warning(f"Temporal analysis failed for user {user_id}: {e}")

        # Attribution analysis
        if threat_config.get("attribution_engine", False) and self.attribution_engine:
            try:
                if not self.db:
                    logger.warning(f"Attribution analysis requires database connection for user {user_id}")
                    return
                
                # Query messages from database for attribution analysis
                cursor = self.db.execute(
                    "SELECT id, content FROM messages WHERE user_id = ? AND content IS NOT NULL AND content != '' ORDER BY date",
                    (user_id,)
                )
                rows = cursor.fetchall()
                
                if rows:
                    # Format messages for attribution engine
                    messages = []
                    for row in rows:
                        msg_id, content = row
                        messages.append({
                            'id': msg_id,
                            'text': content
                        })
                    
                    # Perform attribution analysis
                    style_profile = self.attribution_engine.analyze_writing_style(messages)
                    logger.info(f"Attribution analysis completed for user {user_id}: vocabulary_size={style_profile.vocabulary_size}, avg_sentence_length={style_profile.avg_sentence_length:.2f}")
                else:
                    logger.debug(f"No messages with content found for attribution analysis of user {user_id}")
            except Exception as e:
                logger.warning(f"Attribution analysis failed for user {user_id}: {e}")
