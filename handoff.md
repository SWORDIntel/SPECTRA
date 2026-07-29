# SPECTRA Handoff

Date: 2026-07-29
Workspace: `/fast/SPECTRA`
Purpose: operator-ready handoff for the SPECTRA CLI, Telegram collection pipeline, security posture, and off-host operator-model training work.

## Current Position

SPECTRA is in an active v2 modernization pass. The modern Click CLI is the primary interface for new work, while the older argparse runtime remains available for compatibility. The CLI now exposes grouped commands, structured output, reserved exit codes, local task persistence, resumable accelerated channel downloads, typed operation definitions, and a deterministic natural-language planner.

The latest implemented features are:

```bash
spectra agent plan "download all media from -1002407846598 to /fast/ULPs" --output json
```

This produces a validated `channel.download` operation envelope with `dry_run: true`. It does not execute the download and does not contact Telegram. The planner is deliberately deterministic and constrained to registered operations. `agent run` can execute only registered operations with local handlers and records the complete redacted request-to-operation audit trail.

## Entry Points

Use either installed `spectra` or the repository form:

```bash
PYTHONPATH=. python -m tgarchive --help
PYTHONPATH=. python -m tgarchive --output json version
```

The installed `spectra` entrypoint routes directly to `tgarchive.cli.app:run`; `spectra-legacy` retains the argparse runtime. Repository `python -m tgarchive` routing also selects the modern command tree before importing heavy Telegram, analytics, GUI, or native dependencies. `tgarchive/operations/` contains the shared typed envelope and registry. `tgarchive/services/channel_downloader.py` contains the accelerated download implementation.

Global options must precede the command:

```text
--config PATH
--db PATH
--output table|json|jsonl|csv
--quiet
--verbose
--no-color
--non-interactive
--yes
--dry-run
--timeout SECONDS
--detach
```

Use JSON for automation. Results go to stdout; progress and diagnostics are intended for stderr or task log files.

## Main CLI Surface

Core and inspection:

```bash
spectra version
spectra doctor --capabilities
spectra help
spectra help channel-download
spectra completion bash
```

Configuration:

```bash
spectra config path
spectra config show --output json
spectra config get accounts.0.session_name --output json
spectra config set download_media false
spectra config unset forwarding.mode
spectra config validate
spectra --yes config migrate-env --prefix SPECTRA --env-file .env.spectra
spectra config profile list
```

Account and authorization:

```bash
spectra account list --output json
spectra account health --output json
spectra account show ACCOUNT --output json
spectra account test
spectra account login ACCOUNT
spectra --non-interactive account login ACCOUNT --code CODE
spectra account logout ACCOUNT
spectra --yes account remove ACCOUNT --delete-session
```

Credentials belong in local environment/config references. Never put API hashes, passwords, OTPs, session contents, or access tokens in shell history, task arguments, documentation, or commits. Telegram 2FA should use `--password-env NAME`.

Channel collection:

```bash
spectra channel download @target \\
  --output-dir /fast/ULPs \\
  --account ACCOUNT \\
  --media-only \\
  --no-proxy \\
  --max-connections 32 \\
  --max-retries 5 \\
  --retry-delay 3 \\
  --progress-interval 15 \\
  --stall-timeout 75
```

For a negative numeric Telegram ID, put `--` before the entity:

```bash
spectra channel download --output-dir /fast/ULPs --media-only -- -1002407846598
```

Partial collection uses the same pipeline:

```bash
spectra channel download @target --output-dir /fast/ULPs --limit 1000
spectra channel download @target --output-dir /fast/ULPs --min-id 1000 --max-id 2000
```

The transfer pool defaults to 32 concurrent media transfers. It checks existing files and manifest records before downloading, uses `.part` files during transfer, atomically promotes completed files, records checksums where available, retries failures, and keeps channel metadata ordering independent from media completion order. Transfer completion and stall state are polled every 250 ms. Raising concurrency is account- and host-dependent; it can increase flood waits, connection failures, or disk contention.

