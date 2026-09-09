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

## 🔓 Mini App Deep-Link Analysis
- Decodes Telegram Mini App (`t.me/<bot>/app?startapp=`) deep links.
- Extracts bot commands, referral/invite codes, and ad-attribution segments.
- Supports three real-world `startapp` encodings: bare commands, equals-delimited, and camelCase concatenation.
- Integrated into group discovery to identify and log Mini App links during network traversal.

## 🔐 CNSA 2.0 Post-Quantum Cryptography
- ML-KEM-768 key encapsulation, ML-DSA-65 digital signatures, SHA-384 hashing.
- Key management with encrypted keystore, backup, and public key export.
- Available as CLI subcommands (`crypto keygen`, `encrypt`, `decrypt`, `sign`, `verify`) and as a library (`tgarchive.crypto.pqc`, `tgarchive.crypto.key_manager`).
- Requires `liboqs-python` — gracefully degrades if not installed.

## 🕵️ Threat Analysis
- **Attribution Engine:** Writing-style profiling (vocabulary, sentence length, technical density), tool fingerprinting (Metasploit, Nmap, etc.), operational pattern detection (reconnaissance → exploitation chains), and AI-generated content detection.
- **Temporal Analysis:** Activity pattern mapping (peak hours/days), timezone inference, regularity scoring, and next-activity prediction.
- Available as CLI subcommands (`threat attribution`, `threat temporal`) and as libraries (`tgarchive.threat.attribution`, `tgarchive.threat.temporal`).

## 📐 Vector Search
- Semantic similarity search over archived messages.
- **QIHSE native vector engine** (`QihseSearchEngine`) — the sole production backend. Qdrant and ChromaDB are legacy fallbacks that are not installed; numpy is a testing-only fallback.
- Embeddings via `all-MiniLM-L6-v2` (SentenceTransformers, 384-dim, CPU-runnable, air-gapped). Deterministic hash fallback if the model is unavailable.
- Available as CLI subcommands (`vectors stats`, `vectors search`) and as a library (`tgarchive.db.vector_store`).
- The `QdrantVectorManager` class name is a legacy misnomer — it instantiates `VectorStoreManager(backend="qihse")` and uses QIHSE at runtime.

## 📊 Index Pipeline & Cross-Indexing

### Durable Outbox Architecture

All data writes (messages, users, media, operations, checkpoints) flow through a durable outbox before reaching native projections:

```text
upsert_message() / upsert_user() / upsert_media()
  → SQLite tables (messages, users, media)
  → IndexOutbox.append_to() (durable change log)
  → IndexProjector projects to:
      - qihse.content.v1  (full-text + semantic content)
      - qihse.graph.v1    (entity graph + Cypher)
      - qihse.errors.v1   (structured error storage)
      - fts.messages.v1   (SQLite FTS5 full-text search)
      - keystone.ids.v1   (O(1) ID anchor lookup)
      - keystone.events.v1, keystone.media_manifest.v1, etc.
```

### KEYSTONE Cross-Indexing

KEYSTONE creates O(1) ID anchors for cross-indexing:
- `("message", str(message_id))` — standalone messages
- `("telegram-message", f"{channel_id}:{message_id}")` — channel-scoped messages
- `("user", str(user_id))` — users
- `("media", str(media_id))` — media items

Cross-index flow: KEYSTONE finds ID → QIHSE retrieves content → FTS does text search.

### Services

| Service | File | Purpose |
|---------|------|---------|
| Import | `services/import_service.py` | Import SQLite, JSON, CSV, Telegram export data through the outbox pipeline. Supports batch, resume, and validation. |
| Backfill | `services/index_database_backfill.py` | Backfill existing SQLite records (messages, users, media, checkpoints, events) into the index. |
| Cross-Index | `services/cross_index.py` | Traverse all projections from a single ID (KEYSTONE + QIHSE + FTS + relations). |
| Analysis | `services/analysis.py` | Timeline analysis (heatmap, top posters) and user correlation (reply patterns, cross-channel flags). |
| Projection Lag | `services/projection_lag.py` | Monitor unprocessed outbox events per projection. |
| Steganographic Analysis | `services/steganographic_analysis.py` | Detect hidden data in media (LSB steganography, EOF appended data, EXIF anomalies, format mismatch, entropy analysis). |
| Impersonation Detection | `services/impersonation_detection.py` | Detect accounts pretending to be someone else (username cloning, homoglyphs, avatar matching, display name similarity). |
| Bot Detection | `services/bot_detection.py` | Detect bots acting as humans (timing regularity, vocabulary diversity, content repetition, 24/7 activity, response time, edit behavior). |
| Target Tracking | `services/target_tracking.py` | Surveillance target management — alias resolution, contact network, timing correlation, writing style fingerprint, risk indicators. |
| Scheduled Analysis | `services/scheduled_analysis.py` | Hourly targeting analysis — activity spikes, reply bombing, mention flooding, cross-channel coordination. Persists alerts. |
| File Search | `services/file_search.py` | Search all chats and accounts for a file by name (fuzzy/exact) or hash. Includes password field detection (keyword patterns, quoted strings, bare words near protected file extensions) and extended media metadata (size, mime_type, dimensions, dc_id, posted_by with username resolution). |
| Async File Search | `services/async_file_search.py` | Distributed file search across multiple Telegram sessions. Uses QIHSE RESP KV for atomic channel-to-session assignment (SETNX with TTL). Falls back to Redis, then SQLite. Aggregates and deduplicates results across sessions. Includes `TelegramPasswordFinder` (API-first, discovers dialogs live, scans nearby messages for passwords, CLI: `spectra find-passwords`). |
| QIHSE RESP Server | `search/qihse_resp_server.py` | RESP-compatible server wrapping the QIHSE C RESP engine. Provides KV helpers (`kv_set`, `kv_get`, `kv_setnx`, `kv_del`, `kv_expire`, `resp_command`), connect-only readiness probes, fd-reuse race mitigation, and AUTH support. Used for distributed coordination. |
| DB Locking | `db/db_base.py` | Exclusive flock on sidecar `.lock` files to prevent concurrent QIHSE VFS opens (which corrupt global state). Process-level flags ensure `libqihse.so` and `qihse_vfs.so` load only once per process. `close()`/`__del__`/`__exit__` all release the lock. |
| Shared Utils | `services/utils.py` | Shared service utilities — `parse_dt()` (ISO datetime parser) and `revision_hash()` (deterministic SHA-256 dict hash). Single source of truth for service helpers. |

### Single Source of Truth

| Component | Canonical Location | Notes |
|-----------|-------------------|-------|
| SQL Schema | `db/schema.py` | `SCHEMA_SQL` + `apply_migrations()` for upgrades. `db.py` and `db_base.py` import from here. |
| Data Models | `db/models.py` | `User`, `Media`, `Message`, `Month`, `Day` NamedTuples. `db.py` re-exports for backwards compatibility. |
| Service Utils | `services/utils.py` | `parse_dt()`, `revision_hash()`. Imported by scheduled_analysis, target_tracking, bot_detection, import_service, index_database_backfill. |
| Pagination Helper | `db/db_base.py` | `_page()` function. `db.py` imports from here. |

---

## 🔒 Air-Gapped AI Doctrine
- **Zero Cloud LLM Reliance**: No calls to remote or commercial AI APIs.
- **Strict Hardware Ceiling**: Any integrated local model must operate under a **2GB VRAM ceiling** (quantized lightweight models) with full heuristic fallback.
