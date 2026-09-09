# SPECTRA — Agent Guide

## Purpose

Spectrally-Processing Extraction, Crawling, & Tele-Reconnaissance Archive. SWORD Cipher Command platform for OSINT and data extraction.

**Direction: CLI-only.** GUI is a zombie (still in codebase, slated for removal). Air-gapped AI only (no cloud LLM API calls). Local models must fit under 2GB VRAM ceiling.

**VPU (Myriad X) integration removed.** Semantic embeddings now run on CPU via SentenceTransformer. The `spectra-vpu-embed` systemd service has been removed. VPU sticks are free for other compute. Model conversion scripts (`scripts/export_minilm*.py`, `scripts/myriad_embedding_server.py`) are retained but not auto-started. KEYSTONE's C-level VPU dispatch flag still exists but defaults to disabled.

## Repository State

This is a **consolidated merge** of:
- **SPECTRA master** (317 commits): QIHSE SQLite VFS, tdata2session, 10 rotation strategies, sticker downloader, Redis cache, AVX fallback, CNSA 2.0 crypto, threat analysis, vector search
- **Operational extensions**: KP14 live media scanner, TCP transport, Gatekeeper evasion, CaaS tracking, OCR, wallet extraction, MSNET integration, Overwatch GNN pipeline, cloud training framework, ChannelDownloader, IndexOutbox, OperationRecords

**MEMSHADOW has been cut.** Everything stores in QIHSE natively (KV, vector, document, graph).

### Remotes

| Remote | URL | Visibility | Push? |
|--------|-----|-----------|-------|
| `origin` | github.com/SWORDIntel/SPECTRA.git | PUBLIC | Primary public repo |

### Submodules

| Path | Commit | Purpose |
|------|--------|---------|
| `KEYSTONE/` | e081bb9 | Interpolation search + vector engine (LSH + SIMD + CUDA + VPU) |
| `QIHSE/` | 96f6769 | Multi-model database engine (Phase 9) |
| `libs/KEYSTONE/` | 18de82e | Alternate KEYSTONE location (older) |
| `libs/QIHSE/` | 3609d2c | Alternate QIHSE location |

## Architecture

```
Data sources (Telegram) → Crawlers/Scanners → Extraction engine
  → SQLite (spectra.db) + QIHSE (vector/graph/KV) + KEYSTONE (anchor search + vector engine)
  → IndexOutbox (durable change log) → IndexProjector (QIHSE/KEYSTONE projections)
  → CLI query/dispatch
```

### Recording Chain (QIHSE)

```
upsert_message() / upsert_user() / upsert_media()
save_audit_log() / save_operation() / save_operation_event()
  → messages / users / media / operations / operation_events tables (SQLite)
  → IndexOutbox.append_to() (durable outbox table)
  → index drain (CLI: `spectra index drain`)
  → IndexProjector projects to:
      - qihse.content.v1  (full-text + semantic content — messages, users, media)
      - qihse.semantic.v1 (dense vector embeddings for similarity search)
      - qihse.graph.v1    (entity graph + Cypher)
      - qihse.errors.v1   (structured error storage — OperationRecords failures)
      - fts.messages.v1   (SQLite FTS5 full-text search)
      - keystone.ids.v1   (fast ID lookup anchors — message_id, user_id, media_id)
      - keystone.events.v1 (telemetry event search)
      - keystone.media_manifest.v1
      - keystone.checkpoints.v1
      - keystone.export_records.v1
      - keystone.archive_members.v1
```

### Concurrency Model (QIHSE Writes)

The drain loop supports **concurrent writes** from multiple projector workers:

```
Worker 1 ─┐
Worker 2 ─┼─→ NativeStoreLock(shared=True) ─→ SQLite WAL writes (concurrent)
Worker 3 ─┘                                      │
                                                 ↓
                                    NativeStoreLock(exclusive)
                                    ─→ QIHSE native sync (serialized)
```

- **SQLite projections**: shared lock — multiple workers project concurrently
  (WAL mode handles concurrent writes, busy_timeout=300s)
- **Native QIHSE syncs** (`_sync_qihse`, `_sync_graph`): exclusive lock —
  serialized via `NativeStoreLock` on the `.qihse.qdb` / `.graph.qdb` files
- **Persistent index handles**: `QihseVectorIndex`, `QihseGraphIndex`, and
  `SemanticProjection` are kept open across batches with deferred flush
  (`upsert_no_flush` / `sync_no_flush` / `project_batch`)
- **Flush cadence**: controlled by `--flush-every-batches` (default 50) and
  `--flush-interval-seconds` (default 60s) — avoids O(total_vectors) flush
  per batch
- **close() flushes**: all native index `close()` methods flush/checkpoint
  before closing to prevent data loss

**CLI:**
```bash
spectra-cli --db data/spectra.db index drain \
  --batch-size 500 \
  --flush-every-batches 20 \
  --flush-interval-seconds 30
```

**Key files:**
- `tgarchive/db/index_projector.py` — drain loop, persistent handles, shared lock
- `tgarchive/db/native_store_lock.py` — `NativeStoreLock(shared=True/False)`
- `tgarchive/search/qihse_vector_backend.py` — `upsert_no_flush()` / `flush()`
- `tgarchive/search/qihse_graph_backend.py` — `sync_no_flush()` / `flush()`
- `tgarchive/search/semantic_projection.py` — `project_batch()` / `flush()`

### KEYSTONE Cross-Indexing

```
Message saved → upsert_message() → IndexOutbox
  → KEYSTONE anchor: ("message", str(message_id)) — O(1) lookup by ID
  → KEYSTONE anchor: ("telegram-message", f"{channel_id}:{message_id}") — if channel_id present
  → QIHSE content: full text + semantic vector for similarity search
  → FTS: SQLite FTS5 index for full-text MATCH queries

User saved → upsert_user() → IndexOutbox
  → KEYSTONE anchor: ("user", str(user_id)) — O(1) lookup by user ID

Media saved → upsert_media() → IndexOutbox
  → KEYSTONE anchor: ("media", str(media_id)) — O(1) lookup by media ID

Cross-index: KEYSTONE finds ID → QIHSE retrieves content → FTS does text search
```

### DB Size Management

The outbox is a **transient work queue** — once events are projected, their
payloads live on in `index_projection_records` and source tables. Keeping
millions of processed events wastes ~5GB on a 3.9M-event database.

