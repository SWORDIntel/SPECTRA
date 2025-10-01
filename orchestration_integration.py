#!/usr/bin/env python3
"""
SPECTRA Multi-Agent Orchestration Integration
=============================================

Complete integration script that brings together all orchestration components:
- Core orchestrator
- Workflow automation
- Real-time dashboard
- Agent communication
- Phase-specific workflows

Author: COORDINATOR Agent - Multi-Agent Orchestration Specialist
Date: September 18, 2025
"""

import asyncio
import logging
import json
import signal
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

# SPECTRA Orchestration Components
from spectra_orchestrator import SpectraOrchestrator
from orchestration_workflows import SpectraWorkflowBuilder
from orchestration_dashboard import SpectraOrchestrationDashboard
from workflow_automation import WorkflowAutomationEngine
from agent_communication import AgentCommunicationBus, SpectraAgentProxy


class SpectraOrchestrationSystem:
    """
    Complete SPECTRA multi-agent orchestration system that integrates
    all components into a unified platform.
    """

    def __init__(self,
                 config_path: str = "spectra_config.json",
                 db_path: str = "spectra.db",
                 dashboard_interface: str = "web",
                 dashboard_port: int = 5000):
        """Initialize the complete orchestration system"""
        self.config_path = config_path
        self.db_path = db_path
        self.dashboard_interface = dashboard_interface
        self.dashboard_port = dashboard_port

        # Core components
        self.orchestrator: Optional[SpectraOrchestrator] = None
        self.workflow_builder: Optional[SpectraWorkflowBuilder] = None
        self.dashboard: Optional[SpectraOrchestrationDashboard] = None
        self.automation_engine: Optional[WorkflowAutomationEngine] = None
        self.communication_bus: Optional[AgentCommunicationBus] = None

        # Agent proxies
        self.agent_proxies: Dict[str, SpectraAgentProxy] = {}

        # System state
        self.is_running = False
        self.startup_time: Optional[datetime] = None

        # Logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('spectra_orchestration.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)

    async def initialize_system(self) -> bool:
        """Initialize all orchestration components"""
        try:
            self.logger.info("Initializing SPECTRA Multi-Agent Orchestration System")

            # 1. Initialize core orchestrator
            self.logger.info("1/5 - Initializing Core Orchestrator...")
            self.orchestrator = SpectraOrchestrator(
                config_path=self.config_path,
                db_path=self.db_path
            )
            if not await self.orchestrator.initialize():
                self.logger.error("Failed to initialize orchestrator")
                return False

            # 2. Initialize workflow builder
            self.logger.info("2/5 - Initializing Workflow Builder...")
            self.workflow_builder = SpectraWorkflowBuilder()

            # 3. Initialize communication bus
            self.logger.info("3/5 - Initializing Communication Bus...")
            self.communication_bus = AgentCommunicationBus()

            # 4. Initialize automation engine
            self.logger.info("4/5 - Initializing Automation Engine...")
            self.automation_engine = WorkflowAutomationEngine(self.orchestrator)

            # 5. Initialize dashboard
            self.logger.info("5/5 - Initializing Dashboard...")
            self.dashboard = SpectraOrchestrationDashboard(
                orchestrator=self.orchestrator,
                interface_type=self.dashboard_interface,
                port=self.dashboard_port
            )

            # Create agent proxies
            await self._create_agent_proxies()

            # Setup integration between components
            await self._setup_component_integration()

            self.logger.info("All orchestration components initialized successfully")
            return True

        except Exception as e:
            self.logger.error(f"System initialization failed: {e}", exc_info=True)
            return False

    async def start_orchestration_system(self):
        """Start the complete orchestration system"""
        if self.is_running:
            self.logger.warning("Orchestration system is already running")
            return

        self.is_running = True
        self.startup_time = datetime.now()

        self.logger.info("Starting SPECTRA Multi-Agent Orchestration System")

        try:
            # Start all components concurrently
            await asyncio.gather(
                self._start_communication_bus(),
                self._start_orchestrator(),
                self._start_automation_engine(),
                self._start_dashboard(),
                self._start_monitoring()
            )

        except Exception as e:
            self.logger.error(f"System startup failed: {e}", exc_info=True)
            raise
        finally:
            self.is_running = False

    async def stop_orchestration_system(self):
        """Stop the orchestration system gracefully"""
        self.logger.info("Stopping SPECTRA Multi-Agent Orchestration System")

        try:
            # Stop components in reverse order
            stop_tasks = []

            if self.dashboard:
                stop_tasks.append(self.dashboard.stop_dashboard())

            if self.automation_engine:
                stop_tasks.append(self.automation_engine.stop_automation())

            if self.orchestrator:
                stop_tasks.append(self.orchestrator.stop_orchestration())

            if self.communication_bus:
                stop_tasks.append(self.communication_bus.stop_communication_bus())

            # Wait for all components to stop
            await asyncio.gather(*stop_tasks, return_exceptions=True)

            self.is_running = False
            self.logger.info("Orchestration system stopped successfully")

        except Exception as e:
            self.logger.error(f"Error during system shutdown: {e}", exc_info=True)

    async def submit_phase_workflow(self, phase: str) -> Optional[str]:
        """Submit a specific phase workflow for execution"""
        try:
            if not self.workflow_builder or not self.automation_engine:
                self.logger.error("System not properly initialized")
                return None

            workflows = self.workflow_builder.get_all_workflows()
            phase_key = f"phase{phase}"

            if phase_key not in workflows:
                self.logger.error(f"Phase {phase} workflow not found")
                return None

            workflow = workflows[phase_key]
            workflow_id = await self.automation_engine.execute_workflow_automated(workflow)

            self.logger.info(f"Submitted Phase {phase} workflow: {workflow_id}")
            return workflow_id

        except Exception as e:
            self.logger.error(f"Failed to submit Phase {phase} workflow: {e}")
            return None

    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        try:
            status = {
                "system": {
                    "is_running": self.is_running,
                    "startup_time": self.startup_time.isoformat() if self.startup_time else None,
                    "uptime_seconds": (datetime.now() - self.startup_time).total_seconds() if self.startup_time else 0
                },
                "components": {},
                "agents": {},
                "workflows": {},
                "communication": {},
                "automation": {}
            }

            # Orchestrator status
            if self.orchestrator:
                status["components"]["orchestrator"] = {
                    "running": self.orchestrator.is_running,
                    "agents_loaded": len(self.orchestrator.agents),
                    "workflows_total": len(self.orchestrator.workflows),
                    "active_tasks": len(self.orchestrator.active_tasks)
                }
                status["workflows"] = await self.orchestrator.get_system_metrics()

            # Communication bus status
            if self.communication_bus:
                status["communication"] = await self.communication_bus.get_communication_stats()

            # Automation engine status
            if self.automation_engine:
                status["automation"] = await self.automation_engine.get_automation_status()

            # Dashboard status
            if self.dashboard:
                status["components"]["dashboard"] = {
                    "interface": self.dashboard_interface,
                    "port": self.dashboard_port if self.dashboard_interface == "web" else None,
                    "active_connections": self.dashboard.metrics.active_connections
                }

            # Agent proxy status
            status["agents"] = {
                agent_id: {
                    "registered": agent_id in self.communication_bus.agents if self.communication_bus else False,
                    "capabilities": proxy.comm_bus.agents[agent_id].capabilities if self.communication_bus and agent_id in self.communication_bus.agents else []
                }
                for agent_id, proxy in self.agent_proxies.items()
            }

            return status

        except Exception as e:
            self.logger.error(f"Failed to get system status: {e}")
            return {"error": str(e)}

    async def execute_coordination_demo(self) -> Dict[str, Any]:
        """Execute a demonstration of multi-agent coordination"""
        try:
            self.logger.info("Starting multi-agent coordination demonstration")

            demo_results = {
                "timestamp": datetime.now().isoformat(),
                "steps": [],
                "success": False
            }

            # Step 1: Test agent communication
            demo_results["steps"].append({
                "step": "agent_communication",
                "description": "Testing agent-to-agent communication",
                "status": "running"
            })

            if "DIRECTOR" in self.agent_proxies and "DATABASE" in self.agent_proxies:
                await self.agent_proxies["DIRECTOR"].send_to_agent(
                    "DATABASE",
                    {"action": "status_check", "demo": True}
                )
                demo_results["steps"][-1]["status"] = "completed"
            else:
                demo_results["steps"][-1]["status"] = "failed"
                demo_results["steps"][-1]["error"] = "Required agents not available"

            # Step 2: Test synchronization barrier
            demo_results["steps"].append({
                "step": "synchronization_barrier",
                "description": "Testing agent synchronization",
                "status": "running"
            })

            if self.communication_bus and len(self.agent_proxies) >= 3:
                barrier_id = "demo_barrier"
                agent_list = list(self.agent_proxies.keys())[:3]

                await self.communication_bus.create_synchronization_barrier(
                    barrier_id, agent_list, timeout_seconds=30
                )

                # Have agents join the barrier
                for agent_id in agent_list:
                    await self.agent_proxies[agent_id].join_barrier(barrier_id)

                demo_results["steps"][-1]["status"] = "completed"
                demo_results["steps"][-1]["participants"] = agent_list
            else:
                demo_results["steps"][-1]["status"] = "failed"
                demo_results["steps"][-1]["error"] = "Insufficient agents for barrier test"

            # Step 3: Test workflow automation
            demo_results["steps"].append({
                "step": "workflow_automation",
                "description": "Testing automated workflow execution",
                "status": "running"
            })

            if self.automation_engine and self.workflow_builder:
                # Create a simple test workflow
                workflows = self.workflow_builder.get_all_workflows()
                if "phase1" in workflows:
                    # Don't actually execute the full workflow for demo
                    demo_results["steps"][-1]["status"] = "simulated"
                    demo_results["steps"][-1]["workflow"] = "phase1_foundation"
                else:
                    demo_results["steps"][-1]["status"] = "failed"
                    demo_results["steps"][-1]["error"] = "No workflows available"
            else:
                demo_results["steps"][-1]["status"] = "failed"
                demo_results["steps"][-1]["error"] = "Automation engine not available"

            # Check overall success
            demo_results["success"] = all(
                step["status"] in ["completed", "simulated"]
                for step in demo_results["steps"]
            )

            self.logger.info(f"Coordination demonstration completed: {'Success' if demo_results['success'] else 'Failed'}")
            return demo_results

        except Exception as e:
            self.logger.error(f"Coordination demonstration failed: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "success": False,
                "error": str(e)
            }

    async def _create_agent_proxies(self):
        """Create agent proxies for communication"""
        if not self.orchestrator or not self.communication_bus:
            return

        # Create proxies for all orchestrator agents
        for agent_name, agent_metadata in self.orchestrator.agents.items():
            proxy = SpectraAgentProxy(agent_name, self.communication_bus)
            await proxy.initialize(agent_metadata.capabilities)
            self.agent_proxies[agent_name] = proxy

        self.logger.info(f"Created {len(self.agent_proxies)} agent proxies")

    async def _setup_component_integration(self):
        """Setup integration between different components"""
        # This would configure how components interact with each other
        # For example, linking automation rules to dashboard alerts
        pass

    async def _start_communication_bus(self):
        """Start the communication bus"""
        if self.communication_bus:
            await self.communication_bus.start_communication_bus()

    async def _start_orchestrator(self):
        """Start the core orchestrator"""
        if self.orchestrator:
            await self.orchestrator.start_orchestration()

    async def _start_automation_engine(self):
        """Start the automation engine"""
        if self.automation_engine:
            await self.automation_engine.start_automation()

    async def _start_dashboard(self):
        """Start the dashboard"""
        if self.dashboard:
            await self.dashboard.start_dashboard()

    async def _start_monitoring(self):
        """Start system monitoring"""
        while self.is_running:
            try:
                # Monitor system health
                await self._check_system_health()
                await asyncio.sleep(30)  # Check every 30 seconds
            except Exception as e:
                self.logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(60)

    async def _check_system_health(self):
        """Check overall system health"""
        # This would implement health checks for all components
        pass


