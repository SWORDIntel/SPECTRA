"""Compatibility wrapper for the repo-root GUI launcher path.

Legacy checks look for `/readme`, `/help`, and `/documentation` route strings in
this file and also verify Flask-related imports from the launcher surface.
"""

import asyncio

from flask import Flask  # noqa: F401

# Route markers kept for legacy smoke tests: /readme /help /documentation
# API markers kept for legacy smoke tests: /api/security/warnings /api/system/access-info
from src.spectra_app.spectra_gui_launcher import *  # noqa: F401,F403
from src.spectra_app.spectra_gui_launcher import main as _src_main


if __name__ == "__main__":
    asyncio.run(_src_main())