**CLI commands:**
```bash
# Prune processed outbox events older than 24h (keeps newest 10K for debugging)
spectra-cli --db data/spectra.db index prune --retain-count 10000 --older-than-hours 24

# Prune ALL processed events
spectra-cli --db data/spectra.db index prune --all

# VACUUM to reclaim free pages and shrink the DB file
spectra-cli --db data/spectra.db index vacuum

# Full compact: prune + null payloads + vacuum (one-shot)
spectra-cli --db data/spectra.db index compact --retain-count 10000 --older-than-hours 24
```

**Automatic payload nulling:** After native QIHSE/graph sync completes,
`IndexProjector._null_projection_payloads()` sets `payload_json='{}'` (NOT
NULL constraint) and `vector_json=NULL` on synced projection records. This
reclaims ~4GB on a 3.9M-event database. Disable with `SPECTRA_SKIP_PAYLOAD_NULL=1`.

**Verified results:** `spectra index compact` on a 3.9M-event database:
- 21.9GB → 6.4GB (71% reduction, 15.5GB saved)
- Pruned 3.1M processed outbox events
- Nulled 2.77M vector_json, shrunk 5.66M payload_json to '{}'

**Fast drain env vars (size vs. speed tradeoffs):**
```
SPECTRA_SKIP_SEMANTIC=1       — skip 384-dim vector upsert
SPECTRA_SKIP_GRAPH=1          — skip graph projection
SPECTRA_SKIP_NATIVE=1         — skip 64-dim content vector sync
SPECTRA_SKIP_FTS=1            — skip FTS5 tokenization
SPECTRA_SKIP_STATE_REFRESH=1  — skip SHA-256 state checksums
SPECTRA_SKIP_PAYLOAD_NULL=1   — skip payload nulling after sync
```

**Future DB size reduction ideas (not yet implemented):**
- Contentless FTS5 tables (text already in messages.content)
- Deduplicate text_content across messages + projection_records + FTS
- Consolidate 110 indexes (several redundant)
- Separate outbox into its own DB file
- QIHSE vector quantization (PQ/int8 — requires re-encoding, parked)

### LAN Sync (Gossip + CRDT)

Multiple SPECTRA instances on the same LAN can replicate IndexOutbox events
using QIHSE's built-in gossip protocol and CRDT LWW-Set. When a second
instance comes online, it discovers peers via mDNS (or UDP broadcast) and
begins replicating events automatically.

```
SPECTRA Instance A (LAN)          SPECTRA Instance B (LAN)
  ┌─────────────────┐               ┌─────────────────┐
  │ Crawler → DB    │               │ Crawler → DB    │
  │ IndexOutbox     │               │ IndexOutbox     │
  │   ↓             │               │   ↓             │
  │ QIHSE (local)   │               │ QIHSE (local)   │
  │   ↓             │               │   ↓             │
  │ Gossip Manager  │◄──UDP/7900──► │ Gossip Manager  │
  │   + CRDT        │   PQC-signed  │   + CRDT        │
  │   + Anti-Entropy│   Bloom sync  │   + Anti-Entropy│
  └─────────────────┘               └─────────────────┘
```

**Components:**
- `tgarchive/search/qihse_sync.py` — ctypes bindings for QIHSE gossip + CRDT
- `scripts/spectra_sync_daemon.py` — UDP server + 7 daemon threads
- `tgarchive/db/index_outbox.py` — CRDT vector_clock + origin_node columns,
  `receive_replicated()` for peer events, `get_unsynced_events()` for anti-entropy
- `spectra_config.json` → `sync` section (enabled, port, peers, fan_out)

**QIHSE C layer (already compiled into libqihse.so):**
- `sync/qihse_sync_gossip.{c,h}` — epidemic broadcast, peer discovery,
  anti-entropy (Bloom filter comparison), ML-DSA-87 PQC signatures
- `sync/qihse_crdt.{c,h}` — LWW-Set with trinary Merkle DAG for state reconciliation

**Protocol:**
1. mDNS broadcast: `_spectra-sync._udp.local.` on port 7900
2. UDP heartbeat every 1s with node ID + IP
3. Gossip round every 5s: fan-out to 3 random peers (C library)
4. Anti-entropy every 30s: compare CRDT root hashes, transfer missing events
5. On new outbox event: broadcast `DATA_REPLICATE` to all known peers
6. On receive: insert via CRDT LWW into local outbox for projection
7. Failure detection every 10s: remove peers unseen for 60s

**CRDT conflict resolution:** Each outbox event gets a `vector_clock`
(microsecond timestamp) and `origin_node`. When two instances crawl the
same channel, the event with the higher vector_clock wins (LWW). The
`source_revision` SHA-256 hash ensures idempotent inserts.

**CLI:**
```bash
# Test the sync library
spectra sync test

# Check sync status (peers, seen messages)
spectra sync status --db data/spectra.db

# Start daemon in foreground
spectra sync start --db data/spectra.db --port 7900

# Start with a static peer (no mDNS needed)
spectra sync start --peer 192.168.1.50 7900

# systemd service (auto-starts on boot, restarts on failure)
systemctl --user enable spectra-sync
systemctl --user start spectra-sync
```

**systemd service:** `spectra-sync.service` — enabled, `Restart=always`,
auto-starts on boot after network is up.

**What gets replicated — and what doesn't:**

| Replicated (via gossip) | NOT replicated (local only) |
|--------------------------|----------------------------|
| IndexOutbox events (metadata + payload_json) | `messages`, `users`, `media` source tables |
| `vector_clock` + `origin_node` (CRDT metadata) | QIHSE stores (`.qihse.qdb`, `.semantic.qdb`) |
| `source_revision` (SHA-256 content hash) | KEYSTONE stores (`.keystone_vec.bin`) |
| | FTS5 index (`index_projection_fts`) |
| | Graph store (`.graph.qdb`) |
| | Projection records (`index_projection_records`) |
| | Projection state (`index_projection_state`) |
| | Intelligence tables (evidence, hypotheses, etc.) |
| | Persona tables (profiles, examples, drift) |

The sync daemon only replicates **IndexOutbox events** — the change log.
Each receiving instance must run `spectra index drain` independently to
project received events into its own QIHSE/KEYSTONE/FTS/graph stores.
This is by design: each instance has independent local indexes tuned to
its own hardware (AVX, CUDA).

**Payload availability window:** Outbox events retain full `payload_json`
until an explicit `spectra index prune` or `compact`. The sync daemon
broadcasts events as they arrive (2s poll). The `_null_projection_payloads()`
method only nulls payloads in `index_projection_records`, NOT in
`index_outbox` — so replicated events always carry their full payload.

