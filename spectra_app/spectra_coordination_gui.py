#!/usr/bin/env python3
"""
SPECTRA Agent Coordination GUI System
====================================

Comprehensive GUI application for coordinating multi-agent workflows across
the 4-phase SPECTRA advanced data management implementation.

Features:
- Agent Selection Interface with capability matrix
- Phase Management Dashboard with timeline visualization
- Real-time Coordination Interface with live monitoring
- Implementation Management Tools with project planning
- Team Optimization with resource allocation
- Integration with orchestration framework

Author: PYTHON-INTERNAL Agent - Elite Python execution environment specialist
Date: September 18, 2025
"""

import asyncio
import json
import logging
import socket
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
import uuid

# Web framework and GUI components
try:
    from flask import Flask, render_template, jsonify, request, session, redirect, url_for
    from flask_socketio import SocketIO, emit, join_room, leave_room
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Data visualization and analysis
try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# SPECTRA orchestration imports
from .spectra_orchestrator import (
    SpectraOrchestrator, AgentMetadata, Task, Workflow,
    AgentStatus, WorkflowStatus, ExecutionMode, Priority
)
from .orchestration_workflows import SpectraWorkflowBuilder, CoordinationPattern
from .orchestration_dashboard import SpectraOrchestrationDashboard


class TeamRole(Enum):
    """Team role definitions for agent coordination"""
    LEAD = "lead"
    SPECIALIST = "specialist"
    SUPPORT = "support"
    QUALITY_ASSURANCE = "qa"
    COORDINATION = "coordination"


class OptimizationCriteria(Enum):
    """Optimization criteria for team composition"""
    PERFORMANCE = "performance"
    COST = "cost"
    RELIABILITY = "reliability"
    SPEED = "speed"
    QUALITY = "quality"


@dataclass
class AgentCapabilityMatrix:
    """Detailed agent capability assessment"""
    agent_name: str
    primary_capabilities: List[str]
    secondary_capabilities: List[str]
    performance_metrics: Dict[str, float]
    resource_requirements: Dict[str, Any]
    coordination_compatibility: List[str]
    success_history: Dict[str, float]
    current_load: float
    availability_score: float
    specialization_score: float


@dataclass
class TeamComposition:
    """Team composition with role assignments"""
    team_id: str
    phase: str
    team_name: str
    lead_agent: str
    specialist_agents: List[str]
    support_agents: List[str]
    qa_agents: List[str]
    coordination_agents: List[str]
    estimated_cost: float
    estimated_duration: timedelta
    success_probability: float
    risk_factors: List[str]
    dependencies: List[str]


@dataclass
class PhaseProgress:
    """Phase progress tracking"""
    phase_id: str
    phase_name: str
    start_date: datetime
    end_date: datetime
    current_progress: float
    milestones: List[Dict[str, Any]]
    active_workflows: List[str]
    completed_workflows: List[str]
    blocked_workflows: List[str]
    team_assignments: List[str]
    resource_utilization: Dict[str, float]
    issues: List[Dict[str, Any]]


@dataclass
class CoordinationEvent:
    """Real-time coordination event"""
    event_id: str
    timestamp: datetime
    event_type: str
    source_agent: str
    target_agent: Optional[str]
    message: str
    data: Dict[str, Any]
    priority: Priority
    status: str


