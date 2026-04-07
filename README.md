Here’s the edited drop-in version with the same styling and image block retained.

````markdown
# SPECTRA

**Spectrally-Processing Extraction, Crawling, & Tele-Reconnaissance Archive**

SPECTRA is an advanced framework for Telegram data collection, network discovery, forensic-grade archiving, and semantic intelligence with multi-account support, graph-based targeting, queue-backed enrichment, and robust OPSEC features.

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
- 🗄️ **SQL database storage** for discovered groups, relationships, archive metadata, and semantic-intelligence tables
- ⚡ **Parallel processing** leveraging multiple accounts and proxies simultaneously
- 🖥️ **Modern TUI** (npyscreen) and CLI, both using the same modular backend
- ⚙️ **Streamlined Account Management** - Full CRUD operations directly in the TUI with keyboard shortcuts
- ☁️ **Forwarding Mode:** Traverse a series of channels, discover related channels, and download text/archive files with specific rules, using a single API key
- 🧠 **Semantic discovery and triage** for category hints, urgency scoring, actor alias harvesting, and high-signal channel prioritization
- 🧱 **Canonical archive pipeline** using channel-scoped message identity instead of fragile raw Telegram message IDs
- 🧰 **Queue-backed deep profiling** for non-blocking enrichment and downstream analysis
- 🖥️ **Dedicated semantic-intelligence TUI** for discovery, canonical archive, queue processing, and signal review
- 🛡️ **Red team/OPSEC features**: account/proxy rotation, SQL audit trail, sidecar metadata, persistent state

## ⚡ Quick Start

**Root launchers:**

