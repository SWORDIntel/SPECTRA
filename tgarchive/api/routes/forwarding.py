"""
Forwarding API Routes
=====================

Message forwarding and scheduling endpoints.
"""

import asyncio
import logging
from flask import request, jsonify
from pathlib import Path

from . import forwarding_bp
from ..security import require_auth, rate_limit
from ...core.config_models import Config
from ...db import SpectraDB
from ..services import ForwardingService, TaskManager

logger = logging.getLogger(__name__)

# Global service instances
_forwarding_service: ForwardingService = None


def init_forwarding_routes(app, config: Config, task_manager: TaskManager):
    """Initialize forwarding routes with dependencies."""
    global _forwarding_service
    
    db = SpectraDB(Path(config.data.get("db_path", "spectra.db")))
    _forwarding_service = ForwardingService(config, task_manager, db)
    
    app.register_blueprint(forwarding_bp, url_prefix='/api/forwarding')


@forwarding_bp.route('/messages', methods=['POST'])
@require_auth
@rate_limit(limit=10, per='user')
def forward_messages():
    """
    Forward messages from origin to destination.
    
    Request JSON:
        {
            "origin_id": "@source_channel",
            "destination_id": "@dest_channel",
            "account_identifier": "spectra_1",
            "options": {}
        }
    
    Returns:
        {
            "task_id": "uuid",
            "forward_id": "uuid",
            "status": "queued"
        }
    """
    try:
        data = request.get_json() or {}
        origin_id = data.get('origin_id')
        destination_id = data.get('destination_id')
        
        if not origin_id or not destination_id:
            return jsonify({'error': 'origin_id and destination_id are required'}), 400
        
        account_identifier = data.get('account_identifier')
        options = data.get('options', {})
        
        result = asyncio.run(_forwarding_service.forward_messages(
            origin_id,
            destination_id,
            account_identifier,
            options
        ))
        
        return jsonify(result), 202
    except Exception as e:
        logger.error(f"Forward request failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@forwarding_bp.route('/batch', methods=['POST'])
@require_auth
@rate_limit(limit=5, per='user')
def batch_forward():
    """
    Batch forwarding operations.
    
    Request JSON:
        {
            "forwards": [
                {
                    "origin_id": "@source1",
                    "destination_id": "@dest"
                }
            ],
            "options": {}
        }
    
    Returns:
        {
            "task_ids": ["uuid1", "uuid2"],
            "total": 2
        }
    """
    try:
        data = request.get_json() or {}
        forwards = data.get('forwards', [])
        
        if not forwards:
            return jsonify({'error': 'forwards array is required'}), 400
        
        task_ids = []
        shared_options = data.get('options', {})
        for forward in forwards:
            forward_options = dict(shared_options)
            forward_options.update(forward.get('options', {}))
            result = asyncio.run(_forwarding_service.forward_messages(
                forward.get('origin_id'),
                forward.get('destination_id'),
                forward.get('account_identifier'),
                forward_options
            ))
            task_ids.append(result['task_id'])
        
        return jsonify({
            "task_ids": task_ids,
            "total": len(task_ids)
        }), 202
    except Exception as e:
        logger.error(f"Batch forward request failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@forwarding_bp.route('/<forward_id>/status', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_forward_status(forward_id):
    """Get forwarding status."""
    try:
        result = asyncio.run(_forwarding_service.get_forward_status(forward_id))
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to get forward status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@forwarding_bp.route('/all-dialogs', methods=['POST'])
@require_auth
@rate_limit(limit=5, per='user')
def forward_all_dialogs():
    """
    Forward all dialogs to destination.
    
    Request JSON:
        {
            "destination_id": "@dest_channel",
            "account_identifier": "spectra_1",
            "options": {}
        }
    
    Returns:
        {
            "task_id": "uuid",
            "status": "queued"
        }
    """
    try:
        data = request.get_json() or {}
        destination_id = data.get('destination_id')
        
        if not destination_id:
            return jsonify({'error': 'destination_id is required'}), 400
        
        account_identifier = data.get('account_identifier')
        options = data.get('options', {})
        
        result = asyncio.run(_forwarding_service.forward_all_dialogs(
            destination_id,
            account_identifier,
            options
        ))
        
        return jsonify(result), 202
    except Exception as e:
        logger.error(f"Forward all dialogs request failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@forwarding_bp.route('/total-mode', methods=['POST'])
@require_auth
@rate_limit(limit=5, per='user')
def forward_total_mode():
    """
    Forward all accessible channels (total mode).
    
    Request JSON:
        {
            "destination_id": "@dest_channel",
            "account_identifier": "spectra_1",
            "options": {}
        }
    
    Returns:
        {
            "task_id": "uuid",
            "status": "queued"
        }
    """
    try:
        data = request.get_json() or {}
        destination_id = data.get('destination_id')
        
        if not destination_id:
            return jsonify({'error': 'destination_id is required'}), 400
        
        account_identifier = data.get('account_identifier')
        options = data.get('options', {})
        
        result = asyncio.run(_forwarding_service.forward_total_mode(
            destination_id,
            account_identifier,
            options
        ))
        
        return jsonify(result), 202
    except Exception as e:
        logger.error(f"Total mode forward request failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@forwarding_bp.route('/schedules', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def list_forwarding_schedules():
    """List all forwarding schedules."""
    try:
        result = asyncio.run(_forwarding_service.get_forwarding_schedules())
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to list schedules: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@forwarding_bp.route('/schedules', methods=['POST'])
@require_auth
@rate_limit(limit=10, per='user')
def create_forwarding_schedule():
    """
    Create a forwarding schedule.
    
    Request JSON:
        {
            "channel_id": -1001234567890,
            "destination": "@dest_channel",
            "schedule": "*/5 * * * *"
        }
    
    Returns:
        {
            "message": "Schedule created successfully"
        }
    """
    try:
        data = request.get_json() or {}
        channel_id = data.get('channel_id')
        destination = data.get('destination')
        schedule = data.get('schedule')
        
        if not all([channel_id, destination, schedule]):
            return jsonify({'error': 'channel_id, destination, and schedule are required'}), 400
        
        result = asyncio.run(_forwarding_service.create_forwarding_schedule(
            channel_id,
            destination,
            schedule
        ))
        
        return jsonify(result), 201
    except Exception as e:
        logger.error(f"Failed to create schedule: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@forwarding_bp.route('/schedules/<int:schedule_id>', methods=['DELETE'])
@require_auth
@rate_limit(limit=10, per='user')
def delete_forwarding_schedule(schedule_id):
    """Delete a forwarding schedule."""
    try:
        result = asyncio.run(_forwarding_service.delete_forwarding_schedule(schedule_id))
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to delete schedule: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
