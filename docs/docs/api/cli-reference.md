---
id: cli-reference
title: CLI Reference
sidebar_position: 1
description: Complete command-line interface documentation
tags: [api, cli, commands]
---

# CLI Reference

For automation, scripting, and advanced use cases, SPECTRA provides a comprehensive CLI. Most operations available in the TUI can also be performed via CLI commands.

## Account Management

```bash
# Import accounts from gen_config.py
python -m tgarchive accounts --import

# List configured accounts and their status
python -m tgarchive accounts --list

# Test all accounts for connectivity
python -m tgarchive accounts --test

# Reset account usage statistics
python -m tgarchive accounts --reset
```

## Discovery Mode

```bash
# Discover groups from a seed entity
python -m tgarchive discover --seed @example_channel --depth 2

# Discover from multiple seeds in a file
python -m tgarchive discover --seeds-file seeds.txt --depth 2 --export discovered.txt

# Import existing scan data
python -m tgarchive discover --crawler-dir ./telegram-groups-crawler/
```

## Network Analysis

```bash
# Analyze network from crawler data
python -m tgarchive network --crawler-dir ./telegram-groups-crawler/ --plot

# Analyze network from SQL database
python -m tgarchive network --from-db --export priority_targets.json --top 50
```

## Archive Mode

```bash
# Archive a specific channel
python -m tgarchive archive --entity @example_channel
```

## Batch Operations

```bash
# Process multiple groups from file
python -m tgarchive batch --file groups.txt --delay 30

# Process high-priority groups from database
python -m tgarchive batch --from-db --limit 20 --min-priority 0.1
```

## Parallel Processing

SPECTRA supports parallel processing using multiple Telegram accounts and proxies simultaneously:

```bash
# Run discovery in parallel across multiple accounts
python -m tgarchive parallel discover --seeds-file seeds.txt --depth 2 --max-workers 4

# Join multiple groups in parallel
python -m tgarchive parallel join --file groups.txt --max-workers 4

# Archive multiple entities in parallel
python -m tgarchive parallel archive --file entities.txt --max-workers 4
```

## Forwarding

See the [Forwarding Guide](../guides/forwarding.md) for complete forwarding command documentation.

## Shunt Mode

Shunt Mode transfers all media files from one Telegram channel to another with advanced deduplication.

```bash
python -m tgarchive --shunt-from @source_channel --shunt-to @destination_channel
```

See the [Shunt Mode Guide](../guides/shunt-mode.md) for detailed documentation.

## Agent Planner

The Agent Planner can formulate automated intelligence gathering plans from natural language requests.

```bash
# Generate an execution plan from a natural language request
spectra agent plan "download all media from -1002407846598 to /fast/ULPs" --output json
```

### Agent Run
Safely execute an operation plan using the unified execution manager, with full audit trails and idempotency tracking.

```bash
spectra agent run "download all media from -1002407846598 to /fast/ULPs"
```
Or from a pre-planned JSON file:
```bash
spectra agent run --file plan.json
```

## Mass Channel Downloader

The modern CLI supports high-performance, resumable mass channel media downloading that can safely run in parallel across multiple accounts to different directories. It bypasses legacy global locks and maintains local state manifests to skip duplicates and resume interrupted transfers.

```bash
# Mass download all media from a channel with a specific account to a specific directory
python -m tgarchive channel download --account +447871042245 --output-dir channel_downloads -- -1002778007272

# Tune the concurrency and reliability for massive channels
spectra channel download @example_channel \
    --max-connections 64 \
    --max-retries 10 \
    --retry-delay 5.0 \
    --progress-interval 30.0

# Download ONLY media (skip saving text JSONL metadata)
spectra channel download @example_channel --media-only

# Retry ONLY media files that failed to download in a previous run
spectra channel retry-failed @example_channel --output-dir channel_downloads

# Inspect local download status and statistics
spectra channel status channel_downloads/ --output json
```

## Live Unified Monitor

You can monitor all active mass channel downloads locally using a `rich`-based terminal UI dashboard that tracks progress, download speeds, ETAs, failure counts, and the last log output for every job.

```bash
# Launch the live interactive TUI monitor for a directory of downloads
spectra channel monitor /fast/ULPs
```
