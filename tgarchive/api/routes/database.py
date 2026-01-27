"""
Database API Routes
===================

Database query and management endpoints.
"""

import asyncio
import logging
from flask import request, jsonify
from pathlib import Path

from . import database_bp
from ..security import require_auth, rate_limit
from ...core.config_models import Config
from ..services import DatabaseService

logger = logging.getLogger(__name__)

# Global service instance
_database_service: DatabaseService = None


def init_database_routes(app, config: Config):
    """Initialize database routes with dependencies."""
    global _database_service
    
    _database_service = DatabaseService(config)
    
    app.register_blueprint(database_bp, url_prefix='/api/database')


@database_bp.route('/channels', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def list_channels():
    """
    List channels from database.
    
    Query parameters:
        - page: Page number (default: 1)
        - limit: Items per page (default: 20)
        - search: Optional search term
    
    Returns:
        {
            "channels": [...],
            "total": 100,
            "page": 1,
            "limit": 20
        }
    """
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 20, type=int)
        search = request.args.get('search')
        
        result = asyncio.run(_database_service.list_channels(page, limit, search))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to list channels: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@database_bp.route('/channels/<channel_id>', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_channel(channel_id):
    """
    Get channel details.
    
    Returns:
        {
            "channel_id": -1001234567890,
            "title": "Channel Name",
            "archived_messages": 5000
        }
    """
    try:
        result = asyncio.run(_database_service.get_channel(channel_id))
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to get channel: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@database_bp.route('/messages', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def query_messages():
    """
    Query messages from database.
    
    Query parameters:
        - channel_id: Optional channel identifier
        - page: Page number (default: 1)
        - limit: Items per page (default: 20)
        - date_from: Optional start date
        - date_to: Optional end date
    
    Returns:
        {
            "messages": [...],
            "total": 1000,
            "page": 1
        }
    """
    try:
        channel_id = request.args.get('channel_id')
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 20, type=int)
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        result = asyncio.run(_database_service.query_messages(
            channel_id, page, limit, date_from, date_to
        ))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to query messages: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@database_bp.route('/messages/<int:message_id>', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_message(message_id):
    """
    Get message details.
    
    Returns:
        {
            "message_id": 12345,
            "text": "...",
            "sender_id": 67890
        }
    """
    try:
        result = asyncio.run(_database_service.get_message(message_id))
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to get message: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@database_bp.route('/users', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def query_users():
    """
    Query users from database.
    
    Query parameters:
        - page: Page number (default: 1)
        - limit: Items per page (default: 20)
        - search: Optional search term
    
    Returns:
        {
            "users": [...],
            "total": 500,
            "page": 1
        }
    """
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 20, type=int)
        search = request.args.get('search')
        
        result = asyncio.run(_database_service.query_users(page, limit, search))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to query users: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@database_bp.route('/media', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def query_media():
    """
    Query media from database.
    
    Query parameters:
        - channel_id: Optional channel identifier
        - page: Page number (default: 1)
        - limit: Items per page (default: 20)
        - media_type: Optional media type filter
    
    Returns:
        {
            "media": [...],
            "total": 200,
            "page": 1
        }
    """
    try:
        channel_id = request.args.get('channel_id')
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 20, type=int)
        media_type = request.args.get('media_type')
        
        result = asyncio.run(_database_service.query_media(
            channel_id, page, limit, media_type
        ))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to query media: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@database_bp.route('/stats', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_database_stats():
    """
    Get database statistics.
    
    Returns:
        {
            "total_channels": 100,
            "total_messages": 50000,
            "total_users": 1000
        }
    """
    try:
        result = asyncio.run(_database_service.get_database_stats())
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to get database stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@database_bp.route('/migrate', methods=['POST'])
@require_auth
@rate_limit(limit=5, per='user')
def start_migration():
    """
    Start a migration.
    
    Request JSON:
        {
            "source": "/path/to/source",
            "destination": "/path/to/dest",
            "options": {}
        }
    
    Returns:
        {
            "migration_id": 1,
            "status": "queued"
        }
    """
    try:
        data = request.get_json() or {}
        source = data.get('source')
        destination = data.get('destination')
        options = data.get('options', {})
        
        if not source or not destination:
            return jsonify({'error': 'source and destination are required'}), 400
        
        result = asyncio.run(_database_service.start_migration(source, destination, options))
        
        return jsonify(result), 202
    except Exception as e:
        logger.error(f"Failed to start migration: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@database_bp.route('/migrate/<int:migration_id>', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_migration_status(migration_id):
    """
    Get migration status.
    
    Returns:
        {
            "migration_id": 1,
            "status": "running",
            "progress": 45.0
        }
    """
    try:
        result = asyncio.run(_database_service.get_migration_status(migration_id))
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to get migration status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
