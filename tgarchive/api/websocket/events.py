"""
WebSocket Events
================

Event definitions and constants for WebSocket communication.
"""

from enum import Enum
from typing import Dict, Any


class WebSocketEvents:
    """WebSocket event names and structure."""
    
    # Archive events
    ARCHIVE_START = "archive:start"
    ARCHIVE_PROGRESS = "archive:progress"
    ARCHIVE_COMPLETE = "archive:complete"
    ARCHIVE_ERROR = "archive:error"
    
    # Discovery events
    DISCOVER_START = "discover:start"
    DISCOVER_FOUND = "discover:found"
    DISCOVER_COMPLETE = "discover:complete"
    
    # Forwarding events
    FORWARD_START = "forward:start"
    FORWARD_PROGRESS = "forward:progress"
    FORWARD_COMPLETE = "forward:complete"
    
    # Threat intelligence events
    THREAT_DETECTED = "threat:detected"
    THREAT_SCORED = "threat:scored"
    THREAT_CORRELATED = "threat:correlated"
    
    # System events
    SYSTEM_STATUS = "system:status"
    SYSTEM_METRIC = "system:metric"
    SYSTEM_ALERT = "system:alert"
    
    @staticmethod
    def create_archive_start(task_id: str, entity_id: str) -> Dict[str, Any]:
        """Create archive start event."""
        return {
            "event": WebSocketEvents.ARCHIVE_START,
            "task_id": task_id,
            "entity_id": entity_id,
            "timestamp": None  # Will be set by caller
        }
    
    @staticmethod
    def create_archive_progress(task_id: str, progress: float, status: str) -> Dict[str, Any]:
        """Create archive progress event."""
        return {
            "event": WebSocketEvents.ARCHIVE_PROGRESS,
            "task_id": task_id,
            "progress": progress,
            "status": status,
            "timestamp": None
        }
    
    @staticmethod
    def create_discover_found(discovery_id: str, group_id: str, group_info: Dict[str, Any]) -> Dict[str, Any]:
        """Create discover found event."""
        return {
            "event": WebSocketEvents.DISCOVER_FOUND,
            "discovery_id": discovery_id,
            "group_id": group_id,
            "group_info": group_info,
            "timestamp": None
        }
    
    @staticmethod
    def create_system_status(status: Dict[str, Any]) -> Dict[str, Any]:
        """Create system status event."""
        return {
            "event": WebSocketEvents.SYSTEM_STATUS,
            "status": status,
            "timestamp": None
        }
