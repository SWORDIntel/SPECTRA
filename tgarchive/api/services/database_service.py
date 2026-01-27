"""
Database Service
================

Service layer for database operations.
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

from ..db import SpectraDB
from ..core.config_models import Config

logger = logging.getLogger(__name__)


class DatabaseService:
    """Service for database operations."""
    
    def __init__(self, config: Config):
        self.config = config
        db_path = Path(config.data.get("db_path", "spectra.db"))
        self.db = SpectraDB(db_path)
    
    async def list_channels(
        self,
        page: int = 1,
        limit: int = 20,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List channels from database.
        
        Args:
            page: Page number
            limit: Items per page
            search: Optional search term
            
        Returns:
            List of channels
        """
        try:
            channels = self.db.get_all_unique_channels()
            
            # Apply search filter if provided
            if search:
                search_lower = search.lower()
                channels = [
                    c for c in channels
                    if search_lower in str(c.get("id", "")).lower()
                    or search_lower in str(c.get("username", "")).lower()
                    or search_lower in str(c.get("title", "")).lower()
                ]
            
            # Pagination
            total = len(channels)
            start = (page - 1) * limit
            end = start + limit
            paginated_channels = channels[start:end]
            
            return {
                "channels": paginated_channels,
                "total": total,
                "page": page,
                "limit": limit
            }
        except Exception as e:
            logger.error(f"Failed to list channels: {e}", exc_info=True)
            raise
    
    async def get_channel(self, channel_id: str) -> Dict[str, Any]:
        """
        Get channel details.
        
        Args:
            channel_id: Channel identifier
            
        Returns:
            Channel details
        """
        try:
            channels = self.db.get_all_unique_channels()
            
            for channel in channels:
                if str(channel.get("id")) == str(channel_id) or channel.get("username") == channel_id:
                    return {
                        "channel_id": channel.get("id"),
                        "title": channel.get("title"),
                        "username": channel.get("username"),
                        "type": channel.get("type", "channel"),
                        "archived_messages": channel.get("message_count", 0),
                        "last_updated": channel.get("last_message_date")
                    }
            
            return {
                "error": "Channel not found",
                "channel_id": channel_id
            }
        except Exception as e:
            logger.error(f"Failed to get channel: {e}", exc_info=True)
            raise
    
    async def query_messages(
        self,
        channel_id: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query messages from database.
        
        Args:
            channel_id: Optional channel identifier
            page: Page number
            limit: Items per page
            date_from: Optional start date
            date_to: Optional end date
            
        Returns:
            List of messages
        """
        try:
            # This would require additional DB query methods
            # For now, return structure
            return {
                "messages": [],
                "total": 0,
                "page": page,
                "limit": limit
            }
        except Exception as e:
            logger.error(f"Failed to query messages: {e}", exc_info=True)
            raise
    
    async def get_message(self, message_id: int) -> Dict[str, Any]:
        """
        Get message details.
        
        Args:
            message_id: Message ID
            
        Returns:
            Message details
        """
        try:
            # This would require additional DB query methods
            return {
                "message_id": message_id,
                "error": "Message retrieval not yet implemented"
            }
        except Exception as e:
            logger.error(f"Failed to get message: {e}", exc_info=True)
            raise
    
    async def query_users(
        self,
        page: int = 1,
        limit: int = 20,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query users from database.
        
        Args:
            page: Page number
            limit: Items per page
            search: Optional search term
            
        Returns:
            List of users
        """
        try:
            # This would require additional DB query methods
            return {
                "users": [],
                "total": 0,
                "page": page,
                "limit": limit
            }
        except Exception as e:
            logger.error(f"Failed to query users: {e}", exc_info=True)
            raise
    
    async def query_media(
        self,
        channel_id: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        media_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query media from database.
        
        Args:
            channel_id: Optional channel identifier
            page: Page number
            limit: Items per page
            media_type: Optional media type filter
            
        Returns:
            List of media
        """
        try:
            # This would require additional DB query methods
            return {
                "media": [],
                "total": 0,
                "page": page,
                "limit": limit
            }
        except Exception as e:
            logger.error(f"Failed to query media: {e}", exc_info=True)
            raise
    
    async def get_database_stats(self) -> Dict[str, Any]:
        """
        Get database statistics.
        
        Returns:
            Database statistics
        """
        try:
            channels = self.db.get_all_unique_channels()
            
            return {
                "total_channels": len(channels),
                "total_messages": 0,  # Would require additional query
                "total_users": 0,  # Would require additional query
                "total_media": 0,  # Would require additional query
                "database_path": str(self.db.db_path)
            }
        except Exception as e:
            logger.error(f"Failed to get database stats: {e}", exc_info=True)
            raise
    
    async def start_migration(
        self,
        source: str,
        destination: str,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Start a migration.
        
        Args:
            source: Source path
            destination: Destination path
            options: Migration options
            
        Returns:
            Migration task ID
        """
        try:
            # This would use MassMigrationManager
            migration_id = self.db.migration.add_migration_progress(
                source=source,
                destination=destination,
                status="queued"
            )
            
            return {
                "migration_id": migration_id,
                "status": "queued",
                "source": source,
                "destination": destination
            }
        except Exception as e:
            logger.error(f"Failed to start migration: {e}", exc_info=True)
            raise
    
    async def get_migration_status(self, migration_id: int) -> Dict[str, Any]:
        """
        Get migration status.
        
        Args:
            migration_id: Migration ID
            
        Returns:
            Migration status
        """
        try:
            report = self.db.get_migration_report(migration_id)
            
            if not report:
                return {
                    "migration_id": migration_id,
                    "error": "Migration not found"
                }
            
            source, destination, last_message_id, status, created_at, updated_at = report
            
            return {
                "migration_id": migration_id,
                "source": source,
                "destination": destination,
                "status": status,
                "last_message_id": last_message_id,
                "created_at": created_at,
                "updated_at": updated_at
            }
        except Exception as e:
            logger.error(f"Failed to get migration status: {e}", exc_info=True)
            raise
