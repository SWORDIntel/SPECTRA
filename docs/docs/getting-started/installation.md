---
id: installation
title: Installation Guide
sidebar_position: 1
description: Complete installation guide for SPECTRA with automatic bootstrap and CLI setup
tags: [installation, setup, getting-started]
---

# SPECTRA Installation Guide

SPECTRA is packaged as a standard Python package with an automated, self-bootstrapping CLI.

---

## 🚀 Quick Setup (Recommended)

Run the unified bootstrap command from the repository root:

```bash
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA

# Run automated bootstrap
./spectra bootstrap
```

### What the Bootstrap Process Does:
1. Detects your host OS and Python environment.
2. Checks and installs necessary system dependencies.
3. Automatically sets up or validates the local Python virtual environment (`.venv`).
4. Installs SPECTRA in editable mode (`pip install -e .`) along with core dependencies.
5. Initializes required local storage directories (`data/`, `logs/`, `config/`).

---

## 🔧 Manual Installation

If you prefer to configure your environment manually:

```bash
# 1. Create and activate a Python 3.10+ virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Upgrade pip and build tooling
pip install --upgrade pip setuptools wheel

# 3. Install SPECTRA and dependencies
pip install -e .
```

---

## 🔑 Operational Configuration

Create or update your API credentials in `data/config/spectra_config.json`:

```json
{
    "api_id": 1234567,
    "api_hash": "your_telegram_api_hash_here"
}
```

---

## 🧪 Verification

Verify your installation:

```bash
./spectra --help
```
