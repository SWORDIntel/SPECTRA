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

## ⚡ Quick Start

**One-command setup and launch:**

```bash
# Clone and enter directory
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA

# Bootstrap (automatic setup + launch)
./bootstrap
# OR use make
make bootstrap

# On subsequent runs, just launch the TUI
make run
# OR
python -m tgarchive
```

The TUI (Terminal User Interface) is the primary way to interact with SPECTRA. It provides an intuitive, menu-driven interface for all operations including archiving, discovery, network analysis, and forwarding.

For more commands: `make help`

---

## Documentation Index

- `docs/guides/` — Quick start, launcher usage, integration walkthroughs (`AGENTS.md`, `QUICK_START.md`, etc.).
- `docs/reference/` — Core architecture references, changelog, and database schema.
- `docs/design/` — UI mockups and interface planning assets.
- `docs/reports/` — Security summaries, integration reports, and executive updates.
- `docs/roadmap/` — Long-term initiatives and backlog material (e.g., deduplication plan).
- `docs/research/` — Strategic research and enhancement studies.

## Project Layout

```
SPECTRA/
├── scripts/          ← Executable scripts (install, launch, setup)
├── docs/             ← Documentation and guides
├── data/             ← Runtime data (not tracked in git)
├── src/              ← Archived/deprecated code
├── tgarchive/        ← Main Python package
│   ├── core/         ← Core business logic
│   ├── ui/           ← User interfaces (TUI)
│   ├── services/     ← Background services
│   ├── utils/        ← Utility functions
│   ├── db/           ← Database layer
│   ├── forwarding/   ← Message forwarding
│   └── osint/        ← Intelligence gathering
├── tests/            ← Test suite
├── examples/         ← Example scripts
├── bootstrap         ← Auto-setup entry point (recommended)
├── Makefile          ← Common commands (make help)
└── setup.py          ← Python package setup
```

For detailed structure explanation, see [PROJECT_STRUCTURE.md](docs/reference/PROJECT_STRUCTURE.md)

## Installation

```bash
# Clone the repository
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install core dependencies (recommended - stable)
pip install telethon rich pillow pandas networkx matplotlib python-magic pyaes pyasn1 feedgen lxml imagehash croniter npyscreen pysocks

# OR install all dependencies (may require system packages)
pip install -r requirements.txt

# Install package in development mode
pip install -e .
```

## System Status

**Current Version**: 2025-01-XX (Production Ready)
- ✅ **Core System**: Fully operational with all syntax errors resolved
- ✅ **CLI Interface**: 18 commands available and tested
- ✅ **Dependencies**: Core dependencies installed and verified
- ✅ **Architecture**: Professional-grade modular design validated
- ✅ **CNSA 2.0 Compliance**: All cryptographic operations updated

**Recent Enhancements (2025-01-XX)**:
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

SPECTRA provides a powerful Terminal User Interface (TUI) as the primary way to interact with the system. The TUI offers an intuitive, menu-driven interface for all major operations.

### TUI Mode (Terminal User Interface) - Primary Interface

The TUI is the recommended way to use SPECTRA. It provides a comprehensive, interactive interface for all operations.

#### Launching the TUI

```bash
# Launch the interactive TUI
python -m tgarchive

# Or use the launcher script
./spectra.sh

# Or use make
make run
```

#### Main Menu Overview

When you launch SPECTRA, you'll see the main menu with the following options:

1. **Dashboard** - View system status, account health, and operation statistics
2. **Archive Channel/Group** - Archive messages and media from a specific channel or group
3. **Discover Groups** - Discover new groups and channels from seed entities
4. **Network Analysis** - Analyze group relationships and identify high-value targets
5. **Forwarding Utilities** - Forward messages between channels with deduplication
6. **OSINT Utilities** - Intelligence gathering and analysis tools
7. **Group Mirroring** - Mirror groups and channels
8. **Account Management** - Manage Telegram accounts and API keys
9. **Settings (VPS Config)** - Configure VPS and system settings
10. **Forwarding & Deduplication Settings** - Configure forwarding behavior
11. **Download Users** - Download user information and profiles
12. **Help & About** - Access help documentation and system information
13. **Exit** - Exit the application

#### Navigation

