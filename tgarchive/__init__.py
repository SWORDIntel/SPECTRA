"""Public package surface for tgarchive.

Keep import-time side effects minimal so lightweight commands such as
metadata access and help/inspection do not require Telegram-specific
dependencies to already be installed.
"""

from __future__ import annotations

from .core.config_models import Config as ArchCfg

__version__ = "1.0.0"
__all__ = ["archive_channel", "ArchCfg"]


def __getattr__(name: str):
    if name == "archive_channel":
        from .core.sync import archive_channel

        return archive_channel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
