![SPECTRA Banner](assets/SPECTRA.png)

# SPECTRA [SWORD CIPHER COMMAND]

**Spectrally-Processing Extraction, Crawling, & Tele-Reconnaissance Archive**

SPECTRA is firmly on trajectory to become a forensic-grade intelligence framework for Telegram network discovery, criminal market economics, and threat actor attribution. It is not fully there yet, but the vector is locked.

## ⚠️ SITREP: PROJECT STATUS & DEVELOPMENT DOCTRINE

Read this before deploying or submitting PRs. I am actively developing SPECTRA, but due to pressing operational commitments, I am compartmentalizing my bespoke, operational additions from this public release. 

**The GUI is a zombie.** It is still included in the codebase, but it needs to be put down. I do not have the time or patience for web consoles right now. I will find the time to do it eventually, but if anyone feels like it, you are highly encouraged to "commit a shotgun shell" for me and rip it out. We are pivoting strictly to a **CLI-first** architecture, leaning heavily into a centaur/local-model oversight structure. 

**Rules of Engagement for Contributions:**
1. **CLI First:** All new capabilities must be accessible and optimized for the command line. 
2. **Air-Gapped AI Only:** Absolutely zero integration with Claude, ChatGPT, or any other online model provider. If your code makes an API call to a cloud LLM, the PR will be rejected immediately. 
3. **Hardware Constraints:** If you implement a local model, it must fit under a strict **2GB VRAM hard ceiling** (e.g., highly quantized micro-models fitting on legacy GTX 1050 hardware). It must be treated as a non-vital auxiliary function with a seamless, graceful fallback to standard heuristics if the hardware is absent. 

Additions and commits adhering to this doctrine are absolutely welcome and will be reviewed.

## 🛡️ Operational Features

- 🔑 **tdata → Session Import (★ highly useful):** Convert logged-in Telegram Desktop / Alternatives `tdata` folders into Telethon `.session` files with no re-login. Filter by user_id, username, or convert all at once — directly from the CLI.
- 🔄 **Multi-account orchestration:** Smart, persistent selection and failure detection with 10 rotation strategies (sequential, random, weighted, smart, FloodWait-adaptive, circuit breaker, latency-aware, sticky/affinity, sharded, primary+fallback) plus channel de-duplication.
- 🕵️ **Proxy rotation:** OPSEC and anti-detection routing.
- 🔎 **Network discovery:** Automated mapping of connected groups and channels with SQL audit trails.
- 📊 **Graph/network analysis:** Target identification and cluster isolation.
- 📁 **Forensic archiving:** Integrity checksums and sidecar metadata generation.
- ⚄ **QIHSE Database Engine:** Full multi-model database replacement (KV, vector, document, columnar, time-series, FTS, event stream, graph+Cypher) with ACID transactions, MVCC, full SQL engine (JOIN/GROUP BY/ORDER BY/subqueries/CTEs/window functions/UPSERT/RETURNING/views), B+ tree and hash secondary indexes, unified WAL with crash recovery, streaming replication, read replicas, backup/restore, parallel query, connection pooler, and PostgreSQL + Redis + Bolt (Neo4j) wire protocol compatibility. Includes psycopg2, neo4j, tokio-postgres, and libpq-compatible SDKs. Replaces SQLite, Redis, PostgreSQL, Neo4j, and Celery with a single in-process engine.
- ⚡ **QIHSE Task Queue & Scheduler (Celery-Equivalent):** In-process asynchronous task dispatch and 10ms timing wheel cron scheduling with 4 priority levels and NUMA-pinned workers — zero external Celery or RabbitMQ processes required.
- ⚡ **Parallel processing:** Leverage multiple accounts and proxies simultaneously.
- 🖥️ **CLI-First Architecture:** Modular backend designed for terminal-driven centaur analysis.
- ☁️ **Forwarding Mode:** Traverse channel series, discover related infrastructure, and extract payloads based on strict rulesets.
- 🕸️ **Infrastructure Nexus:** Map shared technical artifacts (Panel URLs, Bot IDs) to reveal hidden connections between seemingly independent actors.
- 💰 **Economic Market Engine:** Track Gross Market Value (GMV) across CaaS sectors with USD-normalized pricing.
- 📑 **Narrative Synthesis:** Offline, heuristically-driven intelligence briefings classifying actor archetypes.
- 🤖 **Gatekeeper Evasion:** Built-in anti-bot challenge solving for automated invite access (math captchas and inline callbacks).
- 👁️ **Media OCR & Image Fingerprinting:** Scan downloaded media to extract threat indicators and crypto wallets directly from screenshots.
- ⏳ **Burner Account & Temporal Tracking:** Correlate aliases over time, mapping rebrands back to original Telegram UUIDs.
- 🚀 **Containerized Deployment:** Docker orchestration with automated SSL via Caddy.
- 📤 **Automated STIX/TAXII Exports:** Telemetry pipelines for direct MISP/OpenCTI integration.
- 🎨 **Sticker Set Archiver & Converter:** Download complete Telegram sticker sets (`.webp`, `.tgs`, `.webm`) with metadata sidecars and automatic PNG conversion.
- 🧠 **Attribution Engine:** Multi-source actor identity resolution with Bayesian evidence fusion, 18 feature extractors, and analyst label tracking.
- 🎭 **Persona Modeling:** Train char-LM persona models, score text against known profiles, detect persona drift, and generate synthetic text — all on local hardware.
- 🔍 **Semantic Search:** 384-dimensional vector embeddings (all-MiniLM-L6-v2) with 3-tier fallback (SentenceTransformer → TF-IDF → hash BoW), QIHSE/KEYSTONE/numpy vector stores, and hybrid rank fusion.
- 📊 **Evaluation Harness:** Benchmark intelligence modules with metrics, calibration, dataset splits, and reproducible reports.
- 🔄 **LAN Replication:** Gossip protocol + CRDT LWW-Set for multi-instance SPECTRA deployments with mDNS peer discovery and post-quantum signatures.
- 🗄️ **IndexOutbox + IndexProjector:** Durable change-log architecture with concurrent projection to QIHSE/KEYSTONE/FTS/graph stores, payload nulling, and DB compaction (71% size reduction verified).

