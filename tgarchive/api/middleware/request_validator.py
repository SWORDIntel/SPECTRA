"""
Request Validator
=================

Request validation and sanitization.
"""

import logging
from typing import Any, Dict, Optional
from flask import request, jsonify

logger = logging.getLogger(__name__)


class RequestValidator:
    """Validates and sanitizes API requests."""
    
    @staticmethod
    def validate_json(data: Dict[str, Any], required_fields: list[str]) -> Optional[Dict[str, Any]]:
        """
        Validate JSON request data.
        
        Args:
            data: Request data dictionary
            required_fields: List of required field names
            
        Returns:
            Error response dict if validation fails, None otherwise
        """
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            return {
                'error': 'ValidationError',
                'message': f'Missing required fields: {", ".join(missing_fields)}',
                'missing_fields': missing_fields
            }
        
        return None
    
    @staticmethod
    def validate_pagination(page: int, limit: int, max_limit: int = 100) -> Optional[Dict[str, Any]]:
        """
        Validate pagination parameters.
        
        Args:
            page: Page number
            limit: Items per page
            max_limit: Maximum allowed limit
            
        Returns:
            Error response dict if validation fails, None otherwise
        """
        if page < 1:
            return {
                'error': 'ValidationError',
                'message': 'page must be >= 1'
            }
        
        if limit < 1:
            return {
                'error': 'ValidationError',
                'message': 'limit must be >= 1'
            }
        
        if limit > max_limit:
            return {
                'error': 'ValidationError',
                'message': f'limit cannot exceed {max_limit}'
            }
        
        return None
    
    @staticmethod
    def validate_string(value: Any, field_name: str, min_length: int = 0, max_length: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Validate string field.
        
        Args:
            value: Value to validate
            field_name: Field name for error messages
            min_length: Minimum length
            max_length: Maximum length
            
        Returns:
            Error response dict if validation fails, None otherwise
        """
        if not isinstance(value, str):
            return {
                'error': 'ValidationError',
                'message': f'{field_name} must be a string'
            }
        
        if len(value) < min_length:
            return {
                'error': 'ValidationError',
                'message': f'{field_name} must be at least {min_length} characters'
            }
        
        if max_length and len(value) > max_length:
            return {
                'error': 'ValidationError',
                'message': f'{field_name} must be at most {max_length} characters'
            }
        
        return None
    
    @staticmethod
    def validate_integer(value: Any, field_name: str, min_value: Optional[int] = None, max_value: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Validate integer field.
        
        Args:
            value: Value to validate
            field_name: Field name for error messages
            min_value: Minimum value
            max_value: Maximum value
            
        Returns:
            Error response dict if validation fails, None otherwise
        """
        if not isinstance(value, int):
            try:
                value = int(value)
            except (ValueError, TypeError):
                return {
                    'error': 'ValidationError',
                    'message': f'{field_name} must be an integer'
                }
        
        if min_value is not None and value < min_value:
            return {
                'error': 'ValidationError',
                'message': f'{field_name} must be >= {min_value}'
            }
        
        if max_value is not None and value > max_value:
            return {
                'error': 'ValidationError',
                'message': f'{field_name} must be <= {max_value}'
            }
        
        return None
    
    @staticmethod
    def sanitize_input(value: str) -> str:
        """
        Sanitize string input.
        
        Args:
            value: Input string
            
        Returns:
            Sanitized string
        """
        if not isinstance(value, str):
            return str(value)
        
        # Remove null bytes and control characters
        value = value.replace('\x00', '')
        value = ''.join(char for char in value if ord(char) >= 32 or char in '\n\r\t')
        
        return value.strip()
