"""Built-in operation definitions for the modern SPECTRA CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .index_models import (
    IndexArchiveScanResult,
    IndexBackfillDatabaseResult,
    IndexBackfillExportResult,
    IndexBenchmarkResult,
    IndexDrainResult,
    IndexGraphLookupResult,
    IndexMessageLookupResult,
    IndexProcessResult,
    IndexRebuildResult,
    IndexRecordLookupResult,
    IndexStatusResult,
    IndexVerifyResult,
    IndexWatchRequest,
    IndexWatchResult,
)
from .registry import OperationDefinition, OperationRegistry


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionResult(BaseModel):
    spectra: str
    python: str


class DoctorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: bool = False


class DoctorResult(BaseModel):
    checks: dict[str, Any]


class ConfigGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)


class ConfigGetResult(BaseModel):
    path: str
    value: Any


class TaskShowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    tail: int = Field(default=10, ge=0, le=1000)


class TaskRecordResult(BaseModel):
    record: dict[str, Any]


class ChannelStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    export_dir: Path
    tail: int = Field(default=10, ge=0, le=1000)


class ChannelStatusResult(BaseModel):
    status: dict[str, Any]


class ChannelDownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    entity: str = Field(min_length=1)
    output_dir: Path
    account: str | None = None
    auto: bool = False
    no_proxy: bool = False
    no_media: bool = False
    media_only: bool = False
    max_connections: int = Field(default=32, ge=1, le=128)
    max_retries: int = Field(default=5, ge=0, le=100)
    retry_delay: float = Field(default=3.0, ge=0.0)
    fail_fast: bool = False
    retry_flood_waits: bool = True
    progress_interval: float = Field(default=15.0, ge=1.0)
    stall_timeout: float = Field(default=75.0, ge=1.0)
    limit: int | None = Field(default=None, ge=1)
    min_id: int | None = None
    max_id: int | None = None
    restart: bool = False
    detach: bool = False


class ChannelDownloadPlanResult(BaseModel):
    argv: list[str]
    output_dir: str
    detach: bool
    dry_run: bool


class ChannelDownloadRetryFailedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    entity: str = Field(min_length=1)
    output_dir: Path
    account: str | None = None
    no_proxy: bool = False
    max_connections: int = Field(default=32, ge=1, le=128)
    max_retries: int = Field(default=5, ge=0, le=100)
    retry_delay: float = Field(default=3.0, ge=0.0)
    fail_fast: bool = False
    retry_flood_waits: bool = True
    progress_interval: float = Field(default=15.0, ge=1.0)
    stall_timeout: float = Field(default=75.0, ge=1.0)
    detach: bool = False


class DiscoveryRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    seed: str | None = None
    seeds_file: Path | None = None
    crawler_dir: Path | None = None
    depth: int = Field(default=2, ge=1, le=3)
    messages: int = Field(default=1000, ge=1, le=1_000_000)
    export: Path | None = None
    parallel: bool = False
    max_workers: int | None = Field(default=None, ge=1, le=128)


class NetworkAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    crawler_dir: Path | None = None
    from_db: bool = False
    plot: bool = False
    metric: str = Field(default="combined", min_length=1)
    export: Path | None = None
    top: int = Field(default=50, ge=1, le=10000)


class SearchFulltextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    channel_id: int | None = None


class ArchiveChannelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str = Field(min_length=1)
    auto: bool = False
    no_media: bool = False
    no_avatars: bool = False
    no_topics: bool = False


class ExportTableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    table: str = Field(min_length=1)
    output_file: Path
    export_format: str = Field(default="jsonl", min_length=1)
    limit: int | None = Field(default=None, ge=1)
    offset: int = Field(default=0, ge=0)


class IndexProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_size: int = Field(default=100, ge=1, le=10_000)
    lease_seconds: int = Field(default=300, ge=1, le=86_400)


class IndexDrainRequest(IndexProcessRequest):
    max_batches: int = Field(default=0, ge=0, le=100_000)


class IndexProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection: str = Field(
        default="all",
        pattern=(
            r"^(all|keystone|media|checkpoints|events|exports|archive-members|"
            r"qihse|fts|graph|keystone\.ids\.v1|keystone\.media_manifest\.v1|"
            r"keystone\.checkpoints\.v1|keystone\.events\.v1|"
            r"keystone\.export_records\.v1|keystone\.archive_members\.v1|qihse\.content\.v1|"
            r"fts\.messages\.v1|qihse\.graph\.v1)$"
        ),
    )


class IndexVerifyRequest(IndexProjectionRequest):
    native: bool = True
    sample_size: int = Field(default=16, ge=1, le=10_000)


class IndexLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: int
    message_id: int


class IndexRecordLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection: str = Field(pattern=r"^(checkpoints|events|exports|archive-members)$")
    namespace: str = Field(min_length=1, max_length=128)
    external_id: str = Field(min_length=1, max_length=4096)


class IndexGraphRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_type: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    edge_type: str | None = Field(default=None, max_length=31)
    direction: str = Field(default="both", pattern=r"^(outgoing|incoming|both)$")
    limit: int = Field(default=100, ge=1, le=10_000)


class IndexBackfillExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    export_dir: Path
    limit: int | None = Field(default=None, ge=1)


class IndexBackfillDatabaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int | None = Field(default=None, ge=1)


class IndexScanArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    archive_path: Path
    limit: int = Field(default=10_000, ge=1, le=100_000)


class IndexBenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    database: Path | None = None
    events: int = Field(default=1000, ge=10, le=1_000_000)
    writers: int = Field(default=16, ge=1, le=256)
    lookups: int = Field(default=10, ge=1, le=10_000)
    batch_size: int = Field(default=1000, ge=1, le=100_000)


class OperationPlanResult(BaseModel):
    planned: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


def create_builtin_registry() -> OperationRegistry:
    registry = OperationRegistry()
    for definition in _definitions():
        registry.register(definition)
    return registry


def _definitions() -> list[OperationDefinition]:
    return [
        OperationDefinition(
            operation_id="version",
            title="Version",
            summary="Print SPECTRA and Python runtime versions.",
            group="system",
            request_model=EmptyRequest,
            result_model=VersionResult,
            local_only=True,
            cli="spectra version",
            examples=[{"arguments": {}}],
        ),
        OperationDefinition(
            operation_id="doctor",
            title="Doctor",
            summary="Check local configuration, runtime, and optional capability readiness.",
            group="system",
            request_model=DoctorRequest,
            result_model=DoctorResult,
            local_only=True,
            cli="spectra doctor --capabilities",
            examples=[{"arguments": {"capabilities": True}}],
        ),
        OperationDefinition(
            operation_id="config.get",
            title="Config Get",
            summary="Read one dotted configuration value with secret redaction.",
            group="config",
            request_model=ConfigGetRequest,
            result_model=ConfigGetResult,
            local_only=True,
            cli="spectra config get accounts.0.session_name --output json",
            examples=[{"arguments": {"path": "accounts.0.session_name"}}],
        ),
        OperationDefinition(
            operation_id="task.show",
            title="Task Show",
            summary="Show one locally recorded detached task with process and log status.",
            group="task",
            request_model=TaskShowRequest,
            result_model=TaskRecordResult,
            local_only=True,
            cli="spectra task show task-20260728T205258Z --output json",
            examples=[{"arguments": {"task_id": "task-20260728T205258Z", "tail": 10}}],
        ),
        OperationDefinition(
            operation_id="channel.status",
            title="Channel Status",
            summary="Inspect a local channel download export directory without connecting to Telegram.",
            group="channel",
            request_model=ChannelStatusRequest,
            result_model=ChannelStatusResult,
            local_only=True,
            cli="spectra channel status channel_downloads/Example_123 --output json",
            examples=[{"arguments": {"export_dir": "channel_downloads/Example_123", "tail": 20}}],
        ),
        OperationDefinition(
            operation_id="channel.download",
            title="Channel Download",
            summary="Download a Telegram channel through the accelerated resumable media pipeline.",
            group="channel",
            request_model=ChannelDownloadRequest,
            result_model=ChannelDownloadPlanResult,
            local_only=False,
            telegram_backed=True,
            supports_dry_run=True,
            capability="telegram",
            cli="spectra channel download @target --output-dir channel_downloads --media-only",
            examples=[
                {
                    "arguments": {
                        "entity": "-1002407846598",
                        "output_dir": "/fast/ULPs",
                        "media_only": True,
                        "no_proxy": True,
                        "max_connections": 32,
                    }
                }
            ],
        ),
        OperationDefinition(
            operation_id="channel.download.retry_failed",
            title="Channel Download Retry Failed",
            summary="Retry only failed media from a previous channel download.",
            group="channel",
            request_model=ChannelDownloadRetryFailedRequest,
            result_model=OperationPlanResult,
            local_only=False,
            telegram_backed=True,
            supports_dry_run=True,
            capability="telegram",
            cli="spectra channel retry-failed @target --output-dir channel_downloads",
            examples=[{"arguments": {"entity": "@target", "output_dir": "channel_downloads"}}],
        ),
        OperationDefinition(
            operation_id="discovery.run",
            title="Discovery Run",
            summary="Crawl Telegram seeds and persist discovered channel/network results.",
            group="discovery",
            request_model=DiscoveryRunRequest,
            result_model=OperationPlanResult,
            local_only=False,
            telegram_backed=True,
            supports_dry_run=True,
            capability="telegram",
            cli="spectra discover run --seed @target --depth 2 --messages 1000",
            examples=[{"arguments": {"seed": "@target", "depth": 2, "messages": 1000}}],
        ),
        OperationDefinition(
            operation_id="network.analyze",
            title="Network Analyze",
            summary="Analyze a crawler export or the local database network graph.",
            group="network",
            request_model=NetworkAnalyzeRequest,
            result_model=OperationPlanResult,
            local_only=True,
            supports_dry_run=True,
            cli="spectra network analyze --from-db --metric combined --top 50",
            examples=[{"arguments": {"from_db": True, "metric": "combined", "top": 50}}],
        ),
        OperationDefinition(
            operation_id="search.fulltext",
            title="Full-Text Search",
            summary="Search archived message text with pagination and an optional channel filter.",
            group="search",
            request_model=SearchFulltextRequest,
            result_model=OperationPlanResult,
            local_only=True,
            supports_dry_run=True,
            cli="spectra search fulltext \"query\" --limit 50",
            examples=[{"arguments": {"query": "query", "limit": 50}}],
        ),
        OperationDefinition(
            operation_id="channel.archive",
            title="Channel Archive",
            summary="Archive an accessible Telegram channel into the configured database.",
            group="channel",
            request_model=ArchiveChannelRequest,
            result_model=OperationPlanResult,
            local_only=False,
            telegram_backed=True,
            supports_dry_run=True,
            capability="telegram",
            cli="spectra channel archive @target --no-media",
            examples=[{"arguments": {"entity": "@target", "no_media": True}}],
        ),
        OperationDefinition(
            operation_id="export.table",
            title="Export Table",
            summary="Export a validated local database table to JSON, JSONL, or CSV.",
            group="export",
            request_model=ExportTableRequest,
            result_model=OperationPlanResult,
            local_only=True,
            supports_dry_run=True,
            cli="spectra export table messages --output-file exports/messages.jsonl --format jsonl",
            examples=[{"arguments": {"table": "messages", "output_file": "exports/messages.jsonl", "export_format": "jsonl"}}],
        ),
        OperationDefinition(
            operation_id="index.status",
            title="Index Status",
            summary="Show pending durable index events and projection checkpoints.",
            group="index",
            request_model=EmptyRequest,
            result_model=IndexStatusResult,
            local_only=True,
            cli="spectra index status --output json",
            examples=[{"arguments": {}}],
        ),
        OperationDefinition(
            operation_id="index.process",
            title="Index Process",
            summary="Consume a bounded batch of durable outbox events into derived projections.",
            group="index",
            request_model=IndexProcessRequest,
            result_model=IndexProcessResult,
            local_only=True,
            supports_dry_run=True,
            cli="spectra index process --batch-size 100 --output json",
            examples=[{"arguments": {"batch_size": 100, "lease_seconds": 300}}],
        ),
        OperationDefinition(
            operation_id="index.watch",
            title="Index Watch",
            summary=(
                "Supervise repeated typed index.process batches with bounded polling "
                "and backoff; execution belongs to the long-running CLI/service loop."
            ),
            group="index",
            request_model=IndexWatchRequest,
            result_model=IndexWatchResult,
            local_only=True,
            cli="spectra index watch --batch-size 1000 --poll-interval 0.1 --output json",
            examples=[{
                "arguments": {
                    "batch_size": 1000,
                    "lease_seconds": 300,
                    "poll_interval": 0.1,
                    "max_backoff": 60.0,
                    "idle_exit": 0.0,
                },
            }],
        ),
        OperationDefinition(
            operation_id="index.rebuild",
            title="Index Rebuild",
            summary="Rebuild QIHSE and/or KEYSTONE projection records from the committed outbox.",
            group="index",
            request_model=IndexProjectionRequest,
            result_model=IndexRebuildResult,
            local_only=True,
            supports_dry_run=True,
            cli="spectra index rebuild --projection all --output json",
            examples=[{"arguments": {"projection": "all"}}],
        ),
        OperationDefinition(
            operation_id="index.drain",
            title="Index Drain",
            summary="Consume outbox batches until empty or a configured batch limit is reached.",
            group="index",
            request_model=IndexDrainRequest,
            result_model=IndexDrainResult,
            local_only=True,
            supports_dry_run=True,
            cli="spectra index drain --batch-size 1000 --output json",
            examples=[{"arguments": {"batch_size": 1000, "lease_seconds": 300, "max_batches": 0}}],
        ),
        OperationDefinition(
            operation_id="index.verify",
            title="Index Verify",
            summary="Compare projection rows and checksums with SQLite and sample native lookups.",
            group="index",
            request_model=IndexVerifyRequest,
            result_model=IndexVerifyResult,
            local_only=True,
            cli="spectra index verify --projection all --native --output json",
            examples=[{"arguments": {"projection": "all", "native": True, "sample_size": 16}}],
        ),
        OperationDefinition(
            operation_id="index.lookup",
            title="Index Lookup",
            summary="Look up a channel-scoped Telegram message through the KEYSTONE projection.",
            group="index",
            request_model=IndexLookupRequest,
            result_model=IndexMessageLookupResult,
            local_only=True,
            cli="spectra index lookup --channel-id -100123 --message-id 42 --output json",
            examples=[{"arguments": {"channel_id": -100123, "message_id": 42}}],
        ),
        OperationDefinition(
            operation_id="index.lookup-record",
            title="Index Record Lookup",
            summary="Resolve a typed checkpoint, event, export, or archive-member record through KEYSTONE.",
            group="index",
            request_model=IndexRecordLookupRequest,
            result_model=IndexRecordLookupResult,
            local_only=True,
            cli="spectra index lookup-record events task_events 42 --output json",
            examples=[{
                "arguments": {
                    "projection": "events",
                    "namespace": "task_events",
                    "external_id": "42",
                },
            }],
        ),
        OperationDefinition(
            operation_id="index.graph",
            title="Index Graph Query",
            summary="Query persistent typed QIHSE relationship edges for one stable entity node.",
            group="index",
            request_model=IndexGraphRequest,
            result_model=IndexGraphLookupResult,
            local_only=True,
            cli="spectra index graph --node-type message --external-id=-100123:42 --output json",
            examples=[{
                "arguments": {
                    "node_type": "message",
                    "external_id": "-100123:42",
                    "edge_type": "IN_CHANNEL",
                    "direction": "outgoing",
                    "limit": 100,
                },
            }],
        ),
        OperationDefinition(
            operation_id="index.backfill-export",
            title="Index Export Backfill",
            summary="Import a stable channel media-manifest snapshot into the durable index outbox.",
            group="index",
            request_model=IndexBackfillExportRequest,
            result_model=IndexBackfillExportResult,
            local_only=True,
            supports_dry_run=True,
            cli="spectra index backfill-export /fast/ULPs/Channel_123 --output json",
            examples=[{"arguments": {"export_dir": "/fast/ULPs/Channel_123"}}],
        ),
        OperationDefinition(
            operation_id="index.backfill-database",
            title="Index Database Backfill",
            summary="Import safe checkpoint and event identities that predate outbox integration.",
            group="index",
            request_model=IndexBackfillDatabaseRequest,
            result_model=IndexBackfillDatabaseResult,
            local_only=True,
            supports_dry_run=True,
            cli="spectra index backfill-database --output json",
            examples=[{"arguments": {}}],
        ),
        OperationDefinition(
            operation_id="index.scan-archive",
            title="Index Archive Members",
            summary="Scan bounded ZIP/TAR headers into archive-member KEYSTONE records without extraction.",
            group="index",
            request_model=IndexScanArchiveRequest,
            result_model=IndexArchiveScanResult,
            local_only=True,
            supports_dry_run=True,
            cli="spectra index scan-archive exports/archive.zip --output json",
            examples=[{"arguments": {"archive_path": "exports/archive.zip", "limit": 10000}}],
        ),
        OperationDefinition(
            operation_id="index.benchmark",
            title="Index Benchmark",
            summary="Measure concurrent writes, native projection drain, lookup, replay, and lease recovery.",
            group="index",
            request_model=IndexBenchmarkRequest,
            result_model=IndexBenchmarkResult,
            local_only=True,
            cli="spectra index benchmark --events 1000 --writers 16 --output json",
            examples=[{"arguments": {"events": 1000, "writers": 16, "lookups": 10}}],
        ),
    ]
