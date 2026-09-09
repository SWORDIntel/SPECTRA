---
id: 'vector-database-architecture'
title: 'Vector Database Architecture'
sidebar_position: 7
description: 'QIHSE vector database architecture and semantic search'
tags: ['vector-database', 'qihse', 'architecture', 'reference']
---

# SPECTRA Vector Database & Semantic Search Architecture
## Hybrid Storage: SQLite + QIHSE

---

## Executive Summary

SPECTRA implements a **hybrid search architecture** combining:
- **SQLite via QIHSE VFS**: Transactional storage for messages, users, media, and FTS5 full-text index. All SQLite I/O goes through the QIHSE VFS extension (`qihse_vfs.so`).
- **QIHSE native vector engine** (`QihseSearchEngine`): High-dimensional vector storage and cosine similarity search using QIHSE's C-level vector primitives.
- **Unified API**: Single search interface supporting keyword, semantic, and hybrid queries.

> **Note:** Qdrant and ChromaDB are listed as legacy fallbacks in `VectorStoreManager` but are **not installed** in the SPECTRA production environment. QIHSE is the sole production backend. Numpy is a testing-only fallback. The `QdrantVectorManager` class name is a legacy misnomer — it instantiates `VectorStoreManager(backend="qihse")` and uses QIHSE at runtime.

This enables:
- Keyword-based search (FTS5, BM25 ranking)
- Semantic search (conceptually similar messages via vector embeddings)
- Intelligent clustering (organize by topic)
- Anomaly detection (find unusual patterns)
- Correlation analysis (discover relationships)
- Threat scoring (intelligence assessment)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                   SPECTRA Storage & Search                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐           ┌──────────────────┐           │
│  │  SQLite (QIHSE   │           │  QIHSE Vector    │           │
│  │  VFS)            │           │  Engine          │           │
│  ├──────────────────┤           ├──────────────────┤           │
│  │ • Messages table │           │ • Embeddings     │           │
│  │ • Users table    │           │ • Metadata       │           │
│  │ • Media table    │           │ • Collections    │           │
│  │ • FTS5 index     │           │ • Cosine search  │           │
│  │ • Metadata       │           │                  │           │
│  └────────┬─────────┘           └────────┬─────────┘           │
│           │ INSERT/UPDATE/DELETE        │ UPSERT VECTORS       │
│           │                             │                      │
│           └──────────────┬──────────────┘                       │
│                          │                                      │
│                   ┌──────▼───────────┐                          │
│                   │  Hybrid Search   │                          │
│                   │    Engine        │                          │
│                   │                  │                          │
│                   ├─ Keyword Search  │                          │
│                   ├─ Semantic Search │                          │
│                   ├─ Hybrid Query    │                          │
│                   └──────┬───────────┘                          │
│                          │                                      │
│        ┌─────────────────┼─────────────────┐                    │
│        │                 │                 │                    │
│   ┌────▼────┐    ┌──────▼─────┐   ┌──────▼─────┐              │
│   │Clustering│    │  Anomalies │   │Correlation │              │
│   │Engine    │    │ Detection  │   │ Analysis   │              │
│   └──────────┘    └────────────┘   └────────────┘              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Storage Components

### SQLite via QIHSE VFS (Persistent Storage)

**Purpose**: Reliable, transactional storage for message data, accessed through the QIHSE VFS extension.

**What it stores**:
- Message content and metadata
- User profiles
- Media references
- Channel information
- Full-Text Search Index (FTS5)
- IndexOutbox (durable change log for projection)

**Key features**:
- ACID compliance for reliability
- Foreign key constraints
- WAL mode for concurrent access
- Automatic index triggers
- QIHSE VFS for native I/O integration

**VFS protection**: `BaseDB` (`db/db_base.py`) acquires an exclusive `flock` on a sidecar `.lock` file before opening the database. This prevents concurrent opens of the same DB path, which would corrupt QIHSE VFS global state. Process-level flags (`_QIHSE_LIB_LOADED`, `_QIHSE_VFS_LOADED`) ensure `libqihse.so` and `qihse_vfs.so` are loaded exactly once per process — re-loading causes segfaults.

