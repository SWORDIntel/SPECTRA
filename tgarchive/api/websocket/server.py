"""
WebSocket Server
================

Real-time event broadcasting and connection management.
"""

import logging
from typing import Dict, Set, Optional
from flask import Flask

try:
    from flask_socketio import SocketIO, emit, join_room, leave_room
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Flask-SocketIO not available - WebSocket features disabled")

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and event broadcasting."""
    
    def __init__(self, app: Flask):
        if not SOCKETIO_AVAILABLE:
            self.socketio = None
            self.connected_clients: Dict[str, Set[str]] = {}  # room -> set of session_ids
            logger.warning("WebSocket disabled - Flask-SocketIO not installed")
            return
        
        self.app = app
        self.socketio = SocketIO(
            app,
            cors_allowed_origins=app.config.get('CORS_ORIGINS', ['http://localhost:3000']),
            async_mode='threading'
        )
        self.connected_clients: Dict[str, Set[str]] = {}  # room -> set of session_ids
        self.client_rooms: Dict[str, Set[str]] = {}  # session_id -> set of rooms
    
    def emit(self, event: str, data: Dict, room: Optional[str] = None):
        """
        Emit an event to connected clients.
        
        Args:
            event: Event name
            data: Event data
            room: Optional room identifier (None = broadcast to all)
        """
        if not self.socketio:
            logger.debug(f"WebSocket disabled - would emit {event} to {room or 'all'}")
            return
        
        try:
            if room:
                self.socketio.emit(event, data, room=room)
            else:
                self.socketio.emit(event, data, broadcast=True)
        except Exception as e:
            logger.error(f"Failed to emit WebSocket event: {e}", exc_info=True)
    
    def join_room(self, session_id: str, room: str):
        """Join a room."""
        if not self.socketio:
            return
        
        if room not in self.connected_clients:
            self.connected_clients[room] = set()
        
        self.connected_clients[room].add(session_id)
        
        if session_id not in self.client_rooms:
            self.client_rooms[session_id] = set()
        
        self.client_rooms[session_id].add(room)
    
    def leave_room(self, session_id: str, room: str):
        """Leave a room."""
        if not self.socketio:
            return
        
        if room in self.connected_clients:
            self.connected_clients[room].discard(session_id)
        
        if session_id in self.client_rooms:
            self.client_rooms[session_id].discard(room)
    
    def get_room_clients(self, room: str) -> Set[str]:
        """Get clients in a room."""
        return self.connected_clients.get(room, set())
    
    def get_client_rooms(self, session_id: str) -> Set[str]:
        """Get rooms a client is in."""
        return self.client_rooms.get(session_id, set())
