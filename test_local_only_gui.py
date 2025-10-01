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

def test_port_checking():
    """Test port availability checking functions"""
    print("1. Testing port availability checking...")

    # Import the functions
    sys.path.insert(0, str(Path(__file__).parent))
    from spectra_gui_launcher import check_port_available, find_available_port, get_security_level

    # Test port checking
    localhost_available = check_port_available("127.0.0.1", 5000)
    print(f"   Port 5000 available on localhost: {localhost_available}")

    # Test port finding
    available_port, is_preferred = find_available_port("127.0.0.1", 5000)
    print(f"   Found available port: {available_port} (preferred: {is_preferred})")

    return True

def test_security_levels():
    """Test security level detection"""
    print("2. Testing security level detection...")

    from spectra_gui_launcher import get_security_level

    # Test localhost
    level, desc = get_security_level("127.0.0.1")
    print(f"   127.0.0.1: {level} - {desc}")
    assert level == "HIGH", f"Expected HIGH security for localhost, got {level}"

    # Test network access
    level, desc = get_security_level("0.0.0.0")
    print(f"   0.0.0.0: {level} - {desc}")
    assert level == "CRITICAL", f"Expected CRITICAL security for 0.0.0.0, got {level}"

    return True

def test_default_config():
    """Test default configuration is localhost"""
    print("3. Testing default configuration...")

    from spectra_gui_launcher import create_default_config

    config = create_default_config()
    print(f"   Default host: {config.host}")
    print(f"   Default port: {config.port}")

    assert config.host == "127.0.0.1", f"Expected localhost default, got {config.host}"
    print("   ✅ Default configuration is LOCAL ONLY")

    return True

def test_template_content():
    """Test that templates contain LOCAL ONLY messaging"""
    print("4. Testing template LOCAL ONLY messaging...")

    # Check README template
    readme_template = Path("templates/readme.html")
    if readme_template.exists():
        content = readme_template.read_text()
        if "LOCAL ONLY" in content:
            print("   ✅ README template contains LOCAL ONLY messaging")
        else:
            print("   ❌ README template missing LOCAL ONLY messaging")
            return False
    else:
        print("   ❌ README template not found")
        return False

    return True

def test_security_api_routes():
    """Test that security API routes are present in the launcher"""
    print("5. Testing security API routes...")

    launcher_file = Path("spectra_gui_launcher.py")
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

    return all_present

def main():
    """Run all tests"""
    print("🔒 SPECTRA GUI LOCAL ONLY & Port Management Test")
    print("=" * 55)

    tests = [
        test_port_checking,
        test_security_levels,
        test_default_config,
        test_template_content,
        test_security_api_routes
    ]

    passed = 0
    total = len(tests)

    for test_func in tests:
        try:
            if test_func():
                passed += 1
                print("   ✅ PASSED\n")
            else:
                print("   ❌ FAILED\n")
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
        print("python3 demo_readme_gui.py")
        print("Then visit: http://127.0.0.1:5000/readme")

        return True
    else:
        print("⚠️ Some tests failed. Check the issues above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)