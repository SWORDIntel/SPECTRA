---
id: cli-infrastructure
title: CLI Infrastructure
sidebar_position: 2
description: Architecture and operational model of the SPECTRA command-line interface
tags: [api, cli, architecture, operations]
---

# CLI Infrastructure

This document describes the current SPECTRA CLI infrastructure as implemented in the repository. It is intended for operators and maintainers who need to understand how commands route, what they persist, which commands are local-only, and where optional Telegram/API backends are invoked.

For the implemented concurrent storage and lookup design, see [Lookup And Indexing Architecture](./indexing-architecture.md).

For command examples, see the [CLI Reference](./cli-reference.md). This page documents the structure behind that interface.

## Executables And Entry Points

SPECTRA currently has a modern Click CLI and a compatibility argparse runtime.

Primary entry points:

- `spectra ...`
- `python -m tgarchive ...`
- `python -m tgarchive --output json ...`

Implementation entry points:

- `tgarchive/cli/app.py` contains the modern Click command tree, output handling, task registry, local database inspection, and most new command groups.
- `tgarchive/__main__.py` contains the compatibility runtime and legacy Telegram-backed handlers.
- `tgarchive/__main__.py` decides whether a request should use the modern Click tree or legacy argparse tree before importing heavy Telegram/analytics modules.

The modern path is intentionally lazy. Help, version, config inspection, local status, and most database checks must not initialize Telegram, QIHSE, NumExpr, GUI, Flask, GraphQL, or crypto stacks.

## Global Options

Global options are parsed before the command:

```bash
spectra --config spectra_config.json --db spectra.db --output json account list
```

Global options:

| Option | Purpose |
| --- | --- |
| `--config PATH` | Active SPECTRA JSON config path. Default: `spectra_config.json`. |
| `--db PATH` | Active SQLite database path. Default: `spectra.db`. |
| `--output table|json|jsonl|csv` | Result format. Default: `table`. |
| `--quiet` | Suppress non-result status output where supported. |
| `--verbose` | Emit additional diagnostics where supported. |
| `--no-color` | Disable terminal color. |
| `--non-interactive` | Never prompt. Missing required interactive input fails. |
| `--yes` | Confirm guarded mutations in non-interactive mode. |
| `--dry-run` | Validate or preview work without making changes where supported. |
| `--timeout SECONDS` | Reserved for timeout-capable operations. |
| `--detach` | Start long-running supported operations in the background. |

Some command-level `--output` overrides are also supported for common status/config commands where operators naturally place output options after the subcommand.

## Output Contracts

The modern CLI keeps results on stdout. Logs and operational progress go to stderr or task log files.

Output formats:

- `table`: human-readable key/value or line output.
- `json`: pretty JSON object or list.
- `jsonl`: one JSON object per line.
- `csv`: CSV with stable field names derived from the result rows.

Machine-readable errors use a reserved envelope when `--output json` is active:

```json
{
  "error": {
    "code": 4,
    "category": "not_found",
    "message": "Error: Database not found: spectra.db"
  }
}
```

Exit codes:

| Code | Category |
| --- | --- |
| `0` | Success |
| `2` | Usage error |
| `3` | Configuration, auth, account, or credential issue |
| `4` | Not found |
| `5` | Conflict or overwrite refusal |
| `6` | Telegram, network, flood wait, or timeout failure |
| `7` | Partial completion |
| `8` | Unavailable optional capability |
| `130` | Interrupted |

`tgarchive.cli.app.run()` maps Click errors into those reserved categories and preserves integer return values from Click callbacks.

## Secret Handling

CLI output redacts sensitive values by key name. Redacted keys include:

- `api_hash`
- `password`
- `token`
- `secret`
- `jwt_secret`
- `session_secret`
- `bootstrap_secret`
- `private_key`
- `refresh_token`

Config inspection, account inspection, task output, and migration helpers all pass through redaction before emitting machine output. Commands that intentionally generate a persistent hash, such as `admin operator hash-password`, print the hash because that is the operator artifact to store; they never print the raw password.

## Config Model

Configuration is JSON-backed through `tgarchive/core/config_models.py`.

Key behavior:

- Missing configs are created with defaults.
- Inline `env:NAME` references are resolved at load time.
- `config migrate-env` can move inline sensitive values to environment references.
- Named config profiles live inside the active config under `profiles`.
- Secret paths are redacted in output.

Important commands:

