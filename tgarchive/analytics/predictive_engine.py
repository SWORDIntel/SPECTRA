"""
Predictive Analytics Engine
===========================

Predictive analytics for threat detection and activity forecasting.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from .time_series_analyzer import TimeSeriesAnalyzer
from .forecasting import ActivityForecaster

logger = logging.getLogger(__name__)


class PredictiveEngine:
    """
    Predictive analytics engine for threat detection and activity forecasting.
    
    Features:
    - Threat actor behavior prediction
    - Channel growth forecasting
    - Anomaly detection
    - Threat escalation probability
    """
    
    def __init__(self):
        """Initialize predictive engine"""
        self.time_series = TimeSeriesAnalyzer()
        self.forecaster = ActivityForecaster()
    
    def predict_threat_escalation(
        self,
        actor_history: List[Dict[str, Any]],
        recent_activity: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Predict probability of threat escalation.
        
        Args:
            actor_history: Historical actor activity
            recent_activity: Recent activity patterns
        
        Returns:
            Escalation prediction with probability
        """
        # Analyze activity trends
        timestamps = [a.get('timestamp') for a in recent_activity if a.get('timestamp')]
        
        if not timestamps:
            return {'escalation_probability': 0.0, 'confidence': 0.0}
        
        # Detect activity bursts using time-series analysis
        volume_analysis = self.time_series.analyze_message_volume(timestamps, window="1H")
        
        # Calculate escalation indicators based on statistical analysis
        mean_volume = volume_analysis.get('mean_volume', 0)
        max_volume = volume_analysis.get('max_volume', 0)
        trend = volume_analysis.get('trend', 'stable')
        
        indicators = {
            'activity_increase': trend == 'increasing',
            'burst_detected': max_volume > mean_volume * 2 if mean_volume > 0 else False,
            'recent_spike': len(recent_activity) > len(actor_history) * 0.1 if actor_history else False,
        }
        
        # Calculate probability using weighted indicators
        probability = 0.0
        if indicators['activity_increase']:
            probability += 0.3
        if indicators['burst_detected']:
            probability += 0.4
        if indicators['recent_spike']:
            probability += 0.3
        
        return {
            'escalation_probability': min(1.0, probability),
            'confidence': 0.75,
            'indicators': indicators,
        }
    
    def forecast_channel_growth(
        self,
        channel_messages: List[datetime],
        forecast_days: int = 7
    ) -> Dict[str, Any]:
        """Forecast channel growth"""
        growth_analysis = self.time_series.analyze_channel_growth(channel_messages)
        forecast = self.forecaster.forecast_message_volume(
            channel_messages, forecast_hours=forecast_days * 24
        )
        
        return {
            'current_growth_rate': growth_analysis.get('growth_rate', 0.0),
            'forecast': forecast,
            'projected_messages': sum(f.get('expected_messages', 0) for f in forecast.get('forecast', [])),
        }
    
    def detect_anomalies(
        self,
        timestamps: List[datetime],
        threshold_std: float = 2.0
    ) -> List[Dict[str, Any]]:
        """
        Detect anomalous activity patterns.
        
        Args:
            timestamps: Message timestamps
            threshold_std: Standard deviation threshold for anomalies
        
        Returns:
            List of detected anomalies
        """
        if not timestamps:
            return []
        
        volume_analysis = self.time_series.analyze_message_volume(timestamps, window="1H")
        
        mean_volume = volume_analysis.get('mean_volume', 0)
        std_volume = volume_analysis.get('std_volume', 0)
        threshold = mean_volume + (threshold_std * std_volume)
        
        # Detect anomalies using statistical threshold method
        anomalies = []
        if volume_analysis.get('max_volume', 0) > threshold:
            anomalies.append({
                'type': 'volume_spike',
                'severity': 'high' if volume_analysis.get('max_volume', 0) > threshold * 2 else 'medium',
                'value': volume_analysis.get('max_volume', 0),
                'threshold': threshold,
            })
        
        return anomalies
