"""
Rate Limiting Module (CSNA 2.0 DDoS Protection)
================================================

Provides per-IP and per-user rate limiting to prevent abuse.
"""

import time
import logging
from collections import defaultdict
from functools import wraps
from typing import Callable, Dict, Tuple

from flask import request, jsonify

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    In-memory rate limiter with cleanup of old entries.

    CSNA 2.0 Compliance:
    - Prevents brute force attacks
    - Mitigates DDoS attacks
    - Tracks requests per IP and per user
    """

    def __init__(self, default_limit: int = 100, window_seconds: int = 60):
        """
        Initialize rate limiter.

        Args:
            default_limit: Default requests per window
            window_seconds: Time window in seconds
        """
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self.requests: Dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, identifier: str, limit: int = None) -> Tuple[bool, Dict]:
        """
        Check if request is allowed for identifier.

        Args:
            identifier: IP address, user ID, or endpoint+IP
            limit: Override default limit

        Returns:
            Tuple of (allowed: bool, rate_info: dict)
        """
        limit = limit or self.default_limit
        now = time.time()
        cutoff = now - self.window_seconds

        # Remove old requests
        self.requests[identifier] = [
            req_time for req_time in self.requests[identifier]
            if req_time > cutoff
        ]

        # Get current count
        current_count = len(self.requests[identifier])

        # Check limit
        allowed = current_count < limit

        # Record this request if allowed
        if allowed:
            self.requests[identifier].append(now)

        # Calculate remaining and reset time
        remaining = limit - current_count
        reset_time = self.requests[identifier][0] + self.window_seconds if self.requests[identifier] else now

        return allowed, {
            'limit': limit,
            'current': current_count + 1,
            'remaining': max(0, remaining - 1),
            'reset': reset_time
        }

    def cleanup(self):
        """Remove all old request records."""
        now = time.time()
        cutoff = now - self.window_seconds * 2  # Keep 2x window of history

        for identifier in list(self.requests.keys()):
            self.requests[identifier] = [
                req_time for req_time in self.requests[identifier]
                if req_time > cutoff
            ]
            if not self.requests[identifier]:
                del self.requests[identifier]


def rate_limit(limit: int = 100, per: str = 'ip') -> Callable:
    """
    Decorator to rate limit endpoints.

    Args:
        limit: Requests per window
        per: 'ip' for IP-based, 'user' for user-based (requires auth)

    Usage:
        @app.route('/api/search')
        @require_auth
        @rate_limit(limit=30, per='user')
        def search():
            ...
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated(*args, **kwargs):
            # Get identifier based on 'per' parameter
            if per == 'user':
                # Requires authentication
                if not hasattr(request, 'ctx') or 'user' not in request.ctx:
                    identifier = request.remote_addr
                else:
                    identifier = f"user_{request.ctx['user']['user_id']}"
            else:  # 'ip'
                identifier = request.remote_addr

            # Add endpoint to identifier for per-endpoint limits
            endpoint_id = f"{identifier}:{request.endpoint}"

            # Check rate limit
            rate_limiter = request.app.rate_limiter
            allowed, rate_info = rate_limiter.is_allowed(endpoint_id, limit)

            if not allowed:
                logger.warning(
                    f"Rate limit exceeded for {identifier} "
                    f"at {request.endpoint} "
                    f"(limit: {rate_info['limit']})"
                )
                response = jsonify({
                    'error': 'Rate limit exceeded',
                    'rate_limit': rate_info
                })
                response.status_code = 429
                response.headers['X-RateLimit-Limit'] = str(rate_info['limit'])
                response.headers['X-RateLimit-Remaining'] = str(rate_info['remaining'])
                response.headers['X-RateLimit-Reset'] = str(int(rate_info['reset']))
                response.headers['Retry-After'] = str(int(rate_info['reset'] - time.time()) + 1)
                return response

            # Add rate limit headers to response
            resp = f(*args, **kwargs)

            # Handle both dict responses and Response objects
            if isinstance(resp, tuple):
                data, status_code = resp[:2]
                headers = resp[2] if len(resp) > 2 else {}
                headers['X-RateLimit-Limit'] = str(rate_info['limit'])
                headers['X-RateLimit-Remaining'] = str(rate_info['remaining'])
                headers['X-RateLimit-Reset'] = str(int(rate_info['reset']))
                return data, status_code, headers
            else:
                resp.headers['X-RateLimit-Limit'] = str(rate_info['limit'])
                resp.headers['X-RateLimit-Remaining'] = str(rate_info['remaining'])
                resp.headers['X-RateLimit-Reset'] = str(int(rate_info['reset']))
                return resp

        return decorated
    return decorator
