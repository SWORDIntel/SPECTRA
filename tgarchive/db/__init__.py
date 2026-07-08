"""
SPECTRA-004 — Telegram Archiver DB Handler (v1.0)
=================================================
A hardened SQLite backend for SPECTRA-series tools.
Built for **SWORD-EPI** with the same conventions as *SPECTRA-002*:

* WAL-mode, foreign-key integrity, application-level checksums.
* Exponential-back-off on locked writes.
* Conveniences for timeline queries + resumable checkpoints.

MIT-style licence.  © 2025 John (SWORD-EPI) – codename *SPECTRA-004*.
"""
from __future__ import annotations

# ── Standard Library ─────────────────────────────────────────────────────
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Logging setup ────────────────────────────────────────────────────────
APP_NAME = "spectra_004_db"
from tgarchive.core.log_engine import setup_log_engine
logger = setup_log_engine(APP_NAME)

# ── Package exports ──────────────────────────────────────────────────────
from .models import Day, Media, Message, Month, User
from .spectra_db import SpectraDB

__all__ = [
    "SpectraDB",
    "User",
    "Media",
    "Message",
    "Month",
    "Day",
]
