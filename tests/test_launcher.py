#!/usr/bin/env python3
"""
SPECTRA Launcher Test Suite
===========================

Quick test script to validate the launcher system components
"""

import subprocess
import sys
import os
from pathlib import Path

def run_test(name, command, expected_return_codes=[0]):
    """Run a test command and report results"""
    print(f"Testing {name}...")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode in expected_return_codes:
            print(f"  ✓ {name} - PASSED")
            return True
        else:
            print(f"  ✗ {name} - FAILED (return code: {result.returncode})")
            if result.stderr:
                print(f"    Error: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"  ✗ {name} - ERROR: {e}")
        return False

def main():
    """Run launcher system tests"""
    project_root = Path(__file__).resolve().parents[1]
    os.chdir(project_root)

    print("SPECTRA Launcher System Test Suite")
    print("=" * 50)

    tests = [
        ("Python launcher help", "python3 scripts/spectra_launch.py --help"),
        ("Python launcher check", "python3 scripts/spectra_launch.py --check", [0, 1]),
        ("Splash screen check", "python3 scripts/spectra_splash.py --check"),
        ("Bash launcher help", "bash spectra.sh --help"),
        ("Bash launcher status", "bash spectra.sh --status"),
        ("File permissions", "ls -la scripts/*.py spectra.sh", [0]),
    ]

    passed = 0
    total = len(tests)

    for test_name, command, *expected_codes in tests:
        expected = expected_codes[0] if expected_codes else [0]
        if run_test(test_name, command, expected):
            passed += 1

    print("\n" + "=" * 50)
    print(f"Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Launcher system is ready.")
        return 0
    else:
        print(f"⚠  {total - passed} tests failed. Check system setup.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
