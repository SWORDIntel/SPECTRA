"""Shared utility functions for tgarchive.services modules.

Consolidates helpers that were previously duplicated across multiple
service files (scheduled_analysis, target_tracking, bot_detection,
index_database_backfill, import_service).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional


def parse_dt(dt_str: str) -> Optional[datetime]:
    """Parse an ISO datetime string.

    Handles trailing ``Z`` (UTC designator) by converting it to ``+00:00``
    before falling back to a plain ``datetime.fromisoformat`` call.
    Returns ``None`` if *dt_str* is falsy or cannot be parsed.
    """
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.fromisoformat(dt_str)
        except Exception:
            return None


def revision_hash(payload: dict[str, Any]) -> str:
    """Return a SHA-256 hex digest of *payload* (deterministic JSON encoding).

    The payload is serialised with ``sort_keys=True`` and compact separators
    so that the same logical content always produces the same hash.
    """
    encoded = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["parse_dt", "revision_hash"]
