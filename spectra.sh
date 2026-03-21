#!/bin/bash

# Compatibility wrapper for legacy scripts.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/spectra" "$@"
