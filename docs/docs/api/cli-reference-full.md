# SPECTRA CLI Reference

SPECTRA is a **CLI-first** intelligence framework designed for forensic investigation, Telegram network discovery, and automated threat actor attribution.

All operational capabilities are accessible via the root executable:

```bash
./spectra [COMMAND] [OPTIONS]
```

Running `./spectra` with no command prints help. The TUI is no longer the default — all operations are CLI subcommands.

---

## Core Operations

### archive
Archives messages, media, reactions, and sidecar metadata with cryptographic integrity checksums.

```bash
# Archive a target channel
./spectra archive --entity @target_channel

# Archive with media downloads
./spectra archive --entity @target_channel --download-media --media-types photo,document
```

### download-channel
Downloads channels via the modern `ChannelDownloader` with enhanced retry logic, stall detection, and flood-wait handling.

Supports **round-robin multi-account downloading** — cycles through all configured Telegram accounts, auto-rotating on FloodWait errors. Each account resumes from the last checkpoint, distributing load across sessions.

```bash
# Download a channel with auto account selection
./spectra download-channel --entity @target_channel --auto

# Download with limits and no media
./spectra download-channel --entity @target_channel --no-media --limit 1000

# Download only media (skip messages)
./spectra download-channel --entity @target_channel --media-only

# Restart a stalled download
./spectra download-channel --entity @target_channel --restart --stall-timeout 120

# Round-robin: use all configured accounts, rotate on FloodWait
./spectra download-channel --entity @target_channel --round-robin --no-proxy

# Round-robin with random rotation and custom rotation limit
./spectra download-channel --entity @target_channel --round-robin \
  --rotation-mode random --max-rotations 100
```

**Flags:**
| Flag | Description |
|------|-------------|
| `--entity <channel>` | Channel/group to download (required). |
| `--account <name>` | Session name to use. |
| `--auto` | Auto-select account from pool. |
| `--output-dir <dir>` | Output directory. |
| `--no-media` | Skip media downloads. |
| `--no-proxy` | Disable proxy. |
| `--limit <n>` | Maximum messages to download. |
| `--min-id <id>` | Start from message ID. |
| `--max-id <id>` | Stop at message ID. |
| `--restart` | Restart from scratch (ignore resume state). |
| `--media-only` | Download only media (skip messages). |
| `--max-connections <n>` | Max concurrent connections. |
| `--max-retries <n>` | Max retries per download. |
| `--retry-delay <s>` | Delay between retries. |
| `--fail-fast` | Stop on first error. |
| `--no-retry-flood-waits` | Don't auto-retry on FloodWait. |
| `--progress-interval <s>` | Progress report interval. |
| `--stall-timeout <s>` | Timeout for stalled downloads. |
| `--round-robin` | Use all configured accounts in rotation (auto-rotates on FloodWait). |
| `--rotation-mode <mode>` | Account rotation mode: `sequential` (default) or `random`. |
| `--max-rotations <n>` | Max account rotations before giving up (default: 50). |

**Round-robin mode** uses `RoundRobinChannelDownloader` which:
- Cycles through all accounts in `spectra_config.json`
- On FloodWait: puts the current account in cooldown, switches to the next available one
- Each rotation resumes from the last checkpoint (`state.json`)
- Continues until the download completes or all rotations are exhausted
- Requires at least 2 configured accounts

### retry-failed
Retries failed media downloads for a specific channel using the modern downloader's retry system.

```bash
# Retry failed downloads for a channel
./spectra retry-failed --entity @target_channel

# Retry with specific account and custom retry settings
./spectra retry-failed --entity @target_channel --account spectra_tdata_8011484242_1 --max-retries 5 --retry-delay 10
```

**Flags:** Same as `download-channel` minus `--limit`, `--min-id`, `--max-id`, `--restart`, `--media-only`.

### discover
Traverses Telegram networks using CaaS (Crime-as-a-Service) heuristic scoring to map high-value target clusters.

