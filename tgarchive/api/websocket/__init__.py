"""
WebSocket API
=============

Real-time event broadcasting for SPECTRA operations.
"""

from .server import WebSocketManager
from .routes import init_websocket_routes
from .events import WebSocketEvents

__all__ = [
    'WebSocketManager',
    'init_websocket_routes',
    'WebSocketEvents',
]
