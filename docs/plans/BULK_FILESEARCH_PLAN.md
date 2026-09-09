# Bulk File Search Architecture — Next Commit

## Problem

Current `search_files()` in `tgarchive/services/file_search.py`:

1. **Row-at-a-time scoring**: Loads ALL media rows into Python, loops each row,
   makes up to 3 Python→ctypes→C calls per row (`_fuzzy_match` on filename,
   title, url). The C binding itself is deliberately tiny — one string pair
   per call.

2. **N+1 password scanning**: `_scan_nearby_for_passwords()` does 4 separate
   SQLite queries PER message ID:
   - message itself
   - nearby messages (`WHERE id BETWEEN ? AND ?`)
   - reply parent
   - reply children

3. **Wrong contextual boundary**: `WHERE id BETWEEN ? AND ?` assumes global
   numerical message-ID proximity = conversational proximity. Breaks with
   multiple channels/accounts/sources.

## Solution

### A. Bulk C scoring API (`fs_batch_score`)

Add to `filesearch_worker.c`:

```c
typedef struct {
    int64_t id;
    char filename[256];
    char title[512];
    char url[1024];
} fs_candidate_t;

typedef struct {
    double score;
    int match_type;  // 0=none, 1=filename_fuzzy, 2=title_fuzzy, 3=url_fuzzy,
                     // 4=filename_exact, 5=title_exact, 6=url_exact, 7=hash
} fs_score_t;

int fs_batch_score(
    const char *query,
    const fs_candidate_t *candidates,
    int count,
    fs_score_t *results,
    double threshold,
    int fuzzy   // 1 = fuzzy match, 0 = exact/substring only
);
```

This scores all candidates in a single C call, eliminating the Python loop
and 3× ctypes overhead per row. The function reuses the existing
`fs_fuzzy_match` internals but operates on the struct array in-place.

### B. FTS5 pre-filtering

Before scoring all media rows, narrow candidates using FTS5:

```sql
-- Create FTS5 index on media filenames/titles (via IndexOutbox projection)
CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(
    filename, title, url, content='media', content_rowid='id'
);
```

Query flow:
1. FTS5 MATCH to get candidate IDs (fast token-based narrowing)
2. SELECT media rows for those IDs only
3. Pack into `fs_candidate_t[]` array
4. Single `fs_batch_score()` call
5. Sort, take top-K

If FTS5 index doesn't exist, fall back to loading all rows (current behavior)
but still use bulk scoring.

### C. Eliminate N+1 password scanning

Replace `_scan_nearby_for_passwords()` with set-based queries:

```python
def _scan_nearby_for_passwords_batch(conn, message_ids, window=5):
    # 1. All messages themselves (1 query)
    msgs = conn.execute(
        "SELECT id, user_id, date, content, reply_to FROM messages WHERE id IN (...)",
        message_ids
    ).fetchall()

    # 2. All reply parents (1 query)
    parent_ids = [m["reply_to"] for m in msgs if m["reply_to"]]
    parents = conn.execute(
        "SELECT id, user_id, date, content FROM messages WHERE id IN (...)",
        parent_ids
    ).fetchall() if parent_ids else []

    # 3. All reply children (1 query)
    children = conn.execute(
        "SELECT id, user_id, date, content, reply_to FROM messages WHERE reply_to IN (...)",
        message_ids
    ).fetchall()

    # 4. Contextual neighbors by channel + timestamp (1 query)
    # Uses channel_messages join to find same-channel messages
    # within a timestamp window, NOT global ID proximity
    neighbors = conn.execute("""
        SELECT m.id, m.user_id, m.date, m.content
        FROM messages m
        JOIN channel_messages cm ON cm.message_id = m.id
        WHERE cm.channel_id IN (
            SELECT channel_id FROM channel_messages WHERE message_id IN (...)
        )
        AND m.date BETWEEN ? AND ?
        AND m.id NOT IN (...)
    """, ...).fetchall()

    # Extract passwords from all collected texts in Python
    # (or batch via native extract_passwords)
```

Total: 4 set-based queries instead of 4×N individual queries.

### D. Fix contextual boundaries

Replace `WHERE id BETWEEN ? AND ?` with channel + timestamp window:

```sql
-- Find messages in the same channel within a time window
SELECT m2.id, m2.user_id, m2.date, m2.content
FROM channel_messages cm1
JOIN channel_messages cm2 ON cm2.channel_id = cm1.channel_id
JOIN messages m2 ON m2.id = cm2.message_id
WHERE cm1.message_id IN (...)
  AND m2.date BETWEEN datetime(?, '-{window} seconds') AND datetime(?, '+{window} seconds')
  AND m2.id NOT IN (...)
```

This makes password association an actual evidence relation based on
conversational proximity (same channel, nearby timestamp) rather than
a lucky adjacency heuristic (global DB ID ± 5).

## Files to change

| File | Change |
|------|--------|
| `tgarchive/native/filesearch_worker.c` | Add `fs_batch_score()` function |
| `tgarchive/native/filesearch_bindings.py` | Add `_FsCandidate`, `_FsScore` structs + `batch_score()` binding |
| `tgarchive/native/Makefile` | Ensure rebuild picks up new symbol |
| `tgarchive/services/file_search.py` | Replace row-at-a-time loop with bulk scoring; replace `_scan_nearby_for_passwords` with set-based batch; fix contextual boundaries |
| `tgarchive/db/schema.py` | Add `media_fts` FTS5 virtual table to schema |

## Verification

1. Build: `cd tgarchive/native && make`
2. Unit test: `python3 -m pytest tgarchive/tests/test_filesearch_native.py -x`
3. Functional test with real data (after crawl):
   ```python
   from tgarchive.services.file_search import search_files
   r = search_files("spectra.db", "test.zip", fuzzy=True)
   print(r["summary"])
   ```
4. Performance: compare rows/sec before and after