```bash
# Discover connected channels starting from a seed
./spectra discover --seed @target_channel --depth 2

# Discover from a list of seeds and export results
./spectra discover --seeds-file seeds.txt --depth 2 --export discovered.json
```

### network
Analyzes the network of discovered Telegram groups using graph metrics (degree, betweenness, PageRank).

```bash
# Analyze network from crawler data
./spectra network --crawler-dir ./data/crawlers

# Analyze from database with plot output
./spectra network --from-db --plot --export network.json

# Top channels by PageRank
./spectra network --from-db --metric pagerank --top 20
```

**Flags:**
| Flag | Description |
|------|-------------|
| `--crawler-dir <dir>` | Crawler data directory. |
| `--plot` | Generate a visual plot of the network. |
| `--metric <type>` | Metric: `degree`, `in_degree`, `betweenness`, `pagerank`, `combined`. |
| `--export <file>` | Export network data to JSON. |
| `--top <n>` | Show top N channels by metric. |
| `--from-db` | Use discovered groups from database. |

---

## Batch / Parallel Operations

### batch
Batch operations on multiple groups from a file or database.

```bash
# Process groups from a file
./spectra batch --file groups.txt --delay 5

# Process priority groups from database
./spectra batch --from-db --limit 50 --min-priority 5
```

**Flags:**
| Flag | Description |
|------|-------------|
| `--file <path>` | File with list of groups to process. |
| `--from-db` | Use priority groups from database. |
| `--delay <s>` | Delay between operations. |
| `--limit <n>` | Maximum groups to process. |
| `--min-priority <n>` | Minimum priority threshold. |
| `--no-leave` | Don't leave groups after processing. |

### parallel
Run operations in parallel across multiple accounts.

```bash
# Parallel discovery across accounts
./spectra parallel discover --seeds-file seeds.txt --depth 2

# Parallel group joining
./spectra parallel join --channels-file channels.txt

# Parallel archiving
./spectra parallel archive --channels-file channels.txt
```

**Subcommands:** `discover`, `join`, `archive`

---

## Account Management

### accounts
Manage Telegram accounts, rotation strategies, and connectivity.

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

### tdata2session
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
| `--account <spec>` | Which account(s) to convert: `all` (default), a numeric user_id, or comma-separated user_ids. |
| `--username <name>` | Convert only the account matching this Telegram username. Requires network access. |
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

---

## Forwarding

### forward
Forward messages between channels or perform targeted traversal and downloading. Useful for channel recovery when the owner has been banned.

```bash
# Forward from one channel to another
./spectra forward --origin @source_channel --destination @dest_channel

# Cloud forwarding: traverse a series of channels from a file
./spectra forward --channels-file channels.txt --output-dir ./output

# Forward to all saved dialogs
./spectra forward --origin @source --forward-to-all-saved

# Copy into destination (no forward header)
./spectra forward --origin @source --destination @dest --copy-into-destination
```

**Flags:**
| Flag | Description |
|------|-------------|
| `--origin <channel>` | Source channel. |
| `--destination <channel>` | Destination channel. |
| `--channels-file <path>` | File with channels for traversal mode. |
| `--output-dir <dir>` | Output directory for traversal mode. |
| `--max-depth <n>` | Maximum traversal depth. |
| `--min-files-gateway <n>` | Minimum files to consider a gateway. |
| `--account <name>` | Session name to use. |
| `--total-mode` | Total mode forwarding. |
| `--all-dialogs` | Include all dialogs. |
| `--forward-to-all-saved` | Forward to all saved messages. |
| `--prepend-origin-info` | Prepend origin channel info to forwarded messages. |
| `--copy-into-destination` | Copy without forward header. |
| `--preserve-forward-header` | Preserve the original forward header. |

---

## Configuration

### config
Manage SPECTRA configuration.

```bash
# Set the default forwarding destination
./spectra config set-forward-dest --dest-id 123456789

# View the current forwarding destination
./spectra config view-forward-dest
```

