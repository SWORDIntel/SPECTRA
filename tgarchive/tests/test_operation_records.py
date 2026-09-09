import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tgarchive.db.spectra_db import SpectraDB
from tgarchive.db.schema import SCHEMA_SQL
from tgarchive.operations.models import OperationEnvelope, OperationResult, OperationEvent, OperationError

class TestOperationRecords(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        
        # init DB with schema
        self.db = SpectraDB(self.db_path)
        self.db.cur.executescript(SCHEMA_SQL)
        self.db.commit()

    def tearDown(self):
        if hasattr(self.db, 'db') and self.db.db:
            self.db.db.close()
        self.temp_dir.cleanup()

    def test_save_and_get_operation(self):
        envelope = OperationEnvelope(
            operation_id="op-123",
            arguments={"arg1": "value1"},
            dry_run=False,
            idempotency_key="idemp-123"
        )
        
        result = OperationResult.completed(
            operation_id="op-123",
            result={"output": "success"},
            idempotency_key="idemp-123"
        )
        
        # Add an event
        event = OperationEvent(event="started", message="Started operation")
        result.events.append(event)
        
        self.db.save_operation(envelope, result)
        
        # Get operation
        saved_op = self.db.get_operation("op-123")
        self.assertIsNotNone(saved_op)
        self.assertEqual(saved_op["operation_id"], "op-123")
        self.assertEqual(saved_op["arguments"], {"arg1": "value1"})
        self.assertEqual(saved_op["status"], "completed")
        self.assertEqual(saved_op["result"], {"output": "success"})
        self.assertEqual(saved_op["idempotency_key"], "idemp-123")
        
        # Check events
        events = saved_op["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "started")
        self.assertEqual(events[0]["message"], "Started operation")
        outbox_sources = {
            row[0]
            for row in self.db.cur.execute("SELECT source_table FROM index_outbox").fetchall()
        }
        self.assertEqual(outbox_sources, {"operations", "operation_events"})

    def test_cancel_operation(self):
        envelope = OperationEnvelope(operation_id="op-run")
        result = OperationResult(
            operation_id="op-run",
            status="running"
        )
        self.db.save_operation(envelope, result)
        
        # Cancel running op
        self.assertTrue(self.db.cancel_operation("op-run"))
        
        saved_op = self.db.get_operation("op-run")
        self.assertEqual(saved_op["status"], "cancelled")
        
        # Cannot cancel completed op
        result.status = "completed"
        self.db.save_operation(envelope, result)
        self.assertFalse(self.db.cancel_operation("op-run"))

    def test_idempotency_lookup(self):
        envelope = OperationEnvelope(
            operation_id="op-idemp",
            idempotency_key="key-abc"
        )
        result = OperationResult.completed(
            operation_id="op-idemp",
            result={"done": True},
            idempotency_key="key-abc"
        )
        self.db.save_operation(envelope, result)
        
        found_op = self.db.get_operation_by_idempotency_key("key-abc")
        self.assertIsNotNone(found_op)
        self.assertEqual(found_op["operation_id"], "op-idemp")
        
        not_found = self.db.get_operation_by_idempotency_key("key-def")
        self.assertIsNone(not_found)

    def test_audit_log(self):
        envelope = OperationEnvelope(operation_id="op-1")
        result = OperationResult(
            operation_id="op-1",
            status="running"
        )
        self.db.save_operation(envelope, result)

        self.db.save_audit_log(
            operation_id="op-1",
            action="execute",
            user="admin",
            authorization="role:admin",
            details={"ip": "127.0.0.1"}
        )
        
        query = "SELECT * FROM operation_audit_log"
        rows = self.db.cur.execute(query).fetchall()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[1], "op-1")
        self.assertEqual(row[2], "execute")
        self.assertEqual(row[3], "admin")
        self.assertEqual(row[4], "role:admin")
        self.assertEqual(json.loads(row[5]), {"ip": "127.0.0.1"})
        outbox_row = self.db.cur.execute(
            "SELECT event_type, payload_json FROM index_outbox WHERE source_table='operation_audit_log'"
        ).fetchone()
        self.assertEqual(outbox_row[0], "execute")
        self.assertEqual(json.loads(outbox_row[1])["user"], "admin")

if __name__ == "__main__":
    unittest.main()
