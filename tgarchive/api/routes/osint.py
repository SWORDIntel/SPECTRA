"""
OSINT API Routes
================

OSINT target management and scanning endpoints.
"""

import asyncio
import logging
from flask import request, jsonify
from pathlib import Path

from . import osint_bp
from ..security import require_auth, rate_limit
from ...core.config_models import Config
from ...db import SpectraDB
from ...osint.intelligence import IntelligenceCollector

logger = logging.getLogger(__name__)

# Global service instances
_config: Config = None
_db: SpectraDB = None
_intelligence_collector: IntelligenceCollector = None


def init_osint_routes(app, config: Config):
    """Initialize OSINT routes with dependencies."""
    global _config, _db, _intelligence_collector
    
    _config = config
    db_path = Path(config.data.get("db_path", "spectra.db"))
    _db = SpectraDB(db_path)
    
    # IntelligenceCollector requires a client, which we'll initialize on demand
    app.register_blueprint(osint_bp, url_prefix='/api/osint')


@osint_bp.route('/targets', methods=['POST'])
@require_auth
@rate_limit(limit=10, per='user')
def add_target():
    """
    Add a target to OSINT tracking.
    
    Request JSON:
        {
            "user": "@target_username",
            "notes": "Person of interest"
        }
    
    Returns:
        {
            "message": "Target added successfully",
            "target": {...}
        }
    """
    try:
        data = request.get_json() or {}
        user = data.get('user')
        notes = data.get('notes', '')
        
        if not user:
            return jsonify({'error': 'user is required'}), 400
        
        result = asyncio.run(_add_target_async(user, notes))
        
        return jsonify(result), 201
    except Exception as e:
        logger.error(f"Failed to add target: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


async def _add_target_async(user: str, notes: str):
    """Add target asynchronously."""
    from telethon import TelegramClient
    
    account = _config.auto_select_account()
    if not account:
        return {"error": "No account available"}
    
    client = TelegramClient(account['session_name'], account['api_id'], account['api_hash'])
    await client.connect()
    
    try:
        collector = IntelligenceCollector(_config, _db, client)
        await collector.add_target(user, notes)
        return {
            "message": "Target added successfully",
            "target": {"user": user, "notes": notes}
        }
    finally:
        await client.disconnect()


@osint_bp.route('/targets/<target_id>', methods=['DELETE'])
@require_auth
@rate_limit(limit=10, per='user')
def remove_target(target_id):
    """
    Remove a target from OSINT tracking.
    
    Returns:
        {
            "message": "Target removed successfully"
        }
    """
    try:
        result = asyncio.run(_remove_target_async(target_id))
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to remove target: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


async def _remove_target_async(target_id: str):
    """Remove target asynchronously."""
    from telethon import TelegramClient
    
    account = _config.auto_select_account()
    if not account:
        return {"error": "No account available"}
    
    client = TelegramClient(account['session_name'], account['api_id'], account['api_hash'])
    await client.connect()
    
    try:
        collector = IntelligenceCollector(_config, _db, client)
        await collector.remove_target(target_id)
        return {"message": "Target removed successfully"}
    finally:
        await client.disconnect()


@osint_bp.route('/targets', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def list_targets():
    """
    List all OSINT targets.
    
    Returns:
        {
            "targets": [...],
            "total": 10
        }
    """
    try:
        result = asyncio.run(_list_targets_async())
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to list targets: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


async def _list_targets_async():
    """List targets asynchronously."""
    from telethon import TelegramClient
    
    account = _config.auto_select_account()
    if not account:
        return {"targets": [], "total": 0}
    
    client = TelegramClient(account['session_name'], account['api_id'], account['api_hash'])
    await client.connect()
    
    try:
        collector = IntelligenceCollector(_config, _db, client)
        await collector.list_targets()
        # list_targets prints to console, we'd need to capture output
        return {"targets": [], "total": 0, "message": "Target listing requires console output capture"}
    finally:
        await client.disconnect()


@osint_bp.route('/scan', methods=['POST'])
@require_auth
@rate_limit(limit=10, per='user')
def scan_channel():
    """
    Scan a channel for target interactions.
    
    Request JSON:
        {
            "channel": "@channel_name",
            "user": "@target_username"
        }
    
    Returns:
        {
            "task_id": "uuid",
            "status": "queued"
        }
    """
    try:
        data = request.get_json() or {}
        channel = data.get('channel')
        user = data.get('user')
        
        if not channel or not user:
            return jsonify({'error': 'channel and user are required'}), 400
        
        result = asyncio.run(_scan_channel_async(channel, user))
        
        return jsonify(result), 202
    except Exception as e:
        logger.error(f"Failed to scan channel: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


async def _scan_channel_async(channel: str, user: str):
    """Scan channel asynchronously."""
    from telethon import TelegramClient
    
    account = _config.auto_select_account()
    if not account:
        return {"error": "No account available"}
    
    client = TelegramClient(account['session_name'], account['api_id'], account['api_hash'])
    await client.connect()
    
    try:
        collector = IntelligenceCollector(_config, _db, client)
        await collector.scan_channel(channel, user)
        return {
            "message": "Scan initiated",
            "channel": channel,
            "user": user
        }
    finally:
        await client.disconnect()


@osint_bp.route('/network/<target_id>', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_target_network(target_id):
    """
    Get target interaction network.
    
    Returns:
        {
            "target_id": "...",
            "network": {
                "nodes": [...],
                "edges": [...]
            }
        }
    """
    try:
        result = asyncio.run(_get_target_network_async(target_id))
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to get target network: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


async def _get_target_network_async(target_id: str):
    """Get target network asynchronously."""
    from telethon import TelegramClient
    
    account = _config.auto_select_account()
    if not account:
        return {"error": "No account available"}
    
    client = TelegramClient(account['session_name'], account['api_id'], account['api_hash'])
    await client.connect()
    
    try:
        collector = IntelligenceCollector(_config, _db, client)
        await collector.show_network(target_id)
        # show_network prints to console, we'd need to capture output
        return {
            "target_id": target_id,
            "network": {"nodes": [], "edges": []},
            "message": "Network visualization requires console output capture"
        }
    finally:
        await client.disconnect()