Local status and recovery:

```bash
spectra channel status /fast/ULPs/TheUnderground_-_Reborn_2407846598 --output json --tail 50
spectra task list --output json
spectra task show TASK_ID --output json
spectra task events TASK_ID --output json
spectra task watch TASK_ID --tail 30
spectra task recover --output json
```

The export directory normally contains `state.json`, `manifest.json`, `media_manifest.jsonl`, `download.log`, `media/`, and final `summary.json`. Media manifest records are byte-addressable through recorded offsets, lengths, and SHA-256 values. A rerun without `--restart` is the intended resume path. Use `channel retry-failed` to retry only recorded failed IDs.

Other grouped surfaces include `archive`, `forward`, `scheduler`, `files`, `db`, `export`, `discover`, `network`, `search`, `analyze`, `ml`, `crypto`, `admin`, `server`, `api`, `osint`, `migration`, and `mirror`. Use `spectra GROUP --help` and the [CLI Reference](docs/docs/api/cli-reference.md) for command-level options.

## Operation Registry

The registry is the contract boundary for automation and future operator models:

```bash
spectra operations list --output json
spectra operations show channel.download --schema --output json
spectra operations schema config.get --output json
spectra operations run version --output json
spectra operations run config.get \\
  --arguments '{"path":"accounts.0.session_name"}' --output json
```

Current registered operations:

| Operation | Execution | Purpose |
| --- | --- | --- |
| `version` | local | Runtime version |
| `doctor` | local | Configuration and capability health |
| `config.get` | local | Redacted dotted-path lookup |
| `task.show` | local | Task and export inspection |
| `channel.status` | local | Export inspection without Telegram |
| `channel.download` | schema/planning | Accelerated Telegram download request |
| `discovery.run` | schema/planning | Seed-based Telegram discovery/crawling |
| `network.analyze` | schema/planning | Crawler export or local database graph analysis |
| `search.fulltext` | schema/planning | Local full-text message search |
| `channel.archive` | schema/planning | Telegram channel archive request |
| `export.table` | schema/planning | Local table export request |
| `index.status` | local | Durable index outbox and projection checkpoint status |
| `index.process` | local | Claim and project a bounded outbox batch |
| `index.drain` | local | Drain committed outbox batches until empty |
| `index.rebuild` | local | Replay SQLite events into QIHSE/KEYSTONE projections |
| `index.verify` | local | Verify checksums and sampled native lookups |
| `index.lookup` | local | Resolve a channel-scoped message through KEYSTONE |
| `index.lookup-record` | local | Resolve checkpoint, event, export, or archive-member identities |
| `index.graph` | local | Query stable typed QIHSE relationship edges |
| `index.backfill-export` | local | Idempotently import a stable manifest snapshot into the outbox |
| `index.backfill-database` | local | Import safe pre-outbox checkpoint/event identities |
| `index.scan-archive` | local | Index bounded ZIP/TAR member metadata without extraction |
| `index.benchmark` | local | Exercise writes, projection drain, lookups, replay, lease recovery, and verification |

`operations run` returns a common envelope containing `operation_id`, `status`, `result`, `warnings`, `events`, `error`, timestamps, and an optional idempotency key. Operations without a local handler fail explicitly as unavailable; they do not report synthetic success.

Indexing status is available directly with `spectra index status --output json`. Process one batch with `index process`, drain all current work with `index drain`, or run `index watch` under a service manager. Rebuild with `spectra index rebuild --projection all`, and validate SQLite plus native engines with `spectra index verify --projection all --native`. SQLite remains authoritative. QIHSE persists `<database>.qihse.qdb` and `<database>.graph.qdb`; SQLite FTS5 provides BM25 keyword search; KEYSTONE accelerates message, media-manifest, checkpoint, immutable event, export-record, and archive-member keys. Events are acknowledged only after native persistence, permanent retries stop after five attempts, and verification drift exits `7`.

