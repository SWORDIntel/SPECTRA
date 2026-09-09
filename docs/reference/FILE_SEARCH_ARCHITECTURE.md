# File Search Architecture

## Overview

SPECTRA's file search finds media across all archived Telegram channels and
accounts by filename, title, URL, or hash. It uses a native C accelerator
for fuzzy matching and a set-based password scanner for extracting passwords
from nearby messages.

## Architecture

```
Query (filename / hash / partial)
  │
  ├── Hash search? ──→ SQLite checksum LIKE ──→ results
  │
  ├── FTS5 pre-filter (future) ──→ candidate IDs
  │         (media_fts virtual table)
  │
  ├── SQLite candidate generation
  │     SELECT id, filename, title, url FROM media
  │
  ├── Bulk native scorer (single C call)
  │     fs_batch_score(query, candidates[], threshold, fuzzy)
  │     → fs_score_t[] per candidate
  │
  ├── Top-K selection
  │
  ├── Batch relationship fetch (4 set-based queries)
  │     ├── messages WHERE media_id IN (top-K)
  │     ├── channel_messages WHERE media_id IN (top-K)
  │     ├── users WHERE id IN (all referenced user_ids)
  │     └── reply relationships
  │
  ├── Batch password scan (4 set-based queries)
  │     ├── source messages themselves
  │     ├── reply parents
  │     ├── reply children
  │     └── same-channel timestamp neighbors (NOT global ID proximity)
  │
  └── Enriched results with passwords, channels, users, context
```

## Native C Accelerator

### `filesearch_worker.so`

Located at `tgarchive/native/filesearch_worker.so`. Built with:
```bash
cd tgarchive/native && make
```

### APIs

#### `fs_fuzzy_match(query, candidate) -> double`
Single-pair fuzzy match. Returns 0.0-1.0 similarity.
- Exact match (case-insensitive): 1.0
- Query is substring of candidate: 0.9
- Candidate is substring of query: 0.8
- Otherwise: normalized Levenshtein distance

#### `fs_batch_score(query, candidates[], threshold, fuzzy) -> int`
**Bulk scoring** — scores N candidates in a single C call. This is the
primary API for file search, eliminating the Python loop and 3×N ctypes
round-trips.

Operates on `fs_candidate_t[]` struct array:
```c
typedef struct {
    int64_t id;
    char filename[256];
    char title[512];
    char url[1024];
} fs_candidate_t;
```

Returns `fs_score_t[]` with score + match_type per candidate:
```c
typedef struct {
    double score;
    int match_type;  // 0=none, 1=filename_fuzzy, 2=title_fuzzy, ...
} fs_score_t;
```

Match type constants:
| Value | Name | Description |
|-------|------|-------------|
| 0 | `MATCH_NONE` | No match |
| 1 | `MATCH_FILENAME_FUZZY` | Filename fuzzy match |
| 2 | `MATCH_TITLE_FUZZY` | Title fuzzy match |
| 3 | `MATCH_URL_FUZZY` | URL fuzzy match |
| 4 | `MATCH_FILENAME_EXACT` | Filename exact/substring (non-fuzzy mode) |
| 5 | `MATCH_TITLE_EXACT` | Title exact/substring |
| 6 | `MATCH_URL_EXACT` | URL exact/substring |
| 7 | `MATCH_HASH` | Hash match |

#### `fs_extract_passwords(text, filename_hint, out[], max) -> int`
Extracts password-like values from message text using regex patterns.
Returns count of passwords found (max 16).

Detects:
- `password: value` / `pwd = value` / `secret - value`
- `password is value`
- `password → value` (arrow notation)
- `file.zip "password"` (quoted after filename)
- Bare standalone word on next line after file mention

### Python Bindings

`tgarchive/native/filesearch_bindings.py` provides ctypes bindings:
- `fuzzy_match(query, candidate) -> Optional[float]`
- `batch_score(query, candidates, threshold, fuzzy) -> Optional[List[Tuple[float, int]]]`
- `extract_passwords(text, filename_hint) -> Optional[List[Dict]]`
- `match_type_name(match_type) -> str`
- `native_available() -> bool`
- `batch_available() -> bool`

Python fallback is preserved — if the native library is unavailable,
`search_files()` falls back to row-at-a-time `SequenceMatcher` scoring.

## Password Scanning

### Contextual Boundaries

Password association uses **conversational proximity**, not global DB ID
proximity:

```
CORRECT:                           WRONG (old):
same channel                       global DB ID ± 5
+ timestamp window (±5 min)        (breaks with multiple channels)
= actual evidence relation
```

The scanner:
1. Fetches the source message itself
2. Fetches reply parent (true conversational link)
3. Fetches reply children
4. Fetches same-channel messages within ±5 minutes via `channel_messages` join
5. Falls back to ID-proximity only when `channel_messages` table is absent

All fetches are set-based `IN(...)` queries — 4 total, not 4×N.

## FTS5 Media Index

The `media_fts` virtual table provides fast token-based candidate narrowing:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(
    filename, title, url,
    content='media', content_rowid='id'
);
```

This will be populated by the IndexProjector (`fts.media.v1` projection)
as media is ingested. The file-search service will use it to pre-filter
candidates before bulk C scoring, reducing the candidate set from
"all media" to "token-matching media."

## Performance

### Before (row-at-a-time)
```
Python loop over N media rows
  → 3 ctypes calls per row (filename, title, url)
  → 4 SQLite queries per message ID for passwords
Total: 3N ctypes calls + 4M SQLite queries (M = matching messages)
```

### After (bulk)
```
1 ctypes call for all N candidates
  → 4 SQLite queries total for passwords
Total: 1 ctypes call + 4 SQLite queries + 3 set-based IN(...) queries
```

## Files

| File | Purpose |
|------|---------|
| `tgarchive/native/filesearch_worker.c` | C implementation (fuzzy match, batch score, password extraction) |
| `tgarchive/native/filesearch_worker.so` | Compiled shared library |
| `tgarchive/native/filesearch_bindings.py` | ctypes Python bindings |
| `tgarchive/native/Makefile` | Build configuration |
| `tgarchive/services/file_search.py` | Python search service (orchestration + enrichment) |
| `tgarchive/tests/test_filesearch_native.py` | Tests (16 tests: 9 existing + 7 batch scoring) |
| `tgarchive/db/schema.py` | `media_fts` FTS5 virtual table definition |

## Future Work

1. **FTS5 pre-filtering**: Use `media_fts MATCH` to narrow candidates before
   bulk scoring, reducing N from "all media" to "token-matching media"
2. **Unified query planner**: Integrate file search with semantic, graph,
   entity, and hash search via Reciprocal Rank Fusion
3. **Regression corpus**: Freeze 10k-100k real search examples to measure
   ranking changes across versions