### Mismatched Databases & Version Skew

**Scenario 1: Two instances with completely different data sets**

Instance A crawls channels 1-300, Instance B crawls channels 301-607.
After sync, both outboxes contain the union of all events. Each instance
drains independently → both end up with QIHSE/KEYSTONE indexes covering
all 607 channels. No conflict — different `source_key` values never collide.

**Scenario 2: Both crawl the same channel (overlap)**

Both instances crawl channel 12345 and get the same message. Both create
outbox events with identical `source_revision` (SHA-256 of payload). The
receiving instance's `INSERT ... ON CONFLICT DO NOTHING` silently drops
the duplicate. No conflict, no data loss. The `vector_clock` is irrelevant
here because the content is identical.

**Scenario 3: Same channel, different crawl timing (edit/delete)**

Instance A gets message 12345 at T1. The message is edited. Instance B
gets the edited version at T2 > T1. Both create outbox events with
**different** `source_revision` hashes (different content). Both events
are inserted into both outboxes. Both are drained. The projection
records overwrite — the last projection wins. QIHSE upsert is idempotent
by key, so the final state reflects whichever was projected last.
CRDT LWW at the metadata level records T2 as the winner, but the actual
data resolution happens at projection time (last-write-wins per key).

**Scenario 4: Older SPECTRA version (no sync daemon)**

Instance A runs an older version without `qihse_sync.py` or the sync
daemon. Instance B runs the new version with sync enabled.

- B's sync daemon starts, broadcasts mDNS + UDP heartbeats
- A is not listening on port 7900 → no response
- B runs alone, no peers discovered, no harm
- B's outbox events are not replicated to A
- A's outbox events are not replicated to B
- **When A is upgraded:** A's `ensure_schema()` auto-migrates — adds
  `vector_clock`, `origin_node`, `index_sync_state`, `index_sync_seen`
  tables via `ALTER TABLE` / `CREATE TABLE IF NOT EXISTS`. A starts its
  sync daemon, discovers B via mDNS. B's anti-entropy request triggers
  A to send its outbox history. Both sync up.

**Scenario 5: Older schema, newer code (auto-migration)**

If an instance has the new code but an old database (pre-CRDT columns),
`IndexOutbox.ensure_schema()` auto-migrates on first connection:
```sql
ALTER TABLE index_outbox ADD COLUMN vector_clock INTEGER NOT NULL DEFAULT 0;
ALTER TABLE index_outbox ADD COLUMN origin_node TEXT;
CREATE TABLE IF NOT EXISTS index_sync_state (...);
CREATE TABLE IF NOT EXISTS index_sync_seen (...);
```
Existing events get `vector_clock=0` and `origin_node=NULL`. They will
sync normally — the sync daemon assigns a UUID for the message_id and
uses the existing `source_revision` for dedup.

**Scenario 6: Schema mismatch (different table structures)**

If instance A has tables that B doesn't (e.g., A has
`intelligence_conclusions` but B is an older version without it), the
sync daemon only replicates `index_outbox` events. Events with
`source_table="intelligence_conclusions"` will be inserted into B's
outbox, but when B tries to drain them, the projector will skip or
error on unknown source tables. This is non-fatal — the drain loop
logs the error and moves on. The event stays in the outbox with an
error note until B is upgraded to understand that source table.

**Scenario 7: Different DB sizes (A=6GB, B=500MB)**

Sync is incremental — only new outbox events are replicated. B does not
receive A's historical data (messages, users, projection records). B
only receives outbox events created after the sync daemon started. To
bootstrap B with A's full history, use `spectra import` with A's SQLite
file as the source, then let sync handle ongoing incremental updates.

**Scenario 8: Network partition (LAN split)**

The gossip protocol is designed for partition tolerance:
- During partition: each instance continues independently, queuing events
- On reunion: anti-entropy sync compares CRDT root hashes, transfers
  all missing events in both directions
- No data loss — CRDT LWW resolves any concurrent writes
- The `index_sync_seen` table prevents re-processing of already-seen
  gossip messages (dedup via 16-byte UUID)

**Version compatibility matrix:**

| Instance A version | Instance B version | Behavior |
|--------------------|--------------------|----------|
| New (with sync) | New (with sync) | Full bidirectional sync |
| New (with sync) | Old (no sync) | B doesn't respond, A runs alone |
| Old (no sync) | Old (no sync) | No sync, both independent |
| Newer schema | Older schema | Auto-migrate on first connect |
| Newer code, old DB | — | `ensure_schema()` auto-migrates |

**Wire protocol versioning:** The UDP wire protocol has a version byte
(`WIRE_VERSION=1`). If a future version changes the protocol, older
instances will silently drop version-mismatched packets. This prevents
corruption from protocol skew.

### Import Mode

```
spectra-cli import <source> [--format auto|sqlite|json|csv] [--limit N]
  → services/import_service.py
  → Auto-detects format by extension and content magic bytes
  → SQLite: imports messages, users, media, channel_messages tables
  → JSON/NDJSON: imports message arrays or line-delimited objects
  → CSV: imports with column mapping (id, content, user_id, type, date, ...)
  → All data → IndexOutbox → IndexProjector → QIHSE + KEYSTONE
  → Idempotent: re-imports dedup via source_revision hash

Backfill existing data:
  spectra-cli index backfill-database
  → services/index_database_backfill.py
  → Scans messages, users, media, checkpoints, events from SQLite
  → Appends to IndexOutbox for projection
```

### Error Storage (qihse.errors.v1)

```
Operation fails → OperationRecords.save_operation() / update_operation_status()
  → error_store.record_error() → IndexOutbox.append_to(source_table="errors")
  → IndexProjector projects to qihse.errors.v1
  → CLI query: spectra-cli index errors [--stats] [--category CAT]
```

Errors are deduped by (category + message + context hash). Each error record
contains: error_code, category, error_message, timestamp, optional context,
optional operation_id, optional traceback (truncated to 4KB).

### Search Stack

