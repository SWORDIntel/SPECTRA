"""
Async Task Management
=====================

Background task execution, status tracking, and result storage.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task status enumeration."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """Task data structure."""
    task_id: str
    operation: str
    params: Dict[str, Any]
    status: TaskStatus = TaskStatus.QUEUED
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class TaskManager:
    """Manages background task execution and tracking."""
    
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self._lock = asyncio.Lock()
    
    async def create_task(
        self,
        operation: str,
        params: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a new task.
        
        Args:
            operation: Operation name
            params: Operation parameters
            metadata: Optional metadata
            
        Returns:
            Task ID
        """
        task_id = str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            operation=operation,
            params=params,
            metadata=metadata or {}
        )
        
        async with self._lock:
            self.tasks[task_id] = task
        
        logger.info(f"Created task {task_id} for operation {operation}")
        return task_id
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        async with self._lock:
            return self.tasks.get(task_id)
    
    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        progress: Optional[float] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> bool:
        """
        Update task status.
        
        Returns:
            True if task was found and updated
        """
        async with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            
            task.status = status
            if progress is not None:
                task.progress = progress
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            
            if status == TaskStatus.RUNNING and not task.started_at:
                task.started_at = datetime.now()
            elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                task.completed_at = datetime.now()
            
            return True
    
    async def execute_task(
        self,
        task_id: str,
        handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
    ) -> None:
        """
        Execute a task with the given handler.
        
        Args:
            task_id: Task ID
            handler: Async function that takes params and returns result
        """
        task = await self.get_task(task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return
        
        await self.update_task_status(task_id, TaskStatus.RUNNING)
        
        try:
            result = await handler(task.params)
            await self.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                progress=100.0,
                result=result
            )
            logger.info(f"Task {task_id} completed successfully")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Task {task_id} failed: {error_msg}", exc_info=True)
            await self.update_task_status(
                task_id,
                TaskStatus.FAILED,
                error=error_msg
            )
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        task = await self.get_task(task_id)
        if not task:
            return False
        
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False
        
        await self.update_task_status(task_id, TaskStatus.CANCELLED)
        logger.info(f"Task {task_id} cancelled")
        return True
    
    async def list_tasks(
        self,
        operation: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        limit: int = 100
    ) -> list[Task]:
        """List tasks with optional filters."""
        async with self._lock:
            tasks = list(self.tasks.values())
        
        if operation:
            tasks = [t for t in tasks if t.operation == operation]
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        # Sort by created_at descending
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]
    
    async def cleanup_old_tasks(self, days: int = 7) -> int:
        """
        Remove tasks older than specified days.
        
        Returns:
            Number of tasks removed
        """
        cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
        removed = 0
        
        async with self._lock:
            to_remove = [
                task_id for task_id, task in self.tasks.items()
                if task.created_at.timestamp() < cutoff
                and task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            ]
            
            for task_id in to_remove:
                del self.tasks[task_id]
                removed += 1
        
        if removed > 0:
            logger.info(f"Cleaned up {removed} old tasks")
        
        return removed
