---
title: Channel Downloads
---

# Channel Downloads

SPECTRA can download a complete accessible Telegram channel, a bounded message
range, or only the media attached to matching messages. Downloads are resumable
and use existing files plus `state.json` as the deduplication boundary.

## Whole-channel download

Pass a channel username, numeric peer ID, or private-channel peer ID:

```bash
spectra --db spectra.db channel download \
  --account ACCOUNT_NAME \
  --output-dir /fast/ULPs \
  --media-only \
  --max-connections 32 \
  --no-proxy \
  -- -1002407846598
```

The `--` separator prevents a negative numeric peer ID from being interpreted
as an option. Use `--auto` instead of `--account` to select an available,
authorized account.

`--media-only` suppresses message JSONL output but still writes the durable
media manifest needed for resume, deduplication, indexing, and recovery.
Omit it to retain message metadata as well.

## Partial downloads

Use message ID bounds for a stable range, or `--limit` for a bounded pass:

```bash
spectra --db spectra.db channel download \
  --account ACCOUNT_NAME \
  --output-dir /fast/ULPs \
  --min-id 1000 \
  --max-id 2000 \
  -- -1002407846598

spectra --db spectra.db channel download \
  --account ACCOUNT_NAME \
  --output-dir /fast/ULPs \
  --limit 100 \
  -- -1002407846598
```

The same accelerated media pipeline, manifest format, and index outbox are used
for whole-channel and partial downloads.

## Concurrency and progress

The default media concurrency is 32:

```bash
spectra channel download \
  --max-connections 32 \
  --max-retries 5 \
  --retry-delay 3 \
  --progress-interval 15 \
  --stall-timeout 75 \
  --account ACCOUNT_NAME \
  --output-dir /fast/ULPs \
  -- -1002407846598
```

Each active transfer writes a `.part` file and atomically promotes it to the
final media filename after completion. Seeing `.part` files while the process
and byte counters are advancing is normal. A transfer that makes no byte
progress for `--stall-timeout` seconds is retried.

Aggregate log entries report:

- messages examined during the current run;
- downloaded, skipped, duplicate, and failed media counts;
- active transfer and ordered-result queue counts;
- bytes transferred, current throughput, and active-transfer ETA.

Telegram, disk, and upstream server limits usually determine useful
concurrency. Raising the value beyond 32 can reduce throughput or increase
flood waits; compare measured rates before keeping a larger setting.

## Inspecting a running export

```bash
spectra channel status \
  /fast/ULPs/TheUnderground_-_Reborn_2407846598 \
  --tail 30 \
  --output json

tail -f /fast/ULPs/TheUnderground_-_Reborn_2407846598/download.log
```

The status report includes the durable checkpoint, export completion flag,
current-run counters, failed IDs, completed media count and bytes, manifest
record count, and the freshest known log.

The durable `last_message_id` can remain unchanged while later media transfers
advance. SPECTRA commits manifest and state records in deterministic message
order, so an earlier large transfer can temporarily hold the checkpoint behind
completed later transfers. Use active-transfer count, byte progress, and log
timestamps to decide whether the process is stalled.

## Resume and deduplication

Rerun the same command after an interruption. Resume is enabled by default:

```bash
spectra --db spectra.db channel download \
  --account ACCOUNT_NAME \
  --output-dir /fast/ULPs \
  --media-only \
  -- -1002407846598
```

SPECTRA preserves the export ID and record ordinals, loads `state.json`, checks
existing final files, and avoids duplicate downloads. Do not delete
`manifest.json`, `state.json`, `media_manifest.jsonl`, or completed media before
resuming.

`--restart` ignores the durable message checkpoint. It does not make duplicate
files desirable and should be reserved for a deliberate full rescan.

## Failed-media recovery

Wait for the whole or bounded pass to exit before retrying its failures:

```bash
spectra --db spectra.db channel retry-failed \
  --account ACCOUNT_NAME \
  --output-dir /fast/ULPs \
  --max-connections 32 \
  --no-proxy \
  -- -1002407846598
```

The retry command reads the export's failed IDs, checks files already present,
and uses the same concurrent downloader. Re-run `channel status` afterward and
review any remaining failure categories. Persistent access-denied, deleted,
or unavailable media may remain unresolved and should not be treated as a
transfer stall.

## Index recovery and verification

Filesystem manifest appends and SQLite commits cannot share one atomic
transaction. Reconcile the final stable manifest after a completed or
interrupted pass:

```bash
spectra --db spectra.db index backfill-export \
  /fast/ULPs/TheUnderground_-_Reborn_2407846598 \
  --output json

spectra --db spectra.db index drain --output json
spectra --db spectra.db index verify \
  --projection all \
  --native \
  --sample-size 32 \
  --output json
```

Backfill snapshots the manifest byte length, ignores an incomplete trailing
record, preserves export identity and ordinals, and is idempotent. Verification
must report `ok: true` before the export/index recovery is considered complete.

## Recovery checklist

1. Confirm whether the downloader process is still present.
2. Inspect `channel status` and the current `download.log`.
3. Compare byte counters and `.part` modification times across two intervals.
4. Resume the original command if the process exited before `complete: true`.
5. Run `retry-failed` only after the main pass exits.
6. Run `index backfill-export`, drain both active outboxes, and verify native
   projections.
7. Preserve the export until final counts, checksums, and remaining failures
   have been reviewed.
