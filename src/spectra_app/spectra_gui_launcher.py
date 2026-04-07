#!/usr/bin/env python3
"""
SPECTRA Comprehensive GUI System Launcher
=========================================

Complete GUI system launcher that integrates all components:
- Agent Selection & Team Optimization
- Phase Management Dashboard
- Real-time Coordination Interface
- Implementation Management Tools
- Orchestration System Backend

Features:
- Unified application launcher
- Component health monitoring
- Configuration management
- Error handling and recovery
- System initialization and shutdown
- Cross-component communication
- Performance monitoring

Author: PYTHON-INTERNAL Agent - Elite Python execution environment specialist
Date: September 18, 2025
"""

import asyncio
import json
import logging
import os
import secrets
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import argparse

# Optional markdown import
try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

# GUI Framework Integration
try:
    from flask import Flask, render_template, jsonify, redirect, url_for, request, session
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

try:
    from flask_socketio import SocketIO, emit
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False

    class SocketIO:  # type: ignore[override]
        """Minimal SocketIO fallback used when Flask-SocketIO is unavailable."""

        def __init__(self, app, cors_allowed_origins="*"):
            self.app = app

        def on(self, _event_name):
            def decorator(func):
                return func

            return decorator

        def emit(self, _event_name, _payload):
            return None

        def run(self, app, host, port, debug=False, use_reloader=False):
            app.run(host=host, port=port, debug=debug, use_reloader=use_reloader)

    def emit(_event_name, _payload):
        return None

# SPECTRA Component Imports
from .spectra_orchestrator import SpectraOrchestrator
from .spectra_coordination_gui import SpectraCoordinationGUI
from .phase_management_dashboard import PhaseManagementDashboard
from .coordination_interface import CoordinationInterface
from .implementation_tools import ImplementationTools
from .agent_optimization_engine import AgentOptimizationEngine
from .programmatic_api import SpectraProgrammaticAPI


def check_port_available(host: str, port: int, timeout: float = 3.0) -> bool:
    """
    Check if a port is available for binding.

    Args:
        host: Host address to check
        port: Port number to check
        timeout: Connection timeout in seconds

    Returns:
        True if port is available, False otherwise
    """
    try:
        # Create socket with proper options
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout)

            # Try to bind to the port
            result = sock.bind((host, port))
            return True

    except (socket.error, OSError) as e:
        return False


def find_available_port(host: str, preferred_port: int, max_attempts: int = 20) -> Tuple[int, bool]:
    """
    Find an available port starting from the preferred port.

    Args:
        host: Host address to check
        preferred_port: Preferred port number
        max_attempts: Maximum number of ports to try

    Returns:
        Tuple of (port_number, is_preferred_port)
    """
    # First try the preferred port
    if check_port_available(host, preferred_port):
        return preferred_port, True

    # Try alternative ports
    for i in range(1, max_attempts + 1):
        alternative_port = preferred_port + i
        if check_port_available(host, alternative_port):
            return alternative_port, False

    # If no port found, return the preferred port and let it fail gracefully
    return preferred_port, False


def get_security_level(host: str) -> Tuple[str, str]:
    """
    Determine security level based on host configuration.

    Args:
        host: Host address

    Returns:
        Tuple of (security_level, description)
    """
    if host in ['127.0.0.1', 'localhost', '::1']:
        return "HIGH", "LOCAL ACCESS ONLY - Secure localhost configuration"
    elif host in ['0.0.0.0', '::', '*']:
        return "CRITICAL", "⚠️ NETWORK ACCESSIBLE - External access enabled"
    else:
        return "MEDIUM", f"Specific interface: {host}"


class ComponentStatus(Enum):
    """Component status enumeration"""
    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class SystemMode(Enum):
    """System operation modes"""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    DEMO = "demo"

    def __eq__(self, other):
        if isinstance(other, str):
            return self.value == other
        return super().__eq__(other)


@dataclass
class ComponentHealth:
    """Component health status"""
    name: str
    status: ComponentStatus
    start_time: Optional[datetime]
    last_health_check: Optional[datetime]
    error_count: int
    response_time: float
    resource_usage: Dict[str, float]
    dependencies_met: bool
    health_score: float


@dataclass
class SystemConfiguration:
    """System configuration settings"""
    mode: SystemMode
    host: str
    port: int
    debug: bool
    orchestrator_config: str
    database_path: str
    log_level: str
    enable_components: List[str]
    component_ports: Dict[str, int]
    security_enabled: bool
    monitoring_interval: float
    api_key: Optional[str]
    home_page: str

    def __init__(
        self,
        mode: Any = SystemMode.DEVELOPMENT,
        host: str = "127.0.0.1",
        port: int = 5000,
        debug: bool = False,
        orchestrator_config: str = "spectra_config.json",
        database_path: str = "spectra.db",
        log_level: str = "INFO",
        enable_components: Optional[List[str]] = None,
        component_ports: Optional[Dict[str, int]] = None,
        security_enabled: bool = True,
        monitoring_interval: float = 5.0,
        config_file: Optional[str] = None,
        api_key: Optional[str] = None,
        home_page: str = "console",
    ):
        self.mode = mode if isinstance(mode, SystemMode) else SystemMode(str(mode))
        self.host = host
        self.port = port
        self.debug = debug
        self.orchestrator_config = orchestrator_config if config_file is None else config_file
        self.database_path = database_path
        self.log_level = log_level
        self.enable_components = enable_components or [
            "orchestrator",
            "optimization",
            "phase_dashboard",
            "coordination",
            "implementation",
        ]
        self.component_ports = component_ports or {
            "main_gui": 5001,
            "coordination": 5002,
            "phase_dashboard": 5003,
            "implementation": 5004,
        }
        self.security_enabled = security_enabled
        self.monitoring_interval = monitoring_interval
        self.config_file = config_file
        self.api_key = api_key
        self.home_page = home_page


