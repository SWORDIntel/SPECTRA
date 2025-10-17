# SPECTRA

**Spectrally-Processing Extraction, Crawling, & Tele-Reconnaissance Archive**
SPECTRA is an advanced framework for Telegram data collection, network discovery, and forensic-grade archiving with multi-account support, graph-based targeting, and robust OPSEC features.

<p align="center">
  <img src="SPECTRA.png" alt="SPECTRA" width="35%">
</p>

## Features

- 🔄 **Multi-account & API key rotation** with smart, persistent selection and failure detection
- 🕵️ **Proxy rotation** for OPSEC and anti-detection
- 🔎 **Network discovery** of connected groups and channels (with SQL audit trail)
- 📊 **Graph/network analysis** to identify high-value targets
- 📁 **Forensic archiving** with integrity checksums and sidecar metadata
- 📱 **Topic/thread support** for complete conversation capture
- 🗄️ **SQL database storage** for all discovered groups, relationships, and archive metadata
- ⚡ **Parallel processing** leveraging multiple accounts and proxies simultaneously
- 🖥️ **Modern TUI** (npyscreen) and CLI, both using the same modular backend
- ☁️ **Forwarding Mode:** Traverse a series of channels, discover related channels, and download text/archive files with specific rules, using a single API key.
- 🛡️ **Red team/OPSEC features**: account/proxy rotation, SQL audit trail, sidecar metadata, persistent stateS

## Documentation Index

- `docs/guides/` — Quick start, launcher usage, integration walkthroughs (`AGENTS.md`, `QUICK_START.md`, etc.).
- `docs/reference/` — Core architecture references, changelog, and database schema.
- `docs/design/` — UI mockups and interface planning assets.
- `docs/reports/` — Security summaries, integration reports, and executive updates.
- `docs/roadmap/` — Long-term initiatives and backlog material (e.g., deduplication plan).
- `docs/research/` — Strategic research and enhancement studies.

## Project Layout

- `tgarchive/` — Core Python package (CLI, TUI, backend services).
- `spectra_app/` — Orchestration, coordination, and GUI modules (importable package).
- `examples/` — Demonstrations and sample workflows (e.g., `parallel_example.py`).
- `scripts/` — Operational helpers (`spectra_launch.py`, `spectra_splash.py`, `system_validation_report.py`).
- `tests/` — System and integration tests (`test_*.py`, `integration_test_suite.py`).
- `deploy/` — Deployment assets such as `spectra-scheduler.service`.

## Installation

```bash
# Clone the repository
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install core dependencies (recommended - stable)
pip install telethon rich pillow pandas networkx matplotlib python-magic pyaes pyasn1 rsa feedgen lxml imagehash croniter npyscreen pysocks

# OR install all dependencies (may require system packages)
pip install -r requirements.txt

# Install package in development mode
pip install -e .
```

## System Status

**Current Version**: 2025-09-17 (Production Ready)
- ✅ **Core System**: Fully operational with all syntax errors resolved
- ✅ **CLI Interface**: 18 commands available and tested
- ✅ **Dependencies**: Core dependencies installed and verified
- ✅ **Architecture**: Professional-grade modular design validated

**Recent Fixes (2025-09-17)**:
- Fixed critical Git merge conflicts blocking system startup
- Resolved CLI parser conflicts and syntax errors
- Validated full system functionality and dependency chain
- See [CHANGELOG.md](docs/reference/CHANGELOG.md) for complete details

## Configuration

SPECTRA supports multi-account configuration with automatic account import from `gen_config.py` (TELESMASHER-compatible) and persistent SQL storage for all operations.

### Setting up Telegram API access

1. Visit https://my.telegram.org/apps to register your application
2. Create a config file or use the built-in account import:

```bash
# Import accounts from gen_config.py
python -m tgarchive accounts --import
```

## Usage

SPECTRA can be used in several modes:

### TUI Mode (Terminal User Interface)

```bash
# Launch the interactive TUI
python -m tgarchive
```

