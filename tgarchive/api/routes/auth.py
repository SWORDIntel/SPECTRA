"""
Authentication API Routes
=========================

Handles login, logout, token refresh, and user management.
"""

import logging
from flask import request, jsonify

from . import auth_bp
from ..security import TokenManager, require_auth, validate_input, ValidationError

logger = logging.getLogger(__name__)


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Authenticate user and return JWT tokens.

    Request JSON:
        {
            "username": "admin",
            "password": "secure_password"
        }

    Response:
        {
            "access_token": "...",
            "refresh_token": "...",
            "user": {
                "user_id": "...",
                "username": "admin",
                "roles": ["admin"],
                "created_at": "..."
            }
        }
    """
    try:
        data = request.get_json() or {}

        # Validate input
        username = validate_input(data.get('username'), 'username', required=True)
        password = validate_input(data.get('password'), 'string', required=True, min_length=8)

    except ValidationError as e:
        return {'error': str(e)}, 400

    # TODO: Verify credentials against database
    # For now, accept admin/admin for demo
    if username == 'admin' and password == 'admin':
        user_id = 'user_001'
        roles = ['admin']
        permissions = {
            'manage_channels': True,
            'manage_users': True,
            'manage_operations': True,
            'export_data': True,
            'view_logs': True
        }
    elif username == 'analyst':
        user_id = 'user_002'
        roles = ['analyst']
        permissions = {
            'manage_channels': False,
            'manage_users': False,
            'manage_operations': True,
            'export_data': True,
            'view_logs': True
        }
    else:
        logger.warning(f"Failed login attempt for user: {username}")
        return {'error': 'Invalid credentials'}, 401

    # Generate tokens
    token_manager = request.app.token_manager
    access_token = token_manager.create_access_token(
        user_id=user_id,
        username=username,
        roles=roles,
        permissions=permissions
    )
    refresh_token = token_manager.create_refresh_token(user_id, username)

    logger.info(f"User logged in: {username}")

    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'user': {
            'user_id': user_id,
            'username': username,
            'roles': roles,
            'created_at': '2024-01-01T00:00:00Z'  # TODO: Get from database
        }
    }, 200


@auth_bp.route('/refresh', methods=['POST'])
def refresh():
    """
    Refresh access token using refresh token.

    Request JSON:
        {
            "refresh_token": "..."
        }

    Response:
        {
            "access_token": "...",
            "expires_in": 3600
        }
    """
    try:
        data = request.get_json() or {}
        refresh_token = data.get('refresh_token')

        if not refresh_token:
            return {'error': 'Refresh token required'}, 400

        token_manager = request.app.token_manager
        new_access_token = token_manager.refresh_access_token(refresh_token)

        if not new_access_token:
            logger.warning("Failed token refresh attempt")
            return {'error': 'Invalid refresh token'}, 401

        logger.info("Token refreshed successfully")

        return {
            'access_token': new_access_token,
            'expires_in': TokenManager.ACCESS_TOKEN_EXPIRY * 3600
        }, 200

    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        return {'error': 'Token refresh failed'}, 500


@auth_bp.route('/logout', methods=['POST'])
@require_auth
def logout():
    """
    Logout user (client-side token invalidation).

    Returns:
        {
            "message": "Logged out successfully"
        }
    """
    user = request.ctx['user']
    logger.info(f"User logged out: {user['username']}")

    return {'message': 'Logged out successfully'}, 200


@auth_bp.route('/profile', methods=['GET'])
@require_auth
def get_profile():
    """
    Get current user profile.

    Returns:
        {
            "user_id": "...",
            "username": "...",
            "roles": [...],
            "permissions": {...},
            "created_at": "..."
        }
    """
    user = request.ctx['user']

    return {
        'user_id': user['user_id'],
        'username': user['username'],
        'roles': user['roles'],
        'permissions': user['permissions'],
        'created_at': '2024-01-01T00:00:00Z'  # TODO: Get from database
    }, 200


@auth_bp.route('/profile', methods=['PUT'])
@require_auth
def update_profile():
    """
    Update current user profile.

    Request JSON:
        {
            "email": "user@example.com",
            "preferences": {...}
        }

    Returns:
        {
            "message": "Profile updated successfully"
        }
    """
    try:
        user = request.ctx['user']
        data = request.get_json() or {}

        # Validate input
        if 'email' in data:
            validate_input(data['email'], 'email', required=True)

        # TODO: Update database

        logger.info(f"Profile updated for user: {user['username']}")

        return {'message': 'Profile updated successfully'}, 200

    except ValidationError as e:
        return {'error': str(e)}, 400
    except Exception as e:
        logger.error(f"Profile update error: {str(e)}")
        return {'error': 'Profile update failed'}, 500
