import logging
import sys
import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path

# Try to import QIHSE to initialize our signature log engine combo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "QIHSE" / "python"))
try:
    from qihse.timeseries import TimeSeriesDB
    QIHSE_AVAILABLE = True
except ImportError:
    QIHSE_AVAILABLE = False

class KeystoneQihseHandler(logging.Handler):
    """
    Signature QIHSE KEYSTONE combo log engine.
    Forwards structured logs through KEYSTONE ingestion logic into QIHSE DB.
    """
    def __init__(self):
        super().__init__()
        # Initialization of the timeseries DB for logging
        if QIHSE_AVAILABLE:
            try:
                self.tsdb = TimeSeriesDB()
            except Exception:
                self.tsdb = None
        else:
            self.tsdb = None

    def emit(self, record):
        try:
            # Map log levels to series_id for the QIHSE TSDB
            level_map = {
                logging.DEBUG: 0,
                logging.INFO: 1,
                logging.WARNING: 2,
                logging.ERROR: 3,
                logging.CRITICAL: 4
            }
            series_id = level_map.get(record.levelno, 1)
            
            # Timestamp for TSDB
            timestamp = int(time.time())
            
            # Value metric
            value = 1.0
            
            if self.tsdb:
                self.tsdb.insert(series_id, timestamp, value)
                
                # In a full implementation we would stream the JSON log to KEYSTONE's bridge
                # msg = self.format(record)
                # payload = json.dumps({"level": record.levelname, "name": record.name, "msg": msg})
                # _libkeystone.ingest(payload)
                
        except Exception:
            self.handleError(record)

def setup_log_engine(app_name: str) -> logging.Logger:
    """Setup unified logging engine for SPECTRA using KEYSTONE+QIHSE."""
    logs_dir = Path.cwd() / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    # Configure root logger with force=True to fix the initialization bug
    log_file = logs_dir / f"{app_name}_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"
    
    handlers = [
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
        KeystoneQihseHandler()
    ]
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True
    )
    
    # Suppress verbose telethon logging
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("telethon.network").setLevel(logging.WARNING)
    
    return logging.getLogger(app_name)
