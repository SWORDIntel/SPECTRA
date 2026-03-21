"""
Forwarding Service
==================

Service layer for forwarding operations.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from ...core.config_models import Config
from ...forwarding import AttachmentForwarder
from ...db import SpectraDB
from .tasks import TaskManager, TaskStatus

logger = logging.getLogger(__name__)


def _coerce_optional_int(value):
    if value in (None, ""):
        return None
    return int(value)


def _resolve_copy_mode(options: Dict[str, Any]) -> bool:
    quote_mode = options.get("quote_mode")
    if isinstance(quote_mode, str):
        normalized = quote_mode.strip().lower()
        if normalized in {"copy", "plain", "without_quote", "without-quote", "no_quote", "no-quote"}:
            return True
        if normalized in {"forward", "quoted", "with_quote", "with-quote"}:
            return False

    preserve_forward_header = options.get("preserve_forward_header")
    if preserve_forward_header is not None:
        return not bool(preserve_forward_header)

    return bool(options.get("copy_into_destination", False))


class ForwardingService:
    """Service for forwarding operations."""
    
    def __init__(self, config: Config, task_manager: TaskManager, db: Optional[SpectraDB] = None):
        self.config = config
        self.task_manager = task_manager
        self.db = db or SpectraDB(Path(config.data.get("db_path", "spectra.db")))

    def _build_forwarder(self, options: Dict[str, Any]) -> AttachmentForwarder:
        source_topic_id = _coerce_optional_int(options.get("source_topic_id"))
        destination_topic_id = _coerce_optional_int(options.get("destination_topic_id"))
        include_text_messages = bool(options.get("include_text_messages", False) or source_topic_id is not None)

        return AttachmentForwarder(
            config=self.config,
            db=self.db,
            forward_to_all_saved_messages=options.get("forward_to_all_saved", False),
            prepend_origin_info=options.get("prepend_origin_info", False),
            destination_topic_id=destination_topic_id,
            source_topic_id=source_topic_id,
            enable_deduplication=options.get("enable_deduplication", True),
            copy_messages_into_destination=_resolve_copy_mode(options),
            quote_copied_messages=bool(options.get("quote_copied_messages", False)),
            include_text_messages=include_text_messages,
        )
    
    async def forward_messages(
        self,
        origin_id: str,
        destination_id: str,
        account_identifier: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Forward messages from origin to destination.
        
        Args:
            origin_id: Origin channel/chat ID
            destination_id: Destination channel/chat ID
            account_identifier: Optional account identifier
            options: Forwarding options
            
        Returns:
            Task ID and status
        """
        options = options or {}
        
        # Create task
        task_id = await self.task_manager.create_task(
            operation="forward",
            params={
                "origin_id": origin_id,
                "destination_id": destination_id,
                "account_identifier": account_identifier,
                "options": options
            }
        )
        
        # Execute in background
        asyncio.create_task(self._execute_forward(task_id, origin_id, destination_id, account_identifier, options))
        
        return {
            "task_id": task_id,
            "forward_id": task_id,  # Alias for compatibility
            "status": "queued",
            "origin_id": origin_id,
            "destination_id": destination_id
        }
    
    async def _execute_forward(
        self,
        task_id: str,
        origin_id: str,
        destination_id: str,
        account_identifier: Optional[str],
        options: Dict[str, Any]
    ):
        """Execute forwarding operation."""
        try:
            await self.task_manager.update_task_status(task_id, TaskStatus.RUNNING)
            
            # Create forwarder
            forwarder = self._build_forwarder(options)
            
            try:
                # Forward messages
                last_message_id, stats = await forwarder.forward_messages(
                    origin_id=origin_id,
                    destination_id=destination_id,
                    account_identifier=account_identifier
                )
                
                await self.task_manager.update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    progress=100.0,
                    result={
                        "last_message_id": last_message_id,
                        "stats": stats
                    }
                )
            finally:
                await forwarder.close()
        except Exception as e:
            await self.task_manager.update_task_status(
                task_id,
                TaskStatus.FAILED,
                error=str(e)
            )
    
    async def forward_all_dialogs(
        self,
        destination_id: str,
        account_identifier: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Forward all dialogs to destination.
        
        Args:
            destination_id: Destination channel/chat ID
            account_identifier: Optional account identifier
            options: Forwarding options
            
        Returns:
            Task ID and status
        """
        options = options or {}
        
        task_id = await self.task_manager.create_task(
            operation="forward_all_dialogs",
            params={
                "destination_id": destination_id,
                "account_identifier": account_identifier,
                "options": options
            }
        )
        
        asyncio.create_task(self._execute_forward_all_dialogs(task_id, destination_id, account_identifier, options))
        
        return {
            "task_id": task_id,
            "status": "queued",
            "destination_id": destination_id
        }
    
    async def _execute_forward_all_dialogs(
        self,
        task_id: str,
        destination_id: str,
        account_identifier: Optional[str],
        options: Dict[str, Any]
    ):
        """Execute forward all dialogs operation."""
        try:
            await self.task_manager.update_task_status(task_id, TaskStatus.RUNNING)
            
            forwarder_options = dict(options)
            forwarder_options.pop("source_topic_id", None)
            forwarder = self._build_forwarder(forwarder_options)
            
            try:
                await forwarder.forward_all_dialogs(
                    destination_id=destination_id,
                    orchestration_account_identifier=account_identifier,
                    allowed_accounts=options.get("allowed_accounts"),
                    include_private_chats=options.get("include_private_chats", True),
                    include_saved_messages=options.get("include_saved_messages", False)
                )
                
                await self.task_manager.update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    progress=100.0,
                    result={"message": "All dialogs forwarded successfully"}
                )
            finally:
                await forwarder.close()
        except Exception as e:
            await self.task_manager.update_task_status(
                task_id,
                TaskStatus.FAILED,
                error=str(e)
            )
    
    async def forward_total_mode(
        self,
        destination_id: str,
        account_identifier: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Forward all accessible channels (total mode).
        
        Args:
            destination_id: Destination channel/chat ID
            account_identifier: Optional account identifier
            options: Forwarding options
            
        Returns:
            Task ID and status
        """
        options = options or {}
        
        task_id = await self.task_manager.create_task(
            operation="forward_total_mode",
            params={
                "destination_id": destination_id,
                "account_identifier": account_identifier,
                "options": options
            }
        )
        
        asyncio.create_task(self._execute_forward_total_mode(task_id, destination_id, account_identifier, options))
        
        return {
            "task_id": task_id,
            "status": "queued",
            "destination_id": destination_id
        }
    
    async def _execute_forward_total_mode(
        self,
        task_id: str,
        destination_id: str,
        account_identifier: Optional[str],
        options: Dict[str, Any]
    ):
        """Execute forward total mode operation."""
        try:
            await self.task_manager.update_task_status(task_id, TaskStatus.RUNNING)
            
            forwarder_options = dict(options)
            forwarder_options.pop("source_topic_id", None)
            forwarder = self._build_forwarder(forwarder_options)
            
            try:
                await forwarder.forward_all_accessible_channels(
                    destination_id=destination_id,
                    orchestration_account_identifier=account_identifier,
                    allowed_accounts=options.get("allowed_accounts")
                )
                
                await self.task_manager.update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    progress=100.0,
                    result={"message": "Total forward mode completed successfully"}
                )
            finally:
                await forwarder.close()
        except Exception as e:
            await self.task_manager.update_task_status(
                task_id,
                TaskStatus.FAILED,
                error=str(e)
            )
    
    async def get_forward_status(self, forward_id: str) -> Dict[str, Any]:
        """Get forwarding status."""
        task = await self.task_manager.get_task(forward_id)
        
        if not task:
            return {
                "forward_id": forward_id,
                "status": "not_found"
            }
        
        return {
            "forward_id": forward_id,
            "status": task.status.value,
            "progress": task.progress,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at.isoformat(),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None
        }
    
    async def get_forwarding_schedules(self) -> Dict[str, Any]:
        """Get all forwarding schedules."""
        if not self.db:
            return {"schedules": []}
        
        schedules = self.db.get_channel_forward_schedules()
        return {
            "schedules": [
                {
                    "id": s[0],
                    "channel_id": s[1],
                    "destination": s[2],
                    "schedule": s[3],
                    "last_message_id": s[4]
                }
                for s in schedules
            ]
        }
    
    async def create_forwarding_schedule(
        self,
        channel_id: int,
        destination: str,
        schedule: str
    ) -> Dict[str, Any]:
        """Create a forwarding schedule."""
        if not self.db:
            return {"error": "Database not available"}
        
        self.db.add_channel_forward_schedule(channel_id, destination, schedule)
        return {
            "message": "Schedule created successfully",
            "channel_id": channel_id,
            "destination": destination,
            "schedule": schedule
        }
    
    async def delete_forwarding_schedule(self, schedule_id: int) -> Dict[str, Any]:
        """Delete a forwarding schedule."""
        # This would require additional DB methods
        return {"message": "Schedule deletion not yet implemented"}
