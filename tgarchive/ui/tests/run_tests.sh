#!/bin/bash
# Test harness runner for SPECTRA operator-friendly enhancements
# Can be integrated with tools/vectorrevamp

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPECTRA_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

echo "SPECTRA Operator-Friendly Enhancements Test Harness"
echo "===================================================="
echo ""

# Set Python path
export PYTHONPATH="$SPECTRA_ROOT:$PYTHONPATH"

# Run tests
cd "$SCRIPT_DIR"
python3 -m pytest test_enhancements.py -v --tb=short || python3 test_enhancements.py

echo ""
echo "Test harness complete."
