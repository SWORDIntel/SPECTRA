# SPECTRA CLI Reference

SPECTRA is a **CLI-first** intelligence framework designed for forensic investigation, Telegram network discovery, and automated threat actor attribution.

All operational capabilities are accessible via the root executable:

```bash
./spectra [COMMAND] [OPTIONS]
```

---

## 🚀 Common Commands

### 1. Interactive TUI Launch
```bash
# Launch default operator console
./spectra

# Launch specialized CaaS semantic intelligence TUI
./spectra semantic-tui
```

### 2. Semantic Network Discovery (Layer 0)
Traverses Telegram networks using CaaS (Crime-as-a-Service) heuristic scoring to map high-value target clusters.

```bash
# Discover connected channels starting from a seed
./spectra discover --seed @target_channel --depth 2

# Discover from a list of seeds and export results
./spectra discover --seeds-file seeds.txt --depth 2 --export discovered.json
```

### 3. Forensic Actor Profiling (Layer 1)
Extracts pricing, criminal services, aliases, and operational footprint into structured dossiers.

```bash
# Generate forensic actor profile
./spectra profile --target @target_channel

# Export structured intelligence dossier
./spectra profile --target @target_channel --export-json dossier.json
```

### 4. Background Worker Queue (Layer 1.5)
Executes bulk extraction jobs through the automated worker queue.

```bash
# Process a single batch
./spectra process-queue --batch-size 250

# Continuous processing daemon
./spectra process-queue --loop --interval 30
```

### 5. Forensic Archiving
Archives messages, media, reactions, and sidecar metadata with cryptographic integrity checksums.

```bash
# Archive a target channel
./spectra archive --entity @target_channel

# Archive with media downloads
./spectra archive --entity @target_channel --download-media --media-types photo,document
```

### 6. Account Pool Management
```bash
# List configured Telegram accounts and status
./spectra accounts --list

# Test connectivity across all configured proxies
./spectra accounts --test

# Import accounts from configuration
./spectra accounts --import
```

### 7. Environment & Maintenance
```bash
# Automatic setup & virtual environment creation
./spectra bootstrap

# Install or update dependencies
./spectra install

# Repair a damaged virtualenv or missing packages
./spectra repair

# Show complete CLI help
./spectra --help
```