- The TUI supports all major workflows: discovery, network analysis, batch/parallel archiving, and account management.
- All TUI and CLI operations use the same modular, OPSEC-aware backend.

### Account Management

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

### Discovery Mode

```bash
# Discover groups from a seed entity
python -m tgarchive discover --seed @example_channel --depth 2

# Discover from multiple seeds in a file
python -m tgarchive discover --seeds-file seeds.txt --depth 2 --export discovered.txt

# Import existing scan data
python -m tgarchive discover --crawler-dir ./telegram-groups-crawler/
```

### Network Analysis

```bash
# Analyze network from crawler data
python -m tgarchive network --crawler-dir ./telegram-groups-crawler/ --plot

# Analyze network from SQL database
python -m tgarchive network --from-db --export priority_targets.json --top 50
```

### Archive Mode

```bash
# Archive a specific channel
default
python -m tgarchive archive --entity @example_channel
```

### Batch Operations

```bash
# Process multiple groups from file
python -m tgarchive batch --file groups.txt --delay 30

# Process high-priority groups from database
python -m tgarchive batch --from-db --limit 20 --min-priority 0.1
```

### Parallel Processing

SPECTRA supports parallel processing using multiple Telegram accounts and proxies simultaneously, with full SQL-backed state and OPSEC-aware account/proxy rotation:

```bash
# Run discovery in parallel across multiple accounts
python -m tgarchive parallel discover --seeds-file seeds.txt --depth 2 --max-workers 4

# Join multiple groups in parallel
python -m tgarchive parallel join --file groups.txt --max-workers 4

# Archive multiple entities in parallel
python -m tgarchive parallel archive --file entities.txt --max-workers 4

# Archive high-priority entities from DB in parallel
python -m tgarchive parallel archive --from-db --limit 20 --min-priority 0.1
```

You can also use the global parallel flag with standard commands:

```bash
# Run batch operations in parallel
python -m tgarchive batch --file groups.txt --parallel --max-workers 4

# Run discovery in parallel
python -m tgarchive discover --seeds-file seeds.txt --parallel --max-workers 4
```

### Forwarding Mode

This mode is designed for automated traversal and targeted downloading from an initial set of seed channels. It uses a single API key to explore channels, discover new ones through links in messages (up to a defined depth), and download specific file types (text and common archives) into an organized output directory.

**Command Structure:**
```bash
python -m tgarchive forward --channels-file <path_to_channels.txt> --output-dir <path_to_output_directory> [options]
```

**Arguments:**

*   `--channels-file PATH`: Required. Path to a text file containing the initial list of seed channel URLs or IDs (one per line).
*   `--output-dir PATH`: Required. Directory where downloaded files (in `text_files/` and `archive_files/` subfolders) and the `forward_download_log.csv` will be stored.
*   `--max-depth INT`: Optional. Maximum depth to follow channel links during discovery. Default is 2.
*   `--min-files-gateway INT`: Optional. Minimum number of files a channel should ideally have to be considered a 'gateway' for focused downloading (Note: current implementation downloads from all accessible discovered channels; this option is for future refinement). Default is 100.

**API Key Usage:**

Forwarding mode is designed to use a single API key (specifically, the first account configured in your `spectra_config.json` or imported from `gen_config.py`) for all its operations. This is to avoid potentially joining the same channel with multiple accounts, which might be undesirable for certain operational goals.

**Output Structure:**

In the specified output directory, you will find:

*   `text_files/`: Contains downloaded plain text files.
*   `archive_files/`: Contains downloaded archive files (e.g., .zip, .rar) along with their metadata in `.json` sidecar files (e.g., `example.zip.json`).
*   `forward_download_log.csv`: A CSV log detailing every downloaded file, its source channel, message ID, timestamp, and other metadata.

**Running Long Forwarding Sessions:**

For extended forwarding mode operations, it is highly recommended to use a terminal multiplexer like `screen` or `tmux` to ensure the process continues running even if your connection drops.

