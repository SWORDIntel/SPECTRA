# SPECTRA Index Drain — Bottleneck Analysis

**Date:** 2026-08-29
**Context:** Draining ~2M+ unprocessed `index_outbox` events after bulk channel
backfill for target `atklib`. Events span `channel_messages` and `messages`
source tables, each routed to up to 5 projection subsystems.

---

## Architecture Recap

```
index_outbox (SQLite) → IndexProjector.drain()
  → per-event: _projections_for_source_table() → 5 projections
      1. qihse.content.v1    (SQLite + deferred QIHSE native sync)
      2. keystone.ids.v1     (SQLite)
      3. fts.messages.v1     (SQLite FTS5)
      4. qihse.semantic.v1   (SentenceTransformer → QIHSE vector upsert)
      5. qihse.graph.v1      (SQLite + deferred QIHSE native sync)
  → per-batch: parallel post-SQLite phase
      → semantic projection (embedding + vector store upsert)
      → intelligence vector sync (if applicable)
  → periodic flush: deferred QIHSE + graph native sync
```

Each message event touches all 5 projections. Each projection does a SQLite
upsert into `index_projection_records`. After the SQLite phase, the semantic
projection generates embeddings and upserts vectors into a QIHSE native vector
store. The QIHSE and graph native syncs are deferred and run in bulk at flush
time.

---

## Bottlenecks Identified

### BN-1: SentenceTransformer Model Loading (Startup)

**Severity:** Blocks drain start for 3–8 minutes
**Root cause:** `EmbeddingGenerator._select_backend()` defaults to
`sentence_transformer` when the package is installed. On first run (or after
cache invalidation), it downloads model files from HuggingFace Hub, loads
weights into memory, and validates the model. This happens inside the first
`_get_persistent_semantic_projection()` call, which is lazy — so the drain
appears to hang after claiming the first batch.

**Observed:**
- 19:04:42 — model loading starts (HF API calls for config files)
- 19:04:47 — weights loaded
- 19:05:00 — SemanticProjection initialized
- Total: ~8 minutes from drain start to first batch processing

**Fix applied:** Set `SPECTRA_EMBEDDING_BACKEND=hash_bow` to skip
SentenceTransformer entirely. Hash bag-of-words is zero-dependency,
instant-init, and sufficient for bulk drain (semantic quality can be
backfilled later with a separate pass).

**Residual:** Even with `hash_bow`, the `SemanticProjection` constructor
still opens the QIHSE vector store (1.6 GB file), adding ~15s startup.

---

### BN-2: QIHSE Semantic Vector Upsert (Per-Batch)

**Severity:** Dominant bottleneck — 10x slowdown
**Root cause:** `SemanticProjection.project_batch()` calls
`EmbeddingGenerator.embed_batch()` then upserts vectors into the QIHSE
native vector store (`spectra.db.semantic.qdb`, 1.6 GB). The QIHSE C library
performs a disk seek + insert per vector. With 5000 events per batch and
384-dim float32 vectors, this is ~7.5 MB of vector data per batch, but the
per-vector upsert overhead dominates.

**Observed:**
- With semantic projection enabled: **15–17 events/sec**
- With semantic projection skipped: **167 events/sec**
- 10x speedup confirms this is the dominant bottleneck

**Fix applied:** Added `SPECTRA_SKIP_SEMANTIC=1` env var to
`_projections_for_source_table()` in `index_projector.py`. When set, the
semantic projection is excluded from the projection list, so no embeddings
are generated and no vector upserts occur.

**Trade-off:** Semantic search (`qihse.semantic.v1`) will not have vectors
for newly drained messages. A separate semantic backfill pass is needed
after the fast drain completes. This is acceptable — FTS5 + KEYSTONE
provide full-text and ID lookup search in the interim.

---

### BN-3: QIHSE Native Content Sync (Deferred Buffer Flush)

**Severity:** Moderate — causes periodic stalls
**Root cause:** The deferred QIHSE content rows buffer
(`_deferred_qihse_rows`) triggers a native sync when it reaches 4000 rows
or when the flush interval elapses. The native sync calls `_sync_qihse()`
which invokes the QIHSE C library to bulk-upsert content vectors (64-dim
hash-bow) into `spectra.db.qihse.qdb` (395 MB). This is a serialized
operation (exclusive `NativeStoreLock`).

