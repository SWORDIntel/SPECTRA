"""
Threat Intelligence Service
===========================

Service layer for threat intelligence operations.
"""

import logging
from typing import Dict, Any, Optional, List

from ...threat.attribution import AttributionEngine
from ...threat.temporal import TemporalAnalyzer
from ...threat.network import ThreatNetworkTracker
from ...threat.scoring import ThreatScorer
from ...threat.indicators import ThreatIndicatorDetector, ThreatIndicator
from ...threat.visualization import MermaidGenerator, ThreatReportGenerator

logger = logging.getLogger(__name__)


class ThreatService:
    """Service for threat intelligence operations."""
    
    def __init__(self):
        self.attribution_engine = AttributionEngine()
        self.temporal_analyzer = TemporalAnalyzer()
        self.network_tracker = ThreatNetworkTracker()
        self.threat_scorer = ThreatScorer()
        self.indicator_detector = ThreatIndicatorDetector()
        self.visualizer = MermaidGenerator()
        self.report_generator = ThreatReportGenerator()
    
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
            analysis = self.temporal_analyzer.analyze_activity_patterns(messages)
            prediction = self.temporal_analyzer.predict_next_activity(
                messages,
                forecast_hours=options.get("prediction_window_hours", 24) if options else 24,
            )
            
            return {
                "timezone_inference": analysis.get("inferred_timezone"),
                "peak_hours": analysis.get("peak_hours"),
                "activity_bursts": analysis.get("burst_periods"),
                "regularity_score": analysis.get("regularity_score"),
                "entropy": analysis.get("hour_distribution"),
                "prediction": prediction,
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
            if not entities:
                return {
                    "nodes": [],
                    "edges": [],
                    "centrality_metrics": {},
                    "communities": [],
                }

            for entity in entities:
                source_id = int(entity.get("source_id", entity.get("user_id", 0)))
                target_id = int(entity.get("target_id", entity.get("related_user_id", 0)))
                if source_id and target_id and source_id != target_id:
                    self.network_tracker.add_interaction(
                        source_id=source_id,
                        target_id=target_id,
                        interaction_type=entity.get("interaction_type", "same_channel"),
                        timestamp=entity.get("timestamp"),
                        message_id=entity.get("message_id"),
                        channel_id=entity.get("channel_id"),
                    )

            return {
                "nodes": [i.to_dict() for i in self.network_tracker.interactions],
                "edges": [r.to_dict() for r in self.network_tracker.relationships.values()],
                "centrality_metrics": {},
                "communities": self.network_tracker.detect_communities(),
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
            total_severity = 0.0
            normalized_indicators: List[ThreatIndicator] = []

            for indicator in indicators or []:
                if isinstance(indicator, ThreatIndicator):
                    normalized_indicators.append(indicator)
                    total_severity += float(indicator.severity)
                elif isinstance(indicator, dict):
                    severity = float(indicator.get("severity", 0.0))
                    total_severity += severity

            score = min(10.0, total_severity)
            
            return {
                "entity_id": entity_id,
                "score": score,
                "severity": "high" if score >= 7 else "medium" if score >= 4 else "low",
                "indicators": [i.to_dict() for i in normalized_indicators] if normalized_indicators else indicators or [],
                "reasoning": "Derived from indicator severities",
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
            if entity_id is None:
                return {
                    "indicators": [],
                    "entity_id": entity_id
                }

            indicators = self.indicator_detector.detect_indicators(entity_id)
            return {
                "indicators": [indicator.to_dict() for indicator in indicators],
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
            if visualization_type == "report":
                data = self.report_generator.generate_executive_report([], self.network_tracker)
            else:
                data = self.visualizer.generate_network_graph([], self.network_tracker)

            return {
                "type": visualization_type,
                "data": data,
                "entity_id": entity_id
            }
        except Exception as e:
            logger.error(f"Failed to get threat visualization: {e}", exc_info=True)
            raise
