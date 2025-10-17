#!/usr/bin/env python3
"""
SPECTRA Real-Time Coordination Interface
=======================================

Advanced real-time coordination interface for monitoring and managing agent
interactions, communication flows, task execution, and system performance
across the multi-agent SPECTRA implementation.

Features:
- Real-time agent status monitoring with live updates
- Interactive communication flow visualization
- Task execution tracking with dependency mapping
- Performance metrics dashboard with predictive analytics
- Alert system for coordination issues and bottlenecks
- Interactive agent control and task management
- Communication pattern analysis and optimization
- System health monitoring with automated recovery

Author: PYTHON-INTERNAL Agent - Elite Python execution environment specialist
Date: September 18, 2025
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict, deque
import uuid

# Real-time processing and visualization
try:
    import pandas as pd
    import numpy as np
    from plotly import graph_objects as go
    from plotly.subplots import make_subplots
    import networkx as nx
    ANALYTICS_AVAILABLE = True
except ImportError:
    ANALYTICS_AVAILABLE = False
    # Mock go.Figure for type hints when analytics packages are not available
    class MockFigure:
        pass
    class MockGo:
        Figure = MockFigure
    go = MockGo()

# SPECTRA imports
from .spectra_orchestrator import SpectraOrchestrator, AgentStatus, WorkflowStatus, Priority
from .agent_optimization_engine import AgentOptimizationEngine


class MessageType(Enum):
    """Types of coordination messages"""
    TASK_ASSIGNMENT = "task_assignment"
    STATUS_UPDATE = "status_update"
    RESULT_DELIVERY = "result_delivery"
    ERROR_REPORT = "error_report"
    COORDINATION_REQUEST = "coordination_request"
    RESOURCE_REQUEST = "resource_request"
    HEARTBEAT = "heartbeat"
    ALERT = "alert"


class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class CoordinationState(Enum):
    """Overall coordination system state"""
    OPTIMAL = "optimal"
    GOOD = "good"
    WARNING = "warning"
    DEGRADED = "degraded"
    CRITICAL = "critical"


@dataclass
class CoordinationMessage:
    """Real-time coordination message"""
    id: str
    timestamp: datetime
    sender: str
    receiver: Optional[str]
    message_type: MessageType
    content: Dict[str, Any]
    priority: Priority
    status: str = "pending"
    response_time: Optional[float] = None
    processing_time: Optional[float] = None


@dataclass
class AgentHealthMetrics:
    """Comprehensive agent health metrics"""
    agent_name: str
    status: AgentStatus
    last_heartbeat: datetime
    response_time_avg: float
    response_time_p95: float
    success_rate: float
    error_count: int
    active_tasks: int
    queue_length: int
    cpu_usage: float
    memory_usage: float
    network_latency: float
    coordination_score: float
    health_score: float


@dataclass
class TaskExecutionTrace:
    """Task execution trace for monitoring"""
    task_id: str
    agent: str
    start_time: datetime
    end_time: Optional[datetime]
    status: str
    progress: float
    dependencies: List[str]
    dependents: List[str]
    estimated_completion: Optional[datetime]
    actual_duration: Optional[timedelta]
    resource_usage: Dict[str, Any]
    error_messages: List[str]


@dataclass
class CoordinationAlert:
    """System coordination alert"""
    id: str
    timestamp: datetime
    level: AlertLevel
    category: str
    message: str
    affected_agents: List[str]
    suggested_actions: List[str]
    auto_resolved: bool = False
    resolution_time: Optional[datetime] = None


@dataclass
class CommunicationPattern:
    """Communication pattern analysis"""
    source_agent: str
    target_agent: str
    message_count: int
    avg_response_time: float
    success_rate: float
    last_interaction: datetime
    interaction_frequency: float
    bandwidth_usage: float
    pattern_type: str  # frequent, occasional, rare, problematic


class CoordinationInterface:
    """
    Advanced real-time coordination interface for monitoring and managing
    multi-agent interactions in the SPECTRA system.
    """

    def __init__(self, orchestrator: SpectraOrchestrator):
        """Initialize the coordination interface"""
        self.orchestrator = orchestrator
        self.optimization_engine = AgentOptimizationEngine(orchestrator.agents)

        # Real-time data streams
        self.coordination_messages = deque(maxlen=10000)  # Last 10k messages
        self.agent_health_metrics = {}
        self.task_execution_traces = {}
        self.coordination_alerts = deque(maxlen=1000)  # Last 1k alerts
        self.communication_patterns = {}

        # Performance tracking
        self.message_throughput = deque(maxlen=300)  # 5 minutes at 1-second intervals
        self.response_time_history = deque(maxlen=3600)  # 1 hour history
        self.error_rate_history = deque(maxlen=3600)

        # System state
        self.coordination_state = CoordinationState.OPTIMAL
        self.system_load = 0.0
        self.network_health = 1.0
        self.alert_counts = defaultdict(int)

        # Configuration
        self.monitoring_interval = 1.0  # seconds
        self.alert_thresholds = {
            'response_time_warning': 5.0,  # seconds
            'response_time_critical': 15.0,
            'error_rate_warning': 0.05,  # 5%
            'error_rate_critical': 0.15,  # 15%
            'agent_health_warning': 0.7,
            'agent_health_critical': 0.4
        }

        # Logging
        self.logger = logging.getLogger(__name__)

        # Background monitoring
        self.monitoring_active = False
        self.monitoring_task = None

    async def start_monitoring(self):
        """Start real-time monitoring"""
        if self.monitoring_active:
            return

        self.monitoring_active = True
        self.logger.info("Starting real-time coordination monitoring")

        # Initialize agent health metrics
        await self._initialize_agent_health()

        # Start monitoring task
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())

    async def stop_monitoring(self):
        """Stop real-time monitoring"""
        self.monitoring_active = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        self.logger.info("Stopped real-time coordination monitoring")

    async def _monitoring_loop(self):
        """Main monitoring loop"""
        while self.monitoring_active:
            try:
                # Collect metrics
                await self._collect_agent_metrics()
                await self._update_communication_patterns()
                await self._check_system_health()
                await self._process_alerts()

                # Update performance tracking
                self._update_performance_metrics()

                # Wait for next interval
                await asyncio.sleep(self.monitoring_interval)

            except Exception as e:
                self.logger.error(f"Monitoring loop error: {e}", exc_info=True)
                await asyncio.sleep(5)  # Longer wait on error

    async def _initialize_agent_health(self):
        """Initialize agent health metrics"""
        for agent_name, agent in self.orchestrator.agents.items():
            self.agent_health_metrics[agent_name] = AgentHealthMetrics(
                agent_name=agent_name,
                status=agent.status,
                last_heartbeat=datetime.now(),
                response_time_avg=0.5,
                response_time_p95=1.0,
                success_rate=agent.success_rate,
                error_count=0,
                active_tasks=0,
                queue_length=0,
                cpu_usage=0.0,
                memory_usage=0.0,
                network_latency=0.0,
                coordination_score=0.8,
                health_score=0.9
            )

    async def _collect_agent_metrics(self):
        """Collect real-time agent metrics"""
        current_time = datetime.now()

        for agent_name, health_metrics in self.agent_health_metrics.items():
            agent = self.orchestrator.agents.get(agent_name)
            if not agent:
                continue

            # Update basic metrics
            health_metrics.status = agent.status
            health_metrics.last_heartbeat = current_time

            # Calculate active tasks
            active_tasks = [t for t in self.orchestrator.active_tasks.values()
                          if t.agent == agent_name]
            health_metrics.active_tasks = len(active_tasks)

            # Calculate queue length
            queued_tasks = [t for t in self.orchestrator.task_queue
                          if t.agent == agent_name]
            health_metrics.queue_length = len(queued_tasks)

            # Update success rate
            health_metrics.success_rate = agent.success_rate

            # Simulate resource metrics (would be real in production)
            health_metrics.cpu_usage = min(100.0, health_metrics.active_tasks * 20.0)
            health_metrics.memory_usage = min(100.0, health_metrics.active_tasks * 15.0)
            health_metrics.network_latency = np.random.normal(10.0, 2.0)  # ms

            # Calculate coordination score
            health_metrics.coordination_score = self._calculate_coordination_score(agent_name)

            # Calculate overall health score
            health_metrics.health_score = self._calculate_health_score(health_metrics)

    def _calculate_coordination_score(self, agent_name: str) -> float:
        """Calculate agent coordination effectiveness score"""
        # Base score from success rate
        base_score = self.orchestrator.agents[agent_name].success_rate

        # Adjust for communication effectiveness
        comm_patterns = [p for p in self.communication_patterns.values()
                        if p.source_agent == agent_name or p.target_agent == agent_name]

        if comm_patterns:
            avg_response_time = np.mean([p.avg_response_time for p in comm_patterns])
            avg_success_rate = np.mean([p.success_rate for p in comm_patterns])

            # Lower response time and higher success rate improve score
            time_factor = max(0.1, 1.0 - (avg_response_time - 1.0) / 10.0)
            success_factor = avg_success_rate

            coordination_score = base_score * time_factor * success_factor
        else:
            coordination_score = base_score

        return min(1.0, max(0.0, coordination_score))

    def _calculate_health_score(self, metrics: AgentHealthMetrics) -> float:
        """Calculate overall agent health score"""
        # Component scores
        availability_score = 1.0 if metrics.status == AgentStatus.RUNNING else 0.0
        performance_score = min(1.0, 2.0 - metrics.response_time_avg / 5.0)  # Penalty for slow response
        reliability_score = metrics.success_rate
        load_score = max(0.0, 1.0 - metrics.cpu_usage / 100.0)  # Penalty for high CPU
        coordination_score = metrics.coordination_score

        # Weighted combination
        health_score = (
            availability_score * 0.3 +
            performance_score * 0.2 +
            reliability_score * 0.2 +
            load_score * 0.15 +
            coordination_score * 0.15
        )

        return min(1.0, max(0.0, health_score))

    async def _update_communication_patterns(self):
        """Update communication pattern analysis"""
        # Analyze recent messages for patterns
        recent_messages = [msg for msg in self.coordination_messages
                         if (datetime.now() - msg.timestamp).total_seconds() < 300]  # Last 5 minutes

        # Group by agent pairs
        agent_pairs = defaultdict(list)
        for msg in recent_messages:
            if msg.receiver:
                pair_key = f"{msg.sender}->{msg.receiver}"
                agent_pairs[pair_key].append(msg)

        # Update patterns
        for pair_key, messages in agent_pairs.items():
            sender, receiver = pair_key.split("->")

            if pair_key not in self.communication_patterns:
                self.communication_patterns[pair_key] = CommunicationPattern(
                    source_agent=sender,
                    target_agent=receiver,
                    message_count=0,
                    avg_response_time=0.0,
                    success_rate=1.0,
                    last_interaction=datetime.now(),
                    interaction_frequency=0.0,
                    bandwidth_usage=0.0,
                    pattern_type="occasional"
                )

            pattern = self.communication_patterns[pair_key]
            pattern.message_count = len(messages)
            pattern.last_interaction = max(msg.timestamp for msg in messages)

            # Calculate response times
            response_times = [msg.response_time for msg in messages if msg.response_time]
            if response_times:
                pattern.avg_response_time = np.mean(response_times)

            # Calculate success rate
            successful_messages = [msg for msg in messages if msg.status == "completed"]
            pattern.success_rate = len(successful_messages) / len(messages) if messages else 1.0

            # Update pattern type
            pattern.pattern_type = self._classify_communication_pattern(pattern)

    def _classify_communication_pattern(self, pattern: CommunicationPattern) -> str:
        """Classify communication pattern type"""
        if pattern.message_count > 50:  # High frequency
            if pattern.avg_response_time > 5.0 or pattern.success_rate < 0.8:
                return "problematic"
            else:
                return "frequent"
        elif pattern.message_count > 10:
            return "occasional"
        else:
            return "rare"

    async def _check_system_health(self):
        """Check overall system health and generate alerts"""
        current_time = datetime.now()

        # Check agent health
        for agent_name, metrics in self.agent_health_metrics.items():
            # Response time alerts
            if metrics.response_time_avg > self.alert_thresholds['response_time_critical']:
                await self._create_alert(
                    AlertLevel.CRITICAL,
                    "performance",
                    f"Agent {agent_name} response time critical: {metrics.response_time_avg:.2f}s",
                    [agent_name],
                    ["Check agent load", "Restart agent if necessary", "Scale resources"]
                )
            elif metrics.response_time_avg > self.alert_thresholds['response_time_warning']:
                await self._create_alert(
                    AlertLevel.WARNING,
                    "performance",
                    f"Agent {agent_name} response time high: {metrics.response_time_avg:.2f}s",
                    [agent_name],
                    ["Monitor agent performance", "Consider load balancing"]
                )

            # Health score alerts
            if metrics.health_score < self.alert_thresholds['agent_health_critical']:
                await self._create_alert(
                    AlertLevel.CRITICAL,
                    "health",
                    f"Agent {agent_name} health critical: {metrics.health_score:.2f}",
                    [agent_name],
                    ["Immediate investigation required", "Consider agent restart"]
                )
            elif metrics.health_score < self.alert_thresholds['agent_health_warning']:
                await self._create_alert(
                    AlertLevel.WARNING,
                    "health",
                    f"Agent {agent_name} health degraded: {metrics.health_score:.2f}",
                    [agent_name],
                    ["Monitor closely", "Check resource availability"]
                )

        # Check communication patterns
        for pattern in self.communication_patterns.values():
            if pattern.pattern_type == "problematic":
                await self._create_alert(
                    AlertLevel.WARNING,
                    "communication",
                    f"Problematic communication pattern: {pattern.source_agent} -> {pattern.target_agent}",
                    [pattern.source_agent, pattern.target_agent],
                    ["Investigate communication issues", "Check network connectivity"]
                )

        # Update overall coordination state
        self._update_coordination_state()

    def _update_coordination_state(self):
        """Update overall coordination system state"""
        # Calculate aggregate health metrics
        health_scores = [metrics.health_score for metrics in self.agent_health_metrics.values()]
        avg_health = np.mean(health_scores) if health_scores else 1.0
        min_health = min(health_scores) if health_scores else 1.0

        # Count problematic patterns
        problematic_patterns = len([p for p in self.communication_patterns.values()
                                  if p.pattern_type == "problematic"])

        # Count critical alerts in last hour
        one_hour_ago = datetime.now() - timedelta(hours=1)
        recent_critical_alerts = len([a for a in self.coordination_alerts
                                    if a.timestamp > one_hour_ago and a.level == AlertLevel.CRITICAL])

        # Determine coordination state
        if min_health < 0.4 or recent_critical_alerts > 5:
            self.coordination_state = CoordinationState.CRITICAL
        elif min_health < 0.6 or avg_health < 0.7 or recent_critical_alerts > 2:
            self.coordination_state = CoordinationState.DEGRADED
        elif problematic_patterns > 3 or avg_health < 0.8:
            self.coordination_state = CoordinationState.WARNING
        elif avg_health > 0.9 and problematic_patterns == 0:
            self.coordination_state = CoordinationState.OPTIMAL
        else:
            self.coordination_state = CoordinationState.GOOD

    async def _create_alert(self,
                          level: AlertLevel,
                          category: str,
                          message: str,
                          affected_agents: List[str],
                          suggested_actions: List[str]):
        """Create a new coordination alert"""
        alert = CoordinationAlert(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            level=level,
            category=category,
            message=message,
            affected_agents=affected_agents,
            suggested_actions=suggested_actions
        )

        self.coordination_alerts.append(alert)
        self.alert_counts[level.value] += 1

        # Log alert
        self.logger.warning(f"Coordination Alert [{level.value.upper()}]: {message}")

    async def _process_alerts(self):
        """Process and potentially auto-resolve alerts"""
        for alert in self.coordination_alerts:
            if not alert.auto_resolved and alert.level in [AlertLevel.INFO, AlertLevel.WARNING]:
                # Check if conditions have improved
                if await self._check_alert_resolution(alert):
                    alert.auto_resolved = True
                    alert.resolution_time = datetime.now()

    async def _check_alert_resolution(self, alert: CoordinationAlert) -> bool:
        """Check if an alert can be auto-resolved"""
        if alert.category == "performance":
            # Check if performance has improved
            for agent_name in alert.affected_agents:
                metrics = self.agent_health_metrics.get(agent_name)
                if metrics and metrics.response_time_avg > self.alert_thresholds['response_time_warning']:
                    return False
            return True

        elif alert.category == "health":
            # Check if health has improved
            for agent_name in alert.affected_agents:
                metrics = self.agent_health_metrics.get(agent_name)
                if metrics and metrics.health_score < self.alert_thresholds['agent_health_warning']:
                    return False
            return True

        return False

    def _update_performance_metrics(self):
        """Update system performance metrics"""
        current_time = time.time()

        # Message throughput (messages per second)
        recent_messages = [msg for msg in self.coordination_messages
                         if (datetime.now() - msg.timestamp).total_seconds() < 1.0]
        self.message_throughput.append(len(recent_messages))

        # Average response time
        recent_response_times = [msg.response_time for msg in self.coordination_messages
                               if msg.response_time and (datetime.now() - msg.timestamp).total_seconds() < 60]
        avg_response_time = np.mean(recent_response_times) if recent_response_times else 0.0
        self.response_time_history.append(avg_response_time)

        # Error rate
        recent_errors = [msg for msg in self.coordination_messages
                       if msg.status == "error" and (datetime.now() - msg.timestamp).total_seconds() < 60]
        total_recent_messages = [msg for msg in self.coordination_messages
                               if (datetime.now() - msg.timestamp).total_seconds() < 60]
        error_rate = len(recent_errors) / max(1, len(total_recent_messages))
        self.error_rate_history.append(error_rate)

    def add_coordination_message(self, message: CoordinationMessage):
        """Add a coordination message to the monitoring system"""
        self.coordination_messages.append(message)

        # Update task execution traces if it's a task-related message
        if message.message_type == MessageType.TASK_ASSIGNMENT:
            task_id = message.content.get('task_id')
            if task_id:
                self.task_execution_traces[task_id] = TaskExecutionTrace(
                    task_id=task_id,
                    agent=message.receiver or message.sender,
                    start_time=message.timestamp,
                    end_time=None,
                    status="assigned",
                    progress=0.0,
                    dependencies=message.content.get('dependencies', []),
                    dependents=[],
                    estimated_completion=None,
                    actual_duration=None,
                    resource_usage={},
                    error_messages=[]
                )

    def get_real_time_status(self) -> Dict[str, Any]:
        """Get comprehensive real-time system status"""
        current_time = datetime.now()

        # Agent status summary
        agent_status_counts = defaultdict(int)
        for metrics in self.agent_health_metrics.values():
            agent_status_counts[metrics.status.value] += 1

        # Communication statistics
        active_communications = len([p for p in self.communication_patterns.values()
                                   if (current_time - p.last_interaction).total_seconds() < 300])

        # Recent alerts
        recent_alerts = [a for a in self.coordination_alerts
                        if (current_time - a.timestamp).total_seconds() < 3600]  # Last hour

        return {
            'coordination_state': self.coordination_state.value,
            'timestamp': current_time.isoformat(),
            'system_metrics': {
                'total_agents': len(self.agent_health_metrics),
                'active_agents': agent_status_counts.get('running', 0),
                'avg_health_score': np.mean([m.health_score for m in self.agent_health_metrics.values()]),
                'message_throughput': list(self.message_throughput)[-10:],  # Last 10 readings
                'avg_response_time': np.mean(list(self.response_time_history)[-60:]) if self.response_time_history else 0.0,
                'error_rate': np.mean(list(self.error_rate_history)[-60:]) if self.error_rate_history else 0.0,
                'active_communications': active_communications,
                'coordination_score': self._calculate_overall_coordination_score()
            },
            'agent_health': {
                agent_name: {
                    'status': metrics.status.value,
                    'health_score': metrics.health_score,
                    'response_time': metrics.response_time_avg,
                    'active_tasks': metrics.active_tasks,
                    'success_rate': metrics.success_rate,
                    'last_heartbeat': metrics.last_heartbeat.isoformat()
                }
                for agent_name, metrics in self.agent_health_metrics.items()
            },
            'communication_patterns': {
                pattern_id: {
                    'source': pattern.source_agent,
                    'target': pattern.target_agent,
                    'message_count': pattern.message_count,
                    'avg_response_time': pattern.avg_response_time,
                    'success_rate': pattern.success_rate,
                    'pattern_type': pattern.pattern_type,
                    'last_interaction': pattern.last_interaction.isoformat()
                }
                for pattern_id, pattern in self.communication_patterns.items()
            },
            'recent_alerts': [
                {
                    'id': alert.id,
                    'timestamp': alert.timestamp.isoformat(),
                    'level': alert.level.value,
                    'category': alert.category,
                    'message': alert.message,
                    'affected_agents': alert.affected_agents,
                    'auto_resolved': alert.auto_resolved
                }
                for alert in recent_alerts
            ],
            'task_execution': {
                task_id: {
                    'agent': trace.agent,
                    'status': trace.status,
                    'progress': trace.progress,
                    'start_time': trace.start_time.isoformat(),
                    'estimated_completion': trace.estimated_completion.isoformat() if trace.estimated_completion else None
                }
                for task_id, trace in list(self.task_execution_traces.items())[-50:]  # Last 50 tasks
            }
        }

    def _calculate_overall_coordination_score(self) -> float:
        """Calculate overall coordination effectiveness score"""
        if not self.agent_health_metrics:
            return 0.0

        # Component scores
        health_scores = [m.health_score for m in self.agent_health_metrics.values()]
        coordination_scores = [m.coordination_score for m in self.agent_health_metrics.values()]

        avg_health = np.mean(health_scores)
        avg_coordination = np.mean(coordination_scores)

        # Communication effectiveness
        successful_patterns = len([p for p in self.communication_patterns.values()
                                 if p.success_rate > 0.8 and p.avg_response_time < 3.0])
        total_patterns = max(1, len(self.communication_patterns))
        communication_effectiveness = successful_patterns / total_patterns

        # Alert penalty
        recent_alerts = len([a for a in self.coordination_alerts
                           if (datetime.now() - a.timestamp).total_seconds() < 3600
                           and a.level in [AlertLevel.ERROR, AlertLevel.CRITICAL]])
        alert_penalty = max(0.0, 1.0 - recent_alerts * 0.1)

        # Overall score
        overall_score = (
            avg_health * 0.3 +
            avg_coordination * 0.3 +
            communication_effectiveness * 0.2 +
            alert_penalty * 0.2
        )

        return min(1.0, max(0.0, overall_score))

    def create_coordination_visualization(self) -> Optional[go.Figure]:
        """Create real-time coordination visualization"""
        if not ANALYTICS_AVAILABLE:
            return None

        # Create subplots
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                "Agent Health Status", "Communication Network",
                "Performance Metrics", "Alert Timeline"
            ),
            specs=[
                [{"type": "bar"}, {"type": "scatter"}],
                [{"type": "scatter"}, {"type": "bar"}]
            ]
        )

        # Agent Health Status
        agent_names = list(self.agent_health_metrics.keys())
        health_scores = [self.agent_health_metrics[name].health_score for name in agent_names]

        fig.add_trace(
            go.Bar(
                x=agent_names,
                y=health_scores,
                name="Health Score",
                marker_color=['#2ecc71' if score > 0.8 else '#f39c12' if score > 0.6 else '#e74c3c'
                            for score in health_scores]
            ),
            row=1, col=1
        )

        # Communication Network (simplified visualization)
        if self.communication_patterns:
            sources = [p.source_agent for p in self.communication_patterns.values()]
            targets = [p.target_agent for p in self.communication_patterns.values()]
            response_times = [p.avg_response_time for p in self.communication_patterns.values()]

            fig.add_trace(
                go.Scatter(
                    x=list(range(len(sources))),
                    y=response_times,
                    mode='markers',
                    name="Communication Response Time",
                    marker=dict(
                        size=10,
                        color=response_times,
                        colorscale='RdYlGn_r',
                        showscale=True
                    ),
                    text=[f"{s} -> {t}" for s, t in zip(sources, targets)],
                    hovertemplate="<b>%{text}</b><br>Response Time: %{y:.2f}s<extra></extra>"
                ),
                row=1, col=2
            )

        # Performance Metrics
        if self.response_time_history:
            time_points = list(range(len(self.response_time_history)))[-60:]  # Last 60 points
            response_times = list(self.response_time_history)[-60:]

            fig.add_trace(
                go.Scatter(
                    x=time_points,
                    y=response_times,
                    mode='lines',
                    name="Avg Response Time",
                    line=dict(color='#3498db')
                ),
                row=2, col=1
            )

        # Alert Timeline
        if self.coordination_alerts:
            alert_levels = [alert.level.value for alert in list(self.coordination_alerts)[-20:]]
            alert_counts = defaultdict(int)
            for level in alert_levels:
                alert_counts[level] += 1

            fig.add_trace(
                go.Bar(
                    x=list(alert_counts.keys()),
                    y=list(alert_counts.values()),
                    name="Alert Count",
                    marker_color=['#3498db', '#f39c12', '#e74c3c', '#8e44ad']
                ),
                row=2, col=2
            )

        # Update layout
        fig.update_layout(
            height=800,
            title_text="Real-Time Coordination Dashboard",
            showlegend=False
        )

        return fig

    def generate_coordination_html(self) -> str:
        """Generate HTML template for coordination interface"""
        status = self.get_real_time_status()
        visualization = self.create_coordination_visualization()

        viz_html = visualization.to_html(include_plotlyjs=True) if visualization else "<p>Visualization not available</p>"

        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPECTRA Real-Time Coordination Interface</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body {{ font-family: 'Inter', sans-serif; margin: 0; padding: 20px; background-color: #f8fafc; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .status-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .status-card {{ background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
        .status-value {{ font-size: 2em; font-weight: bold; }}
        .status-optimal {{ color: #2ecc71; }}
        .status-good {{ color: #3498db; }}
        .status-warning {{ color: #f39c12; }}
        .status-degraded {{ color: #e67e22; }}
        .status-critical {{ color: #e74c3c; }}
        .visualization-container {{ background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .agent-list {{ max-height: 400px; overflow-y: auto; }}
        .agent-item {{ display: flex; justify-content: space-between; align-items: center; padding: 10px; border-bottom: 1px solid #eee; }}
        .health-bar {{ width: 100px; height: 10px; background: #ecf0f1; border-radius: 5px; overflow: hidden; }}
        .health-fill {{ height: 100%; transition: width 0.3s ease; }}
        .alert-item {{ padding: 10px; margin: 5px 0; border-radius: 5px; }}
        .alert-critical {{ background: #fdf2f2; border-left: 4px solid #e74c3c; }}
        .alert-warning {{ background: #fefdf2; border-left: 4px solid #f39c12; }}
        .alert-info {{ background: #f2f8fd; border-left: 4px solid #3498db; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>SPECTRA Real-Time Coordination Interface</h1>
        <p>Live monitoring and management of multi-agent coordination</p>
    </div>

    <div class="status-grid">
        <div class="status-card">
            <div>Coordination State</div>
            <div class="status-value status-{status['coordination_state']}">{status['coordination_state'].title()}</div>
        </div>
        <div class="status-card">
            <div>Active Agents</div>
            <div class="status-value">{status['system_metrics']['active_agents']}/{status['system_metrics']['total_agents']}</div>
        </div>
        <div class="status-card">
            <div>Avg Health Score</div>
            <div class="status-value">{status['system_metrics']['avg_health_score']:.2f}</div>
        </div>
        <div class="status-card">
            <div>Message Throughput</div>
            <div class="status-value">{status['system_metrics']['message_throughput'][-1] if status['system_metrics']['message_throughput'] else 0} msg/s</div>
        </div>
        <div class="status-card">
            <div>Avg Response Time</div>
            <div class="status-value">{status['system_metrics']['avg_response_time']:.2f}s</div>
        </div>
        <div class="status-card">
            <div>Error Rate</div>
            <div class="status-value">{status['system_metrics']['error_rate']:.1%}</div>
        </div>
    </div>

    <div class="visualization-container">
        <h2>Real-Time Coordination Dashboard</h2>
        {viz_html}
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px;">
        <div class="visualization-container">
            <h3>Agent Health Status</h3>
            <div class="agent-list">
                {''.join([f'''
                <div class="agent-item">
                    <div>
                        <strong>{agent_name}</strong>
                        <br><small>{agent_data["status"]}</small>
                    </div>
                    <div>
                        <div class="health-bar">
                            <div class="health-fill" style="width: {agent_data["health_score"]*100}%; background: {'#2ecc71' if agent_data['health_score'] > 0.8 else '#f39c12' if agent_data['health_score'] > 0.6 else '#e74c3c'};"></div>
                        </div>
                        <small>{agent_data["health_score"]:.2f}</small>
                    </div>
                </div>
                ''' for agent_name, agent_data in status['agent_health'].items()])}
            </div>
        </div>

        <div class="visualization-container">
            <h3>Recent Alerts</h3>
            <div class="agent-list">
                {''.join([f'''
                <div class="alert-item alert-{alert["level"]}">
                    <div><strong>{alert["level"].upper()}</strong> - {alert["category"]}</div>
                    <div>{alert["message"]}</div>
                    <small>{alert["timestamp"][:16]} - Agents: {", ".join(alert["affected_agents"])}</small>
                </div>
                ''' for alert in status['recent_alerts'][:10]])}
            </div>
        </div>
    </div>

    <script>
        // Auto-refresh every 5 seconds
        setInterval(function() {{
            location.reload();
        }}, 5000);
    </script>
</body>
</html>
        """


