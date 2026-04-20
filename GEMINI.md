# SPECTRA - Gemini Project Context

## Project Overview
**SPECTRA** (Spectrally-Processing Extraction, Crawling, & Tele-Reconnaissance Archive) is an advanced framework for Telegram data collection, network discovery, forensic-grade archiving, and semantic intelligence. It features multi-account rotation, proxy support, graph-based targeting, and robust OPSEC features.

### Core Technologies
- **Language:** Python 3.10+
- **Telegram API:** [Telethon](https://github.com/LonamiWebs/Telethon)
- **Database:** SQLite (primary data store: `spectra.db`)
- **TUI/CLI:** `npyscreen`, `rich`, `tqdm`
- **Analysis:** `networkx`, `matplotlib`, `pandas`
- **Web/Docs:** Docusaurus (Node.js/React), Flask/Express (via `webapp.py`)
- **Orchestration:** Custom web console (via `./spectra`)

## Project Structure
- `tgarchive/`: Core Python package containing CLI, TUI, archiving, and forwarding logic.
  - `core/`: Sync and canonical archive paths.
  - `ui/`: TUI implementations (legacy and semantic).
  - `osint/caas/`: Semantic discovery, queue processing, and profiling.
- `src/spectra_app/` / `spectra_app/`: Web launcher and orchestration dashboard.
- `docs/`: Docusaurus source files and generated HTML.
- `scripts/`: Installation, launch, and environment setup scripts.
- `tests/`: Integration, security, and GUI-specific tests.
- `examples/`: Usage demonstrations for parallel operations and AI features.

## Building and Running

### Quick Start
- **Bootstrap (Recommended):** `./bootstrap` or `make bootstrap` - Automatically sets up the environment and launches the system.
- **Main Web Console:** `./spectra` - Launches the orchestration dashboard.
- **Documentation:** `python3 webapp.py` - Launches the local documentation server (accessible at `/docs`).

### Installation
- **Standard Install:** `make install` (runs `scripts/install/install-spectra.sh`).
- **Development Mode:** `pip install -e .`

### Key Entry Points
- **Unified CLI/TUI:** `python -m tgarchive` or `spectra` command (if installed).
- **Semantic TUI:** `python -m tgarchive.ui.tui_caas`
- **Semantic Discovery:** `python -m tgarchive.osint.caas.discovery_ops`

## Development Conventions

### Workflows
- **Testing:** `make test` runs `pytest` on the `tgarchive/tests/` directory. Additional integration tests are located in the root `tests/` folder.
- **Formatting:** Use `black` for code formatting (`make format`).
- **Linting:** Use `pylint` for static analysis (`make lint`).
- **Clean up:** `make clean` removes build artifacts and caches.

### Configuration & State
- **Config:** `spectra_config.json` (JSON) or `gen_config.py` (Python) for account imports.
- **Database:** `spectra.db` handles discovered groups, relationships, and semantic intelligence.
- **Logs:** Persistent logs are stored in the `logs/` directory (ignored by git).

### Architectural Notes
- **Canonical Identity:** The system uses channel-scoped message identity `(channel_id, message_id)` to ensure collision-safe storage.
- **Semantic Cutover:** Newer semantic-intelligence features exist as a parallel "cutover path" to maintain stability with legacy collector paths.
- **OPSEC:** Built-in account/proxy rotation and SQL audit trails are mandatory for forensic-grade data integrity.
