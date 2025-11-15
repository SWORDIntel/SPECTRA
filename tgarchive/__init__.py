# tgarchive/__init__.py
from .core.sync import archive_channel # archive_channel remains in sync.py
from .core.config_models import Config as ArchCfg # Config (aliased as ArchCfg) is now from config_models.py

__version__ = "1.0.0"  # Update as needed
__all__ = ["archive_channel", "ArchCfg"]
