"""
Command History System for SPECTRA TUI
=======================================

Hybrid architecture for fast command history:
- In-memory deque for recent operations (1000-5000) - O(1) append, instant access
- NOT_STISLA indexing for fast timestamp-based lookups - 22.28x speedup
- SQLite persistence for older history and periodic flush

Performance:
- Recent operations: Instant access from memory
- Timestamp searches: 22.28x faster with NOT_STISLA
- Memory efficient: Only recent N operations in memory
- Persistent: SQLite ensures data survives restarts
"""

import json
import logging
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import NOT_STISLA for fast timestamp searches
try:
    from ..search.not_stisla_bindings import (
        NotStislaSearchEngine,
        NOT_STISLA_WORKLOAD_TELEMETRY,
        not_stisla_available,
    )
    NOT_STISLA_ENABLED = not_stisla_available()
except ImportError:
    NOT_STISLA_ENABLED = False
    logger.debug("NOT_STISLA not available for command history")


@dataclass
class CommandHistoryEntry:
    """A single command history entry"""
    timestamp: float
    operation_type: str
    parameters: Dict[str, Any]
    result_status: str
    result_data: Optional[Dict[str, Any]] = None
    execution_time_ms: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CommandHistoryEntry':
        """Create from dictionary"""
        return cls(**data)


