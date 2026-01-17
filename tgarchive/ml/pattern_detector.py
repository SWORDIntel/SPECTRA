"""
Pattern Detector
================

Detect patterns in message content and user behavior.
"""

import logging
from typing import List, Dict, Any, Optional
import numpy as np

from .learning_store import LearningStore

logger = logging.getLogger(__name__)


class PatternDetector:
    """
    Pattern detection system for continuous learning.
    
    Detects:
    - Message content patterns
    - User behavior patterns
    - Temporal patterns
    - Network relationship patterns
    """
    
    def __init__(self, learning_store: LearningStore):
        """Initialize pattern detector"""
        self.store = learning_store
    
    def detect_content_patterns(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect patterns in message content"""
        patterns = []
        
        # Simple pattern: repeated phrases
        phrase_counts = {}
        for msg in messages:
            content = msg.get('content', '')
            words = content.split()
            for i in range(len(words) - 2):
                phrase = ' '.join(words[i:i+3])
                phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1
        
        # Find repeated phrases
        for phrase, count in phrase_counts.items():
            if count >= 3:  # Threshold
                pattern = {
                    'type': 'repeated_phrase',
                    'pattern': phrase,
                    'frequency': count,
                    'confidence': min(1.0, count / len(messages)),
                }
                patterns.append(pattern)
                self.store.save_pattern('content', pattern, pattern['confidence'])
        
        return patterns
    
    def detect_user_behavior_patterns(
        self,
        user_activity: Dict[int, List[datetime]]
    ) -> List[Dict[str, Any]]:
        """Detect user behavior patterns"""
        patterns = []
        
        for user_id, timestamps in user_activity.items():
            if len(timestamps) < 5:
                continue
            
            # Calculate activity intervals
            sorted_times = sorted(timestamps)
            intervals = [
                (sorted_times[i+1] - sorted_times[i]).total_seconds() / 3600
                for i in range(len(sorted_times) - 1)
            ]
            
            if intervals:
                mean_interval = np.mean(intervals)
                std_interval = np.std(intervals)
                
                # Pattern: regular posting
                if std_interval < mean_interval * 0.5:
                    pattern = {
                        'type': 'regular_posting',
                        'user_id': user_id,
                        'mean_interval_hours': float(mean_interval),
                        'confidence': 0.8,
                    }
                    patterns.append(pattern)
                    self.store.save_pattern('user_behavior', pattern, pattern['confidence'])
        
        return patterns
    
    def detect_temporal_patterns(self, timestamps: List[datetime]) -> List[Dict[str, Any]]:
        """Detect temporal patterns"""
        patterns = []
        
        # Group by hour
        hour_counts = {}
        for ts in timestamps:
            hour = ts.hour
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
        
        # Find peak hours
        if hour_counts:
            max_hour = max(hour_counts.items(), key=lambda x: x[1])
            if max_hour[1] > len(timestamps) * 0.2:  # 20% threshold
                pattern = {
                    'type': 'peak_hour',
                    'hour': max_hour[0],
                    'frequency': max_hour[1],
                    'confidence': max_hour[1] / len(timestamps),
                }
                patterns.append(pattern)
                self.store.save_pattern('temporal', pattern, pattern['confidence'])
        
        return patterns