**File location**: `data/spectra.db` (or configured path)

**FTS5 Indexing**:
```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(
    message_id UNINDEXED,
    content,
    user_id UNINDEXED,
    channel_id UNINDEXED,
    date UNINDEXED,
    content='messages',
    content_rowid='id'
);
```

### QIHSE Native Vector Engine

**Purpose**: High-performance semantic search using vector embeddings, powered by QIHSE's C-level vector primitives.

**What it stores**:
- Vector embeddings (384 dimensions by default)
- Metadata (message_id, channel_id, user_id, date, etc.)
- Collections
- Cosine similarity indexes

**Key features**:
- Cosine similarity for measuring vector distance
- Metadata filtering
- Collection-based organization
- Native C implementation (no external service required)
- No Docker container needed — runs in-process
- Air-gapped, no network dependencies

**Backend selection** (`VectorStoreManager`):
1. **QIHSE** (primary, always used in production)
2. Qdrant (legacy fallback — not installed)
3. ChromaDB (legacy fallback — not installed)
4. Numpy (testing only)

**Configuration**:
```python
config = VectorStoreConfig(
    backend="qihse",          # Always "qihse" in production
    path="./data/qihse_vectors",
    collection_name="spectra_messages",
    vector_size=384,
    distance_metric="cosine",
    confidence_threshold=0.95,
)
```

---

## 3. Embedding Pipeline

### Process Flow

```
Message Input
    │
    ├─→ Store in SQLite (QIHSE VFS) ───→ Index in FTS5
    │
    ├─→ Extract text ─────→ SentenceTransformer Model
    │                        (all-MiniLM-L6-v2)
    │
    └─→ Generate embedding ──→ 384-dimensional vector
           (384D vector)       │
                               ├─→ Store in QIHSE vector engine
                               │
                               └─→ Link to message_id
```

### Embedding Model

**Model**: `all-MiniLM-L6-v2` (SentenceTransformers)
- **Output dimension**: 384
- **Training data**: General English text (not fine-tuned on Telegram/threat-intel corpus)
- **Speed**: ~1000 sentences/second on CPU
- **Memory**: ~22M params, ~90MB model, CPU-runnable
- **Air-gapped**: Can be pre-downloaded and cached locally; no runtime network needed

**Fallback**: If `sentence_transformers` is not installed or the model cannot be loaded, `QdrantVectorManager` falls back to a deterministic hash-based 384-dim embedding. Semantic search still works but without real semantic meaning.

**Alternative models** (configurable via `SPECTRA_EMBEDDING_MODEL`):
- `all-mpnet-base-v2` (768D) - Better quality, slower
- `all-MiniLM-L6-v2` (384D) - Balanced quality/speed (default)
- `all-MiniLM-L12-v2` (384D) - Lighter weight
- `multilingual-e5-base` (768D) - Multi-language support

**Future: Domain-specific fine-tuning**: The base model was not trained on cybercrime slang, threat actor handles, wallet addresses, or Telegram-specific jargon. Fine-tuning on the SPECTRA Telegram archive (contrastive pairs from reply chains, shared entities, thread proximity) would improve domain retrieval. Minimum ~20K messages for useful results; 50K+ for robust domain embeddings. This is a future TODO.

### Automatic Indexing

New messages are automatically:
1. Stored in SQLite (via QIHSE VFS)
2. Indexed in FTS5
3. Embedded and stored in QIHSE vector engine

All through the IndexOutbox → IndexProjector pipeline.

---

## 4. Search Methods

### 4.1 Full-Text Search (FTS5)

**How it works**: Keyword matching with BM25 ranking, through SQLite FTS5 (via QIHSE VFS)

**Syntax supported**:
```
Simple:         "word1 word2"
Phrases:        '"exact phrase"'
Boolean:        "word1 OR word2", "word1 AND word2"
Negation:       "NOT word1"
Proximity:      "word1 NEAR word2"
Wildcards:      "word*"
```