```bash
# Clone and enter directory
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA

# Main web console
./spectra

# Documentation launcher
python3 webapp.py
````

`./spectra` is the primary entry point for the web console. `python3 webapp.py` opens the documentation shell and lands on `/docs`.

## Local GUI

The repository also includes a local web launcher for orchestration, status, and documentation:

```bash
./spectra
```

Optional API key protection:

```bash
export SPECTRA_GUI_API_KEY="change-me"
./spectra --api-key "$SPECTRA_GUI_API_KEY"
```

Standard machine-readable API surfaces:

* `/openapi.json`
* `/.well-known/openapi.json`
* `/docs`

## Semantic-Intelligence Quick Start

### Dedicated semantic TUI

```bash
python -m tgarchive.ui.tui_caas --config spectra_config.json --db spectra.db --data-dir spectra_data
```

### Semantic discovery

```bash
python -m tgarchive.osint.caas.discovery_ops --seed @seed_channel --db spectra.db --data-dir spectra_data --depth 2 --messages 1000 --triage-sample 100
```

### Canonical archive

```bash
python -m tgarchive.core.sync_canonical --entity @target --db spectra.db --auto
```

### Queue processing

```bash
python -m tgarchive.osint.caas.cli process-queue --db spectra.db --batch-size 500
```

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

## Configuration

SPECTRA supports multi-account configuration with automatic account import from `gen_config.py` (TELESMASHER-compatible) and persistent SQL storage for all operations.

### Setting up Telegram API access

1. Visit [https://my.telegram.org/apps](https://my.telegram.org/apps) to register your application
2. Create a config file or use the built-in account import:

```bash
# Import accounts from gen_config.py
python -m tgarchive accounts --import
```

## System Status

**Current Version**: 2026-04 branch state

* ✅ **Core System**: Operational with web console, CLI, TUI, archive, and discovery paths
* ✅ **Semantic Pipeline**: Discovery triage, canonical archival, queue-backed profiling, and dedicated TUI present
* ✅ **Dependencies**: Core dependencies installed and verified
* ✅ **Architecture**: Modular cutover path in place for semantic-intelligence workflows
* ✅ **Canonical Identity Path**: Channel-scoped archival path available for collision-safe message storage

**Recent Enhancements**:

* Added canonical archive path with `(channel_id, message_id)` identity
* Added queue-backed semantic profiling pipeline
* Added semantic discovery wrapper for high-interest channel triage
* Added dedicated semantic-intelligence TUI
* Added schema bootstrap for channel profiles, queue items, message profiles, actors, and alerts
* See [CHANGELOG.md](docs/reference/CHANGELOG.md) for complete details

## Semantic Pipeline Overview

### Layer 0: Discovery-time triage

Fast semantic scoring is designed to run during or immediately after discovery to surface high-interest channels without blocking collection. Current signals include:

* likely service categories
* enterprise model hints
* payment method cues
* actor aliases
* geo hints
* urgency / critical markers
* bot / storefront likelihood

### Layer 1: Queue-backed deep profiling

Archive-time profiling is intentionally decoupled from Telegram ingest. Archived messages are queued first, then processed offline into structured intelligence tables.

Current core tables include:

* `caas_channel_profile`
* `caas_profile_queue`
* `caas_message_profile`
* `actor_entity`
* `caas_alert`

### Canonical message identity

The semantic archive path uses **channel-scoped identity** rather than assuming Telegram message IDs are globally unique. This prevents collisions across archived channels and gives the queue/profiling path a durable key.

## Documentation

### 📚 [Full Documentation Site](https://swordintel.github.io/SPECTRA/)

**Complete HTML documentation built with [Docusaurus](https://docusaurus.io/) - a modern static site generator with:**

* 🔍 **Full-text search** across all documentation
* 🌙 **Dark theme** (default) with light mode toggle
* 📱 **Responsive design** for mobile and desktop
* 🧭 **Interactive navigation** with organized sidebar
* ⚡ **Fast loading** with optimized static HTML
* 🔗 **Versioning support** for future releases

**For local development:**

```bash
cd docs
npm install          # Install Docusaurus dependencies
npm start            # Start development server (http://localhost:3000)
npm run build        # Build static HTML to docs/html/
```

**Documentation Framework:**

* Built with Docusaurus 3.x
* Source files: `docs/docs/` (markdown with frontmatter)
* Configuration: `docs/docusaurus.config.js`
* Build output: `docs/html/` (generated HTML files)
* Root entry point: `index.html` (redirects to documentation)

### Quick Links

#### Getting Started

* **[Installation Guide](docs/docs/getting-started/installation.md)** - Complete installation instructions
* **[Quick Start Guide](docs/docs/getting-started/quick-start.md)** - Get running in 30 seconds
* **[Configuration Guide](docs/docs/getting-started/configuration.md)** - Setting up API keys and accounts

#### User Guides

* **[TUI Usage Guide](docs/docs/guides/tui-usage.md)** - Complete guide to using the Terminal User Interface
* **[Forwarding Guide](docs/docs/guides/forwarding.md)** - Message forwarding and deduplication features
* **[CLI Reference](docs/docs/api/cli-reference.md)** - Complete command-line interface documentation

#### Features

* **[Advanced Features](docs/docs/features/advanced-features.md)** - AI/ML intelligence, threat scoring, vector databases, and more

### Legacy Documentation

Original markdown files are still available in:

* `docs/guides/` — User guides and walkthroughs
* `docs/reference/` — Technical reference documentation
* `docs/features/` — Feature documentation
* `docs/reports/` — Security summaries and integration reports
* `docs/roadmap/` — Long-term initiatives and backlog
* `docs/research/` — Strategic research documents

## Project Layout

```text
SPECTRA/
├── spectra              ← Main launcher for the local web console
├── webapp.py            ← Documentation launcher (`/docs`)
├── spectra.sh           ← Compatibility wrapper
├── tgarchive/           ← Core CLI/TUI/archive/forwarding package
│   ├── core/            ← Core archive and canonical archive paths
│   ├── ui/              ← Legacy TUI and dedicated semantic TUI
│   ├── utils/           ← Discovery and shared helpers
│   └── osint/caas/      ← Semantic discovery, queue worker, profiler, and schema
├── src/spectra_app/     ← Web launcher and orchestration implementation
├── spectra_app/         ← Compatibility package for repo-root imports
├── templates/           ← Shared web UI templates
├── docs/                ← Docusaurus source and compatibility docs
├── scripts/             ← Install, launch, and maintenance helpers
├── examples/            ← Example scripts
├── tests/               ← Repo-level smoke/integration scripts
├── deployment/          ← Docker/system deployment assets
├── bootstrap            ← Bootstrap entrypoint
├── index.html           ← Root redirect into the documentation site
├── Makefile             ← Common development commands
├── setup.py             ← Packaging entrypoint
└── CONTRIBUTING.md      ← Development workflow guide
```

Local runtime output such as `logs/`, `spectra_venv/`, `spectra.db`, `spectra_data/`, and `spectra_config.json` is intentionally kept out of version control.

For detailed structure explanation, see [PROJECT_STRUCTURE.md](docs/reference/PROJECT_STRUCTURE.md)

## Integration & Architecture

* **`SPECTRA/tgarchive/__main__.py`**: Unified CLI/TUI entry point for the legacy path
* **`SPECTRA/tgarchive/core/sync_canonical.py`**: Canonical archive path with channel-scoped identity and queue enqueueing
* **`SPECTRA/tgarchive/osint/caas/discovery_ops.py`**: Semantic discovery wrapper for triage and persistence
* **`SPECTRA/tgarchive/osint/caas/queue_worker.py`**: Offline queue processor for deep profiling
* **`SPECTRA/tgarchive/ui/tui_caas.py`**: Dedicated semantic-intelligence TUI
* **`examples/parallel_example.py`**: Example for parallel, multi-account operations

All modules are importable and can be reused in your own scripts or pipelines.

## Notes on Cutover

The legacy archive/discovery stack still exists. The semantic path is currently a **parallel cutover path**, not a full hard replacement of every legacy entrypoint. That is deliberate. It allows the newer pipeline to be exercised without risking the older collector paths until final splice work is complete.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow and verification guidance.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

```
```