**Subcommands:** `set-forward-dest`, `view-forward-dest`

---

## Channel Management

### channels
Manage channel-related information.

```bash
# Update the list of channels accessible by each account
./spectra channels update-access
```

**Subcommands:** `update-access` — updates the channel access map for all accounts.

---

## Scheduling

### schedule
Manage scheduled tasks with cron-style scheduling.

```bash
# Add a scheduled task
./spectra schedule add --name nightly_crawl --schedule "0 2 * * *" --command "discover --seed @target"

# List all scheduled tasks
./spectra schedule list

# Remove a scheduled task
./spectra schedule remove --name nightly_crawl

# Run the scheduler daemon
./spectra schedule run

# Add a channel forwarding schedule
./spectra schedule add-channel-forward --source @src --dest @dst --schedule "*/30 * * * *"

# Add a file forwarding schedule
./spectra schedule add-file-forward --source @src --dest @dst --schedule "0 * * * *"

# Report status of file forwarding schedules
./spectra schedule report
```

**Subcommands:** `add`, `list`, `remove`, `run`, `add-channel-forward`, `add-file-forward`, `report`

---

## Migration

### migrate
Perform a one-time migration of data between sources.

```bash
./spectra migrate --source ./old_data --destination ./new_data --dry-run
```

**Flags:** `--source` (required), `--destination` (required), `--dry-run`, `--parallel`

### migrate-report
Generate a report for a completed migration.

```bash
./spectra migrate-report --migration-id <id>
```

**Flags:** `--migration-id` (required)

### rollback
Roll back a migration.

```bash
./spectra rollback --migration-id <id>
```

**Flags:** `--migration-id` (required)

---

## Advanced Tools

### download-users
Download user list from a server.

```bash
./spectra download-users --server-id 12345 --output-file users.csv --output-format csv
```

**Flags:**
| Flag | Description |
|------|-------------|
| `--server-id <id>` | Server ID (required). |
| `--output-file <path>` | Output file path (required). |
| `--output-format <fmt>` | `csv`, `json`, or `sqlite`. |
| `--rotate-ip` | Rotate IP addresses. |
| `--rate-limit-delay <s>` | Delay between requests. |

### mirror
Mirror a group to another group using two separate accounts.

```bash
./spectra mirror --source @source_group --destination @dest_group \
  --source-account account1 --destination-account account2
```

**Flags:** `--source` (required), `--destination` (required), `--source-account` (required), `--destination-account` (required)

### osint
OSINT commands for tracking users and their interactions.

```bash
# Add a user to the OSINT targets list
./spectra osint add-target @username

# Remove a user from the targets list
./spectra osint remove-target @username

# List all OSINT targets
./spectra osint list-targets

# Scan a channel for interactions involving a target
./spectra osint scan --target @username --channel @channel

# Show the interaction network for a target user
./spectra osint show-network --target @username
```

**Subcommands:** `add-target`, `remove-target`, `list-targets`, `scan`, `show-network`

### sort
Watch a directory and sort new files by type.

```bash
./spectra sort --directory ./downloads --output-directory ./sorted
```

**Flags:** `--directory` (required, directory to watch), `--output-directory` (required, destination for sorted files)

### stickers
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

---

## Crypto & Security

### decode-miniapp
Decodes Telegram Mini App (Web App) deep links of the form `t.me/<bot>/app?startapp=<payload>`. Extracts bot commands, referral/invite codes, and ad-attribution segments from the opaque `startapp` parameter.

```bash
# Human-readable decode
./spectra decode-miniapp "https://t.me/virus_play_bot/app?startapp=openRouletteMain_inviteCodeuoAAYtVHNUPG9imz_adSegmentCode=freespininlineshare4"

# Structured JSON output (for piping into other tools)
./spectra decode-miniapp --json "https://t.me/some_bot/app?startapp=..."
```

**Flags:**
| Flag | Description |
|------|-------------|
| `url` (positional) | The Mini App URL to decode. |
| `--json` | Emit structured JSON instead of human-readable output. |

