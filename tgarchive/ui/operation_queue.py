"""
Operation Queue and Batch Operations System
===========================================

Manages background operation queue with priority system and batch processing.
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Operation priority levels"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class QueuedOperation:
    """A queued operation"""
    operation_id: str
    operation_type: str
    function: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    priority: Priority = Priority.NORMAL
    callback: Optional[Callable] = None
    error_callback: Optional[Callable] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    status: str = "pending"  # pending, running, completed, failed, cancelled
    result: Any = None
    error: Optional[Exception] = None


class OperationQueue:
    """Manages operation queue with priority and batch processing"""
    
    def __init__(self, max_concurrent: int = 3):
        self.queue: deque = deque()
        self.running: Dict[str, QueuedOperation] = {}
        self.completed: deque = deque(maxlen=100)
        self.max_concurrent = max_concurrent
        self.lock = threading.Lock()
        self.worker_thread: Optional[threading.Thread] = None
        self._stop_workers = False
    
    def add_operation(
        self,
        operation_id: str,
        operation_type: str,
        function: Callable,
        args: tuple = (),
        kwargs: dict = None,
        priority: Priority = Priority.NORMAL,
        callback: Optional[Callable] = None,
        error_callback: Optional[Callable] = None
    ) -> QueuedOperation:
        """Add operation to queue"""
        if kwargs is None:
            kwargs = {}
        
        op = QueuedOperation(
            operation_id=operation_id,
            operation_type=operation_type,
            function=function,
            args=args,
            kwargs=kwargs,
            priority=priority,
            callback=callback,
            error_callback=error_callback,
        )
        
        with self.lock:
            # Insert by priority (higher first)
            inserted = False
            for i, existing_op in enumerate(self.queue):
                if op.priority > existing_op.priority:
                    self.queue.insert(i, op)
                    inserted = True
                    break
            if not inserted:
                self.queue.append(op)
        
        self._start_worker()
        return op
    
    def _start_worker(self):
        """Start worker thread if not running"""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self._stop_workers = False
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
    
    def _worker_loop(self):
        """Worker thread that processes operations"""
        while not self._stop_workers:
            with self.lock:
                # Check if we can start more operations
                if len(self.running) >= self.max_concurrent:
                    time.sleep(0.1)
                    continue
                
                # Get next operation
                if not self.queue:
                    time.sleep(0.1)
                    continue
                
                op = self.queue.popleft()
                op.status = "running"
                op.started_at = time.time()
                self.running[op.operation_id] = op
            
            # Execute operation in thread
            try:
                result = op.function(*op.args, **op.kwargs)
                op.result = result
                op.status = "completed"
                op.completed_at = time.time()
                
                if op.callback:
                    try:
                        op.callback(result)
                    except Exception as e:
                        logger.error(f"Callback error for {op.operation_id}: {e}")
            except Exception as e:
                op.status = "failed"
                op.error = e
                op.completed_at = time.time()
                logger.error(f"Operation {op.operation_id} failed: {e}")
                
                if op.error_callback:
                    try:
                        op.error_callback(e)
                    except Exception as e2:
                        logger.error(f"Error callback error: {e2}")
            
            with self.lock:
                self.running.pop(op.operation_id, None)
                self.completed.append(op)
    
    def get_status(self) -> Dict[str, Any]:
        """Get queue status"""
        with self.lock:
            return {
                "queued": len(self.queue),
                "running": len(self.running),
                "completed": len(self.completed),
                "running_ops": [op.operation_id for op in self.running.values()],
            }
    
    def cancel_operation(self, operation_id: str) -> bool:
        """Cancel a pending operation"""
        with self.lock:
            for i, op in enumerate(self.queue):
                if op.operation_id == operation_id:
                    op.status = "cancelled"
                    self.queue.remove(op)
                    return True
            return False
    
    def get_operation(self, operation_id: str) -> Optional[QueuedOperation]:
        """Get operation by ID"""
        with self.lock:
            # Check queue
            for op in self.queue:
                if op.operation_id == operation_id:
                    return op
            # Check running
            if operation_id in self.running:
                return self.running[operation_id]
            # Check completed
            for op in self.completed:
                if op.operation_id == operation_id:
                    return op
        return None
