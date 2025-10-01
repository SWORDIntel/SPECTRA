#!/usr/bin/env python3
"""
SPECTRA Orchestration Dashboard
===============================

Real-time monitoring and management dashboard for multi-agent orchestration.
Provides comprehensive visibility into workflow execution, agent status,
resource utilization, and system performance.

Author: COORDINATOR Agent - Multi-Agent Orchestration Specialist
Date: September 18, 2025
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import threading
import signal
import sys

# Web framework imports
try:
    from flask import Flask, render_template, jsonify, request, websocket
    from flask_socketio import SocketIO, emit
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Terminal UI imports
try:
    import curses
    import npyscreen
    CURSES_AVAILABLE = True
except ImportError:
    CURSES_AVAILABLE = False

# SPECTRA imports
from spectra_orchestrator import SpectraOrchestrator, AgentStatus, WorkflowStatus
from orchestration_workflows import SpectraWorkflowBuilder


@dataclass
class DashboardMetrics:
    """Dashboard-specific metrics"""
    active_connections: int = 0
    last_update: datetime = None
    update_frequency: float = 1.0  # seconds
    total_updates: int = 0
    error_count: int = 0


class SpectraOrchestrationDashboard:
    """
    Real-time dashboard for SPECTRA orchestration monitoring and management.

    Supports both web-based and terminal-based interfaces for different
    deployment scenarios.
    """

    def __init__(self,
                 orchestrator: SpectraOrchestrator,
                 interface_type: str = "web",
                 host: str = "0.0.0.0",
                 port: int = 5000):
        """Initialize the dashboard"""
        self.orchestrator = orchestrator
        self.interface_type = interface_type
        self.host = host
        self.port = port

        # Dashboard state
        self.is_running = False
        self.metrics = DashboardMetrics()
        self.connected_clients = set()

        # Web interface components
        self.app = None
        self.socketio = None

        # Terminal interface components
        self.terminal_app = None

        # Logging
        self.logger = logging.getLogger(__name__)

        # Update thread
        self.update_thread = None
        self.stop_event = threading.Event()

        self._initialize_interface()

    def _initialize_interface(self):
        """Initialize the appropriate interface"""
        if self.interface_type == "web" and FLASK_AVAILABLE:
            self._initialize_web_interface()
        elif self.interface_type == "terminal" and CURSES_AVAILABLE:
            self._initialize_terminal_interface()
        else:
            self.logger.warning(f"Interface type '{self.interface_type}' not available, falling back to basic monitoring")
            self.interface_type = "basic"

    def _initialize_web_interface(self):
        """Initialize Flask web interface"""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'spectra_orchestration_dashboard'
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")

        # Route definitions
        @self.app.route('/')
        def index():
            return render_template('dashboard.html')

        @self.app.route('/api/status')
        def api_status():
            return jsonify(self._get_system_status())

        @self.app.route('/api/metrics')
        def api_metrics():
            return jsonify(self._get_system_metrics())

        @self.app.route('/api/workflows')
        def api_workflows():
            return jsonify(self._get_workflows_status())

        @self.app.route('/api/agents')
        def api_agents():
            return jsonify(self._get_agents_status())

        @self.app.route('/api/workflows/<workflow_id>/pause', methods=['POST'])
        def api_pause_workflow(workflow_id):
            result = asyncio.run(self.orchestrator.pause_workflow(workflow_id))
            return jsonify({"success": result})

        @self.app.route('/api/workflows/<workflow_id>/resume', methods=['POST'])
        def api_resume_workflow(workflow_id):
            result = asyncio.run(self.orchestrator.resume_workflow(workflow_id))
            return jsonify({"success": result})

        @self.app.route('/api/workflows/<workflow_id>/cancel', methods=['POST'])
        def api_cancel_workflow(workflow_id):
            result = asyncio.run(self.orchestrator.cancel_workflow(workflow_id))
            return jsonify({"success": result})

        @self.app.route('/api/workflows/submit', methods=['POST'])
        def api_submit_workflow():
            try:
                data = request.get_json()
                workflow_type = data.get('type', 'phase1')

                builder = SpectraWorkflowBuilder()
                workflows = builder.get_all_workflows()

                if workflow_type in workflows:
                    workflow_id = asyncio.run(self.orchestrator.submit_workflow(workflows[workflow_type]))
                    return jsonify({"success": True, "workflow_id": workflow_id})
                else:
                    return jsonify({"success": False, "error": "Invalid workflow type"})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)})

        # WebSocket events
        @self.socketio.on('connect')
        def handle_connect():
            self.connected_clients.add(request.sid)
            self.metrics.active_connections = len(self.connected_clients)
            self.logger.info(f"Client connected: {request.sid}")

        @self.socketio.on('disconnect')
        def handle_disconnect():
            self.connected_clients.discard(request.sid)
            self.metrics.active_connections = len(self.connected_clients)
            self.logger.info(f"Client disconnected: {request.sid}")

        @self.socketio.on('subscribe_updates')
        def handle_subscribe():
            # Client will receive real-time updates
            emit('subscription_confirmed', {"status": "subscribed"})

    def _initialize_terminal_interface(self):
        """Initialize terminal-based interface using npyscreen"""

        class SpectraTerminalApp(npyscreen.NPSAppManaged):
            def __init__(self, dashboard):
                self.dashboard = dashboard
                super().__init__()

            def onStart(self):
                self.addForm('MAIN', MainDashboardForm, name="SPECTRA Orchestration Dashboard")

        class MainDashboardForm(npyscreen.FormBaseNew):
            def create(self):
                self.add(npyscreen.TitleText, name="System Status:", editable=False)
                self.status_display = self.add(npyscreen.Pager, max_height=10)

                self.add(npyscreen.TitleText, name="Active Workflows:", editable=False)
                self.workflows_display = self.add(npyscreen.Pager, max_height=8)

                self.add(npyscreen.TitleText, name="Agent Status:", editable=False)
                self.agents_display = self.add(npyscreen.Pager, max_height=8)

                self.add(npyscreen.TitleText, name="System Metrics:", editable=False)
                self.metrics_display = self.add(npyscreen.Pager, max_height=6)

            def update_displays(self, dashboard):
                """Update all display components"""
                try:
                    # System status
                    status = dashboard._get_system_status()
                    status_text = [
                        f"Orchestrator Status: {status['orchestrator_status']}",
                        f"Total Workflows: {status['total_workflows']}",
                        f"Active Workflows: {status['active_workflows']}",
                        f"Total Agents: {status['total_agents']}",
                        f"Active Tasks: {status['active_tasks']}",
                        f"Last Update: {status['last_update']}"
                    ]
                    self.status_display.values = status_text

                    # Workflows
                    workflows = dashboard._get_workflows_status()
                    workflow_text = []
                    for wf in workflows.get('workflows', []):
                        workflow_text.append(f"{wf['name']}: {wf['status']} ({wf['progress']:.1%})")
                    self.workflows_display.values = workflow_text if workflow_text else ["No active workflows"]

                    # Agents
                    agents = dashboard._get_agents_status()
                    agent_text = []
                    for agent_name, agent_info in agents.get('agents', {}).items():
                        agent_text.append(f"{agent_name}: {agent_info['status']} (Success: {agent_info['success_rate']:.1%})")
                    self.agents_display.values = agent_text

                    # Metrics
                    metrics = dashboard._get_system_metrics()
                    metrics_text = [
                        f"System Load: {metrics.get('system_load', 0):.1%}",
                        f"CPU Usage: {metrics.get('resource_utilization', {}).get('cpu_percent', 0):.1f}%",
                        f"Memory Usage: {metrics.get('resource_utilization', {}).get('memory_percent', 0):.1f}%",
                        f"Connected Clients: {dashboard.metrics.active_connections}",
                        f"Update Frequency: {dashboard.metrics.update_frequency:.1f}s"
                    ]
                    self.metrics_display.values = metrics_text

                    self.display()

                except Exception as e:
                    self.status_display.values = [f"Error updating display: {str(e)}"]
                    self.display()

        self.terminal_app = SpectraTerminalApp(self)

    async def start_dashboard(self):
        """Start the dashboard interface"""
        if self.is_running:
            self.logger.warning("Dashboard is already running")
            return

        self.is_running = True
        self.logger.info(f"Starting SPECTRA Orchestration Dashboard ({self.interface_type} interface)")

        # Start update thread
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()

        try:
            if self.interface_type == "web":
                await self._run_web_interface()
            elif self.interface_type == "terminal":
                await self._run_terminal_interface()
            else:
                await self._run_basic_interface()
        except Exception as e:
            self.logger.error(f"Dashboard error: {e}", exc_info=True)
        finally:
            self.is_running = False

    async def stop_dashboard(self):
        """Stop the dashboard interface"""
        self.logger.info("Stopping SPECTRA Orchestration Dashboard")
        self.is_running = False
        self.stop_event.set()

        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=5)

    async def _run_web_interface(self):
        """Run the web-based dashboard"""
        def run_socketio():
            self.socketio.run(self.app, host=self.host, port=self.port, debug=False)

        # Run in separate thread to avoid blocking
        web_thread = threading.Thread(target=run_socketio, daemon=True)
        web_thread.start()

        self.logger.info(f"Web dashboard running at http://{self.host}:{self.port}")

        # Keep the async context alive
        while self.is_running:
            await asyncio.sleep(1)

    async def _run_terminal_interface(self):
        """Run the terminal-based dashboard"""
        def run_terminal():
            try:
                self.terminal_app.run()
            except Exception as e:
                self.logger.error(f"Terminal interface error: {e}")

        # Run terminal interface in separate thread
        terminal_thread = threading.Thread(target=run_terminal, daemon=True)
        terminal_thread.start()

        # Update terminal display
        while self.is_running and terminal_thread.is_alive():
            try:
                if hasattr(self.terminal_app, 'getForm'):
                    form = self.terminal_app.getForm('MAIN')
                    if form:
                        form.update_displays(self)
                await asyncio.sleep(self.metrics.update_frequency)
            except Exception as e:
                self.logger.error(f"Terminal update error: {e}")
                break

    async def _run_basic_interface(self):
        """Run basic console output interface"""
        self.logger.info("Running basic console monitoring interface")

        while self.is_running:
            try:
                status = self._get_system_status()
                print(f"\n{'='*60}")
                print(f"SPECTRA Orchestration Status - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"{'='*60}")
                print(f"Orchestrator: {status['orchestrator_status']}")
                print(f"Workflows: {status['active_workflows']}/{status['total_workflows']} active")
                print(f"Agents: {status['total_agents']} total")
                print(f"Tasks: {status['active_tasks']} active, {status['completed_tasks']} completed")
                print(f"System Load: {status.get('system_load', 0):.1%}")

                # Show active workflows
                workflows = self._get_workflows_status()
                if workflows.get('workflows'):
                    print(f"\nActive Workflows:")
                    for wf in workflows['workflows']:
                        print(f"  - {wf['name']}: {wf['status']} ({wf['progress']:.1%})")

                await asyncio.sleep(10)  # Update every 10 seconds for basic interface

            except Exception as e:
                self.logger.error(f"Basic interface error: {e}")
                await asyncio.sleep(5)

    def _update_loop(self):
        """Background update loop for real-time data"""
        while not self.stop_event.is_set():
            try:
                # Update metrics
                self.metrics.last_update = datetime.now()
                self.metrics.total_updates += 1

                # Broadcast updates to web clients
                if self.interface_type == "web" and self.socketio and self.connected_clients:
                    update_data = {
                        "timestamp": self.metrics.last_update.isoformat(),
                        "status": self._get_system_status(),
                        "metrics": self._get_system_metrics(),
                        "workflows": self._get_workflows_status(),
                        "agents": self._get_agents_status()
                    }
                    self.socketio.emit('dashboard_update', update_data)

                time.sleep(self.metrics.update_frequency)

            except Exception as e:
                self.logger.error(f"Update loop error: {e}")
                self.metrics.error_count += 1
                time.sleep(5)

    def _get_system_status(self) -> Dict[str, Any]:
        """Get current system status"""
        try:
            return {
                "orchestrator_status": "running" if self.orchestrator.is_running else "stopped",
                "total_workflows": len(self.orchestrator.workflows),
                "active_workflows": len([w for w in self.orchestrator.workflows.values()
                                       if w.status == WorkflowStatus.RUNNING]),
                "completed_workflows": len([w for w in self.orchestrator.workflows.values()
                                         if w.status == WorkflowStatus.COMPLETED]),
                "failed_workflows": len([w for w in self.orchestrator.workflows.values()
                                       if w.status == WorkflowStatus.FAILED]),
                "total_agents": len(self.orchestrator.agents),
                "active_agents": len([a for a in self.orchestrator.agents.values()
                                    if a.status == AgentStatus.RUNNING]),
                "active_tasks": len(self.orchestrator.active_tasks),
                "completed_tasks": len(self.orchestrator.completed_tasks),
                "failed_tasks": len(self.orchestrator.failed_tasks),
                "task_queue_size": len(self.orchestrator.task_queue),
                "system_load": self.orchestrator.metrics.system_load,
                "last_update": self.metrics.last_update.isoformat() if self.metrics.last_update else None,
                "dashboard_metrics": {
                    "active_connections": self.metrics.active_connections,
                    "total_updates": self.metrics.total_updates,
                    "error_count": self.metrics.error_count
                }
            }
        except Exception as e:
            self.logger.error(f"Error getting system status: {e}")
            return {"error": str(e)}

    def _get_system_metrics(self) -> Dict[str, Any]:
        """Get detailed system metrics"""
        try:
            return asyncio.run(self.orchestrator.get_system_metrics())
        except Exception as e:
            self.logger.error(f"Error getting system metrics: {e}")
            return {"error": str(e)}

    def _get_workflows_status(self) -> Dict[str, Any]:
        """Get workflows status"""
        try:
            workflows_data = []
            for workflow_id, workflow in self.orchestrator.workflows.items():
                workflow_info = asyncio.run(self.orchestrator.get_workflow_status(workflow_id))
                if workflow_info:
                    workflows_data.append(workflow_info)

            return {
                "workflows": workflows_data,
                "summary": {
                    status.value: len([w for w in self.orchestrator.workflows.values() if w.status == status])
                    for status in WorkflowStatus
                }
            }
        except Exception as e:
            self.logger.error(f"Error getting workflows status: {e}")
            return {"error": str(e)}

    def _get_agents_status(self) -> Dict[str, Any]:
        """Get agents status"""
        try:
            agents_data = {}
            for agent_name, agent in self.orchestrator.agents.items():
                agents_data[agent_name] = {
                    "status": agent.status.value,
                    "category": agent.category,
                    "capabilities": agent.capabilities,
                    "success_rate": agent.success_rate,
                    "average_execution_time": agent.average_execution_time,
                    "max_concurrent_tasks": agent.max_concurrent_tasks,
                    "last_health_check": agent.last_health_check.isoformat() if agent.last_health_check else None,
                    "dependencies": agent.dependencies,
                    "resource_requirements": agent.resource_requirements
                }

            return {
                "agents": agents_data,
                "summary": {
                    status.value: len([a for a in self.orchestrator.agents.values() if a.status == status])
                    for status in AgentStatus
                }
            }
        except Exception as e:
            self.logger.error(f"Error getting agents status: {e}")
            return {"error": str(e)}

    def create_html_template(self) -> str:
        """Create HTML template for web dashboard"""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPECTRA Orchestration Dashboard</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
        }
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        .card {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .metric-value {
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
        }
        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
        }
        .status-running { background-color: #28a745; }
        .status-idle { background-color: #ffc107; }
        .status-failed { background-color: #dc3545; }
        .status-completed { background-color: #28a745; }
        .workflow-item, .agent-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }
        .progress-bar {
            width: 100px;
            height: 20px;
            background-color: #e9ecef;
            border-radius: 10px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #28a745, #20c997);
            transition: width 0.3s ease;
        }
        .controls {
            margin-top: 20px;
        }
        button {
            background-color: #667eea;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            margin-right: 10px;
        }
        button:hover {
            background-color: #5a6fd8;
        }
        .chart-container {
            height: 300px;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>SPECTRA Orchestration Dashboard</h1>
        <p>Real-time Multi-Agent Workflow Monitoring</p>
    </div>

    <div class="dashboard-grid">
        <!-- System Overview -->
        <div class="card">
            <h3>System Overview</h3>
            <div id="system-status">
                <div class="metric-value" id="active-workflows">0</div>
                <div>Active Workflows</div>
                <br>
                <div class="metric-value" id="active-tasks">0</div>
                <div>Active Tasks</div>
                <br>
                <div class="metric-value" id="system-load">0%</div>
                <div>System Load</div>
            </div>
        </div>

        <!-- Performance Metrics -->
        <div class="card">
            <h3>Performance Metrics</h3>
            <div id="performance-chart" class="chart-container"></div>
        </div>

        <!-- Active Workflows -->
        <div class="card">
            <h3>Active Workflows</h3>
            <div id="workflows-list">
                <p>No active workflows</p>
            </div>
            <div class="controls">
                <button onclick="submitWorkflow('phase1')">Start Phase 1</button>
                <button onclick="submitWorkflow('phase2')">Start Phase 2</button>
                <button onclick="submitWorkflow('phase3')">Start Phase 3</button>
                <button onclick="submitWorkflow('phase4')">Start Phase 4</button>
            </div>
        </div>

        <!-- Agent Status -->
        <div class="card">
            <h3>Agent Status</h3>
            <div id="agents-list">
                <p>Loading agents...</p>
            </div>
        </div>

        <!-- Resource Utilization -->
        <div class="card">
            <h3>Resource Utilization</h3>
            <div id="resource-chart" class="chart-container"></div>
        </div>

        <!-- Recent Activity -->
        <div class="card">
            <h3>Recent Activity</h3>
            <div id="activity-log">
                <p>No recent activity</p>
            </div>
        </div>
    </div>

    <script>
        // Initialize Socket.IO connection
        const socket = io();

        // Performance data for charts
        let performanceData = {
            timestamps: [],
            systemLoad: [],
            cpuUsage: [],
            memoryUsage: []
        };

        socket.on('connect', function() {
            console.log('Connected to dashboard');
            socket.emit('subscribe_updates');
        });

        socket.on('dashboard_update', function(data) {
            updateDashboard(data);
        });

        function updateDashboard(data) {
            // Update system overview
            document.getElementById('active-workflows').textContent = data.status.active_workflows || 0;
            document.getElementById('active-tasks').textContent = data.status.active_tasks || 0;
            document.getElementById('system-load').textContent = ((data.status.system_load || 0) * 100).toFixed(1) + '%';

            // Update workflows
            updateWorkflows(data.workflows);

            // Update agents
            updateAgents(data.agents);

            // Update performance charts
            updatePerformanceChart(data);
        }

        function updateWorkflows(workflowsData) {
            const container = document.getElementById('workflows-list');
            const workflows = workflowsData.workflows || [];

            if (workflows.length === 0) {
                container.innerHTML = '<p>No active workflows</p>';
                return;
            }

            let html = '';
            workflows.forEach(workflow => {
                const statusClass = `status-${workflow.status}`;
                const progress = (workflow.progress * 100).toFixed(1);

                html += `
                    <div class="workflow-item">
                        <div>
                            <span class="status-indicator ${statusClass}"></span>
                            <strong>${workflow.name}</strong>
                            <br>
                            <small>Phase: ${workflow.phase}</small>
                        </div>
                        <div>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${progress}%"></div>
                            </div>
                            <small>${progress}%</small>
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        function updateAgents(agentsData) {
            const container = document.getElementById('agents-list');
            const agents = agentsData.agents || {};

            if (Object.keys(agents).length === 0) {
                container.innerHTML = '<p>No agents loaded</p>';
                return;
            }

            let html = '';
            Object.entries(agents).forEach(([name, agent]) => {
                const statusClass = `status-${agent.status}`;
                const successRate = (agent.success_rate * 100).toFixed(1);

                html += `
                    <div class="agent-item">
                        <div>
                            <span class="status-indicator ${statusClass}"></span>
                            <strong>${name}</strong>
                            <br>
                            <small>${agent.category}</small>
                        </div>
                        <div>
                            <small>Success: ${successRate}%</small>
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        function updatePerformanceChart(data) {
            // Add new data point
            const now = new Date(data.timestamp);
            const metrics = data.metrics.orchestration_metrics || {};
            const resources = data.metrics.resource_utilization || {};

            performanceData.timestamps.push(now);
            performanceData.systemLoad.push((data.status.system_load || 0) * 100);
            performanceData.cpuUsage.push(resources.cpu_percent || 0);
            performanceData.memoryUsage.push(resources.memory_percent || 0);

            // Keep only last 50 data points
            if (performanceData.timestamps.length > 50) {
                performanceData.timestamps.shift();
                performanceData.systemLoad.shift();
                performanceData.cpuUsage.shift();
                performanceData.memoryUsage.shift();
            }

            // Update performance chart
            const performanceTrace1 = {
                x: performanceData.timestamps,
                y: performanceData.systemLoad,
                name: 'System Load',
                type: 'scatter',
                mode: 'lines'
            };

            const performanceTrace2 = {
                x: performanceData.timestamps,
                y: performanceData.cpuUsage,
                name: 'CPU Usage',
                type: 'scatter',
                mode: 'lines',
                yaxis: 'y2'
            };

            const performanceLayout = {
                title: 'System Performance',
                xaxis: { title: 'Time' },
                yaxis: { title: 'Load %', side: 'left' },
                yaxis2: { title: 'CPU %', side: 'right', overlaying: 'y' },
                margin: { t: 50, r: 50, b: 50, l: 50 }
            };

            Plotly.newPlot('performance-chart', [performanceTrace1, performanceTrace2], performanceLayout);

            // Update resource chart
            const resourceData = [{
                labels: ['CPU', 'Memory', 'Available'],
                values: [
                    resources.cpu_percent || 0,
                    resources.memory_percent || 0,
                    100 - ((resources.cpu_percent || 0) + (resources.memory_percent || 0)) / 2
                ],
                type: 'pie'
            }];

            const resourceLayout = {
                title: 'Resource Utilization',
                margin: { t: 50, r: 50, b: 50, l: 50 }
            };

            Plotly.newPlot('resource-chart', resourceData, resourceLayout);
        }

        function submitWorkflow(phase) {
            fetch('/api/workflows/submit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ type: phase })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    console.log('Workflow submitted:', data.workflow_id);
                } else {
                    console.error('Failed to submit workflow:', data.error);
                }
            })
            .catch(error => {
                console.error('Error submitting workflow:', error);
            });
        }

        // Initial load
        fetch('/api/status')
            .then(response => response.json())
            .then(data => {
                document.getElementById('active-workflows').textContent = data.active_workflows || 0;
                document.getElementById('active-tasks').textContent = data.active_tasks || 0;
                document.getElementById('system-load').textContent = ((data.system_load || 0) * 100).toFixed(1) + '%';
            });
    </script>
</body>
</html>
        """