**Supported encodings:** bare commands (`openRouletteMain`), equals-delimited (`key=value`), and camelCase concatenation (`inviteCode<value>`). Also available as a library: `from tgarchive.utils.webapp_parser import MiniAppURL`.

### crypto
CNSA 2.0 post-quantum cryptography operations. Requires `liboqs-python` and `cryptography`.

```bash
# Show algorithm information
./spectra crypto info

# Generate a KEM or signature keypair
./spectra crypto keygen --type kem --key-id recipient_001 -o keypair.json
./spectra crypto keygen --type sig --key-id sender_001 -o sig_keypair.json

# Encrypt a string or file
./spectra crypto encrypt "Classified data" --pubkey keypair.json -o ciphertext.json
./spectra crypto encrypt /path/to/file --pubkey keypair.json --from-file -o ciphertext.json

# Decrypt
./spectra crypto decrypt ciphertext.json --privkey keypair.json -o plaintext.txt

# Sign and verify
./spectra crypto sign "Intelligence report" --privkey sig_keypair.json --signer-id analyst_007 -o signed.json
./spectra crypto verify signed.json --pubkey sig_keypair.json
```

**Subcommands:**
| Subcommand | Description |
|------------|-------------|
| `info` | Show CNSA 2.0 algorithm information (KEM, signature, hash). |
| `keygen` | Generate a KEM or signature keypair. `--type kem\|sig`, `--key-id`, `-o`. |
| `encrypt` | Encrypt a string or file. `--pubkey`, `-o`, `--from-file`. |
| `decrypt` | Decrypt a ciphertext file. `--privkey`, `-o`. |
| `sign` | Create a signed package. `--privkey`, `--signer-id`, `-o`, `--from-file`. |
| `verify` | Verify a signed package and optionally extract plaintext. `--pubkey`, `-o`. |

---

## Threat Analysis

### threat
Writing-style attribution, tool fingerprinting, operational pattern detection, AI-generated content detection, and temporal activity analysis.

```bash
# Attribution analysis on a JSON file of messages
./spectra threat attribution messages.json
./spectra threat attribution messages.json --json

# Temporal pattern analysis (requires date fields in messages)
./spectra threat temporal messages.json
./spectra threat temporal messages.json --json
```

**Subcommands:**
| Subcommand | Description |
|------------|-------------|
| `attribution` | Analyze messages for writing style, tool fingerprints, operational patterns, and AI-generated content. |
| `temporal` | Analyze temporal activity patterns, peak hours, timezone inference, and predict next activity. |

**Input format:** JSON array of `{"id": ..., "text": ..., "date": "ISO-8601"}` objects.

---

## Vector Search

### vectors
Semantic vector store operations for message similarity search.

```bash
# Show vector store statistics
./spectra vectors stats --path ./data/qihse_vectors --backend qihse

# Semantic search for similar messages
./spectra vectors search "suspicious activity" --top-k 5 --threshold 0.5
```

**Subcommands:**
| Subcommand | Description |
|------------|-------------|
| `stats` | Show vector store statistics. `--path`, `--backend`. |
| `search` | Semantic search for similar messages. `--path`, `--top-k`, `--threshold`. |

**Backends:** `qihse` (sole production backend). `qdrant`/`chromadb` are legacy fallbacks (not installed). `numpy` is testing-only.

## Index Management

### index

Manage the IndexOutbox → IndexProjector pipeline that projects SQLite data into QIHSE (content, graph, errors) and KEYSTONE (ID anchors, events, media manifests).

