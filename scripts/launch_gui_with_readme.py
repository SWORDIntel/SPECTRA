#!/usr/bin/env python3
"""
Launch script for SPECTRA GUI with integrated README documentation
"""

import asyncio
import sys
from pathlib import Path

# Ensure repository root is on the import path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from spectra_app.spectra_gui_launcher import SpectraGUILauncher, create_default_config

async def main():
    """Launch SPECTRA GUI with README integration"""
    print("🚀 Starting SPECTRA GUI with Integrated Documentation")
    print("=" * 60)

    # Create configuration
    config = create_default_config()
    config.debug = True
    config.log_level = "INFO"

    # Initialize launcher
    launcher = SpectraGUILauncher(config)

    print(f"📡 Starting server at http://{config.host}:{config.port}")
    print("📖 Documentation available at:")
    print(f"   • http://{config.host}:{config.port}/readme")
    print(f"   • http://{config.host}:{config.port}/help")
    print(f"   • http://{config.host}:{config.port}/documentation")
    print("\n🎯 Features available:")
    print("   • Complete SPECTRA documentation in web interface")
    print("   • Responsive design for mobile and desktop")
    print("   • Integrated navigation from main dashboard")
    print("   • Professional styling with SPECTRA branding")
    print("\n⏹️  Press Ctrl+C to stop the server")
    print("=" * 60)

    try:
        await launcher.start_system()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down SPECTRA GUI...")
        await launcher.stop_system()
        print("✅ Shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())