# Example usage and testing
async def main():
    """Example usage of the coordination interface"""
    print("SPECTRA Real-Time Coordination Interface")
    print("=" * 50)

    # Mock orchestrator for testing
    from .spectra_orchestrator import SpectraOrchestrator

    # Create mock orchestrator
    orchestrator = SpectraOrchestrator()
    await orchestrator.initialize()

    # Create coordination interface
    interface = CoordinationInterface(orchestrator)

    # Start monitoring
    await interface.start_monitoring()

    # Simulate some coordination messages
    for i in range(10):
        message = CoordinationMessage(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            sender=f"AGENT_{i % 3}",
            receiver=f"AGENT_{(i + 1) % 3}",
            message_type=MessageType.TASK_ASSIGNMENT,
            content={"task_id": f"task_{i}", "action": "test_action"},
            priority=Priority.MEDIUM,
            response_time=np.random.normal(2.0, 0.5)
        )
        interface.add_coordination_message(message)

    # Wait for some monitoring cycles
    await asyncio.sleep(3)

    # Get status
    status = interface.get_real_time_status()
    print(f"Coordination State: {status['coordination_state']}")
    print(f"Active Agents: {status['system_metrics']['active_agents']}")
    print(f"Health Score: {status['system_metrics']['avg_health_score']:.2f}")

    # Generate HTML
    html = interface.generate_coordination_html()
    with open("/tmp/coordination_interface.html", "w") as f:
        f.write(html)
    print("Coordination interface HTML saved to /tmp/coordination_interface.html")

    # Stop monitoring
    await interface.stop_monitoring()


if __name__ == "__main__":
    asyncio.run(main())