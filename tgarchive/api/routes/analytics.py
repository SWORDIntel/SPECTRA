"""
Analytics API Routes
====================

Forecasting, time series, and predictive analysis endpoints.
"""

import asyncio
import logging
from flask import request, jsonify

from . import analytics_bp
from ..security import require_auth, rate_limit
from ..services import AnalyticsService

logger = logging.getLogger(__name__)

# Global service instance
_analytics_service: AnalyticsService = None


def init_analytics_routes(app):
    """Initialize analytics routes with dependencies."""
    global _analytics_service
    
    _analytics_service = AnalyticsService()
    
    app.register_blueprint(analytics_bp, url_prefix='/api/analytics')


@analytics_bp.route('/forecast', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def generate_forecast():
    """
    Generate forecast from time series data.
    
    Request JSON:
        {
            "data": [...],
            "forecast_periods": 7,
            "options": {}
        }
    
    Returns:
        {
            "forecast": [...],
            "confidence_intervals": [...],
            "metrics": {...}
        }
    """
    try:
        data = request.get_json() or {}
        time_series_data = data.get('data', [])
        forecast_periods = data.get('forecast_periods', 7)
        options = data.get('options', {})
        
        if not time_series_data:
            return jsonify({'error': 'data array is required'}), 400
        
        result = asyncio.run(_analytics_service.generate_forecast(
            time_series_data,
            forecast_periods,
            options
        ))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Forecast generation failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/time-series', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def analyze_time_series():
    """
    Analyze time series data.
    
    Request JSON:
        {
            "data": [...],
            "options": {}
        }
    
    Returns:
        {
            "trend": {...},
            "seasonality": {...},
            "anomalies": [...]
        }
    """
    try:
        data = request.get_json() or {}
        time_series_data = data.get('data', [])
        options = data.get('options', {})
        
        if not time_series_data:
            return jsonify({'error': 'data array is required'}), 400
        
        result = asyncio.run(_analytics_service.analyze_time_series(time_series_data, options))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Time series analysis failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/predictive', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def predictive_analysis():
    """
    Perform predictive analysis.
    
    Request JSON:
        {
            "data": [...],
            "target_variable": "value",
            "options": {}
        }
    
    Returns:
        {
            "predictions": [...],
            "accuracy": 0.85,
            "feature_importance": {...}
        }
    """
    try:
        data = request.get_json() or {}
        input_data = data.get('data', [])
        target_variable = data.get('target_variable')
        options = data.get('options', {})
        
        if not input_data or not target_variable:
            return jsonify({'error': 'data and target_variable are required'}), 400
        
        result = asyncio.run(_analytics_service.predictive_analysis(
            input_data,
            target_variable,
            options
        ))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Predictive analysis failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/stats', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_analytics_stats():
    """
    Get analytics statistics.
    
    Returns:
        {
            "forecasting_available": true,
            "time_series_available": true,
            "predictive_available": true
        }
    """
    try:
        result = asyncio.run(_analytics_service.get_analytics_stats())
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to get analytics stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