Use `spectra index backfill-export EXPORT_DIR` for downloads created before outbox integration. It snapshots the manifest byte length, skips an incomplete trailing line, and is idempotent. Use `spectra index benchmark` for reproducible concurrent-write, drain, lookup, replay, crash-recovery, and verification measurements. Repeated KEYSTONE lookups reuse a crash-isolated child and reload automatically when the projection advances.

Modern whole-channel downloads, bounded partial downloads, and failed-media retries pass the selected global `--db` into the downloader. Each ordered checkpoint appends the filesystem manifest record and writes the matching outbox event through one reused SQLite transaction. The filesystem append cannot be part of SQLite's atomic commit; `index backfill-export` is the idempotent recovery path if a process stops between those two writes.

Graph and keyword examples:

```bash
spectra search fulltext "indicator phrase" --output json
spectra index graph --node-type message --external-id=-1002407846598:12 --direction outgoing --output json
```

Export privacy-reviewed real operation examples for model training:

```bash
python training/spectra_operator/export_audit_corpus.py \
  --database spectra.tasks.sqlite3 \
  --output training/spectra_operator/data/operation_audit.jsonl
```

## Agent Planner

The deterministic planner is the first operator-model integration point:

```bash
spectra --output json agent plan "show task task-123 --tail 20"
spectra --output json agent plan "get config accounts.0.session_name"
spectra --output json agent plan "check channel status /fast/ULPs/Export"
spectra --output json agent plan "download media from @target to /fast/ULPs --max-connections 32"
spectra agent plan --file request.txt --output json
```

Supported request families are version, doctor/health, config get, task show, channel status, and channel download. The planner validates arguments through the operation registry and refuses credential-bearing requests. `agent run` executes only allowlisted local handlers; Telegram-backed operations without a shared executor remain unavailable. Every plan, execution, planning failure, and unavailable operation is recorded in the local audit sidecar. Later model-backed planning must retain this validation boundary and must never emit raw shell commands as its trusted output.

The planner also understands discovery/crawling, network analysis, full-text search, channel archive, and table export requests. Examples:

```bash
spectra agent plan "crawl from @seed depth 3 messages 250 parallel --max-workers 4" --output json
spectra agent plan "analyze network from db metric combined top 50" --output json
spectra agent plan 'search for "indicator" --limit 25' --output json
spectra agent plan "archive channel @target --no-media" --output json
spectra agent plan "export table messages to exports/messages.csv --format csv" --output json
```

Inspect the audit trail:

```bash
spectra agent audit list --output json
spectra agent audit show AUDIT_ID --output json
```

## Structured Errors And Exit Codes

With `--output json`, errors use an `error` object containing `code`, `category`, and `message`. The standard categories are:

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `2` | Usage or validation |
| `3` | Configuration or authentication |
| `4` | Not found |
| `5` | Conflict or overwrite refusal |
| `6` | Telegram, network, flood-wait, or timeout |
| `7` | Partial completion |
| `8` | Optional capability unavailable |
| `130` | Interrupted |

Secret-shaped fields are redacted in config, account, task, and operation output. Logs must be checked separately because external library logging can occur before the modern CLI owns the logger configuration.

### Live Download State

The authorized media-only process:

```text
PID 2668344
entity -1002407846598
output /fast/ULPs
max connections 32
max retries 5
retry delay 3 seconds
progress interval 15 seconds
stall timeout 75 seconds
```

Status as of 11:07 BST: **active, not complete.** 114 GB on disk, 938 files. Rate dropped from 24 MiB/s to ~4 MiB/s (Telegram rate-limiting after the initial burst); ETA approximately 3 hours from that point. Zero failed media IDs. `last_message_id: 1058`.

Check it with:

