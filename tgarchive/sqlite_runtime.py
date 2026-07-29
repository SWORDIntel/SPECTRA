"""Shared SQLite connection policy for concurrent SPECTRA workloads."""

from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_SQLITE_TIMEOUT = 60.0
DEFAULT_BUSY_TIMEOUT_MS = 60_000


def connect_sqlite(
    database: Path | str,
    *,
    timeout: float = DEFAULT_SQLITE_TIMEOUT,
    read_only: bool = False,
    detect_types: int = 0,
) -> sqlite3.Connection:
    """Open SQLite with WAL, foreign keys, and bounded lock waiting."""
    if not isinstance(database, (Path, str)):
        raise TypeError("database must be a path")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    connection = sqlite3.connect(database, timeout=timeout, detect_types=detect_types)
    try:
        connection.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA foreign_keys=ON")
        if not read_only:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
        return connection
    except sqlite3.Error:
        connection.close()
        raise