**Example**:
```python
results = engine.fts5.search_messages(
    query='"suspicious activity" AND user*',
    limit=20,
    filter_channel=-1001234567890
)
```

**Performance**:
- ~10-50ms for most queries
- Supports 1M+ messages efficiently
- Memory efficient (index is on disk)

### 4.2 Semantic Search (Vector)

**How it works**: Embedding similarity matching via QIHSE vector engine

**Process**:
1. Convert search query to 384D vector (SentenceTransformer or fallback)
2. Find most similar message vectors in QIHSE
3. Return top-K results with similarity scores

**Advantages**:
- Find semantically similar content (even with different words)
- Works with natural language queries
- Captures meaning and context

**Example**:
```python
results = engine.vector.search_semantic(
    query="suspicious user behavior detected",
    limit=20,
    filter_channel=-1001234567890
)
```

**Performance**:
- ~50-200ms for most queries
- Scales to millions of vectors in-process
- Score range: 0.0-1.0 (higher = more similar)

### 4.3 Hybrid Search

**How it works**: Combines FTS5 and vector results

**Process**:
1. Execute both keyword and semantic search in parallel
2. Normalize both scores to 0-1
3. Weighted combination (40% keyword, 60% semantic by default)
4. Rank combined results
5. Return top-K unified results

**Example**:
```python
results = engine.search(
    query="target activity",
    search_type=SearchType.HYBRID,
    limit=20
)
```

**When to use**:
- General intelligence queries
- Don't know if searching for keywords or concepts
- Want comprehensive results from all search methods

---

## 5. Semantic Analysis Features

### 5.1 Message Clustering

**Purpose**: Organize messages into topics

**Algorithms**:

**K-means clustering**:
- Need to specify number of clusters (K)
- Fast and deterministic
- Globular clusters

```python
clusters = engine.clustering.cluster_kmeans(
    n_clusters=10,
    max_iter=100
)
```

**DBSCAN**:
- Automatically finds number of clusters
- Detects outliers
- Handles arbitrary cluster shapes

```python
clusters = engine.clustering.cluster_dbscan(
    eps=0.5,        # Distance threshold
    min_samples=5   # Minimum cluster size
)
```

### 5.2 Anomaly Detection

**Purpose**: Find unusual or suspicious messages

**Algorithms**:

**Isolation Forest**:
- Isolates anomalies by random splitting
- Good for global outliers
- Fast and scalable

```python
anomalies = engine.anomalies.detect_isolation_forest(
    contamination=0.1  # Expected % of anomalies
)
```

**Local Outlier Factor (LOF)**:
- Measures density deviation
- Good for local outliers
- K-NN based approach

```python
anomalies = engine.anomalies.detect_lof(
    n_neighbors=20,
    contamination=0.1
)
```

### 5.3 Correlation Analysis

**Purpose**: Find related messages

**Types**:

**Semantic correlation**:
```python
correlations = engine.correlations.find_semantic_correlations(
    message_id=123,
    limit=20,
    score_threshold=0.7
)
```

**Temporal correlation**:
```python
correlations = engine.correlations.find_temporal_correlations(
    message_id=123,
    time_window_hours=24
)
```

### 5.4 Threat Scoring

**Purpose**: Calculate intelligence/risk scores

**Factors considered**:
- Anomaly score (how unusual)
- Keyword score (threat keywords present)
- Behavior score (user typical behavior)
- Pattern score (network patterns)

**Example**:
```python
score = engine.threat_scoring.calculate_threat_score(
    message_id=123,
    include_anomaly_score=True
)
```

---

## 6. QIHSE RESP Coordination

In addition to the vector engine, QIHSE provides a RESP-compatible server for distributed coordination across SPECTRA nodes.

### RESP Server (`search/qihse_resp_server.py`)

