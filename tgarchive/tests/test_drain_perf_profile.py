import sqlite3
import tempfile
from pathlib import Path
import time
import json
import os
import cProfile
import pstats

from tgarchive.db.db_base import BaseDB
from tgarchive.db.index_outbox import IndexOutbox
from tgarchive.db.index_projector import IndexProjector

def run_perf():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "spectra.db"
        with BaseDB(db_path) as db: pass
        outbox = IndexOutbox(db_path)
        projector = IndexProjector(db_path)
        message_events = [{"source_table": "messages", "source_key": f"-10012345:{i}", "event_type": "insert", "payload": {"id": i, "channel_id": -10012345, "message": f"Hello world {i}", "date": "2026-08-22T00:00:00+00:00", "from_id": 1000 + (i % 100)}} for i in range(10000)]
        with sqlite3.connect(db_path) as conn:
            outbox.bulk_append_to(conn, message_events)
            conn.commit()
            
        pr = cProfile.Profile()
        pr.enable()
        projector.drain(batch_size=1000)
        pr.disable()
        
        with open("/tmp/agent_logs/profile.txt", "w") as f:
            ps = pstats.Stats(pr, stream=f).sort_stats('tottime')
            ps.print_stats(30)
            
run_perf()
