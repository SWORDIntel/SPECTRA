"""
Archive Service
===============

Service layer for archive operations.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

from ...core.config_models import Config
from ...core.sync import runner, archive_channel, ProxyCycler
from ...db import SpectraDB
from .tasks import TaskManager, TaskStatus

logger = logging.getLogger(__name__)


class ArchiveService:
    """Service for archive operations."""
    
    def __init__(self, config: Config, task_manager: TaskManager, db: Optional[SpectraDB] = None):
        self.config = config
        self.task_manager = task_manager
        self.db = db or SpectraDB(Path(config.data.get("db_path", "spectra.db")))
    
    async def archive_channel(
        self,
        entity_id: str,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Archive a channel/group.
        
        Args:
            entity_id: Channel/group identifier
            options: Archive options (download_media, download_avatars, etc.)
            
        Returns:
            Task ID and status
        """
        options = options or {}
        
        # Create task
        task_id = await self.task_manager.create_task(
            operation="archive",
            params={
                "entity_id": entity_id,
                "options": options
            }
        )
        
        # Update config with entity and options
        archive_config = Config(Path(self.config.config_path))
        archive_config.data["entity"] = entity_id
        archive_config.data["download_media"] = options.get("download_media", True)
        archive_config.data["download_avatars"] = options.get("download_avatars", True)
        archive_config.data["archive_topics"] = options.get("archive_topics", True)
        
        # Execute in background
        asyncio.create_task(self._execute_archive(task_id, archive_config))
        
        return {
            "task_id": task_id,
            "status": "queued",
            "entity_id": entity_id
        }
    
    async def _execute_archive(self, task_id: str, config: Config):
        """Execute archive operation."""
        try:
            await self.task_manager.update_task_status(task_id, TaskStatus.RUNNING)
            
            # Run archive
            await runner(config, auto_account=None)
            
            await self.task_manager.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                progress=100.0,
                result={"message": "Archive completed successfully"}
            )
        except Exception as e:
            await self.task_manager.update_task_status(
                task_id,
                TaskStatus.FAILED,
                error=str(e)
            )
    
    async def get_archive_status(self, entity_id: str) -> Dict[str, Any]:
        """
        Get archive status for an entity.
        
        Args:
            entity_id: Channel/group identifier
            
        Returns:
            Archive status information
        """
        # Query database for archive information
        channels = self.db.get_all_unique_channels()
        
        entity_info = None
        for channel in channels:
            if str(channel.get("id")) == str(entity_id) or channel.get("username") == entity_id:
                entity_info = channel
                break
        
        if not entity_info:
            return {
                "entity_id": entity_id,
                "archived": False,
                "message": "Entity not found in archive"
            }
        
        # Get message count
        # This would require additional DB queries
        return {
            "entity_id": entity_id,
            "archived": True,
            "channel_info": entity_info,
            "last_updated": entity_info.get("last_message_date")
        }
    
    async def batch_archive(
        self,
        entity_ids: List[str],
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Batch archive multiple channels/groups.
        
        Args:
            entity_ids: List of channel/group identifiers
            options: Archive options
            
        Returns:
            Task IDs for each archive operation
        """
        task_ids = []
        
        for entity_id in entity_ids:
            result = await self.archive_channel(entity_id, options)
            task_ids.append(result["task_id"])
        
        return {
            "task_ids": task_ids,
            "total": len(task_ids),
            "status": "queued"
        }
