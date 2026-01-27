"""
Analytics Service
=================

Service layer for analytics operations.
"""

import logging
from typing import Dict, Any, Optional, List

try:
    from ..analytics.forecasting import ForecastingEngine
    from ..analytics.time_series_analyzer import TimeSeriesAnalyzer
    from ..analytics.predictive_engine import PredictiveEngine
    ANALYTICS_AVAILABLE = True
except ImportError:
    ANALYTICS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Analytics modules not available")

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for analytics operations."""
    
    def __init__(self):
        if ANALYTICS_AVAILABLE:
            self.forecasting_engine = ForecastingEngine()
            self.time_series_analyzer = TimeSeriesAnalyzer()
            self.predictive_engine = PredictiveEngine()
        else:
            self.forecasting_engine = None
            self.time_series_analyzer = None
            self.predictive_engine = None
    
    async def generate_forecast(
        self,
        data: List[Dict[str, Any]],
        forecast_periods: int = 7,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate forecast from time series data.
        
        Args:
            data: Time series data
            forecast_periods: Number of periods to forecast
            options: Forecast options
            
        Returns:
            Forecast results
        """
        if not self.forecasting_engine:
            return {"error": "Forecasting engine not available"}
        
        try:
            forecast = self.forecasting_engine.forecast(
                data,
                periods=forecast_periods,
                **options or {}
            )
            
            return {
                "forecast": forecast.get("values", []),
                "confidence_intervals": forecast.get("confidence_intervals", []),
                "metrics": forecast.get("metrics", {})
            }
        except Exception as e:
            logger.error(f"Forecast generation failed: {e}", exc_info=True)
            raise
    
    async def analyze_time_series(
        self,
        data: List[Dict[str, Any]],
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze time series data.
        
        Args:
            data: Time series data
            options: Analysis options
            
        Returns:
            Time series analysis results
        """
        if not self.time_series_analyzer:
            return {"error": "Time series analyzer not available"}
        
        try:
            analysis = self.time_series_analyzer.analyze(
                data,
                **options or {}
            )
            
            return {
                "trend": analysis.get("trend", {}),
                "seasonality": analysis.get("seasonality", {}),
                "anomalies": analysis.get("anomalies", []),
                "statistics": analysis.get("statistics", {})
            }
        except Exception as e:
            logger.error(f"Time series analysis failed: {e}", exc_info=True)
            raise
    
    async def predictive_analysis(
        self,
        data: List[Dict[str, Any]],
        target_variable: str,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform predictive analysis.
        
        Args:
            data: Input data
            target_variable: Target variable to predict
            options: Analysis options
            
        Returns:
            Predictive analysis results
        """
        if not self.predictive_engine:
            return {"error": "Predictive engine not available"}
        
        try:
            prediction = self.predictive_engine.predict(
                data,
                target=target_variable,
                **options or {}
            )
            
            return {
                "predictions": prediction.get("predictions", []),
                "accuracy": prediction.get("accuracy", 0.0),
                "feature_importance": prediction.get("feature_importance", {})
            }
        except Exception as e:
            logger.error(f"Predictive analysis failed: {e}", exc_info=True)
            raise
    
    async def get_analytics_stats(self) -> Dict[str, Any]:
        """
        Get analytics statistics.
        
        Returns:
            Analytics statistics
        """
        return {
            "forecasting_available": self.forecasting_engine is not None,
            "time_series_available": self.time_series_analyzer is not None,
            "predictive_available": self.predictive_engine is not None
        }
