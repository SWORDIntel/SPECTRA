"""
ML/AI API Routes
================

Machine learning and AI operations endpoints.
"""

import asyncio
import logging
from flask import request, jsonify

from . import ml_bp
from ..security import require_auth, rate_limit
from ..services import MLService

logger = logging.getLogger(__name__)

# Global service instance
_ml_service: MLService = None


def init_ml_routes(app):
    """Initialize ML/AI routes with dependencies."""
    global _ml_service
    
    _ml_service = MLService()
    
    app.register_blueprint(ml_bp, url_prefix='/api/ml')


@ml_bp.route('/patterns/detect', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def detect_patterns():
    """
    Detect patterns in data.
    
    Request JSON:
        {
            "data": [...],
            "pattern_type": "all",
            "options": {}
        }
    
    Returns:
        {
            "patterns": [...],
            "confidence": {...}
        }
    """
    try:
        data = request.get_json() or {}
        input_data = data.get('data', [])
        pattern_type = data.get('pattern_type', 'all')
        options = data.get('options', {})
        
        if not input_data:
            return jsonify({'error': 'data array is required'}), 400
        
        result = asyncio.run(_ml_service.detect_patterns(input_data, pattern_type, options))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Pattern detection failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@ml_bp.route('/correlation/analyze', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def analyze_correlation():
    """
    Analyze correlations between entities.
    
    Request JSON:
        {
            "entities": [...],
            "correlation_type": "behavioral",
            "options": {}
        }
    
    Returns:
        {
            "correlations": [...],
            "strength": {...},
            "graph": {...}
        }
    """
    try:
        data = request.get_json() or {}
        entities = data.get('entities', [])
        correlation_type = data.get('correlation_type', 'behavioral')
        options = data.get('options', {})
        
        if not entities:
            return jsonify({'error': 'entities array is required'}), 400
        
        result = asyncio.run(_ml_service.analyze_correlation(entities, correlation_type, options))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Correlation analysis failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@ml_bp.route('/entities/extract', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def extract_entities():
    """
    Extract entities from text.
    
    Request JSON:
        {
            "text": "Sample text...",
            "entity_types": ["person", "location"],
            "options": {}
        }
    
    Returns:
        {
            "entities": [...],
            "confidence": {...}
        }
    """
    try:
        data = request.get_json() or {}
        text = data.get('text', '')
        entity_types = data.get('entity_types')
        options = data.get('options', {})
        
        if not text:
            return jsonify({'error': 'text is required'}), 400
        
        result = asyncio.run(_ml_service.extract_entities(text, entity_types, options))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Entity extraction failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@ml_bp.route('/semantic/search', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def semantic_search():
    """
    Perform semantic search.
    
    Request JSON:
        {
            "query": "search query",
            "limit": 10,
            "options": {}
        }
    
    Returns:
        {
            "results": [...],
            "total": 100,
            "query": "search query"
        }
    """
    try:
        data = request.get_json() or {}
        query = data.get('query', '')
        limit = data.get('limit', 10)
        options = data.get('options', {})
        
        if not query:
            return jsonify({'error': 'query is required'}), 400
        
        result = asyncio.run(_ml_service.semantic_search(query, limit, options))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Semantic search failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@ml_bp.route('/models', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def list_models():
    """
    List available ML models.
    
    Returns:
        {
            "models": [...]
        }
    """
    try:
        result = asyncio.run(_ml_service.list_models())
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to list models: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@ml_bp.route('/models/train', methods=['POST'])
@require_auth
@rate_limit(limit=5, per='user')
def train_model():
    """
    Train an ML model.
    
    Request JSON:
        {
            "model_name": "pattern_detector",
            "training_data": [...],
            "options": {}
        }
    
    Returns:
        {
            "model_name": "pattern_detector",
            "status": "completed",
            "metrics": {...}
        }
    """
    try:
        data = request.get_json() or {}
        model_name = data.get('model_name')
        training_data = data.get('training_data', [])
        options = data.get('options', {})
        
        if not model_name or not training_data:
            return jsonify({'error': 'model_name and training_data are required'}), 400
        
        result = asyncio.run(_ml_service.train_model(model_name, training_data, options))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Model training failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
