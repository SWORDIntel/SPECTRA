"""Typed SPECTRA operation registry."""

from .builtin import create_builtin_registry
from .models import OperationEnvelope, OperationError, OperationEvent, OperationResult
from .registry import OperationDefinition, OperationRegistry, OperationUnavailable

__all__ = [
    "OperationDefinition",
    "OperationEnvelope",
    "OperationError",
    "OperationEvent",
    "OperationRegistry",
    "OperationResult",
    "OperationUnavailable",
    "create_builtin_registry",
]
