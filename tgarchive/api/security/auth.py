"""
JWT-based Authentication Module (CSNA 2.0 Compliant)
======================================================

Handles token generation, validation, and role-based access control.
"""

import os
import jwt
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Optional, Dict, Any, Callable

from flask import request, jsonify, current_app

logger = logging.getLogger(__name__)


class TokenManager:
    """Manages JWT token creation, validation, and refresh."""

    # Default expiration times (in hours)
    ACCESS_TOKEN_EXPIRY = 1  # 1 hour
    REFRESH_TOKEN_EXPIRY = 24 * 7  # 7 days

    def __init__(self, secret_key: Optional[str] = None, algorithm: str = 'HS256'):
        """
        Initialize TokenManager.

        Args:
            secret_key: JWT signing key (defaults to env var SPECTRA_JWT_SECRET)
            algorithm: JWT algorithm (HS256, RS256, etc.)
        """
        self.secret_key = secret_key or os.getenv('SPECTRA_JWT_SECRET')
        if not self.secret_key:
            raise ValueError(
                "JWT secret key not set. Set SPECTRA_JWT_SECRET environment variable."
            )
        self.algorithm = algorithm

    def create_access_token(
        self,
        user_id: str,
        username: str,
        roles: list[str],
        permissions: Dict[str, bool] = None,
        expires_in: int = None
    ) -> str:
        """
        Create a new access token.

        Args:
            user_id: Unique user identifier
            username: Username for audit logging
            roles: List of user roles (admin, analyst, viewer)
            permissions: Dict of permission flags
            expires_in: Token expiry in hours (defaults to ACCESS_TOKEN_EXPIRY)

        Returns:
            Signed JWT token
        """
        expires_in = expires_in or self.ACCESS_TOKEN_EXPIRY
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(hours=expires_in)

        payload = {
            'user_id': user_id,
            'username': username,
            'roles': roles,
            'permissions': permissions or {},
            'iat': now.timestamp(),
            'exp': expiry.timestamp(),
            'type': 'access'
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        logger.info(f"Access token created for user: {username}")
        return token

    def create_refresh_token(self, user_id: str, username: str) -> str:
        """
        Create a long-lived refresh token.

        Args:
            user_id: User identifier
            username: Username for audit logging

        Returns:
            Signed refresh token
        """
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(hours=self.REFRESH_TOKEN_EXPIRY)

        payload = {
            'user_id': user_id,
            'username': username,
            'iat': now.timestamp(),
            'exp': expiry.timestamp(),
            'type': 'refresh'
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        logger.info(f"Refresh token created for user: {username}")
        return token

    def verify_token(self, token: str, token_type: str = 'access') -> Optional[Dict[str, Any]]:
        """
        Verify and decode a token.

        Args:
            token: JWT token to verify
            token_type: Expected token type ('access' or 'refresh')

        Returns:
            Decoded token payload if valid, None otherwise
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Verify token type
            if payload.get('type') != token_type:
                logger.warning(f"Token type mismatch: expected {token_type}, got {payload.get('type')}")
                return None

            return payload
        except jwt.ExpiredSignatureError:
            logger.warning(f"Token expired for user: {token.split('.')[0][:20]}")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {str(e)}")
            return None

    def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        """
        Generate a new access token from a refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            New access token if refresh token is valid, None otherwise
        """
        payload = self.verify_token(refresh_token, token_type='refresh')
        if not payload:
            return None

        return self.create_access_token(
            user_id=payload['user_id'],
            username=payload['username'],
            roles=payload.get('roles', []),
            permissions=payload.get('permissions', {})
        )


def require_auth(f: Callable) -> Callable:
    """
    Decorator to require valid JWT authentication.

    Usage:
        @app.route('/protected')
        @require_auth
        def protected_route():
            current_user = request.ctx['user']
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        # Check Authorization header
        if 'Authorization' in request.headers:
            try:
                auth_header = request.headers['Authorization']
                token = auth_header.split(' ')[1]  # "Bearer <token>"
            except IndexError:
                return jsonify({'error': 'Invalid authorization header'}), 401

        # Check cookies as fallback
        elif 'access_token' in request.cookies:
            token = request.cookies['access_token']

        if not token:
            logger.warning(f"Unauthorized access attempt from {request.remote_addr}")
            return jsonify({'error': 'Missing authorization token'}), 401

        # Verify token
        token_manager = current_app.token_manager
        payload = token_manager.verify_token(token, token_type='access')

        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401

        # Store user info in request context
        request.ctx = {'user': payload}
        logger.debug(f"Authenticated user: {payload['username']}")

        return f(*args, **kwargs)

    return decorated


def require_role(*allowed_roles: str) -> Callable:
    """
    Decorator to require specific roles for access.

    Usage:
        @app.route('/admin')
        @require_auth
        @require_role('admin')
        def admin_route():
            ...
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated(*args, **kwargs):
            # This assumes require_auth has already been applied
            if not hasattr(request, 'ctx') or 'user' not in request.ctx:
                return jsonify({'error': 'Authentication required'}), 401

            user = request.ctx['user']
            user_roles = user.get('roles', [])

            # Check if user has required role
            if not any(role in user_roles for role in allowed_roles):
                logger.warning(
                    f"Access denied for user {user['username']} "
                    f"(roles: {user_roles}, required: {allowed_roles})"
                )
                return jsonify({'error': 'Insufficient permissions'}), 403

            return f(*args, **kwargs)

        return decorated
    return decorator