```
Query → query_planner.py (unified entry point)
  → QueryPlanner.plan(query, limit, subsystems) → EvidenceBundle
  → Subsystem adapters (asyncio parallel, per-subsystem timeout):
      file_search     → services/file_search.py (bulk C scoring)
      hybrid_search   → search/hybrid_search.py (KEYSTONE + QIHSE + cache)
      semantic_search → search/semantic_search.py (QIHSE/KEYSTONE vector store)
  → Reciprocal Rank Fusion (RRF, k=60) fuses ranked lists
  → Graceful degradation: failed/timed-out subsystems skipped

Legacy path:
Query → hybrid_search.py
  → KEYSTONE (anchor interpolation search, 22x speedup over binary search)
  → QIHSE (vector similarity, graph traversal, KV lookup)
  → cache_manager.py (Redis/memcached optional, QIHSE KV native)
  → SQLite fallback
```

### KEYSTONE Vector Engine

The KEYSTONE Vector Engine (`libkeystone_vector.so`) provides hardware-agnostic
vector similarity search with LSH coarse indexing and SIMD exact rerank. It
serves as a fallback for QIHSE vector search across all SPECTRA pipelines.

**Fallback chain:** QIHSE → KEYSTONE → numpy brute force

**KEYSTONE internal dispatch:** CUDA → AVX-512 → AVX2 → AVX → SSE4.2 → NEON → scalar (VPU dispatch flag exists in C but defaults to disabled)

**Benchmark** (Intel Xeon E5-2407, AVX backend, 384-dim float32):
- 100K vectors: 2.36 ms/query, 423 q/s (30.8x faster than NumPy)
- 10K vectors: 1.80 ms/query, 556 q/s (4.4x faster than NumPy)

**Integration points:**
- `tgarchive/search/keystone_vector_backend.py` — ctypes wrapper (`KeystoneVectorIndex`)
- `tgarchive/search/semantic_projection.py` — fallback upsert + `vector_backend` property
- `tgarchive/search/semantic_search.py` — `_search_keystone()` method
- `tgarchive/db/index_projector.py` — fallback for 64-dim content vector sync
- `tgarchive/intelligence/vectors.py` — `IntelligenceVectorIndex` fallback

**Build:**
```bash
cd KEYSTONE/vector_engine && ./build_vector_engine.sh
# With VPU support: KEYSTONE_HAVE_VPU=1 ./build_vector_engine.sh
```

### Semantic Projection

```
Message/Media saved → IndexOutbox → IndexProjector
  → qihse.semantic.v1 projection:
      Extract text via _text_content(event)
      → EmbeddingGenerator (2-tier fallback):
          1. SentenceTransformer all-MiniLM-L6-v2 (384 dims, CPU, <2GB VRAM)
          2. TF-IDF + Gaussian random projection (CPU-only, deterministic)
          3. Hash-based bag-of-words (zero dependencies)
      → L2-normalized float32 vector
      → Vector store upsert (3-tier fallback):
          1. QIHSE vector store (spectra.db.semantic.qdb)
          2. KEYSTONE vector engine (spectra.db.keystone_vec.bin) — LSH + SIMD
          3. numpy BLOB sidecar (spectra.db.semantic.meta.db)
      → SQLite metadata sidecar (always written)

Query → semantic_search.py
  → Embed query → vector search (QIHSE → KEYSTONE → numpy) → similarity scores
  → Bug fixes: distance→similarity conversion (1.0 - distance),
    content populated from stored metadata
  → KEYSTONE fallback: LSH coarse index + SIMD exact rerank (30x faster than numpy)
  → Numpy fallback with correct cosine similarity if both unavailable
```

### Intelligence Pipeline (WP1-WP8 + Cross-Index/Patterns/Conclusions/Network)

```
Analytical modules (attribution, scoring, network, temporal, indicators)
  → adapters.py (convert module outputs to AnalysisEvidence)
  → schema.py (canonical evidence objects with provenance + versioning)
  → resolver.py (ActorIdentityResolver: 6 feature families → P(A=B))
  → entity_resolver_v2.py (EntityResolverV2: 7 evidence sources → IdentityCluster)
  → fusion.py (EvidenceFusionEngine: Bayesian fusion, anti-double-counting)
  → labels.py (AnalystLabelStore: append-only Confirm/Reject/Unsure)
  → evaluation/ (benchmark harness: metrics, splits, calibration, datasets)
  → IntelligenceStore → SQLite + IndexOutbox → IndexProjector
      → qihse.intelligence.v1 (structured intelligence search)
      → qihse.graph.v1 (hypothesis + campaign edges)
      → keystone.ids.v1 (O(1) anchor lookup by evidence/hypothesis ID)
  → vectors.py (QIHSE vector index for evidence feature vectors)
  → patterns.py (clustering, recurring pattern detection, cross-actor)
  → conclusions.py (Bayesian fusion → ranked conclusions with provenance)
  → network_expansion.py (discover network members from known leaders)
  → CLI: `spectra intel resolve|label|labels|fuse|changepoint|benchmark|
            cross-index|patterns|conclude|expand-network`
```

**Key principle:** `score != confidence` — score is the raw measurement,
confidence is how much we trust it (sample size, model quality).

**Anti-double-counting:** Correlated evidence (same URL + same domain +
same hostname) is grouped via union-find and counted once, preventing
five correlated weak scores from inflating 42% → 96%.

**Competing hypotheses:** same_actor, different_actor, shared_organization,
automation, copied_content, compromised_account — softmax-normalized
across all hypotheses for proper probability distribution.

### Intelligence Cross-Index & Analysis

```
Entity ID (e.g. telegram:user:123)
  │
  ├── cross_index_intelligence()  [services/cross_index.py]
  │     ├── Evidence WHERE subject = ID OR object = ID
  │     ├── Hypotheses WHERE subject_a = ID OR subject_b = ID
  │     ├── Campaigns WHERE actors/channels contain ID
  │     ├── Inferences that used evidence about the entity
  │     ├── Graph neighborhood (index_graph_nodes + index_graph_edges)
  │     └── KEYSTONE anchors for intelligence objects
  │
  ├── PatternMatcher  [intelligence/patterns.py]
  │     ├── detect_recurring_patterns() — evidence types across multiple actors
  │     ├── cluster_evidence_by_type() — group and summarize
  │     ├── find_evidence_clusters() — connected components via shared subjects
  │     ├── find_cross_actor_patterns() — coordinated behavior via hypotheses
  │     └── find_similar_evidence() — score-proximity similarity
  │
  ├── IntelligenceVectorIndex  [intelligence/vectors.py]
  │     ├── evidence_to_vector() — 64-dim L2-normalized feature vector
  │     ├── Separate QIHSE vector DB (spectra.db.intelligence.qdb)
  │     └── search_similar() — semantic similarity on evidence signatures
  │
  ├── draw_conclusions() / conclude_actor()  [intelligence/conclusions.py]
  │     ├── Gather all evidence + hypotheses + campaigns + graph
  │     ├── Run EntityResolverV2 → IdentityCluster (7 evidence sources)
  │     ├── Bayesian fusion → probability + confidence
  │     ├── Conclusion type detection (actor_identity, threat, etc.)
  │     ├── Persist identity_clusters + identity_cluster_members to spectra.db
  │     ├── Record provenance to provenance_nodes table (spectra.db, not sidecar)
  │     └── Full provenance (supporting/contradicting evidence IDs)
  │
  └── expand_network()  [intelligence/network_expansion.py]
        ├── Input: known leader actor IDs
        ├── Expand via: graph edges, hypotheses, contact network, co-channel
        ├── Score each discovered actor: P(member of network)
        ├── Actors above threshold → auto-added to campaign
        └── Multi-hop expansion (depth 1=direct, 2=indirect)
```

