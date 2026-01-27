"""
API Route Blueprints
====================

Modular route definitions for the SPECTRA REST API.
"""

from flask import Blueprint

# Authentication routes
auth_bp = Blueprint('auth', __name__)

# Channel/Group management routes
channels_bp = Blueprint('channels', __name__)

# Message search and retrieval routes
messages_bp = Blueprint('messages', __name__)

# Full-text search routes
search_bp = Blueprint('search', __name__)

# Export and download routes
export_bp = Blueprint('export', __name__)

# Admin/user management routes
admin_bp = Blueprint('admin', __name__)

# Core operations routes
core_bp = Blueprint('core', __name__)

# Account management routes
accounts_bp = Blueprint('accounts', __name__)

# Forwarding routes
forwarding_bp = Blueprint('forwarding', __name__)

# Threat intelligence routes
threat_bp = Blueprint('threat', __name__)

# Analytics routes
analytics_bp = Blueprint('analytics', __name__)

# ML/AI routes
ml_bp = Blueprint('ml', __name__)

# Crypto routes
crypto_bp = Blueprint('crypto', __name__)

# Database routes
database_bp = Blueprint('database', __name__)

# OSINT routes
osint_bp = Blueprint('osint', __name__)

# Services routes
services_bp = Blueprint('services', __name__)

# CLI API routes
cli_bp = Blueprint('cli', __name__)


# Import route handlers
from .auth import *
from .channels import *
from .messages import *
from .search import *
from .export import *
from .admin import *


__all__ = [
    'auth_bp',
    'channels_bp',
    'messages_bp',
    'search_bp',
    'export_bp',
    'admin_bp',
    'core_bp',
    'accounts_bp',
    'forwarding_bp',
    'threat_bp',
    'analytics_bp',
    'ml_bp',
    'crypto_bp',
    'database_bp',
    'osint_bp',
    'services_bp',
    'cli_bp',
]
