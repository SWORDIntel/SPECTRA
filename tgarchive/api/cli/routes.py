"""
CLI API Routes
==============

HTTP endpoints for executing CLI commands.
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import List, Dict, Any
from flask import request, jsonify

from ..routes import cli_bp
from ..security import require_auth, require_role, rate_limit
from ..services import TaskManager, TaskStatus

logger = logging.getLogger(__name__)

# Global service instance
_task_manager: TaskManager = None


def init_cli_routes(app, task_manager: TaskManager):
    """Initialize CLI API routes with dependencies."""
    global _task_manager
    
    _task_manager = task_manager
    
    app.register_blueprint(cli_bp, url_prefix='/api/cli')


@cli_bp.route('/execute', methods=['POST'])
@require_auth
@require_role('admin', 'analyst')
@rate_limit(limit=10, per='user')
def execute_command():
    """
    Execute a CLI command.
    
    Request JSON:
        {
            "command": "archive",
            "args": ["--entity", "@channel_name"],
            "options": {}
        }
    
    Returns:
        {
            "command_id": "uuid",
            "status": "queued"
        }
    """
    try:
        data = request.get_json() or {}
        command = data.get('command')
        args = data.get('args', [])
        options = data.get('options', {})
        
        if not command:
            return jsonify({'error': 'command is required'}), 400
        
        # Create task
        command_id = str(uuid.uuid4())
        task_id = asyncio.run(_task_manager.create_task(
            operation='cli_command',
            params={
                'command': command,
                'args': args,
                'options': options
            },
            metadata={'command_id': command_id}
        ))
        
        # Execute in background
        asyncio.create_task(_execute_cli_command(task_id, command, args, options))
        
        return jsonify({
            "command_id": command_id,
            "task_id": task_id,
            "status": "queued",
            "command": command
        }), 202
    except Exception as e:
        logger.error(f"CLI command execution failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


async def _execute_cli_command(task_id: str, command: str, args: List[str], options: Dict[str, Any]):
    """Execute CLI command asynchronously."""
    try:
        await _task_manager.update_task_status(task_id, TaskStatus.RUNNING)
        
        # Build command
        cmd = ['python', '-m', 'tgarchive', command] + args
        
        # Execute command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=Path(__file__).parent.parent.parent.parent
        )
        
        stdout, stderr = await process.communicate()
        
        result = {
            "exit_code": process.returncode,
            "stdout": stdout.decode('utf-8') if stdout else '',
            "stderr": stderr.decode('utf-8') if stderr else ''
        }
        
        if process.returncode == 0:
            await _task_manager.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                progress=100.0,
                result=result
            )
        else:
            await _task_manager.update_task_status(
                task_id,
                TaskStatus.FAILED,
                error=result.get('stderr', 'Command failed'),
                result=result
            )
    except Exception as e:
        await _task_manager.update_task_status(
            task_id,
            TaskStatus.FAILED,
            error=str(e)
        )


@cli_bp.route('/commands', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def list_commands():
    """
    List available CLI commands.
    
    Returns:
        {
            "commands": [
                {
                    "name": "archive",
                    "description": "Archive a channel/group",
                    "args": [...]
                }
            ]
        }
    """
    try:
        # This would parse the CLI help or command definitions
        commands = [
            {"name": "archive", "description": "Archive a channel/group"},
            {"name": "discover", "description": "Discover groups from seed"},
            {"name": "network", "description": "Analyze network graph"},
            {"name": "forward", "description": "Forward messages"},
            {"name": "accounts", "description": "Manage accounts"},
            {"name": "schedule", "description": "Manage scheduled tasks"},
        ]
        
        return jsonify({"commands": commands}), 200
    except Exception as e:
        logger.error(f"Failed to list commands: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@cli_bp.route('/<command_id>/status', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_command_status(command_id):
    """
    Get command execution status.
    
    Returns:
        {
            "command_id": "uuid",
            "status": "running",
            "progress": 45.0
        }
    """
    try:
        # Find task by command_id in metadata
        tasks = asyncio.run(_task_manager.list_tasks(operation='cli_command'))
        
        for task in tasks:
            if task.metadata.get('command_id') == command_id:
                return jsonify({
                    "command_id": command_id,
                    "status": task.status.value,
                    "progress": task.progress,
                    "created_at": task.created_at.isoformat(),
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None
                }), 200
        
        return jsonify({'error': 'Command not found'}), 404
    except Exception as e:
        logger.error(f"Failed to get command status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@cli_bp.route('/<command_id>/result', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_command_result(command_id):
    """
    Get command execution result.
    
    Returns:
        {
            "command_id": "uuid",
            "status": "completed",
            "result": {
                "exit_code": 0,
                "stdout": "...",
                "stderr": ""
            }
        }
    """
    try:
        tasks = asyncio.run(_task_manager.list_tasks(operation='cli_command'))
        
        for task in tasks:
            if task.metadata.get('command_id') == command_id:
                if task.status != TaskStatus.COMPLETED:
                    return jsonify({
                        "command_id": command_id,
                        "status": task.status.value,
                        "message": "Command not completed yet"
                    }), 200
                
                return jsonify({
                    "command_id": command_id,
                    "status": "completed",
                    "result": task.result or {}
                }), 200
        
        return jsonify({'error': 'Command not found'}), 404
    except Exception as e:
        logger.error(f"Failed to get command result: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