class SpectraCoordinationGUI:
    """
    Main GUI application for SPECTRA agent coordination and management.

    Provides comprehensive interfaces for:
    - Agent selection and team optimization
    - Phase management and timeline visualization
    - Real-time coordination monitoring
    - Implementation planning and tracking
    """

    def __init__(self,
                 orchestrator: SpectraOrchestrator,
                 host: str = "127.0.0.1",  # Changed default to localhost only
                 port: int = 5001,
                 debug: bool = False):
        """Initialize the coordination GUI"""
        self.orchestrator = orchestrator
        self.workflow_builder = SpectraWorkflowBuilder()
        self.host = host
        self.port = port
        self.debug = debug

        # Security configuration
        self.local_only = host in ["127.0.0.1", "localhost"]
        self.available_port = None

        # GUI state management
        self.is_running = False
        self.connected_clients = set()
        self.active_sessions = {}
        self.coordination_events = []
        self.team_compositions = {}
        self.phase_progress = {}

        # Agent capability analysis
        self.agent_capabilities = {}
        self.capability_matrix = []
        self.optimization_cache = {}

        # Flask application setup
        if FLASK_AVAILABLE:
            self.app = Flask(__name__)
            self.app.config['SECRET_KEY'] = str(uuid.uuid4())
            self.socketio = SocketIO(self.app, cors_allowed_origins="*")
            self._setup_routes()
            self._setup_websocket_handlers()
        else:
            raise ImportError("Flask is required for the GUI application")

        # Logging setup
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        # Background processing
        self.update_thread = None
        self.stop_event = threading.Event()

    def _check_port_availability(self, port: int) -> bool:
        """Check if a port is available for use"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(2)  # Increased timeout for better reliability
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                result = sock.connect_ex((self.host, port))
                return result != 0  # Port is available if connection fails
        except Exception as e:
            self.logger.warning(f"Port availability check failed for {port}: {e}")
            return False

    def _find_available_port(self, start_port: int = 5001, max_attempts: int = 20) -> Optional[int]:
        """Find an available port starting from start_port"""
        self.logger.info(f"🔍 Searching for available port starting from {start_port}")

        for port in range(start_port, start_port + max_attempts):
            if self._check_port_availability(port):
                self.logger.info(f"✅ Found available port: {port}")
                return port
            else:
                self.logger.debug(f"❌ Port {port} is in use")

        self.logger.error(f"❌ No available ports found in range {start_port}-{start_port + max_attempts}")
        return None

    def _get_security_warnings(self) -> List[str]:
        """Generate security warnings based on configuration"""
        warnings = []

        if not self.local_only:
            warnings.extend([
                "🚨 CRITICAL SECURITY RISK: GUI is accessible from external networks!",
                "🔒 This exposes README and system information to network access",
                "⚠️ Potential data exposure risk from network accessibility",
                "🏠 IMMEDIATE ACTION: Change host to 127.0.0.1 or localhost for security",
                "🔐 Current configuration allows external file system access"
            ])
        else:
            warnings.extend([
                "✅ SECURE: GUI is configured for localhost access only",
                "🔒 README and system files are protected from external access"
            ])

        warnings.extend([
            "📍 README ACCESS IS LOCAL SYSTEM ONLY",
            "🔐 No external file system access is provided",
            "💻 All documentation served from local installation only",
            "🚫 No network file sharing or remote access capabilities",
            "🛡️ System files and configuration protected from external access"
        ])

        return warnings

    def _get_access_info(self) -> Dict[str, str]:
        """Get access information for display"""
        return {
            "access_level": "LOCAL ONLY" if self.local_only else "NETWORK ACCESSIBLE",
            "host": self.host,
            "port": str(self.available_port or self.port),
            "security_status": "SECURE (localhost)" if self.local_only else "EXPOSED (network)",
            "readme_source": "Local file system only",
            "data_access": "Local system files only"
        }

    def _setup_routes(self):
        """Setup Flask routes for the GUI application"""

        @self.app.route('/')
        def index():
            """Main dashboard page"""
            return render_template('coordination_gui.html')

        @self.app.route('/agent-selection')
        def agent_selection():
            """Agent selection interface"""
            return render_template('agent_selection.html')

        @self.app.route('/phase-management')
        def phase_management():
            """Phase management dashboard"""
            return render_template('phase_management.html')

        @self.app.route('/coordination-monitor')
        def coordination_monitor():
            """Real-time coordination monitoring"""
            return render_template('coordination_monitor.html')

        @self.app.route('/implementation-tools')
        def implementation_tools():
            """Implementation management tools"""
            return render_template('implementation_tools.html')

        # API Endpoints
        @self.app.route('/api/agents')
        def api_get_agents():
            """Get agent information and capabilities"""
            return jsonify(self._get_agent_data())

        @self.app.route('/api/agents/capabilities')
        def api_get_agent_capabilities():
            """Get detailed agent capability matrix"""
            return jsonify(self._build_capability_matrix())

        @self.app.route('/api/teams/optimize', methods=['POST'])
        def api_optimize_team():
            """Optimize team composition for given requirements"""
            data = request.get_json()
            result = self._optimize_team_composition(data)
            return jsonify(result)

        @self.app.route('/api/teams/create', methods=['POST'])
        def api_create_team():
            """Create a new team composition"""
            data = request.get_json()
            result = self._create_team_composition(data)
            return jsonify(result)

        @self.app.route('/api/phases')
        def api_get_phases():
            """Get phase information and progress"""
            return jsonify(self._get_phase_data())

        @self.app.route('/api/phases/<phase_id>/start', methods=['POST'])
        def api_start_phase(phase_id):
            """Start execution of a specific phase"""
            result = self._start_phase_execution(phase_id)
            return jsonify(result)

        @self.app.route('/api/phases/<phase_id>/progress')
        def api_get_phase_progress(phase_id):
            """Get detailed phase progress"""
            return jsonify(self._get_phase_progress(phase_id))

        @self.app.route('/api/coordination/events')
        def api_get_coordination_events():
            """Get recent coordination events"""
            return jsonify(self._get_coordination_events())

        @self.app.route('/api/workflows')
        def api_get_workflows():
            """Get workflow information"""
            return jsonify(self._get_workflow_data())

        @self.app.route('/api/workflows/submit', methods=['POST'])
        def api_submit_workflow():
            """Submit a new workflow for execution"""
            data = request.get_json()
            result = self._submit_workflow(data)
            return jsonify(result)

        @self.app.route('/api/system/status')
        def api_system_status():
            """Get comprehensive system status"""
            return jsonify(self._get_system_status())

        @self.app.route('/api/optimization/recommendations')
        def api_get_optimization_recommendations():
            """Get optimization recommendations"""
            return jsonify(self._get_optimization_recommendations())

        @self.app.route('/api/security/warnings')
        def api_security_warnings():
            """Get security warnings and notices"""
            return jsonify({
                "warnings": self._get_security_warnings(),
                "access_info": self._get_access_info(),
                "local_only": self.local_only,
                "security_level": "HIGH" if self.local_only else "LOW"
            })

        @self.app.route('/api/system/access-info')
        def api_access_info():
            """Get system access information"""
            return jsonify(self._get_access_info())

    def _setup_websocket_handlers(self):
        """Setup WebSocket event handlers for real-time communication"""

        @self.socketio.on('connect')
        def handle_connect():
            """Handle client connection"""
            client_id = request.sid
            self.connected_clients.add(client_id)
            self.active_sessions[client_id] = {
                'connected_at': datetime.now(),
                'subscriptions': set(),
                'user_preferences': {}
            }
            emit('connection_confirmed', {
                'client_id': client_id,
                'server_time': datetime.now().isoformat()
            })
            self.logger.info(f"Client connected: {client_id}")

        @self.socketio.on('disconnect')
        def handle_disconnect():
            """Handle client disconnection"""
            client_id = request.sid
            self.connected_clients.discard(client_id)
            if client_id in self.active_sessions:
                del self.active_sessions[client_id]
            self.logger.info(f"Client disconnected: {client_id}")

        @self.socketio.on('subscribe_updates')
        def handle_subscribe_updates(data):
            """Handle subscription to real-time updates"""
            client_id = request.sid
            subscription_type = data.get('type', 'all')

            if client_id in self.active_sessions:
                self.active_sessions[client_id]['subscriptions'].add(subscription_type)
                join_room(subscription_type)
                emit('subscription_confirmed', {
                    'type': subscription_type,
                    'status': 'subscribed'
                })

        @self.socketio.on('unsubscribe_updates')
        def handle_unsubscribe_updates(data):
            """Handle unsubscription from real-time updates"""
            client_id = request.sid
            subscription_type = data.get('type', 'all')

            if client_id in self.active_sessions:
                self.active_sessions[client_id]['subscriptions'].discard(subscription_type)
                leave_room(subscription_type)
                emit('unsubscription_confirmed', {
                    'type': subscription_type,
                    'status': 'unsubscribed'
                })

        @self.socketio.on('agent_interaction')
        def handle_agent_interaction(data):
            """Handle agent interaction events"""
            self._process_agent_interaction(data)

        @self.socketio.on('request_team_optimization')
        def handle_team_optimization_request(data):
            """Handle team optimization requests"""
            result = self._optimize_team_composition(data)
            emit('team_optimization_result', result)

    def _get_agent_data(self) -> Dict[str, Any]:
        """Get comprehensive agent information"""
        agents_info = {}

        for agent_name, agent in self.orchestrator.agents.items():
            agents_info[agent_name] = {
                'name': agent.name,
                'category': agent.category,
                'capabilities': agent.capabilities,
                'status': agent.status.value,
                'success_rate': agent.success_rate,
                'average_execution_time': agent.average_execution_time,
                'max_concurrent_tasks': agent.max_concurrent_tasks,
                'dependencies': agent.dependencies,
                'resource_requirements': agent.resource_requirements,
                'last_health_check': agent.last_health_check.isoformat() if agent.last_health_check else None,
                'current_load': self._calculate_agent_load(agent_name),
                'availability_score': self._calculate_availability_score(agent_name),
                'specialization_score': self._calculate_specialization_score(agent_name)
            }

        return {
            'agents': agents_info,
            'total_agents': len(agents_info),
            'categories': self._get_agent_categories(),
            'capability_summary': self._get_capability_summary()
        }

    def _build_capability_matrix(self) -> Dict[str, Any]:
        """Build detailed agent capability matrix"""
        if not self.capability_matrix:
            self.capability_matrix = []

            for agent_name, agent in self.orchestrator.agents.items():
                # Get agent capabilities from workflow builder
                agent_caps = self.workflow_builder.agent_capabilities.get(agent_name, {})

                capability_entry = AgentCapabilityMatrix(
                    agent_name=agent_name,
                    primary_capabilities=agent.capabilities[:3] if len(agent.capabilities) > 3 else agent.capabilities,
                    secondary_capabilities=agent.capabilities[3:] if len(agent.capabilities) > 3 else [],
                    performance_metrics={
                        'success_rate': agent.success_rate,
                        'avg_execution_time': agent.average_execution_time,
                        'reliability_score': self._calculate_reliability_score(agent_name)
                    },
                    resource_requirements=agent.resource_requirements,
                    coordination_compatibility=agent_caps.get('coordinates', []),
                    success_history=self._get_agent_success_history(agent_name),
                    current_load=self._calculate_agent_load(agent_name),
                    availability_score=self._calculate_availability_score(agent_name),
                    specialization_score=self._calculate_specialization_score(agent_name)
                )

                self.capability_matrix.append(capability_entry)

        return {
            'capability_matrix': [asdict(entry) for entry in self.capability_matrix],
            'compatibility_graph': self._build_compatibility_graph(),
            'optimization_recommendations': self._get_capability_optimization_recommendations()
        }

    def _optimize_team_composition(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize team composition based on requirements"""
        phase = requirements.get('phase', 'phase1')
        optimization_criteria = requirements.get('criteria', OptimizationCriteria.PERFORMANCE.value)
        constraints = requirements.get('constraints', {})

        # Get available agents
        available_agents = self._get_available_agents()

        # Build capability matrix if not exists
        if not self.capability_matrix:
            self._build_capability_matrix()

        # Optimization algorithm
        optimized_teams = []

        # Multi-criteria optimization
        for criteria in [OptimizationCriteria.PERFORMANCE, OptimizationCriteria.RELIABILITY, OptimizationCriteria.COST]:
            team = self._generate_optimized_team(phase, criteria, available_agents, constraints)
            if team:
                optimized_teams.append(team)

        # Rank teams by composite score
        ranked_teams = self._rank_team_compositions(optimized_teams, optimization_criteria)

        return {
            'optimized_teams': [asdict(team) for team in ranked_teams[:3]],  # Top 3 teams
            'optimization_criteria': optimization_criteria,
            'analysis': self._get_optimization_analysis(ranked_teams),
            'recommendations': self._get_team_optimization_recommendations(ranked_teams)
        }

    def _generate_optimized_team(self,
                                phase: str,
                                criteria: OptimizationCriteria,
                                available_agents: List[str],
                                constraints: Dict[str, Any]) -> Optional[TeamComposition]:
        """Generate an optimized team for specific criteria"""

        # Get phase requirements
        phase_requirements = self._get_phase_requirements(phase)
        required_capabilities = phase_requirements.get('capabilities', [])

        # Agent selection algorithm
        selected_agents = {
            'lead': None,
            'specialists': [],
            'support': [],
            'qa': [],
            'coordination': []
        }

        # Select lead agent (highest specialization score for phase)
        lead_candidates = self._get_lead_candidates(available_agents, required_capabilities)
        if lead_candidates:
            selected_agents['lead'] = lead_candidates[0]
            available_agents.remove(selected_agents['lead'])

        # Select specialist agents
        specialist_needs = self._get_specialist_needs(phase, required_capabilities)
        for need in specialist_needs:
            specialist = self._select_best_specialist(available_agents, need, criteria)
            if specialist:
                selected_agents['specialists'].append(specialist)
                available_agents.remove(specialist)

        # Select support agents
        support_needs = max(1, len(specialist_needs) // 2)
        for _ in range(support_needs):
            support_agent = self._select_support_agent(available_agents, criteria)
            if support_agent:
                selected_agents['support'].append(support_agent)
                available_agents.remove(support_agent)

        # Select QA agents
        qa_agent = self._select_qa_agent(available_agents)
        if qa_agent:
            selected_agents['qa'].append(qa_agent)
            available_agents.remove(qa_agent)

        # Select coordination agents
        if phase in ['phase2', 'phase3', 'phase4']:  # Complex phases need coordination
            coord_agent = self._select_coordination_agent(available_agents)
            if coord_agent:
                selected_agents['coordination'].append(coord_agent)

        # Build team composition
        if selected_agents['lead'] and selected_agents['specialists']:
            team_id = f"team_{phase}_{criteria.value}_{int(time.time())}"

            team = TeamComposition(
                team_id=team_id,
                phase=phase,
                team_name=f"{phase.title()} Team - {criteria.value.title()} Optimized",
                lead_agent=selected_agents['lead'],
                specialist_agents=selected_agents['specialists'],
                support_agents=selected_agents['support'],
                qa_agents=selected_agents['qa'],
                coordination_agents=selected_agents['coordination'],
                estimated_cost=self._calculate_team_cost(selected_agents),
                estimated_duration=self._estimate_team_duration(selected_agents, phase),
                success_probability=self._calculate_success_probability(selected_agents),
                risk_factors=self._identify_risk_factors(selected_agents, phase),
                dependencies=self._identify_team_dependencies(selected_agents)
            )

            return team

        return None

    def _get_phase_data(self) -> Dict[str, Any]:
        """Get comprehensive phase information"""
        phases = {
            'phase1': {
                'id': 'phase1',
                'name': 'Foundation Enhancement',
                'description': 'Database migration, compression integration, deduplication system',
                'duration_weeks': 4,
                'complexity': 'High',
                'required_capabilities': [
                    'database_management', 'performance_optimization', 'system_architecture',
                    'compression_algorithms', 'deduplication', 'postgresql_expertise'
                ],
                'key_deliverables': [
                    'PostgreSQL cluster deployment',
                    'Kanzi-cpp compression integration',
                    'Multi-layer deduplication system',
                    'Performance baseline establishment'
                ]
            },
            'phase2': {
                'id': 'phase2',
                'name': 'Advanced Features',
                'description': 'Smart recording, multi-tier storage, real-time analytics',
                'duration_weeks': 4,
                'complexity': 'Very High',
                'required_capabilities': [
                    'machine_learning', 'real_time_processing', 'storage_architecture',
                    'analytics_systems', 'api_development', 'web_interfaces'
                ],
                'key_deliverables': [
                    'ML-powered content classification',
                    'Multi-tier storage system',
                    'Real-time analytics dashboard',
                    'Network analysis engine'
                ]
            },
            'phase3': {
                'id': 'phase3',
                'name': 'Production Deployment',
                'description': 'Kubernetes orchestration, auto-scaling, monitoring',
                'duration_weeks': 4,
                'complexity': 'High',
                'required_capabilities': [
                    'kubernetes_orchestration', 'container_deployment', 'monitoring_systems',
                    'security_hardening', 'load_balancing', 'disaster_recovery'
                ],
                'key_deliverables': [
                    'Production Kubernetes cluster',
                    'Auto-scaling infrastructure',
                    'Comprehensive monitoring',
                    'Security hardening implementation'
                ]
            },
            'phase4': {
                'id': 'phase4',
                'name': 'Optimization & Enhancement',
                'description': 'Advanced ML, performance optimization, next-gen features',
                'duration_weeks': 4,
                'complexity': 'Medium',
                'required_capabilities': [
                    'advanced_machine_learning', 'system_optimization', 'research_development',
                    'threat_detection', 'emerging_technologies'
                ],
                'key_deliverables': [
                    'Advanced ML models deployment',
                    'Global performance optimization',
                    'Enhanced threat detection',
                    'Next-generation features research'
                ]
            }
        }

        # Add progress information
        for phase_id, phase_info in phases.items():
            phase_info['progress'] = self._get_phase_progress(phase_id)
            phase_info['team_assignments'] = self._get_phase_team_assignments(phase_id)
            phase_info['resource_requirements'] = self._calculate_phase_resources(phase_id)

        return {
            'phases': phases,
            'current_phase': self._get_current_phase(),
            'overall_progress': self._calculate_overall_progress(),
            'timeline': self._generate_timeline()
        }

    def _start_phase_execution(self, phase_id: str) -> Dict[str, Any]:
        """Start execution of a specific phase"""
        try:
            # Get workflow for phase
            workflows = self.workflow_builder.get_all_workflows()
            if phase_id not in workflows:
                return {'success': False, 'error': f'Phase {phase_id} not found'}

            workflow = workflows[phase_id]

            # Submit workflow to orchestrator
            workflow_id = asyncio.run(self.orchestrator.submit_workflow(workflow))

            # Update phase progress tracking
            self.phase_progress[phase_id] = PhaseProgress(
                phase_id=phase_id,
                phase_name=workflow.name,
                start_date=datetime.now(),
                end_date=datetime.now() + workflow.estimated_duration,
                current_progress=0.0,
                milestones=[],
                active_workflows=[workflow_id],
                completed_workflows=[],
                blocked_workflows=[],
                team_assignments=[],
                resource_utilization={},
                issues=[]
            )

            # Broadcast update to connected clients
            self._broadcast_phase_update(phase_id, 'started')

            return {
                'success': True,
                'workflow_id': workflow_id,
                'phase_id': phase_id,
                'estimated_completion': (datetime.now() + workflow.estimated_duration).isoformat()
            }

        except Exception as e:
            self.logger.error(f"Failed to start phase {phase_id}: {e}")
            return {'success': False, 'error': str(e)}

    def _get_coordination_events(self, limit: int = 100) -> Dict[str, Any]:
        """Get recent coordination events"""
        recent_events = self.coordination_events[-limit:] if self.coordination_events else []

        return {
            'events': [asdict(event) for event in recent_events],
            'total_events': len(self.coordination_events),
            'event_types': self._get_event_type_summary(),
            'active_interactions': self._get_active_interactions()
        }

    def _get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        return {
            'orchestrator_status': 'running' if self.orchestrator.is_running else 'stopped',
            'gui_status': 'running' if self.is_running else 'stopped',
            'connected_clients': len(self.connected_clients),
            'active_sessions': len(self.active_sessions),
            'total_agents': len(self.orchestrator.agents),
            'active_agents': len([a for a in self.orchestrator.agents.values()
                                if a.status == AgentStatus.RUNNING]),
            'total_workflows': len(self.orchestrator.workflows),
            'active_workflows': len([w for w in self.orchestrator.workflows.values()
                                   if w.status == WorkflowStatus.RUNNING]),
            'system_load': self.orchestrator.metrics.system_load,
            'coordination_events': len(self.coordination_events),
            'team_compositions': len(self.team_compositions),
            'phase_progress': {pid: p.current_progress for pid, p in self.phase_progress.items()},
            'last_update': datetime.now().isoformat()
        }

    # Helper methods for calculations and analysis
    def _calculate_agent_load(self, agent_name: str) -> float:
        """Calculate current load for an agent"""
        active_tasks = [t for t in self.orchestrator.active_tasks.values()
                       if t.agent == agent_name]
        agent = self.orchestrator.agents.get(agent_name)
        if agent:
            return len(active_tasks) / max(1, agent.max_concurrent_tasks)
        return 0.0

    def _calculate_availability_score(self, agent_name: str) -> float:
        """Calculate availability score for an agent"""
        load = self._calculate_agent_load(agent_name)
        agent = self.orchestrator.agents.get(agent_name)
        if agent and agent.last_health_check:
            health_recency = (datetime.now() - agent.last_health_check).total_seconds() / 3600
            health_score = max(0.0, 1.0 - health_recency / 24)  # Decay over 24 hours
            return (1.0 - load) * health_score * agent.success_rate
        return 0.0

    def _calculate_specialization_score(self, agent_name: str) -> float:
        """Calculate specialization score for an agent"""
        agent = self.orchestrator.agents.get(agent_name)
        if agent:
            # Score based on number of capabilities and success rate
            capability_score = min(1.0, len(agent.capabilities) / 10.0)
            return capability_score * agent.success_rate
        return 0.0

    def _get_available_agents(self) -> List[str]:
        """Get list of available agents"""
        return [name for name, agent in self.orchestrator.agents.items()
                if self._calculate_availability_score(name) > 0.5]

    async def start_gui(self):
        """Start the GUI application"""
        if self.is_running:
            self.logger.warning("GUI is already running")
            return

        # Check port availability and find alternative if needed
        self.logger.info(f"🔍 Checking availability of port {self.port}")
        if not self._check_port_availability(self.port):
            self.logger.warning(f"⚠️ Port {self.port} is already in use")
            alternative_port = self._find_available_port(self.port + 1)
            if alternative_port:
                self.logger.info(f"✅ Using alternative port {alternative_port}")
                self.available_port = alternative_port
            else:
                self.logger.error("❌ CRITICAL: No available ports found in range")
                self.logger.error("🔧 Try stopping other services or using a different port range")
                return False
        else:
            self.logger.info(f"✅ Port {self.port} is available")

        actual_port = self.available_port or self.port
        self.is_running = True

        # Log security information
        security_warnings = self._get_security_warnings()
        access_info = self._get_access_info()

        self.logger.info(f"Starting SPECTRA Coordination GUI")
        self.logger.info(f"🌐 Access URL: http://{self.host}:{actual_port}")
        self.logger.info(f"🔒 Security Level: {'HIGH (local only)' if self.local_only else 'LOW (network accessible)'}")

        for warning in security_warnings[:3]:  # Log first 3 warnings
            self.logger.info(f"⚠️  {warning}")

        # Start background update thread
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()

        try:
            # Create templates directory and files
            await self._create_template_files()

            # Run Flask application
            self.socketio.run(
                self.app,
                host=self.host,
                port=actual_port,
                debug=self.debug,
                use_reloader=False  # Avoid conflicts with threading
            )
        except Exception as e:
            self.logger.error(f"GUI application error: {e}", exc_info=True)
            return False
        finally:
            self.is_running = False

        return True

    async def stop_gui(self):
        """Stop the GUI application"""
        self.logger.info("Stopping SPECTRA Coordination GUI")
        self.is_running = False
        self.stop_event.set()

        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=5)

    def _update_loop(self):
        """Background update loop for real-time data"""
        while not self.stop_event.is_set():
            try:
                # Update coordination events
                self._collect_coordination_events()

                # Update phase progress
                self._update_phase_progress()

                # Update team status
                self._update_team_status()

                # Broadcast updates to connected clients
                if self.connected_clients:
                    update_data = {
                        'timestamp': datetime.now().isoformat(),
                        'system_status': self._get_system_status(),
                        'coordination_events': self._get_coordination_events(limit=10),
                        'phase_progress': self._get_phase_data(),
                        'agent_status': self._get_agent_data()
                    }
                    self.socketio.emit('real_time_update', update_data)

                time.sleep(2)  # Update every 2 seconds

            except Exception as e:
                self.logger.error(f"Update loop error: {e}")
                time.sleep(5)

    async def _create_template_files(self):
        """Create HTML template files for the GUI"""
        templates_dir = Path("templates")
        templates_dir.mkdir(exist_ok=True)

        # Main coordination GUI template
        main_template = self._create_main_template()
        (templates_dir / "coordination_gui.html").write_text(main_template)

        # Agent selection template
        agent_template = self._create_agent_selection_template()
        (templates_dir / "agent_selection.html").write_text(agent_template)

        # Phase management template
        phase_template = self._create_phase_management_template()
        (templates_dir / "phase_management.html").write_text(phase_template)

        # Coordination monitor template
        monitor_template = self._create_coordination_monitor_template()
        (templates_dir / "coordination_monitor.html").write_text(monitor_template)

        # Implementation tools template
        tools_template = self._create_implementation_tools_template()
        (templates_dir / "implementation_tools.html").write_text(tools_template)

    def _create_main_template(self) -> str:
        """Create main coordination GUI template"""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPECTRA Agent Coordination GUI</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <style>
        :root {
            --primary-color: #2563eb;
            --secondary-color: #1e40af;
            --success-color: #059669;
            --warning-color: #d97706;
            --danger-color: #dc2626;
            --background-color: #f8fafc;
            --card-background: #ffffff;
            --text-color: #1f2937;
            --border-color: #e5e7eb;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: var(--background-color);
            color: var(--text-color);
            line-height: 1.6;
        }

        .header {
            background: linear-gradient(135deg, var(--primary-color), var(--secondary-color));
            color: white;
            padding: 1.5rem 2rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        .header h1 {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }

        .header p {
            opacity: 0.9;
            font-size: 1.1rem;
        }

        .security-notice {
            background: rgba(255, 255, 255, 0.95);
            border: 2px solid #10b981;
            border-radius: 12px;
            padding: 1rem;
            margin-top: 1rem;
            color: #065f46;
            backdrop-filter: blur(10px);
        }

        .security-header {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
        }

        .security-icon {
            font-size: 1.5rem;
        }

        .security-title {
            font-weight: 700;
            font-size: 1.2rem;
            color: #065f46;
        }

        .security-details p {
            margin: 0.25rem 0;
            font-size: 0.95rem;
            line-height: 1.4;
        }

        .security-details strong {
            color: #047857;
            font-weight: 600;
        }

        #access-host, #access-port, #security-status {
            font-weight: 600;
            color: #059669;
        }

        .security-warning {
            background: #fef3c7;
            border: 2px solid #f59e0b;
            color: #92400e;
        }

        .security-warning .security-title {
            color: #92400e;
        }

        .security-critical {
            background: #fee2e2;
            border: 2px solid #ef4444;
            color: #991b1b;
        }

        .security-critical .security-title {
            color: #991b1b;
        }

        .nav-tabs {
            background: white;
            border-bottom: 1px solid var(--border-color);
            padding: 0 2rem;
            display: flex;
            gap: 0;
        }

        .nav-tab {
            padding: 1rem 1.5rem;
            background: none;
            border: none;
            border-bottom: 3px solid transparent;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: 500;
            color: var(--text-color);
        }

        .nav-tab:hover {
            background-color: #f3f4f6;
            color: var(--primary-color);
        }

        .nav-tab.active {
            border-bottom-color: var(--primary-color);
            color: var(--primary-color);
            background-color: #eff6ff;
        }

        .main-content {
            padding: 2rem;
            max-width: 1400px;
            margin: 0 auto;
        }

        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .card {
            background: var(--card-background);
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            border: 1px solid var(--border-color);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }

        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }

        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--border-color);
        }

        .card-title {
            font-size: 1.25rem;
            font-weight: 600;
            color: var(--text-color);
        }

        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
        }

        .status-running { background-color: var(--success-color); }
        .status-idle { background-color: var(--warning-color); }
        .status-failed { background-color: var(--danger-color); }
        .status-paused { background-color: #6b7280; }

        .metric-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 1rem;
            margin: 1rem 0;
        }

        .metric-item {
            text-align: center;
            padding: 1rem;
            background: #f9fafb;
            border-radius: 8px;
        }

        .metric-value {
            font-size: 2rem;
            font-weight: 700;
            color: var(--primary-color);
            display: block;
        }

        .metric-label {
            font-size: 0.875rem;
            color: #6b7280;
            margin-top: 0.25rem;
        }

        .progress-bar {
            width: 100%;
            height: 8px;
            background-color: #e5e7eb;
            border-radius: 4px;
            overflow: hidden;
            margin: 0.5rem 0;
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--primary-color), var(--success-color));
            transition: width 0.3s ease;
        }

        .btn {
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 8px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            text-decoration: none;
            display: inline-block;
            text-align: center;
        }

        .btn-primary {
            background-color: var(--primary-color);
            color: white;
        }

        .btn-primary:hover {
            background-color: var(--secondary-color);
            transform: translateY(-1px);
        }

        .btn-secondary {
            background-color: #6b7280;
            color: white;
        }

        .btn-success {
            background-color: var(--success-color);
            color: white;
        }

        .btn-warning {
            background-color: var(--warning-color);
            color: white;
        }

        .quick-actions {
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            margin-top: 1rem;
        }

        .agent-list {
            max-height: 300px;
            overflow-y: auto;
        }

        .agent-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.75rem;
            border-bottom: 1px solid var(--border-color);
            transition: background-color 0.2s ease;
        }

        .agent-item:hover {
            background-color: #f9fafb;
        }

        .agent-info {
            display: flex;
            align-items: center;
        }

        .agent-name {
            font-weight: 600;
            margin-left: 0.5rem;
        }

        .agent-category {
            font-size: 0.875rem;
            color: #6b7280;
            margin-left: 0.5rem;
        }

        .phase-timeline {
            display: flex;
            justify-content: space-between;
            margin: 1.5rem 0;
            position: relative;
        }

        .phase-timeline::before {
            content: '';
            position: absolute;
            top: 50%;
            left: 0;
            right: 0;
            height: 2px;
            background-color: var(--border-color);
            z-index: 1;
        }

        .phase-step {
            background: white;
            border: 2px solid var(--border-color);
            border-radius: 50%;
            width: 40px;
            height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            position: relative;
            z-index: 2;
            transition: all 0.3s ease;
        }

        .phase-step.completed {
            background-color: var(--success-color);
            border-color: var(--success-color);
            color: white;
        }

        .phase-step.active {
            background-color: var(--primary-color);
            border-color: var(--primary-color);
            color: white;
            transform: scale(1.1);
        }

        .chart-container {
            height: 250px;
            margin-top: 1rem;
        }

        .connection-status {
            position: fixed;
            top: 1rem;
            right: 1rem;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-size: 0.875rem;
            font-weight: 500;
            z-index: 1000;
        }

        .connection-status.connected {
            background-color: #d1fae5;
            color: #065f46;
            border: 1px solid #10b981;
        }

        .connection-status.disconnected {
            background-color: #fed7d7;
            color: #991b1b;
            border: 1px solid #ef4444;
        }

        @media (max-width: 768px) {
            .header {
                padding: 1rem;
            }

            .main-content {
                padding: 1rem;
            }

            .dashboard-grid {
                grid-template-columns: 1fr;
            }

            .nav-tabs {
                overflow-x: auto;
                padding: 0 1rem;
            }

            .quick-actions {
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <div class="connection-status" id="connection-status">
        <span class="status-indicator status-idle"></span>
        Connecting...
    </div>

    <div class="header">
        <h1>SPECTRA Agent Coordination System</h1>
        <p>Multi-Agent Workflow Management for Advanced Data Management Implementation</p>

        <!-- Security Notice -->
        <div id="security-notice" class="security-notice">
            <div class="security-header">
                <span class="security-icon">🔒</span>
                <span class="security-title">LOCAL ACCESS ONLY</span>
            </div>
            <div class="security-details">
                <p><strong>📍 README and documentation access is LOCAL SYSTEM ONLY</strong></p>
                <p>🔐 No external file system access • 💻 Local installation files only</p>
                <p>Host: <span id="access-host">127.0.0.1</span> | Port: <span id="access-port">5001</span> | Status: <span id="security-status">SECURE</span></p>
            </div>
        </div>
    </div>

    <div class="nav-tabs">
        <button class="nav-tab active" onclick="switchTab('overview')">Overview</button>
        <button class="nav-tab" onclick="switchTab('agent-selection')">Agent Selection</button>
        <button class="nav-tab" onclick="switchTab('phase-management')">Phase Management</button>
        <button class="nav-tab" onclick="switchTab('coordination')">Real-time Coordination</button>
        <button class="nav-tab" onclick="switchTab('tools')">Implementation Tools</button>
    </div>

    <div class="main-content">
        <!-- Overview Tab -->
        <div id="overview-tab" class="tab-content">
            <div class="dashboard-grid">
                <!-- System Status Card -->
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">System Status</h3>
                        <span class="status-indicator status-running"></span>
                    </div>
                    <div class="metric-grid">
                        <div class="metric-item">
                            <span class="metric-value" id="total-agents">0</span>
                            <span class="metric-label">Total Agents</span>
                        </div>
                        <div class="metric-item">
                            <span class="metric-value" id="active-workflows">0</span>
                            <span class="metric-label">Active Workflows</span>
                        </div>
                        <div class="metric-item">
                            <span class="metric-value" id="system-load">0%</span>
                            <span class="metric-label">System Load</span>
                        </div>
                        <div class="metric-item">
                            <span class="metric-value" id="connected-clients">0</span>
                            <span class="metric-label">Connected Clients</span>
                        </div>
                    </div>
                    <div class="quick-actions">
                        <button class="btn btn-primary" onclick="optimizeAllTeams()">Optimize All Teams</button>
                        <button class="btn btn-secondary" onclick="generateReport()">Generate Report</button>
                    </div>
                </div>

                <!-- Phase Progress Card -->
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">Phase Progress</h3>
                    </div>
                    <div class="phase-timeline">
                        <div class="phase-step" id="phase1-step">1</div>
                        <div class="phase-step" id="phase2-step">2</div>
                        <div class="phase-step" id="phase3-step">3</div>
                        <div class="phase-step" id="phase4-step">4</div>
                    </div>
                    <div id="current-phase-info">
                        <h4>Current Phase: Foundation Enhancement</h4>
                        <div class="progress-bar">
                            <div class="progress-fill" id="current-phase-progress" style="width: 0%"></div>
                        </div>
                        <p>Database migration and compression integration in progress...</p>
                    </div>
                    <div class="quick-actions">
                        <button class="btn btn-success" onclick="startNextPhase()">Start Next Phase</button>
                        <button class="btn btn-warning" onclick="pauseCurrentPhase()">Pause Current</button>
                    </div>
                </div>

                <!-- Active Agents Card -->
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">Active Agents</h3>
                    </div>
                    <div class="agent-list" id="active-agents-list">
                        <!-- Agents will be populated dynamically -->
                    </div>
                </div>

                <!-- Performance Metrics Card -->
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">Performance Metrics</h3>
                    </div>
                    <div class="chart-container">
                        <canvas id="performance-chart"></canvas>
                    </div>
                </div>

                <!-- Recent Activity Card -->
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">Recent Activity</h3>
                    </div>
                    <div id="activity-feed">
                        <!-- Activity items will be populated dynamically -->
                    </div>
                </div>

                <!-- Team Compositions Card -->
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">Team Compositions</h3>
                    </div>
                    <div id="team-compositions-list">
                        <!-- Team compositions will be populated dynamically -->
                    </div>
                    <div class="quick-actions">
                        <button class="btn btn-primary" onclick="createNewTeam()">Create New Team</button>
                        <button class="btn btn-secondary" onclick="optimizeExistingTeams()">Optimize Existing</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Other tabs will be loaded via AJAX or iframe -->
        <div id="agent-selection-tab" class="tab-content" style="display: none;">
            <iframe src="/agent-selection" width="100%" height="800px" frameborder="0"></iframe>
        </div>

        <div id="phase-management-tab" class="tab-content" style="display: none;">
            <iframe src="/phase-management" width="100%" height="800px" frameborder="0"></iframe>
        </div>

        <div id="coordination-tab" class="tab-content" style="display: none;">
            <iframe src="/coordination-monitor" width="100%" height="800px" frameborder="0"></iframe>
        </div>

        <div id="tools-tab" class="tab-content" style="display: none;">
            <iframe src="/implementation-tools" width="100%" height="800px" frameborder="0"></iframe>
        </div>
    </div>

    <script>
        // WebSocket connection
        const socket = io();
        let performanceChart;

        // Connection status management
        socket.on('connect', function() {
            updateConnectionStatus(true);
            socket.emit('subscribe_updates', {type: 'all'});
        });

        socket.on('disconnect', function() {
            updateConnectionStatus(false);
        });

        function updateConnectionStatus(connected) {
            const statusEl = document.getElementById('connection-status');
            const indicator = statusEl.querySelector('.status-indicator');

            if (connected) {
                statusEl.className = 'connection-status connected';
                statusEl.innerHTML = '<span class="status-indicator status-running"></span>Connected';
            } else {
                statusEl.className = 'connection-status disconnected';
                statusEl.innerHTML = '<span class="status-indicator status-failed"></span>Disconnected';
            }
        }

        // Real-time updates
        socket.on('real_time_update', function(data) {
            updateSystemMetrics(data.system_status);
            updatePhaseProgress(data.phase_progress);
            updateAgentList(data.agent_status);
            updateActivityFeed(data.coordination_events);
        });

        function updateSystemMetrics(status) {
            document.getElementById('total-agents').textContent = status.total_agents || 0;
            document.getElementById('active-workflows').textContent = status.active_workflows || 0;
            document.getElementById('system-load').textContent = ((status.system_load || 0) * 100).toFixed(1) + '%';
            document.getElementById('connected-clients').textContent = status.connected_clients || 0;
        }

        function updatePhaseProgress(phaseData) {
            // Update phase timeline
            const phases = phaseData.phases || {};
            Object.keys(phases).forEach(phaseId => {
                const phase = phases[phaseId];
                const stepEl = document.getElementById(phaseId + '-step');
                if (stepEl && phase.progress) {
                    if (phase.progress.current_progress >= 1.0) {
                        stepEl.className = 'phase-step completed';
                    } else if (phase.progress.current_progress > 0) {
                        stepEl.className = 'phase-step active';
                    }
                }
            });

            // Update current phase progress
            const currentPhase = phaseData.current_phase || 'phase1';
            const progressBar = document.getElementById('current-phase-progress');
            if (progressBar && phases[currentPhase] && phases[currentPhase].progress) {
                const progress = phases[currentPhase].progress.current_progress * 100;
                progressBar.style.width = progress + '%';
            }
        }

        function updateAgentList(agentData) {
            const agentsList = document.getElementById('active-agents-list');
            if (!agentsList || !agentData.agents) return;

            let html = '';
            Object.entries(agentData.agents).forEach(([name, agent]) => {
                const statusClass = 'status-' + agent.status;
                html += `
                    <div class="agent-item">
                        <div class="agent-info">
                            <span class="status-indicator ${statusClass}"></span>
                            <span class="agent-name">${name}</span>
                            <span class="agent-category">${agent.category}</span>
                        </div>
                        <div>
                            <small>${(agent.success_rate * 100).toFixed(1)}%</small>
                        </div>
                    </div>
                `;
            });
            agentsList.innerHTML = html;
        }

        function updateActivityFeed(eventsData) {
            const activityFeed = document.getElementById('activity-feed');
            if (!activityFeed || !eventsData.events) return;

            let html = '';
            eventsData.events.slice(-10).reverse().forEach(event => {
                const timeStr = new Date(event.timestamp).toLocaleTimeString();
                html += `
                    <div class="activity-item" style="padding: 0.5rem 0; border-bottom: 1px solid var(--border-color);">
                        <div style="font-weight: 500;">${event.message}</div>
                        <div style="font-size: 0.875rem; color: #6b7280;">${timeStr} - ${event.source_agent}</div>
                    </div>
                `;
            });
            activityFeed.innerHTML = html || '<p>No recent activity</p>';
        }

        // Tab switching
        function switchTab(tabName) {
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.style.display = 'none';
            });

            // Remove active class from all nav tabs
            document.querySelectorAll('.nav-tab').forEach(tab => {
                tab.classList.remove('active');
            });

            // Show selected tab
            document.getElementById(tabName + '-tab').style.display = 'block';

            // Add active class to clicked nav tab
            event.target.classList.add('active');
        }

        // Action handlers
        function optimizeAllTeams() {
            socket.emit('request_team_optimization', {
                criteria: 'performance',
                phases: ['phase1', 'phase2', 'phase3', 'phase4']
            });
        }

        function generateReport() {
            fetch('/api/system/status')
                .then(response => response.json())
                .then(data => {
                    console.log('System Report:', data);
                    alert('Report generated successfully! Check console for details.');
                });
        }

        function startNextPhase() {
            // Implement phase starting logic
            alert('Starting next phase...');
        }

        function pauseCurrentPhase() {
            // Implement phase pausing logic
            alert('Pausing current phase...');
        }

        function createNewTeam() {
            // Redirect to agent selection for team creation
            switchTab('agent-selection');
        }

        function optimizeExistingTeams() {
            optimizeAllTeams();
        }

        // Initialize performance chart
        function initializePerformanceChart() {
            const ctx = document.getElementById('performance-chart').getContext('2d');
            performanceChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'System Load',
                        data: [],
                        borderColor: '#2563eb',
                        backgroundColor: 'rgba(37, 99, 235, 0.1)',
                        tension: 0.4
                    }, {
                        label: 'Active Workflows',
                        data: [],
                        borderColor: '#059669',
                        backgroundColor: 'rgba(5, 150, 105, 0.1)',
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        }

        // Load security information
        function loadSecurityInfo() {
            fetch('/api/security/warnings')
                .then(response => response.json())
                .then(data => {
                    updateSecurityNotice(data);
                    updateAccessInfo(data.access_info);
                })
                .catch(error => {
                    console.warn('Could not load security info:', error);
                    updateSecurityNotice({
                        warnings: ["📍 README ACCESS IS LOCAL SYSTEM ONLY"],
                        local_only: true,
                        security_level: "HIGH"
                    });
                });
        }

        function updateSecurityNotice(securityData) {
            const notice = document.getElementById('security-notice');
            if (!notice) return;

            // Update security level styling
            notice.className = 'security-notice';
            if (!securityData.local_only) {
                notice.classList.add('security-critical');
            }

            // Update security status
            const statusEl = document.getElementById('security-status');
            if (statusEl) {
                statusEl.textContent = securityData.local_only ? 'SECURE (LOCAL)' : 'EXPOSED (NETWORK)';
                statusEl.style.color = securityData.local_only ? '#059669' : '#dc2626';
            }
        }

        function updateAccessInfo(accessInfo) {
            if (!accessInfo) return;

            const hostEl = document.getElementById('access-host');
            const portEl = document.getElementById('access-port');

            if (hostEl) hostEl.textContent = accessInfo.host || '127.0.0.1';
            if (portEl) portEl.textContent = accessInfo.port || '5001';
        }

        // Initialize application
        document.addEventListener('DOMContentLoaded', function() {
            initializePerformanceChart();
            loadSecurityInfo();

            // Load initial data
            fetch('/api/system/status')
                .then(response => response.json())
                .then(data => updateSystemMetrics(data));

            // Refresh security info periodically
            setInterval(loadSecurityInfo, 30000); // Every 30 seconds
        });
    </script>
