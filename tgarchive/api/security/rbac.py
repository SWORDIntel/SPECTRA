"""
Role-Based Access Control (RBAC)
=================================

RBAC implementation for API endpoints.
"""

import logging
from functools import wraps
from flask import request, jsonify

logger = logging.getLogger(__name__)


class RBAC:
    """Role-Based Access Control manager."""
    
    # Define role hierarchy
    ROLE_HIERARCHY = {
        'admin': ['admin', 'analyst', 'viewer'],
        'analyst': ['analyst', 'viewer'],
        'viewer': ['viewer']
    }
    
    @staticmethod
    def has_role(user_roles: list, required_roles: list) -> bool:
        """
        Check if user has any of the required roles.
        
        Args:
            user_roles: List of user roles
            required_roles: List of required roles
            
        Returns:
            True if user has required role
        """
        if not user_roles or not required_roles:
            return False
        
        for user_role in user_roles:
            # Check direct match
            if user_role in required_roles:
                return True
            
            # Check role hierarchy
            user_permissions = RBAC.ROLE_HIERARCHY.get(user_role, [])
            if any(role in user_permissions for role in required_roles):
                return True
        
        return False
    
    @staticmethod
    def require_role(*required_roles):
        """
        Decorator to require specific roles.
        
        Usage:
            @require_role('admin', 'analyst')
            def my_endpoint():
                ...
        """
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                # Get user from request (set by auth middleware)
                user = getattr(request, 'user', None)
                
                if not user:
                    return jsonify({'error': 'Authentication required'}), 401
                
                user_roles = user.get('roles', [])
                
                if not RBAC.has_role(user_roles, list(required_roles)):
                    return jsonify({
                        'error': 'Insufficient permissions',
                        'required_roles': list(required_roles),
                        'user_roles': user_roles
                    }), 403
                
                return f(*args, **kwargs)
            return decorated_function
        return decorator