**Keyboard Shortcuts:**
- **Number keys (1-9)**: Jump directly to menu items from the main menu
- **Ctrl+D**: Open Dashboard
- **Ctrl+A**: Open Archive menu
- **Ctrl+F**: Open Forwarding menu
- **Ctrl+H**: Open Help
- **Ctrl+K**: Quick access menu (command palette)
- **Ctrl+Q**: Quit application
- **Esc**: Go back to previous menu
- **Tab / Shift+Tab**: Navigate between fields

**Quick Actions:**
- `qa` = Archive
- `qd` = Dashboard
- `qf` = Forwarding
- `qs` = Search
- `qg` = Graph/Network Analysis
- `qm` = Main Menu

#### Common Workflows

**Archiving a Channel:**
1. From main menu, select **2. Archive Channel/Group** (or press `2`)
2. Enter the channel username (e.g., `@example_channel`) or ID
3. Configure archive options (date range, media types, etc.)
4. Start the archive operation
5. Monitor progress in real-time

**Discovering New Groups:**
1. From main menu, select **3. Discover Groups** (or press `3`)
2. Enter seed channel(s) or load from file
3. Set discovery depth (how many hops to explore)
4. Start discovery operation
5. View discovered groups in the database

**Network Analysis:**
1. From main menu, select **4. Network Analysis** (or press `4`)
2. Choose data source (database or crawler directory)
3. Configure analysis parameters
4. View network graph and priority targets
5. Export results for further analysis

**Forwarding Messages:**
1. From main menu, select **5. Forwarding Utilities** (or press `5`)
2. Choose forwarding mode (selective, total, or forwarding mode)
3. Configure source and destination channels
4. Set deduplication options
5. Start forwarding operation

**Account Management:**
1. From main menu, select **8. Account Management** (or press `8`)
2. View account status and health
3. Import accounts from `gen_config.py`
4. Test account connectivity
5. Manage account rotation settings

#### Dashboard Features

The Dashboard (option 1) provides:
- **System Status**: Account availability, database status, active operations
- **Account Health**: Status of all configured Telegram accounts
- **Operation Statistics**: Recent operations, success rates, error counts
- **Quick Actions**: Fast access to common operations
- **Real-time Updates**: Live status updates during operations

#### Tips for Using the TUI

- **Use keyboard shortcuts** for faster navigation
- **Check the Dashboard** regularly to monitor system health
- **Use the Help menu** (Ctrl+H) for context-sensitive help
- **All operations are resumable** - you can safely exit and resume later
- **Progress indicators** show real-time status for long operations
- **Error messages** provide clear guidance on how to resolve issues

#### TUI vs CLI

The TUI provides the same functionality as the CLI but with a more user-friendly interface. All operations performed in the TUI use the same backend modules, ensuring consistency and reliability. For automation and scripting, you can still use the CLI commands (see below).

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
*   `--copy-into-destination`: Re-posts messages using the signed-in account so they appear native in the destination (no `Forwarded from` banner). Omit this flag to preserve the original sender/forward headers from the origin.
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

### Command Line Interface (CLI) - Advanced Usage

For automation, scripting, and advanced use cases, SPECTRA also provides a comprehensive CLI. Most operations available in the TUI can also be performed via CLI commands.

#### Account Management

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

#### Discovery Mode

```bash
# Discover groups from a seed entity
python -m tgarchive discover --seed @example_channel --depth 2

# Discover from multiple seeds in a file
python -m tgarchive discover --seeds-file seeds.txt --depth 2 --export discovered.txt

# Import existing scan data
python -m tgarchive discover --crawler-dir ./telegram-groups-crawler/
```

#### Network Analysis

```bash
# Analyze network from crawler data
python -m tgarchive network --crawler-dir ./telegram-groups-crawler/ --plot

# Analyze network from SQL database
python -m tgarchive network --from-db --export priority_targets.json --top 50
```

#### Archive Mode

```bash
# Archive a specific channel
python -m tgarchive archive --entity @example_channel
```

#### Batch Operations

```bash
# Process multiple groups from file
python -m tgarchive batch --file groups.txt --delay 30

# Process high-priority groups from database
python -m tgarchive batch --from-db --limit 20 --min-priority 0.1
```

#### Parallel Processing

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

#### Shunt Mode (File Transfer)

Shunt Mode transfers all media files from one Telegram channel to another with advanced deduplication and file grouping. This is useful for consolidating archives, moving collections, or reorganizing media across channels.

