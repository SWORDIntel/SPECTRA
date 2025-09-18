# SPECTRA GUI System
**Comprehensive Multi-Agent Coordination and Management Platform**

<p align="center">
  <img src="SPECTRA.png" alt="SPECTRA GUI" width="35%">
</p>

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [GUI Components](#gui-components)
- [Configuration](#configuration)
- [Usage Guide](#usage-guide)
- [API Reference](#api-reference)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Support](#support)

## Overview

The SPECTRA GUI System is a sophisticated web-based interface for managing and coordinating multi-agent workflows across the 4-phase SPECTRA advanced data management implementation. It provides real-time monitoring, intelligent team optimization, phase management, and comprehensive orchestration capabilities through an intuitive and responsive web interface.

### Key Capabilities

- **🎯 Agent Selection & Team Optimization** - Intelligent agent selection with capability matrix analysis and automated team composition optimization
- **📊 Phase Management Dashboard** - Timeline visualization, milestone tracking, and project progression analytics with Gantt chart support
- **⚡ Real-time Coordination Interface** - Live agent monitoring, communication flows, and system performance tracking with WebSocket support
- **🛠️ Implementation Management Tools** - Project planning, resource allocation, risk management, and quality gates
- **🚀 Unified System Launcher** - Complete system orchestration with health monitoring and component management

## System Architecture

### Core Components

```
SPECTRA GUI System
├── 🎛️ Unified System Launcher (spectra_gui_launcher.py)
│   ├── Component orchestration and health monitoring
│   ├── Configuration management and error handling
│   ├── Cross-component communication
│   └── Performance monitoring and system initialization
│
├── 🎯 Agent Coordination GUI (spectra_coordination_gui.py)
│   ├── Agent selection interface with capability matrix
│   ├── Team optimization with multi-criteria algorithms
│   ├── Real-time coordination monitoring
│   └── WebSocket-based live updates
│
├── 📊 Phase Management Dashboard (phase_management_dashboard.py)
│   ├── Interactive timeline with Gantt chart visualization
│   ├── Milestone tracking with dependency management
│   ├── Resource allocation and utilization monitoring
│   └── Progress analytics with predictive modeling
│
├── 🤖 SPECTRA Orchestrator (spectra_orchestrator.py)
│   ├── Multi-agent workflow coordination
│   ├── Task scheduling and execution management
│   ├── Agent health monitoring and load balancing
│   └── Integration with SPECTRA core system
│
└── ⚙️ Supporting Components
    ├── Orchestration workflows and patterns
    ├── Agent optimization engine
    ├── Implementation tools and utilities
    └── Coordination interface and communication
```

### Technology Stack

- **Backend**: Python 3.8+ with Flask and SocketIO
- **Frontend**: Modern HTML5, CSS3, JavaScript (ES6+)
- **Visualization**: Plotly.js, Chart.js for interactive charts
- **Real-time Communication**: WebSocket with Flask-SocketIO
- **Database**: SQLite with SPECTRA database integration
- **Deployment**: Production-ready with Docker support

## Features

### 🎯 Agent Selection & Team Optimization

- **Intelligent Agent Discovery**: Automatic discovery and registration of all available agents
- **Capability Matrix Analysis**: Detailed agent capability assessment with performance metrics
- **Multi-Criteria Optimization**: Team composition optimization based on performance, cost, reliability, speed, and quality
- **Resource Planning**: Intelligent resource allocation and workload distribution
- **Success Prediction**: Team success probability calculation with risk factor analysis

### 📊 Phase Management Dashboard

- **Interactive Timeline**: Gantt chart visualization with phase dependencies and milestones
- **Milestone Tracking**: Comprehensive milestone management with completion criteria
- **Progress Analytics**: Real-time progress tracking with predictive modeling
- **Resource Utilization**: Monitoring and optimization of resource allocation across phases
- **Risk Management**: Risk assessment and mitigation tracking with automated alerts

### ⚡ Real-time Coordination Interface

- **Live Agent Monitoring**: Real-time agent status, health metrics, and performance tracking
- **Communication Flows**: Visual representation of agent interactions and message routing
- **System Performance**: Comprehensive system load, throughput, and latency monitoring
- **Event Streaming**: Real-time coordination events with filtering and search capabilities
- **Alert Management**: Intelligent alerting system with customizable notification rules

### 🛠️ Implementation Management Tools

- **Project Planning**: Comprehensive project planning with dependency management
- **Quality Gates**: Automated quality assurance checkpoints and validation rules
- **Deployment Tracking**: Deployment pipeline monitoring and rollback capabilities
- **Documentation**: Integrated documentation generation and maintenance
- **Reporting**: Advanced reporting and analytics with exportable dashboards

### 🚀 Unified System Management

- **Component Health Monitoring**: Real-time health checks and component status tracking
- **Configuration Management**: Centralized configuration with environment-specific settings
- **Error Handling & Recovery**: Intelligent error detection with automatic recovery mechanisms
- **Performance Optimization**: System-wide performance monitoring and optimization recommendations
- **Security**: Role-based access control and secure communication protocols

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager
- Node.js (optional, for advanced frontend development)
- Git (for cloning the repository)

### Core Installation

```bash
# Clone the SPECTRA repository
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install core dependencies
pip install flask flask-socketio pandas numpy plotly
pip install telethon rich pillow networkx matplotlib python-magic

# Install SPECTRA package in development mode
pip install -e .
```

### Complete Installation (Recommended)

```bash
# Install all dependencies including optional packages
pip install -r requirements.txt

# Verify installation
python -c "import tgarchive; print('SPECTRA installed successfully')"
```

### Docker Installation (Production)

```bash
# Build Docker image
docker build -t spectra-gui .

# Run with Docker Compose
docker-compose up -d

# Access GUI at http://localhost:5000
```

## Quick Start

### 1. Basic Configuration

Create or update your `spectra_config.json`:

```json
{
  "accounts": [
    {
      "api_id": "your_api_id",
      "api_hash": "your_api_hash",
      "session_name": "primary_account",
      "phone_number": "+1234567890"
    }
  ],
  "gui": {
    "host": "0.0.0.0",
    "port": 5000,
    "debug": false
  },
  "orchestrator": {
    "max_concurrent_tasks": 10,
    "health_check_interval": 30
  }
}
```

### 2. Launch the GUI System

```bash
# Start the unified GUI launcher
python -m spectra_gui_launcher

# Or start with specific configuration
python -m spectra_gui_launcher --config custom_config.json --port 8080

# For development with debug mode
python -m spectra_gui_launcher --debug --log-level DEBUG
```

### 3. Access the Interface

Open your browser and navigate to:
- **Primary Interface**: http://localhost:5000
- **Agent Selection**: http://localhost:5000/agent-selection
- **Phase Management**: http://localhost:5000/phase-management
- **Coordination Monitor**: http://localhost:5000/coordination
- **Implementation Tools**: http://localhost:5000/implementation

### 4. First-Time Setup

1. **Configure Telegram Accounts**: Import your Telegram API credentials
2. **Initialize Database**: Set up the SPECTRA database schema
3. **Test Connectivity**: Verify agent connections and system health
4. **Create First Workflow**: Start with a simple discovery workflow

## GUI Components

### Main Dashboard

The unified dashboard provides a comprehensive overview of the entire SPECTRA system:

- **System Status Cards**: Real-time metrics for agents, workflows, and system load
- **Phase Progress Timeline**: Visual representation of project phases with completion status
- **Active Agents List**: Current agent status with health indicators
- **Performance Charts**: Historical performance data with trend analysis
- **Recent Activity Feed**: Latest coordination events and system notifications

### Agent Selection Interface

Advanced agent management and team optimization:

```python
# Example: Accessing agent capabilities
{
  "agent_name": "DATABASE",
  "capabilities": ["postgresql", "optimization", "backup"],
  "performance_metrics": {
    "success_rate": 0.95,
    "avg_execution_time": 45.2,
    "reliability_score": 0.88
  },
  "availability_score": 0.92,
  "current_load": 0.3
}
```

### Phase Management Dashboard

Comprehensive project timeline and milestone tracking:

- **Gantt Chart Visualization**: Interactive timeline with drag-and-drop milestone editing
- **Dependency Management**: Visual dependency mapping with critical path analysis
- **Resource Allocation**: Team assignments and resource utilization tracking
- **Progress Tracking**: Real-time progress updates with completion predictions

### Real-time Coordination Interface

Live monitoring and communication management:

- **Agent Status Grid**: Real-time agent health and performance metrics
- **Communication Flow**: Visual representation of agent-to-agent communications
- **Event Timeline**: Chronological view of coordination events
- **Performance Metrics**: System throughput, latency, and error rates

## Configuration

### System Configuration

The GUI system uses a hierarchical configuration approach:

```json
{
  "system": {
    "mode": "production",
    "host": "0.0.0.0",
    "port": 5000,
    "debug": false,
    "log_level": "INFO"
  },
  "components": {
    "orchestrator": true,
    "optimization_engine": true,
    "phase_dashboard": true,
    "coordination_interface": true,
    "implementation_tools": true
  },
  "monitoring": {
    "health_check_interval": 5.0,
    "performance_metrics": true,
    "alert_thresholds": {
      "cpu_usage": 0.8,
      "memory_usage": 0.9,
      "error_rate": 0.05
    }
  }
}
```

### Environment Variables

```bash
# Core settings
export SPECTRA_CONFIG_PATH="/path/to/spectra_config.json"
export SPECTRA_DB_PATH="/path/to/spectra.db"
export SPECTRA_LOG_LEVEL="INFO"

# GUI-specific settings
export SPECTRA_GUI_HOST="0.0.0.0"
export SPECTRA_GUI_PORT="5000"
export SPECTRA_GUI_DEBUG="false"

# Security settings
export SPECTRA_SECRET_KEY="your-secret-key"
export SPECTRA_CORS_ORIGINS="*"
```

### Component Configuration

Individual components can be configured separately:

```python
# Agent optimization settings
optimization_config = {
    "criteria": ["performance", "reliability", "cost"],
    "algorithm": "multi_objective",
    "constraints": {
        "max_team_size": 8,
        "min_success_rate": 0.8
    }
}

# Phase management settings
phase_config = {
    "timeline_resolution": "daily",
    "milestone_alerts": True,
    "dependency_validation": True,
    "progress_prediction": True
}
```

## Usage Guide

### Starting a New Project

1. **Configure Project Parameters**:
   ```python
   project_config = {
       "name": "SPECTRA Implementation Phase 1",
       "duration_weeks": 4,
       "priority": "high",
       "required_capabilities": [
           "database_management",
           "performance_optimization",
           "system_architecture"
       ]
   }
   ```

2. **Select and Optimize Team**:
   - Use the Agent Selection interface to browse available agents
   - Run team optimization algorithms based on your criteria
   - Review and approve the recommended team composition

3. **Create Project Timeline**:
   - Define project phases and milestones
   - Set dependencies and resource requirements
   - Configure alerts and notification rules

4. **Launch Execution**:
   - Start the orchestrator with your configured workflow
   - Monitor progress through the real-time coordination interface
   - Track milestones and adjust resources as needed

### Managing Agent Teams

#### Viewing Agent Capabilities

```bash
# Access agent information via API
curl http://localhost:5000/api/agents/capabilities
```

#### Optimizing Team Composition

```javascript
// Request team optimization
const optimizationRequest = {
    phase: "phase1",
    criteria: "performance",
    constraints: {
        max_cost: 1000,
        min_success_rate: 0.9
    }
};

fetch('/api/teams/optimize', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(optimizationRequest)
});
```

### Monitoring System Performance

#### Real-time Metrics

The GUI provides comprehensive real-time monitoring:

- **System Load**: CPU, memory, and network utilization
- **Agent Performance**: Success rates, execution times, error counts
- **Workflow Progress**: Completion percentages, milestone status
- **Communication Health**: Message throughput, latency, error rates

#### Custom Dashboards

Create custom monitoring dashboards:

```python
custom_dashboard = {
    "name": "Production Monitoring",
    "widgets": [
        {"type": "metric", "source": "system.cpu_usage"},
        {"type": "chart", "source": "agents.success_rate"},
        {"type": "timeline", "source": "workflows.progress"}
    ]
}
```

### Advanced Workflows

#### Parallel Phase Execution

```python
# Configure parallel phase execution
parallel_config = {
    "phases": ["phase1", "phase2"],
    "execution_mode": "parallel",
    "synchronization_points": ["milestone_1", "milestone_3"],
    "resource_sharing": "dynamic"
}
```

#### Conditional Workflows

```python
# Set up conditional workflow execution
conditional_workflow = {
    "condition": "phase1.success_rate > 0.9",
    "then": "execute_phase2",
    "else": "retry_phase1_with_different_team"
}
```

## API Reference

### REST API Endpoints

#### System Status

```http
GET /api/system/status
Response: {
    "orchestrator_status": "running",
    "total_agents": 25,
    "active_workflows": 3,
    "system_load": 0.45,
    "last_update": "2025-09-18T10:30:00Z"
}
```

#### Agent Management

```http
GET /api/agents
GET /api/agents/capabilities
POST /api/teams/optimize
POST /api/teams/create
```

#### Phase Management

```http
GET /api/phases
GET /api/phases/{phase_id}/progress
POST /api/phases/{phase_id}/start
PUT /api/phases/{phase_id}/update
```

#### Workflow Management

```http
GET /api/workflows
POST /api/workflows/submit
GET /api/workflows/{workflow_id}/status
POST /api/workflows/{workflow_id}/pause
POST /api/workflows/{workflow_id}/resume
```

### WebSocket Events

#### Real-time Updates

```javascript
// Connect to WebSocket
const socket = io();

// Subscribe to system updates
socket.emit('subscribe_updates', {type: 'system_status'});

// Handle real-time updates
socket.on('real_time_update', (data) => {
    updateSystemMetrics(data.system_status);
    updateAgentList(data.agent_status);
    updatePhaseProgress(data.phase_progress);
});

// Handle coordination events
socket.on('coordination_event', (event) => {
    displayCoordinationEvent(event);
});
```

#### Agent Interaction

```javascript
// Send agent interaction
socket.emit('agent_interaction', {
    agent: 'DATABASE',
    action: 'optimize_performance',
    parameters: {
        target_improvement: 0.2
    }
});

// Request team optimization
socket.emit('request_team_optimization', {
    criteria: 'performance',
    phase: 'phase2'
});
```

## Development

### Setting Up Development Environment

```bash
# Clone repository and create development branch
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA
git checkout -b feature/gui-enhancement

# Install development dependencies
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Run tests
pytest tests/gui/

# Start development server with auto-reload
python -m spectra_gui_launcher --debug --host 127.0.0.1 --port 8080
```

### Code Structure

```
spectra_gui/
├── launcher/                    # System launcher and orchestration
│   ├── spectra_gui_launcher.py  # Main launcher application
│   └── component_manager.py     # Component lifecycle management
├── coordination/                # Agent coordination and monitoring
│   ├── spectra_coordination_gui.py  # Main coordination interface
│   └── agent_optimizer.py       # Team optimization algorithms
├── phases/                      # Phase management and timeline
│   ├── phase_management_dashboard.py  # Timeline and milestone tracking
│   └── progress_analytics.py    # Progress prediction and analytics
├── orchestration/               # Workflow orchestration
│   ├── spectra_orchestrator.py  # Core orchestration engine
│   └── workflow_builder.py      # Workflow definition and management
├── static/                      # Frontend assets
│   ├── css/                     # Stylesheets
│   ├── js/                      # JavaScript modules
│   └── images/                  # Images and icons
├── templates/                   # HTML templates
│   ├── base.html                # Base template
│   ├── dashboard.html           # Main dashboard
│   └── components/              # Component-specific templates
└── tests/                       # Test suites
    ├── unit/                    # Unit tests
    ├── integration/             # Integration tests
    └── e2e/                     # End-to-end tests
```

### Adding New Components

To add a new GUI component:

1. **Create Component Module**:
   ```python
   # my_component.py
   class MyComponent:
       def __init__(self, orchestrator):
           self.orchestrator = orchestrator

       async def initialize(self):
           # Component initialization logic
           pass

       def generate_html(self):
           # Generate component HTML
           return render_template('my_component.html')
   ```

2. **Register with Launcher**:
   ```python
   # In spectra_gui_launcher.py
   async def _initialize_my_component(self):
       self.my_component = MyComponent(self.orchestrator)
       return await self.my_component.initialize()
   ```

3. **Add Route and Template**:
   ```python
   # Add route
   @self.app.route('/my-component')
   def my_component():
       return self.my_component.generate_html()
   ```

### Testing

```bash
# Run all tests
pytest

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
pytest tests/e2e/

# Run with coverage
pytest --cov=spectra_gui tests/

# Run tests with specific markers
pytest -m "slow" tests/
pytest -m "integration" tests/
```

### Building for Production

```bash
# Create production build
python setup.py sdist bdist_wheel

# Build Docker image
docker build -t spectra-gui:latest .

# Create deployment package
python scripts/create_deployment_package.py
```

## Troubleshooting

### Common Issues

#### 1. GUI Not Starting

**Problem**: GUI fails to start with "Address already in use" error.

**Solution**:
```bash
# Check what's using the port
lsof -i :5000

# Kill the process or use a different port
python -m spectra_gui_launcher --port 8080
```

#### 2. Agent Connection Issues

**Problem**: Agents showing as "disconnected" or "failed" status.

**Solution**:
```bash
# Check agent health
python -m tgarchive agents --test

# Restart orchestrator
curl -X POST http://localhost:5000/api/system/restart
```

#### 3. Database Connection Errors

**Problem**: Database connection timeouts or corruption.

**Solution**:
```bash
# Check database integrity
sqlite3 spectra.db "PRAGMA integrity_check;"

# Backup and recreate if needed
cp spectra.db spectra_backup.db
python -m tgarchive db --recreate
```

#### 4. WebSocket Connection Issues

**Problem**: Real-time updates not working.

**Solution**:
1. Check browser console for JavaScript errors
2. Verify WebSocket support in browser
3. Check firewall/proxy settings
4. Try different browser or incognito mode

#### 5. Performance Issues

**Problem**: GUI responding slowly or high resource usage.

**Solution**:
```bash
# Check system resources
htop

# Reduce monitoring frequency
export SPECTRA_MONITORING_INTERVAL=10

# Enable performance optimizations
export SPECTRA_PERFORMANCE_MODE=true
```

### Debug Mode

Enable comprehensive debugging:

```bash
# Start with full debugging
python -m spectra_gui_launcher --debug --log-level DEBUG

# Check logs
tail -f spectra_gui_system.log

# Enable component-specific debugging
export SPECTRA_DEBUG_COMPONENTS="orchestrator,coordination"
```

### Log Analysis

Key log locations and what to look for:

```bash
# Main system log
tail -f spectra_gui_system.log | grep ERROR

# Component-specific logs
tail -f logs/orchestrator.log
tail -f logs/coordination.log
tail -f logs/phase_management.log

# Database operation logs
tail -f logs/database.log | grep "slow query"
```

## FAQ

### General Questions

**Q: What browsers are supported?**
A: Modern browsers including Chrome 90+, Firefox 88+, Safari 14+, and Edge 90+. WebSocket support is required.

**Q: Can I run the GUI on a different machine from the SPECTRA core?**
A: Yes, configure the orchestrator connection in `spectra_config.json` with the remote host details.

**Q: Is the GUI suitable for production use?**
A: Yes, the GUI is production-ready with comprehensive error handling, logging, and monitoring capabilities.

### Configuration Questions

**Q: How do I change the default port?**
A: Use `--port` command line argument or set `SPECTRA_GUI_PORT` environment variable.

**Q: Can I disable certain GUI components?**
A: Yes, modify the `enable_components` list in your configuration file.

**Q: How do I configure SSL/HTTPS?**
A: Use a reverse proxy (nginx/Apache) or configure Flask-SSLify for direct HTTPS support.

### Performance Questions

**Q: How many concurrent users can the GUI support?**
A: The GUI can handle 50-100 concurrent users depending on hardware and monitoring complexity.

**Q: Why is the interface slow with many agents?**
A: Consider reducing monitoring frequency or enabling agent grouping for better performance.

**Q: Can I optimize the GUI for mobile devices?**
A: The interface is responsive and works on tablets, but phones may have limited functionality.

### Integration Questions

**Q: Can I integrate with external monitoring systems?**
A: Yes, use the REST API endpoints to export metrics to Prometheus, Grafana, or other systems.

**Q: Is there an API for custom dashboards?**
A: Yes, comprehensive REST and WebSocket APIs are available for building custom interfaces.

**Q: Can I embed GUI components in other applications?**
A: Yes, components can be embedded as iframes or integrated via the API.

## Support

### Getting Help

1. **Documentation**: Check this README and the `/docs` directory
2. **GitHub Issues**: Report bugs and request features
3. **Community**: Join discussions in GitHub Discussions
4. **Email**: Contact the development team for enterprise support

### Contributing

We welcome contributions! Please see:

- [Contributing Guidelines](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Development Setup](#development)

### Reporting Issues

When reporting issues, please include:

1. **System Information**: OS, Python version, browser
2. **Configuration**: Relevant config file sections (redacted)
3. **Error Messages**: Complete error messages and stack traces
4. **Steps to Reproduce**: Detailed reproduction steps
5. **Expected vs Actual**: What you expected and what happened

### License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**SPECTRA GUI System v1.0** - Advanced Multi-Agent Coordination Platform
For more information, visit: [https://github.com/SWORDIntel/SPECTRA](https://github.com/SWORDIntel/SPECTRA)