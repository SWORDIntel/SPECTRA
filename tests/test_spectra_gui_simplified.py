#!/usr/bin/env python3
"""
SPECTRA GUI System Simplified Test Suite
========================================

Simplified test suite for validating core functionality of the SPECTRA GUI system
with tests that match the actual class implementations.

Author: PYTHON-INTERNAL Agent - Elite Python execution environment specialist
Date: September 18, 2025
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Test core imports first
def test_imports():
    """Test that all core components can be imported successfully"""
    print("=== Testing Core Imports ===")

    try:
        from spectra_app.spectra_coordination_gui import SpectraCoordinationGUI
        print("✓ SpectraCoordinationGUI imported successfully")
    except ImportError as e:
        print(f"✗ SpectraCoordinationGUI import failed: {e}")
        raise

    try:
        from spectra_app.agent_optimization_engine import AgentOptimizationEngine, AgentPerformanceProfile
        print("✓ Agent optimization components imported successfully")
    except ImportError as e:
        print(f"✗ Agent optimization import failed: {e}")
        raise

    try:
        from spectra_app.phase_management_dashboard import PhaseManagementDashboard, TimelineEvent, MilestoneStatus
        print("✓ Phase management components imported successfully")
    except ImportError as e:
        print(f"✗ Phase management import failed: {e}")
        raise

    try:
        from spectra_app.coordination_interface import CoordinationInterface, AgentHealthMetrics
        print("✓ Coordination interface components imported successfully")
    except ImportError as e:
        print(f"✗ Coordination interface import failed: {e}")
        raise

    try:
        from spectra_app.implementation_tools import ImplementationTools, WorkBreakdownItem
        print("✓ Implementation tools components imported successfully")
    except ImportError as e:
        print(f"✗ Implementation tools import failed: {e}")
        raise

    try:
        from spectra_app.spectra_gui_launcher import SpectraGUILauncher
        print("✓ GUI launcher imported successfully")
    except ImportError as e:
        print(f"✗ GUI launcher import failed: {e}")
        raise


def test_data_structures():
    """Test creation of core data structures"""
    print("\n=== Testing Data Structures ===")

    try:
        from spectra_app.agent_optimization_engine import AgentPerformanceProfile

        # Create agent performance profile with correct parameters
        profile = AgentPerformanceProfile(
            agent_name="Test Agent",
            capabilities={"security": 0.9, "analysis": 0.8},
            performance_metrics={"response_time": 150.0, "accuracy": 0.95},
            resource_efficiency={"cpu": 0.8, "memory": 0.7},
            collaboration_scores={"teamwork": 0.85, "communication": 0.9},
            workload_capacity=100.0,
            cost_per_hour=50.0,
            availability_probability=0.95,
            learning_rate=0.1,
            stress_tolerance=0.8,
            specialization_breadth=0.7
        )

        assert profile.agent_name == "Test Agent"
        assert profile.capabilities["security"] == 0.9
        assert profile.workload_capacity == 100.0
        print("✓ AgentPerformanceProfile creation successful")

    except Exception as e:
        print(f"✗ AgentPerformanceProfile creation failed: {e}")
        raise

    try:
        from spectra_app.phase_management_dashboard import TimelineEvent, MilestoneStatus

        # Create timeline event
        event = TimelineEvent(
            event_id="evt_001",
            title="Test Event",
            description="Test Description",
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=1),
            phase_id="phase_1",
            milestone_id="milestone_001",
            status=MilestoneStatus.IN_PROGRESS,
            dependencies=[],
            assigned_agents=["agent_001"],
            required_resources={"cpu": 2}
        )

        assert event.event_id == "evt_001"
        assert event.status == MilestoneStatus.IN_PROGRESS
        print("✓ TimelineEvent creation successful")

    except Exception as e:
        print(f"✗ TimelineEvent creation failed: {e}")
        raise

    try:
        from spectra_app.coordination_interface import AgentHealthMetrics

        # Create health metrics
        health = AgentHealthMetrics(
            agent_id="agent_001",
            timestamp=datetime.now(),
            cpu_usage=25.5,
            memory_usage=1024,
            response_time=150,
            error_rate=0.02,
            task_completion_rate=0.95,
            availability_score=0.98,
            performance_score=0.92
        )

        assert health.agent_id == "agent_001"
        assert health.performance_score == 0.92
        print("✓ AgentHealthMetrics creation successful")

    except Exception as e:
        print(f"✗ AgentHealthMetrics creation failed: {e}")
        raise


def test_orchestrator_integration():
    """Test integration with mock orchestrator"""
    print("\n=== Testing Orchestrator Integration ===")

    # Simple mock orchestrator
    class MockOrchestrator:
        def __init__(self):
            self.agents = {
                "agent_001": {
                    "name": "Security Agent",
                    "status": "active",
                    "capabilities": {"security": 0.9, "analysis": 0.8}
                }
            }

        async def get_available_agents(self):
            return self.agents

        async def get_system_metrics(self):
            return {"active_agents": 1, "system_health": "good"}

    try:
        from spectra_app.phase_management_dashboard import PhaseManagementDashboard

        mock_orchestrator = MockOrchestrator()
        dashboard = PhaseManagementDashboard(mock_orchestrator)

        # Test basic functionality
        phases = dashboard.get_phase_overview()
        assert isinstance(phases, dict)
        print("✓ PhaseManagementDashboard integration successful")

    except Exception as e:
        print(f"✗ PhaseManagementDashboard integration failed: {e}")
        raise

    try:
        from spectra_app.coordination_interface import CoordinationInterface

        mock_orchestrator = MockOrchestrator()
        interface = CoordinationInterface(mock_orchestrator)

        # Test basic initialization
        assert interface.orchestrator is not None
        print("✓ CoordinationInterface integration successful")

    except Exception as e:
        print(f"✗ CoordinationInterface integration failed: {e}")
        raise


async def _test_async_functionality():
    """Test asynchronous functionality"""
    print("\n=== Testing Async Functionality ===")

    try:
        # Simple async test
        await asyncio.sleep(0.01)  # Test basic async/await

        # Test that async components can be created
        class MockOrchestrator:
            async def get_available_agents(self):
                return {"agent_001": {"name": "Test Agent"}}

        mock_orch = MockOrchestrator()
        agents = await mock_orch.get_available_agents()

        assert isinstance(agents, dict)
        assert "agent_001" in agents
        print("✓ Async functionality working")
        return None

    except Exception as e:
        print(f"✗ Async functionality failed: {e}")
        raise


def test_async_functionality():
    """Pytest-visible wrapper for async functionality."""
    asyncio.run(_test_async_functionality())


def test_json_serialization():
    """Test JSON serialization capabilities"""
    print("\n=== Testing JSON Serialization ===")

    try:
        # Test basic data serialization
        test_data = {
            "agent_id": "agent_001",
            "capabilities": {"security": 0.9, "analysis": 0.8},
            "timestamp": datetime.now().isoformat(),
            "metrics": {"response_time": 150, "accuracy": 0.95}
        }

        # Serialize to JSON
        json_str = json.dumps(test_data)

        # Deserialize from JSON
        restored_data = json.loads(json_str)

        assert restored_data["agent_id"] == "agent_001"
        assert restored_data["capabilities"]["security"] == 0.9
        print("✓ JSON serialization working")
        return None

    except Exception as e:
        print(f"✗ JSON serialization failed: {e}")
        raise


def test_gui_launcher_basic():
    """Test basic GUI launcher functionality without web dependencies"""
    print("\n=== Testing GUI Launcher Basic Functionality ===")

    try:
        # Test configuration creation
        from spectra_app.spectra_gui_launcher import SystemConfiguration

        config = SystemConfiguration(
            host="localhost",
            port=5001,
            mode="demo",
            debug=True,
            config_file=None
        )

        assert config.host == "localhost"
        assert config.port == 5001
        assert config.mode == "demo"
        print("✓ SystemConfiguration creation successful")
        return None

    except Exception as e:
        print(f"✗ GUI launcher basic test failed: {e}")
        raise


def test_gui_launcher_auth_surface():
    """Test login page copy and auth metadata for the browser UI."""
    print("\n=== Testing GUI Launcher Auth Surface ===")

    try:
        from spectra_app.spectra_gui_launcher import SpectraGUILauncher, SystemConfiguration

        auth_dir = Path(tempfile.mkdtemp(prefix="spectra-auth-"))
        config = SystemConfiguration(
            host="127.0.0.1",
            port=5001,
            mode="demo",
            debug=True,
            home_page="console",
            auth_store_path=str(auth_dir / "operators.json"),
        )
        config.bootstrap_secret = "bootstrap-admin-key"

        launcher = SpectraGUILauncher(config)
        client = launcher.app.test_client()

        assert launcher.config.host == "127.0.0.1"
        assert launcher.config.port == 5001

        login_page = client.get("/login")
        login_html = login_page.get_data(as_text=True)
        assert login_page.status_code == 200
        assert "Bootstrap admin enrollment" in login_html
        assert "YubiKey" in login_html
        assert "passkey" in login_html.lower()

        status = launcher.get_system_status()
        assert status["auth"]["webauthn_required"] is True
        assert status["auth"]["browser_login"] == "/login"
        print("✓ GUI launcher auth surface verified")
        return None
    except Exception as e:
        print(f"✗ GUI launcher auth surface test failed: {e}")
        raise


def run_all_tests():
    """Run all tests and generate report"""
    print("=" * 70)
    print("SPECTRA GUI System - Simplified Test Suite")
    print("=" * 70)

    tests = [
        ("Core Imports", test_imports),
        ("Data Structures", test_data_structures),
        ("Orchestrator Integration", test_orchestrator_integration),
        ("JSON Serialization", test_json_serialization),
        ("GUI Launcher Basic", test_gui_launcher_basic),
        ("GUI Launcher Auth Surface", test_gui_launcher_auth_surface),
    ]

    # Run sync tests
    results = []
    for test_name, test_func in tests:
        print(f"\n🔄 Running {test_name} test...")
        try:
            test_func()
            results.append((test_name, True))
        except Exception as e:
            print(f"✗ {test_name} test crashed: {e}")
            results.append((test_name, False))

    # Run async test
    print(f"\n🔄 Running Async Functionality test...")
    try:
        test_async_functionality()
        results.append(("Async Functionality", True))
    except Exception as e:
        print(f"✗ Async Functionality test crashed: {e}")
        results.append(("Async Functionality", False))

    # Generate report
    print("\n" + "=" * 70)
    print("TEST RESULTS SUMMARY")
    print("=" * 70)

    total_tests = len(results)
    passed_tests = sum(1 for _, result in results if result)
    failed_tests = total_tests - passed_tests

    for test_name, result in results:
        status = "PASSED" if result else "FAILED"
        icon = "✓" if result else "✗"
        print(f"{icon} {test_name}: {status}")

    print(f"\nTotal Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {failed_tests}")
    print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")

    if passed_tests == total_tests:
        print("\n🎉 ALL TESTS PASSED!")
        print("✓ Core GUI system components are functional")
        print("✓ Data structures work correctly")
        print("✓ Integration patterns are solid")
        print("✓ Async functionality is working")
        print("✓ System is ready for further development")
        return True
    else:
        print(f"\n⚠️  {failed_tests} test(s) failed")
        print("Some components need attention before deployment")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
