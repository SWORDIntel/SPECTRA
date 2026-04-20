"""Compatibility wrapper for the repo-root orchestrator import path.

The implementation lives under ``src.spectra_app`` so the repo-root package
can keep legacy imports working while the packaged distribution exposes the
same module tree.
"""

from src.spectra_app.spectra_orchestrator import *  # noqa: F401,F403