**Quick Start:**
```bash
python -m tgarchive --shunt-from @source_channel --shunt-to @destination_channel
```

For detailed Shunt Mode documentation, including configuration options, grouping strategies, and advanced usage, see the [Shunt Mode Guide](docs/guides/SHUNT_MODE_GUIDE.md).

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

## AI/ML Intelligence & Threat Scoring

SPECTRA includes advanced AI/ML capabilities for intelligence analysis:

### Threat Scoring System

Automatically identifies and scores threat actors on a 1-10 scale based on message content, behavior patterns, and network associations:

```bash
# Run the threat scoring demo
python examples/threat_scoring_demo.py
```

**Features:**
- **Multi-factor Scoring**: Combines keyword detection (30%), pattern matching (25%), behavioral analysis (20%), network associations (15%), and temporal patterns (10%)
- **Threat Classifications**: Harmless (1-2), Low Risk (3-4), Medium (5-6), High Risk (7-8), Critical/Nation-State (9-10)
- **Network Tracking**: "Guilt by association" scoring and community detection
- **Mermaid Visualizations**: Color-coded network graphs, community clusters, and activity timelines
- **Intelligence Reports**: Executive summaries with top threat actors and recommended actions

**Detection Capabilities:**
- 100+ critical security keywords (zero-day, APT groups, ransomware, etc.)
- Pattern matching for CVEs, crypto addresses, malware hashes, Tor addresses, IPs
- Behavioral flags for OPSEC awareness, code sharing, coordinated activity
- Network relationship tracking with 6 interaction types

**Usage:**
```python
from tgarchive.threat import (
    ThreatIndicatorDetector,
    ThreatScorer,
    ThreatNetworkTracker,
    MermaidGenerator
)

# Analyze messages for threat indicators
detector = ThreatIndicatorDetector()
indicators = detector.analyze_message(message_text, message_id)

# Calculate threat scores
threat_score, confidence = ThreatScorer.calculate_threat_score(
    keyword_indicators=indicators,
    # ... other parameters
)

# Generate network visualization
mermaid_graph = MermaidGenerator.generate_network_graph(
    profiles=threat_profiles,
    network_tracker=network_tracker
)
```

**Documentation:**
- **Usage Guide**: See `docs/THREAT_SCORING_USAGE.md`
- **System Architecture**: See `docs/THREAT_SCORING_SYSTEM_PLAN.md`
- **Demo Script**: See `examples/threat_scoring_demo.py`

### ⚡ High-Performance Search Algorithms

SPECTRA includes optimized search algorithms for improved performance. These algorithms are automatically used when available.

