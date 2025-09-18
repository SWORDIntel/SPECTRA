#!/usr/bin/env python3
"""
SPECTRA Multi-Agent Orchestration System
=========================================

Comprehensive orchestration framework for coordinating multi-agent workflows
across the 4-phase SPECTRA advanced data management implementation.

Author: COORDINATOR Agent - Multi-Agent Orchestration Specialist
Date: September 18, 2025
"""

import asyncio
import logging
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any, Callable, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import signal
import sys

# SPECTRA-specific imports
from tgarchive.config_models import Config
from tgarchive.db import SpectraDB
from tgarchive.scheduler_service import SchedulerDaemon
from tgarchive.notifications import NotificationManager


class AgentStatus(Enum):
    """Agent status enumeration"""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    PAUSED = "paused"


class WorkflowStatus(Enum):
    """Workflow execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ExecutionMode(Enum):
    """Agent execution modes"""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"
    PIPELINE = "pipeline"


class Priority(Enum):
    """Task priority levels"""
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    BACKGROUND = 5


@dataclass
class AgentMetadata:
    """Agent metadata and capabilities"""
    name: str
    category: str
    capabilities: List[str]
    dependencies: List[str] = field(default_factory=list)
    resource_requirements: Dict[str, Any] = field(default_factory=dict)
    max_concurrent_tasks: int = 1
    average_execution_time: float = 0.0
    success_rate: float = 1.0
    last_health_check: Optional[datetime] = None
    status: AgentStatus = AgentStatus.IDLE


@dataclass
class Task:
    """Individual task definition"""
    id: str
    agent: str
    action: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    priority: Priority = Priority.MEDIUM
    dependencies: List[str] = field(default_factory=list)
    timeout: Optional[int] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: AgentStatus = AgentStatus.IDLE
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0


@dataclass
class Workflow:
    """Workflow definition with multiple tasks"""
    id: str
    name: str
    description: str
    phase: str
    tasks: List[Task] = field(default_factory=list)
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    priority: Priority = Priority.MEDIUM
    max_parallel_tasks: int = 4
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: WorkflowStatus = WorkflowStatus.PENDING
    progress: float = 0.0
    estimated_duration: Optional[timedelta] = None
    actual_duration: Optional[timedelta] = None


@dataclass
class OrchestrationMetrics:
    """System orchestration metrics"""
    total_workflows: int = 0
    active_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    average_task_duration: float = 0.0
    system_load: float = 0.0
    resource_utilization: Dict[str, float] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.now)


class SpectraOrchestrator:
    """
    Main orchestration engine for SPECTRA multi-agent coordination.

    Manages workflow execution, agent coordination, resource allocation,
    and real-time monitoring across all implementation phases.
    """

    def __init__(self,
                 config_path: str = "spectra_config.json",
                 db_path: str = "spectra.db",
                 log_level: str = "INFO"):
        """Initialize the SPECTRA Orchestrator"""
        self.config_path = config_path
        self.db_path = db_path

        # Setup logging
        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('spectra_orchestrator.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)

        # Core components
        self.config: Optional[Config] = None
        self.db: Optional[SpectraDB] = None
        self.scheduler: Optional[SchedulerDaemon] = None
        self.notification_manager: Optional[NotificationManager] = None

        # Orchestration state
        self.agents: Dict[str, AgentMetadata] = {}
        self.workflows: Dict[str, Workflow] = {}
        self.active_tasks: Dict[str, Task] = {}
        self.task_queue: List[Task] = []
        self.completed_tasks: List[Task] = []
        self.failed_tasks: List[Task] = []

        # Execution control
        self.is_running = False
        self.executor = ThreadPoolExecutor(max_workers=8)
        self.metrics = OrchestrationMetrics()

        # Synchronization
        self._lock = threading.RLock()
        self._workflow_lock = threading.RLock()
        self._metrics_lock = threading.RLock()

        # Monitoring and health
        self.health_check_interval = 30  # seconds
        self.last_health_check = datetime.now()

        self.logger.info("SPECTRA Orchestrator initialized")

    async def initialize(self) -> bool:
        """Initialize orchestrator components and load configurations"""
        try:
            # Load configuration
            from pathlib import Path
            config_path = Path(self.config_path)
            self.config = Config(path=config_path)
            if not self.config.data:
                self.logger.error(f"Failed to load configuration from {self.config_path}")
                return False

            # Initialize database
            self.db = SpectraDB(self.db_path)

            # Initialize notification manager
            notification_config = self.config.data.get("notifications", {})
            self.notification_manager = NotificationManager(notification_config)

            # Load agent definitions
            await self._load_agent_definitions()

            # Load predefined workflows
            await self._load_workflow_definitions()

            # Start health monitoring
            asyncio.create_task(self._health_monitor_loop())

            self.logger.info("Orchestrator initialization completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize orchestrator: {e}", exc_info=True)
            return False

    async def _load_agent_definitions(self):
        """Load agent definitions and capabilities"""
        # Define SPECTRA agent ecosystem based on analysis
        agent_definitions = {
            # Command & Control
            "DIRECTOR": AgentMetadata(
                name="DIRECTOR",
                category="command_control",
                capabilities=["strategic_planning", "resource_allocation", "workflow_coordination"],
                resource_requirements={"cpu": 0.5, "memory": "512MB"},
                max_concurrent_tasks=2
            ),
            "PROJECTORCHESTRATOR": AgentMetadata(
                name="PROJECTORCHESTRATOR",
                category="command_control",
                capabilities=["tactical_coordination", "agent_management", "execution_monitoring"],
                resource_requirements={"cpu": 0.3, "memory": "256MB"},
                max_concurrent_tasks=3
            ),

            # Database & Architecture
            "DATABASE": AgentMetadata(
                name="DATABASE",
                category="infrastructure",
                capabilities=["schema_design", "migration", "optimization", "backup_recovery"],
                dependencies=["INFRASTRUCTURE"],
                resource_requirements={"cpu": 1.0, "memory": "2GB", "storage": "100GB"},
                max_concurrent_tasks=1
            ),
            "ARCHITECT": AgentMetadata(
                name="ARCHITECT",
                category="development",
                capabilities=["system_design", "architecture_planning", "integration_design"],
                resource_requirements={"cpu": 0.5, "memory": "1GB"},
                max_concurrent_tasks=2
            ),

            # Performance & Optimization
            "OPTIMIZER": AgentMetadata(
                name="OPTIMIZER",
                category="performance",
                capabilities=["performance_tuning", "compression_optimization", "resource_optimization"],
                dependencies=["DATABASE", "INFRASTRUCTURE"],
                resource_requirements={"cpu": 0.8, "memory": "1GB"},
                max_concurrent_tasks=2
            ),
            "HARDWARE-INTEL": AgentMetadata(
                name="HARDWARE-INTEL",
                category="hardware",
                capabilities=["cpu_optimization", "avx_optimization", "memory_tuning"],
                resource_requirements={"cpu": 0.2, "memory": "256MB"},
                max_concurrent_tasks=1
            ),

            # Data Processing
            "DATASCIENCE": AgentMetadata(
                name="DATASCIENCE",
                category="analytics",
                capabilities=["ml_models", "data_analysis", "pattern_recognition", "anomaly_detection"],
                dependencies=["DATABASE"],
                resource_requirements={"cpu": 2.0, "memory": "4GB", "gpu": "optional"},
                max_concurrent_tasks=2
            ),
            "MLOPS": AgentMetadata(
                name="MLOPS",
                category="analytics",
                capabilities=["model_deployment", "pipeline_automation", "model_monitoring"],
                dependencies=["DATASCIENCE", "INFRASTRUCTURE"],
                resource_requirements={"cpu": 1.0, "memory": "2GB"},
                max_concurrent_tasks=2
            ),

            # Development & Testing
            "PATCHER": AgentMetadata(
                name="PATCHER",
                category="development",
                capabilities=["code_fixes", "integration_patches", "legacy_system_integration"],
                resource_requirements={"cpu": 0.5, "memory": "512MB"},
                max_concurrent_tasks=2
            ),
            "TESTBED": AgentMetadata(
                name="TESTBED",
                category="quality",
                capabilities=["integration_testing", "performance_testing", "regression_testing"],
                dependencies=["DATABASE", "INFRASTRUCTURE"],
                resource_requirements={"cpu": 1.0, "memory": "2GB"},
                max_concurrent_tasks=3
            ),
            "DEBUGGER": AgentMetadata(
                name="DEBUGGER",
                category="quality",
                capabilities=["error_analysis", "performance_debugging", "system_diagnostics"],
                resource_requirements={"cpu": 0.5, "memory": "1GB"},
                max_concurrent_tasks=2
            ),

            # Infrastructure & Deployment
            "INFRASTRUCTURE": AgentMetadata(
                name="INFRASTRUCTURE",
                category="infrastructure",
                capabilities=["cloud_setup", "kubernetes_management", "resource_provisioning"],
                resource_requirements={"cpu": 0.5, "memory": "1GB"},
                max_concurrent_tasks=2
            ),
            "DEPLOYER": AgentMetadata(
                name="DEPLOYER",
                category="deployment",
                capabilities=["application_deployment", "configuration_management", "rollback_procedures"],
                dependencies=["INFRASTRUCTURE"],
                resource_requirements={"cpu": 0.5, "memory": "512MB"},
                max_concurrent_tasks=2
            ),
            "MONITOR": AgentMetadata(
                name="MONITOR",
                category="monitoring",
                capabilities=["system_monitoring", "alerting", "performance_tracking", "log_analysis"],
                dependencies=["INFRASTRUCTURE"],
                resource_requirements={"cpu": 0.3, "memory": "512MB"},
                max_concurrent_tasks=1
            ),

            # Security
            "SECURITY": AgentMetadata(
                name="SECURITY",
                category="security",
                capabilities=["security_analysis", "vulnerability_assessment", "compliance_checking"],
                resource_requirements={"cpu": 0.5, "memory": "1GB"},
                max_concurrent_tasks=2
            ),

            # Web & API
            "WEB": AgentMetadata(
                name="WEB",
                category="frontend",
                capabilities=["web_interface", "dashboard_development", "user_experience"],
                dependencies=["APIDESIGNER"],
                resource_requirements={"cpu": 0.5, "memory": "1GB"},
                max_concurrent_tasks=2
            ),
            "APIDESIGNER": AgentMetadata(
                name="APIDESIGNER",
                category="backend",
                capabilities=["api_design", "endpoint_development", "integration_apis"],
                dependencies=["DATABASE"],
                resource_requirements={"cpu": 0.5, "memory": "1GB"},
                max_concurrent_tasks=2
            )
        }

        self.agents.update(agent_definitions)
        self.logger.info(f"Loaded {len(agent_definitions)} agent definitions")

    async def _load_workflow_definitions(self):
        """Load predefined workflow templates for each phase"""

        # Phase 1: Foundation Enhancement
        phase1_workflow = Workflow(
            id="phase1_foundation",
            name="Foundation Enhancement",
            description="Database migration, compression integration, and deduplication system",
            phase="phase1",
            execution_mode=ExecutionMode.SEQUENTIAL,
            priority=Priority.CRITICAL,
            max_parallel_tasks=4
        )

        # Phase 1 Tasks
        phase1_tasks = [
            # Week 1: Database Migration
            Task("db_setup", "INFRASTRUCTURE", "setup_postgresql_cluster",
                 {"cluster_size": 3, "replication": True}, Priority.CRITICAL),
            Task("schema_migration", "DATABASE", "migrate_schema",
                 {"source": "sqlite", "target": "postgresql", "validate": True}, Priority.CRITICAL,
                 dependencies=["db_setup"]),
            Task("performance_baseline", "OPTIMIZER", "establish_baseline",
                 {"target_metrics": {"inserts_per_sec": 10000}}, Priority.HIGH,
                 dependencies=["schema_migration"]),

            # Week 2: Compression Integration
            Task("kanzi_integration", "OPTIMIZER", "integrate_kanzi_cpp",
                 {"compression_ratio": 0.65, "threading": True}, Priority.HIGH,
                 dependencies=["performance_baseline"]),
            Task("compression_testing", "TESTBED", "test_compression_performance",
                 {"test_datasets": ["small", "medium", "large"]}, Priority.HIGH,
                 dependencies=["kanzi_integration"]),

            # Week 3: Deduplication System
            Task("dedup_implementation", "OPTIMIZER", "implement_deduplication",
                 {"algorithms": ["sha256", "perceptual", "fuzzy"], "accuracy_target": 0.995}, Priority.HIGH,
                 dependencies=["compression_testing"]),
            Task("redis_cache_setup", "INFRASTRUCTURE", "setup_redis_cluster",
                 {"cache_size": "10GB", "persistence": True}, Priority.MEDIUM,
                 dependencies=["dedup_implementation"]),

            # Week 4: Integration Testing
            Task("integration_testing", "TESTBED", "run_integration_tests",
                 {"test_suites": ["migration", "compression", "deduplication"]}, Priority.HIGH,
                 dependencies=["redis_cache_setup"]),
            Task("performance_validation", "DEBUGGER", "validate_performance",
                 {"baseline_comparison": True}, Priority.HIGH,
                 dependencies=["integration_testing"])
        ]

        phase1_workflow.tasks = phase1_tasks
        self.workflows["phase1_foundation"] = phase1_workflow

        # Phase 2: Advanced Features
        phase2_workflow = Workflow(
            id="phase2_advanced",
            name="Advanced Features Implementation",
            description="Smart recording, multi-tier storage, real-time analytics",
            phase="phase2",
            execution_mode=ExecutionMode.PIPELINE,
            priority=Priority.HIGH,
            max_parallel_tasks=6
        )

        phase2_tasks = [
            # Week 5: Smart Recording Engine
            Task("ml_models_training", "DATASCIENCE", "train_classification_models",
                 {"model_types": ["nlp", "content_classifier"], "accuracy_target": 0.85}, Priority.HIGH),
            Task("priority_queue_setup", "ARCHITECT", "design_priority_queue",
                 {"queue_types": ["high", "medium", "low"], "kafka_integration": True}, Priority.HIGH),
            Task("recording_engine", "MLOPS", "deploy_smart_recording",
                 {"real_time": True, "metadata_enrichment": True}, Priority.HIGH,
                 dependencies=["ml_models_training", "priority_queue_setup"]),

            # Week 6: Multi-Tier Storage
            Task("storage_architecture", "ARCHITECT", "design_tiered_storage",
                 {"tiers": {"hot": "7d", "warm": "30d", "cold": "unlimited"}}, Priority.HIGH),
            Task("lifecycle_policies", "INFRASTRUCTURE", "implement_lifecycle_management",
                 {"automated": True, "cost_optimization": True}, Priority.MEDIUM,
                 dependencies=["storage_architecture"]),

            # Week 7: Real-Time Analytics
            Task("clickhouse_setup", "DATABASE", "deploy_clickhouse_cluster",
                 {"nodes": 3, "replication": True}, Priority.HIGH),
            Task("analytics_dashboard", "WEB", "build_analytics_dashboard",
                 {"real_time": True, "threat_indicators": True}, Priority.HIGH,
                 dependencies=["clickhouse_setup"]),
            Task("streaming_analytics", "DATASCIENCE", "setup_stream_processing",
                 {"framework": "flink", "low_latency": True}, Priority.HIGH,
                 dependencies=["clickhouse_setup"]),

            # Week 8: Network Analysis
            Task("graph_database", "DATABASE", "deploy_neo4j_cluster",
                 {"high_availability": True}, Priority.HIGH),
            Task("network_analysis", "DATASCIENCE", "implement_network_analysis",
                 {"algorithms": ["centrality", "community_detection"], "threat_detection": True}, Priority.HIGH,
                 dependencies=["graph_database"])
        ]

        phase2_workflow.tasks = phase2_tasks
        self.workflows["phase2_advanced"] = phase2_workflow

        # Phase 3: Production Deployment
        phase3_workflow = Workflow(
            id="phase3_production",
            name="Production Deployment",
            description="Kubernetes orchestration, auto-scaling, monitoring",
            phase="phase3",
            execution_mode=ExecutionMode.PARALLEL,
            priority=Priority.CRITICAL,
            max_parallel_tasks=8
        )

        phase3_tasks = [
            # Production Infrastructure
            Task("k8s_cluster", "INFRASTRUCTURE", "deploy_kubernetes_cluster",
                 {"nodes": 10, "auto_scaling": True, "high_availability": True}, Priority.CRITICAL),
            Task("production_deploy", "DEPLOYER", "deploy_to_production",
                 {"blue_green": True, "rollback_ready": True}, Priority.CRITICAL,
                 dependencies=["k8s_cluster"]),
            Task("monitoring_stack", "MONITOR", "deploy_monitoring_stack",
                 {"prometheus": True, "grafana": True, "alertmanager": True}, Priority.HIGH,
                 dependencies=["production_deploy"]),
            Task("security_hardening", "SECURITY", "implement_security_hardening",
                 {"compliance": ["SOC2", "ISO27001"], "penetration_testing": True}, Priority.HIGH,
                 dependencies=["production_deploy"])
        ]

        phase3_workflow.tasks = phase3_tasks
        self.workflows["phase3_production"] = phase3_workflow

        # Phase 4: Optimization & Enhancement
        phase4_workflow = Workflow(
            id="phase4_optimization",
            name="Optimization & Enhancement",
            description="Advanced ML, performance optimization, next-gen features",
            phase="phase4",
            execution_mode=ExecutionMode.CONDITIONAL,
            priority=Priority.MEDIUM,
            max_parallel_tasks=6
        )

        phase4_tasks = [
            Task("advanced_ml", "MLOPS", "deploy_advanced_ml_models",
                 {"deep_learning": True, "real_time_inference": True}, Priority.HIGH),
            Task("performance_optimization", "OPTIMIZER", "global_performance_optimization",
                 {"target_improvement": "50%", "resource_efficiency": True}, Priority.HIGH),
            Task("threat_detection", "SECURITY", "advanced_threat_detection",
                 {"ml_powered": True, "behavioral_analysis": True}, Priority.HIGH),
            Task("next_gen_features", "ARCHITECT", "research_next_generation",
                 {"emerging_tech": True, "future_roadmap": True}, Priority.MEDIUM)
        ]

        phase4_workflow.tasks = phase4_tasks
        self.workflows["phase4_optimization"] = phase4_workflow

        self.logger.info(f"Loaded {len(self.workflows)} workflow definitions")

    async def start_orchestration(self):
        """Start the orchestration engine"""
        if self.is_running:
            self.logger.warning("Orchestrator is already running")
            return

        self.is_running = True
        self.logger.info("Starting SPECTRA Orchestration Engine")

        try:
            # Start main orchestration loop
            await asyncio.gather(
                self._workflow_execution_loop(),
                self._task_scheduler_loop(),
                self._metrics_update_loop(),
                self._resource_monitor_loop()
            )
        except Exception as e:
            self.logger.error(f"Orchestration engine error: {e}", exc_info=True)
        finally:
            self.is_running = False

    async def stop_orchestration(self):
        """Stop the orchestration engine gracefully"""
        self.logger.info("Stopping SPECTRA Orchestration Engine")
        self.is_running = False

        # Wait for active tasks to complete or timeout
        timeout = 30  # seconds
        start_time = time.time()

        while self.active_tasks and (time.time() - start_time) < timeout:
            await asyncio.sleep(1)

        # Cancel remaining tasks
        for task_id, task in self.active_tasks.items():
            task.status = AgentStatus.FAILED
            task.error = "Orchestrator shutdown"

        self.executor.shutdown(wait=True)
        self.logger.info("Orchestration engine stopped")

    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit a workflow for execution"""
        with self._workflow_lock:
            workflow.status = WorkflowStatus.PENDING
            self.workflows[workflow.id] = workflow

            # Add tasks to queue
            for task in workflow.tasks:
                self.task_queue.append(task)

        self.logger.info(f"Submitted workflow: {workflow.name} ({workflow.id})")
        await self._notify_workflow_submitted(workflow)
        return workflow.id

    async def submit_task(self, task: Task) -> str:
        """Submit an individual task for execution"""
        with self._lock:
            self.task_queue.append(task)

        self.logger.info(f"Submitted task: {task.action} for agent {task.agent}")
        return task.id

    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed workflow status"""
        with self._workflow_lock:
            workflow = self.workflows.get(workflow_id)
            if not workflow:
                return None

            return {
                "id": workflow.id,
                "name": workflow.name,
                "status": workflow.status.value,
                "progress": workflow.progress,
                "phase": workflow.phase,
                "tasks": [
                    {
                        "id": task.id,
                        "agent": task.agent,
                        "action": task.action,
                        "status": task.status.value,
                        "execution_time": task.execution_time,
                        "error": task.error
                    }
                    for task in workflow.tasks
                ],
                "created_at": workflow.created_at.isoformat(),
                "started_at": workflow.started_at.isoformat() if workflow.started_at else None,
                "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None,
                "estimated_duration": str(workflow.estimated_duration) if workflow.estimated_duration else None,
                "actual_duration": str(workflow.actual_duration) if workflow.actual_duration else None
            }

    async def get_system_metrics(self) -> Dict[str, Any]:
        """Get comprehensive system metrics"""
        with self._metrics_lock:
            return {
                "orchestration_metrics": asdict(self.metrics),
                "agent_status": {
                    name: {
                        "status": agent.status.value,
                        "success_rate": agent.success_rate,
                        "average_execution_time": agent.average_execution_time,
                        "last_health_check": agent.last_health_check.isoformat() if agent.last_health_check else None
                    }
                    for name, agent in self.agents.items()
                },
                "workflow_summary": {
                    status.value: len([w for w in self.workflows.values() if w.status == status])
                    for status in WorkflowStatus
                },
                "task_queue_size": len(self.task_queue),
                "active_tasks": len(self.active_tasks),
                "system_load": self.metrics.system_load,
                "last_updated": self.metrics.last_updated.isoformat()
            }

    async def pause_workflow(self, workflow_id: str) -> bool:
        """Pause a running workflow"""
        with self._workflow_lock:
            workflow = self.workflows.get(workflow_id)
            if not workflow or workflow.status != WorkflowStatus.RUNNING:
                return False

            workflow.status = WorkflowStatus.PAUSED

            # Pause associated tasks
            for task in workflow.tasks:
                if task.status == AgentStatus.RUNNING:
                    task.status = AgentStatus.PAUSED

        self.logger.info(f"Paused workflow: {workflow_id}")
        return True

    async def resume_workflow(self, workflow_id: str) -> bool:
        """Resume a paused workflow"""
        with self._workflow_lock:
            workflow = self.workflows.get(workflow_id)
            if not workflow or workflow.status != WorkflowStatus.PAUSED:
                return False

            workflow.status = WorkflowStatus.RUNNING

            # Resume paused tasks
            for task in workflow.tasks:
                if task.status == AgentStatus.PAUSED:
                    task.status = AgentStatus.IDLE
                    self.task_queue.append(task)

        self.logger.info(f"Resumed workflow: {workflow_id}")
        return True

    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a workflow and its tasks"""
        with self._workflow_lock:
            workflow = self.workflows.get(workflow_id)
            if not workflow:
                return False

            workflow.status = WorkflowStatus.CANCELLED
            workflow.completed_at = datetime.now()

            # Cancel all tasks
            for task in workflow.tasks:
                if task.status in [AgentStatus.IDLE, AgentStatus.RUNNING, AgentStatus.PAUSED]:
                    task.status = AgentStatus.FAILED
                    task.error = "Workflow cancelled"
                    task.completed_at = datetime.now()

        self.logger.info(f"Cancelled workflow: {workflow_id}")
        return True

    async def _workflow_execution_loop(self):
        """Main workflow execution loop"""
        while self.is_running:
            try:
                with self._workflow_lock:
                    for workflow in self.workflows.values():
                        if workflow.status == WorkflowStatus.PENDING:
                            await self._start_workflow_execution(workflow)
                        elif workflow.status == WorkflowStatus.RUNNING:
                            await self._update_workflow_progress(workflow)

                await asyncio.sleep(1)

            except Exception as e:
                self.logger.error(f"Workflow execution loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _task_scheduler_loop(self):
        """Task scheduling and execution loop"""
        while self.is_running:
            try:
                if not self.task_queue:
                    await asyncio.sleep(1)
                    continue

                # Get next available task
                task = await self._get_next_ready_task()
                if not task:
                    await asyncio.sleep(1)
                    continue

                # Check agent availability
                agent = self.agents.get(task.agent)
                if not agent or not await self._is_agent_available(agent):
                    await asyncio.sleep(1)
                    continue

                # Execute task
                await self._execute_task(task)

            except Exception as e:
                self.logger.error(f"Task scheduler loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _metrics_update_loop(self):
        """Metrics collection and update loop"""
        while self.is_running:
            try:
                await self._update_system_metrics()
                await asyncio.sleep(10)  # Update every 10 seconds

            except Exception as e:
                self.logger.error(f"Metrics update loop error: {e}", exc_info=True)
                await asyncio.sleep(30)

    async def _resource_monitor_loop(self):
        """Resource monitoring and optimization loop"""
        while self.is_running:
            try:
                await self._monitor_system_resources()
                await self._optimize_resource_allocation()
                await asyncio.sleep(30)  # Monitor every 30 seconds

            except Exception as e:
                self.logger.error(f"Resource monitor loop error: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _health_monitor_loop(self):
        """Agent health monitoring loop"""
        while self.is_running:
            try:
                for agent_name, agent in self.agents.items():
                    await self._check_agent_health(agent)

                self.last_health_check = datetime.now()
                await asyncio.sleep(self.health_check_interval)

            except Exception as e:
                self.logger.error(f"Health monitor loop error: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _start_workflow_execution(self, workflow: Workflow):
        """Start execution of a pending workflow"""
        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = datetime.now()

        self.logger.info(f"Starting workflow execution: {workflow.name}")
        await self._notify_workflow_started(workflow)

    async def _update_workflow_progress(self, workflow: Workflow):
        """Update workflow progress based on task completion"""
        total_tasks = len(workflow.tasks)
        completed_tasks = len([t for t in workflow.tasks if t.status == AgentStatus.COMPLETED])
        failed_tasks = len([t for t in workflow.tasks if t.status == AgentStatus.FAILED])

        workflow.progress = completed_tasks / total_tasks if total_tasks > 0 else 0

        # Check if workflow is complete
        if completed_tasks == total_tasks:
            workflow.status = WorkflowStatus.COMPLETED
            workflow.completed_at = datetime.now()
            workflow.actual_duration = workflow.completed_at - workflow.started_at
            await self._notify_workflow_completed(workflow)

        elif failed_tasks > 0 and (completed_tasks + failed_tasks) == total_tasks:
            workflow.status = WorkflowStatus.FAILED
            workflow.completed_at = datetime.now()
            workflow.actual_duration = workflow.completed_at - workflow.started_at
            await self._notify_workflow_failed(workflow)

    async def _get_next_ready_task(self) -> Optional[Task]:
        """Get the next task ready for execution"""
        with self._lock:
            # Sort by priority and creation time
            self.task_queue.sort(key=lambda t: (t.priority.value, t.created_at))

            for i, task in enumerate(self.task_queue):
                if await self._are_dependencies_satisfied(task):
                    return self.task_queue.pop(i)

            return None

    async def _are_dependencies_satisfied(self, task: Task) -> bool:
        """Check if task dependencies are satisfied"""
        for dep_id in task.dependencies:
            dep_task = None

            # Find dependency task
            for workflow in self.workflows.values():
                for t in workflow.tasks:
                    if t.id == dep_id:
                        dep_task = t
                        break

            if not dep_task or dep_task.status != AgentStatus.COMPLETED:
                return False

        return True

    async def _is_agent_available(self, agent: AgentMetadata) -> bool:
        """Check if agent is available for new tasks"""
        active_agent_tasks = len([t for t in self.active_tasks.values() if t.agent == agent.name])
        return active_agent_tasks < agent.max_concurrent_tasks

    async def _execute_task(self, task: Task):
        """Execute a task with the appropriate agent"""
        try:
            task.status = AgentStatus.RUNNING
            task.started_at = datetime.now()
            self.active_tasks[task.id] = task

            agent = self.agents[task.agent]
            agent.status = AgentStatus.RUNNING

            self.logger.info(f"Executing task {task.id}: {task.action} with agent {task.agent}")

            # Simulate task execution (replace with actual agent invocation)
            execution_result = await self._invoke_agent(task)

            if execution_result.get("success", False):
                task.status = AgentStatus.COMPLETED
                task.result = execution_result.get("result")
                task.completed_at = datetime.now()
                task.execution_time = (task.completed_at - task.started_at).total_seconds()

                # Update agent metrics
                agent.average_execution_time = (
                    (agent.average_execution_time + task.execution_time) / 2
                    if agent.average_execution_time > 0
                    else task.execution_time
                )

                self.completed_tasks.append(task)
                self.logger.info(f"Task {task.id} completed successfully")

            else:
                task.status = AgentStatus.FAILED
                task.error = execution_result.get("error", "Unknown error")
                task.completed_at = datetime.now()

                # Retry logic
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    task.status = AgentStatus.IDLE
                    self.task_queue.append(task)
                    self.logger.warning(f"Task {task.id} failed, retrying ({task.retry_count}/{task.max_retries})")
                else:
                    self.failed_tasks.append(task)
                    self.logger.error(f"Task {task.id} failed permanently: {task.error}")

        except Exception as e:
            task.status = AgentStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()
            self.failed_tasks.append(task)
            self.logger.error(f"Task {task.id} execution error: {e}", exc_info=True)

        finally:
            if task.id in self.active_tasks:
                del self.active_tasks[task.id]
            agent.status = AgentStatus.IDLE

    async def _invoke_agent(self, task: Task) -> Dict[str, Any]:
        """Invoke agent to execute task (placeholder for actual implementation)"""
        # This is a simulation - replace with actual agent invocation logic
        agent_name = task.agent
        action = task.action
        parameters = task.parameters

        # Simulate execution time based on agent and action complexity
        base_time = {
            "DATABASE": 5.0,
            "OPTIMIZER": 3.0,
            "TESTBED": 4.0,
            "INFRASTRUCTURE": 6.0,
            "DATASCIENCE": 8.0,
            "MLOPS": 7.0
        }.get(agent_name, 2.0)

        execution_time = base_time + (len(str(parameters)) * 0.01)
        await asyncio.sleep(min(execution_time, 10.0))  # Cap at 10 seconds for simulation

        # Simulate success/failure (95% success rate)
        import random
        success = random.random() > 0.05

        if success:
            return {
                "success": True,
                "result": f"Completed {action} for {agent_name}",
                "execution_time": execution_time,
                "parameters": parameters
            }
        else:
            return {
                "success": False,
                "error": f"Simulated failure in {action}",
                "execution_time": execution_time
            }

    async def _check_agent_health(self, agent: AgentMetadata):
        """Check agent health and update status"""
        try:
            # Placeholder for actual health check
            agent.last_health_check = datetime.now()
            # In real implementation, this would ping the agent service

        except Exception as e:
            self.logger.warning(f"Health check failed for agent {agent.name}: {e}")

    async def _update_system_metrics(self):
        """Update system performance metrics"""
        with self._metrics_lock:
            self.metrics.total_workflows = len(self.workflows)
            self.metrics.active_workflows = len([w for w in self.workflows.values()
                                                if w.status == WorkflowStatus.RUNNING])
            self.metrics.completed_workflows = len([w for w in self.workflows.values()
                                                   if w.status == WorkflowStatus.COMPLETED])
            self.metrics.failed_workflows = len([w for w in self.workflows.values()
                                                if w.status == WorkflowStatus.FAILED])

            self.metrics.total_tasks = len(self.completed_tasks) + len(self.failed_tasks) + len(self.active_tasks)
            self.metrics.completed_tasks = len(self.completed_tasks)
            self.metrics.failed_tasks = len(self.failed_tasks)

            if self.completed_tasks:
                self.metrics.average_task_duration = sum(t.execution_time for t in self.completed_tasks) / len(self.completed_tasks)

            self.metrics.system_load = len(self.active_tasks) / max(1, sum(a.max_concurrent_tasks for a in self.agents.values()))
            self.metrics.last_updated = datetime.now()

    async def _monitor_system_resources(self):
        """Monitor system resource utilization"""
        try:
            import psutil

            # Update resource utilization metrics
            with self._metrics_lock:
                self.metrics.resource_utilization = {
                    "cpu_percent": psutil.cpu_percent(interval=1),
                    "memory_percent": psutil.virtual_memory().percent,
                    "disk_percent": psutil.disk_usage('/').percent,
                    "network_io": {
                        "bytes_sent": psutil.net_io_counters().bytes_sent,
                        "bytes_recv": psutil.net_io_counters().bytes_recv
                    }
                }

        except ImportError:
            # psutil not available, use placeholder values
            self.metrics.resource_utilization = {
                "cpu_percent": 50.0,
                "memory_percent": 60.0,
                "disk_percent": 40.0
            }

    async def _optimize_resource_allocation(self):
        """Optimize resource allocation based on current load"""
        # Placeholder for resource optimization logic
        current_load = self.metrics.system_load

        if current_load > 0.8:
            self.logger.warning(f"High system load detected: {current_load:.2f}")
            # Could implement load balancing, task throttling, etc.

        elif current_load < 0.3:
            self.logger.info(f"Low system load: {current_load:.2f} - could increase parallel tasks")

    async def _notify_workflow_submitted(self, workflow: Workflow):
        """Send notification when workflow is submitted"""
        if self.notification_manager:
            message = f"Workflow '{workflow.name}' submitted for execution"
            await self.notification_manager.send_async(message)

    async def _notify_workflow_started(self, workflow: Workflow):
        """Send notification when workflow starts"""
        if self.notification_manager:
            message = f"Workflow '{workflow.name}' started execution"
            await self.notification_manager.send_async(message)

    async def _notify_workflow_completed(self, workflow: Workflow):
        """Send notification when workflow completes"""
        if self.notification_manager:
            duration = workflow.actual_duration.total_seconds() if workflow.actual_duration else 0
            message = f"Workflow '{workflow.name}' completed successfully in {duration:.1f} seconds"
            await self.notification_manager.send_async(message)

    async def _notify_workflow_failed(self, workflow: Workflow):
        """Send notification when workflow fails"""
        if self.notification_manager:
            failed_tasks = [t for t in workflow.tasks if t.status == AgentStatus.FAILED]
            message = f"Workflow '{workflow.name}' failed with {len(failed_tasks)} failed tasks"
            await self.notification_manager.send_async(message)


# CLI Interface for the Orchestrator
async def main():
    """Main entry point for the orchestrator"""
    import argparse

    parser = argparse.ArgumentParser(description="SPECTRA Multi-Agent Orchestrator")
    parser.add_argument("--config", default="spectra_config.json", help="Configuration file path")
    parser.add_argument("--db", default="spectra.db", help="Database file path")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--workflow", help="Submit a specific workflow (phase1, phase2, phase3, phase4)")
    parser.add_argument("--status", action="store_true", help="Show system status")
    parser.add_argument("--metrics", action="store_true", help="Show system metrics")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")

    args = parser.parse_args()

    # Initialize orchestrator
    orchestrator = SpectraOrchestrator(
        config_path=args.config,
        db_path=args.db,
        log_level=args.log_level
    )

    if not await orchestrator.initialize():
        print("Failed to initialize orchestrator")
        return 1

    # Handle different modes
    if args.status:
        print("SPECTRA Orchestrator Status:")
        print(f"Agents loaded: {len(orchestrator.agents)}")
        print(f"Workflows available: {len(orchestrator.workflows)}")
        print(f"System ready: {'Yes' if orchestrator.config else 'No'}")
        return 0

    elif args.metrics:
        metrics = await orchestrator.get_system_metrics()
        print(json.dumps(metrics, indent=2, default=str))
        return 0

    elif args.workflow:
        workflow_id = f"phase{args.workflow}_" + ("foundation" if args.workflow == "1" else
                                                   "advanced" if args.workflow == "2" else
                                                   "production" if args.workflow == "3" else
                                                   "optimization")

        if workflow_id in orchestrator.workflows:
            await orchestrator.submit_workflow(orchestrator.workflows[workflow_id])
            print(f"Submitted workflow: {workflow_id}")

            if not args.daemon:
                # Start orchestration and wait for completion
                task = asyncio.create_task(orchestrator.start_orchestration())

                # Setup signal handlers for graceful shutdown
                def signal_handler():
                    asyncio.create_task(orchestrator.stop_orchestration())

                signal.signal(signal.SIGINT, lambda s, f: signal_handler())
                signal.signal(signal.SIGTERM, lambda s, f: signal_handler())

                await task
        else:
            print(f"Workflow not found: {workflow_id}")
            return 1

    elif args.daemon:
        print("Starting SPECTRA Orchestrator in daemon mode...")

        # Setup signal handlers for graceful shutdown
        def signal_handler():
            asyncio.create_task(orchestrator.stop_orchestration())

        signal.signal(signal.SIGINT, lambda s, f: signal_handler())
        signal.signal(signal.SIGTERM, lambda s, f: signal_handler())

        await orchestrator.start_orchestration()

    else:
        print("No action specified. Use --help for usage information.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))