"""
Error Handler
=============

Comprehensive error handling for API endpoints.
"""

import logging
import traceback
from flask import jsonify, request
from functools import wraps

logger = logging.getLogger(__name__)


class ErrorHandler:
    """Centralized error handling for API."""
    
    @staticmethod
    def handle_exception(e: Exception):
        """
        Handle an exception and return appropriate response.
        
        Args:
            e: Exception to handle
            
        Returns:
            JSON error response
        """
        error_type = type(e).__name__
        error_message = str(e)
        
        # Log the error
        logger.error(
            f"API error: {error_type} - {error_message}",
            exc_info=True,
            extra={
                'path': request.path,
                'method': request.method,
                'error_type': error_type
            }
        )
        
        # Map exceptions to HTTP status codes
        status_code = 500
        if isinstance(e, ValueError):
            status_code = 400
        elif isinstance(e, KeyError):
            status_code = 400
        elif isinstance(e, PermissionError):
            status_code = 403
        elif isinstance(e, FileNotFoundError):
            status_code = 404
        elif isinstance(e, TimeoutError):
            status_code = 504
        
        return jsonify({
            'error': error_type,
            'message': error_message,
            'path': request.path,
            'method': request.method
        }), status_code
    
    @staticmethod
    def error_handler(f):
        """Decorator for error handling."""
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as e:
                return ErrorHandler.handle_exception(e)
        return wrapper


def register_error_handlers(app):
    """Register global error handlers with Flask app."""
    
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({
            'error': 'BadRequest',
            'message': str(error),
            'status_code': 400
        }), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({
            'error': 'Unauthorized',
            'message': 'Authentication required',
            'status_code': 401
        }), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({
            'error': 'Forbidden',
            'message': 'Insufficient permissions',
            'status_code': 403
        }), 403
    
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            'error': 'NotFound',
            'message': 'Resource not found',
            'status_code': 404
        }), 404
    
    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        return jsonify({
            'error': 'RateLimitExceeded',
            'message': 'Rate limit exceeded',
            'status_code': 429
        }), 429
    
    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}", exc_info=True)
        return jsonify({
            'error': 'InternalServerError',
            'message': 'An internal error occurred',
            'status_code': 500
        }), 500
    
    @app.errorhandler(Exception)
    def handle_generic_exception(e):
        return ErrorHandler.handle_exception(e)
