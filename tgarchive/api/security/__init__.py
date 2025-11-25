"""
CSNA 2.0 Security Module for SPECTRA API
=========================================

Implements security controls for the REST API including:
- JWT authentication and token management
- Rate limiting and DDoS protection
- CSRF/XSS prevention
- Input validation and sanitization
- Secure headers
- Audit logging
"""

from .auth import TokenManager, require_auth, require_role
from .rate_limit import RateLimiter, rate_limit
from .validation import validate_input, sanitize_string
from .headers import SecurityHeaders

__all__ = [
    'TokenManager',
    'require_auth',
    'require_role',
    'RateLimiter',
    'rate_limit',
    'validate_input',
    'sanitize_string',
    'SecurityHeaders',
]
