# SPECTRA [SWORD CIPHER COMMAND]

**Spectrally-Processing Extraction, Crawling, & Tele-Reconnaissance Archive**

SPECTRA is a forensic-grade intelligence framework for Telegram network discovery, criminal market economics, and threat actor attribution. It features a unified **NSO-style Cipher Command** dashboard for real-time operational control.

<p align="center">
  <img src="SPECTRA.png" alt="SPECTRA" width="35%">
</p>

## 🛡️ Cipher Command Features

- 🔄 **Multi-account orchestration** with smart, persistent selection and failure detection
- 🕵️ **Proxy rotation** for OPSEC and anti-detection
- 🔎 **Network discovery** of connected groups and channels (with SQL audit trail)
- 📊 **Graph/network analysis** to identify high-value targets
- 📁 **Forensic archiving** with integrity checksums and sidecar metadata
- 📱 **Topic/thread support** for complete conversation capture
- 🗄️ **SQL database storage** for all discovered groups, relationships, and archive metadata
- ⚡ **Parallel processing** leveraging multiple accounts and proxies simultaneously
- 🖥️ **Modern TUI** (npyscreen) and CLI, both using the same modular backend
- ⚙️ **Streamlined Account Management** - Full CRUD operations directly in the TUI with keyboard shortcuts
- ☁️ **Forwarding Mode:** Traverse a series of channels, discover related channels, and download text/archive files with specific rules.
- 🔐 **Dockerized web console** with first-run bootstrap admin enrollment and YubiKey/passkey WebAuthn sign-in
- 🛡️ **Red team/OPSEC features**: account/proxy rotation, SQL audit trail, sidecar metadata, persistent state
- 🕸️ **Infrastructure Nexus**: Map shared technical artifacts (Panel URLs, Bot IDs) to reveal hidden connections between seemingly independent actors.
- 💰 **Economic Market Engine**: Track Gross Market Value (GMV) across CaaS sectors (Initial Access, Malware, Logs) with USD-normalized pricing.
- 📑 **Narrative Synthesis**: Automated LLM-driven intelligence briefings that classify actor archetypes and strategic threat status.
- 💳 **Wallet-Watch (DIRECTEYE Ready)**: Forensic extraction of BTC, XMR, and TRX/ETH addresses with built-in hooks for [DIRECTEYE](https://github.com/SWORDIntel/DIRECTEYE) blockchain attribution.
- 🚀 **One-Command Deployment**: Production-ready Docker orchestration with automated SSL via **Caddy**.
- 🛡️ **OPSEC Core**: Multi-account/API rotation and proxy support for anti-detection and persistent collection.
- 🧠 **MEMSHADOW Sidecar**: Advanced 4096-dimensional semantic memory persistence and cross-LLM context preservation for deep threat analysis.

## ⚡ Quick Start (Docker)

The fastest way to launch the **Cipher Command Deck** with automated SSL and secure proxying:

```bash
# Clone and enter
git clone https://github.com/SWORDIntel/SPECTRA.git
cd SPECTRA

# Launch the full stack
export SITE_ADDRESS="your-domain.com" # Defaults to localhost
docker-compose up -d
```

Access the dashboard at `https://your-domain.com` (or `http://localhost`).

## 🖥️ Local Execution

Launch the unified web console directly:

```bash
./spectra
```

Docker-friendly browser authentication:

```bash
export SPECTRA_BOOTSTRAP_SECRET="one-time-bootstrap-secret"
export SPECTRA_SESSION_SECRET="change-me-in-production"
export SPECTRA_WEBAUTHN_ORIGIN="http://localhost:5000"
export SPECTRA_WEBAUTHN_RP_ID="localhost"
./spectra
### Operational API Keys
Secure the interface for remote access:
```bash
export SPECTRA_GUI_API_KEY="your-secure-key"
./spectra --api-key "$SPECTRA_GUI_API_KEY"
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
cd docs
npm install          # Install Docusaurus dependencies
npm start            # Start development server (http://localhost:3000)
npm run build        # Build static HTML to docs/html/
```

**Documentation Framework:**
- Built with Docusaurus 3.x
- Source files: `docs/docs/` (markdown with frontmatter)
- Configuration: `docs/docusaurus.config.js`
- Build output: `docs/html/` (generated HTML files)
- Root entry point: `index.html` (redirects to documentation)

### Quick Links

#### Getting Started
- **[Installation Guide](docs/docs/getting-started/installation.md)** - Complete installation instructions
- **[Quick Start Guide](docs/docs/getting-started/quick-start.md)** - Get running in 30 seconds
- **[Configuration Guide](docs/docs/getting-started/configuration.md)** - Setting up accounts, sessions, and browser auth

#### User Guides
- **[TUI Usage Guide](docs/docs/guides/tui-usage.md)** - Complete guide to using the Terminal User Interface
- **[Forwarding Guide](docs/docs/guides/forwarding.md)** - Message forwarding and deduplication features
- **[CLI Reference](docs/docs/api/cli-reference.md)** - Complete command-line interface documentation

#### Features
- **[Advanced Features](docs/docs/features/advanced-features.md)** - AI/ML intelligence, threat scoring, vector databases, and more

### Legacy Documentation

Original markdown files are still available in:
- `docs/guides/` — User guides and walkthroughs
- `docs/reference/` — Technical reference documentation
- `docs/features/` — Feature documentation
- `docs/reports/` — Security summaries and integration reports
- `docs/roadmap/` — Long-term initiatives and backlog
- `docs/research/` — Strategic research documents

## Project Layout

./spectra process-queue --batch-size 250
```

### Layer 2: Nexus & Wallet Analysis
Automatically map infrastructure links and crypto-financial footprints across the entire repository.

## 📁 System Status & Architecture

* ✅ **Cipher-Ops Dashboard**: High-contrast operational control surface.
* ✅ **Economic Intel**: USD-normalized GMV tracking and profitability rankings.
* ✅ **Forensic Dossiers**: Narrative summaries, wallet sightings, and nexus alerts.
* ✅ **Production Ready**: Docker + Caddy integration for secure remote ops.

## 📚 Documentation

Detailed technical reference and guides are available at:
* **Dashboard API**: `/docs` (OpenAPI 3.1 / Swagger)
* **Full Manual**: `/readme` or [GitHub Pages](https://swordintel.github.io/SPECTRA/)

## 📜 License

This project is licensed under the MIT License - see the LICENSE file for details.
