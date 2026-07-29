"""Reproducible workstation benchmark for the durable indexing pipeline."""

from __future__ import annotations

import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..db.index_outbox import IndexOutbox
from ..db.index_projector import IndexProjector
from ..sqlite_runtime import connect_sqlite


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def benchmark_indexing(
    *,
    database: Path | str | None = None,
    events: int = 1000,
    writers: int = 16,
    lookups: int = 10,
    batch_size: int = 1000,
) -> dict[str, Any]:
    if events < 10 or writers < 1 or lookups < 1 or batch_size < 1:
        raise ValueError("events must be at least 10; writers, lookups, and batch_size must be positive")
    if database is None:
        with tempfile.TemporaryDirectory(prefix="spectra-index-benchmark-") as temporary:
            result = benchmark_indexing(
                database=Path(temporary) / "benchmark.db",
                events=events,
                writers=writers,
                lookups=lookups,
                batch_size=batch_size,
            )
            result["temporary_database"] = True
            return result

    database_path = Path(database).expanduser().resolve()
    outbox = IndexOutbox(database_path)
    channel_id = -1009876543210

    def append_event(message_id: int, *, phase: str) -> int | None:
        return outbox.append(
            source_table="channel_messages",
            source_key=f"{channel_id}:{message_id}",
            event_type="download",
            payload={
                "channel_id": channel_id,
                "message_id": message_id,
                "sender_id": 5000 + (message_id % 100),
                "text": f"{phase} benchmark message {message_id}",
            },
            source_revision=f"{phase}-v1",
        )

    write_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=writers) as executor:
        sequence_ids = list(executor.map(
            lambda message_id: append_event(message_id, phase="bulk"),
            range(1, events + 1),
        ))
    write_seconds = time.perf_counter() - write_started
    if any(sequence_id is None for sequence_id in sequence_ids):
        raise RuntimeError("benchmark unexpectedly generated duplicate outbox events")

    projector = IndexProjector(database_path)
    drain_started = time.perf_counter()
    drain = projector.drain(batch_size=batch_size)
    drain_seconds = time.perf_counter() - drain_started

    concurrent_events = min(200, max(20, events // 5))
    concurrent_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=writers) as executor:
        futures = [
            executor.submit(append_event, events + offset, phase="concurrent")
            for offset in range(1, concurrent_events + 1)
        ]
        concurrent_projection = {"processed": 0, "failed": 0, "batches": 0}
        while not all(future.done() for future in futures) or outbox.status()["outbox"]["pending"]:
            result = projector.process(batch_size=min(batch_size, 200), lease_seconds=30)
            concurrent_projection["processed"] += int(result["processed"])
            concurrent_projection["failed"] += int(result["failed"])
            concurrent_projection["batches"] += 1
            if result["claimed"] == 0:
                time.sleep(0.005)
        for future in futures:
            if future.result() is None:
                raise RuntimeError("concurrent benchmark generated a duplicate event")
    concurrent_seconds = time.perf_counter() - concurrent_started

    lookup_ids = [
        1 + round(index * (events - 1) / max(lookups - 1, 1))
        for index in range(min(lookups, events))
    ]
    lookup_ms: list[float] = []
    for message_id in lookup_ids:
        started = time.perf_counter()
        result = projector.lookup(channel_id=channel_id, message_id=message_id)
        lookup_ms.append((time.perf_counter() - started) * 1000)
        if not result["found"] or not result["native"].get("found"):
            raise RuntimeError(f"benchmark lookup failed for message {message_id}")

    rebuild_started = time.perf_counter()
    rebuild = projector.rebuild(projection="all")
    rebuild_seconds = time.perf_counter() - rebuild_started

    crash_message_id = events + concurrent_events + 1
    crash_sequence = append_event(crash_message_id, phase="crash-recovery")
    claimed = outbox.claim(batch_size=1, lease_seconds=1)
    if not claimed or int(claimed[0]["sequence_id"]) != crash_sequence:
        raise RuntimeError("unable to establish simulated crashed lease")
    with connect_sqlite(database_path) as connection:
        connection.execute(
            "UPDATE index_outbox SET claimed_at='1970-01-01T00:00:00+00:00' WHERE sequence_id=?",
            (crash_sequence,),
        )
    recovered = projector.process(batch_size=1, lease_seconds=1)
    crash_recovery_ok = recovered["processed"] == 1 and recovered["failed"] == 0
    verification = projector.verify(projection="all", native=True, sample_size=min(32, events))
    projector.close()

    result = {
        "database": str(database_path),
        "temporary_database": False,
        "events": events,
        "writers": writers,
        "write": {
            "seconds": round(write_seconds, 6),
            "events_per_second": round(events / write_seconds, 2),
        },
        "drain": {
            "seconds": round(drain_seconds, 6),
            **drain,
        },
        "concurrent": {
            "events": concurrent_events,
            "seconds": round(concurrent_seconds, 6),
            "events_per_second": round(concurrent_events / concurrent_seconds, 2),
            **concurrent_projection,
        },
        "lookup": {
            "samples": len(lookup_ms),
            "mean_ms": round(statistics.fmean(lookup_ms), 3),
            "p50_ms": round(_percentile(lookup_ms, 0.50), 3),
            "p95_ms": round(_percentile(lookup_ms, 0.95), 3),
            "max_ms": round(max(lookup_ms), 3),
        },
        "rebuild": {
            "seconds": round(rebuild_seconds, 6),
            **rebuild,
        },
        "crash_recovery": {
            "ok": crash_recovery_ok,
            "sequence_id": crash_sequence,
            "attempts": outbox.events(after_sequence=int(crash_sequence) - 1, limit=1)[0]["attempts"],
        },
        "verification": verification,
    }
    return result


__all__ = ["benchmark_indexing"]
