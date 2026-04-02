"""Compatibility alias for deduplication helpers."""

from .core import deduplication as _deduplication
import sys as _sys

_sys.modules[__name__] = _deduplication
