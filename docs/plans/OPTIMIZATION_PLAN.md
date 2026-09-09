# SPECTRA Optimization Plan

## Current Benchmarks (t420, no AVX)

| Operation | Time | Calls/sec | Notes |
|-----------|------|-----------|-------|
| `_fuzzy_match` (Python SequenceMatcher) | 0.816s / 30k | 36,767/s | Called 3x per media row — #1 bottleneck |
| `_extract_passwords` (Python regex) | 0.878s / 10k | 11,389/s | Called per nearby message |
| `search_files` 500 rows (specific query) | 0.224s | — | 50 matches, 50 passwords |
| `search_files` 500 rows (broad query) | 0.166s | — | 50 matches |
| IndexProjector drain 1000 entries | ~0.3s | — | Subprocess-based projection |

**Codebase size**: 84,337 lines of Python across `tgarchive/`

---

## Optimization Areas

Each section includes **difficulty** (1=trivial, 5=hard) and **% of codebase touched**.

---

### 1. C Native File Search Worker
- **Status**: IN PROGRESS (external agent)
- **Difficulty**: 4/5 — C + ctypes + regex.h + Levenshtein DP
- **Codebase touched**: ~1.5% (new: ~600 lines C + ~150 lines binding + ~30 lines integration in file_search.py)
- **Files**:
  - NEW: `tgarchive/native/filesearch_worker.c` → `filesearch_worker.so`
  - NEW: `tgarchive/native/filesearch_bindings.py` (ctypes)
  - NEW: `tgarchive/native/Makefile`
  - MODIFIED: `tgarchive/services/file_search.py` (delegate to C if available)
  - NEW: `tgarchive/tests/test_filesearch_native.py`
- **What**: `fs_fuzzy_match()` (Levenshtein), `fs_extract_passwords()` (C regex)
- **Fallback**: Python implementations remain if .so not built
- **Expected speedup**: 10-50x fuzzy match, 5-10x password extraction
- **Risk**: C memory safety, cross-platform build issues

---

### 2. SQLite N+1 Query Fix (file_search.py)
- **Difficulty**: 2/5 — straightforward query batching
- **Codebase touched**: ~0.7% (622 lines file, ~80 lines changed)
- **Files**: `tgarchive/services/file_search.py`
- **What**:
  - Preload all message refs: `SELECT ... FROM messages WHERE media_id IN (...)` — one query
  - Preload all channel refs: `SELECT DISTINCT ... FROM channel_messages WHERE media_id IN (...)` — one query
  - Preload all users: `SELECT id, username FROM users WHERE id IN (...)` — one query
  - Build in-memory dicts, look up per-media
  - Add covering indexes on `messages(media_id)`, `channel_messages(media_id)`
- **Expected speedup**: 2-3x for large result sets
- **Risk**: Low — same output format, just fewer queries

---

### 3. Password Regex Precompilation
- **Difficulty**: 1/5 — move `re.search()` strings to module-level `re.compile()`
- **Codebase touched**: ~0.05% (~40 lines changed in file_search.py)
- **Files**: `tgarchive/services/file_search.py`
- **What**: Module-level `re.compile()` for all password patterns, reference compiled objects
- **Expected speedup**: 2-3x for Python fallback path
- **Risk**: None — pure mechanical refactor

---

### 4. IndexOutbox Bulk Append
- **Difficulty**: 2/5 — new method, `executemany()`, single transaction
- **Codebase touched**: ~0.3% (281 lines file, ~60 lines added)
- **Files**: `tgarchive/db/index_outbox.py`
- **What**:
  - Add `bulk_append()` — takes list of events, one `executemany()`, single commit
  - Add `bulk_append_to()` — batch alias matching `append_to()` signature
  - Keep `append_to()` unchanged for backwards compat
- **Expected speedup**: 5-10x for bulk imports
- **Risk**: Low — additive only, no existing behavior changed

---

### 5. IndexProjector Batch Optimization
- **Difficulty**: 5/5 — 2048-line file, subprocess management, projection state machine
- **Codebase touched**: ~2.4% (2048 lines, ~200 lines changed + ~100 lines new)
- **Files**: `tgarchive/db/index_projector.py`
- **What**:
  - Batch claim + process multiple outbox entries per subprocess invocation
  - Cache projection state instead of re-reading per entry
  - Use `executemany()` for bulk SQLite writes within projections
  - Consider in-process projection for QIHSE (avoid subprocess when libqihse.so loaded)
- **Expected speedup**: 3-5x for drain operations
- **Risk**: High — core indexing pipeline, must not break projection correctness

---

### 6. Async File Search — Real Telegram Integration
- **Difficulty**: 4/5 — Telethon async, session management, remote+local merge
- **Codebase touched**: ~1.5% (749 lines file, ~400 lines new + ~100 lines changed)
- **Files**: `tgarchive/services/async_file_search.py`, possibly `tgarchive/services/telegram_file_searcher.py`
- **What**:
  - `TelegramFileSearcher` class — connects via Telethon using session files
  - Download media metadata from assigned channels in parallel
  - Merge remote results with local DB results
  - Use QIHSE task queue (`qihse_task.py`) for true distributed dispatch
