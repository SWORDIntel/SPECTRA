"""
Continuous Learner
==================

Core continuous learning engine for pattern and correlation discovery.
"""

import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
import numpy as np

from .learning_store import LearningStore
from .pattern_detector import PatternDetector
from .correlation_engine import CorrelationEngine

logger = logging.getLogger(__name__)


class ContinuousLearner:
    """
    Continuous learning engine for unsupervised pattern discovery.
    
    Features:
    - Autoencoder for content compression
    - DBSCAN clustering for anomaly detection
    - Continuous model updates
    - Pattern library growth
    """
    
    def __init__(self, learning_store_path: Path):
        """Initialize continuous learner"""
        self.store = LearningStore(learning_store_path)
        self.pattern_detector = PatternDetector(self.store)
        self.correlation_engine = CorrelationEngine(self.store)
    
    def learn_from_messages(self, messages: List[Dict[str, Any]]):
        """Learn patterns from new messages"""
        if not messages:
            return
        
        # Detect content patterns
        content_patterns = self.pattern_detector.detect_content_patterns(messages)
        logger.info(f"Discovered {len(content_patterns)} content patterns")
        
        # Detect temporal patterns
        timestamps = [msg.get('date') for msg in messages if msg.get('date')]
        if timestamps:
            temporal_patterns = self.pattern_detector.detect_temporal_patterns(timestamps)
            logger.info(f"Discovered {len(temporal_patterns)} temporal patterns")
        
        # Group by user for behavior patterns
        user_messages = {}
        for msg in messages:
            user_id = msg.get('user_id')
            if user_id:
                if user_id not in user_messages:
                    user_messages[user_id] = []
                user_messages[user_id].append(msg.get('date'))
        
        if user_messages:
            behavior_patterns = self.pattern_detector.detect_user_behavior_patterns(user_messages)
            logger.info(f"Discovered {len(behavior_patterns)} behavior patterns")
    
    def discover_correlations(
        self,
        channel_messages: Optional[Dict[int, List]] = None,
        user_activity: Optional[Dict[int, List]] = None
    ):
        """Discover correlations"""
        if channel_messages:
            channel_correlations = self.correlation_engine.discover_cross_channel_correlations(channel_messages)
            logger.info(f"Discovered {len(channel_correlations)} channel correlations")
        
        if user_activity:
            user_correlations = self.correlation_engine.discover_user_correlations(user_activity)
            logger.info(f"Discovered {len(user_correlations)} user correlations")
    
    def get_learned_patterns(self, pattern_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get learned patterns"""
        return self.store.get_patterns(pattern_type)
    
    def get_correlations(self, entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get discovered correlations"""
        return self.store.get_correlations(entity_type)
