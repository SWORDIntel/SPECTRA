# SPECTRA CLI 2.0 Upgrade

  ## Summary

  Rebuild SPECTRA around one polished, documented command interface with full local and authenticated remote parity. Replace synthetic API responses with working
  implementations, preserve existing commands as deprecated aliases until v3, and make every workflow usable without source inspection or an LLM.

  ## Remaining Jobs Tasklist

  ### Active Runtime Work

  - [ ] Monitor the live media-only channel download for `-1002407846598` until completion (rate-limited, ~3h ETA as of 11:07 BST).
  - [x] Confirm the detached downloader process is still running; the current resumed PID is `2668344` with 32 media transfers.
  - [ ] Confirm `/fast/ULPs/TheUnderground_-_Reborn_2407846598/state.json` ends with `complete: true`.
  - [ ] Review `failed_media_ids`, duplicate skips, final media count, and final byte total.
  - [x] Keep `/fast/ULPs/TheUnderground_-_Reborn_2407846598/download.log` as the operator-visible progress log.
  - [x] Confirm `spectra channel status /fast/ULPs/TheUnderground_-_Reborn_2407846598 --output json` reports fresh log progress.
  - [x] Restart the media-only run without `--restart` at `--max-connections 32`; completed files remain skipped by resume state and existing-file checks.

  ### Next Priority Order

  - [x] Implement `task watch` for following detached job logs and status.
  - [x] Implement `task cancel` with guarded SIGINT and state recheck.
  - [x] Add a SQLite-backed task registry migration to replace the current JSONL bridge.
  - [x] Add `config set` and `config unset` with type-preserving JSON values, redaction, validation, and `--yes` safeguards.
  - [x] Add built-in `account login` using the proven phone/code/2FA flow and non-interactive failure modes.
  - [x] Continue modern command coverage for OSINT and database/export surfaces.

  ### Completed In Current Tranche

  - [x] Sync the checkout with upstream before feature work.
  - [x] Configure the authorized Telegram account locally without committing session material.
  - [x] Add `.session` and `.session-journal` ignore rules.
  - [x] Add a whole-channel downloader service with resumable `state.json`.
  - [x] Add media-only exports that skip JSONL metadata when requested.
  - [x] Add existing-file checks before transfer.
  - [x] Add SHA-256 duplicate avoidance against existing destination files.
  - [x] Add per-file check, start, progress, completion, duplicate, skip, and failure log events.
  - [x] Add `--no-proxy` for the channel download path.
  - [x] Add `--max-connections` / `--concurrency`.
  - [x] Replace fixed download batches with a rolling async transfer pool.
  - [x] Raise the default accelerated media transfer concurrency to 32.
  - [x] Guard the concurrent deduplication index with an `asyncio.Lock`.
  - [x] Preserve deterministic message order in metadata while media downloads complete out of order.
  - [x] Add focused downloader and CLI tests for resume, dedupe, existing files, media-only routing, and concurrent transfer behavior.
  - [x] Update README and CLI reference for the new channel download flow.

  ### Channel Downloader Hardening

  - [x] Add `channel retry-failed` backed by persisted failed media IDs and existing-file deduplication.
  - [x] Classify failed transfers as retryable, flood wait, missing media, permission, filesystem, or unknown failures.
  - [x] Add explicit retry/backoff around Telegram `FloodWaitError`, temporary network drops, timeouts, and server disconnects.
  - [x] Add CLI options for `--max-retries`, `--retry-delay`, `--fail-fast`, and flood-wait retry behavior.
  - [x] Promote accelerated defaults across whole-channel and partial downloads: 32 media transfers, 5 retries, 3s retry delay, 15s summaries, and 75s stall watchdog.
  - [x] Add aggregate active transfer count, completed count, skipped count, duplicate count, and failed count to periodic logs.
  - [x] Add aggregate byte-rate and active-window ETA to periodic logs.
  - [x] Write a checksum manifest for completed media files.
  - [x] Add an interrupted-transfer cleanup policy for partial files.
  - [x] Reduce transfer watchdog polling to 250 ms so completed small files do not incur a five-second delay.
  - [x] Support separate partial-download suffixes to distinguish completed files from in-progress replacements.
  - [x] Add a final summary file with entity, started/finished timestamps, totals, failures, and resume guidance.
  - [x] Add deterministic tests for retries, interrupted partial cleanup, dedupe, resume, existing files, and concurrent transfer behavior.
  - [x] Add deterministic tests for Telegram flood-wait retry timing without sleeping the real wait duration.

  ### CLI UX Polish

  - [ ] Finish modern Click coverage for all major legacy operations.
  - [x] Keep current modern command groups lazy-loaded so help commands do not initialize Telegram, QIHSE, analytics, NumExpr, GUI, or server modules.
  - [x] Remove remaining noisy imports from legacy compatibility help paths.
  - [x] Standardize current modern global options: `--config`, `--db`, `--output`, `--quiet`, `--verbose`, `--no-color`, `--non-interactive`, `--yes`, `--dry-run`, and `--timeout`.
  - [x] Add local `--output` overrides for common status/config inspection commands where operators naturally place output options after the subcommand.
  - [x] Add detached `--detach` support for channel downloads with generated log path and dry-run argv preview.
  - [x] Add local JSONL detached task registry plus `task list` and `task show`.
  - [x] Add restart recovery for SQLite-backed task registry, task watch, and task cancel.
  - [x] Increase task watch tail polling frequency to 1s by default.
  - [x] Standardize exit codes and structured error envelopes for the local modern CLI runner.
  - [ ] Standardize exit codes and structured error envelopes across detached task runner, REST, GraphQL, and WebSocket events.
  - [x] Add shell completion generation and install docs.
  - [x] Add `spectra help <topic>` offline help for channel download and common error codes.
  - [x] Add `spectra help <topic>` offline help pages for discovery, forwarding, exports, and recovery.

  ### Operation Coverage

  - [x] Configuration operations: `path`, `show`, `get`, `validate`, `set-forward-dest`, and `view-forward-dest`.
  - [x] Configuration operations: profile management and environment-reference migration.
  - [x] Account operations: `list`, `show`, `test`, `reset-usage`, and `import`.
  - [x] Account operations: `add`, `logout`, `remove`, and `stats`.
  - [x] Auth operations: session health checks and redacted config display.
  - [x] Channel operations: `download` and local export `status`.
  - [x] Channel operations: `archive`, `members`, `add`, and `remove`.
  - [x] Task operations: local `list` and `show` for detached jobs.
  - [x] Task operations: restart recovery and persisted event streams.
  - [x] Discovery/network operations: `discover run/status/results`, `network analyze/export`, and persisted crawl summaries.
  - [x] Forwarding operations: `dialogs`, `recover`, `traverse`, `status`, `schedule`, and service-level `dry-run`.
  - [x] Mirror and migration operations: `mirror run/status`, `migration run/status/report/rollback`.
  - [x] Scheduling and file operations: `scheduler job show` and persisted scheduler status.
  - [x] Search, intelligence, ML, crypto, admin, server, and GraphQL operation groups. Local read-only/search/status backends are wired; optional semantic, ML training, advanced analysis, GraphQL, and crypto dependencies return explicit unavailable capability errors when absent.

  ### Backend Completion And Remote Parity

  - [ ] Move business logic out of Flask routes and CLI handlers into shared validated services.
  - [x] Introduce the initial dependency-light CLI operation registry with Pydantic v2 schemas and local executors for `version`, `doctor`, `config.get`, `task.show`, and `channel.status`.
  - [x] Add the first common operation envelope with `operation_id`, status, result, warnings, events, structured error, timestamps, dry-run propagation, and idempotency key fields.
  - [x] Register a typed `channel.download` schema for planning, generated examples, and future agent execution.
  - [x] Add deterministic `agent plan`, allowlisted local `agent run`, and redacted request-to-argv audit records with `agent audit list/show`.
  - [x] Adapt the CNScan cloud-training framework pattern into `training/spectra_operator/` with registry-derived dataset generation, Qwen LoRA training script, GPU requirements, and cloud runner model config.
  - [ ] Introduce the operation registry shared by CLI, REST, GraphQL, task execution, authorization, and generated docs.
  - [ ] Define Pydantic v2 request/result models with a common operation envelope.
  - [ ] Provide `LocalExecutor` and authenticated `RemoteExecutor` adapters.
  - [ ] Promote the operation audit sidecar into versioned SQLite migrations with persistent operation events, cancellation, idempotency, authorization decisions, exports, users, refresh tokens, saved searches, and channel catalog data.
  - [x] Add the shared SQLite connection policy with WAL, 60-second busy timeouts, foreign keys, and short-transaction callers.
  - [x] Add the committed `index_outbox` and `index_projection_state` schema/API for downloader, crawler, task, audit, and message metadata projections.
  - [x] Keep schema initialization outside per-record hot paths; downloader and worker loops reuse initialized outbox/projection connections.
  - [x] Serialize projection writes into one batch transaction with per-event savepoints and acknowledge the batch in one follow-up transaction.
  - [x] Add versioned, rebuildable KEYSTONE sorted-ID projection records with native sampled verification.
  - [x] Add a persistent QIHSE content-vector projection with idempotent external-ID upserts and semantic lookup.
  - [x] Add projection versions, source revisions, checksums, replay, drift detection, sampled equivalence checks against SQLite, and full rebuild commands.
  - [x] Add durable `fts.messages.v1` BM25 keyword search over allowlisted message fields.
  - [x] Add persistent `qihse.graph.v1` stable nodes and typed downloader/crawler relationships with native queries.
  - [x] Feed whole-channel, bounded partial, and failed-media retry downloads into the transactional index outbox selected by global `--db`.
  - [x] Add a privacy-reviewed operation-audit training corpus exporter with versioned redaction and deduplication.
  - [x] Add compound `(channel_id, message_id)` KEYSTONE keys and a typed `index lookup` operation/CLI.
  - [x] Add explicit byte offsets, byte lengths, and record checksums in `keystone.media_manifest.v1`.
  - [x] Add collision-checked `keystone.checkpoints.v1`, `keystone.events.v1`, `keystone.export_records.v1`, and `keystone.archive_members.v1` projections with typed native lookup.
  - [x] Add safe historical database backfill plus bounded ZIP/TAR member scanning without extraction.
  - [ ] Replace raw remote subprocess dispatch with allowlisted operation-registry execution and idempotency keys.
  - [ ] Complete synthetic export, admin, saved-search, channel mutation/statistics, account-correlation, analytics, GraphQL, operation cancellation, and system-health backends.

  ### Concurrent Storage And Lookup Architecture

  - [x] Decide SQLite remains the relational source of truth while QIHSE and KEYSTONE provide derived lookup projections.
  - [x] Document the separation between media transfer concurrency and relational write concurrency.
  - [x] Document the WAL/outbox boundary, serialized batch writer, replay, rebuild, and projection validation model in `docs/docs/api/indexing-architecture.md`.
  - [x] Implement and benchmark the WAL/busy-timeout writer boundary while a 32-transfer downloader and 100-message crawler run together; four crawler events projected with zero lock failures.
  - [x] Implement the outbox consumer and idempotent KEYSTONE/QIHSE projection updates.
  - [x] Add `spectra index status` as a typed operation and CLI surface.
  - [x] Add `spectra index rebuild` and `spectra index verify` operation/CLI surfaces.
  - [x] Add a supervised continuous index worker with drain, watch, 100 ms polling, bounded leases, and graceful interrupt summaries.
  - [x] Add exponential error backoff and packaged systemd service units for primary and task-sidecar index workers.
  - [x] Route the installed `spectra` entrypoint directly to the lazy modern CLI and retain `spectra-legacy`.
  - [x] Acknowledge outbox events only after QIHSE persistence, sync only the current batch, bound permanent retries at five attempts, and make verification drift exit `7`.
  - [x] Benchmark the synthetic workstation outbox path: 1,000 events from 16 writers in 0.902 seconds (1,108.2 events/second), 4.522-second projection drain, and successful native QIHSE/KEYSTONE verification.
  - [x] Repeat the 1,000-event benchmark with graph and FTS enabled: 0.757-second writes (1,321.0/second), 10.263-second five-projection drain, 1,051 graph nodes, 2,999 typed edges, and 3.793-second successful verification.
  - [x] Add typed `index backfill-export` and `index benchmark` operations covering active-manifest snapshots, concurrent writers, lookup latency, replay, lease recovery, and native verification.
  - [x] Benchmark lookup latency, replay time, crash recovery, and a simultaneous live downloader/crawler workload on the workstation.
  - [x] Bound persistent KEYSTONE child startup and lookup waits, restart once after failure, and reap unresponsive children.
  - [x] Replace per-event projection/acknowledgement commits with per-event savepoints inside two serialized batch transactions; 200-event drain improved from 3.398 seconds to 0.810 seconds.
  - [x] Bind acknowledgements to opaque claim tokens so expired workers cannot overwrite a reclaimed lease owner's result.
  - [x] Invalidate persistent KEYSTONE caches from projection state plus ordered-key checksums, including same-max-sequence rebuilds and deletions.
  - [x] Verify exact QIHSE source identity for duplicate-vector groups instead of accepting vector equality alone.
  - [x] Derive archive IDs from verified content snapshots and reject oversized ZIP directories before `ZipFile` parses them.
  - [x] Serialize native QIHSE vector and graph operations across processes with bounded advisory locks and crash-safe kernel release.
  - [x] Emit redacted watcher diagnostics and apply exponential backoff to raised errors and failed projection batches.
  - [x] Add a bounded, redacted SSH benchmark launcher with native QIHSE/KEYSTONE preflight for explicit L40S/H100 targets.
  - [ ] Repeat the indexing benchmarks on the separate L40S/H100 training hosts.

  ### Security And Secrets

  - [x] Define local server security posture as workstation trust by default: an operator who can run SPECTRA on this machine is trusted for local operations.
  - [x] Use salted PBKDF2-HMAC-SHA384 password hashes for hardened remote operators.
  - [x] Use HS384 access tokens, role checks, and authenticated WebSockets where hardened auth is enabled.
  - [x] Rotate refresh tokens non-destructively for hardened remote mode; earlier refresh tokens remain valid until JWT expiry.
  - [ ] Add an explicit persistent token store for server-side refresh-token revocation and audit.
  - [x] Add an optional hardened remote profile for operators who intentionally expose the API beyond the workstation.
  - [ ] Store refresh tokens and Telegram-sensitive values in the OS keyring where available.
  - [ ] Support environment references and existing inline config during migration.
  - [x] Scrub all hardcoded credentials from tracked files: `gen_config.py` and 17 other docs/script files had plaintext phone numbers, API IDs, API hashes, and proxy credentials replaced with `[REDACTED]` placeholders (commit `dee05e9`).
  - [x] Rewrite git history with `git-filter-repo` to purge 25 secret patterns across all 309 commits; post-rewrite verification confirmed zero remaining occurrences.
  - [ ] Refuse accidental overwrite of private crypto outputs without `--force`.

  ### Documentation

  - [x] Add CLI infrastructure documentation covering the current command tree, routing, persistence, security posture, channel downloads, task registry, and validation.
  - [ ] Rewrite the Docusaurus manual around installation, first-run setup, Telegram authentication, local and remote profiles, command groups, configuration, environment variables, output schemas, exit codes, recipes, recovery workflows, security, troubleshooting, and v1 migration.
  - [ ] Generate CLI reference and compatibility tables from the operation registry.
  - [ ] Reduce README to accurate quick start, common workflows, capability matrix, and links into the manual.
  - [ ] Replace roadmap-style or exaggerated claims with verified behavior.
  - [x] Add operator docs for channel downloads that explain resume, dedupe, concurrency, partial files, log interpretation, and recovery without requiring source inspection or an LLM.
  - [x] Rewrite systemd deployment guide (`docs/docs/deployment/systemd.md`) to document all five service units with system and user installation paths, installer flag reference, key behaviours, and management commands (commit `179425b`).
  - [x] Build Docusaurus with broken links treated as errors: exit 0, zero broken links, zero broken anchors (verified 2026-07-29).

  ### Verification And Release

  - [x] Add parser/help tests for current modern command groups, including detach dry-run behavior.
  - [x] Add parser/help tests for every final modern command group.
  - [x] Add focused parser/help/status tests for current modern CLI groups.
  - [ ] Add command-to-operation parity tests and local/remote contract tests.
  - [x] Add focused structured-output tests for JSON and CSV on current modern commands.
  - [x] Run the complete primary repository test suite without native shutdown faults: 247 passed and 9 optional async/service tests skipped.
  - [x] Add regression coverage for active detached-log discovery in `channel status`.
  - [ ] Add structured-output tests for table, JSONL, YAML, and quiet/error modes.
  - [ ] Add deprecated-alias tests that verify warnings stay on stderr and JSON stdout stays clean.
  - [ ] Add documentation-generation drift checks.
  - [ ] Add integration coverage using temporary databases for migrations, persistent tasks, cancellation, exports, admin CRUD, authentication, search, analytics, and server restart recovery.
  - [ ] Add security tests for redaction, missing server secrets, authorization, role enforcement, WebSocket authentication, path traversal, file permissions, token rotation, and prohibited raw command execution.
  - [ ] Build/install the wheel in a clean environment.
  - [ ] Run every `--help` path and ensure no help command emits startup noise.
  - [x] Build Docusaurus with broken links treated as errors: exit 0, verified 2026-07-29.
  - [ ] Execute documented examples in CI.
  - [ ] Release as `2.0.0`, unify version declarations, preserve v1 aliases for the v2 line, and document v3 alias removal.

  ## Architecture And Contracts

  - Replace the monolithic argparse entrypoint with lazy-loaded Click command groups and Rich terminal rendering. spectra --help must exit cleanly without loading
    Telegram, QIHSE, analytics, or GUI modules.

  - Introduce a single operation registry shared by CLI, REST, GraphQL, task execution, authorization, and generated documentation.
  - Define Pydantic v2 request/result models with a common envelope: operation ID, status, progress, result, warnings, timestamps, and structured error.
  - Provide interchangeable LocalExecutor and RemoteExecutor adapters. Local execution is default; --remote PROFILE or --api-url selects the authenticated API.
  - Standardize global options: --config, --db, --output table|json|jsonl|yaml|csv, --quiet, --verbose, --no-color, --non-interactive, --yes, --dry-run, --timeout,
    and --detach.

  - Reserve exit codes: 0 success, 2 usage, 3 config/auth, 4 not found, 5 conflict, 6 network/Telegram, 7 partial completion, 8 unavailable capability, and 130
    interruption.

  - Persist operations, events, cancellation state, exports, audit records, users, refresh tokens, saved searches, and channel catalog data in versioned SQLite
    migrations. Detached work must survive server restarts.

  ## Command Surface

  - System: init, doctor, version, completion, server run|health, task list|show|watch|cancel, events watch.
  - Configuration: config path|show|get|set|unset|validate|migrate; profile list|show|add|use|remove|login|logout.
  - Telegram accounts: account list|show|add|login|logout|remove|test|stats|reset-usage|import. account login provides the built-in code and hidden 2FA flow used
    successfully in this checkout.

  - Collection: archive channel|batch|status, download channel|members, channel list|show|add|remove|stats|access-refresh.
  - Discovery and movement: discover run|status|results, network analyze, forward messages|dialogs|recover|traverse|status|schedule, mirror run|status, migration
    run|status|report|rollback.

  - Scheduling and files: scheduler job add|list|show|remove|run, scheduler daemon, files sort|watch.
  - OSINT and data: osint target add|remove|list, osint scan|network; db stats|channels|messages|users|media|migrate.
  - Search and exports: search fulltext|semantic|hybrid|correlations|cluster|anomalies|threat-score|saved|config|stats; export create|list|status|download|cancel|
    templates.

  - Intelligence: analyze attribution|account-correlation|temporal|predict-activity|network|score|indicators|visualize|forecast|time-series|predictive.
  - ML: ml patterns|correlate|entities|semantic-search, ml model list|train.
  - Security and administration: crypto kem, crypto signature, crypto encrypt|decrypt|algorithms; admin user, admin logs|health|config|operations|stats; api
    graphql.

  - Preserve current forms such as download-channel, accounts --list, migrate-report, and rollback as aliases that print a migration warning to stderr without
    contaminating JSON stdout. Remove aliases in v3.

  ## Backend Completion And Security

  - Move business logic out of Flask routes and CLI handlers into validated services; both transports must return equivalent result models.
  - Complete the currently synthetic export, admin, channel mutation/statistics, saved-search, account-correlation, analytics, GraphQL, operation cancellation, and
    system-health implementations.

  - Repair mismatched analytics/ML imports and method contracts, validate model inputs, and return capability errors instead of empty or fabricated success.
  - Replace the arbitrary remote CLI subprocess endpoint with allowlisted operation-registry dispatch and idempotency keys.
  - Keep local workstation mode auth-light by default. Add a separate hardened remote profile with salted PBKDF2-HMAC-SHA384 password hashes, HS384 access tokens,
    rotating refresh tokens, role checks, authenticated WebSockets, and explicit network exposure settings.

  - Store remote refresh tokens and Telegram-sensitive values in the OS keyring where available; support environment references and existing inline config during
    migration. Never print API hashes, passwords, session material, private keys, or tokens.

  - Resolve configuration in this order: explicit flag, process environment, selected .env, existing project config, XDG user config, validated defaults. Default
    accounts must be empty rather than containing sample credentials.

  - Write private crypto outputs to owner-only files or stdout only when explicitly requested; refuse accidental overwrite without --force.
  - Add *.session and *.session-journal secret hygiene while preserving the current authorized session locally and never committing it.
  - Package optional capability sets as spectra[server], spectra[analysis], spectra[crypto], and spectra[full]; doctor --capabilities reports exact missing
    dependencies and remediation.

  ## UX And Documentation

  - Prompt only when stdin is a terminal and required input is missing. --non-interactive must fail immediately with an actionable message.
  - Keep logs on stderr and machine output on stdout. Add progress bars, pagination, resumable transfers, retry/flood-wait reporting, consistent entity/date
    selectors, destructive confirmations, and bulk-operation summaries.

  - Generate the CLI reference and compatibility table from the operation registry so help, REST metadata, and documentation cannot drift.
  - Rewrite the Docusaurus documentation around installation, first-run setup, Telegram authentication, local/remote profiles, every command group, configuration
    and environment variables, output schemas, exit codes, recipes, recovery workflows, security, troubleshooting, and migration from v1.

  - Replace exaggerated or roadmap-style feature claims with verified behavior. Keep planning documents clearly separated from user documentation.
  - Reduce the README to an accurate quick start, common workflows, security warning, capability installation matrix, and links into the complete manual.
  - Ship shell completions and an offline spectra help <topic> index covering examples and common error recovery.

  ## Verification And Release

  - Initialize qlearn before implementation, then refresh it after each major subsystem and at completion.
  - Add parser/help tests, command-to-operation parity tests, local/remote contract tests, structured-output tests, deprecated-alias tests, and documentation-
    generation drift checks.

  - Add integration coverage using temporary databases for migrations, persistent tasks, cancellation, exports in JSON/CSV/XLSX/PDF, admin CRUD, authentication,
    search, analytics, and server restart recovery.

  - Test Telegram operations through deterministic client doubles; retain an opt-in live smoke suite that never alters channels or consumes the configured account
    without an explicit flag.

  - Add security tests for secret redaction, missing server secrets, authorization and role enforcement, WebSocket authentication, path traversal, file permissions,
    token rotation, and prohibited raw command execution.

  - Build and install the wheel in a clean environment, run every --help path, build Docusaurus with broken links treated as errors, and execute documented examples
    in CI.

  - Release as 2.0.0, unify all conflicting version declarations, preserve v1 aliases through the entire v2 line, and document their v3 removal.
  - Before edits, snapshot the dirty worktree and preserve the existing channel downloader, README changes, .env, config, and authorized session. No runtime secret
    or session file enters a commit.

  ## Acceptance Criteria

  - Every advertised REST, GraphQL, WebSocket, service, Telegram, analytics, export, security, and administration operation has a real backend, CLI entry,
    authorization policy, help text, example, and test.

  - Local and remote execution produce the same structured results and error categories.
  - A new user can install, initialize, authenticate a Telegram account, download a channel, inspect progress, export data, and troubleshoot failures using only
    shipped CLI help and documentation.

  - No command reports synthetic success, no help command emits startup noise, and no secret appears in logs or default output.