Example using `screen`:
1. Start a new screen session: `screen -S spectra_forward_session`
2. Run the command: `python -m tgarchive forward --channels-file your_seeds.txt --output-dir ./forward_output`
3. Detach from the session: Press `Ctrl+A` then `D`.
4. To reattach later: `screen -r spectra_forward_session`

SPECTRA will not install `screen` or `tmux` for you. Please install them using your system's package manager if needed (e.g., `sudo apt install screen`).

---

## Enhanced Forwarding & Forwarding Operations

SPECTRA now includes advanced capabilities for message deduplication during forwarding and an automated account invitation system for channels discovered in Forwarding Mode.

### Deduplication Forwarding

To prevent redundant information and save on API calls, SPECTRA's forwarding mechanism can now detect and skip messages that have already been processed and forwarded.

**Overview:**

*   When enabled, SPECTRA computes a unique hash for each message's content (text and media attributes) before forwarding.
*   These hashes are stored in the local database (`spectra.sqlite3` in a table named `forwarded_messages`).
*   If a message's hash is already found in the database or an in-memory cache for the current session, it's considered a duplicate and will not be forwarded to the primary destination.
*   Unique messages can optionally be routed to a secondary, specified channel, ensuring this channel only receives content not seen before.

**Configuration (`spectra_config.json`):**

Add or modify the `forwarding` section in your `spectra_config.json`:

```json
{
  "forwarding": {
    "enable_deduplication": true,
    "secondary_unique_destination": "@your_unique_content_channel"
  }
  // ... other forwarding settings ...
}
```

*   `enable_deduplication` (boolean): Set to `true` (default) to enable duplicate detection, `false` to disable.
*   `secondary_unique_destination` (string | null): Optional. The username or ID of a channel where unique messages (those not previously forwarded) will be sent. If `null` or not provided, unique messages are only sent to the primary destination.

**CLI Flags for `tgarchive forward`:**

*   `--enable-deduplication` / `--disable-deduplication`: Overrides the `enable_deduplication` setting from `spectra_config.json` for the current command.
    *   Example: `python -m tgarchive forward --origin @source --destination @main_dest --disable-deduplication`
*   `--secondary-unique-destination <channel_id_or_username>`: Specifies the secondary destination for unique messages, overriding the config for the current command.
    *   Example: `python -m tgarchive forward --origin @source --destination @main_dest --secondary-unique-destination @only_uniques_here`

**Usage Example:**

To forward messages from `@news_source` to `@my_archive`, skip duplicates, and send unique messages also to `@special_uniques`:

1.  Ensure your `spectra_config.json` has:
    ```json
    "forwarding": {
      "enable_deduplication": true,
      "secondary_unique_destination": "@special_uniques"
    }
    ```
2.  Run the command:
    ```bash
    python -m tgarchive forward --origin @news_source --destination @my_archive
    ```
    Or, using CLI overrides:
    ```bash
    python -m tgarchive forward --origin @news_source --destination @my_archive --enable-deduplication --secondary-unique-destination @special_uniques
    ```

### Forwarding Mode: Automated Account Invitations

When operating in Forwarding Mode, SPECTRA can now automatically invite other configured accounts to join newly discovered and accessible public channels. This helps distribute channel membership across your available accounts.

**Overview:**

*   After the primary Forwarding Mode account successfully accesses/joins a new channel, that channel is added to an invitation queue.
*   Other accounts configured in `spectra_config.json` (excluding the primary Forwarding Mode account) will be gradually invited to join these queued channels.
*   Invitations are processed with randomized delays to simulate natural user behavior and respect Telegram's rate limits.
*   The system tracks successful and failed invitations in a state file (`invitation_state.json` in your forward output directory) to avoid re-processing and to allow resumability.

**Configuration (`spectra_config.json`):**

Add or modify the `forwarding` section in your `spectra_config.json`:

```json
{
  "forwarding": {
    "auto_invite_accounts": true,
    "invitation_delays": {
      "min_seconds": 120,
      "max_seconds": 600,
      "variance": 0.3
    }
  }
  // ... other forwarding settings ...
}
```