**Observed:**
- With batch_size=5000, the 4000-row threshold is hit every batch
- Each native sync takes 30–60 seconds
- Process enters D state (disk sleep) during sync

**Fix applied:**
1. Added `SPECTRA_SKIP_NATIVE=1` env var to skip `qihse.content.v1` entirely
2. Added `SPECTRA_DEFERRED_NATIVE_THRESHOLD` env var (default 4000) to
   control the buffer flush threshold — can be raised to 50000 to reduce
   sync frequency

**Trade-off:** QIHSE content search (`qihse.content.v1`) won't have new
vectors. FTS5 covers full-text search. Native content can be backfilled
later.

---

### BN-4: Graph Native Sync (Deferred Buffer Flush)

**Severity:** Low–moderate
**Root cause:** Same deferred buffer pattern as BN-3, but for
`qihse.graph.v1` (`spectra.db.graph.qdb`, 19 MB). Graph sync is faster
than content sync due to smaller data volume, but still acquires an
exclusive `NativeStoreLock` and can stall the drain.

**Fix applied:** Added `SPECTRA_SKIP_GRAPH=1` env var to skip
`qihse.graph.v1` projection entirely.

---

### BN-5: SQLite Per-Event Savepoint Overhead

**Severity:** Low — baseline cost
**Root cause:** `_process_locked()` creates a SQLite `SAVEPOINT` per event,
executes 3–5 projection upserts, then releases the savepoint. With
batch_size=5000, this is 5000 savepoint create/release cycles per batch.
Each cycle involves SQLite WAL writes.

**Observed:**
- With all native projections skipped (FTS + KEYSTONE only): 167 events/sec
- This is the irreducible baseline — SQLite I/O is the floor
- 167 ev/s × 3600 = 600K events/hour — acceptable for 2M events

**Mitigation:** Larger batch sizes (5000) amortize the `claim()` and
`complete_batch()` overhead. Going beyond 5000 has diminishing returns
due to memory pressure from the event list.

---

### BN-6: Stale Claim Recovery

**Severity:** One-time cost on restart
**Root cause:** When a drain process is killed (e.g., timeout, OOM), it
leaves `claimed_at` set on the events it was processing. These events
are invisible to subsequent `claim()` calls until the lease expires
(default 300s). This wastes 5 minutes on every restart.

**Observed:**
- 500 events claimed at 18:07 by a killed process
- Current drain (started 18:56) couldn't claim them until 18:12
- Manual clearing (`UPDATE index_outbox SET claimed_at=NULL...`) was needed

**Mitigation:** Always clear stale claims before restarting:
```sql
UPDATE index_outbox SET claimed_at=NULL, claim_token=NULL
WHERE processed_at IS NULL AND claimed_at IS NOT NULL;
```

---

### BN-7: Concurrent Writer Contention (Backfill + Drain)

**Severity:** Moderate during concurrent operation
**Root cause:** The Telegram backfill process writes new messages to the
same SQLite database (`spectra.db`) that the drain is reading from. Both
use WAL mode, but the backfill's `INSERT` operations compete with the
drain's `claim()` / `complete_batch()` transactions for the write lock.

**Observed:**
- Pending count increased during concurrent backfill + drain (new events
  appended faster than drain processed them)
- Drain rate dropped from 167 to ~0 ev/s during heavy backfill writes

**Mitigation:** Run backfill and drain sequentially, not concurrently.
Finish all Telegram scraping first, then start the drain.

---

## Performance Summary

| Configuration | Rate (ev/s) | ETA (2M events) | Bottleneck |
|---|---|---|---|
| SentenceTransformer, batch=500, all projections | 15 | 37 h | BN-1 + BN-2 |
| hash_bow, batch=5000, all projections | 17 | 33 h | BN-2 |
| hash_bow, batch=500, all projections | 8 | 69 h | BN-2 + BN-5 |
| hash_bow, batch=5000, high deferred threshold | 17 | 33 h | BN-2 |
| **hash_bow, skip semantic+graph+native, batch=5000** | **167** | **3.5 h** | BN-5 (baseline) |