**Network expansion workflow:**
1. Analyst identifies known bad actors (leaders) by user ID
2. `spectra intel expand-network --leaders 123,456 --campaign "Op Name"`
3. Engine discovers connected actors via 4 signals:
   - Hypothesis links (same-actor, associated_with)
   - Contact network (replies, mentions)
   - Co-channel co-occurrence
   - Graph edges from existing campaigns
4. Each discovered actor scored with Bayesian fusion
5. Actors above `--min-probability` saved to campaign as network members
6. Result includes full graph (nodes + edges) for visualization

### Periodic Intelligence Analysis (Automated)

A systemd user timer spawns a Devin GLM-5.2 subagent every 3 hours to
analyze intelligence data from QIHSE and produce a structured report.

```
systemd timer (every 3h, OnCalendar=*-*-* 00/3:00:00)
  → scripts/periodic_intel_analysis.sh
  → Export intelligence_evidence / intelligence_hypotheses / intelligence_campaigns
    + graph edges + top entities + high-probability hypotheses from SQLite/QIHSE
  → Run SPECTRA CLI: intel patterns --mode recurring/cross-actor --json
    + intel conclude <top_entities> --json
    + intel cross-index <top_entities> --json
  → Devin GLM-5.2 subagent (non-interactive, --print --permission-mode dangerous)
  → Analysis report → data/intel_reports/intel_analysis_<timestamp>.md
  → Devin session deleted (before/after session list diff + devin rm --force)
```

**Persistence:** Conclusions and patterns can now be saved with `--save`:
- `spectra intel conclude 123 --save` → intelligence_conclusions table + outbox
- `spectra intel patterns --mode recurring --save` → intelligence_patterns table + outbox
Both flow through IndexOutbox → IndexProjector → QIHSE/KEYSTONE projections.

**Vector indexing:** Evidence vectors are now upserted into the QIHSE
intelligence vector index during `spectra index drain`. The
`PatternMatcher.find_similar_evidence()` uses the vector index for semantic
similarity search, falling back to SQL score-proximity if vectors are
unavailable.

**Network expansion graph edges:** `expand_network()` now persists discovered
graph edges into `index_graph_nodes` and `index_graph_edges` projection tables,
so they survive across sessions and are visible to `spectra index graph`.

**Timer/service files:**
- `~/.config/systemd/user/spectra-intel-analysis.timer`
- `~/.config/systemd/user/spectra-intel-analysis.service`

**Manage:**
```bash
systemctl --user status spectra-intel-analysis.timer
systemctl --user start spectra-intel-analysis.service   # manual run
systemctl --user list-timers spectra-intel-analysis.timer
journalctl --user -u spectra-intel-analysis.service -f  # tail logs
```

**Reports:** `data/intel_reports/intel_analysis_<timestamp>.md` (analysis)
+ `.json` (raw export). Reports cover threat assessment, network analysis,
campaign assessment, pattern detection, key findings, recommended actions,
and data quality assessment.

### Persona Training-Data Pipeline (Consent-Based)

A longitudinal persona corpus and knowledge-profile system for building
authorized bot/persona training data. Collects positive and negative examples
over time, records domain knowledge scores (`score != confidence`), builds
style/vocabulary snapshots, and exports JSONL for local model training.

```
Register authorized persona target
  → Collect examples from messages table (positives = target author,
     negatives = temporally matched non-target authors)
  → Add manual examples with explicit labels (positive/negative/review)
  → Record domain knowledge observations (computers: 0.75, biology: 0.32)
     — score is the measurement, confidence is trust in the measurement
  → Build longitudinal snapshot (vocabulary, distinctive vocab via log-odds,
     bigrams, linguistic features, knowledge estimates)
  → Persist to spectra.db (persona_targets, persona_examples,
     persona_knowledge_observations, persona_profile_snapshots)
  → IndexOutbox → IndexProjector → QIHSE content + KEYSTONE anchors + graph
  → Export JSONL (authorized targets only, disclosure_required=true)
```

**Authorization gate:** Export refuses with `PermissionError` unless the
target's `authorization_status == 'authorized'`. The `--force` flag overrides
this for emergency use.

**Labels:**
- `positive` — target-authored or target-approved text
- `negative` — counterexamples, other authors, copied content
- `review` — uncertain material, never treated as positive by default

**Knowledge metadata:** Each observation stores `domain`, `score` [0,1],
`confidence` [0,1], `evidence_source`, `evaluator`, `evaluator_version`,
`observed_at`, and `notes`. Estimates aggregate via confidence-weighted mean
with contradiction penalty (high-variance scores lower confidence).

**Inferred knowledge:** `PersonaTrainingModel.infer_knowledge_observations()`
scans positive examples for domain lexicon terms (computers, biology, finance,
security, medicine) and produces conservative calibrated estimates. No claim
without evidence.

**Schema tables** (in `schema.py`):
- `persona_targets` — authorized targets with `authorization_status`
- `persona_examples` — labeled text with source provenance
- `persona_knowledge_observations` — domain knowledge with score/confidence
- `persona_profile_snapshots` — longitudinal vocabulary/style/knowledge

**Outbox source tables:** `persona_targets`, `persona_examples`,
`persona_knowledge_observations`, `persona_profile_snapshots` → flow through
`IndexProjector` to QIHSE content, KEYSTONE anchors (`persona-targets`,
`persona-examples`, etc.), and graph edges (example → target, snapshot → target).