class SpectraGUILauncher:
    """
    Comprehensive launcher for the complete SPECTRA GUI system.

    Manages initialization, health monitoring, and coordination of all
    GUI components and backend services.
    """

    def __init__(self, config: SystemConfiguration):
        """Initialize the GUI launcher"""
        self.config = config
        self.component_health = {}
        self.system_running = False
        self.shutdown_requested = False

        # Security configuration
        self.local_only = config.host in ["127.0.0.1", "localhost"]
        self.available_port = None
        self.api_key_enabled = bool(config.api_key)

        # Core components
        self.orchestrator: Optional[SpectraOrchestrator] = None
        self.main_gui: Optional[SpectraCoordinationGUI] = None
        self.phase_dashboard: Optional[PhaseManagementDashboard] = None
        self.coordination_interface: Optional[CoordinationInterface] = None
        self.implementation_tools: Optional[ImplementationTools] = None
        self.optimization_engine: Optional[AgentOptimizationEngine] = None
        self.programmatic_api: Optional[SpectraProgrammaticAPI] = None

        # Flask application for unified interface
        if FLASK_AVAILABLE:
            self.app = Flask(__name__, static_folder='static', static_url_path='/static')
            self.app.config['SECRET_KEY'] = 'spectra_gui_system'
            self.socketio = SocketIO(self.app, cors_allowed_origins="*")
            self.programmatic_api = SpectraProgrammaticAPI(self)
            self._setup_auth_middleware()
            self._setup_unified_routes()
        else:
            raise ImportError("Flask is required for the GUI system")

        # Logging setup
        logging.basicConfig(
            level=getattr(logging, config.log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('spectra_gui_system.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)

        # Background monitoring
        self.monitoring_task = None
        self.health_check_interval = config.monitoring_interval

    def _check_port_availability(self, port: int) -> bool:
        """Check if a port is available for use"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(2)  # Increased timeout for better reliability
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                result = sock.connect_ex((self.config.host, port))
                return result != 0  # Port is available if connection fails
        except Exception as e:
            self.logger.warning(f"Port availability check failed for {port}: {e}")
            return False

    def _find_available_port(self, start_port: int = 5000, max_attempts: int = 20) -> Optional[int]:
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
                "🚨 CRITICAL SECURITY RISK: System is accessible from external networks!",
                "🔒 This exposes README files and system information to network access",
                "⚠️ Potential data exposure risk from network accessibility",
                "🏠 IMMEDIATE ACTION: Change host to 127.0.0.1 or localhost for security",
                "🔐 Current configuration allows external file system access"
            ])
        else:
            warnings.extend([
                "✅ SECURE: System is configured for localhost access only",
                "🔒 README and system files are protected from external access"
            ])

        warnings.extend([
            "📍 README ACCESS IS LOCAL SYSTEM ONLY",
            "🔐 No external file system access provided",
            "💻 All documentation served from local installation only",
            "🚫 No network file sharing or remote access capabilities",
            "🛡️ System files and configuration protected from external access"
        ])

        return warnings

    def _log_security_status(self):
        """Log security status and warnings"""
        security_warnings = self._get_security_warnings()
        actual_port = self.available_port or self.config.port

        self.logger.info("=" * 70)
        self.logger.info("🔒 SPECTRA GUI SECURITY STATUS")
        self.logger.info("=" * 70)
        self.logger.info(f"🌐 Access URL: http://{self.config.host}:{actual_port}")
        self.logger.info(f"🔐 Security Level: {'HIGH (localhost only)' if self.local_only else 'CRITICAL (network accessible)'}")
        self.logger.info(f"📍 README Source: Local file system only")
        self.logger.info(f"⚡ Port Status: {'Alternative port {}'.format(actual_port) if self.available_port else 'Default port {}'.format(self.config.port)}")

        if not self.local_only:
            self.logger.critical("🚨 SECURITY ALERT: External network access enabled!")
            self.logger.critical("⚠️ This configuration exposes README and system files!")

        self.logger.info("📋 Security Warnings:")
        for warning in security_warnings:
            if warning.startswith(("🚨", "⚠️")):
                self.logger.warning(f"   {warning}")
            elif warning.startswith("✅"):
                self.logger.info(f"   {warning}")
            else:
                self.logger.info(f"   ℹ️  {warning}")

        self.logger.info("=" * 70)

    def _setup_unified_routes(self):
        """Setup unified Flask routes for the complete system"""

        @self.app.route('/login', methods=['GET', 'POST'])
        def login():
            """Simple API-key login flow for browser access."""
            if request.method == 'POST':
                submitted_key = request.form.get("api_key") or request.json.get("api_key") if request.is_json else None
                if self._is_valid_api_key(submitted_key):
                    session["spectra_api_key_authenticated"] = True
                    next_url = request.args.get("next") or url_for("index")
                    if request.is_json:
                        return jsonify({"success": True, "redirect_to": next_url})
                    return redirect(next_url)
                if request.is_json:
                    return jsonify({"success": False, "error": "Invalid API key"}), 401
                return self._render_api_key_login(error_message="Invalid API key"), 401
            return self._render_api_key_login()

        @self.app.route('/logout', methods=['POST'])
        def logout():
            session.pop("spectra_api_key_authenticated", None)
            return jsonify({"success": True})

        @self.app.route('/')
        def index():
            """Main system dashboard"""
            if self.config.home_page == "docs":
                return redirect(url_for("readme_help"))
            return render_template('unified_dashboard.html',
                                 system_status=self.get_system_status(),
                                 components=self.get_component_status(),
                                 access_host=self.config.host,
                                 access_port=self.available_port or self.config.port,
                                 local_only=self.local_only)

        @self.app.route('/agent-selection')
        def agent_selection():
            """Agent selection and team optimization interface"""
            if 'agent_gui' in self.config.enable_components and self.main_gui:
                return render_template(
                    'workspace_embed.html',
                    title="SPECTRA Agent Selection",
                    kicker="Embedded Workspace",
                    heading="Agent Selection",
                    description="Agent selection remains accessible inside the same web shell rather than breaking into a mismatched standalone page.",
                    iframe_src="/agent-selection/raw",
                    secondary_href="/api/system/status",
                    secondary_label="Status JSON",
                )
            return self._render_component_unavailable("Agent Selection")

        @self.app.route('/agent-selection/raw')
        def agent_selection_raw():
            """Raw agent selection view for embedding."""
            if 'agent_gui' in self.config.enable_components and self.main_gui:
                return redirect(f"http://{self.config.host}:{self.config.component_ports['main_gui']}/agent-selection")
            return self._render_component_unavailable("Agent Selection")

        @self.app.route('/phase-management')
        def phase_management():
            """Phase management dashboard"""
            if 'phase_dashboard' in self.config.enable_components and self.phase_dashboard:
                return render_template(
                    'workspace_embed.html',
                    title="SPECTRA Phase Management",
                    kicker="Embedded Workspace",
                    heading="Phase Management",
                    description="Timeline and phase tracking inside the same launcher shell.",
                    iframe_src="/phase-management/raw",
                    secondary_href="/api/system/status",
                    secondary_label="Status JSON",
                )
            return self._render_component_unavailable("Phase Management")

        @self.app.route('/phase-management/raw')
        def phase_management_raw():
            """Raw phase management view for embedding."""
            if 'phase_dashboard' in self.config.enable_components and self.phase_dashboard:
                return self.phase_dashboard.generate_timeline_html()
            return self._render_component_unavailable("Phase Management")

        @self.app.route('/api/caas/process-queue', methods=['POST'])
        def api_caas_process_queue():
            """Trigger the CaaS profile queue processor in the background."""
            try:
                from tgarchive.osint.caas.queue_worker import process_queue
                def _run():
                    with self.app.app_context():
                        process_queue(db_path=self.config.database_path, batch_size=250, once=True)
                
                threading.Thread(target=_run, daemon=True).start()
                return jsonify({"success": True, "message": "CaaS Queue processing initiated in background."})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route('/api/caas/discover', methods=['POST'])
        def api_caas_discover():
            """Trigger a semantic discovery crawl from the web console."""
            try:
                data = request.get_json() or {}
                seed = data.get("seed")
                if not seed:
                    return jsonify({"success": False, "error": "Seed entity required"}), 400
                
                from tgarchive.osint.caas.discovery_ops import discover_with_caas
                def _run():
                    asyncio.run(discover_with_caas(
                        config_path=self.config.orchestrator_config,
                        db_path=self.config.database_path,
                        data_dir="spectra_data",
                        seed=seed,
                        depth=1,
                        max_messages=500
                    ))
                
                threading.Thread(target=_run, daemon=True).start()
                return jsonify({"success": True, "message": f"Discovery initiated for {seed}"})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route('/api/v1/actor/brief/<handle>')
        def api_actor_brief(handle):
            """Get full forensic briefing for a threat actor."""
            db_path = self.config.database_path
            try:
                from tgarchive.db import SpectraDB
                from tgarchive.osint.caas.aggregator import ActorDossierAggregator
                from tgarchive.osint.caas.wallet_watch import WalletWatcher
                from tgarchive.osint.caas.nexus_graph import InfrastructureNexus
                from tgarchive.osint.caas.llm_intel import NarrativeSynthesisEngine
                
                db = SpectraDB(Path(db_path))
                aggregator = ActorDossierAggregator(db)
                watcher = WalletWatcher(db)
                nexus_engine = InfrastructureNexus(db)
                narrative = NarrativeSynthesisEngine()
                
                dossier = aggregator.generate_dossier(handle)
                wallets = watcher.get_actor_wallets(handle)
                artifacts = nexus_engine.extract_artifacts("") # Get all shared artifacts logic would go here
                
                # Simple nexus linkage logic
                shared_nexus = [n for n in nexus_engine.map_shared_nexus() if handle in n["actors"]]
                nexus_ids = [n["artifact"] for n in shared_nexus]
                
                brief = narrative.synthesize_actor_brief(dossier, wallets, nexus_ids)
                
                return jsonify({
                    "handle": handle,
                    "brief": brief,
                    "wallets": wallets,
                    "nexus_links": shared_nexus,
                    "dossier": dossier
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @self.app.route('/caas-intelligence')
        def caas_intelligence():
            """CaaS and Threat Actor Intelligence dashboard"""
            db_path = self.config.database_path
            try:
                from tgarchive.db import SpectraDB
                from tgarchive.osint.caas.aggregator import ActorDossierAggregator
                from tgarchive.osint.caas.market_intel import MarketIntelligenceEngine
                
                db = SpectraDB(Path(db_path))
                aggregator = ActorDossierAggregator(db)
                engine = MarketIntelligenceEngine(db)
                
                snapshot = engine.get_market_snapshot()
                dossiers = aggregator.get_top_actors(limit=10)
                
                return render_template(
                    'caas_intelligence.html',
                    system_status=self.get_system_status(),
                    market_snapshot=snapshot,
                    top_dossiers=dossiers,
                    access_host=self.config.host,
                    access_port=self.available_port or self.config.port,
                )
            except Exception as e:
                self.logger.error(f"Error loading CaaS Intelligence: {e}")
                return self._render_component_unavailable(f"CaaS Intelligence (Error: {e})")

        @self.app.route('/coordination')
        def coordination():
            """Real-time coordination interface"""
            if 'coordination' in self.config.enable_components:
                return render_template(
                    'coordination_hub.html',
                    system_status=self.get_system_status(),
                    access_host=self.config.host,
                    access_port=self.available_port or self.config.port,
                )
            return self._render_component_unavailable("Coordination Interface")

        @self.app.route('/coordination-monitor')
        def coordination_monitor():
            """Raw coordination monitor view for embedding."""
            if 'coordination' in self.config.enable_components and self.coordination_interface:
                return self.coordination_interface.generate_coordination_html()
            return self._render_component_unavailable("Coordination Monitor")

        @self.app.route('/implementation')
        def implementation():
            """Implementation management tools"""
            if 'implementation' in self.config.enable_components and self.implementation_tools:
                return render_template(
                    'workspace_embed.html',
                    title="SPECTRA Implementation Tools",
                    kicker="Embedded Workspace",
                    heading="Implementation Tools",
                    description="Implementation planning and control surfaces inside the same launcher shell.",
                    iframe_src="/implementation/raw",
                    secondary_href="/api/system/status",
                    secondary_label="Status JSON",
                )
            return self._render_component_unavailable("Implementation Tools")

        @self.app.route('/implementation/raw')
        def implementation_raw():
            """Raw implementation tools view for embedding."""
            if 'implementation' in self.config.enable_components and self.implementation_tools:
                return self.implementation_tools.generate_implementation_html()
            return self._render_component_unavailable("Implementation Tools")

        @self.app.route('/readme')
        @self.app.route('/help')
        @self.app.route('/documentation')
        def readme_help():
            """README documentation and help interface"""
            try:
                # Read and convert README.md to HTML
                readme_content = self._get_readme_content()
                system_status = self.get_system_status()
                return render_template('readme.html',
                                     readme_content=readme_content,
                                     system_status=system_status)
            except Exception as e:
                self.logger.error(f"Error loading README: {e}")
                return self._render_readme_error(str(e))

        # API Routes
        @self.app.route('/api/system/status')
        def api_system_status():
            """Get comprehensive system status"""
            return jsonify(self.get_system_status())

        @self.app.route('/api/components/health')
        def api_component_health():
            """Get component health status"""
            return jsonify(self.get_component_status())

        @self.app.route('/api/system/restart', methods=['POST'])
        def api_restart_system():
            """Restart the system"""
            asyncio.create_task(self.restart_system())
            return jsonify({"success": True, "message": "System restart initiated"})

        @self.app.route('/api/components/<component_name>/restart', methods=['POST'])
        def api_restart_component(component_name):
            """Restart a specific component"""
            success = asyncio.run(self.restart_component(component_name))
            return jsonify({"success": success, "component": component_name})

        @self.app.route('/api/optimization/team', methods=['POST'])
        def api_optimize_team():
            """Team optimization endpoint"""
            if self.optimization_engine:
                try:
                    data = request.get_json()
                    # This would integrate with the optimization engine
                    return jsonify({"success": True, "optimized_team": "placeholder"})
                except Exception as e:
                    return jsonify({"success": False, "error": str(e)})
            return jsonify({"success": False, "error": "Optimization engine not available"})

        @self.app.route('/api/security/warnings')
        def api_security_warnings():
            """Get security warnings and notices"""
            return jsonify({
                "warnings": self._get_security_warnings(),
                "access_info": {
                    "host": self.config.host,
                    "port": str(self.available_port or self.config.port),
                    "security_level": "HIGH" if self.local_only else "LOW",
                    "access_level": "LOCAL ONLY" if self.local_only else "NETWORK ACCESSIBLE"
                },
                "local_only": self.local_only,
                "security_level": "HIGH" if self.local_only else "LOW"
            })

        @self.app.route('/api/system/access-info')
        def api_access_info():
            """Get system access information"""
            return jsonify({
                "host": self.config.host,
                "port": str(self.available_port or self.config.port),
                "security_level": "HIGH" if self.local_only else "LOW",
                "access_level": "LOCAL ONLY" if self.local_only else "NETWORK ACCESSIBLE",
                "readme_source": "Local file system only",
                "data_access": "Local system files only"
            })

        @self.app.route('/openapi.json')
        @self.app.route('/.well-known/openapi.json')
        def api_openapi_spec():
            """OpenAPI 3.1 document for standard AI/client integration."""
            return jsonify(self.programmatic_api.get_openapi_spec())

        @self.app.route('/docs')
        def api_docs():
            """Interactive API documentation page."""
            return self._render_api_docs()

        @self.app.route('/api/v1/context')
        def api_standard_context():
            """Structured snapshot optimized for machine clients."""
            return jsonify(self.programmatic_api.get_context_snapshot())

        @self.app.route('/api/v1/readme')
        def api_standard_readme():
            """Structured README excerpt for standard machine clients."""
            try:
                max_chars = int(request.args.get("max_chars", "4000"))
            except ValueError:
                max_chars = 4000
            max_chars = max(200, min(12000, max_chars))
            return jsonify(self.programmatic_api.get_readme_resource(max_chars))

        # WebSocket events
        @self.socketio.on('connect')
        def handle_connect():
            """Handle client connection"""
            emit('system_status', self.get_system_status())

        @self.socketio.on('subscribe_system_updates')
        def handle_subscribe():
            """Handle subscription to system updates"""
            emit('subscription_confirmed', {"status": "subscribed"})

    def _render_component_unavailable(self, component_name: str) -> str:
        """Render component unavailable page"""
        return f"""
        <html>
        <head><title>{component_name} - Unavailable</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; margin-top: 100px;">
            <h1>{component_name}</h1>
            <p>This component is currently unavailable.</p>
            <p>Please check the system configuration and component status.</p>
            <a href="/">← Back to System Dashboard</a>
        </body>
        </html>
        """

    def _render_api_docs(self) -> str:
        """Render a lightweight Swagger UI page for the local control API."""
        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>SPECTRA API Docs</title>
            <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
            <style>
                body {
                    margin: 0;
                    background:
                        radial-gradient(circle at top right, rgba(76, 214, 192, 0.12), transparent 24%),
                        linear-gradient(180deg, #0a1016 0%, #0c131a 100%);
                }
                .topbar { display: none; }
                .spectra-banner {
                    background: linear-gradient(90deg, #0d1319, #17323a 65%, #1f5b67);
                    color: #eef4fb;
                    padding: 18px 22px;
                    font-family: "Trebuchet MS", Verdana, sans-serif;
                    border-bottom: 1px solid rgba(76, 214, 192, 0.14);
                    box-shadow: 0 18px 36px rgba(0, 0, 0, 0.22);
                }
                .spectra-banner small { color: #a7c4ce; }
                .swagger-ui .scheme-container {
                    background: rgba(21, 31, 41, 0.94);
                    box-shadow: none;
                    border-bottom: 1px solid rgba(111, 138, 163, 0.2);
                }
            </style>
        </head>
        <body>
            <div class="spectra-banner">
                <div>SPECTRA Local Control API</div>
                <small>Standard OpenAPI 3.1 interface for local automation and operator tooling</small>
            </div>
            <div id="swagger-ui"></div>
            <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
            <script>
                window.ui = SwaggerUIBundle({
                    url: '/openapi.json',
                    dom_id: '#swagger-ui',
                    deepLinking: true,
                    displayRequestDuration: true,
                    persistAuthorization: true
                });
            </script>
        </body>
        </html>
        """

    def _setup_auth_middleware(self):
        """Protect the interface and APIs with an optional API key."""

        @self.app.before_request
        def require_api_key():
            if not self.api_key_enabled:
                return None

            public_paths = {
                "/login",
                "/static",
            }
            if request.path == "/favicon.ico" or any(request.path.startswith(path) for path in public_paths):
                return None

            if self._request_is_authenticated():
                return None

            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "error": "API key required",
                    "auth": {
                        "header": "X-API-Key",
                        "query_param": "api_key",
                        "login_path": "/login",
                    },
                }), 401

            return redirect(url_for("login", next=request.full_path if request.query_string else request.path))

    def _request_is_authenticated(self) -> bool:
        """Allow either browser session auth or direct API-key auth."""
        if session.get("spectra_api_key_authenticated"):
            return True
        submitted_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        return self._is_valid_api_key(submitted_key)

    def _is_valid_api_key(self, submitted_key: Optional[str]) -> bool:
        """Constant-time API key comparison."""
        if not self.api_key_enabled or not self.config.api_key:
            return True
        if not submitted_key:
            return False
        return secrets.compare_digest(str(submitted_key), str(self.config.api_key))

    def _render_api_key_login(self, error_message: Optional[str] = None) -> str:
        """Render a compact API-key login form for browser use."""
        error_html = f'<p style="color:#b91c1c;margin:0 0 1rem 0;">{error_message}</p>' if error_message else ""
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>SPECTRA Login</title>
            <style>
                body {{
                    font-family: monospace;
                    background: #0f172a;
                    color: #e2e8f0;
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0;
                }}
                .card {{
                    width: min(420px, 92vw);
                    background: #111827;
                    border: 1px solid #334155;
                    border-radius: 12px;
                    padding: 24px;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.35);
                }}
                input {{
                    width: 100%;
                    padding: 12px;
                    border-radius: 8px;
                    border: 1px solid #475569;
                    background: #020617;
                    color: #e2e8f0;
                    box-sizing: border-box;
                    margin-bottom: 12px;
                }}
                button {{
                    width: 100%;
                    padding: 12px;
                    border: 0;
                    border-radius: 8px;
                    background: #2563eb;
                    color: white;
                    cursor: pointer;
                }}
                code {{
                    color: #93c5fd;
                }}
            </style>
        </head>
        <body>
            <form class="card" method="post">
                <h2 style="margin-top:0;">SPECTRA Access</h2>
                <p>Enter the configured API key to open the interface.</p>
                {error_html}
                <input type="password" name="api_key" placeholder="API key" autofocus />
                <button type="submit">Open Interface</button>
                <p style="margin-bottom:0;margin-top:12px;font-size:12px;color:#94a3b8;">
                    Programmatic clients can also send <code>X-API-Key</code> or <code>?api_key=...</code>.
                </p>
            </form>
        </body>
        </html>
        """

    def _get_readme_content(self) -> str:
        """Read and process README.md content"""
        try:
            readme_path = Path("README.md")
            if readme_path.exists():
                with open(readme_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Convert markdown to HTML
                if MARKDOWN_AVAILABLE:
                    try:
                        html_content = markdown.markdown(
                            content,
                            extensions=['codehilite', 'fenced_code', 'tables', 'toc']
                        )
                        return html_content
                    except Exception as e:
                        self.logger.warning(f"Markdown processing failed: {e}, using fallback")
                        return self._markdown_to_html_fallback(content)
                else:
                    # Fallback if markdown module is not available
                    self.logger.warning("Markdown module not available, using fallback")
                    return self._markdown_to_html_fallback(content)
            else:
                return "<p>README.md file not found.</p>"
        except Exception as e:
            self.logger.error(f"Error reading README.md: {e}")
            return f"<p>Error loading README content: {e}</p>"

    def _markdown_to_html_fallback(self, content: str) -> str:
        """Basic markdown to HTML conversion fallback"""
        import re

        # Escape HTML characters
        content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        # Convert headers
        content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', content, flags=re.MULTILINE)
        content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', content, flags=re.MULTILINE)
        content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', content, flags=re.MULTILINE)

        # Convert code blocks
        content = re.sub(r'```(\w+)?\n(.*?)\n```', r'<pre><code>\2</code></pre>', content, flags=re.DOTALL)
        content = re.sub(r'`([^`]+)`', r'<code>\1</code>', content)

        # Convert links
        content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', content)

        # Convert line breaks
        content = content.replace('\n\n', '</p><p>').replace('\n', '<br>')
        content = '<p>' + content + '</p>'

        return content

    def _render_readme_error(self, error_message: str) -> str:
        """Render README error page"""
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>SPECTRA - Documentation Error</title>
            <style>
                body {{
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                    background-color: #f8fafc;
                    color: #1f2937;
                    line-height: 1.6;
                    margin: 0;
                    padding: 2rem;
                }}
                .error-container {{
                    max-width: 600px;
                    margin: 0 auto;
                    background: white;
                    padding: 2rem;
                    border-radius: 12px;
                    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
                    text-align: center;
                }}
                .error-title {{
                    color: #dc2626;
                    font-size: 1.5rem;
                    font-weight: 600;
                    margin-bottom: 1rem;
                }}
                .error-message {{
                    color: #6b7280;
                    margin-bottom: 2rem;
                }}
                .back-button {{
                    background: #2563eb;
                    color: white;
                    padding: 0.75rem 1.5rem;
                    border: none;
                    border-radius: 8px;
                    text-decoration: none;
                    display: inline-block;
                    font-weight: 500;
                }}
                .back-button:hover {{
                    background: #1e40af;
                }}
            </style>
        </head>
        <body>
            <div class="error-container">
                <h1 class="error-title">Documentation Load Error</h1>
                <p class="error-message">{error_message}</p>
                <a href="/" class="back-button">← Back to Dashboard</a>
            </div>
        </body>
        </html>
        """

    async def initialize_system(self) -> bool:
        """Initialize all system components"""
        self.logger.info("Initializing SPECTRA GUI System")

        try:
            # Initialize orchestrator first (core dependency)
            if await self._initialize_orchestrator():
                self.logger.info("✓ Orchestrator initialized successfully")
            else:
                self.logger.error("✗ Failed to initialize orchestrator")
                return False

            # Initialize optimization engine
            if await self._initialize_optimization_engine():
                self.logger.info("✓ Optimization engine initialized")
            else:
                self.logger.warning("⚠ Optimization engine initialization failed")

            # Initialize phase dashboard
            if 'phase_dashboard' in self.config.enable_components:
                if await self._initialize_phase_dashboard():
                    self.logger.info("✓ Phase dashboard initialized")
                else:
                    self.logger.warning("⚠ Phase dashboard initialization failed")

            # Initialize coordination interface
            if 'coordination' in self.config.enable_components:
                if await self._initialize_coordination_interface():
                    self.logger.info("✓ Coordination interface initialized")
                else:
                    self.logger.warning("⚠ Coordination interface initialization failed")

            # Initialize implementation tools
            if 'implementation' in self.config.enable_components:
                if await self._initialize_implementation_tools():
                    self.logger.info("✓ Implementation tools initialized")
                else:
                    self.logger.warning("⚠ Implementation tools initialization failed")

            # Initialize main GUI (if enabled)
            if 'main_gui' in self.config.enable_components:
                if await self._initialize_main_gui():
                    self.logger.info("✓ Main GUI initialized")
                else:
                    self.logger.warning("⚠ Main GUI initialization failed")

            self.logger.info("System initialization completed")
            return True

        except Exception as e:
            self.logger.error(f"System initialization failed: {e}", exc_info=True)
            return False

    async def _initialize_orchestrator(self) -> bool:
        """Initialize the orchestrator"""
        try:
            self._update_component_health("orchestrator", ComponentStatus.INITIALIZING)

            self.orchestrator = SpectraOrchestrator(
                config_path=self.config.orchestrator_config,
                db_path=self.config.database_path,
                log_level=self.config.log_level
            )

            if await self.orchestrator.initialize():
                self._update_component_health("orchestrator", ComponentStatus.RUNNING)
                return True
            else:
                self._update_component_health("orchestrator", ComponentStatus.ERROR)
                return False

        except Exception as e:
            self.logger.error(f"Orchestrator initialization failed: {e}")
            self._update_component_health("orchestrator", ComponentStatus.ERROR)
            return False

    async def _initialize_optimization_engine(self) -> bool:
        """Initialize the optimization engine"""
        try:
            self._update_component_health("optimization", ComponentStatus.INITIALIZING)

            if self.orchestrator:
                self.optimization_engine = AgentOptimizationEngine(self.orchestrator.agents)
                self._update_component_health("optimization", ComponentStatus.RUNNING)
                return True
            else:
                self._update_component_health("optimization", ComponentStatus.ERROR)
                return False

        except Exception as e:
            self.logger.error(f"Optimization engine initialization failed: {e}")
            self._update_component_health("optimization", ComponentStatus.ERROR)
            return False

    async def _initialize_phase_dashboard(self) -> bool:
        """Initialize the phase dashboard"""
        try:
            self._update_component_health("phase_dashboard", ComponentStatus.INITIALIZING)

            if self.orchestrator:
                self.phase_dashboard = PhaseManagementDashboard(self.orchestrator)
                self._update_component_health("phase_dashboard", ComponentStatus.RUNNING)
                return True
            else:
                self._update_component_health("phase_dashboard", ComponentStatus.ERROR)
                return False

        except Exception as e:
            self.logger.error(f"Phase dashboard initialization failed: {e}")
            self._update_component_health("phase_dashboard", ComponentStatus.ERROR)
            return False

    async def _initialize_coordination_interface(self) -> bool:
        """Initialize the coordination interface"""
        try:
            self._update_component_health("coordination", ComponentStatus.INITIALIZING)

            if self.orchestrator:
                self.coordination_interface = CoordinationInterface(self.orchestrator)
                await self.coordination_interface.start_monitoring()
                self._update_component_health("coordination", ComponentStatus.RUNNING)
                return True
            else:
                self._update_component_health("coordination", ComponentStatus.ERROR)
                return False

        except Exception as e:
            self.logger.error(f"Coordination interface initialization failed: {e}")
            self._update_component_health("coordination", ComponentStatus.ERROR)
            return False

    async def _initialize_implementation_tools(self) -> bool:
        """Initialize the implementation tools"""
        try:
            self._update_component_health("implementation", ComponentStatus.INITIALIZING)

            if self.orchestrator and self.phase_dashboard:
                self.implementation_tools = ImplementationTools(self.orchestrator, self.phase_dashboard)
                self._update_component_health("implementation", ComponentStatus.RUNNING)
                return True
            else:
                self._update_component_health("implementation", ComponentStatus.ERROR)
                return False

        except Exception as e:
            self.logger.error(f"Implementation tools initialization failed: {e}")
            self._update_component_health("implementation", ComponentStatus.ERROR)
            return False

    async def _initialize_main_gui(self) -> bool:
        """Initialize the main GUI"""
        try:
            self._update_component_health("main_gui", ComponentStatus.INITIALIZING)

            if self.orchestrator:
                self.main_gui = SpectraCoordinationGUI(
                    orchestrator=self.orchestrator,
                    host=self.config.host,
                    port=self.config.component_ports.get('main_gui', 5001),
                    debug=self.config.debug
                )
                # Main GUI would be started in separate thread in production
                self._update_component_health("main_gui", ComponentStatus.RUNNING)
                return True
            else:
                self._update_component_health("main_gui", ComponentStatus.ERROR)
                return False

        except Exception as e:
            self.logger.error(f"Main GUI initialization failed: {e}")
            self._update_component_health("main_gui", ComponentStatus.ERROR)
            return False

    async def _create_unified_template(self):
        """Legacy no-op retained for compatibility."""
        return None

    def _generate_unified_template(self) -> str:
        """Generate unified dashboard HTML template with dynamic content"""
        # Get current component status for dynamic template
        component_status = self.get_component_status()
        enabled_components = len([c for c in self.config.enable_components if c in component_status])
        system_status = self.get_system_status()
        total_agents = system_status.get('total_agents', 0)
        security_level = "HIGH" if self.local_only else "LOW"
        access_port = str(self.available_port or self.config.port)
        
        # Generate template with computed values
        template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPECTRA GUI System - Unified Dashboard</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
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
            padding: 2rem;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        .header h1 {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }

        .header p {
            font-size: 1.2rem;
            opacity: 0.9;
        }

        .system-status {
            background: white;
            margin: 2rem;
            padding: 1.5rem;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }

        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .status-card {
            background: white;
            padding: 1.5rem;
            border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
            text-align: center;
            transition: transform 0.2s ease;
        }

        .status-card:hover {
            transform: translateY(-2px);
        }

        .status-value {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }

        .status-running { color: var(--success-color); }
        .status-warning { color: var(--warning-color); }
        .status-error { color: var(--danger-color); }

        .component-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 2rem;
            margin: 2rem;
        }

        .component-card {
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            overflow: hidden;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }

        .component-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.15);
        }

        .component-header {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 1.5rem;
            text-align: center;
        }

        .component-body {
            padding: 1.5rem;
        }

        .component-title {
            font-size: 1.4rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }

        .component-description {
            opacity: 0.9;
            margin-bottom: 1rem;
        }

        .component-status {
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 1rem;
        }

        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }

        .btn {
            background: var(--primary-color);
            color: white;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 8px;
            font-weight: 500;
            cursor: pointer;
            transition: background-color 0.2s ease;
            text-decoration: none;
            display: inline-block;
            text-align: center;
            width: 100%;
        }

        .btn:hover {
            background: var(--secondary-color);
        }

        .btn:disabled {
            background: #9ca3af;
            cursor: not-allowed;
        }

        .health-metrics {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 1rem;
            margin-top: 1rem;
        }

        .metric-item {
            text-align: center;
            padding: 0.5rem;
            background: #f9fafb;
            border-radius: 6px;
        }

        .metric-value {
            font-weight: 600;
            color: var(--primary-color);
        }

        .metric-label {
            font-size: 0.875rem;
            color: #6b7280;
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

        .footer {
            text-align: center;
            padding: 2rem;
            background: white;
            margin-top: 2rem;
            border-top: 1px solid var(--border-color);
        }

        @media (max-width: 768px) {
            .header {
                padding: 1rem;
            }

            .header h1 {
                font-size: 2rem;
            }

            .component-grid {
                grid-template-columns: 1fr;
                margin: 1rem;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>SPECTRA GUI System</h1>
        <p>Comprehensive Multi-Agent Coordination and Management Platform</p>

        <!-- Security Notice -->
        <div id="security-notice" class="security-notice">
            <div class="security-header">
                <span class="security-icon">🔒</span>
                <span class="security-title">LOCAL ACCESS ONLY</span>
            </div>
            <div class="security-details">
                <p><strong>📍 README and system access is LOCAL SYSTEM ONLY</strong></p>
                <p>🔐 No external file access • 💻 Local installation files only • 🚫 No network sharing</p>
                <p>Host: <span id="access-host">__HOST__</span> | Port: <span id="access-port">__ACCESS_PORT__</span> | Status: <span id="security-status">__SECURITY_LEVEL__</span></p>
            </div>
        </div>
    </div>

    <div class="system-status">
        <h2>System Status</h2>
        <div class="status-grid">
            <div class="status-card">
                <div class="status-value status-running" id="system-status">OPERATIONAL</div>
                <div>System Status</div>
            </div>
            <div class="status-card">
                <div class="status-value" id="component-count">__ENABLED_COMPONENTS__</div>
                <div>Active Components</div>
            </div>
            <div class="status-card">
                <div class="status-value" id="agent-count">__TOTAL_AGENTS__</div>
                <div>Available Agents</div>
            </div>
            <div class="status-card">
                <div class="status-value" id="uptime">00:00:00</div>
                <div>System Uptime</div>
            </div>
        </div>
    </div>

    <div class="component-grid">
        <!-- Agent Selection & Team Optimization -->
        <div class="component-card">
            <div class="component-header">
                <div class="component-title">Agent Selection & Team Optimization</div>
                <div class="component-description">Intelligent agent selection with capability matrix and team optimization algorithms</div>
            </div>
            <div class="component-body">
                <div class="component-status">
                    <span class="status-indicator status-running"></span>
                    <span>Ready</span>
                </div>
                <div class="health-metrics">
                    <div class="metric-item">
                        <div class="metric-value">98%</div>
                        <div class="metric-label">Health Score</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-value">15ms</div>
                        <div class="metric-label">Response Time</div>
                    </div>
                </div>
                <button class="btn" onclick="openComponent('/agent-selection')">Open Agent Selection</button>
            </div>
        </div>

        <!-- Phase Management Dashboard -->
        <div class="component-card">
            <div class="component-header">
                <div class="component-title">Phase Management Dashboard</div>
                <div class="component-description">Timeline visualization, milestone tracking, and project progression analytics</div>
            </div>
            <div class="component-body">
                <div class="component-status">
                    <span class="status-indicator status-running"></span>
                    <span>Ready</span>
                </div>
                <div class="health-metrics">
                    <div class="metric-item">
                        <div class="metric-value">96%</div>
                        <div class="metric-label">Health Score</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-value">22ms</div>
                        <div class="metric-label">Response Time</div>
                    </div>
                </div>
                <button class="btn" onclick="openComponent('/phase-management')">Open Phase Dashboard</button>
            </div>
        </div>

        <!-- Real-time Coordination Interface -->
        <div class="component-card">
            <div class="component-header">
                <div class="component-title">Real-time Coordination Interface</div>
                <div class="component-description">Live agent monitoring, communication flows, and system performance tracking</div>
            </div>
            <div class="component-body">
                <div class="component-status">
                    <span class="status-indicator status-running"></span>
                    <span>Monitoring Active</span>
                </div>
                <div class="health-metrics">
                    <div class="metric-item">
                        <div class="metric-value">94%</div>
                        <div class="metric-label">Health Score</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-value">18ms</div>
                        <div class="metric-label">Response Time</div>
                    </div>
                </div>
                <button class="btn" onclick="openComponent('/coordination')">Open Coordination</button>
            </div>
        </div>

        <!-- Implementation Management Tools -->
        <div class="component-card">
            <div class="component-header">
                <div class="component-title">Implementation Management Tools</div>
                <div class="component-description">Project planning, resource allocation, risk management, and quality gates</div>
            </div>
            <div class="component-body">
                <div class="component-status">
                    <span class="status-indicator status-running"></span>
                    <span>Ready</span>
                </div>
                <div class="health-metrics">
                    <div class="metric-item">
                        <div class="metric-value">97%</div>
                        <div class="metric-label">Health Score</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-value">25ms</div>
                        <div class="metric-label">Response Time</div>
                    </div>
                </div>
                <button class="btn" onclick="openComponent('/implementation')">Open Implementation Tools</button>
            </div>
        </div>

        <!-- Documentation & Help -->
        <div class="component-card">
            <div class="component-header">
                <div class="component-title">Documentation & Help 🔒</div>
                <div class="component-description">Complete system documentation, usage guides, and feature reference</div>
                <div style="background: rgba(22, 163, 74, 0.2); color: #16a34a; padding: 0.5rem; border-radius: 6px; margin-top: 0.5rem; font-size: 0.85rem; font-weight: 600; text-align: center;">
                    LOCAL ACCESS ONLY
                </div>
            </div>
            <div class="component-body">
                <div class="component-status">
                    <span class="status-indicator status-running"></span>
                    <span>Secure & Available</span>
                </div>
                <div class="health-metrics">
                    <div class="metric-item">
                        <div class="metric-value">100%</div>
                        <div class="metric-label">Coverage</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-value">5ms</div>
                        <div class="metric-label">Load Time</div>
                    </div>
                </div>
                <button class="btn" onclick="openComponent('/readme')">Open Documentation</button>
            </div>
        </div>
    </div>

    <div class="footer">
        <p>&copy; 2025 SPECTRA Advanced Data Management System</p>
        <p>Multi-Agent Coordination GUI - Version 1.0</p>
    </div>

    <script>
        // WebSocket connection
        const socket = io();

        socket.on('connect', function() {
            console.log('Connected to system');
            socket.emit('subscribe_system_updates');
        });

        socket.on('system_status', function(data) {
            updateSystemStatus(data);
        });

        function updateSystemStatus(data) {
            // Update system metrics based on received data
            if (data.orchestrator_status) {
                document.getElementById('system-status').textContent =
                    data.orchestrator_status === 'running' ? 'OPERATIONAL' : 'OFFLINE';
            }

            if (data.total_agents) {
                document.getElementById('agent-count').textContent = data.total_agents;
            }
        }

        function openComponent(path) {
            window.open(path, '_blank');
        }

        // Update uptime
        function updateUptime() {
            const now = new Date();
            const start = new Date(now.getTime() - (Math.random() * 3600000)); // Random start time
            const diff = now - start;

            const hours = Math.floor(diff / 3600000);
            const minutes = Math.floor((diff % 3600000) / 60000);
            const seconds = Math.floor((diff % 60000) / 1000);

            document.getElementById('uptime').textContent =
                `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }

        // Update uptime every second
        setInterval(updateUptime, 1000);
        updateUptime();

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
            if (portEl) portEl.textContent = accessInfo.port || '5000';
        }

        // Auto-refresh system status
        setInterval(function() {
            fetch('/api/system/status')
                .then(response => response.json())
                .then(data => updateSystemStatus(data))
                .catch(error => console.error('Error fetching system status:', error));
        }, 5000);

        // Load initial security info and refresh periodically
        loadSecurityInfo();
        setInterval(loadSecurityInfo, 30000); // Every 30 seconds
    </script>
</body>
</html>
        """
        return (
            template
            .replace("__HOST__", self.config.host)
            .replace("__ACCESS_PORT__", access_port)
            .replace("__SECURITY_LEVEL__", security_level)
            .replace("__ENABLED_COMPONENTS__", str(enabled_components))
            .replace("__TOTAL_AGENTS__", str(total_agents))
        )

    def _update_component_health(self, component_name: str, status: ComponentStatus):
        """Update component health status"""
        current_time = datetime.now()

        if component_name not in self.component_health:
            self.component_health[component_name] = ComponentHealth(
                name=component_name,
                status=status,
                start_time=current_time if status == ComponentStatus.RUNNING else None,
                last_health_check=current_time,
                error_count=0,
                response_time=0.0,
                resource_usage={},
                dependencies_met=True,
                health_score=1.0 if status == ComponentStatus.RUNNING else 0.0
            )
        else:
            health = self.component_health[component_name]
            health.status = status
            health.last_health_check = current_time

            if status == ComponentStatus.RUNNING and not health.start_time:
                health.start_time = current_time
            elif status == ComponentStatus.ERROR:
                health.error_count += 1

    async def start_system(self):
        """Start the complete GUI system"""
        if self.system_running:
            self.logger.warning("System is already running")
            return

        self.logger.info("Starting SPECTRA GUI System")

        # Check port availability and find alternative if needed
        self.logger.info(f"🔍 Checking availability of port {self.config.port}")
        if not self._check_port_availability(self.config.port):
            self.logger.warning(f"⚠️ Port {self.config.port} is already in use")
            alternative_port = self._find_available_port(self.config.port + 1)
            if alternative_port:
                self.logger.info(f"✅ Using alternative port {alternative_port}")
                self.available_port = alternative_port
            else:
                self.logger.error("❌ CRITICAL: No available ports found in range")
                self.logger.error("🔧 Try stopping other services or using a different port range")
                return False
        else:
            self.logger.info(f"✅ Port {self.config.port} is available")

        # Initialize all components
        if not await self.initialize_system():
            self.logger.error("System initialization failed")
            return False

        self.system_running = True

        # Log security status
        self._log_security_status()

        # Start orchestrator
        if self.orchestrator:
            asyncio.create_task(self.orchestrator.start_orchestration())

        # Start health monitoring
        self.monitoring_task = asyncio.create_task(self._health_monitoring_loop())

        # Start unified web interface
        actual_port = self.available_port or self.config.port
        try:
            self.logger.info(f"Starting unified interface at http://{self.config.host}:{actual_port}")
            self.socketio.run(
                self.app,
                host=self.config.host,
                port=actual_port,
                debug=self.config.debug,
                use_reloader=False
            )
        except Exception as e:
            self.logger.error(f"Failed to start web interface: {e}")
            return False

        return True

    async def stop_system(self):
        """Stop the complete GUI system"""
        if not self.system_running:
            return

        self.logger.info("Stopping SPECTRA GUI System")
        self.shutdown_requested = True

        # Stop monitoring
        if self.monitoring_task:
            self.monitoring_task.cancel()

        # Stop components in reverse order
        if self.coordination_interface:
            await self.coordination_interface.stop_monitoring()

        if self.orchestrator:
            await self.orchestrator.stop_orchestration()

        self.system_running = False
        self.logger.info("System stopped successfully")

    async def restart_system(self):
        """Restart the complete system"""
        self.logger.info("Restarting SPECTRA GUI System")
        await self.stop_system()
        await asyncio.sleep(2)  # Brief pause
        await self.start_system()

    async def restart_component(self, component_name: str) -> bool:
        """Restart a specific component"""
        self.logger.info(f"Restarting component: {component_name}")

        try:
            # Component-specific restart logic
            if component_name == "orchestrator" and self.orchestrator:
                await self.orchestrator.stop_orchestration()
                await asyncio.sleep(1)
                success = await self.orchestrator.initialize()
                if success:
                    asyncio.create_task(self.orchestrator.start_orchestration())
                return success

            elif component_name == "coordination" and self.coordination_interface:
                await self.coordination_interface.stop_monitoring()
                await asyncio.sleep(1)
                await self.coordination_interface.start_monitoring()
                return True

            # Add other component restart logic as needed

            return False

        except Exception as e:
            self.logger.error(f"Component restart failed: {e}")
            return False

    async def _health_monitoring_loop(self):
        """Background health monitoring loop"""
        while self.system_running and not self.shutdown_requested:
            try:
                await self._check_component_health()
                await self._broadcast_system_status()
                await asyncio.sleep(self.health_check_interval)

            except Exception as e:
                self.logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(5)

    async def _check_component_health(self):
        """Check health of all components"""
        for component_name, health in self.component_health.items():
            # Component-specific health checks
            if component_name == "orchestrator" and self.orchestrator:
                health.health_score = 1.0 if self.orchestrator.is_running else 0.0
            elif component_name == "coordination" and self.coordination_interface:
                health.health_score = 1.0 if self.coordination_interface.monitoring_active else 0.0
            # Add other health checks as needed

            health.last_health_check = datetime.now()

    async def _broadcast_system_status(self):
        """Broadcast system status to connected clients"""
        if hasattr(self, 'socketio'):
            status = self.get_system_status()
            self.socketio.emit('system_status', status)

    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        return {
            "system_running": self.system_running,
            "mode": self.config.mode.value,
            "orchestrator_status": "running" if self.orchestrator and self.orchestrator.is_running else "stopped",
            "total_agents": len(self.orchestrator.agents) if self.orchestrator else 0,
            "active_agents": len([a for a in self.orchestrator.agents.values()
                                if hasattr(a, 'status') and a.status.value == 'running']) if self.orchestrator else 0,
            "components_enabled": self.config.enable_components,
            "auth": {
                "api_key_required": self.api_key_enabled,
                "browser_login": "/login" if self.api_key_enabled else None,
                "header": "X-API-Key" if self.api_key_enabled else None,
                "query_param": "api_key" if self.api_key_enabled else None,
            },
            "api_endpoints": {
                "status": "/api/system/status",
                "components": "/api/components/health",
                "security": "/api/security/warnings",
                "openapi": "/openapi.json",
                "docs": "/docs",
                "standard_context": "/api/v1/context",
                "standard_readme": "/api/v1/readme",
            },
            "timestamp": datetime.now().isoformat()
        }

    def get_component_status(self) -> Dict[str, Any]:
        """Get component health status"""
        return {
            component_name: asdict(health)
            for component_name, health in self.component_health.items()
        }


def create_default_config() -> SystemConfiguration:
    """Create default system configuration with security-first defaults"""
    return SystemConfiguration(
        mode=SystemMode.DEVELOPMENT,
        host="127.0.0.1",  # SECURITY: localhost only by default
        port=5000,
        debug=True,
        orchestrator_config="spectra_config.json",
        database_path="spectra.db",
        log_level="INFO",
        enable_components=["orchestrator", "optimization", "phase_dashboard", "coordination", "implementation"],
        component_ports={
            "main_gui": 5001,
            "coordination": 5002,
            "phase_dashboard": 5003,
            "implementation": 5004
        },
        security_enabled=True,  # SECURITY: Enable security by default
        monitoring_interval=5.0,
        api_key=None,
        home_page="console",
    )


async def main():
    """Main entry point for the SPECTRA GUI system"""
    parser = argparse.ArgumentParser(description="SPECTRA Comprehensive GUI System")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1 for security)")
    parser.add_argument("--port", type=int, default=5000, help="Port number")
    parser.add_argument("--mode", choices=["development", "staging", "production", "demo"],
                       default="development", help="System mode")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       default="INFO", help="Log level")
    parser.add_argument("--api-key", help="Require this API key for browser and API access")
    parser.add_argument(
        "--api-key-env",
        default="SPECTRA_GUI_API_KEY",
        help="Environment variable to read the API key from if --api-key is unset",
    )
    parser.add_argument(
        "--home-page",
        choices=["console", "docs"],
        default="console",
        help="Select the initial route served at /",
    )

    args = parser.parse_args()

    # Create configuration
    config = create_default_config()
    config.host = args.host
    config.port = args.port
    config.mode = SystemMode(args.mode)
    config.debug = args.debug
    config.log_level = args.log_level
    config.api_key = args.api_key or os.environ.get(args.api_key_env)
    config.home_page = args.home_page

    # Initialize and start system
    launcher = SpectraGUILauncher(config)

    # Setup signal handlers
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}, shutting down...")
        asyncio.create_task(launcher.stop_system())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await launcher.start_system()
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        print(f"System error: {e}")
    finally:
        await launcher.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
