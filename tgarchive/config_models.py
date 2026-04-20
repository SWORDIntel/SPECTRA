"""Compatibility wrapper for legacy config imports.

The canonical configuration model lives in `tgarchive.core.config_models`,
but a number of integration scripts still import `tgarchive.config_models`.
"""

from __future__ import annotations

from tgarchive.core.config_models import Config, DEFAULT_CFG

__all__ = ["Config", "DEFAULT_CFG"]