- **Expected speedup**: Enables searching channels not yet in local DB (feature, not just perf)
- **Risk**: Medium — Telethon session handling, network errors, rate limits

---

### 7. Steganographic Analysis — Parallel Processing
- **Difficulty**: 3/5 — ProcessPoolExecutor, pickling, result ordering
- **Codebase touched**: ~0.6% (466 lines file, ~80 lines changed)
- **Files**: `tgarchive/services/steganographic_analysis.py`
- **What**:
  - `concurrent.futures.ProcessPoolExecutor` (default 4 workers, configurable)
  - Each worker analyzes one media file (LSB, EOF, EXIF, entropy, format mismatch)
  - Checksum-based skip cache (don't re-analyze)
  - Sequential fallback when workers=1
- **Expected speedup**: 4-8x on t420 (4 cores)
- **Risk**: Medium — pickling issues with file handles, shared state

---

### 8. Bot Detection — Vectorized Timing Analysis
- **Difficulty**: 3/5 — numpy vectorization, SQL window functions
- **Codebase touched**: ~0.5% (459 lines file, ~120 lines changed)
- **Files**: `tgarchive/services/bot_detection.py`
- **What**:
  - Use `numpy` for timestamp arrays (histograms, intervals, autocorrelation)
  - Vectorize message interval regularity
  - Batch user activity with SQL window functions
  - Check numpy availability at import, fall back to pure Python
- **Expected speedup**: 5-20x for large user histories
- **Risk**: Medium — numpy dependency (check if installed), numerical edge cases

---

### 9. Hybrid Search Cache Warming
- **Difficulty**: 4/5 — background threading, KEYSTONE anchor preloading, LRU tuning
- **Codebase touched**: ~1.0% (836 lines file, ~150 lines new + ~50 lines changed)
- **Files**: `tgarchive/search/hybrid_search.py`
- **What**:
  - Warm KEYSTONE anchors on startup for top-N frequent queries
  - Pre-build QIHSE vector index for recent messages (background thread)
  - LRU cache for fuzzy match results (same query+candidate pairs repeat)
- **Expected speedup**: 2-10x for repeated queries
- **Risk**: Medium — background thread lifecycle, cache invalidation

---

### 10. Import Service — Streaming JSON Parse
- **Difficulty**: 3/5 — ijson streaming, chunk processing, progress callbacks
- **Codebase touched**: ~1.1% (942 lines file, ~200 lines changed)
- **Files**: `tgarchive/services/import_service.py`
- **What**:
  - Use `ijson` for streaming JSON parse (handles multi-GB exports)
  - Process messages in chunks of 1000, bulk append to outbox
  - Yield progress callbacks for CLI display
- **Expected speedup**: Eliminates OOM on large exports, 2-3x throughput
- **Risk**: Medium — ijson dependency, streaming parse edge cases

---

## Summary Table

| # | Optimization | Difficulty | % Codebase | Speedup | Status |
|---|--------------|------------|------------|---------|--------|
| 1 | C file search worker | 4/5 | 1.5% | 10-50x | In progress (external) |
| 2 | SQLite N+1 fix | 2/5 | 0.7% | 2-3x | Subagent dispatched |
| 3 | Regex precompilation | 1/5 | 0.05% | 2-3x | Subagent dispatched |
| 4 | IndexOutbox bulk append | 2/5 | 0.3% | 5-10x | Subagent dispatched |
| 5 | IndexProjector batch | 5/5 | 2.4% | 3-5x | Pending |
| 6 | Async Telegram integration | 4/5 | 1.5% | Feature | Pending |
| 7 | Steganographic parallel | 3/5 | 0.6% | 4-8x | Subagent dispatched |
| 8 | Bot detection vectorize | 3/5 | 0.5% | 5-20x | Pending |
| 9 | Hybrid search warming | 4/5 | 1.0% | 2-10x | Pending |
| 10 | Import streaming JSON | 3/5 | 1.1% | 2-3x | Pending |

**Total codebase touched if all done**: ~9.7% (with overlap in file_search.py)

---

## Priority Order (by effort/impact ratio)

1. **Regex precompilation** (diff 1, 2-3x) — trivial, do now
2. **SQLite N+1 fix** (diff 2, 2-3x) — quick win
3. **IndexOutbox bulk append** (diff 2, 5-10x) — needed for imports
4. **C file search worker** (diff 4, 10-50x) — biggest single win, in progress
5. **Steganographic parallel** (diff 3, 4-8x) — easy parallel win
6. **IndexProjector batch** (diff 5, 3-5x) — complex but high value
7. **Bot detection vectorize** (diff 3, 5-20x) — needs numpy check
8. **Import streaming JSON** (diff 3, 2-3x) — needs ijson
9. **Async Telegram integration** (diff 4, feature) — feature gap
10. **Hybrid search warming** (diff 4, 2-10x) — needs usage patterns

---

## Constraints

- No AVX/SSE (t420)
- No cloud LLM APIs
- Local models under 2GB VRAM
- Python 3.13
- Must not break existing tests (280 passing)
- C extensions must have Python fallbacks
- No new heavy dependencies without checking availability
