# QIHSE/KEYSTONE Drain Speedup Plan

> **Goal**: Reduce 907K-event drain from 18.8 hours to <30 minutes (500+ events/sec)

## Current State (baseline)

- 907,618 events processed in ~18.8 hours = **13 events/sec**
- Batch size: 1000, flush every 10 batches / 15s
- Embedding backend: hash bag-of-words (fallback, no SentenceTransformer)
- KEYSTONE: subprocess server with per-event JSON IPC over stdin/stdout
- Projections run serially per event within a batch

## Bottleneck Breakdown

| Phase | Events | Bottleneck | Time share |
|-------|--------|------------|------------|
| Semantic embedding | 708,915 | Hash bag-of-words (CPU, no SIMD) | ~60% |
| KEYSTONE anchors | 856,671 | Subprocess JSON IPC per event | ~20% |
| SQLite projections | 907,618 | FTS5 + content + graph (WAL mode) | ~10% |
| QIHSE vector upsert | 907,618 | In-process C, deferred flush | ~5% |
| Outbox claim/complete | 907,618 | Per-batch overhead | ~5% |

## Optimizations

### #1: SentenceTransformer batch embeddings (10-50x on embedding)

**Problem**: `EmbeddingGenerator` falls back to hash bag-of-words because
`sentence-transformers` is not installed. Hash-bow is pure Python with no SIMD.

**Fix**:
- Install `sentence-transformers` + `scikit-learn` in `.venv`
- Download `all-MiniLM-L6-v2` model (384 dims, <100MB)
- `embed_batch()` already calls `self._st_model.encode(texts, batch_size=...)`
  — ensure `project_batch()` passes all texts in one call
- GPU: if CUDA available, use `device="cuda"` — batch of 1000 in ~0.5s
- CPU: still 5-10x faster than hash-bow with SIMD intrinsics

**Files**: `tgarchive/search/semantic_projection.py`

### #2: KEYSTONE batch insert via in-process ctypes (5-10x on anchors)

**Problem**: `_keystone_lookup()` sends one JSON request per event over
stdin/stdout to a subprocess. 856K events = 856K IPC round-trips.

**Fix**:
- Add `keystone_insert_batch()` ctypes binding to `keystone_bindings.py`
- Use the existing `keystone_search_batch()` C API as a template
- Replace subprocess `_keystone_lookup()` with in-process batch insert
- Batch all KEYSTONE anchors per drain batch, insert in one C call
- Keep subprocess as fallback if C library load fails

**Files**: `tgarchive/search/keystone_bindings.py`, `tgarchive/db/index_projector.py`

### #3: Parallel projection within batch (2-3x overall)

**Problem**: Projections run serially per event: FTS → KEYSTONE → QIHSE → semantic.
With 7 projections × 1000 events = 7000 serial calls per batch.

**Fix**:
- Split projections into independent groups:
  - Group A (SQLite, shared lock): FTS, QIHSE content, graph records
  - Group B (KEYSTONE): anchor inserts (after #2, in-process batch)
  - Group C (QIHSE native): vector upsert (in-process, deferred flush)
  - Group D (Semantic): embedding + vector upsert
- Run groups B, C, D in parallel threads while Group A holds the SQLite connection
- Use `concurrent.futures.ThreadPoolExecutor(max_workers=4)`
- Group A must complete first (it writes projection records that B/C/D consume)

**Files**: `tgarchive/db/index_projector.py`

### #4: Larger batch sizes + flush intervals (2x)

**Problem**: batch_size=1000 with flush every 10 batches = flush every 10K events.
Per-batch overhead (claim, complete, state refresh) is amortized over too few events.

**Fix**:
- Default `batch_size`: 1000 → 5000
- Default `flush_every_batches`: 50 → 20
- Default `flush_interval_seconds`: 60 → 30
- CLI `index drain` and `index watch` updated

**Files**: `tgarchive/cli/app.py`, `tgarchive/operations/builtin.py`

### #5: Contiguous numpy arrays for QIHSE upsert (2x on vector ops)

**Problem**: `upsert_no_flush()` receives `list[list[float]]`, converts each to
a ctypes array. QIHSE's `qihse_vector_db_upsert_by_ids()` expects a contiguous
`float*` — the conversion adds overhead and prevents SIMD optimization.

**Fix**:
- In `QihseVectorIndex.upsert_no_flush()`: convert `vectors` to a single
  `np.float32` contiguous array, pass `.ctypes.data_as(POINTER(c_float))`
- In `IndexProjector._sync_qihse_in_process()`: pass vectors as numpy array
- In `SemanticProjection.project_batch()`: pass embeddings as numpy array
- Verify QIHSE AVX2/AVX512 paths are engaged (check `qihse_cpu_detect` output)

**Files**: `tgarchive/search/qihse_vector_backend.py`, `tgarchive/search/semantic_projection.py`, `tgarchive/db/index_projector.py`

### #6: Skip redundant projections by source_table (1.5x)

**Problem**: Every event runs through all 7 projections. But:
- `fts.messages.v1` only applies to `messages` (not users, support_network)
- `qihse.semantic.v1` only applies to events with text content
- `qihse.graph.v1` only applies to graph-producing events (support_network_edges)
- KEYSTONE anchor projections only apply to specific source_tables

**Fix**:
- Add `_PROJECTIONS_BY_SOURCE_TABLE` mapping
- In `_process_locked()`, filter `PROJECTIONS` to only those relevant
- Skip `_upsert_event()` call for irrelevant projections entirely

**Files**: `tgarchive/db/index_projector.py`

## Implementation Order

1. **#4** (batch size defaults) — trivial, immediate 2x
2. **#6** (skip redundant) — simple filter, 1.5x
3. **#5** (contiguous numpy) — small change, 2x on vector ops
4. **#1** (SentenceTransformer) — install + verify, 10-50x on embedding
5. **#2** (KEYSTONE batch) — ctypes binding + refactor, 5-10x on anchors
6. **#3** (parallel projection) — thread pool, 2-3x overall (depends on #1, #2)

## Expected Combined Throughput

| Scenario | Rate | Time for 907K |
|----------|------|---------------|
| Current | 13/sec | 18.8 hours |
| + #4 (batch size) | 26/sec | 9.7 hours |
| + #6 (skip redundant) | 39/sec | 6.5 hours |
| + #5 (contiguous numpy) | 52/sec | 4.8 hours |
| + #1 (SentenceTransformer) | 260/sec | 58 min |
| + #2 (KEYSTONE batch) | 400/sec | 38 min |
| + #3 (parallel) | 500+/sec | <30 min |
