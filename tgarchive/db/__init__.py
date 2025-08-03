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
LOGS_DIR = Path.cwd() / "logs"
LOGS_DIR.mkdir(exist_ok=True)
log_file = LOGS_DIR / f"{APP_NAME}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(APP_NAME)

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
