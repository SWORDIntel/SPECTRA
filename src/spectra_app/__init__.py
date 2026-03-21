"""High-level application package for SPECTRA orchestration/UI components.

Avoid importing the full backend graph at package import time. The GUI layer is
used by standalone tooling and tests that should not require every optional
dependency to be present merely to import the package.
"""

from __future__ import annotations

__all__ = [
    "SpectraOrchestrator",
    "AgentStatus",
    "WorkflowStatus",
    "Priority",
    "AgentMetadata",
    "Task",
    "Workflow",
]


def __getattr__(name: str):
    if name in __all__:
        from .spectra_orchestrator import (
            AgentMetadata,
            AgentStatus,
            Priority,
            SpectraOrchestrator,
            Task,
            Workflow,
            WorkflowStatus,
        )

        exports = {
            "SpectraOrchestrator": SpectraOrchestrator,
            "AgentStatus": AgentStatus,
            "WorkflowStatus": WorkflowStatus,
            "Priority": Priority,
            "AgentMetadata": AgentMetadata,
            "Task": Task,
            "Workflow": Workflow,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