```bash
ps -p 2668344 -o pid=,stat=,etime=,cmd=
tail -n 50 /fast/ULPs/TheUnderground_-_Reborn_2407846598/download.log
spectra channel status /fast/ULPs/TheUnderground_-_Reborn_2407846598 --output json --tail 50
```

Do not delete the export or state files. If the process exits, rerun the same command without `--restart`; existing files are the deduplication boundary. Run `channel retry-failed` after the pass ends if `failed_media_ids` is non-empty. Then run `index backfill-export`, `index drain`, and `index verify --projection all --native`.

## Security And Public Repository Hygiene

`.env`, Telegram session files, databases, logs, key material, tokens, model outputs, checkpoints, generated training data, and cloud-training state are ignored. Local copies remain available to the operator but must not enter a commit.


**Completed (2026-07-29):**

1. Full tracked-file scan identified credentials in 18 files: plaintext phone numbers, API IDs, API hashes, and proxy credentials in `scripts/setup/gen_config.py`, multiple defunct docs, active docs, scripts, and source files.
2. All credential-shaped values replaced with `[REDACTED]` placeholders in the working tree. Security commit: `dee05e9`.
3. `git-filter-repo --replace-text` rewrote all 309 commits with 25 replacement rules (7 phone numbers, 8 API hashes, 8 API IDs, 1 proxy user, 1 proxy password). Post-rewrite `git log -S` scan confirmed zero remaining occurrences across the full history.
4. Local `.env` and session files remain present and untracked.

**Remaining before push:** run a final `git grep` sweep across all branches, then `git push --force`. Credential rotation is not planned.

## Training Framework

The copied framework is under `training/cloud_training_framework/`. It is a pruned native copy of the supplied cloud-training starting point. Heavy artifacts and secrets were excluded. SPECTRA-specific operator training is under `training/spectra_operator/`.

Generate registry-derived data:

```bash
python3 training/spectra_operator/generate_data.py \\
  --output training/spectra_operator/data/train.jsonl \\
  --count-per-template 100
```

Train on a separate L40S or H100 host only:

```bash
pip install -r training/spectra_operator/requirements-gpu.txt
python3 training/spectra_operator/train_spectra_operator.py \\
  --base-model Qwen/Qwen2.5-7B-Instruct \\
  --data-path training/spectra_operator/data/train.jsonl \\
  --output-dir models/spectra-operator-qwen7b
```

The normal workstation uses root `requirements.txt`; GPU training dependencies are intentionally isolated. The cloud launcher has its own `requirements-launcher.txt` for VM control and uses `TRAINING_REPO_DIR` to sync the SPECTRA root while excluding secrets, databases, caches, and model artifacts.

Recommended training progression is registry-derived positive examples, malformed/ambiguous requests, explicit refusal examples for credentials and destructive ambiguity, then held-out operation/schema validation. VectorReVamp-style augmentation can expand language variation, but generated samples must still be parsed and validated against the live registry before entering training data.

## Verification Evidence

The latest focused checks passed:

```bash
PYTHONPATH=. pytest -q tgarchive/tests/test_cli_app.py -k 'agent_plan or operations'
```

Result: 6 passed, 75 deselected, 1 warning.

The primary repository suite now exits normally with `247 passed, 9 skipped, 24 warnings`; the previous delayed exit-139 fault was removed by taking the obsolete parent-process QIHSE temporal-search ABI out of service. Focused CLI, downloader, indexing, archive-scanner, operator-training, and remote benchmark checks also pass. Python compilation and `git diff --check` pass. Five skips are async OSINT tests because this system interpreter does not currently have the already-declared `pytest-asyncio` test dependency installed; the remaining skips are optional service cases.

The active pre-upgrade export now has persistent export ID `83817bd5-a342-5556-9aa6-b193760e29e9`. Backfill imported 1,065 complete manifest records with stable ordinals, zero malformed records, zero partial-tail records, and exact byte-range SHA verification. After processing ten records from the second active downloader, `spectra.db` contained 2,160 processed outbox events with zero pending or failed events. All nine SQLite/native projections verified successfully, including KEYSTONE identity maps, 1,075 export records, 2,154 message IDs, 2,160 QIHSE content rows, and 2,155 graph rows. Exact export-record and task-event lookups resolve through the persistent native worker.

