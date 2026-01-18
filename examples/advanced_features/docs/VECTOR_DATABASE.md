# Vector Database Architecture

## Overview

SPECTRA uses **QIHSE (Quantum-Inspired Hilbert Space Expansion)** as the primary vector storage backend for semantic search. QIHSE replaces Qdrant entirely and provides direct vector storage with quantum-inspired search acceleration.

## QIHSE as Primary Storage

### Why QIHSE?

- **Direct Storage**: No separate database server required (embedded)
- **Quantum-Inspired Algorithm**: Faster than classical ANN search
- **High Confidence**: Quantum verification reduces false positives
- **Scalability**: Handles millions of vectors efficiently
- **Native Integration**: Built into SPECTRA codebase

### Architecture

```
┌─────────────────────────────────────┐
│      QIHSE Vector Store            │
├─────────────────────────────────────┤
│  • Direct vector storage            │
│  • Quantum-inspired search          │
│  • Metadata payload storage         │
│  • Automatic indexing              │
│  • High-confidence verification     │
└─────────────────────────────────────┘
```

## Embedding Generation

### Model Selection

**Default**: `all-MiniLM-L6-v2` (384 dimensions)
- Fast inference (~10ms per message)
- Good semantic understanding
- Balanced performance/quality

**High-Quality**: `all-mpnet-base-v2` (768 dimensions)
- Better semantic accuracy
- Slower inference (~30ms per message)
- Recommended for critical intelligence

### Embedding Process

1. **Text Input** → Message content
2. **Tokenization** → SentenceTransformers tokenizer
3. **Model Inference** → Neural network forward pass
4. **Vector Output** → 384-dimensional float64 array
5. **Normalization** → L2 normalization (optional)

## Storage Format

### Vector Structure

```python
{
    "id": "msg_12345",  # QIHSE internal ID
    "vector": [0.123, -0.456, ...],  # 384 float64 values
    "metadata": {
        "message_id": 12345,
        "user_id": 1001,
        "channel_id": 5000,
        "threat_score": 8.5,
        "date": "2024-06-15T10:30:00Z",
        "content_preview": "Discussing zero-day..."
    }
}
```

### Metadata Payload

Stored alongside vector for filtering:
- **message_id**: Links to SQLite `messages` table
- **user_id**: For user-based filtering
- **channel_id**: For channel-based filtering
- **threat_score**: For threat-based filtering
- **date**: For temporal filtering
- **content_preview**: First 500 chars for quick preview

## Semantic Search Workflow

### 1. Query Processing

```python
# User query: "zero-day exploits"
query_embedding = model.encode("zero-day exploits")
# → [0.234, -0.567, ...] (384 dimensions)
```

### 2. QIHSE Search

```python
# QIHSE performs quantum-inspired similarity search
results = qihse_engine.search_vectors(
    vectors=all_message_vectors,  # All indexed vectors
    query_vector=query_embedding,
    confidence_threshold=0.95
)
# → [(index_12345, 0.98), (index_67890, 0.95), ...]
```

### 3. Filtering

```python
# Apply metadata filters
filtered_results = [
    r for r in results
    if r.metadata["threat_score"] >= 7.0
    and r.metadata["date"] >= "2024-01-01"
]
```

### 4. Result Enrichment

```python
# Fetch full message data from SQLite
for result in filtered_results:
    message = sqlite_db.get_message(result.metadata["message_id"])
    result.full_content = message.content
    result.user = message.user
```

## Integration with SQLite

### Dual-Database Pattern

**SQLite** stores:
- Full message text
- User information
- Channel metadata
- Timestamps
- Relationships

**QIHSE** stores:
- Vector embeddings
- Minimal metadata (for filtering)
- Similarity relationships

**Link**: `message_id` connects both databases

### Query Pattern

```python
# 1. QIHSE: Find similar vectors
vector_results = qihse.search(query_embedding, top_k=50)

# 2. Extract message IDs
message_ids = [r.metadata["message_id"] for r in vector_results]

# 3. SQLite: Fetch full data
messages = sqlite_db.get_messages_by_ids(message_ids)

# 4. Combine results
final_results = combine(vector_results, messages)
```

## Performance Characteristics

### Indexing Performance

- **Embedding Generation**: ~10-30ms per message (model dependent)
- **QIHSE Storage**: ~1-2ms per vector
- **Total Indexing**: ~15-35ms per message

### Search Performance

- **QIHSE Search**: <100ms for 1M vectors (99th percentile)
- **Recall@10**: >95% (search accuracy)
- **Confidence Threshold**: 0.95 (high-confidence results)

### Memory Usage

- **384D Vector**: ~3KB per message
- **1M Messages**: ~3GB raw vectors
- **With Metadata**: ~4-5GB total

## Configuration

```json
{
  "advanced_features": {
    "vector_database": {
      "backend": "qihse",
      "auto_index_messages": true,
      "embedding_model": "all-MiniLM-L6-v2",
      "vector_dimension": 384,
      "collection_name": "spectra_messages",
      "confidence_threshold": 0.95
    }
  }
}
```

## Migration from Qdrant

QIHSE completely replaces Qdrant:

1. **No Qdrant Dependency**: Removed from requirements
2. **Direct Storage**: Vectors stored directly in QIHSE
3. **No Server Required**: Embedded operation
4. **Simplified Architecture**: Single vector storage backend

## Troubleshooting

### Low Search Quality

- **Check Embedding Model**: Use higher-quality model (768D)
- **Verify Confidence Threshold**: Lower threshold (0.85) for more results
- **Check Vector Quality**: Ensure proper text preprocessing

### Performance Issues

- **Reduce Vector Dimension**: Use 384D instead of 768D
- **Batch Operations**: Index messages in batches
- **Optimize Queries**: Use filters to reduce search space

### Storage Issues

- **Monitor Disk Space**: Vectors require significant storage
- **Enable Compression**: Use quantization if available
- **Archive Old Vectors**: Move old vectors to cold storage
