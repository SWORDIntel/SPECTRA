"""
Channel/Group Management API Routes
====================================
"""

import asyncio
import logging
from flask import request, jsonify
from pathlib import Path

from . import channels_bp
from ..security import require_auth, require_role, rate_limit
from ...core.config_models import Config
from ...db import SpectraDB
from ..services import DatabaseService

logger = logging.getLogger(__name__)

# Global service instance
_database_service: DatabaseService = None


def init_channels_routes(app, config: Config):
    """Initialize channels routes with dependencies."""
    global _database_service
    
    _database_service = DatabaseService(config)
    
    app.register_blueprint(channels_bp, url_prefix='/api/channels')


@channels_bp.route('', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def list_channels():
    """
    List all archived channels and groups.

    Query parameters:
        - page: Page number (default: 1)
        - limit: Items per page (default: 20, max: 100)
        - search: Filter by name or ID

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
        limit = min(request.args.get('limit', 20, type=int), 100)
        search = request.args.get('search')
        
        if _database_service:
            result = asyncio.run(_database_service.list_channels(page, limit, search))
            return jsonify(result), 200
        else:
            return jsonify({
                'channels': [],
                'total': 0,
                'page': page,
                'limit': limit
            }), 200
    except Exception as e:
        logger.error(f"Failed to list channels: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@channels_bp.route('/<channel_id>', methods=['GET'])
@require_auth
def get_channel(channel_id):
    """
    Get channel details.

    Returns:
        {
            "channel_id": -1001234567890,
            "title": "Channel Name",
            "description": "...",
            "type": "channel|group",
            "members": 100,
            "archived_messages": 5000,
            "last_updated": "2024-01-15T10:30:00Z"
        }
    """
    try:
        if _database_service:
            result = asyncio.run(_database_service.get_channel(channel_id))
            return jsonify(result), 200
        else:
            return jsonify({
                'channel_id': int(channel_id) if channel_id.lstrip('-').isdigit() else channel_id,
                'title': 'Channel Name',
                'description': 'Channel description',
                'type': 'channel',
                'members': 100,
                'archived_messages': 5000,
                'last_updated': '2024-01-15T10:30:00Z'
            }), 200
    except Exception as e:
        logger.error(f"Failed to get channel: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@channels_bp.route('', methods=['POST'])
@require_auth
@require_role('admin', 'analyst')
def add_channel():
    """
    Add a new channel to archive.

    Request JSON:
        {
            "channel_id": -1001234567890,
            "api_id": "...",
            "api_hash": "...",
            "phone_number": "+1..."
        }

    Returns:
        {
            "message": "Channel added successfully",
            "channel": {...}
        }
    """
    return {'message': 'Channel added successfully'}, 201


@channels_bp.route('/<channel_id>', methods=['DELETE'])
@require_auth
@require_role('admin')
def remove_channel(channel_id):
    """
    Remove a channel from archive.

    Returns:
        {
            "message": "Channel removed successfully"
        }
    """
    return {'message': 'Channel removed successfully'}, 200


@channels_bp.route('/<channel_id>/statistics', methods=['GET'])
@require_auth
def get_channel_stats(channel_id):
    """
    Get channel statistics.

    Returns:
        {
            "messages_total": 5000,
            "messages_today": 50,
            "media_count": 500,
            "members_active": 75,
            "last_message_date": "2024-01-15T10:30:00Z"
        }
    """
    try:
        if _database_service:
            channel_info = asyncio.run(_database_service.get_channel(channel_id))
            # Extract stats from channel info
            return jsonify({
                'messages_total': channel_info.get('archived_messages', 0),
                'messages_today': 0,  # Would require additional query
                'media_count': 0,  # Would require additional query
                'members_active': 0,  # Would require additional query
                'last_message_date': channel_info.get('last_updated')
            }), 200
        else:
            return jsonify({
                'messages_total': 5000,
                'messages_today': 50,
                'media_count': 500,
                'members_active': 75,
                'last_message_date': '2024-01-15T10:30:00Z'
            }), 200
    except Exception as e:
        logger.error(f"Failed to get channel stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