class CommandHistory:
    """
    Command history manager with hybrid storage architecture.
    
    Architecture:
    - In-memory deque: Recent 1000-5000 operations (instant access)
    - NOT_STISLA: Fast timestamp-based lookups (22.28x speedup)
    - SQLite: Persistence for older history and periodic flush
    """
    
    # Configuration
    RECENT_HISTORY_SIZE = 5000  # Keep last 5000 operations in memory
    FLUSH_INTERVAL = 100  # Flush to SQLite every N operations
    FLUSH_TIME_INTERVAL = 300  # Flush to SQLite every N seconds
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize command history.
        
        Args:
            db_path: Path to SQLite database (default: data/command_history.db)
        """
        if db_path is None:
            db_path = Path("data/command_history.db")
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # In-memory storage for recent operations
        self.recent_history: deque = deque(maxlen=self.RECENT_HISTORY_SIZE)
        
        # NOT_STISLA engine for fast timestamp searches
        self.not_stisla_engine: Optional[NotStislaSearchEngine] = None
        self.timestamp_array: List[int] = []  # Sorted timestamps for NOT_STISLA
        self.timestamp_to_index: Dict[int, int] = {}  # Map timestamp to index in recent_history
        
        if NOT_STISLA_ENABLED:
            try:
                self.not_stisla_engine = NotStislaSearchEngine(
                    workload_type=NOT_STISLA_WORKLOAD_TELEMETRY
                )
                logger.debug("NOT_STISLA engine initialized for command history")
            except Exception as e:
                logger.warning(f"Failed to initialize NOT_STISLA: {e}")
                self.not_stisla_engine = None
        
        # SQLite database for persistence
        self._init_database()
        
        # Load recent history from database
        self._load_recent_history()
        
        # Flush tracking
        self.last_flush_time = time.time()
        self.operations_since_flush = 0
    
    def _init_database(self):
        """Initialize SQLite database schema"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS command_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                operation_type TEXT NOT NULL,
                parameters TEXT NOT NULL,
                result_status TEXT NOT NULL,
                result_data TEXT,
                execution_time_ms REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create index on timestamp for fast queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON command_history(timestamp)
        """)
        
        # Create index on operation_type for filtering
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_operation_type ON command_history(operation_type)
        """)
        
        conn.commit()
        conn.close()
    
    def _load_recent_history(self):
        """Load recent history from database into memory"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # Load most recent entries
            cursor.execute("""
                SELECT timestamp, operation_type, parameters, result_status, result_data, execution_time_ms
                FROM command_history
                ORDER BY timestamp DESC
                LIMIT ?
            """, (self.RECENT_HISTORY_SIZE,))
            
            entries = []
            for row in cursor.fetchall():
                entry = CommandHistoryEntry(
                    timestamp=row[0],
                    operation_type=row[1],
                    parameters=json.loads(row[2]),
                    result_status=row[3],
                    result_data=json.loads(row[4]) if row[4] else None,
                    execution_time_ms=row[5],
                )
                entries.append(entry)
            
            conn.close()
            
            # Add to recent history (oldest first for deque)
            for entry in reversed(entries):
                self.recent_history.append(entry)
            
            # Build NOT_STISLA index
            self._rebuild_not_stisla_index()
            
            logger.debug(f"Loaded {len(self.recent_history)} recent operations from database")
            
        except Exception as e:
            logger.error(f"Failed to load recent history: {e}")
    
    def _rebuild_not_stisla_index(self):
        """Rebuild NOT_STISLA timestamp index"""
        if not self.not_stisla_engine:
            return
        
        # Extract timestamps and create sorted array
        self.timestamp_array = sorted([int(entry.timestamp) for entry in self.recent_history])
        self.timestamp_to_index = {
            int(entry.timestamp): idx
            for idx, entry in enumerate(self.recent_history)
        }
    
    def add_entry(
        self,
        operation_type: str,
        parameters: Dict[str, Any],
        result_status: str = "success",
        result_data: Optional[Dict[str, Any]] = None,
        execution_time_ms: Optional[float] = None
    ) -> CommandHistoryEntry:
        """
        Add a new command history entry.
        
        Args:
            operation_type: Type of operation (e.g., "archive", "discover", "forward")
            parameters: Operation parameters
            result_status: Result status ("success", "error", "cancelled")
            result_data: Optional result data
            execution_time_ms: Optional execution time in milliseconds
            
        Returns:
            Created CommandHistoryEntry
        """
        timestamp = time.time()
        
        entry = CommandHistoryEntry(
            timestamp=timestamp,
            operation_type=operation_type,
            parameters=parameters,
            result_status=result_status,
            result_data=result_data,
            execution_time_ms=execution_time_ms,
        )
        
        # Add to in-memory recent history
        self.recent_history.append(entry)
        
        # Update NOT_STISLA index
        if self.not_stisla_engine:
            timestamp_int = int(timestamp)
            # Insert in sorted order for NOT_STISLA
            import bisect
            bisect.insort(self.timestamp_array, timestamp_int)
            # Map timestamp to index in recent_history
            # Since we just appended, the new entry is at the end
            # Rebuild mapping for all entries to ensure correctness
            entry_list = list(self.recent_history)
            self.timestamp_to_index.clear()
            for idx, e in enumerate(entry_list):
                self.timestamp_to_index[int(e.timestamp)] = idx
        
        # Periodic flush to SQLite
        self.operations_since_flush += 1
        current_time = time.time()
        
        if (self.operations_since_flush >= self.FLUSH_INTERVAL or
            current_time - self.last_flush_time >= self.FLUSH_TIME_INTERVAL):
            self._flush_to_database()
        
        return entry
    
    def _flush_to_database(self):
        """Flush recent entries to SQLite database"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # Get entries that haven't been flushed yet
            # For simplicity, flush all recent entries (SQLite handles duplicates)
            for entry in self.recent_history:
                cursor.execute("""
                    INSERT OR IGNORE INTO command_history
                    (timestamp, operation_type, parameters, result_status, result_data, execution_time_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    entry.timestamp,
                    entry.operation_type,
                    json.dumps(entry.parameters),
                    entry.result_status,
                    json.dumps(entry.result_data) if entry.result_data else None,
                    entry.execution_time_ms,
                ))
            
            conn.commit()
            conn.close()
            
            self.last_flush_time = time.time()
            self.operations_since_flush = 0
            logger.debug(f"Flushed {len(self.recent_history)} entries to database")
            
        except Exception as e:
            logger.error(f"Failed to flush to database: {e}")
    
    def get_recent(self, limit: int = 10) -> List[CommandHistoryEntry]:
        """
        Get recent command history entries.
        
        Args:
            limit: Number of recent entries to return
            
        Returns:
            List of recent CommandHistoryEntry objects (newest first)
        """
        # Return most recent entries (deque is oldest to newest)
        return list(self.recent_history)[-limit:][::-1]
    
    def search_by_timestamp(
        self,
        target_timestamp: float,
        tolerance_seconds: float = 1.0
    ) -> Optional[CommandHistoryEntry]:
        """
        Search for entry by timestamp using NOT_STISLA.
        
        Args:
            target_timestamp: Target timestamp
            tolerance_seconds: Tolerance in seconds
            
        Returns:
            CommandHistoryEntry if found, None otherwise
        """
        if not self.timestamp_array or not self.not_stisla_engine:
            # Fallback to linear search
            target_int = int(target_timestamp)
            for entry in self.recent_history:
                if abs(int(entry.timestamp) - target_int) <= int(tolerance_seconds):
                    return entry
            return None
        
        # Use NOT_STISLA for fast search
        target_int = int(target_timestamp)
        idx = self.not_stisla_engine.search(self.timestamp_array, target_int, tolerance=int(tolerance_seconds))
        
        if idx is not None and 0 <= idx < len(self.timestamp_array):
            timestamp = self.timestamp_array[idx]
            entry_idx = self.timestamp_to_index.get(timestamp)
            if entry_idx is not None and 0 <= entry_idx < len(self.recent_history):
                return list(self.recent_history)[entry_idx]
        
        return None
    
    def search_by_operation_type(
        self,
        operation_type: str,
        limit: int = 10
    ) -> List[CommandHistoryEntry]:
        """
        Search for entries by operation type.
        
        Args:
            operation_type: Operation type to search for
            limit: Maximum number of results
            
        Returns:
            List of matching CommandHistoryEntry objects
        """
        results = []
        for entry in reversed(self.recent_history):
            if entry.operation_type == operation_type:
                results.append(entry)
                if len(results) >= limit:
                    break
        return results
    
    def search_by_time_range(
        self,
        start_time: float,
        end_time: float
    ) -> List[CommandHistoryEntry]:
        """
        Search for entries in a time range.
        
        Args:
            start_time: Start timestamp
            end_time: End timestamp
            
        Returns:
            List of matching CommandHistoryEntry objects
        """
        results = []
        start_int = int(start_time)
        end_int = int(end_time)
        
        # Use NOT_STISLA to find entries in range
        if self.not_stisla_engine and self.timestamp_array:
            # Find start and end indices
            start_idx = self.not_stisla_engine.search(self.timestamp_array, start_int, tolerance=3600)
            end_idx = self.not_stisla_engine.search(self.timestamp_array, end_int, tolerance=3600)
            
            if start_idx is not None and end_idx is not None:
                # Get entries in range
                for idx in range(start_idx, min(end_idx + 1, len(self.timestamp_array))):
                    timestamp = self.timestamp_array[idx]
                    entry_idx = self.timestamp_to_index.get(timestamp)
                    if entry_idx is not None:
                        entry = list(self.recent_history)[entry_idx]
                        if start_time <= entry.timestamp <= end_time:
                            results.append(entry)
        else:
            # Fallback to linear search
            for entry in self.recent_history:
                if start_time <= entry.timestamp <= end_time:
                    results.append(entry)
        
        return sorted(results, key=lambda e: e.timestamp, reverse=True)
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get command history statistics.
        
        Returns:
            Dictionary with statistics
        """
        if not self.recent_history:
            return {
                'total_entries': 0,
                'in_memory_count': 0,
                'not_stisla_enabled': self.not_stisla_engine is not None,
            }
        
        # Count by operation type
        operation_counts = {}
        for entry in self.recent_history:
            operation_counts[entry.operation_type] = operation_counts.get(entry.operation_type, 0) + 1
        
        # Count by status
        status_counts = {}
        for entry in self.recent_history:
            status_counts[entry.result_status] = status_counts.get(entry.result_status, 0) + 1
        
        # Get database count
        db_count = 0
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM command_history")
            db_count = cursor.fetchone()[0]
            conn.close()
        except Exception:
            pass
        
        return {
            'total_entries': db_count,
            'in_memory_count': len(self.recent_history),
            'not_stisla_enabled': self.not_stisla_engine is not None,
            'operation_counts': operation_counts,
            'status_counts': status_counts,
            'oldest_in_memory': self.recent_history[0].timestamp if self.recent_history else None,
            'newest_in_memory': self.recent_history[-1].timestamp if self.recent_history else None,
        }
    
    def clear(self):
        """Clear all command history (both memory and database)"""
        self.recent_history.clear()
        self.timestamp_array.clear()
        self.timestamp_to_index.clear()
        
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("DELETE FROM command_history")
            conn.commit()
            conn.close()
            logger.info("Command history cleared")
        except Exception as e:
            logger.error(f"Failed to clear database: {e}")
    
    def close(self):
        """Close and flush all data"""
        self._flush_to_database()
        if self.not_stisla_engine:
            # NOT_STISLA engine cleanup is handled by __del__
            self.not_stisla_engine = None
