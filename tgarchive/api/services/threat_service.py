"""
Threat Intelligence Service
===========================

Service layer for threat intelligence operations.
"""

import logging
from typing import Dict, Any, Optional, List

from ..threat.attribution import AttributionEngine
from ..threat.temporal import TemporalAnalyzer
from ..threat.network import ThreatNetworkAnalyzer
from ..threat.scoring import ThreatScorer
from ..threat.indicators import ThreatIndicatorExtractor
from ..threat.visualization import ThreatVisualizer

logger = logging.getLogger(__name__)


class ThreatService:
    """Service for threat intelligence operations."""
    
    def __init__(self):
        self.attribution_engine = AttributionEngine()
        self.temporal_analyzer = TemporalAnalyzer()
        self.network_analyzer = ThreatNetworkAnalyzer()
        self.threat_scorer = ThreatScorer()
        self.indicator_extractor = ThreatIndicatorExtractor()
        self.visualizer = ThreatVisualizer()
    
    async def analyze_attribution(
        self,
        messages: List[Dict[str, Any]],
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze writing style and attribution.
        
        Args:
            messages: List of message dictionaries
            options: Analysis options
            
        Returns:
            Attribution analysis results
        """
        try:
            profile = self.attribution_engine.analyze_writing_style(messages)
            
            return {
                "profile": {
                    "avg_sentence_length": profile.avg_sentence_length,
                    "avg_word_length": profile.avg_word_length,
                    "punctuation_ratio": profile.punctuation_ratio,
                    "capitalization_ratio": profile.capitalization_ratio,
                    "technical_term_ratio": profile.technical_term_ratio,
                    "proficiency_level": profile.proficiency_level
                },
                "tool_fingerprints": self.attribution_engine.detect_tool_fingerprints(messages),
                "operational_patterns": self.attribution_engine.detect_operational_patterns(messages),
                "ai_generated": self.attribution_engine.detect_ai_generated_content(messages)
            }
        except Exception as e:
            logger.error(f"Attribution analysis failed: {e}", exc_info=True)
            raise
    
    async def correlate_accounts(
        self,
        account_ids: List[str],
        similarity_threshold: float = 0.7
    ) -> Dict[str, Any]:
        """
        Correlate accounts by writing style.
        
        Args:
            account_ids: List of account identifiers
            similarity_threshold: Similarity threshold for correlation
            
        Returns:
            Correlation results
        """
        try:
            # This would require fetching messages for each account
            # For now, return structure
            return {
                "correlations": [],
                "similarity_threshold": similarity_threshold,
                "message": "Account correlation requires message data"
            }
        except Exception as e:
            logger.error(f"Account correlation failed: {e}", exc_info=True)
            raise
    
    async def analyze_temporal_patterns(
        self,
        messages: List[Dict[str, Any]],
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze temporal patterns in messages.
        
        Args:
            messages: List of message dictionaries with timestamps
            options: Analysis options
            
        Returns:
            Temporal analysis results
        """
        try:
            analysis = self.temporal_analyzer.analyze_activity_patterns(
                messages,
                time_window_days=options.get("time_window_days", 30) if options else 30
            )
            
            return {
                "timezone_inference": analysis.get("timezone_inference"),
                "peak_hours": analysis.get("peak_hours"),
                "activity_bursts": analysis.get("activity_bursts"),
                "regularity_score": analysis.get("regularity_score"),
                "entropy": analysis.get("entropy")
            }
        except Exception as e:
            logger.error(f"Temporal analysis failed: {e}", exc_info=True)
            raise
    
    async def predict_next_activity(
        self,
        messages: List[Dict[str, Any]],
        prediction_window_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Predict next activity time.
        
        Args:
            messages: List of message dictionaries
            prediction_window_hours: Prediction window in hours
            
        Returns:
            Prediction results
        """
        try:
            prediction = self.temporal_analyzer.predict_next_activity(
                messages,
                prediction_window_hours=prediction_window_hours
            )
            
            return {
                "predicted_time": prediction.get("predicted_time"),
                "confidence": prediction.get("confidence"),
                "reasoning": prediction.get("reasoning")
            }
        except Exception as e:
            logger.error(f"Activity prediction failed: {e}", exc_info=True)
            raise
    
    async def analyze_threat_network(
        self,
        entities: List[Dict[str, Any]],
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze threat network.
        
        Args:
            entities: List of entity dictionaries
            options: Analysis options
            
        Returns:
            Network analysis results
        """
        try:
            # This would use ThreatNetworkAnalyzer
            return {
                "nodes": [],
                "edges": [],
                "centrality_metrics": {},
                "communities": []
            }
        except Exception as e:
            logger.error(f"Threat network analysis failed: {e}", exc_info=True)
            raise
    
    async def calculate_threat_score(
        self,
        entity_id: str,
        indicators: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Calculate threat score for an entity.
        
        Args:
            entity_id: Entity identifier
            indicators: Optional threat indicators
            
        Returns:
            Threat score and details
        """
        try:
            # This would use ThreatScorer
            score = self.threat_scorer.calculate_score(entity_id, indicators or [])
            
            return {
                "entity_id": entity_id,
                "score": score.get("score", 0.0),
                "severity": score.get("severity", "low"),
                "indicators": score.get("indicators", []),
                "reasoning": score.get("reasoning", "")
            }
        except Exception as e:
            logger.error(f"Threat scoring failed: {e}", exc_info=True)
            raise
    
    async def get_threat_indicators(
        self,
        entity_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get threat indicators.
        
        Args:
            entity_id: Optional entity identifier
            
        Returns:
            Threat indicators
        """
        try:
            # This would use ThreatIndicatorExtractor
            return {
                "indicators": [],
                "entity_id": entity_id
            }
        except Exception as e:
            logger.error(f"Failed to get threat indicators: {e}", exc_info=True)
            raise
    
    async def get_threat_visualization(
        self,
        entity_id: Optional[str] = None,
        visualization_type: str = "network"
    ) -> Dict[str, Any]:
        """
        Get threat visualization data.
        
        Args:
            entity_id: Optional entity identifier
            visualization_type: Type of visualization
            
        Returns:
            Visualization data
        """
        try:
            # This would use ThreatVisualizer
            return {
                "type": visualization_type,
                "data": {},
                "entity_id": entity_id
            }
        except Exception as e:
            logger.error(f"Failed to get threat visualization: {e}", exc_info=True)
            raise