```bash
spectra config path
spectra config show --output json
spectra config get accounts.0.session_name --output json
spectra config set forwarding.mode media-only --raw
spectra config unset forwarding.mode
spectra config validate
spectra --yes config migrate-env --prefix SPECTRA --env-file .env.spectra
spectra config profile list
spectra --yes config profile add lab
spectra --yes config profile use lab
```

Guardrails:

- Config mutations require `--yes` in `--non-interactive` mode.
- Writes are atomic through a temporary file and rename.
- JSON values are parsed by default; use `--raw` for literal strings.

## Command Routing Model

The command router in `tgarchive/__main__.py` classifies modern requests before importing the legacy runtime.

Modern command groups include:

- `account`
- `admin`
- `analyze`
- `api`
- `archive`
- `channel`
- `completion`
- `config`
- `crypto`
- `db`
- `discover`
- `doctor`
- `export`
- `files`
- `forward`
- `migration`
- `mirror`
- `ml`
- `network`
- `operations`
- `osint`
- `scheduler`
- `search`
- `server`
- `task`
- `version`

Compatibility aliases still exist for legacy top-level commands such as `download-channel`, `accounts --list`, `migrate-report`, and `rollback`. New work should use the grouped modern form.

## Command Inventory

Current visible modern command tree:

```text
account
  add
  health
  import
  list
  login
  logout
  remove
  reset-usage
  show
  stats
  test
admin
  config
  health
  logs
  operations
  operator
    add
    hash-password
  stats
analyze
  account-correlation
  attribution
  forecast
  indicators
  network
  score
  temporal
api
  graphql
archive
  channel
channel
  access-refresh
  add
  archive
  download
  inspect
  list
  members
  remove
  show
  stats
  status
completion
config
  get
  migrate-env
  path
  profile
    add
    list
    remove
    show
    use
  set
  set-forward-dest
  show
  unset
  validate
  view-forward-dest
crypto
  algorithms
  decrypt
  encrypt
  kem
  signature
db
  stats
  table
  tables
discover
  results
  run
  status
doctor
export
  table
files
  sort
  watch
forward
  dialogs
  messages
  recover
  schedule
  status
  traverse
help
migration
  report
  rollback
  run
  status
mirror
  run
  status
ml
  correlate
  entities
  model
    list
    train
  patterns
  semantic-search
network
  analyze
  export
  status
operations
  list
  run
  schema
  show
osint
  network
  scan
  target
    add
    list
    remove
scheduler
  add
  add-channel-forward
  add-file-forward
  daemon
  list
  remove
  report
  show
  status
search
  fulltext
  hybrid
  saved
  semantic
  stats
server
  health
  run
task
  cancel
  events
  list
  recover
  show
  watch
version
```

## Local-Only Commands

These commands do not contact Telegram or remote services:

- `version`
- `doctor`
- `completion`
- `help`
- `config path/show/get/set/unset/validate/profile/migrate-env`
- `account list/show/add/logout/remove/stats/health`
- `admin health/config/stats/operations/logs`
- `admin operator hash-password/add`
- `db stats/tables/table`
- `export table`
- `task list/show/events/watch/recover/cancel`
- `channel add/remove/list/show/stats/inspect/status`
- `discover status/results`
- `network status/export`
- `forward status`
- `scheduler status/show`
- `migration status`
- `mirror status`
- `search fulltext/stats/saved`
- `analyze indicators/temporal`
- `ml patterns`, `ml model list`
- `server health`
- `api graphql`

Some of these read local SQLite databases or task registries. They still fail if the selected files are missing or malformed.

## Telegram-Backed Commands

These route to existing production Telegram workflows and may require authorized sessions, account access, and network availability:

- `account login`
- `account test`
- `account reset-usage`
- `account import`
- `archive channel`
- `channel archive`
- `channel download`
- `channel members`
- `channel access-refresh`
- `discover run`
- `network analyze`
- `forward messages/dialogs/recover/traverse`
- `scheduler add/list/remove/daemon/add-channel-forward/add-file-forward/report`
- `files sort/watch`
- `osint scan/network`
- `migration run/report/rollback`
- `mirror run`

Use global `--dry-run` where supported before bulk operations.

## Capability-Gated Commands

Optional dependencies are not imported on normal CLI startup.

Commands that can return exit code `8` include:

- `search semantic`
- `search hybrid`
- advanced `analyze` commands such as `attribution`, `network`, `score`, and `forecast`
- `ml correlate`, `ml entities`, `ml semantic-search`, `ml model train`
- `crypto algorithms/kem/signature/encrypt/decrypt` when the CNSA crypto stack is unavailable
- `api graphql` when GraphQL dependencies are unavailable
- `server health` when Flask itself is unavailable

`server health` uses spec-based capability checks so it does not import noisy optional modules just to report availability.

## Detached Task Registry

Long-running detached operations are tracked in a SQLite registry beside the selected database path.

Default registry:

```text
spectra.tasks.sqlite3
```

Task registry behavior:

- `channel download` with `--detach` starts a child process in a new process group.
- The CLI writes a `task_events` record containing task ID, PID, command, log path, output directory, and status.
- Older `.tasks.jsonl` records are imported automatically.
- `task show` enriches task records with current process state and channel export status when possible.
- `task events` returns all persisted task records for one task ID.
- `task watch` polls once per second by default.
- `task cancel` sends SIGINT to the recorded process group and appends a cancellation event.
- `task recover` appends inferred `completed` or `exited` records for stale `running` tasks.

Useful commands:

```bash
spectra --detach --output json channel download @target --output-dir channel_downloads --media-only
spectra task list --output json
spectra task show task-20260728T205258Z --output json
spectra task events task-20260728T205258Z --output json
spectra task watch task-20260728T205258Z --tail 20
spectra task recover task-20260728T205258Z --output json
spectra --yes task cancel task-20260728T205258Z
```

## Operation Registry

The first operation-registry slice lives under `tgarchive/operations/`.

It provides:

- dependency-light operation metadata
- Pydantic v2 request/result schemas
- a common operation envelope for `operations run`
- local executors for the implemented command families, including channel, discovery, search, export, and index operations
- complete local index executors backed by the durable outbox and rebuildable projections
- a typed `channel.download` schema for planning, generated examples, and future agent execution

Operator-facing commands:

```bash
spectra operations list --output json
spectra operations show channel.download --schema --output json
spectra operations schema channel.status --output json
spectra operations run version --output json
spectra operations run config.get --arguments '{"path":"accounts.0.session_name"}' --output json
spectra index status --output json
spectra index process --batch-size 1000 --output json
spectra index drain --batch-size 1000 --output json
spectra index watch --batch-size 1000 --poll-interval 0.1
spectra index rebuild --projection all --output json
spectra index verify --projection all --native --sample-size 32 --output json
spectra index lookup --channel-id -1002407846598 --message-id 12 --output json
spectra index checkpoint CHECKPOINT_ID --output json
spectra index event task EVENT_ID --output json
spectra index event operation EVENT_ID --output json
spectra index event audit EVENT_ID --output json
spectra index export-record EXPORT_ID RECORD_ORDINAL --output json
spectra index archive-member ARCHIVE_ID MEMBER_INDEX --output json
spectra index graph --node-type message --external-id=-1002407846598:12 --direction outgoing --output json
spectra index backfill-export /fast/ULPs/Channel_123 --output json
spectra index backfill-database --output json
spectra index scan-archive /fast/ULPs/archive.zip --limit 10000 --output json
spectra index benchmark --events 1000 --writers 16 --lookups 10 --output json
spectra operations run index.status --output json
```

The registry is the intended control surface for a SPECTRA operator model: natural language is translated into operation JSON, SPECTRA validates it against the request schema, and only allowlisted executors run.

Agent and operation audit records are stored in the selected task-registry sidecar database. `spectra agent audit list` and `spectra agent audit show AUDIT_ID` expose redacted records linking the source request, validated envelope, planned command, actual argv, lifecycle status, result, and error. Planning failures and unavailable operations are recorded as well, so an operator request does not disappear merely because execution was refused.

The registry includes typed planning surfaces for discovery/crawling (`discovery.run`), network analysis (`network.analyze`), local full-text search (`search.fulltext`), channel archiving (`channel.archive`), and table exports (`export.table`). This keeps natural-language corpus generation aligned with the existing CLI commands and their argument schemas.

