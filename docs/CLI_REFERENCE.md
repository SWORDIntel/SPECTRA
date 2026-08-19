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

# Set account rotation strategy
./spectra accounts --set-rotation floodwait_adaptive

# View live rotation stats (circuit breaker, FloodWait cooldowns, latency, channel locks)
./spectra accounts --rotation-stats
```

**Rotation modes** (see [ROTATION_STRATEGIES.md](ROTATION_STRATEGIES.md) for full details):

| Mode | Description |
|------|-------------|
| `sequential` | Round-robin (default) |
| `random` | Random selection |
| `weighted` | Least-used account |
| `smart` | Rested + under-used scoring |
| `floodwait_adaptive` | Auto-cooldowns from real FloodWaitError seconds |
| `circuit_breaker` | Consecutive failure tracking with quarantine + probe recovery |
| `latency` | Prefers fastest RTT account |
| `sticky` | Pins channels to accounts (OPSEC) |
| `sharded` | Deterministic hash-based partitioning |
| `primary_fallback` | Primary account with fallback rotation |

**Flags:**
| Flag | Description |
|------|-------------|
| `--list` | List all accounts and their usage/ban status |
| `--reset` | Reset usage counts for all accounts |
| `--test` | Test all accounts for connectivity |
| `--import` | Import accounts from `gen_config.py` |
| `--set-rotation <mode>` | Set rotation mode and save to config |
| `--rotation-stats` | Show detailed rotation strategy stats |

### 7. tdata → Session Import
Converts logged-in Telegram Desktop / Alternatives `tdata` folders into Telethon `.session` files with **no re-login**. The existing MTProto authorization keys are extracted directly from the on-disk `tdata` and written into native Telethon SQLite sessions. Supports filtering by user_id, username, or converting all accounts at once.

```bash
# Auto-detect Telegram Desktop / Alternatives tdata, write to ./sessions
./spectra tdata2session

# Custom tdata path + output directory
./spectra tdata2session --tdata /path/to/tdata --output sessions

# Convert only a specific account by user_id
./spectra tdata2session --account 8011484242

# Convert multiple specific accounts by user_id (comma-separated)
./spectra tdata2session --account 8011484242,8199441474

# Convert only the account matching a Telegram username (connects to resolve)
./spectra tdata2session --username @someuser

# List all accounts found in tdata (quick, no network)
./spectra tdata2session --list-accounts

# List accounts with resolved usernames/names/phones (connects to Telegram)
./spectra tdata2session --list-accounts --resolve

# Passcode-protected tdata
./spectra tdata2session --passcode 1234

# Also emit Telethon StringSession strings in the JSON sidecars
./spectra tdata2session --string-sessions

# Register converted accounts into spectra_config.json for multi-account use
./spectra tdata2session --register

# Overwrite existing .session files instead of skipping
./spectra tdata2session --overwrite
```

**Flags:**
| Flag | Description |
|------|-------------|
| `--tdata <path>` | Path to the tdata folder. Defaults to auto-detection (Telegram Desktop / Alternatives / snap). |
| `--output <dir>` | Directory to write `.session` + `.json` files (default: `./sessions`). |
| `--account <spec>` | Which account(s) to convert: `all` (default), a numeric user_id, or comma-separated user_ids (e.g., `8011484242,8199441474`). |
| `--username <name>` | Convert only the account matching this Telegram username (e.g., `@someuser`). Requires network access to resolve. |
| `--list-accounts` | List all accounts found in the tdata folder and exit (no conversion). |
| `--resolve` | When used with `--list-accounts`, connect to Telegram to resolve usernames, phones, and display names. |
| `--passcode <code>` | Local passcode if the tdata folder is passcode-protected. |
| `--string-sessions` | Also emit Telethon `StringSession` strings in the JSON sidecars. |
| `--overwrite` | Overwrite existing `.session` files instead of skipping them. |
| `--register` | Register the converted accounts into `spectra_config.json` so SPECTRA can use them. |

**Output:** Each converted account produces two files:
- `spectra_tdata_<user_id>_<n>.session` — native Telethon SQLite session
- `spectra_tdata_<user_id>_<n>.json` — sidecar with `api_id`, `api_hash`, `user_id`, `dc_id`, device info, and optional `StringSession`

The `sessions/` directory is gitignored by default.

### 8. Telegram Sticker Set Downloader
Download, archive, and convert entire Telegram sticker sets (`.webp`, `.tgs`, `.webm`) with full metadata sidecars.

```bash
# Download a sticker set by name or URL
./spectra stickers atklib

# Convert downloaded WebP stickers to PNG
./spectra stickers atklib --png

# Download to a custom output directory
./spectra stickers https://t.me/addstickers/atklib --output /path/to/stickers --png

# Inspect sticker set metadata without downloading files
./spectra stickers atklib --info-only

# Use a specific session and overwrite existing files
./spectra stickers atklib --session spectra_tdata_8011484242_1 --overwrite --png
```

**Flags:**
| Flag | Description |
|------|-------------|
| `stickerset` | Sticker set short name, `@handle`, or `t.me/addstickers/<name>` URL. |
| `-o, --output <dir>` | Destination directory (default: `./data/stickers/<set_name>`). |
| `--png, --convert-png` | Convert downloaded static WebP stickers into PNG format. |
| `--info-only` | Fetch and print sticker set metadata without downloading. |
| `-s, --session <file>` | Specific session file or name in `sessions/` to use. |
| `--sessions-dir <dir>` | Directory containing converted sessions (default: `./sessions`). |
| `--overwrite` | Overwrite existing files instead of skipping. |

### 9. Environment & Maintenance
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
