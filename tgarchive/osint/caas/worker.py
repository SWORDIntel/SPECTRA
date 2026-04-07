from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from tgarchive.db import SpectraDB
from tgarchive.osint.caas.profiler import CAASProfiler

logger = logging.getLogger(__name__)


def _claim_batch(db: SpectraDB, batch_size: int) -> list[tuple[Any, ...]]:
    rows = db.conn.execute(
        """
        SELECT id, channel_id, message_id, topic_id, sender_id, sender_username, date, content
        FROM caas_profile_queue
        WHERE status = 'pending'
        ORDER BY id
        LIMIT ?
        """,
        (batch_size,),
    ).fetchall()
    if not rows:
        return []

    queue_ids = [row[0] for row in rows]
    placeholders = ",".join("?" for _ in queue_ids)
    db.conn.execute(
        f"UPDATE caas_profile_queue SET status = 'processing' WHERE id IN ({placeholders})",
        queue_ids,
    )
    db.conn.commit()
    return rows


def process_queue(db_path: str | Path = "spectra.db", batch_size: int = 500, once: bool = True) -> int:
    db = SpectraDB(db_path)
    profiler = CAASProfiler()
    processed = 0

    logger.info("Starting CAAS queue worker (db=%s, batch_size=%s)", db_path, batch_size)

    while True:
        rows = _claim_batch(db, batch_size)
        if not rows:
            logger.info("CAAS queue is empty")
            break

        for row in rows:
            q_id, channel_id, message_id, topic_id, sender_id, sender_username, date_value, content = row
            try:
                profile = profiler.profile_message(content or "", sender_username=sender_username)
                profiler.save_profile(db, channel_id, message_id, profile)
                db.conn.execute(
                    "UPDATE caas_profile_queue SET status = 'completed', error = NULL WHERE id = ?",
                    (q_id,),
                )
                processed += 1
            except Exception as exc:
                logger.exception("Failed to process CAAS queue item %s", q_id)
                db.conn.execute(
                    "UPDATE caas_profile_queue SET status = 'failed', error = ? WHERE id = ?",
                    (str(exc), q_id),
                )
            db.conn.commit()

        logger.info("Processed %s CAAS queue items in this pass", len(rows))
        if once:
            break

    logger.info("CAAS worker finished; total processed=%s", processed)
    return processed
