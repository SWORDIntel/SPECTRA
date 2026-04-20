"""Compatibility wrapper for notification utilities.

This module keeps legacy imports like ``tgarchive.notifications`` working
while the implementation lives under ``tgarchive.utils.notifications``.
"""

from __future__ import annotations

from tgarchive.utils.notifications import NotificationManager

__all__ = ["NotificationManager"]