# CLI interface for the dashboard
async def main():
    """Main entry point for the dashboard"""
    import argparse

    parser = argparse.ArgumentParser(description="SPECTRA Orchestration Dashboard")
    parser.add_argument("--interface", choices=["web", "terminal", "basic"], default="web",
                       help="Dashboard interface type")
    parser.add_argument("--host", default="0.0.0.0", help="Host address for web interface")
    parser.add_argument("--port", type=int, default=5000, help="Port for web interface")
    parser.add_argument("--config", default="spectra_config.json", help="Orchestrator configuration file")
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

    # Initialize dashboard
    dashboard = SpectraOrchestrationDashboard(
        orchestrator=orchestrator,
        interface_type=args.interface,
        host=args.host,
        port=args.port
    )

    # Create HTML template if running web interface
    if args.interface == "web":
        templates_dir = Path("templates")
        templates_dir.mkdir(exist_ok=True)

        template_file = templates_dir / "dashboard.html"
        if not template_file.exists():
            template_file.write_text(dashboard.create_html_template())
            print(f"Created HTML template at {template_file}")

    # Setup signal handlers for graceful shutdown
    def signal_handler():
        asyncio.create_task(dashboard.stop_dashboard())
        asyncio.create_task(orchestrator.stop_orchestration())

    signal.signal(signal.SIGINT, lambda s, f: signal_handler())
    signal.signal(signal.SIGTERM, lambda s, f: signal_handler())

    # Start orchestrator and dashboard
    try:
        await asyncio.gather(
            orchestrator.start_orchestration(),
            dashboard.start_dashboard()
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))