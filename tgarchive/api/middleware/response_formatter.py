"""
Response Formatter
==================

Standardized API response formatting.
"""

import logging
from typing import Any, Dict, Optional
from flask import jsonify

logger = logging.getLogger(__name__)


class ResponseFormatter:
    """Formats API responses consistently."""
    
    @staticmethod
    def success(data: Any = None, message: Optional[str] = None, status_code: int = 200) -> tuple:
        """
        Format successful response.
        
        Args:
            data: Response data
            message: Optional success message
            status_code: HTTP status code
            
        Returns:
            Tuple of (jsonify result, status_code)
        """
        response = {
            'success': True,
            'status': 'ok'
        }
        
        if message:
            response['message'] = message
        
        if data is not None:
            response['data'] = data
        
        return jsonify(response), status_code
    
    @staticmethod
    def error(error_type: str, message: str, status_code: int = 400, details: Optional[Dict] = None) -> tuple:
        """
        Format error response.
        
        Args:
            error_type: Error type identifier
            message: Error message
            status_code: HTTP status code
            details: Optional error details
            
        Returns:
            Tuple of (jsonify result, status_code)
        """
        response = {
            'success': False,
            'error': error_type,
            'message': message,
            'status_code': status_code
        }
        
        if details:
            response['details'] = details
        
        return jsonify(response), status_code
    
    @staticmethod
    def paginated(data: list, total: int, page: int, limit: int, **kwargs) -> tuple:
        """
        Format paginated response.
        
        Args:
            data: List of items
            total: Total number of items
            page: Current page number
            limit: Items per page
            **kwargs: Additional metadata
            
        Returns:
            Tuple of (jsonify result, status_code)
        """
        response = {
            'success': True,
            'data': data,
            'pagination': {
                'total': total,
                'page': page,
                'limit': limit,
                'pages': (total + limit - 1) // limit if limit > 0 else 0
            }
        }
        
        response.update(kwargs)
        
        return jsonify(response), 200
    
    @staticmethod
    def task_created(task_id: str, operation: str, **kwargs) -> tuple:
        """
        Format task creation response.
        
        Args:
            task_id: Task identifier
            operation: Operation name
            **kwargs: Additional metadata
            
        Returns:
            Tuple of (jsonify result, status_code)
        """
        response = {
            'success': True,
            'task_id': task_id,
            'operation': operation,
            'status': 'queued'
        }
        
        response.update(kwargs)
        
        return jsonify(response), 202
