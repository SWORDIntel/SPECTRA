"""
Correlation Engine
==================

Discover correlations between entities and patterns.
"""

import logging
from typing import List, Dict, Any, Optional
import numpy as np

from .learning_store import LearningStore

logger = logging.getLogger(__name__)


class CorrelationEngine:
    """
    Correlation discovery engine.
    
    Discovers:
    - Cross-channel correlations
    - User-user correlations
    - Content-content correlations
    - Temporal correlations
    """
    
    def __init__(self, learning_store: LearningStore):
        """Initialize correlation engine"""
        self.store = learning_store
    
    def discover_cross_channel_correlations(
        self,
        channel_messages: Dict[int, List[datetime]]
    ) -> List[Dict[str, Any]]:
        """Discover correlations between channels"""
        correlations = []
        
        channel_ids = list(channel_messages.keys())
        
        for i, ch1 in enumerate(channel_ids):
            for ch2 in channel_ids[i+1:]:
                # Calculate temporal correlation
                ts1 = channel_messages[ch1]
                ts2 = channel_messages[ch2]
                
                if len(ts1) < 5 or len(ts2) < 5:
                    continue
                
                # Simple correlation: overlapping activity periods
                overlap = self._calculate_temporal_overlap(ts1, ts2)
                
                if overlap > 0.3:  # Threshold
                    correlation = {
                        'entity1': {'type': 'channel', 'id': ch1},
                        'entity2': {'type': 'channel', 'id': ch2},
                        'strength': overlap,
                        'type': 'temporal_overlap',
                    }
                    correlations.append(correlation)
                    self.store.save_correlation('channel', ch1, 'channel', ch2, overlap)
        
        return correlations
    
    def discover_user_correlations(
        self,
        user_activity: Dict[int, List[datetime]]
    ) -> List[Dict[str, Any]]:
        """Discover correlations between users"""
        correlations = []
        
        user_ids = list(user_activity.keys())
        
        for i, u1 in enumerate(user_ids):
            for u2 in user_ids[i+1:]:
                ts1 = user_activity[u1]
                ts2 = user_activity[u2]
                
                if len(ts1) < 3 or len(ts2) < 3:
                    continue
                
                overlap = self._calculate_temporal_overlap(ts1, ts2)
                
                if overlap > 0.4:
                    correlation = {
                        'entity1': {'type': 'user', 'id': u1},
                        'entity2': {'type': 'user', 'id': u2},
                        'strength': overlap,
                        'type': 'activity_overlap',
                    }
                    correlations.append(correlation)
                    self.store.save_correlation('user', u1, 'user', u2, overlap)
        
        return correlations
    
    def _calculate_temporal_overlap(
        self,
        timestamps1: List[datetime],
        timestamps2: List[datetime]
    ) -> float:
        """Calculate temporal overlap between two time series"""
        if not timestamps1 or not timestamps2:
            return 0.0
        
        # Find overlapping time windows
        range1 = (min(timestamps1), max(timestamps1))
        range2 = (min(timestamps2), max(timestamps2))
        
        overlap_start = max(range1[0], range2[0])
        overlap_end = min(range1[1], range2[1])
        
        if overlap_end <= overlap_start:
            return 0.0
        
        overlap_duration = (overlap_end - overlap_start).total_seconds()
        total_duration = max(
            (range1[1] - range1[0]).total_seconds(),
            (range2[1] - range2[0]).total_seconds()
        )
        
        if total_duration == 0:
            return 0.0
        
        return overlap_duration / total_duration
