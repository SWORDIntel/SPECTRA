"""
API Middleware
==============

Error handling, request validation, and response formatting.
"""

from .error_handlers import register_error_handlers

__all__ = ['register_error_handlers']