*   `auto_invite_accounts` (boolean): Set to `true` (default) to enable this feature, `false` to disable.
*   `invitation_delays`: An object defining the timing for invitations:
    *   `min_seconds` (integer): Minimum base delay before an invitation attempt.
    *   `max_seconds` (integer): Maximum base delay.
    *   `variance` (float, 0.0 to 1.0): Percentage of random variance applied to the base delay. For example, 0.3 means +/- 30%.

**CLI Flags for `tgarchive forward`:**

*   `--enable-auto-invites` / `--disable-auto-invites`: Overrides the `auto_invite_accounts` setting from `spectra_config.json` for the current forward session.
    *   Example: `python -m tgarchive forward --channels-file seeds.txt --output-dir ./forward_out --disable-auto-invites`

**Usage Example:**

To run Forwarding Mode, discover channels, and have your other accounts automatically invited:

1.  Ensure your `spectra_config.json` has multiple accounts configured and the `forwarding` section is set up (or use defaults):
    ```json
    "accounts": [
      {"session_name": "main_forward_acc", "api_id": 123, "api_hash": "abc"},
      {"session_name": "invitee_acc1", "api_id": 456, "api_hash": "def"},
      {"session_name": "invitee_acc2", "api_id": 789, "api_hash": "ghi"}
    ],
    "forwarding": {
      "auto_invite_accounts": true
    }
    ```
2.  Run the Forwarding Mode command (the first account, `main_forward_acc`, will be used for discovery):
    ```bash
    python -m tgarchive forward --channels-file initial_seeds.txt --output-dir ./my_forward_data
    ```
    As `main_forward_acc` discovers and joins new channels, `invitee_acc1` and `invitee_acc2` will be queued and then invited to join them after randomized delays.

---

## Message Forwarding Features

SPECTRA includes powerful features for forwarding messages with attachments from origin channels/chats to a specified destination, or even to the "Saved Messages" of multiple configured accounts. This can be useful for consolidating information, creating backups, or distributing content.

### Forwarding Modes

1.  **Selective Forwarding:** Forward messages from a specific origin to a specific destination.
    ```bash
    python -m tgarchive forward --origin <origin_id_or_username> --destination <destination_id_or_username>
    ```

2.  **Total Forward Mode:** Forward messages from all channels accessible by your configured accounts (as listed in the `account_channel_access` table) to a specific destination. This mode requires the channel access table to be populated first.
    ```bash
    python -m tgarchive forward --total-mode [--destination <destination_id_or_username>]
    ```
    To populate the `account_channel_access` table, run:
    ```bash
    python -m tgarchive channels --update-access
    ```

### Forwarding Command Details (`tgarchive forward`)

The main command for forwarding is `python -m tgarchive forward` with the following options:

*   `--origin <id_or_username>`: Specifies the source channel or chat from which to forward messages. This is required unless `--total-mode` is used.
*   `--destination <id_or_username>`: Specifies the target channel or chat to which messages will be forwarded. If not provided, SPECTRA will use the `default_forwarding_destination_id` set in your `spectra_config.json` file.
*   `--account <phone_or_session_name>`: Specifies which configured Telegram account to use for the forwarding operation. If not provided, the first account in your configuration is typically used. For "Total Forward Mode", this account is used for orchestration, while individual channel forwarding uses an account known to have access to that specific channel (from the `account_channel_access` table).
*   `--total-mode`: Enables "Total Forward Mode". When this flag is used, the `--origin` argument is ignored, and SPECTRA will attempt to forward messages from all channels recorded in the `account_channel_access` database table.
*   `--forward-to-all-saved`: When enabled, messages successfully forwarded to the main destination will *also* be forwarded to the "Saved Messages" of *every account* configured in `spectra_config.json`. This can be useful for creating broad personal backups but will significantly increase API calls and data redundancy. Use with caution.
*   `--prepend-origin-info`: If enabled, and if not using topic-based forwarding (see below), information about the original channel (e.g., "[Forwarded from OriginalChannelName (ID: 12345)]") will be prepended to the text of the forwarded message. This helps in identifying the source of messages when they are consolidated into a general channel.

