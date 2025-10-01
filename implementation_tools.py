#!/usr/bin/env python3
"""
SPECTRA Implementation Management Tools
======================================

Comprehensive implementation management tools for project planning, resource
allocation, risk management, quality gates, and knowledge management for
the 4-phase SPECTRA advanced data management implementation.

Features:
- Project planning with work breakdown structure
- Resource allocation and capacity planning
- Risk assessment and mitigation tracking
- Quality gates and approval workflows
- Knowledge management and documentation
- Stakeholder communication tools
- Progress reporting and analytics
- Implementation methodology framework

Author: PYTHON-INTERNAL Agent - Elite Python execution environment specialist
Date: September 18, 2025
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
import uuid
import hashlib

# Data processing and visualization
try:
    import pandas as pd
    import numpy as np
    from plotly import graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.express as px
    DATA_TOOLS_AVAILABLE = True
except ImportError:
    DATA_TOOLS_AVAILABLE = False

# SPECTRA imports
from spectra_orchestrator import SpectraOrchestrator, Priority
from phase_management_dashboard import PhaseManagementDashboard, PhaseStatus, MilestoneStatus
from agent_optimization_engine import AgentOptimizationEngine, OptimizationObjective


class TaskStatus(Enum):
    """Task execution status"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"


class QualityGateStatus(Enum):
    """Quality gate approval status"""
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONDITIONAL_APPROVAL = "conditional_approval"


class RiskStatus(Enum):
    """Risk mitigation status"""
    IDENTIFIED = "identified"
    ANALYZING = "analyzing"
    MITIGATING = "mitigating"
    RESOLVED = "resolved"
    ACCEPTED = "accepted"


class DocumentType(Enum):
    """Documentation types"""
    REQUIREMENTS = "requirements"
    ARCHITECTURE = "architecture"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"
    DEPLOYMENT = "deployment"
    USER_GUIDE = "user_guide"
    ADMIN_GUIDE = "admin_guide"
    API_DOCUMENTATION = "api_documentation"
    RUNBOOK = "runbook"


@dataclass
class WorkBreakdownItem:
    """Work breakdown structure item"""
    id: str
    name: str
    description: str
    parent_id: Optional[str]
    level: int
    estimated_hours: float
    actual_hours: float
    assigned_agents: List[str]
    dependencies: List[str]
    status: TaskStatus
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    completion_percentage: float
    deliverables: List[str]
    acceptance_criteria: List[str]
    priority: Priority


@dataclass
class ResourceAllocation:
    """Resource allocation planning"""
    resource_id: str
    resource_type: str  # agent, compute, storage, etc.
    allocated_to: str
    allocation_percentage: float
    start_date: datetime
    end_date: datetime
    cost_per_hour: float
    availability_constraints: List[str]
    skills_required: List[str]
    utilization_target: float
    actual_utilization: float


@dataclass
class RiskItem:
    """Risk assessment and tracking"""
    id: str
    title: str
    description: str
    category: str
    probability: float  # 0.0 to 1.0
    impact: float      # 0.0 to 1.0
    risk_score: float  # probability * impact
    status: RiskStatus
    owner: str
    mitigation_plan: str
    mitigation_actions: List[str]
    target_resolution_date: datetime
    actual_resolution_date: Optional[datetime]
    review_date: datetime
    escalation_required: bool


@dataclass
class QualityGate:
    """Quality gate definition and tracking"""
    id: str
    name: str
    description: str
    phase_id: str
    milestone_id: Optional[str]
    criteria: List[str]
    validation_methods: List[str]
    approvers: List[str]
    status: QualityGateStatus
    submission_date: Optional[datetime]
    review_start_date: Optional[datetime]
    approval_date: Optional[datetime]
    comments: List[str]
    artifacts: List[str]
    exit_criteria_met: bool


@dataclass
class KnowledgeDocument:
    """Knowledge management document"""
    id: str
    title: str
    document_type: DocumentType
    content: str
    author: str
    created_date: datetime
    last_modified: datetime
    version: str
    tags: List[str]
    related_documents: List[str]
    approval_status: str
    stakeholder_access: List[str]
    retention_policy: str


@dataclass
class StakeholderCommunication:
    """Stakeholder communication tracking"""
    id: str
    stakeholder_group: str
    communication_type: str  # status_update, milestone_report, risk_alert, etc.
    subject: str
    content: str
    sent_date: datetime
    recipients: List[str]
    acknowledgments: List[str]
    follow_up_required: bool
    follow_up_date: Optional[datetime]


@dataclass
class ProgressReport:
    """Comprehensive progress report"""
    id: str
    report_date: datetime
    reporting_period_start: datetime
    reporting_period_end: datetime
    overall_progress: float
    phase_progress: Dict[str, float]
    milestones_achieved: List[str]
    risks_identified: List[str]
    issues_resolved: List[str]
    budget_utilization: float
    resource_utilization: Dict[str, float]
    quality_metrics: Dict[str, float]
    next_period_forecast: Dict[str, Any]


