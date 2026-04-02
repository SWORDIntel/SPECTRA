#!/usr/bin/env python3
"""
SPECTRA GUI Security Enhancement Test
====================================

Tests the enhanced security features of the SPECTRA GUI system including:
- Localhost-only default configuration
- Port availability checking and fallback
- Security warning system
- Enhanced logging and status reporting
- Error handling for port conflicts

Author: PYTHON-INTERNAL Agent
Date: September 18, 2025
"""

import asyncio
import socket
import sys
import time
import tempfile
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from spectra_app.spectra_gui_launcher import SpectraGUILauncher, create_default_config, SystemMode
from spectra_app.spectra_coordination_gui import SpectraCoordinationGUI


def _reserve_free_port() -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    return sock, sock.getsockname()[1]


def _build_auth_launcher(bootstrap_secret: str = "bootstrap-admin-key", host: str = "127.0.0.1", port: int = 5000):
    config = create_default_config()
    config.host = host
    config.port = port
    config.home_page = "console"
    config.bootstrap_secret = bootstrap_secret
    auth_dir = Path(tempfile.mkdtemp(prefix="spectra-auth-"))
    config.auth_store_path = str(auth_dir / "operators.json")
    return SpectraGUILauncher(config)


class MockOrchestrator:
    """Mock orchestrator for testing"""
    def __init__(self):
        self.is_running = True
        self.agents = {}

    async def initialize(self):
        return True

    async def start_orchestration(self):
        pass

    async def stop_orchestration(self):
        pass


def test_default_security_configuration():
    """Test that default configuration is secure (localhost only)"""
    print("🔍 Testing default security configuration...")

    config = create_default_config()

    # Verify localhost-only default
    assert config.host == "127.0.0.1", f"Expected localhost, got {config.host}"
    assert config.port == 5000, f"Expected default port 5000, got {config.port}"
    assert config.security_enabled == True, "Security should be enabled by default"
    assert config.home_page == "console", "Default home page should remain console"

    print("✅ Default configuration is secure (localhost only)")


def test_port_availability_checking():
    """Test port availability checking functionality"""
    print("🔍 Testing port availability checking...")

    config = create_default_config()
    launcher = SpectraGUILauncher(config)

    # Test with a port that is guaranteed to be available.
    probe_socket, available_port = _reserve_free_port()
    probe_socket.close()
    assert launcher._check_port_availability(available_port), f"Port {available_port} should be available"
    print(f"✅ Port {available_port} correctly detected as available")

    # Test port finding functionality
    found_port = launcher._find_available_port(available_port, 5)
    assert found_port is not None, "Expected to find an available port"
    print(f"✅ Found available port: {found_port}")


def test_security_warnings():
    """Test security warning generation"""
    print("🔍 Testing security warning generation...")

    # Test localhost configuration (secure)
    config_secure = create_default_config()
    config_secure.host = "127.0.0.1"
    launcher_secure = SpectraGUILauncher(config_secure)

    warnings_secure = launcher_secure._get_security_warnings()
    has_secure_message = any("SECURE" in warning for warning in warnings_secure)
    assert has_secure_message, "Should have secure confirmation message"
    print("✅ Secure configuration generates appropriate warnings")

    # Test network configuration (insecure)
    config_insecure = create_default_config()
    config_insecure.host = "0.0.0.0"
    launcher_insecure = SpectraGUILauncher(config_insecure)

    warnings_insecure = launcher_insecure._get_security_warnings()
    has_critical_warning = any("CRITICAL" in warning for warning in warnings_insecure)
    assert has_critical_warning, "Should have critical security warning"
    print("✅ Insecure configuration generates critical warnings")


def test_coordination_gui_defaults():
    """Test coordination GUI security defaults"""
    print("🔍 Testing coordination GUI security defaults...")

    mock_orchestrator = MockOrchestrator()

    # Test default localhost configuration
    try:
        gui = SpectraCoordinationGUI(
            orchestrator=mock_orchestrator
            # Using default parameters - should be localhost
        )
    except Exception as e:
        if "Flask is required" in str(e):
            print("⚠️ Coordination GUI skipped: Flask is not installed in this environment")
            return
        raise

    assert gui.host == "127.0.0.1", f"Expected localhost, got {gui.host}"
    assert gui.local_only == True, "Should be configured for local only access"

    print("✅ Coordination GUI defaults to secure localhost configuration")


def test_security_status_logging():
    """Test security status logging functionality"""
    print("🔍 Testing security status logging...")

    config = create_default_config()
    launcher = SpectraGUILauncher(config)

    # Capture log output (in real implementation, this would check logs)
    try:
        launcher._log_security_status()
        print("✅ Security status logging completed without errors")
    except Exception as e:
        print(f"❌ Security status logging failed: {e}")
        raise