```bash
# Drain pending outbox events into projections
./spectra index drain

# Drain with custom batch size and flush cadence
./spectra index drain --batch-size 500 --flush-every-batches 20 --flush-interval-seconds 30

# Drain a limited number of batches
./spectra index drain --max-batches 10

# Rebuild all projections from scratch
./spectra index rebuild

# Rebuild a single projection
./spectra index rebuild --projection qihse.content.v1

# Show projection status
./spectra index status

# Show projection lag (unprocessed outbox events)
./spectra index lag --output json

# Query error projection
./spectra index errors --stats
./spectra index errors --category projection --limit 20

# Backfill existing database records into the index
./spectra index backfill-database

# Backfill with a limit
./spectra index backfill-database --limit 10000

# Scan an archive file and index its contents
./spectra index scan-archive exports/archive.zip --output json

# Benchmark index performance
./spectra index benchmark --events 1000 --writers 16

# Look up a channel-scoped message via KEYSTONE
./spectra index lookup --channel-id -100123 --message-id 42

# Look up a typed non-message record
./spectra index lookup-record checkpoints spectra checkpoint-001
```

**Native argparse subcommands** (wired directly to service modules):

| Subcommand | Description | Key Flags |
|------------|-------------|-----------|
| `drain` | Process pending IndexOutbox events into QIHSE/KEYSTONE projections. | `--batch-size`, `--max-batches`, `--lease-seconds`, `--flush-every-batches`, `--flush-interval-seconds` |
| `backfill-database` | Append existing SQLite records (messages, users, media, checkpoints, events) to IndexOutbox for projection. | `--limit` |
| `stats` | Show IndexOutbox event counts (total/pending/claimed/processed/failed) and per-projection state. | — |
| `rebuild` | Rebuild one or all projections from outbox history. | `--projection all\|<name>` |

**Subcommands:**

| Subcommand | Description |
|------------|-------------|
| `drain` | Process pending IndexOutbox events into projections. |
| `rebuild` | Rebuild all projections from scratch. |
| `status` | Show projection status and counts. |
| `lag` | Show unprocessed outbox events per projection. |
| `errors` | Query the `qihse.errors.v1` error projection. `--stats`, `--category`, `--limit`. |
| `backfill-database` | Backfill existing SQLite records (messages, users, media, checkpoints, events) into the index. |
| `scan-archive` | Scan a zip archive and index its member files. `--limit`. |
| `benchmark` | Benchmark concurrent writes, projection drain, lookups, and replay. `--events`, `--writers`, `--lookups`. |
| `lookup` | Look up a channel-scoped message through KEYSTONE. `--channel-id`, `--message-id`. |
| `lookup-record` | Resolve a typed non-message record (checkpoints, events, exports, archive-members). |

**Projections:**

| Projection | Engine | Purpose |
|------------|--------|---------|
| `qihse.content.v1` | QIHSE | Full-text + semantic content (messages, users, media) |
| `qihse.graph.v1` | QIHSE | Entity graph + Cypher traversal |
| `qihse.errors.v1` | QIHSE | Structured error storage (operation failures) |
| `fts.messages.v1` | SQLite FTS5 | Full-text keyword search |
| `keystone.ids.v1` | KEYSTONE | O(1) ID anchor lookup (message_id, user_id, media_id) |
| `keystone.events.v1` | KEYSTONE | Telemetry event search |
| `keystone.media_manifest.v1` | KEYSTONE | Media manifest tracking |
| `keystone.checkpoints.v1` | KEYSTONE | Checkpoint tracking |
| `keystone.export_records.v1` | KEYSTONE | Export record tracking |
| `keystone.archive_members.v1` | KEYSTONE | Archive member tracking |

## Import

### import

Import external data into SPECTRA's native index for cross-indexing. All imported data flows through the durable outbox and projector pipeline.

**Native argparse command** (wired to `import_service.import_data`):

```bash
# Auto-detect format and import (native argparse)
./spectra import /path/to/old_archive.db

# Import with explicit format and limit
./spectra import messages.json --format json --limit 5000

# Import CSV
./spectra import data.csv --format csv

# Import Telegram Export History
./spectra import telegram_export.json --format telegram-export
```

After importing, run `./spectra index drain` to project the new records into QIHSE/KEYSTONE.