class ImplementationTools:
    """
    Comprehensive implementation management tools providing project planning,
    resource management, risk tracking, quality gates, and knowledge management.
    """

    def __init__(self,
                 orchestrator: SpectraOrchestrator,
                 phase_dashboard: PhaseManagementDashboard):
        """Initialize implementation tools"""
        self.orchestrator = orchestrator
        self.phase_dashboard = phase_dashboard
        self.optimization_engine = AgentOptimizationEngine(orchestrator.agents)

        # Work breakdown and planning
        self.work_breakdown = {}
        self.resource_allocations = {}
        self.resource_capacity = {}

        # Risk and quality management
        self.risks = {}
        self.quality_gates = {}
        self.quality_metrics = {}

        # Knowledge management
        self.knowledge_base = {}
        self.document_templates = {}
        self.stakeholder_communications = []

        # Progress tracking
        self.progress_reports = {}
        self.implementation_metrics = {}

        # Configuration
        self.methodology_framework = "agile_waterfall_hybrid"
        self.quality_standards = ["ISO_9001", "CMMI_Level_3"]
        self.risk_tolerance = 0.3  # 30% acceptable risk score

        # Logging
        self.logger = logging.getLogger(__name__)

        # Initialize framework
        self._initialize_implementation_framework()

    def _initialize_implementation_framework(self):
        """Initialize the implementation framework with templates and standards"""

        # Create work breakdown structure
        self._create_work_breakdown_structure()

        # Initialize quality gates
        self._initialize_quality_gates()

        # Setup risk framework
        self._initialize_risk_framework()

        # Create document templates
        self._create_document_templates()

        # Initialize resource capacity
        self._initialize_resource_capacity()

    def _create_work_breakdown_structure(self):
        """Create comprehensive work breakdown structure for all phases"""

        # Phase 1 WBS
        phase1_wbs = [
            WorkBreakdownItem(
                id="1.0",
                name="Foundation Enhancement",
                description="Complete database migration and compression integration",
                parent_id=None,
                level=1,
                estimated_hours=320,
                actual_hours=0,
                assigned_agents=["DATABASE", "OPTIMIZER", "INFRASTRUCTURE"],
                dependencies=[],
                status=TaskStatus.IN_PROGRESS,
                start_date=datetime.now(),
                end_date=datetime.now() + timedelta(weeks=4),
                completion_percentage=15.0,
                deliverables=["PostgreSQL cluster", "Compression system", "Deduplication engine"],
                acceptance_criteria=["99.9% uptime", "65% compression", "99.5% dedup accuracy"],
                priority=Priority.CRITICAL
            ),
            WorkBreakdownItem(
                id="1.1",
                name="Database Infrastructure",
                description="PostgreSQL cluster setup and configuration",
                parent_id="1.0",
                level=2,
                estimated_hours=80,
                actual_hours=12,
                assigned_agents=["INFRASTRUCTURE", "DATABASE"],
                dependencies=[],
                status=TaskStatus.IN_PROGRESS,
                start_date=datetime.now(),
                end_date=datetime.now() + timedelta(days=7),
                completion_percentage=25.0,
                deliverables=["3-node cluster", "Replication setup", "Monitoring"],
                acceptance_criteria=["Cluster operational", "Replication < 1s lag"],
                priority=Priority.CRITICAL
            ),
            WorkBreakdownItem(
                id="1.2",
                name="Schema Migration",
                description="Migrate from SQLite to PostgreSQL with validation",
                parent_id="1.0",
                level=2,
                estimated_hours=60,
                actual_hours=0,
                assigned_agents=["DATABASE", "ARCHITECT"],
                dependencies=["1.1"],
                status=TaskStatus.NOT_STARTED,
                start_date=datetime.now() + timedelta(days=7),
                end_date=datetime.now() + timedelta(days=10),
                completion_percentage=0.0,
                deliverables=["Migrated schema", "Data validation", "Performance baseline"],
                acceptance_criteria=["100% data migrated", "Schema validated", "Performance targets met"],
                priority=Priority.CRITICAL
            ),
            WorkBreakdownItem(
                id="1.3",
                name="Compression Integration",
                description="Integrate Kanzi-cpp compression system",
                parent_id="1.0",
                level=2,
                estimated_hours=100,
                actual_hours=0,
                assigned_agents=["OPTIMIZER", "HARDWARE-INTEL"],
                dependencies=["1.2"],
                status=TaskStatus.NOT_STARTED,
                start_date=datetime.now() + timedelta(days=10),
                end_date=datetime.now() + timedelta(days=17),
                completion_percentage=0.0,
                deliverables=["Compression module", "Performance benchmarks", "Integration tests"],
                acceptance_criteria=["65% compression ratio", "Performance targets", "Tests passed"],
                priority=Priority.HIGH
            ),
            WorkBreakdownItem(
                id="1.4",
                name="Deduplication System",
                description="Multi-layer deduplication with high accuracy",
                parent_id="1.0",
                level=2,
                estimated_hours=80,
                actual_hours=0,
                assigned_agents=["OPTIMIZER", "DATASCIENCE"],
                dependencies=["1.3"],
                status=TaskStatus.NOT_STARTED,
                start_date=datetime.now() + timedelta(days=17),
                end_date=datetime.now() + timedelta(days=24),
                completion_percentage=0.0,
                deliverables=["Deduplication engine", "Accuracy validation", "Performance metrics"],
                acceptance_criteria=["99.5% accuracy", "Performance acceptable", "Integration complete"],
                priority=Priority.HIGH
            )
        ]

        # Store WBS items
        for item in phase1_wbs:
            self.work_breakdown[item.id] = item

        # Add similar structures for other phases (simplified for brevity)
        self._add_phase2_wbs()
        self._add_phase3_wbs()
        self._add_phase4_wbs()

    def _add_phase2_wbs(self):
        """Add Phase 2 work breakdown structure"""
        phase2_items = [
            WorkBreakdownItem(
                id="2.0",
                name="Advanced Features Implementation",
                description="ML, analytics, and storage tiers",
                parent_id=None,
                level=1,
                estimated_hours=480,
                actual_hours=0,
                assigned_agents=["DATASCIENCE", "MLOPS", "WEB", "APIDESIGNER"],
                dependencies=["1.0"],
                status=TaskStatus.NOT_STARTED,
                start_date=datetime.now() + timedelta(weeks=4),
                end_date=datetime.now() + timedelta(weeks=8),
                completion_percentage=0.0,
                deliverables=["ML models", "Analytics dashboard", "Storage tiers"],
                acceptance_criteria=["85% ML accuracy", "<100ms analytics", "Storage operational"],
                priority=Priority.HIGH
            )
        ]

        for item in phase2_items:
            self.work_breakdown[item.id] = item

    def _add_phase3_wbs(self):
        """Add Phase 3 work breakdown structure"""
        phase3_items = [
            WorkBreakdownItem(
                id="3.0",
                name="Production Deployment",
                description="Kubernetes, monitoring, security",
                parent_id=None,
                level=1,
                estimated_hours=200,
                actual_hours=0,
                assigned_agents=["INFRASTRUCTURE", "DEPLOYER", "MONITOR", "SECURITY"],
                dependencies=["2.0"],
                status=TaskStatus.NOT_STARTED,
                start_date=datetime.now() + timedelta(weeks=8),
                end_date=datetime.now() + timedelta(weeks=12),
                completion_percentage=0.0,
                deliverables=["K8s cluster", "Monitoring stack", "Security hardening"],
                acceptance_criteria=["10K+ users", "99.9% uptime", "Security compliant"],
                priority=Priority.CRITICAL
            )
        ]

        for item in phase3_items:
            self.work_breakdown[item.id] = item

    def _add_phase4_wbs(self):
        """Add Phase 4 work breakdown structure"""
        phase4_items = [
            WorkBreakdownItem(
                id="4.0",
                name="Optimization & Enhancement",
                description="Advanced ML and performance optimization",
                parent_id=None,
                level=1,
                estimated_hours=240,
                actual_hours=0,
                assigned_agents=["DATASCIENCE", "OPTIMIZER", "SECURITY", "ARCHITECT"],
                dependencies=["3.0"],
                status=TaskStatus.NOT_STARTED,
                start_date=datetime.now() + timedelta(weeks=12),
                end_date=datetime.now() + timedelta(weeks=16),
                completion_percentage=0.0,
                deliverables=["Advanced ML", "Global optimization", "Future roadmap"],
                acceptance_criteria=["50% improvement", "ML deployed", "Roadmap approved"],
                priority=Priority.MEDIUM
            )
        ]

        for item in phase4_items:
            self.work_breakdown[item.id] = item

    def _initialize_quality_gates(self):
        """Initialize quality gates for all phases"""

        quality_gates = [
            QualityGate(
                id="qg_1_1",
                name="Database Migration Gate",
                description="Validate successful database migration and performance",
                phase_id="phase1",
                milestone_id="m1_2",
                criteria=[
                    "100% data migrated without loss",
                    "Schema validation completed",
                    "Performance baseline established",
                    "Rollback procedure tested"
                ],
                validation_methods=[
                    "Automated data integrity checks",
                    "Performance benchmarking",
                    "Schema validation scripts",
                    "Rollback testing"
                ],
                approvers=["DIRECTOR", "DATABASE", "ARCHITECT"],
                status=QualityGateStatus.PENDING,
                submission_date=None,
                review_start_date=None,
                approval_date=None,
                comments=[],
                artifacts=["migration_report.pdf", "performance_baseline.json"],
                exit_criteria_met=False
            ),
            QualityGate(
                id="qg_1_2",
                name="Compression System Gate",
                description="Validate compression integration and performance",
                phase_id="phase1",
                milestone_id="m1_3",
                criteria=[
                    "65% compression ratio achieved",
                    "Performance within acceptable limits",
                    "Integration tests passed",
                    "System stability validated"
                ],
                validation_methods=[
                    "Compression ratio testing",
                    "Performance benchmarking",
                    "Integration test suite",
                    "Stability testing"
                ],
                approvers=["OPTIMIZER", "HARDWARE-INTEL", "TESTBED"],
                status=QualityGateStatus.PENDING,
                submission_date=None,
                review_start_date=None,
                approval_date=None,
                comments=[],
                artifacts=["compression_report.pdf", "benchmark_results.json"],
                exit_criteria_met=False
            ),
            QualityGate(
                id="qg_2_1",
                name="ML Models Validation Gate",
                description="Validate ML model accuracy and deployment readiness",
                phase_id="phase2",
                milestone_id="m2_1",
                criteria=[
                    "85% classification accuracy achieved",
                    "Model performance validated",
                    "Deployment pipeline tested",
                    "Monitoring configured"
                ],
                validation_methods=[
                    "Model accuracy testing",
                    "Cross-validation",
                    "Deployment testing",
                    "Monitoring validation"
                ],
                approvers=["DATASCIENCE", "MLOPS", "DIRECTOR"],
                status=QualityGateStatus.PENDING,
                submission_date=None,
                review_start_date=None,
                approval_date=None,
                comments=[],
                artifacts=["ml_validation_report.pdf", "model_metrics.json"],
                exit_criteria_met=False
            )
        ]

        for gate in quality_gates:
            self.quality_gates[gate.id] = gate

    def _initialize_risk_framework(self):
        """Initialize risk management framework"""

        initial_risks = [
            RiskItem(
                id="risk_001",
                title="Database Migration Data Loss",
                description="Risk of data loss during migration from SQLite to PostgreSQL",
                category="technical",
                probability=0.2,
                impact=0.9,
                risk_score=0.18,
                status=RiskStatus.MITIGATING,
                owner="DATABASE",
                mitigation_plan="Comprehensive backup and validation strategy",
                mitigation_actions=[
                    "Create full database backup",
                    "Implement incremental migration",
                    "Automated validation scripts",
                    "Rollback procedures"
                ],
                target_resolution_date=datetime.now() + timedelta(days=14),
                actual_resolution_date=None,
                review_date=datetime.now() + timedelta(days=7),
                escalation_required=False
            ),
            RiskItem(
                id="risk_002",
                title="Compression Performance Impact",
                description="Compression may negatively impact system performance",
                category="performance",
                probability=0.4,
                impact=0.6,
                risk_score=0.24,
                status=RiskStatus.ANALYZING,
                owner="OPTIMIZER",
                mitigation_plan="Performance testing and optimization strategy",
                mitigation_actions=[
                    "Baseline performance measurement",
                    "Compression algorithm optimization",
                    "Hardware acceleration evaluation",
                    "Performance monitoring"
                ],
                target_resolution_date=datetime.now() + timedelta(days=21),
                actual_resolution_date=None,
                review_date=datetime.now() + timedelta(days=10),
                escalation_required=False
            ),
            RiskItem(
                id="risk_003",
                title="ML Model Accuracy Below Target",
                description="ML models may not achieve required 85% accuracy",
                category="technical",
                probability=0.3,
                impact=0.7,
                risk_score=0.21,
                status=RiskStatus.IDENTIFIED,
                owner="DATASCIENCE",
                mitigation_plan="Enhanced training data and model optimization",
                mitigation_actions=[
                    "Expand training dataset",
                    "Feature engineering optimization",
                    "Model architecture evaluation",
                    "Ensemble methods consideration"
                ],
                target_resolution_date=datetime.now() + timedelta(days=35),
                actual_resolution_date=None,
                review_date=datetime.now() + timedelta(days=14),
                escalation_required=False
            ),
            RiskItem(
                id="risk_004",
                title="Resource Availability Constraints",
                description="Key agent resources may become unavailable",
                category="resource",
                probability=0.25,
                impact=0.8,
                risk_score=0.20,
                status=RiskStatus.MITIGATING,
                owner="DIRECTOR",
                mitigation_plan="Cross-training and backup resource allocation",
                mitigation_actions=[
                    "Identify backup agents",
                    "Cross-training programs",
                    "Resource scheduling optimization",
                    "Escalation procedures"
                ],
                target_resolution_date=datetime.now() + timedelta(days=30),
                actual_resolution_date=None,
                review_date=datetime.now() + timedelta(days=7),
                escalation_required=False
            )
        ]

        for risk in initial_risks:
            self.risks[risk.id] = risk

    def _create_document_templates(self):
        """Create document templates for different types"""

        templates = {
            DocumentType.REQUIREMENTS: {
                "sections": [
                    "Executive Summary",
                    "Functional Requirements",
                    "Non-Functional Requirements",
                    "Constraints and Assumptions",
                    "Acceptance Criteria"
                ],
                "format": "markdown",
                "approval_required": True
            },
            DocumentType.ARCHITECTURE: {
                "sections": [
                    "System Overview",
                    "Architecture Principles",
                    "Component Design",
                    "Data Flow",
                    "Security Architecture",
                    "Performance Considerations"
                ],
                "format": "markdown",
                "approval_required": True
            },
            DocumentType.IMPLEMENTATION: {
                "sections": [
                    "Implementation Overview",
                    "Setup Instructions",
                    "Configuration Details",
                    "Testing Procedures",
                    "Troubleshooting Guide"
                ],
                "format": "markdown",
                "approval_required": False
            },
            DocumentType.RUNBOOK: {
                "sections": [
                    "Service Overview",
                    "Operational Procedures",
                    "Monitoring and Alerting",
                    "Incident Response",
                    "Recovery Procedures"
                ],
                "format": "markdown",
                "approval_required": True
            }
        }

        self.document_templates = templates

    def _initialize_resource_capacity(self):
        """Initialize resource capacity planning"""

        # Agent capacity (hours per week)
        agent_capacity = {
            "DIRECTOR": 20,  # Strategic focus, limited implementation time
            "PROJECTORCHESTRATOR": 30,
            "ARCHITECT": 35,
            "DATABASE": 40,
            "OPTIMIZER": 40,
            "INFRASTRUCTURE": 40,
            "DATASCIENCE": 40,
            "MLOPS": 35,
            "TESTBED": 30,
            "DEBUGGER": 30,
            "SECURITY": 35,
            "WEB": 35,
            "APIDESIGNER": 35,
            "HARDWARE-INTEL": 25,  # Specialized resource
            "DEPLOYER": 35,
            "MONITOR": 30
        }

        for agent_name, hours_per_week in agent_capacity.items():
            self.resource_capacity[agent_name] = {
                "weekly_capacity": hours_per_week,
                "hourly_rate": self._estimate_agent_hourly_rate(agent_name),
                "skills": self.orchestrator.agents.get(agent_name, {}).capabilities if agent_name in self.orchestrator.agents else [],
                "availability_constraints": [],
                "current_allocation": 0.0
            }

    def _estimate_agent_hourly_rate(self, agent_name: str) -> float:
        """Estimate hourly rate for agent"""
        base_rates = {
            "DIRECTOR": 150,
            "ARCHITECT": 120,
            "DATABASE": 100,
            "DATASCIENCE": 110,
            "SECURITY": 115,
            "INFRASTRUCTURE": 95,
            "OPTIMIZER": 105
        }
        return base_rates.get(agent_name, 80)

    def create_resource_allocation_plan(self) -> Dict[str, Any]:
        """Create comprehensive resource allocation plan"""

        allocation_plan = {
            "planning_period": {
                "start_date": datetime.now().isoformat(),
                "end_date": (datetime.now() + timedelta(weeks=16)).isoformat(),
                "total_weeks": 16
            },
            "resource_allocations": [],
            "capacity_analysis": {},
            "cost_projections": {},
            "utilization_targets": {}
        }

        # Analyze work breakdown structure for resource needs
        for wbs_id, wbs_item in self.work_breakdown.items():
            if wbs_item.assigned_agents and wbs_item.estimated_hours > 0:
                hours_per_agent = wbs_item.estimated_hours / len(wbs_item.assigned_agents)

                for agent_name in wbs_item.assigned_agents:
                    if agent_name in self.resource_capacity:
                        allocation = ResourceAllocation(
                            resource_id=f"alloc_{wbs_id}_{agent_name}",
                            resource_type="agent",
                            allocated_to=wbs_id,
                            allocation_percentage=hours_per_agent / self.resource_capacity[agent_name]["weekly_capacity"],
                            start_date=wbs_item.start_date or datetime.now(),
                            end_date=wbs_item.end_date or datetime.now() + timedelta(weeks=2),
                            cost_per_hour=self.resource_capacity[agent_name]["hourly_rate"],
                            availability_constraints=[],
                            skills_required=wbs_item.deliverables,
                            utilization_target=0.8,
                            actual_utilization=0.0
                        )

                        self.resource_allocations[allocation.resource_id] = allocation
                        allocation_plan["resource_allocations"].append(asdict(allocation))

        # Capacity analysis
        for agent_name, capacity in self.resource_capacity.items():
            agent_allocations = [a for a in self.resource_allocations.values()
                               if a.resource_id.endswith(agent_name)]

            total_allocation = sum(a.allocation_percentage for a in agent_allocations)
            capacity_utilization = min(1.0, total_allocation)

            allocation_plan["capacity_analysis"][agent_name] = {
                "weekly_capacity": capacity["weekly_capacity"],
                "total_allocation_percentage": total_allocation,
                "capacity_utilization": capacity_utilization,
                "overallocation": max(0.0, total_allocation - 1.0),
                "available_capacity": max(0.0, 1.0 - total_allocation)
            }

        # Cost projections
        total_cost = 0
        for allocation in self.resource_allocations.values():
            duration_weeks = (allocation.end_date - allocation.start_date).days / 7
            weekly_hours = self.resource_capacity.get(allocation.resource_id.split('_')[-1], {}).get("weekly_capacity", 40)
            total_hours = duration_weeks * weekly_hours * allocation.allocation_percentage
            cost = total_hours * allocation.cost_per_hour
            total_cost += cost

        allocation_plan["cost_projections"] = {
            "total_project_cost": total_cost,
            "cost_by_phase": self._calculate_cost_by_phase(),
            "cost_by_agent": self._calculate_cost_by_agent()
        }

        return allocation_plan

    def _calculate_cost_by_phase(self) -> Dict[str, float]:
        """Calculate cost breakdown by phase"""
        cost_by_phase = {"phase1": 0, "phase2": 0, "phase3": 0, "phase4": 0}

        for wbs_id, wbs_item in self.work_breakdown.items():
            phase = f"phase{wbs_id.split('.')[0]}"
            if phase in cost_by_phase:
                for agent_name in wbs_item.assigned_agents:
                    if agent_name in self.resource_capacity:
                        hours_per_agent = wbs_item.estimated_hours / len(wbs_item.assigned_agents)
                        rate = self.resource_capacity[agent_name]["hourly_rate"]
                        cost_by_phase[phase] += hours_per_agent * rate

        return cost_by_phase

    def _calculate_cost_by_agent(self) -> Dict[str, float]:
        """Calculate cost breakdown by agent"""
        cost_by_agent = {}

        for allocation in self.resource_allocations.values():
            agent_name = allocation.resource_id.split('_')[-1]
            if agent_name in self.resource_capacity:
                duration_weeks = (allocation.end_date - allocation.start_date).days / 7
                weekly_hours = self.resource_capacity[agent_name]["weekly_capacity"]
                total_hours = duration_weeks * weekly_hours * allocation.allocation_percentage
                cost = total_hours * allocation.cost_per_hour

                if agent_name not in cost_by_agent:
                    cost_by_agent[agent_name] = 0
                cost_by_agent[agent_name] += cost

        return cost_by_agent

    def update_task_progress(self, task_id: str, completion_percentage: float, actual_hours: float):
        """Update task progress and recalculate metrics"""
        if task_id in self.work_breakdown:
            wbs_item = self.work_breakdown[task_id]
            wbs_item.completion_percentage = max(0.0, min(100.0, completion_percentage))
            wbs_item.actual_hours = actual_hours

            # Update status based on progress
            if completion_percentage >= 100.0:
                wbs_item.status = TaskStatus.COMPLETED
                wbs_item.end_date = datetime.now()
            elif completion_percentage > 0:
                wbs_item.status = TaskStatus.IN_PROGRESS
            else:
                wbs_item.status = TaskStatus.NOT_STARTED

            # Update parent task progress
            self._update_parent_progress(wbs_item.parent_id)

    def _update_parent_progress(self, parent_id: Optional[str]):
        """Update parent task progress based on children"""
        if not parent_id or parent_id not in self.work_breakdown:
            return

        parent_item = self.work_breakdown[parent_id]
        child_items = [item for item in self.work_breakdown.values()
                      if item.parent_id == parent_id]

        if child_items:
            total_progress = sum(child.completion_percentage for child in child_items)
            parent_item.completion_percentage = total_progress / len(child_items)

            # Update parent's parent recursively
            self._update_parent_progress(parent_item.parent_id)

    def submit_quality_gate(self, gate_id: str, artifacts: List[str], submitter: str) -> bool:
        """Submit quality gate for review"""
        if gate_id not in self.quality_gates:
            return False

        gate = self.quality_gates[gate_id]
        gate.status = QualityGateStatus.UNDER_REVIEW
        gate.submission_date = datetime.now()
        gate.review_start_date = datetime.now()
        gate.artifacts.extend(artifacts)

        # Log submission
        self.logger.info(f"Quality gate {gate_id} submitted by {submitter}")

        # Notify approvers (would send actual notifications in production)
        for approver in gate.approvers:
            self._notify_stakeholder(
                approver,
                "quality_gate_review",
                f"Quality Gate Review Required: {gate.name}",
                f"Quality gate {gate.name} has been submitted for review. "
                f"Please review artifacts and provide approval/rejection."
            )

        return True

    def approve_quality_gate(self, gate_id: str, approver: str, comments: str) -> bool:
        """Approve a quality gate"""
        if gate_id not in self.quality_gates:
            return False

        gate = self.quality_gates[gate_id]
        if approver not in gate.approvers:
            return False

        gate.status = QualityGateStatus.APPROVED
        gate.approval_date = datetime.now()
        gate.comments.append(f"{approver}: {comments}")
        gate.exit_criteria_met = True

        self.logger.info(f"Quality gate {gate_id} approved by {approver}")
        return True

    def create_progress_report(self, reporting_period_days: int = 7) -> ProgressReport:
        """Create comprehensive progress report"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=reporting_period_days)

        # Calculate overall progress
        total_tasks = len(self.work_breakdown)
        completed_tasks = len([item for item in self.work_breakdown.values()
                             if item.status == TaskStatus.COMPLETED])
        overall_progress = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

        # Calculate phase progress
        phase_progress = {}
        for phase_num in range(1, 5):
            phase_tasks = [item for item in self.work_breakdown.values()
                          if item.id.startswith(f"{phase_num}.")]
            if phase_tasks:
                phase_completion = sum(item.completion_percentage for item in phase_tasks) / len(phase_tasks)
                phase_progress[f"phase{phase_num}"] = phase_completion

        # Identify milestones achieved
        milestones_achieved = []
        for milestone_id, milestone in self.phase_dashboard.milestones.items():
            if (milestone.actual_date and
                start_date <= milestone.actual_date <= end_date):
                milestones_achieved.append(milestone.name)

        # Identify risks
        risks_identified = [risk.title for risk in self.risks.values()
                          if start_date <= risk.review_date <= end_date]

        # Resource utilization
        resource_utilization = {}
        for agent_name, capacity in self.resource_capacity.items():
            if agent_name in self.resource_capacity:
                allocation_data = self.allocation_plan["capacity_analysis"].get(agent_name, {})
                resource_utilization[agent_name] = allocation_data.get("capacity_utilization", 0.0)

        # Create report
        report = ProgressReport(
            id=f"report_{end_date.strftime('%Y%m%d')}",
            report_date=end_date,
            reporting_period_start=start_date,
            reporting_period_end=end_date,
            overall_progress=overall_progress,
            phase_progress=phase_progress,
            milestones_achieved=milestones_achieved,
            risks_identified=risks_identified,
            issues_resolved=[],  # Would track actual issues
            budget_utilization=self._calculate_budget_utilization(),
            resource_utilization=resource_utilization,
            quality_metrics=self._calculate_quality_metrics(),
            next_period_forecast=self._generate_forecast()
        )

        self.progress_reports[report.id] = report
        return report

    def _calculate_budget_utilization(self) -> float:
        """Calculate budget utilization percentage"""
        # Simplified calculation based on completed work
        total_estimated_hours = sum(item.estimated_hours for item in self.work_breakdown.values())
        total_actual_hours = sum(item.actual_hours for item in self.work_breakdown.values())

        if total_estimated_hours > 0:
            return (total_actual_hours / total_estimated_hours) * 100
        return 0.0

    def _calculate_quality_metrics(self) -> Dict[str, float]:
        """Calculate quality metrics"""
        return {
            "quality_gates_passed": len([gate for gate in self.quality_gates.values()
                                       if gate.status == QualityGateStatus.APPROVED]),
            "quality_gates_total": len(self.quality_gates),
            "defect_rate": 0.02,  # Would calculate from actual defects
            "rework_percentage": 0.05,  # Would calculate from actual rework
            "customer_satisfaction": 0.85  # Would come from surveys
        }

    def _generate_forecast(self) -> Dict[str, Any]:
        """Generate forecast for next period"""
        return {
            "expected_completion_percentage": 25.0,  # Would use predictive modeling
            "risk_probability": 0.15,
            "resource_needs": ["Additional testing support"],
            "critical_path_items": ["Database migration", "ML model training"]
        }

    def _notify_stakeholder(self, stakeholder: str, communication_type: str, subject: str, content: str):
        """Send notification to stakeholder"""
        communication = StakeholderCommunication(
            id=str(uuid.uuid4()),
            stakeholder_group=stakeholder,
            communication_type=communication_type,
            subject=subject,
            content=content,
            sent_date=datetime.now(),
            recipients=[stakeholder],
            acknowledgments=[],
            follow_up_required=False,
            follow_up_date=None
        )

        self.stakeholder_communications.append(communication)

    def get_implementation_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive dashboard data"""
        current_allocation_plan = self.create_resource_allocation_plan()

        return {
            "work_breakdown": {
                wbs_id: asdict(item) for wbs_id, item in self.work_breakdown.items()
            },
            "resource_allocation": current_allocation_plan,
            "risk_summary": {
                "total_risks": len(self.risks),
                "high_risks": len([r for r in self.risks.values() if r.risk_score > 0.6]),
                "medium_risks": len([r for r in self.risks.values() if 0.3 <= r.risk_score <= 0.6]),
                "low_risks": len([r for r in self.risks.values() if r.risk_score < 0.3]),
                "risks_by_status": {
                    status.value: len([r for r in self.risks.values() if r.status == status])
                    for status in RiskStatus
                }
            },
            "quality_gates": {
                gate_id: asdict(gate) for gate_id, gate in self.quality_gates.items()
            },
            "progress_summary": {
                "overall_progress": sum(item.completion_percentage for item in self.work_breakdown.values()) / max(1, len(self.work_breakdown)),
                "tasks_completed": len([item for item in self.work_breakdown.values() if item.status == TaskStatus.COMPLETED]),
                "tasks_in_progress": len([item for item in self.work_breakdown.values() if item.status == TaskStatus.IN_PROGRESS]),
                "tasks_not_started": len([item for item in self.work_breakdown.values() if item.status == TaskStatus.NOT_STARTED]),
                "tasks_blocked": len([item for item in self.work_breakdown.values() if item.status == TaskStatus.BLOCKED])
            },
            "budget_summary": {
                "total_budget": sum(self._calculate_cost_by_phase().values()),
                "budget_utilized": self._calculate_budget_utilization(),
                "cost_by_phase": self._calculate_cost_by_phase(),
                "cost_by_agent": self._calculate_cost_by_agent()
            }
        }

    def generate_implementation_html(self) -> str:
        """Generate HTML template for implementation tools"""
        dashboard_data = self.get_implementation_dashboard_data()

        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPECTRA Implementation Management Tools</title>
    <style>
        body {{ font-family: 'Inter', sans-serif; margin: 0; padding: 20px; background-color: #f8fafc; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .dashboard-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 20px; }}
        .card {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .metric-value {{ font-size: 2em; font-weight: bold; color: #667eea; }}
        .progress-bar {{ width: 100%; height: 10px; background: #ecf0f1; border-radius: 5px; overflow: hidden; margin: 10px 0; }}
        .progress-fill {{ height: 100%; background: linear-gradient(90deg, #3498db, #2ecc71); transition: width 0.3s ease; }}
        .risk-high {{ color: #e74c3c; }}
        .risk-medium {{ color: #f39c12; }}
        .risk-low {{ color: #2ecc71; }}
        .status-completed {{ color: #2ecc71; }}
        .status-in-progress {{ color: #3498db; }}
        .status-not-started {{ color: #95a5a6; }}
        .status-blocked {{ color: #e74c3c; }}
        .wbs-item {{ margin: 10px 0; padding: 10px; border-left: 4px solid #3498db; background: #f8f9fa; }}
        .wbs-level-1 {{ margin-left: 0; }}
        .wbs-level-2 {{ margin-left: 20px; }}
        .wbs-level-3 {{ margin-left: 40px; }}
        .quality-gate {{ margin: 10px 0; padding: 15px; border-radius: 8px; background: #fff; border: 1px solid #ddd; }}
        .gate-approved {{ border-left: 4px solid #2ecc71; }}
        .gate-pending {{ border-left: 4px solid #f39c12; }}
        .gate-rejected {{ border-left: 4px solid #e74c3c; }}
        .resource-allocation {{ display: flex; justify-content: space-between; align-items: center; margin: 5px 0; }}
        .agent-utilization {{ width: 150px; height: 20px; background: #ecf0f1; border-radius: 10px; overflow: hidden; }}
        .utilization-fill {{ height: 100%; transition: width 0.3s ease; }}
        .overallocated {{ background: #e74c3c; }}
        .optimal {{ background: #2ecc71; }}
        .underutilized {{ background: #f39c12; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>SPECTRA Implementation Management Tools</h1>
        <p>Comprehensive project planning, resource management, and quality control</p>
    </div>

    <div class="dashboard-grid">
        <!-- Overall Progress -->
        <div class="card">
            <h3>Overall Progress</h3>
            <div class="metric-value">{dashboard_data['progress_summary']['overall_progress']:.1f}%</div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {dashboard_data['progress_summary']['overall_progress']}%"></div>
            </div>
            <div>
                <span class="status-completed">✓ {dashboard_data['progress_summary']['tasks_completed']} Completed</span> |
                <span class="status-in-progress">⏳ {dashboard_data['progress_summary']['tasks_in_progress']} In Progress</span> |
                <span class="status-not-started">⭕ {dashboard_data['progress_summary']['tasks_not_started']} Not Started</span>
                {f" | <span class='status-blocked'>🚫 {dashboard_data['progress_summary']['tasks_blocked']} Blocked</span>" if dashboard_data['progress_summary']['tasks_blocked'] > 0 else ""}
            </div>
        </div>

        <!-- Budget Summary -->
        <div class="card">
            <h3>Budget Summary</h3>
            <div class="metric-value">${dashboard_data['budget_summary']['total_budget']:,.0f}</div>
            <div>Total Project Budget</div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {dashboard_data['budget_summary']['budget_utilized']}%"></div>
            </div>
            <div>Utilized: {dashboard_data['budget_summary']['budget_utilized']:.1f}%</div>
        </div>

        <!-- Risk Summary -->
        <div class="card">
            <h3>Risk Assessment</h3>
            <div>
                <span class="risk-high">🔴 {dashboard_data['risk_summary']['high_risks']} High</span> |
                <span class="risk-medium">🟡 {dashboard_data['risk_summary']['medium_risks']} Medium</span> |
                <span class="risk-low">🟢 {dashboard_data['risk_summary']['low_risks']} Low</span>
            </div>
            <div style="margin-top: 10px;">
                Total Risks: <strong>{dashboard_data['risk_summary']['total_risks']}</strong>
            </div>
        </div>

        <!-- Quality Gates -->
        <div class="card">
            <h3>Quality Gates</h3>
            <div class="metric-value">{len([g for g in dashboard_data['quality_gates'].values() if g['status'] == 'approved'])}/{len(dashboard_data['quality_gates'])}</div>
            <div>Gates Approved</div>
            <div style="margin-top: 10px;">
                {''.join([f"<div class='quality-gate gate-{gate['status']}'><strong>{gate['name']}</strong><br><small>{gate['phase_id']} - {gate['status'].title()}</small></div>" for gate in list(dashboard_data['quality_gates'].values())[:3]])}
            </div>
        </div>
    </div>

    <!-- Resource Allocation -->
    <div class="card" style="margin-bottom: 20px;">
        <h3>Resource Allocation Overview</h3>
        <div>
            {''.join([f'''
            <div class="resource-allocation">
                <span><strong>{agent_name}</strong></span>
                <div class="agent-utilization">
                    <div class="utilization-fill {'overallocated' if analysis['capacity_utilization'] > 1.0 else 'optimal' if analysis['capacity_utilization'] > 0.7 else 'underutilized'}"
                         style="width: {min(100, analysis['capacity_utilization'] * 100)}%"></div>
                </div>
                <span>{analysis['capacity_utilization']:.1%}</span>
            </div>
            ''' for agent_name, analysis in dashboard_data['resource_allocation']['capacity_analysis'].items()])}
        </div>
    </div>

    <!-- Work Breakdown Structure -->
    <div class="card">
        <h3>Work Breakdown Structure</h3>
        <div>
            {''.join([f'''
            <div class="wbs-item wbs-level-{item['level']}">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong>{item['id']} - {item['name']}</strong>
                        <br><small>{item['description']}</small>
                        <br><small>Agents: {", ".join(item['assigned_agents'])}</small>
                    </div>
                    <div style="text-align: right;">
                        <div class="progress-bar" style="width: 100px;">
                            <div class="progress-fill" style="width: {item['completion_percentage']}%"></div>
                        </div>
                        <small>{item['completion_percentage']:.1f}%</small>
                    </div>
                </div>
            </div>
            ''' for item in list(dashboard_data['work_breakdown'].values()) if item['level'] <= 2])}
        </div>
    </div>

    <script>
        // Auto-refresh every 30 seconds
        setInterval(function() {{
            location.reload();
        }}, 30000);
    </script>
</body>
</html>
        """


# Example usage and testing
async def main():
    """Example usage of implementation tools"""
    print("SPECTRA Implementation Management Tools")
    print("=" * 50)

    # Mock orchestrator and phase dashboard
    from spectra_orchestrator import SpectraOrchestrator

    orchestrator = SpectraOrchestrator()
    await orchestrator.initialize()

    phase_dashboard = PhaseManagementDashboard(orchestrator)
    tools = ImplementationTools(orchestrator, phase_dashboard)

    # Update task progress
    tools.update_task_progress("1.1", 25.0, 12.0)
    print("Updated task 1.1 progress to 25%")

    # Create resource allocation plan
    allocation_plan = tools.create_resource_allocation_plan()
    print(f"Resource allocation plan created: ${allocation_plan['cost_projections']['total_project_cost']:,.0f} total cost")

    # Submit quality gate
    success = tools.submit_quality_gate("qg_1_1", ["migration_report.pdf"], "DATABASE")
    print(f"Quality gate submission: {'Success' if success else 'Failed'}")

    # Create progress report
    report = tools.create_progress_report()
    print(f"Progress report created: {report.overall_progress:.1f}% overall progress")

    # Generate HTML
    html = tools.generate_implementation_html()
    with open("/tmp/implementation_tools.html", "w") as f:
        f.write(html)
    print("Implementation tools HTML saved to /tmp/implementation_tools.html")

    # Get dashboard data
    dashboard_data = tools.get_implementation_dashboard_data()
    print(f"Dashboard data: {len(dashboard_data['work_breakdown'])} WBS items, {len(dashboard_data['quality_gates'])} quality gates")


if __name__ == "__main__":
    asyncio.run(main())