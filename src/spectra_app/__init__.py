"""
High-level application package for SPECTRA orchestration and UI components.

This package consolidates the previously top-level modules into a structured
namespace so downstream code can rely on explicit imports while keeping the
repository root clean.
"""

from . import agent_communication
from . import agent_optimization_engine
from . import coordination_interface
from . import implementation_tools
from . import orchestration_dashboard
from . import orchestration_integration
from . import orchestration_workflows
from . import phase_management_dashboard
from . import workflow_automation
from . import spectra_coordination_gui
from . import spectra_gui_launcher
from .spectra_orchestrator import (
    SpectraOrchestrator,
    AgentStatus,
    WorkflowStatus,
    Priority,
    AgentMetadata,
    Task,
    Workflow,
)

__all__ = [
    "agent_communication",
    "agent_optimization_engine",
    "coordination_interface",
    "implementation_tools",
    "orchestration_dashboard",
    "orchestration_integration",
    "orchestration_workflows",
    "phase_management_dashboard",
    "workflow_automation",
    "spectra_coordination_gui",
    "spectra_gui_launcher",
    "SpectraOrchestrator",
    "AgentStatus",
    "WorkflowStatus",
    "Priority",
    "AgentMetadata",
    "Task",
    "Workflow",
]
