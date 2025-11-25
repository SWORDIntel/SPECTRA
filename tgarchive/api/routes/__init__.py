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
]