**CLI:**
```bash
./spectra persona register <target_id> --name "Alice" --authorize
./spectra persona authorize <target_id> --status authorized
./spectra persona collect <target_id> --user-id 100 --limit 5000
./spectra persona add-example <target_id> --label positive --text "hello"
./spectra persona label <target_id> --message-id 42 --label negative
./spectra persona knowledge <target_id> --domain computers --score 0.75 --confidence 0.8
./spectra persona snapshot <target_id> --infer-knowledge
./spectra persona show <target_id>
./spectra persona list --status authorized
./spectra persona export <target_id> -o corpus.jsonl
```

## Build

### KEYSTONE (search engine C library)

```bash
# From SPECTRA root — t420 has no AVX, use scalar build
cd KEYSTONE && KEYSTONE_FORCE_SCALAR=1 bash build.sh
cd libs/KEYSTONE && KEYSTONE_FORCE_SCALAR=1 bash build.sh  # alt location

# Output: KEYSTONE/libkeystone.so + KEYSTONE/fortran/libkeystone_batch.so
# The .so has RUNPATH=$ORIGIN/fortran so it finds the Fortran backend automatically
```

Build flags:
- `KEYSTONE_FORCE_SCALAR=1` — no AVX2/AVX-512 (use on t420/legacy CPUs)
- `KEYSTONE_ENABLE_FORTRAN=1` — Fortran batch backend (default if gfortran found)
- `KEYSTONE_ENABLE_OPENMP=1` — OpenMP parallelism (default)
- `KEYSTONE_ENABLE_AVX2=auto` — auto-detect AVX2

### QIHSE (database engine C library)

QIHSE is pre-built at `QIHSE/libqihse.so`. To rebuild, see `QIHSE/` submodule.

### Docker (optional, not CLI-first)

```bash
docker-compose build
docker-compose up -d
```

## Verify

```bash
# Verify all native libraries load
python3 -c "
import sys; sys.path.insert(0, '.')
from tgarchive.search import keystone_bindings, qihse_bindings
print(f'KEYSTONE: {keystone_bindings.keystone_available()}')
print(f'QIHSE: {qihse_bindings.qihse_available()}')
from tgarchive import __main__
print('CLI: OK')
"

# Run tests
python3 -m pytest tgarchive/tests/ -x

# CLI help
python3 -m tgarchive --help
```

## Key Files

| File | Purpose |
|------|---------|
| `tgarchive/__main__.py` | Main CLI entry point (argparse, all subcommands) |
| `tgarchive/search/keystone_bindings.py` | KEYSTONE C library FFI (ctypes) |
| `tgarchive/search/qihse_bindings.py` | QIHSE C library FFI (ctypes) |
| `tgarchive/search/hybrid_search.py` | Unified search (KEYSTONE + QIHSE + cache) |
| `tgarchive/search/query_planner.py` | QueryPlanner — unified retrieval with RRF (k=60), asyncio parallel subsystems |
| `tgarchive/search/search_candidate.py` | SearchCandidate dataclass — canonical candidate for fused search |
| `tgarchive/search/evidence_bundle.py` | EvidenceBundle dataclass — fused search result with provenance |
| `tgarchive/search/rank_fusion.py` | Reciprocal Rank Fusion (RRF) implementation |
| `tgarchive/search/semantic_projection.py` | SemanticProjection — embedding generation + QIHSE vector store projection |
| `tgarchive/search/semantic_search.py` | SemanticSearchEngine — QIHSE vector search with numpy fallback |
| `tgarchive/agent/tools.py` | 5 agent tool functions: search, expand, timeline, resolve, evidence |
| `tgarchive/agent/tool_schema.py` | JSON schemas for agent tools (LLM function calling) |
| `tgarchive/db/db_base.py` | SQLite base with QIHSE VFS + IndexOutbox |
| `tgarchive/db/index_outbox.py` | Durable change outbox (→ QIHSE/KEYSTONE projections) |
| `tgarchive/db/index_projector.py` | Outbox → QIHSE/KEYSTONE projection builder |
| `tgarchive/db/operation_records.py` | Operation/audit log recording (→ QIHSE) |
| `tgarchive/db/spectra_db.py` | Main DB facade (delegates to operation/mirror/sorting mixins) |
| `tgarchive/db/schema.py` | **Single source of truth** for SQL schema + `apply_migrations()` |
| `tgarchive/db/models.py` | **Single source of truth** for User/Media/Message/Month/Day NamedTuples |
| `tgarchive/services/utils.py` | **Single source of truth** for shared service utils (`parse_dt`, `revision_hash`) |
| `tgarchive/services/async_file_search.py` | Distributed file search across sessions (QIHSE RESP/Redis/SQLite coordination) |
| `tgarchive/utils/discovery.py` | Channel discovery + AdvancedAccountRotator (10 strategies) |
| `tgarchive/services/channel_downloader.py` | Modern channel downloader (ChannelDownloader) |
| `tgarchive/osint/caas/` | CaaS profiling, market intel, actor dossiers |
| `tgarchive/intelligence/` | Canonical evidence schema, resolver, fusion, labels, vectors, patterns, conclusions, network expansion |
| `tgarchive/intelligence/schema.py` | EvidenceSource, AnalysisEvidence, ModelInference, ActorHypothesis, Campaign |
| `tgarchive/intelligence/adapters.py` | Convert existing module outputs → AnalysisEvidence |
| `tgarchive/intelligence/resolver.py` | ActorIdentityResolver (6 feature families → P(A=B)) |
| `tgarchive/intelligence/entity_resolver_v2.py` | EntityResolverV2 — probabilistic resolution with 7 evidence sources, IdentityCluster |
| `tgarchive/intelligence/provenance_graph.py` | ProvenanceGraph — full derivation chain tracking with replayability |
| `tgarchive/intelligence/temporal_graph.py` | TemporalGraph — activity patterns, timezone inference, change-point detection |
| `tgarchive/intelligence/fusion.py` | EvidenceFusionEngine (Bayesian fusion, anti-double-counting) |
| `tgarchive/intelligence/labels.py` | AnalystLabelStore (append-only, chain integrity) |
| `tgarchive/intelligence/vectors.py` | IntelligenceVectorIndex — QIHSE vector DB for evidence feature vectors (64-dim) |
| `tgarchive/intelligence/patterns.py` | PatternMatcher — recurring patterns, evidence clusters, cross-actor detection |
| `tgarchive/intelligence/conclusions.py` | Conclusion engine — Bayesian fusion of all evidence into ranked conclusions |
| `tgarchive/intelligence/network_expansion.py` | Network expansion — discover network members from known leaders |
| `tgarchive/intelligence/persona_training.py` | PersonaTrainingModel — longitudinal corpus, knowledge profile, JSONL export |
| `tgarchive/intelligence/features/` | 6 feature families: linguistic, temporal, infrastructure, telegram_native, media, commercial |
| `tgarchive/evaluation/` | Benchmark harness: metrics, splits, calibration, datasets, benchmarks, reports |
| `tgarchive/threat/changepoint.py` | Behavioral change-point detection + campaign segmentation |
| `tgarchive/db/intelligence_store.py` | DB persistence for evidence/hypotheses/campaigns + IndexOutbox integration |
| `tgarchive/db/persona_store.py` | PersonaStore — durable SQLite store for persona targets, examples, knowledge, snapshots + IndexOutbox |
| `tgarchive/services/cross_index.py` | Cross-index service — traverse all QIHSE/KEYSTONE projections from a single ID (now includes intelligence) |
| `training/` | Cloud training framework + spectra operator training |

