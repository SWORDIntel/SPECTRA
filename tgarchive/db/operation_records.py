"""Operation DB wrapper."""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from tgarchive.operations.models import OperationEnvelope, OperationResult, OperationEvent, OperationError
from .index_outbox import IndexOutbox

class OperationRecords:
    def __init__(self, db_manager):
        self.db = db_manager

    def save_operation(self, envelope: OperationEnvelope, result: OperationResult) -> None:
        """Save an operation record."""
        # Convert objects to JSON
        arguments_json = json.dumps(envelope.arguments)
        result_json = json.dumps(result.result) if result.result is not None else None
        error_json = json.dumps(result.error.model_dump()) if result.error else None
        
        started_at_str = result.started_at.isoformat()
        finished_at_str = result.finished_at.isoformat() if result.finished_at else None
        
        query = """
        INSERT OR REPLACE INTO operations 
        (operation_id, operation_name, arguments, status, result, error, dry_run, idempotency_key, started_at, finished_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        self.db.cur.execute(query, (
            envelope.operation_id,
            envelope.operation_id.split("-")[0] if "-" in envelope.operation_id else envelope.operation_id, # not perfect, but schema requires operation_name
            arguments_json,
            result.status,
            result_json,
            error_json,
            envelope.dry_run,
            envelope.idempotency_key,
            started_at_str,
            finished_at_str
        ))
        IndexOutbox.append_to(
            self.db.conn,
            source_table="operations",
            source_key=envelope.operation_id,
            event_type="save",
            payload={
                "operation_id": envelope.operation_id,
                "status": result.status,
                "arguments": envelope.arguments,
                "result": result.result,
                "error": result.error.model_dump(mode="json") if result.error else None,
                "started_at": started_at_str,
                "finished_at": finished_at_str,
            },
            source_revision=finished_at_str or started_at_str,
        )
        self.db.commit()
        
        # Save events
        for event in result.events:
            self.save_operation_event(envelope.operation_id, event)

    def save_operation_event(self, operation_id: str, event: OperationEvent) -> None:
        """Save a single operation event."""
        data_json = json.dumps(event.data) if event.data else None
        timestamp_str = event.timestamp.isoformat()
        
        query = """
        INSERT INTO operation_events 
        (operation_id, event, message, progress, data, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        self.db.cur.execute(query, (
            operation_id,
            event.event,
            event.message,
            event.progress,
            data_json,
            timestamp_str
        ))
        event_id = int(self.db.cur.lastrowid)
        IndexOutbox.append_to(
            self.db.conn,
            source_table="operation_events",
            source_key=str(event_id),
            event_type=event.event,
            payload={
                "event_id": event_id,
                "operation_id": operation_id,
                "event": event.event,
                "message": event.message,
                "progress": event.progress,
                "data": event.data,
                "timestamp": timestamp_str,
            },
            source_revision=timestamp_str,
        )
        self.db.commit()

    def get_operation(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve an operation."""
        query = "SELECT * FROM operations WHERE operation_id = ?"
        row = self.db.cur.execute(query, (operation_id,)).fetchone()
        if not row:
            return None
            
        columns = [desc[0] for desc in self.db.cur.description]
        data = dict(zip(columns, row))
        
        # Parse JSON fields
        for field in ["arguments", "result", "error"]:
            if data.get(field):
                data[field] = json.loads(data[field])
                
        # Get events
        data["events"] = self.get_operation_events(operation_id)
        
        return data

    def get_operation_events(self, operation_id: str) -> List[Dict[str, Any]]:
        """Retrieve events for an operation."""
        query = "SELECT * FROM operation_events WHERE operation_id = ? ORDER BY timestamp ASC"
        rows = self.db.cur.execute(query, (operation_id,)).fetchall()
        
        events = []
        columns = [desc[0] for desc in self.db.cur.description]
        for row in rows:
            event_data = dict(zip(columns, row))
            if event_data.get("data"):
                event_data["data"] = json.loads(event_data["data"])
            events.append(event_data)
            
        return events

    def update_operation_status(self, operation_id: str, status: str, result: Any = None, error: Any = None) -> None:
        """Update an operation's status and optional result/error."""
        updates = ["status = ?"]
        params = [status]
        
        if result is not None:
            updates.append("result = ?")
            params.append(json.dumps(result))
            
        if error is not None:
            updates.append("error = ?")
            params.append(json.dumps(error))
            
        if status in ("completed", "failed", "cancelled"):
            updates.append("finished_at = ?")
            params.append(datetime.now(timezone.utc).isoformat())
            
        query = f"UPDATE operations SET {', '.join(updates)} WHERE operation_id = ?"
        params.append(operation_id)
        
        self.db.cur.execute(query, tuple(params))
        self.db.commit()

    def save_audit_log(self, operation_id: Optional[str], action: str, user: Optional[str] = None, authorization: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        """Save an audit log entry."""
        details_json = json.dumps(details) if details else None
        timestamp_str = datetime.now(timezone.utc).isoformat()
        
        query = """
        INSERT INTO operation_audit_log 
        (operation_id, action, user, authorization, details, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        self.db.cur.execute(query, (
            operation_id,
            action,
            user,
            authorization,
            details_json,
            timestamp_str
        ))
        audit_id = int(self.db.cur.lastrowid)
        IndexOutbox.append_to(
            self.db.conn,
            source_table="operation_audit_log",
            source_key=str(audit_id),
            event_type=action,
            payload={
                "event_id": audit_id,
                "operation_id": operation_id,
                "action": action,
                "user": user,
                "authorization": authorization,
                "details": details,
                "timestamp": timestamp_str,
            },
            source_revision=timestamp_str,
        )
        self.db.commit()

    def cancel_operation(self, operation_id: str) -> bool:
        """Cancel a running operation."""
        # Check current status
        query = "SELECT status FROM operations WHERE operation_id = ?"
        row = self.db.cur.execute(query, (operation_id,)).fetchone()
        
        if not row:
            return False
            
        current_status = row[0]
        if current_status in ("completed", "failed", "cancelled"):
            return False
            
        # Update status to cancelled
        self.update_operation_status(operation_id, "cancelled")
        
        # Save event
        self.save_operation_event(operation_id, OperationEvent(
            event="cancelled",
            message="Operation cancelled by request"
        ))
        
        # Save audit log
        self.save_audit_log(operation_id, "cancel_operation")
        
        return True

    def get_operation_by_idempotency_key(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve an operation by its idempotency key."""
        query = "SELECT operation_id FROM operations WHERE idempotency_key = ?"
        row = self.db.cur.execute(query, (idempotency_key,)).fetchone()
        if not row:
            return None
        return self.get_operation(row[0])
