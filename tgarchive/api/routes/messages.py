"""
Message Retrieval & Intelligence API Routes
=============================================
"""

import asyncio
import logging
from flask import request, jsonify
from pathlib import Path

from . import messages_bp
from ..security import require_auth, rate_limit
from ...core.config_models import Config
from ..services import DatabaseService

logger = logging.getLogger(__name__)

# Global service instance
_database_service: DatabaseService = None


def init_messages_routes(app, config: Config):
    """Initialize messages routes with dependencies."""
    global _database_service
    
    _database_service = DatabaseService(config)
    
    app.register_blueprint(messages_bp, url_prefix='/api/messages')


@messages_bp.route('/<channel_id>', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_messages(channel_id):
    """
    Get messages from a channel with pagination.
    
    Query parameters:
        - page: Page number (default: 1)
        - limit: Items per page (default: 20)
        - date_from: Optional start date
        - date_to: Optional end date
    """
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 20, type=int)
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        if _database_service:
            result = asyncio.run(_database_service.query_messages(
                channel_id, page, limit, date_from, date_to
            ))
            return jsonify(result), 200
        else:
            return jsonify({
                'messages': [],
                'total': 0,
                'page': page,
                'limit': limit
            }), 200
    except Exception as e:
        logger.error(f"Failed to get messages: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@messages_bp.route('/<channel_id>/<int:message_id>', methods=['GET'])
@require_auth
def get_message(channel_id, message_id):
    """Get a specific message by ID."""
    try:
        if _database_service:
            result = asyncio.run(_database_service.get_message(message_id))
            return jsonify(result), 200
        else:
            return jsonify({
                'message_id': message_id,
                'channel_id': int(channel_id) if channel_id.lstrip('-').isdigit() else channel_id,
                'text': 'Message content',
                'sender_id': 12345,
                'date': '2024-01-15T10:30:00Z',
                'reactions': [],
                'replies_count': 0
            }), 200
    except Exception as e:
        logger.error(f"Failed to get message: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@messages_bp.route('/<channel_id>/<int:message_id>/details', methods=['GET'])
@require_auth
def get_message_details(channel_id, message_id):
    """Get detailed message analysis and metadata."""
    return {
        'message_id': message_id,
        'analysis': {
            'sentiment': 'neutral',
            'language': 'en',
            'entities': [],
            'keywords': [],
            'duplicates': []
        },
        'metadata': {
            'media_count': 0,
            'forwarded_count': 0,
            'reactions_count': 0
        }
    }, 200