## CLI Commands

The singular launcher is `./spectra-launch <command> [args]`. It:
- Logs every launch to QIHSE via the IndexOutbox/audit system
- Captures errors and logs them to `qihse.errors.v1`
- Drains the IndexOutbox after each run (projects to QIHSE/KEYSTONE)

The `./spectra` wrapper routes CLI commands to `spectra-launch` and legacy GUI commands to their handlers.

```bash
# CLI commands (logged to QIHSE)
./spectra index status
./spectra analyze hourly-run
./spectra search "query"
./spectra file-search "file.zip"

# Direct launcher (same thing)
./spectra-launch index status
```
# ── Core Operations ───────────────────────────────────────────────────────
archive            Archive a Telegram channel/group
                     Click: archive channel
download-channel   Download a channel via modern ChannelDownloader
                     `spectra download-channel --entity @channel --round-robin`
                     Round-robin: cycles through all configured accounts,
                     auto-rotates on FloodWait, resumes from last checkpoint.
                     Flags: --round-robin, --rotation-mode sequential|random,
                     --max-rotations N (default 50)
retry-failed       Retry failed media downloads (argparse; Click: channel retry-failed)
discover           Discover Telegram groups
                     Click: discover run | status | results
network            Analyze network of groups
                     Click: network analyze | status | export
batch              Batch operations on multiple groups (argparse)
parallel           Run operations in parallel across accounts
                     argparse: parallel discover | join | archive

# ── Account Management ────────────────────────────────────────────────────
accounts           Manage Telegram accounts (argparse: --rotation-stats, --set-rotation)
account            Manage Telegram accounts (Click: add, list, show, login, logout,
                     remove, stats, health, test, reset-usage, import)
tdata2session      Convert tdata folders → Telethon .session files (argparse)

# ── Forwarding ────────────────────────────────────────────────────────────
forward            Forward messages / channel recovery
                     Click: forward messages | dialogs | recover | traverse | schedule | status

# ── Configuration ─────────────────────────────────────────────────────────
config             Manage SPECTRA configuration
                     Click: config path | show | get | set | unset | validate |
                     migrate-env | set-forward-dest | view-forward-dest |
                     profile (list, show, add, use, remove)

# ── Channel Management ────────────────────────────────────────────────────
channels           Manage channel info (argparse: update-access; Click hidden:
                     update-access, access-refresh, add, inspect, list, remove, show, stats)
channel            Manage channels (Click: archive, download, retry-failed, monitor,
                     members, add, remove, list, show, stats, inspect, access-refresh, status)

# ── Scheduling ────────────────────────────────────────────────────────────
schedule           Manage scheduled tasks (argparse + Click hidden: add, list, remove,
                     daemon/run, add-channel-forward, add-file-forward, report, show, status)
scheduler          Manage scheduled tasks (Click: add, list, status, show, remove, daemon,
                     add-channel-forward, add-file-forward, report)

# ── Migration ─────────────────────────────────────────────────────────────
migrate            One-time migration (argparse; Click: migration run)
migrate-report     Generate a migration report (argparse; Click: migration report)
rollback           Roll back a migration (argparse; Click: migration rollback)
migration          Migration management (Click: run, report, status, rollback)

# ── Index & Search ────────────────────────────────────────────────────────
index              Index management (Click: drain, rebuild, status, lag, errors,
                     backfill-database, process, watch, verify, lookup, lookup-record,
                     checkpoint, event, export-record, archive-member, graph,
                     backfill-export, scan-archive, benchmark)
                     argparse subcommands (native, wired to service modules):
                     `spectra index drain [--batch-size N] [--max-batches N]
                       [--flush-every-batches N] [--flush-interval-seconds S]`
                     `spectra index backfill-database [--limit N]`
                     `spectra index stats`
                     `spectra index rebuild [--projection all|name]`
                     argparse: `spectra index drain [--projection semantic]` now generates
                     qihse.semantic.v1 embeddings via SemanticProjection
cross-index        Cross-index an entity across all projections
search             Unified search via QueryPlanner + RRF (argparse)
                     `spectra search "query" --limit N --subsystems all --json`
                     Subsystems: file_search, hybrid_search, semantic_search
                     Fuses ranked lists via Reciprocal Rank Fusion (k=60)
file-search        Search all chats for a file by name or hash (async by default, --sync for legacy)
agent              Agent tool surface for LLM consumption (argparse)
                     `spectra agent search "query" --limit N --subsystems all`
                     `spectra agent expand "media:123" --depth 2`
                     `spectra agent timeline "user:456" --start 2026-01-01`
                     `spectra agent resolve "@username"`
                     `spectra agent evidence "conclusion:789"`
                     Each tool returns JSON-serializable dict with summary/explanation

# ── Analysis ──────────────────────────────────────────────────────────────
analyze            Analysis (Click: timeline, user, indicators, temporal, steganography,
                     impersonation, bot-detection, hourly-run, account-correlation,
                     attribution, forecast, network, score)
target             Surveillance target management (Click: add, list, remove, dossier,
                     network, timing, alerts, ack)
threat             Threat analysis (argparse: writing-style, tool fingerprint, AI detection)

