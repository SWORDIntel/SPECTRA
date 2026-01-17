"""
WebSocket Server for Real-Time Updates
=======================================

WebSocket server implementation for real-time search updates, message streaming,
and system status notifications.
"""

import logging
import asyncio
import json
from typing import Dict, Set, Optional, Any, Callable
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

# Try to import websockets
try:
    import websockets
    from websockets.server import WebSocketServerProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logger.warning("websockets library not available. Real-time features disabled.")


class EventType(Enum):
    """Event types for WebSocket subscriptions"""
    NEW_MESSAGE = "new_message"
    SEARCH_UPDATE = "search_update"
    SYSTEM_STATUS = "system_status"
    PERFORMANCE_METRICS = "performance_metrics"
    SEARCH_COMPLETE = "search_complete"
    ERROR = "error"


class WebSocketServer:
    """
    WebSocket server for real-time SPECTRA updates.
    
    Features:
    - Connection management
    - Event subscriptions
    - Message queuing for disconnected clients
    - Authentication (optional)
    """
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        require_auth: bool = False,
    ):
        """
        Initialize WebSocket server.
        
        Args:
            host: Server host address
            port: Server port
            require_auth: Require authentication for connections
        """
        if not WEBSOCKETS_AVAILABLE:
            raise RuntimeError("websockets library not available. Install with: pip install websockets")
        
        self.host = host
        self.port = port
        self.require_auth = require_auth
        
        # Connection management
        self.connections: Set[WebSocketServerProtocol] = set()
        self.subscriptions: Dict[WebSocketServerProtocol, Set[EventType]] = {}
        self.message_queues: Dict[WebSocketServerProtocol, list] = {}
        
        # Event handlers
        self.event_handlers: Dict[EventType, list] = {
            event_type: [] for event_type in EventType
        }
        
        # Statistics
        self.stats = {
            'total_connections': 0,
            'active_connections': 0,
            'messages_sent': 0,
            'messages_received': 0,
        }
    
    async def register_client(self, websocket: WebSocketServerProtocol):
        """Register new client connection"""
        self.connections.add(websocket)
        self.subscriptions[websocket] = set()
        self.message_queues[websocket] = []
        self.stats['total_connections'] += 1
        self.stats['active_connections'] += 1
        
        logger.info(f"Client connected: {websocket.remote_address}")
        
        # Send queued messages if any
        if self.message_queues[websocket]:
            for message in self.message_queues[websocket]:
                await self.send_to_client(websocket, message)
            self.message_queues[websocket].clear()
    
    async def unregister_client(self, websocket: WebSocketServerProtocol):
        """Unregister client connection"""
        self.connections.discard(websocket)
        self.subscriptions.pop(websocket, None)
        self.message_queues.pop(websocket, None)
        self.stats['active_connections'] -= 1
        
        logger.info(f"Client disconnected: {websocket.remote_address}")
    
    async def handle_client(self, websocket: WebSocketServerProtocol, path: str):
        """Handle client connection"""
        await self.register_client(websocket)
        
        try:
            async for message in websocket:
                await self.handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister_client(websocket)
    
    async def handle_message(self, websocket: WebSocketServerProtocol, message: str):
        """Handle incoming message from client"""
        try:
            data = json.loads(message)
            self.stats['messages_received'] += 1
            
            action = data.get('action')
            
            if action == 'subscribe':
                event_types = [EventType(et) for et in data.get('events', [])]
                self.subscriptions[websocket].update(event_types)
                await self.send_to_client(websocket, {
                    'type': 'subscription_confirmed',
                    'events': [et.value for et in event_types]
                })
            
            elif action == 'unsubscribe':
                event_types = [EventType(et) for et in data.get('events', [])]
                self.subscriptions[websocket].difference_update(event_types)
                await self.send_to_client(websocket, {
                    'type': 'unsubscription_confirmed',
                    'events': [et.value for et in event_types]
                })
            
            elif action == 'ping':
                await self.send_to_client(websocket, {'type': 'pong', 'timestamp': datetime.now().isoformat()})
            
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from client: {message}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def send_to_client(
        self,
        websocket: WebSocketServerProtocol,
        data: Dict[str, Any]
    ):
        """Send data to specific client"""
        try:
            message = json.dumps(data)
            await websocket.send(message)
            self.stats['messages_sent'] += 1
        except websockets.exceptions.ConnectionClosed:
            await self.unregister_client(websocket)
        except Exception as e:
            logger.error(f"Error sending to client: {e}")
    
    async def broadcast(
        self,
        event_type: EventType,
        data: Dict[str, Any],
        exclude: Optional[WebSocketServerProtocol] = None
    ):
        """
        Broadcast event to all subscribed clients.
        
        Args:
            event_type: Type of event
            data: Event data
            exclude: Optional client to exclude from broadcast
        """
        message = {
            'type': event_type.value,
            'timestamp': datetime.now().isoformat(),
            'data': data,
        }
        
        disconnected = []
        for websocket in self.connections:
            if websocket == exclude:
                continue
            
            if event_type in self.subscriptions.get(websocket, set()):
                try:
                    await self.send_to_client(websocket, message)
                except websockets.exceptions.ConnectionClosed:
                    disconnected.append(websocket)
        
        # Clean up disconnected clients
        for ws in disconnected:
            await self.unregister_client(ws)
    
    async def queue_message(
        self,
        websocket: WebSocketServerProtocol,
        event_type: EventType,
        data: Dict[str, Any]
    ):
        """Queue message for client (when disconnected)"""
        if websocket in self.message_queues:
            self.message_queues[websocket].append({
                'type': event_type.value,
                'timestamp': datetime.now().isoformat(),
                'data': data,
            })
    
    async def start(self):
        """Start WebSocket server"""
        if not WEBSOCKETS_AVAILABLE:
            raise RuntimeError("websockets library not available")
        
        logger.info(f"Starting WebSocket server on {self.host}:{self.port}")
        
        async with websockets.serve(self.handle_client, self.host, self.port):
            await asyncio.Future()  # Run forever
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get server statistics"""
        return {
            **self.stats,
            'subscribed_connections': len([
                ws for ws, subs in self.subscriptions.items() if subs
            ]),
        }