- Wraps the QIHSE C RESP engine
- RESP-compatible protocol (works with Redis clients)
- KV operations: `kv_set`, `kv_get`, `kv_setnx`, `kv_del`, `kv_expire`
- Raw command access: `resp_command(*args)`
- Auth support (AUTH operator <password>)
- Connect-only readiness probes (avoids fd-reuse race in C engine)
- Grace period after short-lived connections to let worker threads clean up

### Coordination Backend (`services/async_file_search.py`)

- `QIHSECoordination`: Uses QIHSE RESP for atomic work assignment (SETNX with TTL)
- `SQLiteCoordination`: Fallback when RESP is unavailable or hangs
- `get_coordination_backend()`: Auto-selects QIHSE, falls back to SQLite
- Auto-fallback: If the QIHSE C RESP engine hangs on a write command, coordination switches to SQLite for all subsequent operations

### Use Case: Distributed File Search

```
Session A ←→ QIHSE RESP ←→ Session B
                │
        Dialog assignment (SETNX)
        Work claims with TTL
        Result storage (SET)
        Heartbeat (INCR)
```

Each session claims dialogs atomically via SETNX. If a session crashes, its claims expire after TTL and another session steals them. Results are aggregated and deduplicated across sessions.

---

## 7. Performance Characteristics

### Search Performance

| Method | Typical Time | Scales To | Trade-offs |
|--------|-------------|-----------|-----------|
| **FTS5 Keyword** | 10-50ms | 1M+ messages | Keyword matching only |
| **Vector Semantic** | 50-200ms | Millions of vectors | Concept matching |
| **Hybrid** | 100-250ms | Large scale | Combines both |
| **Clustering** | 1-10s | 100K messages | Compute intensive |
| **Anomaly** | 5-30s | 100K vectors | Statistical analysis |

### Memory Usage

| Component | Size |
|-----------|------|
| SQLite database (1M messages) | ~2-5 GB |
| FTS5 index | ~500MB-1GB |
| QIHSE vector store (1M vectors @ 384D) | ~1.5-2 GB |
| Embedding model in RAM | ~90-400MB |

### Optimization

**FTS5**:
- Create indexes on frequently filtered columns
- Use composite indexes for common multi-field queries
- Rebuild indexes periodically: `fts5.rebuild_indexes()`

**QIHSE vector engine**:
- Batch upsert operations for speed
- Use filtering to narrow search space
- In-process sync avoids subprocess spawn overhead (IndexProjector)

**Hybrid**:
- Cache frequently searched queries
- Pre-compute clustering for known topics
- Use result pagination for large result sets

---

## 8. Data Flow Example

### Complete Workflow: New Message Ingestion

```
1. Message arrives from Telegram
   └─→ Extract: content, channel_id, user_id, date

2. Store in SQLite (via QIHSE VFS)
   └─→ INSERT INTO messages(...)
   └─→ IndexOutbox.append_to() (durable change log)

3. IndexProjector drains outbox:
   ├─→ FTS5: INSERT INTO messages_fts(...)
   │   └─→ BM25 index created automatically
   ├─→ QIHSE content projection (qihse.content.v1)
   ├─→ KEYSTONE ID anchor (keystone.ids.v1)
   └─→ QIHSE vector engine: upsert embedding

4. Generate embedding
   └─→ SentenceTransformer.encode(content) or deterministic fallback
   └─→ Output: 384D vector

5. Store in QIHSE vector engine
   └─→ vector_store.index_message(message_id, embedding, metadata)

6. Message now searchable
   ├─→ Via keyword search (FTS5)
   ├─→ Via semantic search (QIHSE vectors)
   └─→ Via hybrid search (both)
```

### Complete Workflow: User Search

```
1. User searches: "suspicious activity"

2. Hybrid Search Engine
   ├─→ FTS5: Find keyword matches (BM25 ranked)
   │   └─→ Results: 150 messages
   │
   ├─→ Vector: Generate query embedding
   │   └─→ Search QIHSE vector engine for similar vectors
   │   └─→ Results: 120 messages
   │
   └─→ Combine and rank
       ├─→ Normalize scores (0-1)
       ├─→ Weight: FTS5 (40%) + Vector (60%)
       ├─→ Sort by combined score
       └─→ Return top 20

3. Results returned with:
   - Message content
   - Relevance score (0-1)
   - Match type (keyword/semantic/hybrid)
   - Metadata (channel, user, date)
```

