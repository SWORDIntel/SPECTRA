---
id: quick-start
title: Quick Start Guide
sidebar_position: 2
description: Quick start walkthrough for SPECTRA intelligence pipelines
tags: [quick-start, getting-started, launch]
---

# Quick Start Guide

Get up and running with SPECTRA in under a minute.

---

## ⚡ Launching SPECTRA

### Interactive Operator Console
Launch the interactive terminal interface:

```bash
./spectra
```
*(If this is your first run, `./spectra` automatically runs the bootstrap wizard first).*

### Semantic Intelligence TUI
Directly launch the specialized Crime-as-a-Service (CaaS) intelligence TUI:

```bash
./spectra semantic-tui
```

---

## 🔍 Common Operations

### 1. Network Discovery
Map out connected channels and infrastructure starting from a seed entity:

```bash
./spectra discover --seed @target_channel
```

### 2. Forensic Actor Profiling
Extract economic metrics, services offered, aliases, and pricing dossiers:

```bash
./spectra profile --target @target_channel
```

### 3. Background Worker Queue
Run bulk extraction tasks from the job queue:

```bash
./spectra process-queue --batch-size 250
```

### 4. Forensic Archiving
Archive all historical posts and media from a channel:

```bash
./spectra archive --entity @target_channel
```

---

## 🐳 Docker Deployment

To run SPECTRA in containerized headless worker mode alongside Qdrant:

```bash
docker-compose up -d
```
