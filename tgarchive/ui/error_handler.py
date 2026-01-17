"""Enhanced error handling with user-friendly messages and recovery suggestions"""

import logging
import traceback
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import npyscreen
    HAS_NPYSCREEN = True
except ImportError:
    HAS_NPYSCREEN = False


class ErrorHandler:
    """Enhanced error handling with recovery suggestions"""
    
    ERROR_MESSAGES = {
        "ConnectionError": "Connection failed. Check network and proxy settings.",
        "TimeoutError": "Operation timed out. Try again or increase timeout.",
        "ValueError": "Invalid input. Check your parameters.",
        "KeyError": "Missing required configuration. Check settings.",
        "PermissionError": "Permission denied. Check file/directory permissions.",
    }
    
    RECOVERY_SUGGESTIONS = {
        "ConnectionError": [
            "Check internet connection",
            "Verify proxy settings",
            "Try a different account",
        ],
        "TimeoutError": [
            "Increase timeout value",
            "Check network speed",
            "Try again later",
        ],
        "ValueError": [
            "Review input parameters",
            "Check format requirements",
            "See help for examples",
        ],
    }
    
    def format_error(self, error: Exception, context: Optional[str] = None) -> Tuple[str, List[str]]:
        """Format error with user-friendly message and recovery suggestions"""
        error_type = type(error).__name__
        message = self.ERROR_MESSAGES.get(error_type, str(error))
        
        if context:
            message = f"{context}: {message}"
        
        suggestions = self.RECOVERY_SUGGESTIONS.get(error_type, [
            "Check logs for details",
            "Try the operation again",
            "Contact support if issue persists",
        ])
        
        return message, suggestions
    
    def show_error(self, error: Exception, context: Optional[str] = None):
        """Display error with recovery suggestions"""
        message, suggestions = self.format_error(error, context)
        
        if HAS_NPYSCREEN:
            suggestion_text = "\n".join(f"  • {s}" for s in suggestions)
            full_message = f"{message}\n\nSuggestions:\n{suggestion_text}"
            npyscreen.notify_confirm(full_message, title="Error", form_color="DANGER")
        else:
            logger.error(f"{message}\nSuggestions: {', '.join(suggestions)}")
    
    def handle_operation_error(self, operation: str, error: Exception):
        """Handle operation-specific errors"""
        context = f"Operation '{operation}' failed"
        self.show_error(error, context)
        
        # Log full traceback
        logger.error(f"{context}: {error}", exc_info=True)
