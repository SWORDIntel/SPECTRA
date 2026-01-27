"""
CLI API Server
==============

HTTP endpoint for CLI command execution with queue management.
"""

import asyncio
import logging
import subprocess
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class CommandStatus(Enum):
    """Command execution status."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CommandResult:
    """Command execution result."""
    
    def __init__(self, command_id: str, command: str):
        self.command_id = command_id
        self.command = command
        self.status = CommandStatus.QUEUED
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.stdout: str = ""
        self.stderr: str = ""
        self.return_code: Optional[int] = None
        self.error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "command_id": self.command_id,
            "command": self.command,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "error": self.error
        }


class CLIServer:
    """Manages CLI command execution via HTTP API."""
    
    def __init__(self):
        self.commands: Dict[str, CommandResult] = {}
        self._lock = asyncio.Lock()
    
    async def execute_command(
        self,
        command: str,
        args: Optional[list] = None,
        cwd: Optional[str] = None
    ) -> str:
        """
        Execute a CLI command.
        
        Args:
            command: Command to execute (e.g., "spectra", "archive")
            args: Command arguments
            cwd: Working directory
            
        Returns:
            Command ID
        """
        command_id = str(uuid.uuid4())
        
        # Build full command
        full_command = [command]
        if args:
            full_command.extend(args)
        
        cmd_result = CommandResult(command_id, " ".join(full_command))
        
        async with self._lock:
            self.commands[command_id] = cmd_result
        
        # Execute in background
        asyncio.create_task(self._execute_command(cmd_result, full_command, cwd))
        
        return command_id
    
    async def _execute_command(
        self,
        cmd_result: CommandResult,
        command: list,
        cwd: Optional[str]
    ):
        """Execute command asynchronously."""
        try:
            cmd_result.status = CommandStatus.RUNNING
            cmd_result.started_at = datetime.now()
            
            # Execute command
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            
            stdout, stderr = await process.communicate()
            
            cmd_result.stdout = stdout.decode('utf-8', errors='ignore')
            cmd_result.stderr = stderr.decode('utf-8', errors='ignore')
            cmd_result.return_code = process.returncode
            cmd_result.completed_at = datetime.now()
            
            if process.returncode == 0:
                cmd_result.status = CommandStatus.COMPLETED
            else:
                cmd_result.status = CommandStatus.FAILED
                cmd_result.error = f"Command failed with return code {process.returncode}"
        
        except Exception as e:
            cmd_result.status = CommandStatus.FAILED
            cmd_result.error = str(e)
            cmd_result.completed_at = datetime.now()
            logger.error(f"Command execution failed: {e}", exc_info=True)
    
    async def get_command(self, command_id: str) -> Optional[CommandResult]:
        """Get command result by ID."""
        async with self._lock:
            return self.commands.get(command_id)
    
    async def list_commands(self, limit: int = 100) -> list[CommandResult]:
        """List recent commands."""
        async with self._lock:
            commands = list(self.commands.values())
            commands.sort(key=lambda c: c.created_at, reverse=True)
            return commands[:limit]
    
    async def cancel_command(self, command_id: str) -> bool:
        """Cancel a running command."""
        cmd_result = await self.get_command(command_id)
        if not cmd_result:
            return False
        
        if cmd_result.status not in (CommandStatus.QUEUED, CommandStatus.RUNNING):
            return False
        
        cmd_result.status = CommandStatus.CANCELLED
        cmd_result.completed_at = datetime.now()
        return True
    
    def get_available_commands(self) -> list[Dict[str, str]]:
        """
        Get list of available CLI commands.
        
        Returns:
            List of command dictionaries with name and description
        """
        return [
            {"name": "archive", "description": "Archive a Telegram channel/group"},
            {"name": "discover", "description": "Discover groups from seed"},
            {"name": "network", "description": "Analyze network graph"},
            {"name": "batch", "description": "Batch operations"},
            {"name": "forward", "description": "Forward messages"},
            {"name": "accounts", "description": "Manage accounts"},
            {"name": "schedule", "description": "Manage scheduled tasks"},
            {"name": "osint", "description": "OSINT operations"},
            {"name": "mirror", "description": "Mirror group"},
            {"name": "sort", "description": "Sort files"},
        ]