**Click-based commands** (additional features):
# Auto-detect format and import
./spectra import /path/to/old_archive.db

# Import JSON messages with a limit
./spectra import messages.json --format json --limit 5000

# Import CSV file
./spectra import data.csv --format csv

# Import Telegram Export History
./spectra import telegram_export.json --format telegram-export

# Import all files from a directory recursively
./spectra import /path/to/exports/ --batch

# Resume an interrupted import from the last checkpoint
./spectra import big_file.json --resume --limit 10000

# Validate data without writing to the database
./spectra import data.json --validate-only
```

**Options:**

| Option | Description |
|--------|-------------|
| `--format` | Source format: `auto` (default), `sqlite`, `json`, `csv`, `telegram-export`. |
| `--limit` | Maximum records to import. |
| `--validate-only` | Check data without writing to the database. |
| `--batch` | Import all data files from a directory recursively. |
| `--resume` | Resume an interrupted import from the last checkpoint. |
| `--output` | Override output format: `table`, `json`, `jsonl`, `csv`. |

**Supported formats:**

| Format | Description |
|--------|-------------|
| `sqlite` | tgarchive-compatible SQLite databases (messages, users, media, channel_messages tables). |
| `json` | JSON arrays or NDJSON line-delimited message objects. |
| `csv` | CSV files with message columns (id, content, user_id, type, date, ...). |
| `telegram-export` | Telegram's Export History JSON (converts from_id, text entity arrays, Unix timestamps). |
| `auto` | Auto-detect by file extension and content magic bytes. |

## Cross-Index

### cross-index

Cross-index an entity across all native index projections. Given a message_id, user_id, or media_id, resolves the full cross-index graph: ID anchors, content projections, FTS records, and related records.

```bash
# Cross-index a message
./spectra cross-index 42 --type message --output json

# Cross-index a user
./spectra cross-index 123 --type user

# Cross-index a media item
./spectra cross-index 999 --type media
```

**Options:**

| Option | Description |
|--------|-------------|
| `--type` | Entity type: `message` (default), `user`, `media`. |
| `--output` | Output format: `table`, `json`, `jsonl`, `csv`. |

**Output includes:**

- `keystone_anchors` — KEYSTONE ID anchor records for O(1) lookup
- `projection_records` — QIHSE content, FTS, and other projection records
- `relations` — Entity-specific relations:
  - Messages: replies, reply_to parent, same_user_messages
  - Users: user_info, activity stats, recent_messages, channels
  - Media: media_info, messages referencing the media

## Unified Search

### search

Unified search across KEYSTONE, QIHSE, and FTS5.

```bash
# Auto mode (tries KEYSTONE for numeric IDs, hybrid for text)
./spectra search "suspicious activity" --output json

# Semantic vector similarity search
./spectra search "suspicious activity" --mode semantic --limit 50

# Full-text keyword search
./spectra search "keyword exact" --mode fulltext

# KEYSTONE ID lookup (numeric query)
./spectra search 42 --mode keystone

# Filter by channel, user, and date range
./spectra search "query" --channel -100123 --user 456 --from 2024-01-01 --to 2024-12-31
```

**Options:**

| Option | Description |
|--------|-------------|
| `--mode` | Search mode: `auto` (default), `semantic`, `fulltext`, `keystone`. |
| `--limit` | Max results (default 20, max 1000). |
| `--channel` | Filter by channel ID. |
| `--user` | Filter by user ID. |
| `--from` | Start date (ISO format). |
| `--to` | End date (ISO format). |
| `--output` | Output format: `table`, `json`, `jsonl`, `csv`. |

**Modes:**

| Mode | Description |
|------|-------------|
| `auto` | Tries KEYSTONE for numeric IDs, hybrid search for text queries. |
| `semantic` | QIHSE vector similarity search. |
| `fulltext` | SQLite FTS5 keyword search. |
| `keystone` | KEYSTONE ID anchor lookup (for numeric queries). |

## Analysis

### analyze

Run local analysis over archived data.

```bash
# Timeline analysis — activity heatmap, top posters, hourly distribution
./spectra analyze timeline --output json
./spectra analyze timeline --channel -100123 --from 2024-01-01 --to 2024-12-31 --granularity week
./spectra analyze timeline --granularity hour --top-posters 20

