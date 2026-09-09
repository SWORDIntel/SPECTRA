"""
Projection Lag Monitor — Track outbox → projection pipeline health
===================================================================

Measures how many IndexOutbox events are unprocessed per projection.
Useful for detecting when projections can't keep up with writes.

Usage (library)::

    from tgarchive.services.projection_lag import measure_lag

    lag = measure_lag("spectra.db")

Usage (CLI)::

    spectra-cli index lag
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict

from ..db.index_outbox import IndexOutbox
from ..sqlite_runtime import connect_sqlite

logger = logging.getLogger(__name__)


def measure_lag(db_path: Path | str) -> Dict[str, Any]:
    """Measure projection lag — unprocessed outbox events per projection.

    Returns:
        Dict with: total_pending, by_projection, processing_rate, oldest_pending
    """
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Total unprocessed events
        total_pending = conn.execute(
            "SELECT COUNT(*) as count FROM index_outbox WHERE processed_at IS NULL"
        ).fetchone()["count"]

        # Oldest unprocessed event
        oldest = conn.execute(
            "SELECT created_at, source_table, source_key FROM index_outbox WHERE processed_at IS NULL ORDER BY sequence_id ASC LIMIT 1"
        ).fetchone()
        oldest_pending = {
            "created_at": oldest["created_at"],
            "source_table": oldest["source_table"],
            "source_key": oldest["source_key"],
        } if oldest else None

        # Processed count (for rate calculation)
        processed = conn.execute(
            "SELECT COUNT(*) as count FROM index_outbox WHERE processed_at IS NOT NULL"
        ).fetchone()["count"]

        # Failed events
        failed = conn.execute(
            "SELECT COUNT(*) as count FROM index_outbox WHERE error IS NOT NULL"
        ).fetchone()["count"]

        # Per-source-table breakdown of pending events
        by_table = {}
        rows = conn.execute(
            """
            SELECT source_table, COUNT(*) as count
            FROM index_outbox
            WHERE processed_at IS NULL
            GROUP BY source_table
            ORDER BY count DESC
            """,
        ).fetchall()
        for row in rows:
            by_table[row["source_table"]] = row["count"]

        # Per-projection breakdown (from projection records)
        by_projection = {}
        try:
            proj_rows = conn.execute(
                """
                SELECT projection_name, COUNT(*) as projected_count
                FROM index_projection_records
                GROUP BY projection_name
                """,
            ).fetchall()
            for row in proj_rows:
                by_projection[row["projection_name"]] = {
                    "projected_records": row["projected_count"],
                }
        except sqlite3.OperationalError:
            pass  # projection records table may not exist yet

        # Total outbox events
        total_events = conn.execute(
            "SELECT COUNT(*) as count FROM index_outbox"
        ).fetchone()["count"]

    processing_rate = (processed / total_events * 100) if total_events > 0 else 100.0

    return {
        "total_events": total_events,
        "processed": processed,
        "pending": total_pending,
        "failed": failed,
        "processing_rate_pct": round(processing_rate, 2),
        "oldest_pending": oldest_pending,
        "pending_by_table": by_table,
        "projection_status": by_projection,
        "healthy": total_pending == 0 and failed == 0,
    }


__all__ = ["measure_lag"]
