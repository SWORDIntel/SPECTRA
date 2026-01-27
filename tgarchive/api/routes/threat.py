"""
Threat Intelligence API Routes
===============================

Threat analysis, attribution, and scoring endpoints.
"""

import asyncio
import logging
from flask import request, jsonify

from . import threat_bp
from ..security import require_auth, rate_limit
from ..services import ThreatService

logger = logging.getLogger(__name__)

# Global service instance
_threat_service: ThreatService = None


def init_threat_routes(app):
    """Initialize threat routes with dependencies."""
    global _threat_service
    
    _threat_service = ThreatService()
    
    app.register_blueprint(threat_bp, url_prefix='/api/threat')


@threat_bp.route('/attribution/analyze', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def analyze_attribution():
    """
    Analyze writing style and attribution.
    
    Request JSON:
        {
            "messages": [...],
            "options": {}
        }
    
    Returns:
        {
            "profile": {...},
            "tool_fingerprints": {...},
            "operational_patterns": {...}
        }
    """
    try:
        data = request.get_json() or {}
        messages = data.get('messages', [])
        
        if not messages:
            return jsonify({'error': 'messages array is required'}), 400
        
        options = data.get('options', {})
        result = asyncio.run(_threat_service.analyze_attribution(messages, options))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Attribution analysis failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@threat_bp.route('/attribution/correlate', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def correlate_accounts():
    """
    Correlate accounts by writing style.
    
    Request JSON:
        {
            "account_ids": ["account1", "account2"],
            "similarity_threshold": 0.7
        }
    
    Returns:
        {
            "correlations": [...],
            "similarity_threshold": 0.7
        }
    """
    try:
        data = request.get_json() or {}
        account_ids = data.get('account_ids', [])
        similarity_threshold = data.get('similarity_threshold', 0.7)
        
        if not account_ids:
            return jsonify({'error': 'account_ids array is required'}), 400
        
        result = asyncio.run(_threat_service.correlate_accounts(account_ids, similarity_threshold))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Account correlation failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@threat_bp.route('/temporal/analyze', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def analyze_temporal_patterns():
    """
    Analyze temporal patterns in messages.
    
    Request JSON:
        {
            "messages": [...],
            "options": {
                "time_window_days": 30
            }
        }
    
    Returns:
        {
            "timezone_inference": "...",
            "peak_hours": [...],
            "activity_bursts": [...]
        }
    """
    try:
        data = request.get_json() or {}
        messages = data.get('messages', [])
        
        if not messages:
            return jsonify({'error': 'messages array is required'}), 400
        
        options = data.get('options', {})
        result = asyncio.run(_threat_service.analyze_temporal_patterns(messages, options))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Temporal analysis failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@threat_bp.route('/temporal/predict', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def predict_next_activity():
    """
    Predict next activity time.
    
    Request JSON:
        {
            "messages": [...],
            "prediction_window_hours": 24
        }
    
    Returns:
        {
            "predicted_time": "2024-01-16T10:30:00Z",
            "confidence": 0.85
        }
    """
    try:
        data = request.get_json() or {}
        messages = data.get('messages', [])
        prediction_window_hours = data.get('prediction_window_hours', 24)
        
        if not messages:
            return jsonify({'error': 'messages array is required'}), 400
        
        result = asyncio.run(_threat_service.predict_next_activity(messages, prediction_window_hours))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Activity prediction failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@threat_bp.route('/network/analyze', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def analyze_threat_network():
    """
    Analyze threat network.
    
    Request JSON:
        {
            "entities": [...],
            "options": {}
        }
    
    Returns:
        {
            "nodes": [...],
            "edges": [...],
            "centrality_metrics": {...}
        }
    """
    try:
        data = request.get_json() or {}
        entities = data.get('entities', [])
        options = data.get('options', {})
        
        result = asyncio.run(_threat_service.analyze_threat_network(entities, options))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Threat network analysis failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@threat_bp.route('/scoring/calculate', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def calculate_threat_score():
    """
    Calculate threat score for an entity.
    
    Request JSON:
        {
            "entity_id": "entity123",
            "indicators": [...]
        }
    
    Returns:
        {
            "entity_id": "entity123",
            "score": 0.75,
            "severity": "high"
        }
    """
    try:
        data = request.get_json() or {}
        entity_id = data.get('entity_id')
        indicators = data.get('indicators', [])
        
        if not entity_id:
            return jsonify({'error': 'entity_id is required'}), 400
        
        result = asyncio.run(_threat_service.calculate_threat_score(entity_id, indicators))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Threat scoring failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@threat_bp.route('/indicators', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_threat_indicators():
    """
    Get threat indicators.
    
    Query parameters:
        - entity_id: Optional entity identifier
    
    Returns:
        {
            "indicators": [...],
            "entity_id": "..."
        }
    """
    try:
        entity_id = request.args.get('entity_id')
        result = asyncio.run(_threat_service.get_threat_indicators(entity_id))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to get threat indicators: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@threat_bp.route('/visualization', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_threat_visualization():
    """
    Get threat visualization data.
    
    Query parameters:
        - entity_id: Optional entity identifier
        - visualization_type: Type of visualization (default: network)
    
    Returns:
        {
            "type": "network",
            "data": {...}
        }
    """
    try:
        entity_id = request.args.get('entity_id')
        visualization_type = request.args.get('visualization_type', 'network')
        
        result = asyncio.run(_threat_service.get_threat_visualization(entity_id, visualization_type))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to get threat visualization: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
