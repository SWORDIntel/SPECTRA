import sqlite3
import tempfile
from pathlib import Path
import time
import json
import os

import pytest

from tgarchive.db.db_base import BaseDB
from tgarchive.db.index_outbox import IndexOutbox
from tgarchive.db.index_projector import IndexProjector

def test_drain_perf():
    # Setup temp DB
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "spectra.db"
        
        # Initialize schema properly
        with BaseDB(db_path) as db:
            pass # schema is created in BaseDB.__init__
            
        outbox = IndexOutbox(db_path)
        projector = IndexProjector(db_path)

        # 2. Insert 10,000 message events
        message_events = []
        for i in range(10000):
            message_events.append({
                "source_table": "messages",
                "source_key": f"-10012345:{i}",
                "event_type": "insert",
                "payload": {
                    "id": i,
                    "channel_id": -10012345,
                    "message": f"Hello world {i}",
                    "date": "2026-08-22T00:00:00+00:00",
                    "from_id": 1000 + (i % 100),
                }
            })
        
        # 3. Insert 1,000 user events
        user_events = []
        for i in range(1000):
            user_events.append({
                "source_table": "users",
                "source_key": f"{1000 + i}",
                "event_type": "insert",
                "payload": {
                    "id": 1000 + i,
                    "username": f"user_{i}",
                    "first_name": f"User {i}",
                }
            })
        
        # 4. Insert 500 media events
        media_events = []
        for i in range(500):
            media_events.append({
                "source_table": "media",
                "source_key": f"{2000 + i}",
                "event_type": "insert",
                "payload": {
                    "id": 2000 + i,
                    "message_id": i,
                    "file_path": f"/tmp/media_{i}.jpg",
                }
            })
            
        # Append all
        start_append = time.time()
        with sqlite3.connect(db_path) as conn:
            outbox.bulk_append_to(conn, message_events)
            outbox.bulk_append_to(conn, user_events)
            outbox.bulk_append_to(conn, media_events)
            conn.commit()
        append_time = time.time() - start_append
        print(f"Append time: {append_time:.2f}s")
        
        # 5. Measure drain time
        start_drain = time.time()
        result = projector.drain(batch_size=1000)
        drain_time = time.time() - start_drain
        
        total_events = 11500
        throughput = total_events / drain_time if drain_time > 0 else 0
        
        print(f"Drain time: {drain_time:.2f}s")
        print(f"Throughput: {throughput:.2f} events/sec")
        print(f"Result: {json.dumps(result, indent=2)}")
        
        assert result["ok"], "Drain failed"
        assert result["processed"] == total_events, f"Expected {total_events} processed, got {result['processed']}"
        
        # Write report
        os.makedirs("/tmp/agent_logs", exist_ok=True)
        report_content = f"""# Drain Performance Report

## Workload
- 10,000 message events
- 1,000 user events
- 500 media events
- Total events: {total_events}

## Metrics
- Append time: {append_time:.3f} seconds
- Drain time: {drain_time:.3f} seconds
- Throughput: {throughput:.2f} events/second
- Result OK: {result['ok']}
- Processed: {result['processed']}

## Projector Result Data
```json
{json.dumps(result, indent=2)}
```
"""
        with open("/tmp/agent_logs/drain_perf_report.md", "w") as f:
            f.write(report_content)
