"""Enhanced audit logging with NOT_STISLA indexing and export capabilities"""

import csv
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from ..search.not_stisla_bindings import NotStislaSearchEngine, NOT_STISLA_WORKLOAD_TELEMETRY, not_stisla_available
    NOT_STISLA_ENABLED = not_stisla_available()
except ImportError:
    NOT_STISLA_ENABLED = False


@dataclass
class AuditLogEntry:
    """Audit log entry"""
    timestamp: float
    event_type: str  # "operation", "config_change", "error", "access"
    user: str
    action: str
    details: Dict[str, Any]
    result: str  # "success", "failure", "warning"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AuditLogEntry':
        return cls(**data)


class AuditLogger:
    """Enhanced audit logging with NOT_STISLA indexing"""
    
    def __init__(self, log_dir: Optional[Path] = None, max_memory: int = 10000):
        if log_dir is None:
            log_dir = Path("data/audit_logs")
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.memory_log: deque = deque(maxlen=max_memory)
        self.not_stisla_engine = None
        self.timestamp_array: List[int] = []
        
        if NOT_STISLA_ENABLED:
            try:
                self.not_stisla_engine = NotStislaSearchEngine(NOT_STISLA_WORKLOAD_TELEMETRY)
            except Exception as e:
                logger.debug(f"NOT_STISLA not available for audit log: {e}")
    
    def log(self, event_type: str, user: str, action: str, details: Dict[str, Any], result: str = "success"):
        """Log an audit event"""
        entry = AuditLogEntry(
            timestamp=time.time(),
            event_type=event_type,
            user=user,
            action=action,
            details=details,
            result=result,
        )
        
        self.memory_log.append(entry)
        
        # Update NOT_STISLA index
        if self.not_stisla_engine:
            timestamp_int = int(entry.timestamp)
            import bisect
            bisect.insort(self.timestamp_array, timestamp_int)
        
        # Periodic flush to disk
        if len(self.memory_log) % 100 == 0:
            self._flush_to_disk()
    
    def _flush_to_disk(self):
        """Flush logs to disk"""
        log_file = self.log_dir / f"audit_{datetime.now().strftime('%Y%m%d')}.jsonl"
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                for entry in list(self.memory_log)[-100:]:
                    f.write(json.dumps(entry.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to flush audit log: {e}")
    
    def search_by_time(self, start_time: float, end_time: float) -> List[AuditLogEntry]:
        """Search logs by time range using NOT_STISLA"""
        results = []
        start_int = int(start_time)
        end_int = int(end_time)
        
        if self.not_stisla_engine and self.timestamp_array:
            # Use NOT_STISLA for fast search
            start_idx = self.not_stisla_engine.search(self.timestamp_array, start_int, tolerance=3600)
            end_idx = self.not_stisla_engine.search(self.timestamp_array, end_int, tolerance=3600)
            
            if start_idx is not None and end_idx is not None:
                for idx in range(start_idx, min(end_idx + 1, len(self.timestamp_array))):
                    timestamp = self.timestamp_array[idx]
                    for entry in self.memory_log:
                        if int(entry.timestamp) == timestamp and start_time <= entry.timestamp <= end_time:
                            results.append(entry)
        else:
            # Fallback to linear search
            for entry in self.memory_log:
                if start_time <= entry.timestamp <= end_time:
                    results.append(entry)
        
        return sorted(results, key=lambda e: e.timestamp, reverse=True)
    
    def export_csv(self, output_path: Path, start_time: Optional[float] = None, end_time: Optional[float] = None):
        """Export audit logs to CSV"""
        entries = self.memory_log
        if start_time and end_time:
            entries = self.search_by_time(start_time, end_time)
        
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['timestamp', 'event_type', 'user', 'action', 'result', 'details'])
                writer.writeheader()
                for entry in entries:
                    row = entry.to_dict()
                    row['details'] = json.dumps(row['details'])
                    writer.writerow(row)
        except Exception as e:
            logger.error(f"Failed to export audit log: {e}")
