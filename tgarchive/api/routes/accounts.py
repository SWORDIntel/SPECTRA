"""
Account Management API Routes
==============================

Account CRUD and management endpoints.
"""

import asyncio
import logging
import re
from flask import request, jsonify
from pathlib import Path

from . import accounts_bp
from ..security import require_auth, require_role, rate_limit
from ...core.config_models import Config
from ...utils.discovery import GroupManager
from ...db import SpectraDB

logger = logging.getLogger(__name__)

# Global service instances
_config: Config = None
_group_manager: GroupManager = None

_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _public_account(account: dict) -> dict:
    """Return account metadata without reusable Telegram credentials."""
    public = {
        "session_name": account.get("session_name"),
        "api_id": account.get("api_id"),
    }
    if account.get("phone_number"):
        public["phone_number"] = account.get("phone_number")
    if account.get("api_hash"):
        public["api_hash_configured"] = True
    if account.get("password"):
        public["password_configured"] = True
    return public


def _refresh_group_manager() -> None:
    """Rebuild account rotation state after config account mutations."""
    global _group_manager

    db_path = Path(_config.data.get("db_path", "spectra.db"))
    _group_manager = GroupManager(_config, db_path=db_path)


def _validate_account_payload(data: dict, require_all: bool = True):
    required = ("api_id", "api_hash", "session_name")
    if require_all and not all(data.get(field) for field in required):
        return "api_id, api_hash, and session_name are required"

    if "api_id" in data:
        try:
            api_id = int(data["api_id"])
        except (TypeError, ValueError):
            return "api_id must be an integer"
        if api_id <= 0:
            return "api_id must be a positive integer"
        data["api_id"] = api_id

    if "api_hash" in data and data.get("api_hash") is not None:
        api_hash = str(data["api_hash"]).strip()
        if not api_hash:
            return "api_hash cannot be empty"
        data["api_hash"] = api_hash

    if "session_name" in data:
        session_name = str(data["session_name"]).strip()
        if not _SESSION_NAME_RE.fullmatch(session_name):
            return "session_name may only contain letters, numbers, dot, dash, and underscore"
        data["session_name"] = session_name

    if "phone_number" in data and data.get("phone_number") is not None:
        data["phone_number"] = str(data["phone_number"]).strip()

    return None


def init_accounts_routes(app, config: Config):
    """Initialize accounts routes with dependencies."""
    global _config, _group_manager
    
    _config = config
    db_path = Path(config.data.get("db_path", "spectra.db"))
    _group_manager = GroupManager(config, db_path=db_path)
    
    app.register_blueprint(accounts_bp, url_prefix='/api/accounts')