# Command-line interface
async def main():
    """Main entry point for the integrated orchestration system"""
    import argparse

    parser = argparse.ArgumentParser(description="SPECTRA Multi-Agent Orchestration System")
    parser.add_argument("--config", default="spectra_config.json", help="Configuration file path")
    parser.add_argument("--db", default="spectra.db", help="Database file path")
    parser.add_argument("--dashboard", choices=["web", "terminal", "basic"], default="web",
                       help="Dashboard interface type")
    parser.add_argument("--port", type=int, default=5000, help="Web dashboard port")
    parser.add_argument("--phase", help="Start specific phase workflow (1-4)")
    parser.add_argument("--demo", action="store_true", help="Run coordination demonstration")
    parser.add_argument("--status", action="store_true", help="Show system status and exit")

    args = parser.parse_args()

    # Initialize orchestration system
    system = SpectraOrchestrationSystem(
        config_path=args.config,
        db_path=args.db,
        dashboard_interface=args.dashboard,
        dashboard_port=args.port
    )

    # Initialize system
    if not await system.initialize_system():
        print("Failed to initialize orchestration system")
        return 1

    # Handle different modes
    if args.status:
        status = await system.get_system_status()
        print(json.dumps(status, indent=2, default=str))
        return 0

    elif args.demo:
        print("Running multi-agent coordination demonstration...")

        # Start system briefly for demo
        system_task = asyncio.create_task(system.start_orchestration_system())

        # Wait for startup
        await asyncio.sleep(5)

        # Run demo
        demo_results = await system.execute_coordination_demo()
        print(json.dumps(demo_results, indent=2, default=str))

        # Stop system
        await system.stop_orchestration_system()
        return 0

    elif args.phase:
        print(f"Starting Phase {args.phase} workflow...")

        # Start system
        system_task = asyncio.create_task(system.start_orchestration_system())

        # Wait for startup
        await asyncio.sleep(3)

        # Submit workflow
        workflow_id = await system.submit_phase_workflow(args.phase)
        if workflow_id:
            print(f"Phase {args.phase} workflow submitted: {workflow_id}")
            print("System will continue running. Use Ctrl+C to stop.")

            # Setup signal handlers for graceful shutdown
            def signal_handler():
                asyncio.create_task(system.stop_orchestration_system())

            signal.signal(signal.SIGINT, lambda s, f: signal_handler())
            signal.signal(signal.SIGTERM, lambda s, f: signal_handler())

            # Keep running
            await system_task
        else:
            print(f"Failed to start Phase {args.phase} workflow")
            await system.stop_orchestration_system()
            return 1

    else:
        print("Starting complete SPECTRA Multi-Agent Orchestration System...")
        print(f"Dashboard: {args.dashboard}")
        if args.dashboard == "web":
            print(f"Web interface: http://localhost:{args.port}")

        # Setup signal handlers for graceful shutdown
        def signal_handler():
            asyncio.create_task(system.stop_orchestration_system())

        signal.signal(signal.SIGINT, lambda s, f: signal_handler())
        signal.signal(signal.SIGTERM, lambda s, f: signal_handler())

        # Start system
        await system.start_orchestration_system()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))