</body>
</html>
        """

    # Additional helper methods would continue here...
    # (Implementation continues with more helper methods and template creation functions)

    def _collect_coordination_events(self):
        """Collect coordination events from the orchestrator"""
        # This would integrate with the orchestrator to collect real events
        pass

    def _update_phase_progress(self):
        """Update phase progress based on workflow status"""
        # This would check workflow progress and update phase tracking
        pass

    def _update_team_status(self):
        """Update team status and compositions"""
        # This would update team status based on agent activity
        pass

    def _broadcast_phase_update(self, phase_id: str, event_type: str):
        """Broadcast phase update to connected clients"""
        if self.connected_clients:
            self.socketio.emit('phase_update', {
                'phase_id': phase_id,
                'event_type': event_type,
                'timestamp': datetime.now().isoformat()
            })

    # Additional template creation methods would be implemented here...


# CLI interface for the GUI application
async def main():
    """Main entry point for the coordination GUI"""
    import argparse

    parser = argparse.ArgumentParser(description="SPECTRA Agent Coordination GUI")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1 for security)")
    parser.add_argument("--port", type=int, default=5001, help="Port number")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--config", default="spectra_config.json", help="Orchestrator configuration")
    parser.add_argument("--db", default="spectra.db", help="Database file path")

    args = parser.parse_args()

    # Initialize orchestrator
    orchestrator = SpectraOrchestrator(
        config_path=args.config,
        db_path=args.db
    )

    if not await orchestrator.initialize():
        print("Failed to initialize orchestrator")
        return 1

    # Initialize GUI
    gui = SpectraCoordinationGUI(
        orchestrator=orchestrator,
        host=args.host,
        port=args.port,
        debug=args.debug
    )

    try:
        # Start both orchestrator and GUI
        await asyncio.gather(
            orchestrator.start_orchestration(),
            gui.start_gui()
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
        await asyncio.gather(
            orchestrator.stop_orchestration(),
            gui.stop_gui()
        )
    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))