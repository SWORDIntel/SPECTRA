# SPECTRA Architecture & Intelligence Pipeline

SPECTRA operates as a multi-tier intelligence framework combining network topology mapping, financial forensics, and offline local heuristics.

---

## 🏗️ Pipeline Layers

```text
[ Seed Target ] ──► Layer 0: Semantic Discovery (CaaS Scoring)
                         │
                         ▼
                    Layer 1: Forensic Profiling (Pricing, Aliases, Services)
                         │
                         ▼
                    Layer 1.5: Worker Queue Daemon (Batch Processing)
                         │
                         ▼
                    Layer 2: Infrastructure Nexus (Shared IDs, Panels, Bot Links)
```

---

### Layer 0: Semantic Discovery
- Traverses forwarding networks, mentions, and invite links.
- Scores discovered entities using Crime-as-a-Service (CaaS) heuristics.
- Filters out low-value broadcast channels and isolates targeted criminal clusters.

### Layer 1: Forensic Profiling
- Ingests message corpora and media transcripts.
- Extracts pricing matrices and normalizes currency values to USD for Gross Market Value (GMV) estimation.
- Tracks alias drift and historical operator handles across channel rebrands.

### Layer 1.5: Worker Queue Processing
- Offloads intensive extraction tasks to asynchronous workers.
- Supports batch sizes, parallel account rotation, and rate-limit backoffs.

### Layer 2: Infrastructure Nexus
- Correlates technical artifacts across seemingly unrelated channels:
  - Panel URLs & phishing kit domains
  - Telegram Bot IDs & API webhooks
  - Cryptographic payment endpoints

---

## 🔒 Air-Gapped AI Doctrine
- **Zero Cloud LLM Reliance**: No calls to remote or commercial AI APIs.
- **Strict Hardware Ceiling**: Any integrated local model must operate under a **2GB VRAM ceiling** (quantized lightweight models) with full heuristic fallback.
