"""
Workflow Automation System for SPECTRA
======================================

Macro recorder, scheduled tasks, and workflow optimization using ML.
"""

import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    """A single workflow step"""
    step_type: str  # "archive", "discover", "forward", "wait", etc.
    parameters: Dict[str, Any]
    delay_after: float = 0.0  # Delay in seconds after this step


@dataclass
class Workflow:
    """A complete workflow"""
    name: str
    description: str
    steps: List[WorkflowStep]
    created_at: float = 0.0
    last_run: Optional[float] = None
    run_count: int = 0
    
    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "steps": [{"step_type": s.step_type, "parameters": s.parameters, "delay_after": s.delay_after} for s in self.steps],
            "created_at": self.created_at,
            "last_run": self.last_run,
            "run_count": self.run_count,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Workflow':
        steps = [WorkflowStep(**s) for s in data.get("steps", [])]
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            steps=steps,
            created_at=data.get("created_at", time.time()),
            last_run=data.get("last_run"),
            run_count=data.get("run_count", 0),
        )


class WorkflowAutomation:
    """Workflow automation manager"""
    
    def __init__(self, workflows_dir: Optional[Path] = None):
        if workflows_dir is None:
            workflows_dir = Path("data/workflows")
        self.workflows_dir = workflows_dir
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        self.workflows: Dict[str, Workflow] = {}
        self.recording: bool = False
        self.recorded_steps: List[WorkflowStep] = []
        self._load_workflows()
    
    def _load_workflows(self):
        """Load workflows from directory"""
        for workflow_file in self.workflows_dir.glob("*.json"):
            try:
                with open(workflow_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    workflow = Workflow.from_dict(data)
                    self.workflows[workflow.name] = workflow
            except Exception as e:
                logger.warning(f"Failed to load workflow {workflow_file}: {e}")
    
    def save_workflow(self, workflow: Workflow):
        """Save a workflow"""
        workflow_file = self.workflows_dir / f"{workflow.name}.json"
        try:
            with open(workflow_file, 'w', encoding='utf-8') as f:
                json.dump(workflow.to_dict(), f, indent=2, ensure_ascii=False)
            self.workflows[workflow.name] = workflow
            logger.debug(f"Saved workflow: {workflow.name}")
        except Exception as e:
            logger.error(f"Failed to save workflow {workflow.name}: {e}")
    
    def start_recording(self):
        """Start macro recording"""
        self.recording = True
        self.recorded_steps = []
    
    def stop_recording(self) -> Optional[Workflow]:
        """Stop recording and return workflow"""
        self.recording = False
        if self.recorded_steps:
            workflow = Workflow(
                name=f"Recorded_{int(time.time())}",
                description="Recorded workflow",
                steps=self.recorded_steps.copy()
            )
            return workflow
        return None
    
    def record_step(self, step_type: str, parameters: Dict[str, Any], delay_after: float = 0.0):
        """Record a workflow step"""
        if self.recording:
            step = WorkflowStep(
                step_type=step_type,
                parameters=parameters,
                delay_after=delay_after
            )
            self.recorded_steps.append(step)
    
    def execute_workflow(self, workflow_name: str, executor: Callable) -> bool:
        """Execute a workflow"""
        workflow = self.workflows.get(workflow_name)
        if not workflow:
            return False
        
        try:
            for step in workflow.steps:
                executor(step.step_type, step.parameters)
                if step.delay_after > 0:
                    time.sleep(step.delay_after)
            
            workflow.last_run = time.time()
            workflow.run_count += 1
            self.save_workflow(workflow)
            return True
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            return False
    
    def list_workflows(self) -> List[str]:
        """List all workflow names"""
        return list(self.workflows.keys())
    
    def get_workflow(self, name: str) -> Optional[Workflow]:
        """Get a workflow by name"""
        return self.workflows.get(name)
    
    def delete_workflow(self, name: str) -> bool:
        """Delete a workflow"""
        workflow_file = self.workflows_dir / f"{name}.json"
        if workflow_file.exists():
            workflow_file.unlink()
            self.workflows.pop(name, None)
            return True
        return False