### Related Configuration and Utility Commands

*   **Setting Default Destination:**
    ```bash
    python -m tgarchive config --set-forward-dest <destination_id_or_username>
    ```
    This command updates the `default_forwarding_destination_id` in your `spectra_config.json`.

*   **Viewing Default Destination:**
    ```bash
    python -m tgarchive config --view-forward-dest
    ```

*   **Updating Channel Access Data (for Total Mode):**
    ```bash
    python -m tgarchive channels --update-access
    ```
    This command populates the `account_channel_access` table in the database by iterating through all your configured accounts and listing the channels each can access. This table is crucial for the `--total-mode` forwarding feature.

### Configuration for Forwarding

*   **`default_forwarding_destination_id`**: Located in `spectra_config.json`, this key (added manually or via the `config --set-forward-dest` command) allows you to set a global default destination for forwarding operations, so you don't have to specify `--destination` every time.
*   **Supergroup Topic Sorting (Conceptual):**
    Telegram's "Topics" feature in supergroups allows for organized discussions. SPECTRA's forwarding can conceptually support sending messages into specific topics. This is typically done by forwarding a message as a *reply* to the message that represents the topic's creation or its main "general" topic message.
    If you manually identify the message ID for a specific topic in the destination supergroup, this ID could be used (currently via code modification or future enhancement as `destination_topic_id` in the `AttachmentForwarder`) with the `reply_to` parameter in Telegram's API when forwarding.
    Currently, SPECTRA does **not** automatically create or manage topics by name due to limitations with user accounts (topic creation/management often requires bot privileges or specific admin rights).
    The `--prepend-origin-info` flag is the primary method for distinguishing messages from different origins when forwarded to a common, non-topic-based channel.

### "Forward to All Saved Messages" Feature

Enabling `--forward-to-all-saved` provides a way to create a distributed backup or personal archive of forwarded content across all your configured Telegram accounts. Each message successfully forwarded to the main destination will also be sent to the "Saved Messages" chat of each account.

**Implications:**
*   **Increased API Usage:** This feature will make significantly more API calls (one forward per account for each original message). Be mindful of Telegram's rate limits. The system has built-in handling for `FloodWaitError` (rate limit exceeded) and will pause as instructed by Telegram, but excessive use could still lead to temporary restrictions on accounts.
*   **Data Redundancy:** You will have multiple copies of the forwarded messages across your accounts.
*   **Sequential Operation:** Forwarding to each account's "Saved Messages" happens sequentially for each original message to manage client connections and reduce simultaneous API load from this specific feature.

### Database and `account_channel_access` Table

The "Total Forward Mode" (`--total-mode`) relies on the `account_channel_access` table in the SPECTRA database. This table stores a record of which channels are accessible by which of your configured accounts, including their names and access hashes. It is populated by the `tgarchive channels --update-access` command.

For more details on the database schema, please refer to the [DATABASE_SCHEMA.md](docs/reference/DATABASE_SCHEMA.md) file.

---

## Shunt Mode (File Transfer)

Shunt Mode is designed to transfer all media files from one Telegram channel (source) to another (destination) with advanced deduplication and file grouping capabilities. This is useful for consolidating archives, moving collections, or reorganizing media across channels.

**Key Features:**

*   **Deduplication:** Ensures that files already present in the destination (based on content hash) or previously shunted are not transferred again. It uses the same `forwarded_messages` table as the general forwarding feature.
*   **File Grouping:** Attempts to identify and transfer related files as groups. This helps maintain the integrity of multi-part archives or collections of images/videos sent together.
    *   **Strategies:**
        *   `none`: No grouping; files are transferred individually.
        *   `filename`: Groups files based on common base names and sequential numbering patterns (e.g., `archive_part1.rar`, `archive_part2.rar` or `image_001.jpg`, `image_002.jpg`).
        *   `time`: Groups files sent by the same user within a configurable time window.

