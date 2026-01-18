# Advanced Features Architecture

## Overview

SPECTRA's advanced features use a **dual-database architecture** combining SQLite for structured metadata and QIHSE (Quantum-Inspired Hilbert Space Expansion) for high-dimensional vector storage and semantic search.

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│              SPECTRA Application Layer                    │
│  (TUI, CLI, API, Archiving Workflow)                     │
└─────────────────┬───────────────────────┬───────────────┘
                  │                       │
         ┌────────▼────────┐     ┌───────▼────────┐
         │  SQLite (Primary)│     │  QIHSE Vector  │
         │                 │     │  Store (Primary)│
         ├─────────────────┤     ├────────────────┤
         │ • Metadata      │     │ • Embeddings   │
         │ • Relations     │     │ • Similarity   │
         │ • Users         │     │ • Clustering   │
         │ • Messages      │     │ • Semantic ops │
         │ • Threat scores │     │ • ANN search   │
         │ • FTS5 indexes  │     │ • Direct storage│
         └─────────────────┘     └────────────────┘
                  │                       │
                  └───────────┬───────────┘
                              │
                    Unified Query Layer
                    (Hybrid Results)
```

## Data Flow

### Message Archiving Flow

1. **Message Received** → Telegram API
2. **Structured Data** → SQLite (`messages`, `users`, `media` tables)
3. **Text Content** → Embedding Generation (SentenceTransformers)
4. **Vector Embedding** → QIHSE Vector Store
5. **Metadata Link** → Both databases reference `message_id`

### Search Flow

1. **Query Input** → User search query
2. **Query Processing**:
   - **Keyword Search**: SQLite FTS5 (exact matches, phrases)
   - **Semantic Search**: QIHSE vector similarity (semantic meaning)
   - **Structured Search**: SQLite (filters, date ranges)
3. **Result Fusion** → Combine and rank results
4. **Metadata Enrichment** → Fetch full message data from SQLite
5. **Results** → Returned to user

## Storage Patterns

### SQLite Schema

```sql
-- Core message storage
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    content TEXT,
    user_id INTEGER,
    channel_id INTEGER,
    date TEXT,
    ...
);

-- Vector reference (links to QIHSE)
CREATE TABLE message_vectors (
    message_id INTEGER PRIMARY KEY,
    vector_id TEXT,  -- QIHSE internal ID
    embedding_dim INTEGER,
    indexed_at TEXT
);
```

### QIHSE Storage

- **Vector ID**: `msg_{message_id}` (e.g., `msg_12345`)
- **Vector Data**: 384-dimensional float64 array (default)
- **Metadata Payload**: 
  ```json
  {
    "message_id": 12345,
    "user_id": 1001,
    "channel_id": 5000,
    "threat_score": 8.5,
    "date": "2024-06-15T10:30:00Z"
  }
  ```

## Query Patterns

### 1. Semantic Search

```python
# Find messages semantically similar to query
results = vector_store.semantic_search(
    query_embedding=embed("zero-day exploits"),
    top_k=50,
    filters={"threat_score": {"gte": 7.0}}
)
```

**Process:**
1. Generate embedding for query text
2. QIHSE performs quantum-inspired similarity search
3. Filter by metadata (threat_score, date, etc.)
4. Return top-k most similar vectors
5. Fetch full message data from SQLite

### 2. Hybrid Search

```python
# Combine keyword + semantic search
results = hybrid_engine.search(
    query="APT28 infrastructure",
    search_type=SearchType.HYBRID,
    limit=20
)
```

**Process:**
1. **FTS5**: Find exact keyword matches ("APT28", "infrastructure")
2. **QIHSE**: Find semantically similar messages
3. **Fusion**: Combine results with weighted scoring
4. **Ranking**: Sort by combined relevance score

### 3. Threat Analysis

```python
# Analyze threat actor behavior
patterns = temporal_analyzer.analyze_activity_patterns(user_id)
attribution = attribution_engine.analyze_writing_style(user_id)
```

**Process:**
1. Query SQLite for user's messages
2. Analyze temporal patterns (activity times, bursts)
3. Analyze writing style (vocabulary, sentence structure)
4. Store analysis results in SQLite metadata tables

## Integration Points

### Automatic Vector Indexing

When `advanced_features.vector_database.auto_index_messages` is enabled:

1. **Message Archived** → `CoreOperations.upsert_message()`
2. **Hook Triggered** → `AdvancedFeaturesManager.index_message()`
3. **Embedding Generated** → SentenceTransformers model
4. **Vector Stored** → QIHSE vector database
5. **Link Created** → SQLite `message_vectors` table

### Threat Analysis Integration

When `advanced_features.threat_analysis` is enabled:

1. **Message Archived** → User activity tracked
2. **Batch Analysis** → After N messages (configurable)
3. **Temporal Analysis** → Activity patterns detected
4. **Attribution Analysis** → Writing style profiled
5. **Results Stored** → SQLite `threat_profiles` table

## Performance Characteristics

### QIHSE Advantages

- **Quantum-Inspired Algorithm**: Faster than classical ANN search
- **Direct Storage**: No separate server required (embedded)
- **High Confidence**: Quantum verification reduces false positives
- **Scalability**: Handles millions of vectors efficiently

### Storage Requirements

**Example: 10 Million Messages**

| Component | Size | Notes |
|-----------|------|-------|
| SQLite (metadata) | ~5-10 GB | Text, structured data, indexes |
| QIHSE (384D vectors) | ~15 GB | Raw vectors |
| QIHSE (with quantization) | ~4 GB | 4x compression |
| **Total (optimized)** | ~10-15 GB | |

### Query Performance

- **Semantic Search**: <100ms for 1M vectors (99th percentile)
- **Hybrid Search**: <200ms (combines multiple algorithms)
- **Recall@10**: >95% (search accuracy)

## Configuration

All features controlled via `spectra_config.json`:

```json
{
  "advanced_features": {
    "enabled": true,
    "vector_database": {
      "backend": "qihse",
      "auto_index_messages": true,
      "embedding_model": "all-MiniLM-L6-v2",
      "vector_dimension": 384
    }
  }
}
```

## Error Handling

- **Graceful Degradation**: If QIHSE unavailable, falls back to SQLite-only search
- **Retry Logic**: Automatic retry for transient failures
- **Validation**: Embedding dimension validation before storage
- **Logging**: Comprehensive logging for debugging

## Security Considerations

- **Encryption**: Vector data can be encrypted at rest (CNSA 2.0)
- **Access Control**: Vector operations require proper authentication
- **Audit Trail**: All vector operations logged
- **Data Integrity**: Checksums for vector data
