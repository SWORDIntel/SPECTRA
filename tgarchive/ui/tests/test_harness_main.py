#!/usr/bin/env python3
"""
Main Test Harness Entry Point
==============================

Runs all test suites for SPECTRA operator-friendly enhancements.
Can be called from tools/vectorrevamp or run standalone.
"""

import sys
from pathlib import Path

# Add SPECTRA to path
spectra_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(spectra_root))

from test_enhancements import run_all_tests
from test_integration_full import run_integration_tests


def main():
    """Run all test suites"""
    print("=" * 70)
    print("SPECTRA Operator-Friendly Enhancements Test Harness")
    print("=" * 70)
    print()
    
    print("Running unit tests...")
    print("-" * 70)
    unit_success = run_all_tests()
    print()
    
    print("Running integration tests...")
    print("-" * 70)
    integration_success = run_integration_tests()
    print()
    
    print("=" * 70)
    if unit_success and integration_success:
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
