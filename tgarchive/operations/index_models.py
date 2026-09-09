"""Typed request and result contracts for durable index operations."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictIndexModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IndexOutboxCounts(StrictIndexModel):
    total: int = Field(ge=0)
    pending: int = Field(ge=0)
    claimed: int = Field(ge=0)
    processed: int = Field(ge=0)
    failed: int = Field(ge=0)


class IndexProjectionState(StrictIndexModel):
    projection_name: str
    projection_version: str
    last_sequence_id: int = Field(ge=0)
    source_checksum: str | None
    row_count: int = Field(ge=0)
    last_success_at: str | None
    last_error: str | None
    updated_at: str


class IndexProjectionRefresh(StrictIndexModel):
    projection: str
    rows: int = Field(ge=0)
    checksum: str
    last_sequence_id: int = Field(ge=0)


class IndexStatusResult(StrictIndexModel):
    database: str
    outbox: IndexOutboxCounts
    projections: list[IndexProjectionState]


class IndexProjectionFailure(StrictIndexModel):
    sequence_id: int = Field(ge=1)
    error: str


class IndexProcessDetails(StrictIndexModel):
    ok: bool
    claimed: int = Field(ge=0)
    processed: int = Field(ge=0)
    failed: int = Field(ge=0)
    failures: list[IndexProjectionFailure]
    projections: list[IndexProjectionRefresh]
    qihse_native: dict[str, Any] | None
    graph_native: dict[str, Any] | None


class IndexProcessDryRunDetails(StrictIndexModel):
    dry_run: Literal[True]
    batch_size: int = Field(ge=1)
    lease_seconds: int = Field(ge=1)


class IndexProcessResult(StrictIndexModel):
    details: IndexProcessDetails | IndexProcessDryRunDetails


class IndexDrainDetails(StrictIndexModel):
    ok: bool
    batches: int = Field(ge=0)
    claimed: int = Field(ge=0)
    processed: int = Field(ge=0)
    failed: int = Field(ge=0)
    drained: bool
    last_batch: IndexProcessDetails | None


class IndexDrainDryRunDetails(IndexProcessDryRunDetails):
    max_batches: int = Field(ge=0)


class IndexDrainResult(StrictIndexModel):
    details: IndexDrainDetails | IndexDrainDryRunDetails


class IndexRebuildDetails(StrictIndexModel):
    ok: bool
    events: int = Field(ge=0)
    projections: list[IndexProjectionRefresh]
    qihse_native: dict[str, Any] | None
    graph_native: dict[str, Any] | None
    error: str | None = None


class IndexRebuildDryRunDetails(StrictIndexModel):
    dry_run: Literal[True]
    projection: str


class IndexRebuildResult(StrictIndexModel):
    details: IndexRebuildDetails | IndexRebuildDryRunDetails


class IndexNativeVerification(StrictIndexModel):
    model_config = ConfigDict(extra="allow")

    requested: bool
    available: bool | None
    ok: bool
    samples: int = Field(ge=0)
    error: str | None = None
    path: str | None = None
    library: str | None = None
    stats: dict[str, Any] | None = None


class IndexProjectionVerification(StrictIndexModel):
    projection: str
    ok: bool
    expected_rows: int = Field(ge=0)
    actual_rows: int = Field(ge=0)
    expected_checksum: str
    actual_checksum: str
    state_matches: bool
    key_map_matches: bool
    native: IndexNativeVerification


class IndexVerifyDetails(StrictIndexModel):
    ok: bool
    projections: list[IndexProjectionVerification]


class IndexVerifyResult(StrictIndexModel):
    details: IndexVerifyDetails


class IndexProjectedRecord(StrictIndexModel):
    sequence_id: int = Field(ge=1)
    projection: str
    source_table: str
    source_key: str
    payload: dict[str, Any]


class IndexMessageLookupDetails(StrictIndexModel):
    channel_id: int
    message_id: int
    numeric_key: int
    found: bool
    native: dict[str, Any]
    records: list[IndexProjectedRecord]


class IndexMessageLookupResult(StrictIndexModel):
    details: IndexMessageLookupDetails


class IndexRecordLookupDetails(StrictIndexModel):
    projection: str
    namespace: str
    external_id: str
    numeric_key: int
    found: bool
    native: dict[str, Any]
    records: list[IndexProjectedRecord]


class IndexRecordLookupResult(StrictIndexModel):
    details: IndexRecordLookupDetails


class IndexGraphLookupDetails(StrictIndexModel):
    found: bool
    node_key: str
    node_id: int | None = None
    records: list[dict[str, Any]]
    native: dict[str, Any] | None = None


class IndexGraphLookupResult(StrictIndexModel):
    details: IndexGraphLookupDetails


class IndexBackfillExportDetails(StrictIndexModel):
    database: str
    export_dir: str
    manifest_path: str
    export_id: str
    channel_id: int
    snapshot_bytes: int = Field(ge=0)
    records_read: int = Field(ge=0)
    inserted: int = Field(ge=0)
    already_present: int = Field(ge=0)
    invalid: int = Field(ge=0)
    incomplete_tail: int = Field(ge=0)


class IndexBackfillExportDryRunDetails(StrictIndexModel):
    dry_run: Literal[True]
    database: str
    export_dir: str
    limit: int | None = Field(default=None, ge=1)


class IndexBackfillExportResult(StrictIndexModel):
    details: IndexBackfillExportDetails | IndexBackfillExportDryRunDetails


class IndexBackfillTableCounts(StrictIndexModel):
    scanned: int = Field(ge=0)
    inserted: int = Field(ge=0)
    already_present: int = Field(ge=0)


class IndexBackfillDatabaseDetails(StrictIndexModel):
    database: str
    scanned: int = Field(ge=0)
    inserted: int = Field(ge=0)
    already_present: int = Field(ge=0)
    tables: dict[str, IndexBackfillTableCounts]


class IndexBackfillDatabaseDryRunDetails(StrictIndexModel):
    dry_run: Literal[True]
    database: str
    limit: int | None = Field(default=None, ge=1)


class IndexBackfillDatabaseResult(StrictIndexModel):
    details: IndexBackfillDatabaseDetails | IndexBackfillDatabaseDryRunDetails


class IndexArchiveScanDetails(StrictIndexModel):
    database: str
    archive_path: str
    archive_id: str
    archive_format: Literal["zip", "tar"]
    record_limit: int = Field(ge=1)
    records_scanned: int = Field(ge=0)
    inserted: int = Field(ge=0)
    already_present: int = Field(ge=0)
    truncated: bool


class IndexArchiveScanDryRunDetails(StrictIndexModel):
    dry_run: Literal[True]
    database: str
    archive_path: str
    limit: int = Field(ge=1)


class IndexArchiveScanResult(StrictIndexModel):
    details: IndexArchiveScanDetails | IndexArchiveScanDryRunDetails


class IndexBenchmarkWrite(StrictIndexModel):
    seconds: float = Field(ge=0.0)
    events_per_second: float = Field(ge=0.0)


class IndexBenchmarkDrain(IndexDrainDetails):
    seconds: float = Field(ge=0.0)


class IndexBenchmarkConcurrent(IndexBenchmarkWrite):
    events: int = Field(ge=0)
    processed: int = Field(ge=0)
    failed: int = Field(ge=0)
    batches: int = Field(ge=0)


class IndexBenchmarkLookup(StrictIndexModel):
    samples: int = Field(ge=0)
    mean_ms: float = Field(ge=0.0)
    p50_ms: float = Field(ge=0.0)
    p95_ms: float = Field(ge=0.0)
    max_ms: float = Field(ge=0.0)


class IndexBenchmarkRebuild(IndexRebuildDetails):
    seconds: float = Field(ge=0.0)


class IndexBenchmarkCrashRecovery(StrictIndexModel):
    ok: bool
    sequence_id: int = Field(ge=1)
    attempts: int = Field(ge=1)


class IndexBenchmarkDetails(StrictIndexModel):
    database: str
    temporary_database: bool
    events: int = Field(ge=10)
    writers: int = Field(ge=1)
    write: IndexBenchmarkWrite
    drain: IndexBenchmarkDrain
    concurrent: IndexBenchmarkConcurrent
    lookup: IndexBenchmarkLookup
    rebuild: IndexBenchmarkRebuild
    crash_recovery: IndexBenchmarkCrashRecovery
    verification: IndexVerifyDetails


class IndexBenchmarkDryRunDetails(StrictIndexModel):
    dry_run: Literal[True]
    database: str | None
    events: int = Field(ge=10)
    writers: int = Field(ge=1)
    lookups: int = Field(ge=1)
    batch_size: int = Field(ge=1)


class IndexBenchmarkResult(StrictIndexModel):
    details: IndexBenchmarkDetails | IndexBenchmarkDryRunDetails


class IndexWatchRequest(StrictIndexModel):
    batch_size: int = Field(default=1000, ge=1, le=10_000)
    lease_seconds: int = Field(default=300, ge=1, le=86_400)
    poll_interval: float = Field(default=0.1, ge=0.1, le=3600.0)
    max_backoff: float = Field(default=60.0, ge=1.0, le=3600.0)
    idle_exit: float = Field(default=0.0, ge=0.0)


class IndexWatchResult(StrictIndexModel):
    batches: int = Field(ge=0)
    claimed: int = Field(ge=0)
    processed: int = Field(ge=0)
    failed: int = Field(ge=0)
    worker_errors: int = Field(ge=0)
    interrupted: bool = False
    elapsed_seconds: float = Field(ge=0.0)


__all__ = [
    "IndexArchiveScanResult",
    "IndexBackfillDatabaseResult",
    "IndexBackfillExportResult",
    "IndexBenchmarkResult",
    "IndexDrainResult",
    "IndexGraphLookupResult",
    "IndexMessageLookupResult",
    "IndexProcessResult",
    "IndexRebuildResult",
    "IndexRecordLookupResult",
    "IndexStatusResult",
    "IndexVerifyResult",
    "IndexWatchRequest",
    "IndexWatchResult",
]
