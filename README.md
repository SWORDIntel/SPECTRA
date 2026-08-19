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

- 🔄 **Multi-account orchestration:** Smart, persistent selection and failure detection.
- 🕵️ **Proxy rotation:** OPSEC and anti-detection routing.
- 🔎 **Network discovery:** Automated mapping of connected groups and channels with SQL audit trails.
- 📊 **Graph/network analysis:** Target identification and cluster isolation.
- 📁 **Forensic archiving:** Integrity checksums and sidecar metadata generation.
- 🗄️ **SQL database storage:** Persistent tracking of all discovered groups, relationships, and archive metadata.
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
    "api_id": 34453253,
    "api_hash": "b7188bbfe84dda5fce97f40faecfef6d"
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

## 📚 Documentation

Detailed technical reference and guides are available at `/docs` or via [GitHub Pages](https://swordintel.github.io/SPECTRA/).

### Building Documentation

**Documentation Framework:**
- Built with Docusaurus 3.x
- Source files: `docs/docs/`
- Build output: `docs/html/`

```bash
cd docs
npm install          # Install dependencies
npm start            # Start development server
npm run build        # Build static HTML
```

## 📜 License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0) - see the LICENSE file for details.