# User correlation — activity, reply patterns, cross-channel flags
./spectra analyze user 123 --correlate --output json
./spectra analyze user 123

# Threat indicator detection
./spectra analyze indicators "suspicious pattern" --limit 100

# Temporal analysis
./spectra analyze temporal
```

**Subcommands:**

| Subcommand | Description |
|------|-------------|
| `timeline` | Analyze message timeline activity (heatmap, top posters, hourly distribution). `--channel`, `--from`, `--to`, `--granularity` (hour/day/week/month), `--top-posters`. |
| `user` | Analyze a user's activity and optionally correlate across channels. `--correlate`. |
| `indicators` | Detect threat indicators in matching local message text. `--limit`. |
| `temporal` | Analyze timestamp distribution for locally archived messages. |
| `steganography` | Detect hidden data in media files (LSB, EOF appended, EXIF anomalies, format mismatch). `--batch` for directory scan. |
| `impersonation` | Detect accounts impersonating someone else (username cloning, profile copying, homoglyphs). `--scan-all`, `--threshold`. |
| `bot-detection` | Detect bots pretending to be human (timing regularity, vocabulary diversity, content repetition, 24/7 activity). `--scan-all`. |
| `hourly-run` | Run hourly targeting analysis — detect if someone is being targeted (reply bombing, mention flooding, cross-channel coordination). `--target`, `--window`. |
| `account-correlation` | Report analysis capabilities. |
| `attribution` | Report analysis capabilities. |
| `forecast` | Report analysis capabilities. |
| `network` | Report analysis capabilities. |
| `score` | Report analysis capabilities. |

## Export

### export

Export local SPECTRA data.

```bash
# Export a table to CSV
./spectra export table messages --output-file messages.csv --format csv

# Export messages to JSON
./spectra export messages --output-file messages.json --format json --limit 1000
```

**Subcommands:**

| Subcommand | Description |
|------|-------------|
| `table` | Export any SQLite table. `--output-file`, `--format` (csv/json/jsonl), `--limit`. |
| `messages` | Export messages with optional channel filter. `--output-file`, `--format`, `--limit`, `--channel`. |

## Target Tracking

### target

Manage surveillance targets and build comprehensive dossiers. Given usernames or aliases, tracks a person closely across all channels — establishes contact networks, correlates timing against other posters, and detects coordinated targeting.

```bash
# Register a surveillance target with aliases
./spectra target add alice "alice_smith" "alice.tg" --label "Alice Smith — primary suspect"

# List all registered targets
./spectra target list

# Build a full dossier (identity resolution, contact network, timing, writing style)
./spectra target dossier alice "alice_smith"

# Get just the contact network
./spectra target network alice

# Correlate timing against other posters (detect shared operators)
./spectra target timing alice --window 120

# View surveillance alerts from hourly analysis
./spectra target alerts --all

# Acknowledge an alert
./spectra target ack 42

# Remove a target
./spectra target remove alice
```

**Subcommands:**

| Subcommand | Description |
|------------|-------------|
| `add` | Register a target with aliases. `--label`, `--notes`. |
| `list` | List all registered targets. |
| `remove` | Remove a target and its aliases. |
| `dossier` | Build comprehensive surveillance dossier. `--timing-window`, `--no-writing-style`. |
| `network` | Build contact network (who they interact with). |
| `timing` | Correlate posting times against other posters. `--window`. |
| `alerts` | View surveillance alerts. `--target`, `--all`, `--limit`. |
| `ack` | Acknowledge an alert. |

**Dossier includes:**
- Identity resolution (exact username, fuzzy username, display name matching)
- Activity summary (message count, first/last message)
- Channel footprint (all channels where target is active)
- Contact network (reply graph, interaction counts, bidirectional edges)
- Timing correlation (users who post simultaneously, shared operator detection)
- Writing style fingerprint (stylometric profile for cross-identity matching)
- Risk indicators (multi-channel presence, coordinated posting, 24/7 activity)

## File Search

### file-search

Search all chats and accounts for a particular file or the closest matching filename.

```bash
# Search by filename (fuzzy by default)
./spectra file-search "invoice.pdf"