---

## 9. Configuration

### Environment Variables

```bash
SPECTRA_EMBEDDING_MODEL: "all-MiniLM-L6-v2"
SPECTRA_EMBEDDING_DIM: "384"
SPECTRA_QIHSE_VECTOR_PATH: "./data/qihse_vectors"
QIHSE_INDEX_ROOT: "/data/indexes/qihse-api"
```

### Python Configuration

```python
from tgarchive.db.vector_store import VectorStoreManager, VectorStoreConfig

config = VectorStoreConfig(
    backend="qihse",              # Always "qihse" in production
    path="./data/qihse_vectors",
    collection_name="spectra_messages",
    vector_size=384,
    distance_metric="cosine",
    confidence_threshold=0.95,
)

store = VectorStoreManager(config)
store.index_message(message_id=123, embedding=emb, metadata={...})
results = store.semantic_search(query_embedding=query_emb, top_k=10)
```

### Pre-caching the Embedding Model (Air-Gapped)

```bash
# Pre-download model (requires network once)
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Or specify cache directory
export SENTENCE_TRANSFORMERS_HOME=/path/to/models
```

---

## 10. Troubleshooting

### Issue: Semantic search returns no results

```bash
# Check if QIHSE vector store has data
python -c "
from tgarchive.db.vector_store import VectorStoreManager, VectorStoreConfig
s = VectorStoreManager(VectorStoreConfig(backend='qihse'))
print(s.stats())
"

# Check if embedding model is loaded
python -c "
from sentence_transformers import SentenceTransformer
try:
    m = SentenceTransformer('all-MiniLM-L6-v2')
    print('Model loaded:', m.get_sentence_embedding_dimension(), 'dims')
except Exception as e:
    print('Model not available:', e)
    print('Using deterministic fallback (no real semantic meaning)')
"
```

### Issue: QIHSE VFS segfault on DB open

This is caused by concurrent opens of the same database file. `BaseDB` prevents this with an exclusive flock, but if you bypass `SpectraDB` and open `sqlite3.connect()` directly on the same path, you bypass the lock.

**Fix**: Always use `SpectraDB` / `BaseDB` to open the main database. If you need a separate SQLite database (e.g., `LearningStore`, `CommandHistory`), use a different file path.

### Issue: QIHSE RESP server hangs on SET

The QIHSE C RESP engine can hang on write commands because `kv_lock` is held during trinary-trie insertion. The command may time out even though the value was stored.

**Fix**: `QIHSECoordination` has auto-fallback to `SQLiteCoordination`. If a RESP command times out, all subsequent coordination operations use SQLite. This is a workaround; the underlying C engine bug should be fixed in QIHSE.

---

## 11. Future Enhancements

- [ ] Multi-language embedding support
- [ ] Domain-specific embedding model fine-tuning (contrastive pairs from Telegram archive)
- [ ] Incremental clustering updates
- [ ] Real-time anomaly detection
- [ ] User behavior modeling
- [ ] Graph-based correlation analysis
- [ ] Integration with threat intelligence feeds
- [ ] Advanced NLP: NER, sentiment analysis
- [ ] Interactive result refinement
- [ ] Saved search templates

---

## References

- **QIHSE**: In-tree submodule at `QIHSE/` — C database engine with vector, graph, KV, document, and time-series capabilities
- **KEYSTONE**: In-tree submodule at `KEYSTONE/` — interpolation search engine for O(1) ID anchor lookups
- **SentenceTransformers**: https://www.sbert.net/
- **SQLite FTS5**: https://www.sqlite.org/fts5.html
- **scikit-learn**: https://scikit-learn.org/

---

**Last Updated**: 2026-08-22
**Version**: 2.0.0
**Status**: Production Ready (QIHSE-primary)
