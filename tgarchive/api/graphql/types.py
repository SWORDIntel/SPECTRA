"""
GraphQL Types
=============

Type definitions for GraphQL schema.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Global service instance (initialized in schema.py)
_database_service = None

try:
    from graphene import (
        ObjectType, String, Int, Float, Boolean, List, Field,
        DateTime, ID, InputObjectType
    )
    GRAPHQL_AVAILABLE = True
except ImportError:
    GRAPHQL_AVAILABLE = False


if GRAPHQL_AVAILABLE:
    class ChannelType(ObjectType):
        """Channel/Group type."""
        channel_id = ID(required=True)
        title = String()
        username = String()
        type = String()
        archived_messages = Int()
        last_updated = DateTime()
    
    class MessageType(ObjectType):
        """Message type."""
        message_id = ID(required=True)
        channel_id = ID()
        text = String()
        sender_id = ID()
        date = DateTime()
        reactions = List(String)
        replies_count = Int()
    
    class UserType(ObjectType):
        """User type."""
        user_id = ID(required=True)
        username = String()
        first_name = String()
        last_name = String()
    
    class Query(ObjectType):
        """Root query type."""
        hello = String()
        channels = List(ChannelType, page=Int(), limit=Int(), search=String())
        channel = Field(ChannelType, channel_id=ID(required=True))
        messages = List(MessageType, channel_id=ID(), page=Int(), limit=Int())
        message = Field(MessageType, message_id=ID(required=True))
        
        def resolve_hello(self, info):
            """Resolve hello query - returns API version info."""
            import datetime
            return f"SPECTRA GraphQL API v1.0.0 - {datetime.datetime.now().isoformat()}"
        
        def resolve_channels(self, info, page=1, limit=20, search=None):
            """Resolve channels query."""
            global _database_service
            if not _database_service:
                logger.warning("Database service not initialized for GraphQL")
                return []
            
            try:
                result = asyncio.run(_database_service.list_channels(page, limit, search))
                channels = result.get('channels', [])
                # Convert dict to ChannelType objects
                return [ChannelType(**ch) for ch in channels]
            except Exception as e:
                logger.error(f"GraphQL resolve_channels error: {e}", exc_info=True)
                return []
        
        def resolve_channel(self, info, channel_id):
            """Resolve single channel query."""
            global _database_service
            if not _database_service:
                logger.warning("Database service not initialized for GraphQL")
                return None
            
            try:
                result = asyncio.run(_database_service.get_channel(channel_id))
                if result:
                    return ChannelType(**result)
                return None
            except Exception as e:
                logger.error(f"GraphQL resolve_channel error: {e}", exc_info=True)
                return None
        
        def resolve_messages(self, info, channel_id=None, page=1, limit=20):
            """Resolve messages query."""
            global _database_service
            if not _database_service:
                logger.warning("Database service not initialized for GraphQL")
                return []
            
            try:
                if channel_id:
                    result = asyncio.run(_database_service.query_messages(
                        channel_id, page, limit, None, None
                    ))
                    messages = result.get('messages', [])
                    return [MessageType(**msg) for msg in messages]
                return []
            except Exception as e:
                logger.error(f"GraphQL resolve_messages error: {e}", exc_info=True)
                return []
        
        def resolve_message(self, info, message_id):
            """Resolve single message query."""
            global _database_service
            if not _database_service:
                logger.warning("Database service not initialized for GraphQL")
                return None
            
            try:
                result = asyncio.run(_database_service.get_message(message_id))
                if result:
                    return MessageType(**result)
                return None
            except Exception as e:
                logger.error(f"GraphQL resolve_message error: {e}", exc_info=True)
                return None
    
    class ArchiveChannel(Mutation):
        """Archive channel mutation."""
        class Arguments:
            entity_id = String(required=True)
        
        task_id = String()
        status = String()
        
        def mutate(self, info, entity_id):
            """Execute archive mutation."""
            import uuid
            from ..services import ArchiveService
            from ...core.config_models import Config
            from pathlib import Path
            
            try:
                # Initialize archive service
                config_path = Path('spectra_config.json')
                if config_path.exists():
                    config = Config(config_path)
                else:
                    config = Config(config_path)  # Will use defaults
                
                archive_service = ArchiveService(config)
                task_id = asyncio.run(archive_service.archive_channel(entity_id))
                
                return ArchiveChannel(task_id=task_id, status="queued")
            except Exception as e:
                logger.error(f"GraphQL archive mutation error: {e}", exc_info=True)
                # Return error state
                return ArchiveChannel(task_id=str(uuid.uuid4()), status="error")
    
    class Mutation(ObjectType):
        """Root mutation type."""
        archive_channel = ArchiveChannel.Field()
else:
    # Placeholder types when GraphQL not available
    Query = None
    Mutation = None