# Exact match only
./spectra file-search "invoice_2024.pdf" --exact

# Search by file hash
./spectra file-search --hash sha256_abc123

# Filter by type, channel, or user
./spectra file-search "report" --type document --channel -100123 --user 456

# Adjust fuzzy threshold and limit
./spectra file-search "inv" --threshold 0.3 --limit 20
```

**Options:**

| Option | Description |
|--------|-------------|
| `--hash` | Search by file hash (SHA256/MD5) instead of filename. |
| `--fuzzy/--exact` | Use fuzzy or exact filename matching (default: fuzzy). |
| `--type` | Filter by media type (photo, video, document, etc.). |
| `--channel` | Filter by channel ID. |
| `--user` | Filter by uploading user ID. |
| `--limit` | Maximum results (default 50, max 1000). |
| `--threshold` | Minimum fuzzy match score 0-1 (default 0.5). |
| `--output` | Output format: `table`, `json`, `jsonl`, `csv`. |

**Results include:**
- Filename, title, type, URL, and checksum for each match
- Match score and match type (filename_exact, filename_fuzzy, hash_match, etc.)
- Message references (which messages reference this media, with user/date)
- Channel references (which channels contain this media)
- Extended metadata: size, mime_type, duration, dimensions, dc_id, posted_by (with username resolution)
- Nearby passwords: keyword patterns (`password: value`), quoted strings (`file.zip "pass"`), bare words near protected file extensions

## Async File Search

### file-search-async

Search all chats across all Telegram sessions for a file, distributing work via QIHSE coordination. Assigns different channel groups to each session to avoid overlap.

```bash
# Search across all sessions
./spectra file-search-async "invoice.pdf"

# Exact match, 8 concurrent workers
./spectra file-search-async "archive.zip" --exact --workers 8

# Search by hash
./spectra file-search-async --hash sha256_abc123

# Skip password scanning
./spectra file-search-async "report.pdf" --no-passwords

# Custom sessions directory
./spectra file-search-async "file.zip" --sessions-dir /path/to/sessions
```

**Coordination backends (tried in order):**
1. **QIHSE RESP** — QIHSE's Redis-compatible wire protocol (KV store with TTL, atomic SETNX claims)
2. **Redis** — standard Redis fallback if QIHSE RESP is not running
3. **SQLite** — local single-process fallback (no external dependencies)

**Options:**

| Option | Description |
|--------|-------------|
| `--hash` | Search by file hash instead of filename |
| `--fuzzy/--exact` | Fuzzy or exact filename matching (default: fuzzy) |
| `--threshold` | Minimum fuzzy match score 0-1 (default 0.5) |
| `--limit` | Maximum results (default 50, max 1000) |
| `--workers` | Max concurrent search workers (default 4, max 16) |
| `--sessions-dir` | Directory containing Telegram session files (default: sessions) |
| `--no-passwords` | Skip password field detection |
| `--output` | Output format: table, json, jsonl, csv |

**Output includes:**
- Aggregated results from all sessions (deduplicated by media_id)
- Per-session breakdown (channels searched, files found, passwords found, errors)
- Coordination mode used (qihse_resp, redis, sqlite_fallback)
- Total elapsed time

**How channel assignment works:**
1. Discovers all session files in the sessions directory
2. Reads all known channels from `account_channel_access` table
3. Uses QIHSE KV atomic SETNX to claim channels for sessions (round-robin, least-loaded first)
4. Each session searches only its assigned channels
5. Results are aggregated and deduplicated