@accounts_bp.route('', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def list_accounts():
    """
    List all accounts.
    
    Returns:
        {
            "accounts": [...],
            "total": 5
        }
    """
    try:
        account_stats = _group_manager.account_rotator.get_account_stats()
        
        accounts = []
        for stats in account_stats:
            accounts.append({
                "session_name": stats.get("session"),
                "usage": stats.get("usage", 0),
                "is_banned": stats.get("is_banned", False),
                "cooldown_until": stats.get("cooldown_until"),
                "last_error": stats.get("last_error")
            })
        
        return jsonify({
            "accounts": accounts,
            "total": len(accounts)
        }), 200
    except Exception as e:
        logger.error(f"Failed to list accounts: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@accounts_bp.route('/<account_id>', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_account(account_id):
    """
    Get account details.
    
    Returns:
        {
            "session_name": "spectra_1",
            "usage": 10,
            "is_banned": false,
            "status": "active"
        }
    """
    try:
        account_stats = _group_manager.account_rotator.get_account_stats()
        
        for stats in account_stats:
            if stats.get("session") == account_id:
                return jsonify({
                    "session_name": stats.get("session"),
                    "usage": stats.get("usage", 0),
                    "is_banned": stats.get("is_banned", False),
                    "cooldown_until": stats.get("cooldown_until"),
                    "last_error": stats.get("last_error"),
                    "status": "banned" if stats.get("is_banned") else "active"
                }), 200
        
        return jsonify({'error': 'Account not found'}), 404
    except Exception as e:
        logger.error(f"Failed to get account: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@accounts_bp.route('', methods=['POST'])
@require_auth
@require_role('admin')
@rate_limit(limit=10, per='user')
def add_account():
    """
    Add a new account.
    
    Request JSON:
        {
            "api_id": 123456,
            "api_hash": "0123456789abcdef",
            "session_name": "spectra_new"
        }
    
    Returns:
        {
            "message": "Account added successfully",
            "account": {...}
        }
    """
    try:
        data = request.get_json() or {}
        validation_error = _validate_account_payload(data, require_all=True)
        if validation_error:
            return jsonify({'error': validation_error}), 400

        api_id = data.get('api_id')
        api_hash = data.get('api_hash')
        session_name = data.get('session_name')
        
        # Add account to config
        if 'accounts' not in _config.data:
            _config.data['accounts'] = []

        if any(acc.get("session_name") == session_name for acc in _config.data["accounts"]):
            return jsonify({'error': 'Account session_name already exists'}), 409
        
        new_account = {
            "api_id": api_id,
            "api_hash": api_hash,
            "session_name": session_name
        }
        if data.get("phone_number"):
            new_account["phone_number"] = data["phone_number"]
        if data.get("password"):
            new_account["password"] = data["password"]
        
        _config.data['accounts'].append(new_account)
        _config.save()
        _refresh_group_manager()
        
        return jsonify({
            "message": "Account added successfully",
            "account": _public_account(new_account)
        }), 201
    except Exception as e:
        logger.error(f"Failed to add account: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@accounts_bp.route('/<account_id>', methods=['PUT'])
@require_auth
@require_role('admin')
@rate_limit(limit=10, per='user')
def update_account(account_id):
    """
    Update an account.
    
    Request JSON:
        {
            "api_id": 123456,
            "api_hash": "new_hash"
        }
    
    Returns:
        {
            "message": "Account updated successfully"
        }
    """
    try:
        data = request.get_json() or {}
        validation_error = _validate_account_payload(data, require_all=False)
        if validation_error:
            return jsonify({'error': validation_error}), 400
        
        if 'accounts' not in _config.data:
            return jsonify({'error': 'No accounts configured'}), 404
        
        # Find and update account
        for account in _config.data['accounts']:
            if account.get('session_name') == account_id:
                if 'api_id' in data:
                    account['api_id'] = data['api_id']
                if 'api_hash' in data:
                    account['api_hash'] = data['api_hash']
                if 'phone_number' in data:
                    account['phone_number'] = data['phone_number']
                if 'password' in data:
                    account['password'] = data['password']
                
                _config.save()
                _refresh_group_manager()
                return jsonify({
                    "message": "Account updated successfully",
                    "account": _public_account(account)
                }), 200
        
        return jsonify({'error': 'Account not found'}), 404
    except Exception as e:
        logger.error(f"Failed to update account: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@accounts_bp.route('/<account_id>', methods=['DELETE'])
@require_auth
@require_role('admin')
@rate_limit(limit=10, per='user')
def remove_account(account_id):
    """
    Remove an account.
    
    Returns:
        {
            "message": "Account removed successfully"
        }
    """
    try:
        if 'accounts' not in _config.data:
            return jsonify({'error': 'No accounts configured'}), 404
        
        # Find and remove account
        original_count = len(_config.data['accounts'])
        _config.data['accounts'] = [
            acc for acc in _config.data['accounts']
            if acc.get('session_name') != account_id
        ]
        
        if len(_config.data['accounts']) == original_count:
            return jsonify({'error': 'Account not found'}), 404
        
        _config.save()
        _refresh_group_manager()
        return jsonify({'message': 'Account removed successfully'}), 200
    except Exception as e:
        logger.error(f"Failed to remove account: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@accounts_bp.route('/<account_id>/test', methods=['POST'])
@require_auth
@rate_limit(limit=10, per='user')
def test_account(account_id):
    """
    Test account connectivity.
    
    Returns:
        {
            "account_id": "spectra_1",
            "status": "connected",
            "user": {...}
        }
    """
    try:
        result = asyncio.run(_test_account_connectivity(account_id))
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Account test failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


async def _test_account_connectivity(account_id):
    """Test account connectivity."""
    await _group_manager.init_clients()
    
    if account_id not in _group_manager.clients:
        return {
            "account_id": account_id,
            "status": "not_found",
            "error": "Account not initialized"
        }
    
    client = _group_manager.clients[account_id]
    try:
        me = await client.get_me()
        return {
            "account_id": account_id,
            "status": "connected",
            "user": {
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name
            }
        }
    except Exception as e:
        return {
            "account_id": account_id,
            "status": "error",
            "error": str(e)
        }


@accounts_bp.route('/reset-usage', methods=['POST'])
@require_auth
@require_role('admin')
@rate_limit(limit=5, per='user')
def reset_usage():
    """
    Reset usage counts for all accounts.
    
    Returns:
        {
            "message": "Usage counts reset successfully"
        }
    """
    try:
        _group_manager.account_rotator.reset_usage_counts()
        return jsonify({'message': 'Usage counts reset successfully'}), 200
    except Exception as e:
        logger.error(f"Failed to reset usage: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@accounts_bp.route('/stats', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_account_stats():
    """
    Get account statistics.
    
    Returns:
        {
            "total_accounts": 5,
            "active_accounts": 4,
            "banned_accounts": 1,
            "total_usage": 100
        }
    """
    try:
        account_stats = _group_manager.account_rotator.get_account_stats()
        
        total = len(account_stats)
        active = sum(1 for s in account_stats if not s.get("is_banned", False))
        banned = total - active
        total_usage = sum(s.get("usage", 0) for s in account_stats)
        
        return jsonify({
            "total_accounts": total,
            "active_accounts": active,
            "banned_accounts": banned,
            "total_usage": total_usage
        }), 200
    except Exception as e:
        logger.error(f"Failed to get account stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
