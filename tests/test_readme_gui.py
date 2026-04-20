#!/usr/bin/env python3
"""
Test SPECTRA GUI README Integration
==================================

Quick test to verify the README integration works correctly
in the SPECTRA GUI system.
"""

import sys
import os
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

def test_readme_integration():
    """Test README integration components"""

    print("🔍 Testing SPECTRA GUI README Integration...\n")

    tests_passed = 0
    total_tests = 0

    # Test 1: Check if GUI launcher exists and has README routes
    total_tests += 1
    print("1. Checking GUI launcher file...")
    launcher_path = Path("spectra_app/spectra_gui_launcher.py")
    if launcher_path.exists():
        content = launcher_path.read_text()
        if '/readme' in content and '/help' in content and '/documentation' in content:
            print("   ✅ README routes found in GUI launcher")
            tests_passed += 1
        else:
            print("   ❌ README routes not found in GUI launcher")
    else:
        print("   ❌ GUI launcher file not found")

    # Test 2: Check if README template exists
    total_tests += 1
    print("2. Checking README template file...")
    template_path = Path("templates/readme.html")
    if template_path.exists():
        content = template_path.read_text()
        if 'SPECTRA Documentation' in content and 'sidebar' in content:
            print("   ✅ README template found with proper structure")
            tests_passed += 1
        else:
            print("   ❌ README template missing required elements")
    else:
        print("   ❌ README template file not found")

    # Test 3: Check if templates directory exists
    total_tests += 1
    print("3. Checking templates directory...")
    templates_dir = Path("templates")
    if templates_dir.exists() and templates_dir.is_dir():
        print("   ✅ Templates directory exists")
        tests_passed += 1
    else:
        print("   ❌ Templates directory not found")

    # Test 4: Check if GUI_README.md exists (source content)
    total_tests += 1
    print("4. Checking GUI README source file...")
    gui_readme_path = Path("docs/guides/GUI_README.md")
    if gui_readme_path.exists():
        content = gui_readme_path.read_text()
        if len(content) > 10000:  # Should be substantial
            print(f"   ✅ GUI README found ({len(content)} characters)")
            tests_passed += 1
        else:
            print(f"   ❌ GUI README too short ({len(content)} characters)")
    else:
        print("   ❌ GUI README source file not found")

    # Test 5: Check Flask imports in launcher
    total_tests += 1
    print("5. Checking Flask dependencies in launcher...")
    if launcher_path.exists():
        content = launcher_path.read_text()
        if 'from flask import' in content and 'Flask-SocketIO' in str(Path("requirements.txt").read_text()):
            print("   ✅ Flask dependencies properly imported")
            tests_passed += 1
        else:
            print("   ❌ Flask dependencies not properly configured")
    else:
        print("   ❌ Cannot check Flask dependencies (launcher missing)")

    # Test 6: Check if markdown processing is available
    total_tests += 1
    print("6. Checking markdown processing capabilities...")
    try:
        # Check if markdown is in requirements
        reqs = Path("requirements.txt").read_text()
        if 'Markdown' in reqs:
            print("   ✅ Markdown processing available in requirements")
            tests_passed += 1
        else:
            print("   ❌ Markdown not found in requirements")
    except:
        print("   ❌ Could not check requirements.txt")

    # Test 7: Check login template copy for first-run auth flow
    total_tests += 1
    print("7. Checking login template first-run copy...")
    login_template = Path("templates/login.html")
    if login_template.exists():
        content = login_template.read_text()
        if "Bootstrap admin enrollment" in content and "YubiKey" in content and "passkey" in content:
            print("   ✅ Login template contains first-run bootstrap copy")
            tests_passed += 1
        else:
            print("   ❌ Login template missing first-run bootstrap copy")
    else:
        print("   ❌ Login template file not found")

    # Summary
    print(f"\n📊 Test Results: {tests_passed}/{total_tests} tests passed")

    if tests_passed == total_tests:
        print("🎉 All tests passed! README integration is ready.")
    else:
        raise AssertionError("Some README integration checks failed")

def create_demo_launcher():
    """Create a simple demo launcher for testing"""

    demo_content = '''#!/usr/bin/env python3
"""
Demo SPECTRA GUI with README Integration
======================================
"""

import sys
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from spectra_app.spectra_gui_launcher import SpectraGUILauncher, create_default_config
    import asyncio

    async def main():
        """Demo main function"""
        print("🚀 Starting SPECTRA GUI Demo with README Integration...")

        # Create demo configuration
        config = create_default_config()
        config.port = 5000
        config.host = "127.0.0.1"
        config.debug = True

        # Initialize launcher
        launcher = SpectraGUILauncher(config)

        print(f"📖 README available at: http://{config.host}:{config.port}/readme")
        print(f"🏠 Main dashboard at: http://{config.host}:{config.port}/")
        print("Press Ctrl+C to stop")

        try:
            await launcher.start_system()
        except KeyboardInterrupt:
            print("\\nShutting down...")
            await launcher.stop_system()

    if __name__ == "__main__":
        asyncio.run(main())

except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure all dependencies are installed:")
    print("pip install flask flask-socketio markdown")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
'''

    demo_path = Path("examples/demo_readme_gui.py")
    demo_path.write_text(demo_content)
    demo_path.chmod(0o755)

    print(f"📝 Created demo launcher: {demo_path}")
    print("Run with: python3 examples/demo_readme_gui.py")

if __name__ == "__main__":
    print("SPECTRA GUI README Integration Test")
    print("==================================\\n")

    try:
        test_readme_integration()
        print("\\n🚀 Creating demo launcher...")
        create_demo_launcher()
        print("\\n✅ README integration is ready!")
        print("\\nTo test the GUI:")
        print("1. python3 examples/demo_readme_gui.py")
        print("2. Open http://localhost:5000/readme")
    except Exception:
        print("\\n❌ Please fix the issues above before testing.")
        sys.exit(1)
