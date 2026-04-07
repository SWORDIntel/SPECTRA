# SPECTRA Branch Supplement: Semantic Pipeline & Dedicated TUI

This document supplements the top-level `README.md` for the current branch while the legacy entrypoint splice is still in progress.

## What changed on this branch

The branch adds a parallel semantic-intelligence path built around:

- semantic discovery and triage
- canonical channel-scoped archival
- queue-backed message profiling
- a dedicated interactive TUI for reviewing signals

## New modules

- `tgarchive/core/sync_canonical.py`
- `tgarchive/osint/caas/discovery_ops.py`
- `tgarchive/osint/caas/discovery_fingerprint.py`
- `tgarchive/osint/caas/profiler_v2.py`
- `tgarchive/osint/caas/queue_worker.py`
- `tgarchive/osint/caas/schema.py`
- `tgarchive/ui/tui_caas.py`

## Why this path exists

The legacy archive/discovery stack assumes raw Telegram message IDs are globally unique enough for archival workflows. They are not. Telegram message IDs are channel-local, so a branch-safe cutover path was introduced that uses canonical `(channel_id, message_id)` identity and decouples deep profiling from collection.

## Execution flow

1. **Semantic discovery**
   - scan seed channels
   - assign triage scores
   - persist channel-level signal rows

2. **Canonical archive**
   - archive messages using channel-scoped identity
   - enqueue profile candidates

3. **Queue worker**
   - drain `caas_profile_queue`
   - populate `caas_message_profile`
   - upsert `actor_entity`
   - preserve auditability through stored JSON

4. **TUI review**
   - inspect queue state
   - review high-signal channels
   - review actors and alerts

## Commands

### Dedicated semantic TUI

```bash
python -m tgarchive.ui.tui_caas --config spectra_config.json --db spectra.db --data-dir spectra_data
```

### Semantic discovery

```bash
python -m tgarchive.osint.caas.discovery_ops --seed @seed_channel --db spectra.db --data-dir spectra_data --depth 2 --messages 1000 --triage-sample 100
```

### Canonical archive

```bash
python -m tgarchive.core.sync_canonical --entity @target --db spectra.db --auto
```

### Queue processing

```bash
python -m tgarchive.osint.caas.cli process-queue --db spectra.db --batch-size 500
```

## Current semantic tables

- `caas_channel_profile`
- `caas_profile_queue`
- `caas_message_profile`
- `actor_entity`
- `caas_alert`

## Current status

This path is intentionally parallel to the legacy entrypoints. It is designed for low-risk testing, validation, and gradual splice rather than one-shot replacement of the older collector stack.
