"""
WebSocket Routes
================

WebSocket endpoint handlers for real-time updates.
"""

import logging
from datetime import datetime
from flask import request

from .server import WebSocketManager

logger = logging.getLogger(__name__)

try:
    from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False


def init_websocket_routes(app, ws_manager: WebSocketManager):
    """Initialize WebSocket routes."""
    if not SOCKETIO_AVAILABLE or not ws_manager.socketio:
        logger.warning("WebSocket routes not initialized - Flask-SocketIO not available")
        return
    
    socketio = ws_manager.socketio
    
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection."""
        session_id = request.sid
        logger.info(f"WebSocket client connected: {session_id}")
        
        # Join default room
        ws_manager.join_room(session_id, 'default')
        emit('connected', {'message': 'Connected to SPECTRA WebSocket API'})
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        session_id = request.sid
        logger.info(f"WebSocket client disconnected: {session_id}")
        
        # Leave all rooms
        rooms = ws_manager.get_client_rooms(session_id)
        for room in rooms:
            ws_manager.leave_room(session_id, room)
    
    @socketio.on('subscribe')
    def handle_subscribe(data):
        """Handle room subscription."""
        session_id = request.sid
        room = data.get('room', 'default')
        
        ws_manager.join_room(session_id, room)
        emit('subscribed', {'room': room, 'message': f'Subscribed to {room}'})
        logger.info(f"Client {session_id} subscribed to room {room}")
    
    @socketio.on('unsubscribe')
    def handle_unsubscribe(data):
        """Handle room unsubscription."""
        session_id = request.sid
        room = data.get('room', 'default')
        
        ws_manager.leave_room(session_id, room)
        emit('unsubscribed', {'room': room, 'message': f'Unsubscribed from {room}'})
        logger.info(f"Client {session_id} unsubscribed from room {room}")
    
    @socketio.on('subscribe_archive')
    def handle_subscribe_archive(data):
        """Subscribe to archive-specific updates."""
        session_id = request.sid
        entity_id = data.get('entity_id')
        
        if entity_id:
            room = f'archive:{entity_id}'
            ws_manager.join_room(session_id, room)
            emit('subscribed', {'room': room, 'entity_id': entity_id})
    
    @socketio.on('subscribe_discover')
    def handle_subscribe_discover(data):
        """Subscribe to discovery-specific updates."""
        session_id = request.sid
        discovery_id = data.get('discovery_id')
        
        if discovery_id:
            room = f'discover:{discovery_id}'
            ws_manager.join_room(session_id, room)
            emit('subscribed', {'room': room, 'discovery_id': discovery_id})
    
    @socketio.on('subscribe_system')
    def handle_subscribe_system():
        """Subscribe to system metrics."""
        session_id = request.sid
        ws_manager.join_room(session_id, 'system')
        emit('subscribed', {'room': 'system'})
