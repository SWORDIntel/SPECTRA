"""
This package handles the forwarding of message attachments between Telegram entities.
"""
from __future__ import annotations

from .forwarder import AttachmentForwarder
from .queue import QueueManager
from .workflows import Workflows

__all__ = ["AttachmentForwarder", "QueueManager", "Workflows"]