**Note:** NOT_STISLA and QIHSE are third-party libraries with specific licensing requirements. See the [Third-Party Licenses](#third-party-licenses) section below for details.

### Entity Extraction & Knowledge Graphs

Named Entity Recognition and relationship mapping:

```python
from tgarchive.ai import NERModel, KnowledgeGraph

# Extract entities
ner = NERModel(model_name="en_core_web_lg")
entities = ner.extract_entities(text)

# Build knowledge graph
kg = KnowledgeGraph()
kg.add_entities_from_messages(messages)
influential = kg.pagerank(top_k=100)
```

**AI/ML Documentation:**
- **Full Feature Plan**: See `docs/AI_INTELLIGENCE_ENHANCEMENTS.md`
- **Requirements**: Install with `pip install -r requirements-ai.txt`
- **Demo**: See `examples/ai_features_demo.py`

---

## Advanced Intelligence Features

SPECTRA includes enterprise-grade enhancements for high-scale intelligence operations:

### 🔍 Vector Database Integration

Scale to billions of messages with high-dimensional similarity search:

```bash
# Install vector database support
pip install -r requirements-advanced.txt
```

**Features:**
- **Qdrant/ChromaDB Integration**: Production-grade vector storage (384-2048D embeddings)
- **Dual-Database Architecture**: SQLite for metadata + Vector DB for semantic search
- **Semantic Search**: Find similar messages across millions of documents
- **Actor Similarity**: Identify actors with similar behavioral patterns
- **Anomaly Detection**: Flag messages that don't match normal patterns
- **Scalability**: Handle billions of vectors with quantization and sharding

**Usage:**
```python
from tgarchive.db.vector_store import VectorStoreManager, VectorStoreConfig

# Initialize vector store
config = VectorStoreConfig(
    backend="qdrant",  # or "chromadb", "numpy"
    vector_size=384,
    distance_metric="cosine"
)

store = VectorStoreManager(config)

# Index messages with embeddings
store.index_message(
    message_id=123,
    embedding=message_embedding,
    metadata={"user_id": 1001, "threat_score": 8.5}
)

# Semantic search
results = store.semantic_search(
    query_embedding=query_emb,
    top_k=10,
    filters={"threat_score": {"gte": 7.0}}
)
```

### 🛡️ CNSA 2.0 Quantum-Resistant Cryptography

Post-quantum cryptography for future-proof security:

**Standards Compliance:**
- **ML-KEM-1024** (FIPS 203): Quantum-resistant key encapsulation
- **ML-DSA-87** (FIPS 204): Quantum-resistant digital signatures
- **SHA-384** (FIPS 180-4): 384-bit secure hashing
- **NSA CNSA 2.0 Compliant**: Future-proof against quantum attacks

**Features:**
- Hybrid encryption (ML-KEM-1024 + AES-256-GCM)
- Digital signatures for threat reports (ML-DSA-87)
- Secure key management with encrypted keystore
- Archive encryption with quantum resistance
- Database integrity verification

**Usage:**
```python
from tgarchive.crypto import CNSA20CryptoManager, CNSAKeyManager

# Initialize crypto manager
crypto = CNSA20CryptoManager()

# Generate quantum-resistant keys
kem_keys = crypto.generate_kem_keypair()
sig_keys = crypto.generate_signature_keypair()

# Encrypt data
encrypted = crypto.encrypt_data(plaintext, recipient_public_key)

# Sign threat reports
signed_report = crypto.create_signed_package(
    report_data,
    signing_key,
    signer_id="analyst_001"
)

# Verify signature
is_valid = crypto.verify_signed_package(signed_report, public_key)

# Secure key management
key_manager = CNSAKeyManager("./keys/keystore.enc")
key_manager.create_keystore(password="SecurePassword")
```

### ⏱️ Temporal Analysis & Prediction

Analyze time-based patterns in threat actor behavior:

**Capabilities:**
- Activity timeline analysis with burst detection
- Timezone inference from peak activity hours
- Sleep pattern analysis for geolocation
- Campaign periodicity detection
- Predictive activity forecasting
- Coordinated campaign detection

**Usage:**
```python
from tgarchive.threat.temporal import TemporalAnalyzer

analyzer = TemporalAnalyzer()

# Analyze activity patterns
patterns = analyzer.analyze_activity_patterns(messages)
# Returns: peak_hours, peak_days, inferred_timezone, burst_periods, regularity_score

# Detect coordinated campaigns
campaigns = analyzer.detect_coordinated_campaigns(
    actor_messages,
    time_window_minutes=30,
    min_actors=3
)

# Predict next activity
prediction = analyzer.predict_next_activity(messages, forecast_hours=24)
# Returns: likely_active_hours, probability_by_hour, confidence
```

### 🎭 Attribution Engine

Cross-platform identity correlation and behavioral analysis:

**Features:**
- Writing style analysis (stylometry)
- Vocabulary richness and sentence complexity
- Tool/technique fingerprinting (Metasploit, Cobalt Strike, etc.)
- Operational pattern matching (recon → exploit → post-exploit)
- AI-generated content detection
- Cross-account correlation
- Language proficiency assessment

**Usage:**
```python
from tgarchive.threat.attribution import AttributionEngine

engine = AttributionEngine()

# Analyze writing style
profile = engine.analyze_writing_style(messages)
# Returns: vocabulary_size, avg_sentence_length, technical_density, language

# Find similar actors (potential sock puppets)
similar = engine.find_similar_actors_by_style(
    target_profile,
    candidate_profiles,
    threshold=0.85
)

# Detect tool fingerprints
tools = engine.detect_tool_fingerprints(messages)
# Returns: {"Metasploit": [...matches...], "Cobalt Strike": [...]}

# Detect AI-generated content
ai_analysis = engine.detect_ai_generated_content(messages)
# Returns: ai_likelihood, indicators, confidence

# Correlate accounts
account_clusters = engine.correlate_accounts(profiles, min_similarity=0.85)
# Returns: [[1001, 1005, 1009], [2003, 2015]]  # Likely same actor
```

### 📊 Advanced Features Demo

```bash
# Run comprehensive demo of all advanced features
python examples/advanced_features_demo.py
```

**Demonstrates:**
- Vector database operations (indexing, searching, clustering)
- Post-quantum encryption and digital signatures
- Temporal pattern analysis and prediction
- Attribution analysis and tool fingerprinting
- AI content detection

### 📚 Advanced Features Documentation

- **Architecture & Planning**: `docs/ADVANCED_ENHANCEMENTS_PLAN.md`
  - Vector database evaluation (Qdrant vs ChromaDB vs Milvus)
  - CNSA 2.0 implementation strategy
  - Enhanced threat tracking roadmap
- **Requirements**: `requirements-advanced.txt`
- **Demo Script**: `examples/advanced_features_demo.py`

### ⚡ INT8 Neural Acceleration (Planned)

**Leverage 130 TOPS INT8 compute for real-time intelligence at scale:**

**Capabilities:**
- **10,000+ messages/second** continuous psycho-forensic analysis
- **<10ms** actor correlation across 10 million profiles
- **Real-time radicalization detection** with sub-second alerting
- **GPU/NPU acceleration** (NVIDIA/Intel/AMD support)

**Psycho-Forensic Linguistics:**
- Big Five personality profiling (OCEAN model)
- Dark Triad detection (Narcissism, Machiavellianism, Psychopathy)
- Deception detection (hedging, distancing, verbosity)
- Radicalization stage tracking (0-5 scale progression)
- Emotional state analysis (anger, fear, confidence)

**Hardware-Accelerated Operations:**
- INT8 quantization (4x throughput vs FP32)
- GPU tensor cores for vector similarity
- NPU acceleration for linguistic models
- Batch inference at 100μs/message latency

**Documentation:**
- **Master Plan**: `docs/INT8_ACCELERATION_PLAN.md` (13 sections, comprehensive architecture)
- **Implementation Status**: `docs/INT8_IMPLEMENTATION_STATUS.md`
- **Timeline**: 10-week phased implementation
- **Target Performance**: 90% utilization of 130 TOPS, <2% accuracy loss

**Deployment Scenarios:**
- Workstation: NVIDIA RTX 4070 (150 TOPS) - $600
- Laptop: Intel Core Ultra 7 (134 TOPS combined) - Mobile ops
- Cloud: 4× NVIDIA A10G (600+ TOPS) - Auto-scaling

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

## Third-Party Licenses

SPECTRA may use third-party search algorithm libraries with specific licensing requirements:

### NOT_STISLA License

NOT_STISLA is dual-licensed under:
- **GNU Affero General Public License v3.0** - Open source license
- **Commercial License** - Available for proprietary use

**⚠️ License Compliance Warning:**

NOT_STISLA includes license compliance features to ensure proper usage. License violations may result in legal action.

**Commercial Licensing:**
- Commercial licensing available at [swordintel.com/licensing](https://swordintel.com/licensing)
- **Startups & Small Businesses**: Flexible terms with reasonable pricing
- **Medical & Non-Profit Organizations**: Special discounted rates
- **Intelligence Community**: Special consideration available for members of the intelligence community
- **Enterprise**: Volume discounts and custom SLA agreements

**Contact:**
- **Email**: [commercial@swordintel.com](mailto:commercial@swordintel.com)
- **GitHub Issues**: Tag with `[commercial-license]` for public discussion

**Note:** Home and personal use is always free and encouraged.

### QIHSE License

QIHSE is dual-licensed:
- **MIT License** - Open source license for non-commercial use
- **Commercial License** - Required for commercial/proprietary use

**⚠️ License Compliance Warning:**

QIHSE includes license compliance features to ensure proper usage. License violations may result in legal action.

**Commercial Licensing:**
- Commercial licensing available at [swordintel.com/licensing](https://swordintel.com/licensing)
- **Base License**: $500K-$2M per deployment (varies by use case)
- **Annual Maintenance**: 20% of license value for comprehensive support
- **Enterprise Support**: 24/7 support, performance optimization, security updates, version upgrades

**Contact:**
- **Email**: [commercial@swordintel.com](mailto:commercial@swordintel.com)
- **GitHub Issues**: Tag with `[commercial-license]` for public discussion

**Note:** Home and personal use is always free and encouraged.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
