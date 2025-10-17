#!/usr/bin/env python3
"""
Demo SPECTRA GUI with README Integration
======================================
"""

import sys
from pathlib import Path

# Ensure repository root is on sys.path for package imports
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

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
            print("\nShutting down...")
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