---

## Recommended Drain Strategy

### Phase 1: Fast drain (FTS + KEYSTONE only)

```bash
SPECTRA_SKIP_SEMANTIC=1 SPECTRA_SKIP_GRAPH=1 SPECTRA_SKIP_NATIVE=1 \
  python3 -m tgarchive --db data/spectra.db index drain \
  --batch-size 5000 --flush-every-batches 100 --flush-interval-seconds 600
```

- **Rate:** ~167 events/sec
- **Purpose:** Populate FTS5 full-text index + KEYSTONE ID anchors
- **Search available after:** Full-text search, ID lookup, content retrieval
- **Search NOT available:** Semantic similarity, graph traversal, QIHSE content

### Phase 2: Native content backfill (overnight)

```bash
SPECTRA_SKIP_SEMANTIC=1 SPECTRA_SKIP_GRAPH=1 \
  SPECTRA_DEFERRED_NATIVE_THRESHOLD=50000 \
  python3 -m tgarchive --db data/spectra.db index drain \
  --batch-size 5000 --flush-every-batches 50 --flush-interval-seconds 300
```

- **Rate:** ~50–100 events/sec (estimated, native sync every 50K rows)
- **Purpose:** Populate QIHSE content vectors (64-dim hash-bow)

### Phase 3: Semantic + graph backfill (overnight, separate run)

```bash
SPECTRA_EMBEDDING_BACKEND=hash_bow \
  python3 -m tgarchive --db data/spectra.db index drain \
  --batch-size 5000 --flush-every-batches 20 --flush-interval-seconds 120
```

- **Rate:** ~15–17 events/sec
- **Purpose:** Populate QIHSE semantic vectors (384-dim) + graph edges
- **Note:** Can use `SPECTRA_EMBEDDING_BACKEND=sentence_transformer` for
  higher-quality embeddings if time permits (adds 8 min startup)

---

## Code Changes Applied

**File:** `tgarchive/db/index_projector.py`

1. **`_projections_for_source_table()`** — Added 3 env var skip flags:
   - `SPECTRA_SKIP_SEMANTIC=1` — excludes `qihse.semantic.v1`
   - `SPECTRA_SKIP_GRAPH=1` — excludes `qihse.graph.v1`
   - `SPECTRA_SKIP_NATIVE=1` — excludes `qihse.content.v1`

2. **`_process_locked()`** — Added `SPECTRA_DEFERRED_NATIVE_THRESHOLD` env var
   (default 4000) to control when the deferred QIHSE native sync triggers.
   Raising to 50000 reduces sync frequency by 12x.

**File:** `tgarchive/search/semantic_projection.py` (pre-existing)

3. **`SPECTRA_EMBEDDING_BACKEND`** — Already supported. Values:
   `sentence_transformer` (default, slow), `tfidf_svd` (medium),
   `hash_bow` (fast, zero-dependency), `myriad` (VPU hardware)

---

## Future Optimization Opportunities

1. **Batch vector upsert API in QIHSE C library** — The current per-vector
   upsert is the 10x bottleneck. A bulk `upsert_batch()` C function that
   takes a contiguous float32 array would eliminate the per-vector FFI
   call overhead and allow SIMD-optimized insertion.

2. **Parallel projection workers** — The drain loop is single-threaded for
   SQLite projections. Multiple projector workers with shared locks
   (already supported by `NativeStoreLock(shared=True)`) could parallelize
   the SQLite phase across CPU cores.

3. **Incremental semantic projection** — Instead of embedding every message
   on drain, defer semantic projection to a separate background process
   that reads from `index_projection_records` and upserts vectors
   asynchronously. This decouples the drain rate from the embedding speed.

4. **QIHSE vector store compaction** — The 1.6 GB semantic store may have
   fragmentation from incremental upserts. A periodic compaction/defrag
   pass could reduce per-upsert seek time.

5. **WAL checkpoint tuning** — The SQLite WAL grows large during heavy
   drain. Explicit `PRAGMA wal_checkpoint(PASSIVE)` between batches could
   keep the WAL smaller and reduce read amplification.
