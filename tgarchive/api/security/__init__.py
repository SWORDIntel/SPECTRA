"""
API Security Module
===================

Authentication, authorization, rate limiting, and validation.
"""

from .auth import TokenManager, require_auth, require_role
from .rate_limit import RateLimiter, rate_limit
from .validation import validate_input, ValidationError
from .headers import SecurityHeaders

# WebSocket auth decorator (placeholder - would need socketio-specific implementation)
from functools import wraps

def require_auth_ws(f):
    """WebSocket authentication decorator."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        # WebSocket auth would be implemented here
        return f(*args, **kwargs)
    return wrapper

__all__ = [
    'TokenManager',
    'require_auth',
    'require_role',
    'RateLimiter',
    'rate_limit',
    'validate_input',
    'ValidationError',
    'SecurityHeaders',
    'require_auth_ws',
]
