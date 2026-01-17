"""
Real-Time Message Streaming
===========================

Stream new messages as they arrive in real-time via WebSocket.
"""

import logging
import asyncio
from typing import AsyncGenerator, Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageStream:
    """
    Real-time message streaming for SPECTRA.
    
    Streams new messages as they're archived or received,
    allowing clients to receive updates in real-time.
    """
    
    def __init__(self, websocket_server=None):
        """
        Initialize message stream.
        
        Args:
            websocket_server: WebSocketServer instance for broadcasting
        """
        self.websocket_server = websocket_server
        self.active_streams: Dict[str, asyncio.Task] = {}
    
    async def stream_new_messages(
        self,
        channel_id: Optional[int] = None,
        check_interval: float = 1.0
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream new messages as they arrive.
        
        Args:
            channel_id: Optional channel filter
            check_interval: Polling interval in seconds
        
        Yields:
            Message dictionaries as they arrive
        """
        last_message_id = None
        
        while True:
            try:
                # Query database for new messages since last_message_id
                new_messages = await self._get_new_messages(channel_id, last_message_id)
                
                for message in new_messages:
                    last_message_id = message.get('id')
                    yield message
                    
                    # Broadcast via WebSocket if server available
                    if self.websocket_server:
                        await self.websocket_server.broadcast(
                            self.websocket_server.EventType.NEW_MESSAGE,
                            {'message': message}
                        )
                
                await asyncio.sleep(check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in message stream: {e}")
                await asyncio.sleep(check_interval)
    
    async def _get_new_messages(
        self,
        channel_id: Optional[int],
        last_message_id: Optional[int]
    ) -> list:
        """
        Get new messages since last_message_id.
        
        Queries database for messages with id > last_message_id.
        If channel_id provided, filters by channel.
        
        Note: Requires database connection to be passed to MessageStream constructor.
        Query: SELECT * FROM messages WHERE id > ? [AND channel_id = ?] ORDER BY id LIMIT 100
        """
        # Integration point: Connect to actual database
        # Returns empty list until database connection provided to MessageStream
        return []
    
    def start_stream(self, stream_id: str, channel_id: Optional[int] = None):
        """Start a message stream"""
        if stream_id in self.active_streams:
            logger.warning(f"Stream {stream_id} already active")
            return
        
        task = asyncio.create_task(
            self._run_stream(stream_id, channel_id)
        )
        self.active_streams[stream_id] = task
    
    def stop_stream(self, stream_id: str):
        """Stop a message stream"""
        if stream_id in self.active_streams:
            self.active_streams[stream_id].cancel()
            del self.active_streams[stream_id]
    
    async def _run_stream(self, stream_id: str, channel_id: Optional[int]):
        """Run message stream"""
        try:
            async for message in self.stream_new_messages(channel_id):
                # Stream is active, messages are yielded
                pass
        except asyncio.CancelledError:
            logger.info(f"Stream {stream_id} cancelled")
        except Exception as e:
            logger.error(f"Stream {stream_id} error: {e}")