## ⚡ Quick Start (Docker)

The fastest way to launch the operational environment with automated SSL and secure proxying:

```bash
# Clone and enter
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA

# Launch the full stack
export SITE_ADDRESS="your-domain.com" # Defaults to localhost
docker-compose up -d
```

## 🖥️ Local Execution

Launch the unified CLI directly:

```bash
./spectra
```

### Operational API Keys

Secure the interface for remote access or update your local `spectra_config.json`:
```json
{
    "api_id": "YOUR_API_ID",
    "api_hash": "YOUR_API_HASH"
}
```

## 🧠 Intelligence Pipeline

### Layer 0: Semantic Discovery
Pivot through the criminal network using CaaS-aware scoring to identify high-value targets.
```bash
./spectra discover --seed @target_channel
```

### Layer 1: Forensic Profiling
Extract pricing, services, and aliases from canonical archives into structured dossiers.
```bash
./spectra --profile @target_channel
```

### Layer 1.5: Job Queue Processing
Process bulk intelligence extraction requests through the automated worker queue.
```bash
./spectra process-queue --batch-size 250
```

### Layer 2: Nexus & Wallet Analysis
Automatically map infrastructure links and crypto-financial footprints across the entire repository.

### Layer 3: Attribution & Entity Resolution

Multi-source actor identity resolution with Bayesian fusion:

```bash
# Resolve actor identity across channels
./spectra intel resolve --actor @target_user

# Generate attribution evidence with confidence scores
./spectra intel attribute --channel @target_channel --evidence

# Cross-reference entities (wallets, panel URLs, bot IDs)
./spectra intel crossref --entity "example.com"
```

**Attribution engine features:**
- 6 feature families (linguistic, discourse, register, notation, orthographic, temporal)
- 18 feature extractors covering conversation patterns, dialogue acts, formatting, media usage
- Bayesian evidence fusion with anti-double-counting
- ActorIdentityResolver + EntityResolverV2 (7 evidence sources)
- Analyst label store (Confirm/Reject/Unsure) with provenance tracking
- Evaluation harness with benchmarks, metrics, calibration, and dataset splits

### Layer 4: Persona Modeling

Train and evaluate persona models from message corpora:

```bash
# Train a persona model from a channel's message history
./spectra persona train --channel @target_channel --epochs 50

# Score a text sample against known personas
./spectra persona score --model persona_v2 --text "suspicious message"

# Generate synthetic text from a trained persona
./spectra persona generate --model persona_v2 --length 500

# Detect persona drift over time
./spectra persona drift --channel @target_channel --window 30d
```

### Layer 5: Semantic Search

384-dimensional vector embeddings with 3-tier fallback:

```bash
# Search for similar messages across all channels
./spectra search semantic "crypto escrow service"

# Search with filters
./spectra search semantic "wallet address" --channel @target --limit 20

# Hybrid search (semantic + full-text + graph)
./spectra search hybrid "payment processor" --rank-fusion
```

**Search architecture:**
- EmbeddingGenerator: SentenceTransformer (CPU) → TF-IDF + random projection → hash bag-of-words
- Vector store: QIHSE vector index → KEYSTONE LSH + SIMD → numpy BLOB sidecar
- Query planner: cost-based routing across QIHSE/KEYSTONE/FTS/graph
- Rank fusion: reciprocal rank fusion across heterogeneous search backends

