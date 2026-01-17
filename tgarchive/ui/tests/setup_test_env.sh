#!/bin/bash
# Setup script for full test environment
# Installs all dependencies needed for comprehensive testing

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPECTRA_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "Setting up SPECTRA test environment..."
echo "======================================"
echo ""

cd "$SPECTRA_ROOT"

# Create virtual environment if it doesn't exist
if [ ! -d "test_env" ]; then
    echo "Creating virtual environment..."
    python3 -m venv test_env
fi

# Activate virtual environment
source test_env/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip -q

# Install core dependencies
echo "Installing core dependencies..."
pip install -q telethon>=1.40.0 npyscreen rich PyYAML pytz tqdm

# Install additional test dependencies
echo "Installing test dependencies..."
pip install -q pytest pytest-asyncio

echo ""
echo "Test environment setup complete!"
echo ""
echo "To activate: source test_env/bin/activate"
echo "To run tests: python3 tgarchive/ui/tests/test_harness_main.py"
