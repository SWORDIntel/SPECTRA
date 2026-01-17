"""Undo/Redo system for SPECTRA operations"""

import logging
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class OperationState:
    """State snapshot for undo/redo"""
    operation_type: str
    state_data: Dict[str, Any]
    restore_function: Optional[Callable] = None


class UndoRedoManager:
    """Manages undo/redo stack for operations"""
    
    def __init__(self, max_history: int = 50):
        self.undo_stack: deque = deque(maxlen=max_history)
        self.redo_stack: deque = deque(maxlen=max_history)
    
    def push_operation(self, operation: OperationState):
        """Push operation to undo stack, clear redo"""
        self.undo_stack.append(operation)
        self.redo_stack.clear()
    
    def undo(self) -> Optional[OperationState]:
        """Pop from undo stack, push to redo"""
        if not self.undo_stack:
            return None
        state = self.undo_stack.pop()
        self.redo_stack.append(state)
        return state
    
    def redo(self) -> Optional[OperationState]:
        """Pop from redo stack, push to undo"""
        if not self.redo_stack:
            return None
        state = self.redo_stack.pop()
        self.undo_stack.append(state)
        return state
    
    def can_undo(self) -> bool:
        """Check if undo is available"""
        return len(self.undo_stack) > 0
    
    def can_redo(self) -> bool:
        """Check if redo is available"""
        return len(self.redo_stack) > 0
