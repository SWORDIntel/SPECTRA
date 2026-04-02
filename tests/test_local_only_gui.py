#!/usr/bin/env python3
"""
Test SPECTRA GUI LOCAL ONLY and Port Management
==============================================

Test script to verify the GUI is properly configured for LOCAL ONLY access
and handles port assignment correctly.
"""

import socket
import sys
import time
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

def test_port_checking():
    """Test port availability checking functions"""
    print("1. Testing port availability checking...")

    # Import the functions
    from spectra_app.spectra_gui_launcher import check_port_available, find_available_port, get_security_level

    # Test port checking
    localhost_available = check_port_available("127.0.0.1", 5000)
    print(f"   Port 5000 available on localhost: {localhost_available}")

    # Test port finding
    available_port, is_preferred = find_available_port("127.0.0.1", 5000)
    print(f"   Found available port: {available_port} (preferred: {is_preferred})")

def test_security_levels():
    """Test security level detection"""
    print("2. Testing security level detection...")

    from spectra_app.spectra_gui_launcher import get_security_level

    # Test localhost
    level, desc = get_security_level("127.0.0.1")
    print(f"   127.0.0.1: {level} - {desc}")
    assert level == "HIGH", f"Expected HIGH security for localhost, got {level}"

    # Test network access
    level, desc = get_security_level("0.0.0.0")
    print(f"   0.0.0.0: {level} - {desc}")
    assert level == "CRITICAL", f"Expected CRITICAL security for 0.0.0.0, got {level}"

def test_default_config():
    """Test default configuration is localhost"""
    print("3. Testing default configuration...")

    from spectra_app.spectra_gui_launcher import create_default_config

    config = create_default_config()
    print(f"   Default host: {config.host}")
    print(f"   Default port: {config.port}")

    assert config.host == "127.0.0.1", f"Expected localhost default, got {config.host}"
    assert config.port == 5000, f"Expected default port 5000, got {config.port}"
    print("   ✅ Default configuration is LOCAL ONLY")

def test_login_template_copy():
    """Test that login UI copy reflects the first-run bootstrap flow"""
    print("4. Testing login template bootstrap messaging...")

    login_template = ROOT_DIR / "templates" / "login.html"
    if login_template.exists():
        content = login_template.read_text()
        assert "Bootstrap admin enrollment" in content, "Login template missing bootstrap messaging"
        assert "YubiKey" in content, "Login template missing YubiKey copy"
        assert "passkey" in content.lower(), "Login template missing passkey copy"
        print("   ✅ Login template contains first-run bootstrap messaging")
    else:
        raise AssertionError("Login template not found")

def test_template_content():
    """Test that templates contain LOCAL ONLY messaging"""
    print("5. Testing template LOCAL ONLY messaging...")

    # Check README template
    readme_template = ROOT_DIR / "templates" / "readme.html"
    if readme_template.exists():
        content = readme_template.read_text()
        assert "LOCAL ONLY" in content, "README template missing LOCAL ONLY messaging"
        print("   ✅ README template contains LOCAL ONLY messaging")
    else:
        raise AssertionError("README template not found")

def test_security_api_routes():
    """Test that security API routes are present in the launcher"""
    print("6. Testing security API routes...")

    launcher_file = ROOT_DIR / "spectra_app" / "spectra_gui_launcher.py"
    content = launcher_file.read_text()

    required_routes = [
        "/api/security/warnings",
        "/api/system/access-info"
    ]

    all_present = True
    for route in required_routes:
        if route in content:
            print(f"   ✅ Found route: {route}")
        else:
            print(f"   ❌ Missing route: {route}")
            all_present = False

    assert all_present, "Missing security API routes"

def main():
    """Run all tests"""
    print("🔒 SPECTRA GUI LOCAL ONLY & Port Management Test")
    print("=" * 55)

    tests = [
        test_port_checking,
        test_security_levels,
        test_default_config,
        test_login_template_copy,
        test_template_content,
        test_security_api_routes
    ]

    passed = 0
    total = len(tests)

    for test_func in tests:
        try:
            test_func()
            passed += 1
            print("   ✅ PASSED\n")
        except Exception as e:
            print(f"   ❌ ERROR: {e}\n")

    print("=" * 55)
    print(f"📊 Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! GUI is LOCAL ONLY and port-aware.")

        print("\n🔒 Security Status:")
        print("✅ Default configuration is localhost (127.0.0.1)")
        print("✅ Port availability checking implemented")
        print("✅ Security warnings and API endpoints present")
        print("✅ Templates contain LOCAL ONLY messaging")
        print("✅ README access is local system only")

        print("\n🚀 Ready to launch:")
        print("python3 examples/demo_readme_gui.py")
        print("Then visit: http://127.0.0.1:5000/readme")

    else:
        print("⚠️ Some tests failed. Check the issues above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