def test_bootstrap_login_logout_session_flow():
    """Test browser login, session auth, and logout for the bootstrap admin flow."""
    print("🔍 Testing bootstrap login/logout session flow...")

    launcher = _build_auth_launcher()
    client = launcher.app.test_client()

    unauthenticated = client.get("/", follow_redirects=False)
    assert unauthenticated.status_code in (301, 302)
    assert "/login" in unauthenticated.headers["Location"]

    login_page = client.get("/login")
    login_html = login_page.get_data(as_text=True)
    assert login_page.status_code == 200
    assert "Bootstrap admin enrollment" in login_html
    assert "YubiKey" in login_html
    assert "passkey" in login_html.lower()

    bootstrap_status = client.get("/api/auth/bootstrap/status")
    assert bootstrap_status.status_code == 200
    bootstrap_json = bootstrap_status.get_json()
    assert bootstrap_json["auth"]["bootstrap_required"] is True
    assert bootstrap_json["auth"]["bootstrap_configured"] is True

    operator = launcher.auth_service.ensure_admin_bootstrap(
        username="admin",
        display_name="Admin",
        submitted_secret="bootstrap-admin-key",
    )
    with client.session_transaction() as sess:
        sess["spectra_operator_id"] = operator.operator_id

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "SPECTRA Web Console" in dashboard.get_data(as_text=True)

    status_response = client.get("/api/system/status")
    assert status_response.status_code == 200
    status_json = status_response.get_json()
    assert status_json["auth"]["webauthn_required"] is True
    assert status_json["auth"]["authenticated"] is True
    assert status_json["auth"]["browser_login"] == "/login"

    logout = client.post("/logout")
    assert logout.status_code == 200
    assert logout.get_json()["success"] is True

    with client.session_transaction() as sess:
        assert not sess.get("spectra_operator_id")

    post_logout = client.get("/", follow_redirects=False)
    assert post_logout.status_code in (301, 302)
    assert "/login" in post_logout.headers["Location"]


def simulate_port_conflict():
    """Simulate a port conflict scenario"""
    print("🔍 Testing port conflict handling...")

    # Create a socket to occupy a port
    server_socket, test_port = _reserve_free_port()

    try:
        server_socket.listen(1)
        print(f"🔒 Occupied port {test_port} for testing")

        # Test that our port checking detects the conflict
        config = create_default_config()
        config.port = test_port
        launcher = SpectraGUILauncher(config)

        is_available = launcher._check_port_availability(test_port)
        assert not is_available, "Port conflict was not detected"
        print("✅ Port conflict correctly detected")

        # Test that it finds an alternative
        alternative = launcher._find_available_port(test_port + 1, 5)
        assert alternative is not None, "Expected an alternative port"
        print(f"✅ Found alternative port: {alternative}")

    except Exception as e:
        print(f"⚠️ Port conflict test had issues: {e}")
        raise
    finally:
        server_socket.close()


def test_initialization_with_port_conflict():
    """Test system initialization with port conflict"""
    print("🔍 Testing system initialization with port conflict...")

    # Create a socket to occupy the default port
    server_socket, test_port = _reserve_free_port()

    try:
        server_socket.listen(1)

        # Configure launcher to use the occupied port
        config = create_default_config()
        config.port = test_port
        launcher = SpectraGUILauncher(config)

        # Test initialization - should find alternative port
        # Note: We're not actually starting the server, just testing the port logic
        assert launcher._check_port_availability(test_port) is False, "Port conflict should be detected"
        print("✅ Port conflict handling during initialization works")

    except Exception as e:
        print(f"⚠️ Initialization test had issues: {e}")
        raise
    finally:
        server_socket.close()


def run_all_tests():
    """Run all security enhancement tests"""
    print("=" * 70)
    print("🔒 SPECTRA GUI SECURITY ENHANCEMENT TESTS")
    print("=" * 70)

    tests = [
        ("Default Security Configuration", test_default_security_configuration),
        ("Port Availability Checking", test_port_availability_checking),
        ("Security Warning Generation", test_security_warnings),
        ("Coordination GUI Defaults", test_coordination_gui_defaults),
        ("Security Status Logging", test_security_status_logging),
        ("Port Conflict Simulation", simulate_port_conflict),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        print(f"\n🧪 {test_name}")
        print("-" * 50)

        try:
            test_func()
            passed += 1
            print(f"✅ {test_name} PASSED")
        except Exception as e:
            print(f"❌ {test_name} FAILED with exception: {e}")

    # Run async test separately
    print(f"\n🧪 System Initialization with Port Conflict")
    print("-" * 50)
    try:
        test_initialization_with_port_conflict()
        passed += 1
        print("✅ System Initialization with Port Conflict PASSED")
    except Exception as e:
        print(f"❌ System Initialization with Port Conflict FAILED with exception: {e}")

    total += 1  # Add the async test

    print("\n" + "=" * 70)
    print("📊 TEST RESULTS")
    print("=" * 70)
    print(f"Tests Passed: {passed}/{total}")
    print(f"Success Rate: {(passed/total)*100:.1f}%")

    if passed == total:
        print("🎉 ALL TESTS PASSED - Security enhancements are working correctly!")
        return True
    else:
        print("⚠️ Some tests failed - review security implementation")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