### Layer 6: LAN Replication (Gossip + CRDT)

Multi-instance replication for distributed crawling:

```bash
# Start the sync daemon
./spectra sync start --db data/spectra.db --port 7900

# Check sync status
./spectra sync status

# Connect to a static peer
./spectra sync start --peer 192.168.1.50 7900
```

**Replication features:**
- mDNS peer discovery + UDP gossip protocol
- CRDT LWW-Set for conflict-free merging
- Anti-entropy sync with Bloom filter comparison
- ML-DSA-87 post-quantum signatures
- Only IndexOutbox events replicated — each instance projects independently

## 🔑 tdata → Session Import

Convert logged-in Telegram Desktop / Alternatives `tdata` folders into Telethon `.session` files — **no phone number, no verification code, no re-login**. The existing MTProto authorization keys are extracted directly from the on-disk `tdata` and written into native Telethon SQLite sessions that SPECTRA's archiver, discovery crawler, and forwarder can use immediately.

```bash
# Auto-detect Telegram Desktop / Alternatives tdata and write sessions to ./sessions
./spectra tdata2session

# Point at a specific tdata folder and register accounts into spectra_config.json
./spectra tdata2session --tdata /path/to/tdata --output sessions --register

# Convert only a specific account by user_id
./spectra tdata2session --account 8000000002

# Convert multiple specific accounts by user_id (comma-separated)
./spectra tdata2session --account 8000000002,8000000003

# Convert only the account matching a Telegram username (connects to resolve)
./spectra tdata2session --username @someuser

# List all accounts found in tdata (quick, no network)
./spectra tdata2session --list-accounts

# List accounts with resolved usernames/names/phones (connects to Telegram)
./spectra tdata2session --list-accounts --resolve

# Passcode-protected tdata + emit StringSession strings in the JSON sidecars
./spectra tdata2session --passcode 1234 --string-sessions

# Re-run / overwrite existing session files
./spectra tdata2session --overwrite
```

Each converted account produces two files in the output directory:
- `spectra_tdata_<user_id>_<n>.session` — native Telethon SQLite session (drop-in for any Telethon client)
- `spectra_tdata_<user_id>_<n>.json` — sidecar with `api_id`, `api_hash`, `user_id`, `dc_id`, device info, and optional `StringSession`

## 🎨 Sticker Set Archiving & PNG Conversion

Download and archive entire Telegram sticker sets (`.webp`, animated `.tgs`, or video `.webm`) using any active session in the account pool, with full metadata sidecars and optional lossless `.png` conversion:

```bash
# Archive a sticker set by short name or URL
./spectra stickers atklib

# Convert downloaded WebP stickers to PNG
./spectra stickers atklib --png

# Download to a custom output directory
./spectra stickers https://t.me/addstickers/atklib --output ~/Pictures/atklib --png

# Inspect metadata without downloading
./spectra stickers atklib --info-only
```

Each downloaded set produces formatted sticker assets (`001_<doc_id>.webp` / `.png`) alongside a structured `metadata.json` sidecar containing emoji associations, set title, document IDs, dimensions, and type tags.

## 📚 Documentation

Comprehensive technical documentation is available in the [`docs/`](docs/) directory:
- 📖 [CLI Reference](docs/CLI_REFERENCE.md) — full command surface
- 📖 [Full CLI Reference](docs/docs/api/cli-reference-full.md) — every subcommand documented
- 🏗️ [Architecture & Intelligence Pipeline](docs/ARCHITECTURE.md)
- ⚙️ [Configuration & Accounts](docs/CONFIGURATION.md)
- 🔄 [Rotation Strategies](docs/ROTATION_STRATEGIES.md) — all 10 account rotation modes + channel de-duplication
- 🧠 [Advanced Features](docs/docs/features/advanced-features.md) — intelligence, attribution, vector search
- 🎯 [Attribution Engine](docs/docs/features/attribution-engine.md) — actor identity resolution
- 🔐 [CNSA Cryptography](docs/docs/features/cnsa-cryptography.md) — post-quantum security
- ⚡ [Vector Database](docs/docs/features/vector-database.md) — QIHSE + KEYSTONE + semantic search
- 🚀 [Quick Start Guide](docs/docs/getting-started/quick-start.md) — get running in 5 minutes
- 📦 [Installation](docs/docs/getting-started/installation.md) — full setup walkthrough
- 🔧 [Build from Source](docs/docs/getting-started/build.md) — compile QIHSE/KEYSTONE from submodules
- 📋 [Agent Guide](AGENTS.md) — architecture, DB management, LAN sync, all internals
- 📊 [API Examples](docs/docs/api/api-examples.md) — programmatic usage patterns
- 🗄️ [Database Schema](docs/docs/reference/database-schema.md) — full schema reference

## 📜 License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0) - see the LICENSE file for details.