`index status` reports pending, claimed, processed, and failed outbox events plus projection checkpoints. `index process` claims one bounded batch with an opaque ownership token and writes nine idempotent KEYSTONE, QIHSE, graph, and SQLite FTS5 projections through per-event savepoints in one transaction, then acknowledges the batch in one follow-up transaction. It acknowledges events only after native persistence confirms success and while its lease token still matches, syncs only the current batch, and stops retrying a permanent failure after five attempts. QIHSE vector and graph files have separate bounded cross-process locks for sync, query, rebuild, and verification. `index drain` runs batches until empty. `index watch` is the supervised long-running worker and polls every 100 ms by default; exceptions and failed batches produce redacted JSON diagnostics on stderr and use capped exponential backoff. `index rebuild` replays the committed outbox and recreates persistent native stores; `index verify` compares row counts, key maps, checksums, and exact sampled QIHSE identities before running crash-isolated native lookup samples and exits `7` on disagreement.

`index lookup` resolves channel-scoped Telegram records. For non-message records, prefer the identity-specific commands: `index checkpoint CHECKPOINT_ID`, `index event KIND EVENT_ID`, `index export-record EXPORT_ID RECORD_ORDINAL`, and `index archive-member ARCHIVE_ID MEMBER_INDEX`. Event kinds are `task`, `operation`, and `audit`; export ordinals and archive member indexes are zero-based. Each command routes through the reusable crash-isolated native KEYSTONE lookup child with bounded startup and response waits.

`index lookup-record PROJECTION NAMESPACE EXTERNAL_ID` remains the lower-level form for generic tooling and stored projection metadata. For example, `index event task 42` maps to `index lookup-record events task_events 42`. `index graph` queries stable typed QIHSE relationships. `index backfill-export` snapshots an existing media manifest without consuming an incomplete trailing record, `index backfill-database` safely imports historical checkpoint/event identities, and `index scan-archive` reads bounded ZIP/TAR metadata without extraction. `index benchmark` exercises concurrent writers, projection drain, lookup latency, replay, expired-lease recovery, and final verification.

Messages, channel-download records, checkpoints, operation events, task events, and audit events emit outbox rows in the same short SQLite transaction as their authoritative write. Task and agent-audit records live in the task sidecar, so inspect or process them by selecting it explicitly:

```bash
spectra --db spectra.tasks.sqlite3 index status --output json
spectra --db spectra.tasks.sqlite3 index process --batch-size 1000 --output json
```

## Channel Download Pipeline

`channel download` is the main filesystem export path.

It writes:

- `messages.jsonl` unless `--media-only` is used
- `media/`
- `media_manifest.jsonl`
- `manifest.json`
- `state.json`
- `download.log`
- `summary.json` on completion

Downloader properties:

- concurrent media worker pool
- default `--max-connections 32`
- retry and flood-wait handling
- stall watchdog
- 250 ms transfer-completion and stall polling
- `.part` files for in-progress transfers
- atomic move into final filenames
- existing-file checks before transfer
- SHA-256 manifest entries where available
- resume through `state.json`
- range support with `--limit`, `--min-id`, and `--max-id`
- negative Telegram entity IDs require `--` before the entity when passed positionally

Status inspection:

```bash
spectra channel status /path/to/export --output json --tail 20
```

This status command does not connect to Telegram.

## Database And Export Layer

SQLite access is intentionally schema-aware:

- table names are validated against SQLite metadata
- identifiers are quoted
- missing tables return clear errors
- reads use row dictionaries
- exports support CSV, JSON, and JSONL

Core local commands:

```bash
spectra db stats --output json
spectra db tables --output json
spectra db table messages --limit 100 --output json
spectra export table messages --output-file exports/messages.csv --format csv
```

## Search And Analysis Layer

`search fulltext` performs local case-insensitive SQLite text search across whichever message text columns exist:

- `content`
- `message`
- `raw_text`
- `text`
- `caption`

`search stats` reports message table availability, searchable columns, saved-search count, and optional search backend availability.

`analyze indicators` runs the local threat indicator detector over matching or recent message text.

`analyze temporal` summarizes message counts by hour from local message timestamps.

Semantic/hybrid search and advanced analysis commands intentionally return unavailable capability errors until their initialized backends are wired for the local CLI.

## Scheduler, Forwarding, Migration, And Mirror

The CLI exposes both local inspection and Telegram-backed execution.

Local inspection:

```bash
spectra forward status --output json
spectra scheduler status --output json
spectra scheduler show nightly --output json
spectra migration status --output json
spectra mirror status --output json
```

Telegram/service-backed operations:

```bash
spectra forward messages --origin @source --destination @dest
spectra forward dialogs --destination @dest
spectra forward recover --destination @dest
spectra forward traverse --channels-file seeds.txt --output-dir traversal_out
spectra scheduler daemon
spectra migration run --source @source --destination @dest
spectra mirror run --source @source --destination @dest --source-account src --destination-account dst
```

