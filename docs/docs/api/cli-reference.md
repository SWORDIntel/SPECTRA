---
id: cli-reference
title: CLI Reference
sidebar_position: 1
description: Complete command-line interface documentation for SPECTRA
tags: [api, cli, commands, spectra]
---

# Unified CLI Reference

SPECTRA is built around a **CLI-first architecture** designed for high-performance forensic analysis, multi-account Telegram crawling, and automated intelligence pipelines.

All operations can be executed directly using the root executable `./spectra` or via the Python module `python -m tgarchive`.

---

## 🚀 Execution Syntax

```bash
./spectra [COMMAND] [OPTIONS]
```

If run without arguments, `./spectra` automatically resolves the local virtual environment and boots the interactive terminal interface (or runs the setup wizard if unconfigured).

---

## 🧠 Core Intelligence Pipeline

### 1. Semantic Discovery (Layer 0)
Traverses Telegram networks using CaaS (Crime-as-a-Service) heuristic scoring to map high-value clusters.

```bash
# Discover connected channels from a seed entity
./spectra discover --seed @target_channel --depth 2

# Discover from a list of seeds
./spectra discover --seeds-file seeds.txt --depth 2 --export discovered.json
```

### 2. Forensic Profiling (Layer 1)
Extracts pricing, criminal services, aliases, and operational footprint into structured dossiers.

```bash
# Generate forensic actor profile
./spectra profile --target @target_channel

# Export structured intelligence dossier
./spectra profile --target @target_channel --export-json dossier.json
```

### 3. Worker Queue Processing (Layer 1.5)
Executes bulk extraction jobs through the automated background worker queue.

```bash
# Process a batch of pending extraction jobs
./spectra process-queue --batch-size 250

# Continuous processing daemon loop
./spectra process-queue --loop --interval 30
```

### 4. Interactive Semantic TUI
Launches the full-terminal operator console.

```bash
./spectra semantic-tui
```

---

## 📁 Archiving & Network Operations

### Account Management
Manage, rotate, and test Telegram MTProto account pools.

```bash
# List configured accounts and session statuses
./spectra accounts --list

# Test connectivity across all account proxies
./spectra accounts --test

# Import accounts from configuration
./spectra accounts --import
```

### Forensic Archiving
Archive full message history, media, reactions, and sidecar metadata.

```bash
# Archive a target channel or group
./spectra archive --entity @target_channel

# Archive with strict media filtering
./spectra archive --entity @target_channel --download-media --media-types photo,document
```

### Infrastructure Nexus & Network Mapping
Correlate bot IDs, payment artifacts, and shared infrastructure across discovered targets.

```bash
# Generate network graph from SQL database
./spectra network --from-db --export priority_targets.json --top 50

# Plot interactive network visualization
./spectra network --from-db --plot
```

---

## ⚙️ Environment & Maintenance Commands

```bash
# Run automatic setup, dependency installation, and venv creation
./spectra bootstrap

# Install or update Python dependencies
./spectra install

# Repair a damaged virtualenv or broken package dependencies
./spectra repair

# Display CLI help and command overview
./spectra --help
```