The active primary and task-sidecar watchers are now installed as **durable user units** `spectra-index.service` and `spectra-index-tasks.service` in `~/.config/systemd/user/`, enabled with `loginctl enable-linger`. They survive reboots and restart on failure. The transient `spectra-index-live.service` and `spectra-index-tasks-live.service` units (launched via `systemd-run`) remain running; switch to the persistent units by stopping the transient ones. Claims carry opaque ownership tokens, so a worker whose lease expires cannot overwrite the current owner's acknowledgement. Vector and graph native stores use separate bounded cross-process advisory locks with crash-safe release. Watcher failures emit redacted JSON diagnostics to stderr and use capped exponential backoff. Persistent KEYSTONE generations include projection state and ordered-key checksums, QIHSE verification requires exact source identity even for duplicate vectors, and archive scans use content-derived IDs with bounded ZIP-directory preflight. The task sidecar contains 234 processed events with zero pending or failed rows and passes all-nine native verification.

The serialized projection writer benchmark submitted 200 events through eight writers at 1,436.64 events/second and drained them in 0.810 seconds, down from 3.398 seconds with per-event commits. Replaying 240 events took 0.803 seconds, expired-lease recovery reclaimed attempt two, and all nine native projections verified.

No configured Nebius training VM is currently available (`ml-training: not_found`), and no NVIDIA cloud credentials are present in the process environment. The L40S/H100 comparative benchmark therefore remains an off-workstation follow-up; it is not required by the workstation runtime. A provider-independent launcher is ready:

```bash
python3 training/cloud_training_framework/remote_index_benchmark.py \
  --target ubuntu@HOST \
  --identity-file ~/.ssh/id_ed25519 \
  --remote-dir /opt/training-repo \
  --spectra-bin /opt/training-repo/.venv/bin/spectra
```

Use `--dry-run` first. The launcher requires an explicit target, validates native QIHSE and KEYSTONE before benchmarking, enforces connection/stage timeouts, and redacts the identity path and credential-shaped diagnostics.

## Next Work In Order

1. **Confirm download complete** — `state.json → complete: true`; run `channel retry-failed` if `failed_media_ids` non-empty.
2. **Backfill and verify index** — `index backfill-export`, `index drain`, `index verify --projection all --native`.
3. **Final git sweep** — `git grep` across all branches for any credential patterns not caught by the filter-repo pass.
4. **Clean-environment build** — install wheel in a fresh venv, traverse every `--help` path, confirm no startup noise.
5. **Push** — `git push --force` to publish rewritten history.
6. **Promote remaining operations** — move business logic from Flask routes and CLI handlers into shared validated services.
7. **Extend operation records** — authorization decisions and remote-execution contracts.
8. **GPU benchmark** — run `remote_index_benchmark.py` once an L40S/H100 host is reachable.

## Key Files

- [CLI application](tgarchive/cli/app.py)
- [CLI router](tgarchive/__main__.py)
- [Operation models](tgarchive/operations/models.py)
- [Operation registry](tgarchive/operations/registry.py)
- [Built-in operation definitions](tgarchive/operations/builtin.py)
- [Deterministic planner](tgarchive/operations/planner.py)
- [Channel downloader](tgarchive/services/channel_downloader.py)
- [CLI infrastructure docs](docs/docs/api/cli-infrastructure.md)
- [Lookup and indexing architecture](docs/docs/api/indexing-architecture.md)
- [CLI reference](docs/docs/api/cli-reference.md)
- [Project plan](OverarchignPlan.md)
- [Operator training](training/spectra_operator/README.md)
- [Cloud framework notes](training/cloud_training_framework/SPECTRA.md)