Forwarding supports `--dry-run` to emit a structured plan without importing the legacy forwarding runtime.

## Server And API Posture

Local server mode uses workstation trust by default.

Meaning:

- if an operator can run SPECTRA on this workstation, they are trusted for local operations
- local API auth decorators attach a synthetic `local-operator` admin identity
- no JWT secret is required for local workstation mode
- `/health` and `server health` report `security_posture: workstation_trust`

Remote exposure is opt-in.

Remote mode requires:

- `SPECTRA_SECURITY_POSTURE=remote`
- non-default `SPECTRA_JWT_SECRET`
- configured operators with PBKDF2-HMAC-SHA384 password hashes

Operator onboarding:

```bash
export SPECTRA_OPERATOR_PASSWORD='long-unique-password'
spectra --non-interactive --output json admin operator hash-password --username alice --password-env SPECTRA_OPERATOR_PASSWORD
spectra --non-interactive --yes admin operator add --username alice --password-env SPECTRA_OPERATOR_PASSWORD --permission manage_users
```

Onboarding guardrails:

- passwords must be at least 14 characters
- passwords must contain lowercase, uppercase, digit, and symbol characters
- raw passwords are never emitted
- `admin operator add` requires `--yes` in `--non-interactive` mode

Token behavior:

- access tokens use HS384
- refresh tokens include roles, permissions, and `jti`
- refresh-token rotation is non-destructive
- a successful refresh returns a new access token and a new refresh token
- older refresh tokens remain valid until their JWT expiry unless a future persistent token store explicitly revokes them

Optional heavy API route groups are not initialized by default in workstation mode. The web launcher supports:

- `SPECTRA_LOAD_OPTIONAL_ROUTES=1`
- `SPECTRA_LOAD_GRAPHQL=1`
- `SPECTRA_LOAD_CLI_API=1`

Only enable those when the matching optional dependencies are installed.

## Crypto Commands

Crypto commands call the CNSA 2.0 crypto service when available:

```bash
spectra crypto algorithms --output json
spectra crypto kem --key-id lab --output-file secrets/kem.json
spectra crypto signature --key-id signer --output-file secrets/signing.json
spectra crypto encrypt --input-file sample.bin --recipient-public-key "$PUBLIC_KEY" --output-file sample.enc.json
spectra crypto decrypt --package-file sample.enc.json --recipient-secret-key "$SECRET_KEY" --output-file sample.bin
```

File safety:

- private key and plaintext outputs are written with owner-only permissions
- existing outputs are not overwritten unless `--force` is supplied
- missing crypto dependencies return unavailable capability errors instead of synthetic success

## Shell Completion

Completion scripts are generated by Click:

```bash
spectra completion bash
spectra completion zsh
spectra completion fish
```

Install mode writes to standard user completion paths. It refuses overwrite unless `--force` is supplied and requires `--yes` in `--non-interactive` mode.

## Validation And Tests

Focused coverage currently includes:

- modern CLI startup without heavy runtime logging
- JSON and CSV output modes
- structured error mapping
- config redaction and mutation
- account CRUD and login dry-run paths
- task registry list/show/events/watch/cancel/recover
- channel downloader resume, dedupe, media-only, concurrent transfer behavior
- discovery/network local inspection
- forwarding dry-run and status
- search, analysis, ML, crypto, admin, server, and API command behavior
- workstation-trust and hardened remote auth behavior
- non-destructive refresh-token rotation
- remote operator onboarding strength checks

Common verification commands:

```bash
PYTHONPATH=. pytest -q tgarchive/api/tests/test_rest_api.py tgarchive/tests/test_cli_app.py tgarchive/tests/test_channel_downloader.py
python -m py_compile tgarchive/cli/app.py tgarchive/__main__.py
git diff --check
```

## Current Known Gaps

These are explicitly not complete yet:

- expanding the initial CLI operation registry across REST, GraphQL, task execution, authorization, and generated docs
- local/remote executor parity
- operation envelopes for detached task runner, REST, GraphQL, and WebSocket events
- persistent refresh-token revocation and audit store
- full remote operation idempotency
- generated CLI reference from the future operation registry
- full optional route contract coverage
- OS keyring storage for Telegram-sensitive values and remote refresh tokens

The CLI should return explicit unavailable capability errors for unimplemented or unconfigured features rather than reporting synthetic success.