**CLI Command:**

The Shunt Mode is activated using specific arguments with the main `tgarchive` command:

```bash
python -m tgarchive --shunt-from <source_id_or_username> --shunt-to <destination_id_or_username> [options]
```

**CLI Arguments:**

*   `--shunt-from <id_or_username>`: **Required.** The source channel/chat ID or username from which files will be shunted.
*   `--shunt-to <id_or_username>`: **Required.** The destination channel/chat ID or username to which files will be transferred.
*   `--shunt-account <phone_or_session_name>`: Optional. Specifies which configured Telegram account to use for the shunting operation. If not provided, the first available active account from your configuration is typically used.

**Configuration (`spectra_config.json`):**

File grouping behavior for Shunt Mode can be configured in your `spectra_config.json` file under the `grouping` key:

```json
{
  // ... other configurations ...
  "grouping": {
    "strategy": "filename",  // "none", "filename", or "time"
    "time_window_seconds": 300 // Time window in seconds for 'time' strategy (e.g., 300 for 5 minutes)
  },
  // ... other configurations ...
}
```

*   `strategy` (string): Defines the grouping method.
    *   `"none"` (default): No grouping.
    *   `"filename"`: Groups based on filename patterns.
    *   `"time"`: Groups based on time proximity and sender.
*   `time_window_seconds` (integer): Relevant only for the `"time"` strategy. Specifies the maximum time difference (in seconds) between messages from the same sender to be considered part of the same group.

**Usage Example:**

To shunt all files from `@old_archive_channel` to `@new_consolidated_archive`, using filename-based grouping, and specifying the account `my_worker_account`:

1.  Ensure your `spectra_config.json` has the desired grouping strategy (or rely on defaults):
    ```json
    "grouping": {
      "strategy": "filename"
    }
    ```
2.  Run the command:
    ```bash
    python -m tgarchive --shunt-from @old_archive_channel --shunt-to @new_consolidated_archive --shunt-account my_worker_account
    ```

Files will be fetched from the source, grouped according to the strategy, checked for duplicates against the destination (via the shared deduplication database), and then unique files/groups will be forwarded.

---

## Parallel Processing Example Script

A ready-to-use example script is provided to demonstrate parallel discovery, join, and archive operations:

**`examples/parallel_example.py`**

```bash
# Run parallel discovery, join, and archive from a list of seeds
python examples/parallel_example.py --seeds-file seeds.txt --max-workers 4 --discover --join --archive --export-file discovered.txt
```

- Supports importing accounts from `gen_config.py` automatically
- All operations are SQL-backed and use persistent account/proxy rotation
- Exports discovered groups to a file if requested
- See the script for more advanced usage and options

---

## Advanced OPSEC & Red Team Features

- **Account & API key rotation**: Smart, persistent, and SQL-audited
- **Proxy rotation**: Supports rotating proxies for every operation
- **SQL audit trail**: All group discovery, joins, and archiving are logged in the database
- **Sidecar metadata**: Forensic metadata and integrity checksums for all archives
- **Persistent state**: All operations are resumable and stateful
- **Modular backend**: All TUI/CLI operations use the same importable modules for maximum reusability
- **Detection/OPSEC notes**: Designed for red team and forensic use, with anti-detection and audit features

---

## Integration & Architecture

- **`SPECTRA/tgarchive/discovery.py`**: Integration point for group crawling, network analysis, parallel archiving, and SQL-backed state
- **`SPECTRA/tgarchive/__main__.py`**: Unified CLI/TUI entry point
- **`examples/parallel_example.py`**: Example for parallel, multi-account operations
- All modules are importable and can be reused in your own scripts or pipelines

---

## Database Integration

SPECTRA stores all discovery and archiving data in a SQLite database:

- Discovered groups with metadata and priority scores
- Group relationships and network graph data
- Account usage statistics and health metrics
- Archive status tracking

You can specify a custom database path with `--db path/to/database.db`

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
