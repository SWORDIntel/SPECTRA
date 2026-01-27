"""
Services API Routes
===================

Scheduler, mirror, and file sorting service endpoints.
"""

import asyncio
import logging
from flask import request, jsonify
from pathlib import Path

from . import services_bp
from ..security import require_auth, require_role, rate_limit
from ...core.config_models import Config
from ...db import SpectraDB
from ...services.scheduler_service import SchedulerDaemon
from ...services.group_mirror import GroupMirrorManager
from ...services.file_sorting_manager import FileSortingManager

logger = logging.getLogger(__name__)

# Global service instances
_config: Config = None
_db: SpectraDB = None
_scheduler: SchedulerDaemon = None


def init_services_routes(app, config: Config):
    """Initialize services routes with dependencies."""
    global _config, _db, _scheduler
    
    _config = config
    db_path = Path(config.data.get("db_path", "spectra.db"))
    _db = SpectraDB(db_path)
    
    state_path = config.data.get("scheduler", {}).get("state_file", "scheduler_state.json")
    _scheduler = SchedulerDaemon(config.config_path, state_path)
    
    app.register_blueprint(services_bp, url_prefix='/api/services')


@services_bp.route('/scheduler/jobs', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def list_scheduler_jobs():
    """
    List all scheduled jobs.
    
    Returns:
        {
            "jobs": [...],
            "total": 5
        }
    """
    try:
        jobs = _scheduler.list_jobs()
        return jsonify({
            "jobs": jobs if isinstance(jobs, list) else [],
            "total": len(jobs) if isinstance(jobs, list) else 0
        }), 200
    except Exception as e:
        logger.error(f"Failed to list scheduler jobs: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@services_bp.route('/scheduler/jobs', methods=['POST'])
@require_auth
@require_role('admin')
@rate_limit(limit=10, per='user')
def create_scheduler_job():
    """
    Create a scheduled job.
    
    Request JSON:
        {
            "name": "job_name",
            "schedule": "*/5 * * * *",
            "command": "spectra archive --entity @channel"
        }
    
    Returns:
        {
            "message": "Job created successfully",
            "job": {...}
        }
    """
    try:
        data = request.get_json() or {}
        name = data.get('name')
        schedule = data.get('schedule')
        command = data.get('command')
        
        if not all([name, schedule, command]):
            return jsonify({'error': 'name, schedule, and command are required'}), 400
        
        _scheduler.add_job(name, schedule, command)
        
        return jsonify({
            "message": "Job created successfully",
            "job": {
                "name": name,
                "schedule": schedule,
                "command": command
            }
        }), 201
    except Exception as e:
        logger.error(f"Failed to create scheduler job: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@services_bp.route('/scheduler/jobs/<job_name>', methods=['DELETE'])
@require_auth
@require_role('admin')
@rate_limit(limit=10, per='user')
def delete_scheduler_job(job_name):
    """
    Delete a scheduled job.
    
    Returns:
        {
            "message": "Job deleted successfully"
        }
    """
    try:
        _scheduler.remove_job(job_name)
        return jsonify({'message': 'Job deleted successfully'}), 200
    except Exception as e:
        logger.error(f"Failed to delete scheduler job: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@services_bp.route('/mirror', methods=['POST'])
@require_auth
@rate_limit(limit=5, per='user')
def mirror_group():
    """
    Mirror a group to another group.
    
    Request JSON:
        {
            "source": "@source_group",
            "destination": "@dest_group",
            "source_account": "spectra_1",
            "destination_account": "spectra_2"
        }
    
    Returns:
        {
            "task_id": "uuid",
            "mirror_id": "uuid",
            "status": "queued"
        }
    """
    try:
        data = request.get_json() or {}
        source = data.get('source')
        destination = data.get('destination')
        source_account = data.get('source_account')
        destination_account = data.get('destination_account')
        
        if not all([source, destination, source_account, destination_account]):
            return jsonify({'error': 'source, destination, source_account, and destination_account are required'}), 400
        
        # Create mirror task
        import uuid
        mirror_id = str(uuid.uuid4())
        
        # Execute in background
        asyncio.create_task(_execute_mirror(mirror_id, source, destination, source_account, destination_account))
        
        return jsonify({
            "task_id": mirror_id,
            "mirror_id": mirror_id,
            "status": "queued",
            "source": source,
            "destination": destination
        }), 202
    except Exception as e:
        logger.error(f"Mirror request failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


async def _execute_mirror(mirror_id: str, source: str, destination: str, source_account: str, destination_account: str):
    """Execute mirror operation."""
    try:
        manager = GroupMirrorManager(
            config=_config,
            db=_db,
            source_account_id=source_account,
            dest_account_id=destination_account
        )
        
        try:
            await manager.mirror_group(source, destination)
            logger.info(f"Mirror {mirror_id} completed successfully")
        finally:
            await manager.close()
    except Exception as e:
        logger.error(f"Mirror {mirror_id} failed: {e}", exc_info=True)


@services_bp.route('/mirror/<mirror_id>/status', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_mirror_status(mirror_id):
    """
    Get mirror status.
    
    Returns:
        {
            "mirror_id": "uuid",
            "status": "completed"
        }
    """
    try:
        # This would require task tracking
        return jsonify({
            "mirror_id": mirror_id,
            "status": "unknown",
            "message": "Mirror status tracking not yet implemented"
        }), 200
    except Exception as e:
        logger.error(f"Failed to get mirror status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@services_bp.route('/sort', methods=['POST'])
@require_auth
@rate_limit(limit=5, per='user')
def start_file_sorting():
    """
    Start file sorting service.
    
    Request JSON:
        {
            "directory": "/path/to/watch",
            "output_directory": "/path/to/output"
        }
    
    Returns:
        {
            "task_id": "uuid",
            "sort_id": "uuid",
            "status": "queued"
        }
    """
    try:
        data = request.get_json() or {}
        directory = data.get('directory')
        output_directory = data.get('output_directory')
        
        if not directory or not output_directory:
            return jsonify({'error': 'directory and output_directory are required'}), 400
        
        # Create sort task
        import uuid
        sort_id = str(uuid.uuid4())
        
        # Start file sorting (runs in background)
        sorting_manager = FileSortingManager(
            config=_config.data,
            output_dir=output_directory,
            db=_db
        )
        
        from ...services.file_system_watcher import start_watching
        # This starts a background watcher
        start_watching(Path(directory), sorting_manager)
        
        return jsonify({
            "task_id": sort_id,
            "sort_id": sort_id,
            "status": "running",
            "directory": directory,
            "output_directory": output_directory
        }), 202
    except Exception as e:
        logger.error(f"File sorting request failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@services_bp.route('/sort/<sort_id>/status', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_sort_status(sort_id):
    """
    Get file sorting status.
    
    Returns:
        {
            "sort_id": "uuid",
            "status": "running"
        }
    """
    try:
        # This would require task tracking
        return jsonify({
            "sort_id": sort_id,
            "status": "running",
            "message": "Sort status tracking not yet implemented"
        }), 200
    except Exception as e:
        logger.error(f"Failed to get sort status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
