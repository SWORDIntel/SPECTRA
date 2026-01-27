"""
Discovery Service
=================

Service layer for discovery operations.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

from ..core.config_models import Config
from ..utils.discovery import SpectraCrawlerManager
from ..db import SpectraDB
from .tasks import TaskManager, TaskStatus

logger = logging.getLogger(__name__)


class DiscoveryService:
    """Service for discovery operations."""
    
    def __init__(
        self,
        config: Config,
        task_manager: TaskManager,
        data_dir: Path,
        db: Optional[SpectraDB] = None
    ):
        self.config = config
        self.task_manager = task_manager
        self.data_dir = data_dir
        self.db = db or SpectraDB(Path(config.data.get("db_path", "spectra.db")))
        self.manager: Optional[SpectraCrawlerManager] = None
    
    async def discover_from_seed(
        self,
        seed: str,
        depth: int = 1,
        max_messages: int = 1000,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Discover groups from a seed entity.
        
        Args:
            seed: Seed entity identifier
            depth: Discovery depth (1-3)
            max_messages: Maximum messages to check per entity
            options: Additional options
            
        Returns:
            Task ID and status
        """
        options = options or {}
        
        # Create task
        task_id = await self.task_manager.create_task(
            operation="discover",
            params={
                "seed": seed,
                "depth": depth,
                "max_messages": max_messages,
                "options": options
            }
        )
        
        # Execute in background
        asyncio.create_task(self._execute_discovery(task_id, seed, depth, max_messages))
        
        return {
            "task_id": task_id,
            "discovery_id": task_id,  # Alias for compatibility
            "status": "queued",
            "seed": seed
        }
    
    async def _execute_discovery(
        self,
        task_id: str,
        seed: str,
        depth: int,
        max_messages: int
    ):
        """Execute discovery operation."""
        try:
            await self.task_manager.update_task_status(task_id, TaskStatus.RUNNING)
            
            # Initialize manager
            if not self.manager:
                self.manager = SpectraCrawlerManager(
                    config=self.config,
                    data_dir=self.data_dir,
                    db_path=Path(self.config.data.get("db_path", "spectra.db"))
                )
                await self.manager.initialize()
            
            # Perform discovery
            discovered = await self.manager.discover_from_seed(
                seed,
                depth=depth,
                max_messages=max_messages
            )
            
            await self.task_manager.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                progress=100.0,
                result={
                    "discovered_count": len(discovered),
                    "discovered_groups": list(discovered)
                }
            )
        except Exception as e:
            await self.task_manager.update_task_status(
                task_id,
                TaskStatus.FAILED,
                error=str(e)
            )
        finally:
            if self.manager:
                await self.manager.close()
    
    async def get_discovery_status(self, discovery_id: str) -> Dict[str, Any]:
        """
        Get discovery status.
        
        Args:
            discovery_id: Discovery task ID
            
        Returns:
            Discovery status information
        """
        task = await self.task_manager.get_task(discovery_id)
        
        if not task:
            return {
                "discovery_id": discovery_id,
                "status": "not_found"
            }
        
        return {
            "discovery_id": discovery_id,
            "status": task.status.value,
            "progress": task.progress,
            "seed": task.params.get("seed"),
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at.isoformat(),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None
        }
    
    async def get_discovery_results(self, discovery_id: str) -> Dict[str, Any]:
        """
        Get discovery results.
        
        Args:
            discovery_id: Discovery task ID
            
        Returns:
            Discovery results
        """
        task = await self.task_manager.get_task(discovery_id)
        
        if not task:
            return {
                "discovery_id": discovery_id,
                "error": "Discovery not found"
            }
        
        if task.status != TaskStatus.COMPLETED:
            return {
                "discovery_id": discovery_id,
                "status": task.status.value,
                "message": "Discovery not completed yet"
            }
        
        return {
            "discovery_id": discovery_id,
            "status": "completed",
            "results": task.result or {}
        }