# ── Data Import / Export ──────────────────────────────────────────────────
import             Import external data (SQLite, JSON, CSV, Telegram export, batch,
                     resume, validate)
                     argparse (native, wired to import_service.import_data):
                     `spectra import <source> [--format auto|sqlite|json|csv|telegram-export]
                       [--limit N]`
                     Auto-detects format by extension and magic bytes.
                     All imported data → IndexOutbox → IndexProjector → QIHSE/KEYSTONE.
                     Run `spectra index drain` after import to project.
export             Export local SPECTRA data (Click: table)
download-users     Download user list (argparse)

# ── OSINT ─────────────────────────────────────────────────────────────────
osint              OSINT tracking (argparse: add-target, remove-target, list-targets,
                     scan, show-network; Click: target add/remove/list, scan, network)

# ── Advanced Tools ────────────────────────────────────────────────────────
mirror             Mirror a group to another (Click: run, status)
sort               Watch directory and sort files (argparse; Click hidden)
files              File management (Click: sort, watch)
stickers           Download Telegram sticker sets + PNG conversion (argparse)
decode-miniapp     Decode Telegram Mini App deep-links (argparse)
vectors            Vector search over archived messages (argparse)

# ── Crypto & Security ─────────────────────────────────────────────────────
crypto             CNSA 2.0 post-quantum crypto operations
                     Click: algorithms, kem, signature, encrypt, decrypt

# ── ML & AI ───────────────────────────────────────────────────────────────
ml                 Machine learning (Click: patterns, correlate, entities,
                     semantic-search, model list/train)

# ── Intelligence Pipeline ─────────────────────────────────────────────────
intel              Intelligence pipeline (argparse: resolve, label, labels,
                     fuse, changepoint, benchmark, cross-index, patterns,
                     conclude, expand-network)
  resolve           Resolve actor identity between two users (--user-a, --user-b)
  label             Add analyst Confirm/Reject/Unsure verdict
  labels            List analyst labels with filtering
  fuse              Fuse evidence into competing hypotheses
  changepoint       Detect behavioral change points for a user
  benchmark         Run evaluation benchmark from analyst labels
  cross-index       Cross-index entity across all intelligence projections
                     (--type user|channel|message|media, shows evidence,
                     hypotheses, campaigns, graph, KEYSTONE anchors)
  patterns          Find evidence patterns and clusters
                     (--mode recurring|clusters|cross-actor|similar,
                     --min-cluster N, --entity ID, --evidence-id ID)
  conclude          Draw fused conclusions about an entity
                     (--type user|channel|message|media, shows probability,
                     confidence, supporting/contradicting evidence, campaigns,
                     identity_clusters from EntityResolverV2, provenance chain)
                     Persists identity_clusters + provenance_nodes to spectra.db
                     via IntelligenceStore → IndexOutbox → IndexProjector
  expand-network    Discover network members from known leader actor IDs
                     (--leaders 123,456 --campaign "Op Name" --min-probability 0.6
                     --max-depth 2, auto-adds qualified actors to campaign)

# ── Server & API ──────────────────────────────────────────────────────────
server             Web server management (Click: health, run)
api                API management (Click: graphql)

# ── Admin & Operations ────────────────────────────────────────────────────
admin              Administration (Click: health, config, stats, operations, logs,
                     operator add/hash-password)
operations         Operation records (Click: list, show, schema, run)
task               Task management (Click: list, show, events, watch, cancel, recover)
agent              Agent operations (Click: plan, run, audit list/show)

# ── Database ──────────────────────────────────────────────────────────────
db                 Database utilities (Click: stats, tables, table)
database           Database utilities — hidden alias (Click: stats, tables, table)

# ── Diagnostics ───────────────────────────────────────────────────────────
doctor             Check configuration, runtime, and optional capabilities
version            Print SPECTRA and Python runtime versions
completion         Generate or install shell completion (bash, zsh, fish)
help               Show help for commands
```

## Notes

- Machine: t420 (Debian/Proxmox, 192.168.1.91) — no AVX, use KEYSTONE_FORCE_SCALAR=1
- User: john
- PII data (sessions, .env, spectra.db) is tracked in this repo — **never push to public origin**
- KEYSTONE libkeystone.so is built but not tracked in git (it's in .gitignore) — rebuild after clone
- QIHSE libqihse.so is pre-built and tracked in the QIHSE submodule

## Known Issues & Fixes (2026-09-03)

### Fixed

- **index_projector.py SyntaxError** (line 1059): f-string `'{}}'` was not escaped
  → fixed to `'{{}}'`. This was breaking all `spectra index drain` calls with
  `SyntaxError: f-string: valid expression required before '}'`.
- **Wrong DB path in intel-analysis systemd service**: was pointing at
  `spectra.db` (134-byte Git-LFS stub) instead of `data/spectra.db` (real DB).
  Every 3-hourly intel analysis run was silently skipping with "Not a SQLite
  database". Fixed in `~/.config/systemd/user/spectra-intel-analysis.service`.
- **Path inconsistency**: 14 scripts hardcoded `/fast/SPECTRA` instead of
  `/fast/home/john/SPECTRA`. Fixed in: continuous_monitor.py, start_monitor.sh,
  watchdog.sh, behavioral_snapshot.py, kp14_media_scanner.py,
  channel_backfill.py, dm_sync.py, typing_analysis.py, corpus_analysis.py,
  import_exports.py, dual_archive.py, atklib_response_analysis.py,
  alias_watch.py, discord_monitor.py, periodic_member_monitor.sh.
- **Dragnet running on dead sessions**: `spectra-dragnet.service` was cycling
  through 50 rotations × 3 dead accounts, downloading 0 messages but exiting 0
  (false "SUCCESS"). Stopped + disabled the service.
- **Member-monitor timer on dead sessions**: `spectra-member-monitor.timer`
  was failing every 30 min with `AuthKeyDuplicatedError`. Timer disabled.

### Needs User Action

- **ALL Telegram sessions are dead**: All 3 dragnet accounts (8000000003,
  8000000001, 8000000002) show `NOT AUTHORIZED`. The string sessions in
  `new_member_monitor.py` (8000000000, 8000000001) get
  `AuthKeyDuplicatedError`. The `.env` sessions (SPECTRA_JOHN, SPECTRA_J)
  are also `NOT AUTHORIZED`. **All sessions need to be re-converted from
  fresh tdata or re-authorized via phone login.** Until then, no Telegram
  crawling/monitoring can occur.
- **DB compact in progress**: `spectra index compact` running on 22GB DB.
  Expected to take 15-30 min. Check with:
  `tail -f /tmp/spectra_compact.log`
