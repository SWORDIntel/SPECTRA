#!/usr/bin/env python3
"""
SPECTRA System Integration Test Suite
====================================

Comprehensive test suite to verify all integration points and dependencies
for the SPECTRA multi-agent GUI system.

Author: PYTHON-INTERNAL Agent
Date: September 18, 2025
"""

import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

class IntegrationTestSuite:
    """Comprehensive integration test suite for SPECTRA system"""

    def __init__(self):
        self.test_results = {}
        self.start_time = None
        self.end_time = None

    def run_test(self, test_name: str, test_function):
        """Run a single test and record results"""
        print(f"\n{'='*60}")
        print(f"Running: {test_name}")
        print('='*60)

        try:
            start = time.time()
            result = test_function()
            end = time.time()

            self.test_results[test_name] = {
                'status': 'PASS',
                'duration': end - start,
                'result': result
            }
            print(f"✅ {test_name}: PASS ({end - start:.3f}s)")
            return True

        except Exception as e:
            self.test_results[test_name] = {
                'status': 'FAIL',
                'error': str(e),
                'duration': 0
            }
            print(f"❌ {test_name}: FAIL - {e}")
            return False

    def test_dependencies(self):
        """Test all required dependencies"""
        print("Testing core dependencies...")

        # Flask dependencies
        from flask import Flask
        from flask_socketio import SocketIO, emit
        print("✓ Flask and Flask-SocketIO")

        # SPECTRA core components
        from tgarchive.config_models import Config
        from tgarchive.db import SpectraDB
        print("✓ SPECTRA core components")

        # GUI components
        from spectra_app.spectra_orchestrator import SpectraOrchestrator
        from spectra_app.spectra_coordination_gui import SpectraCoordinationGUI
        from spectra_app.phase_management_dashboard import PhaseManagementDashboard
        from spectra_app.coordination_interface import CoordinationInterface
        from spectra_app.implementation_tools import ImplementationTools
        from spectra_app.agent_optimization_engine import AgentOptimizationEngine
        print("✓ All GUI components")

        return "All dependencies available"

    def test_config_loading(self):
        """Test configuration loading"""
        print("Testing configuration loading...")

        from tgarchive.config_models import Config
        from pathlib import Path

        # Test with default config
        config = Config(path=Path('spectra_config.json'))
        assert hasattr(config, 'data'), "Config should have data attribute"
        assert isinstance(config.data, dict), "Config data should be a dictionary"
        print(f"✓ Config loaded with {len(config.data)} settings")

        return f"Configuration loaded successfully with {len(config.data)} settings"

    def test_orchestrator_creation(self):
        """Test orchestrator creation and basic functionality"""
        print("Testing orchestrator creation...")

        from spectra_app.spectra_orchestrator import SpectraOrchestrator

        orchestrator = SpectraOrchestrator(
            config_path='spectra_config.json',
            db_path='test_integration.db',
            log_level='INFO'
        )

        assert hasattr(orchestrator, 'config_path'), "Orchestrator should have config_path"
        assert hasattr(orchestrator, 'db_path'), "Orchestrator should have db_path"
        assert hasattr(orchestrator, 'is_running'), "Orchestrator should have is_running attribute"

        print("✓ Orchestrator created with proper attributes")
        return "Orchestrator creation successful"

    def test_gui_launcher_creation(self):
        """Test GUI launcher creation"""
        print("Testing GUI launcher creation...")

        from spectra_app.spectra_gui_launcher import SpectraGUILauncher, create_default_config

        config = create_default_config()
        launcher = SpectraGUILauncher(config)

        assert hasattr(launcher, 'app'), "Launcher should have Flask app"
        assert hasattr(launcher, 'socketio'), "Launcher should have SocketIO"
        assert hasattr(launcher, 'config'), "Launcher should have config"

        print(f"✓ GUI launcher created with {len(config.enable_components)} components")
        return f"GUI launcher ready with {len(config.enable_components)} components"

    def test_component_integration(self):
        """Test integration between components"""
        print("Testing component integration...")

        from spectra_app.spectra_gui_launcher import SpectraGUILauncher, create_default_config
        from spectra_app.spectra_orchestrator import SpectraOrchestrator

        # Create configuration
        config = create_default_config()
        launcher = SpectraGUILauncher(config)

        # Test component creation
        orchestrator = SpectraOrchestrator(
            config_path='spectra_config.json',
            db_path='test_integration.db',
            log_level='INFO'
        )

        # Verify integration points
        assert launcher.orchestrator is None, "Orchestrator should start as None"
        launcher.orchestrator = orchestrator
        assert launcher.orchestrator is not None, "Orchestrator should be assignable"

        print("✓ Component integration working")
        return "Components integrate properly"

    def test_async_initialization(self):
        """Test async initialization process"""
        print("Testing async initialization...")

        from spectra_app.spectra_gui_launcher import SpectraGUILauncher, create_default_config

        config = create_default_config()
        config.debug = True  # Enable debug for testing
        launcher = SpectraGUILauncher(config)

        # Test async methods exist
        assert hasattr(launcher, 'initialize_system'), "Should have initialize_system method"
        assert asyncio.iscoroutinefunction(launcher.initialize_system), "Should be async"

        print("✓ Async initialization methods available")
        return "Async initialization ready"

    def test_web_interface_setup(self):
        """Test web interface setup"""
        print("Testing web interface setup...")

        from spectra_app.spectra_gui_launcher import SpectraGUILauncher, create_default_config

        config = create_default_config()
        launcher = SpectraGUILauncher(config)

        # Test Flask app setup
        assert launcher.app is not None, "Flask app should be created"
        assert launcher.socketio is not None, "SocketIO should be created"

        # Test routes exist
        rules = [rule.rule for rule in launcher.app.url_map.iter_rules()]
        expected_routes = ['/', '/agent-selection', '/phase-management', '/coordination', '/implementation']

        for route in expected_routes:
            assert route in rules, f"Route {route} should exist"

        print(f"✓ Web interface setup with {len(rules)} routes")
        return f"Web interface ready with {len(rules)} routes"

    def test_template_generation(self):
        """Test template generation"""
        print("Testing template generation...")

        from spectra_app.spectra_gui_launcher import SpectraGUILauncher, create_default_config

        config = create_default_config()
        launcher = SpectraGUILauncher(config)

        # Test template content generation
        template_content = launcher._generate_unified_template()

        assert isinstance(template_content, str), "Template should be a string"
        assert len(template_content) > 1000, "Template should be substantial"
        assert "SPECTRA GUI System" in template_content, "Template should contain title"
        assert "socket.io" in template_content, "Template should include socket.io"

        print(f"✓ Template generated ({len(template_content)} characters)")
        return f"Template generation successful ({len(template_content)} chars)"

    def test_system_status_methods(self):
        """Test system status and health monitoring methods"""
        print("Testing system status methods...")

        from spectra_app.spectra_gui_launcher import SpectraGUILauncher, create_default_config

        config = create_default_config()
        launcher = SpectraGUILauncher(config)

        # Test status methods
        system_status = launcher.get_system_status()
        component_status = launcher.get_component_status()

        assert isinstance(system_status, dict), "System status should be a dict"
        assert isinstance(component_status, dict), "Component status should be a dict"
        assert 'system_running' in system_status, "Should include system_running status"

        print(f"✓ System status methods working")
        return "Status monitoring ready"

    async def run_all_tests(self):
        """Run all integration tests"""
        self.start_time = datetime.now()
        print("🚀 Starting SPECTRA Integration Test Suite")
        print(f"📅 Start time: {self.start_time}")

        tests = [
            ("Dependency Check", self.test_dependencies),
            ("Configuration Loading", self.test_config_loading),
            ("Orchestrator Creation", self.test_orchestrator_creation),
            ("GUI Launcher Creation", self.test_gui_launcher_creation),
            ("Component Integration", self.test_component_integration),
            ("Async Initialization", self.test_async_initialization),
            ("Web Interface Setup", self.test_web_interface_setup),
            ("Template Generation", self.test_template_generation),
            ("System Status Methods", self.test_system_status_methods),
        ]

        passed = 0
        failed = 0

        for test_name, test_function in tests:
            success = self.run_test(test_name, test_function)

            if success:
                passed += 1
            else:
                failed += 1

        self.end_time = datetime.now()
        duration = (self.end_time - self.start_time).total_seconds()

        # Print summary
        print(f"\n{'='*80}")
        print("🏁 INTEGRATION TEST SUITE COMPLETE")
        print('='*80)
        print(f"📊 Results: {passed} PASSED, {failed} FAILED")
        print(f"⏱️  Total Duration: {duration:.2f} seconds")
        print(f"📅 End time: {self.end_time}")

        if failed == 0:
            print("🎉 ALL TESTS PASSED - SYSTEM READY FOR DEPLOYMENT!")
            return True
        else:
            print("⚠️  SOME TESTS FAILED - REVIEW ISSUES BEFORE DEPLOYMENT")
            return False

    def print_detailed_results(self):
        """Print detailed test results"""
        print(f"\n{'='*80}")
        print("📋 DETAILED TEST RESULTS")
        print('='*80)

        for test_name, result in self.test_results.items():
            status_icon = "✅" if result['status'] == 'PASS' else "❌"
            print(f"{status_icon} {test_name}: {result['status']}")

            if result['status'] == 'PASS':
                print(f"   ⏱️  Duration: {result.get('duration', 0):.3f}s")
                if 'result' in result:
                    print(f"   📝 Result: {result['result']}")
            else:
                print(f"   ❌ Error: {result.get('error', 'Unknown error')}")
            print()


async def main():
    """Main test execution"""
    suite = IntegrationTestSuite()

    try:
        success = await suite.run_all_tests()
        suite.print_detailed_results()

        if success:
            print("\n🚀 SPECTRA System Integration: SUCCESS")
            print("✅ System is ready for production deployment")
            sys.exit(0)
        else:
            print("\n⚠️  SPECTRA System Integration: PARTIAL SUCCESS")
            print("❌ Some components need attention before deployment")
            sys.exit(1)

    except Exception as e:
        print(f"\n💥 Integration test suite failed: {e}")
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
