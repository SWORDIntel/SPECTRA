# SPECTRA Vector Database & Semantic Search Architecture
## Hybrid Storage: SQLite + Qdrant

---

## Executive Summary

SPECTRA now implements a **hybrid search architecture** combining:
- **SQLite FTS5**: Fast full-text keyword search with BM25 ranking
- **Qdrant**: Scalable vector database for semantic/similarity search
- **Unified API**: Single search interface supporting keyword, semantic, and hybrid queries

This enables:
✓ Keyword-based search (what was searched before)
✓ Semantic search (conceptually similar messages)
✓ Intelligent clustering (organize by topic)
✓ Anomaly detection (find unusual patterns)
✓ Correlation analysis (discover relationships)
✓ Threat scoring (intelligence assessment)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                   SPECTRA Storage & Search                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐           ┌──────────────────┐           │
│  │   SQLite (Disk)  │           │   Qdrant (RAM)   │           │
│  ├──────────────────┤           ├──────────────────┤           │
│  │ • Messages table │           │ • Embeddings     │           │
│  │ • Users table    │           │ • Metadata       │           │
│  │ • Media table    │           │ • Collections    │           │
│  │ • FTS5 index     │           │ • Indexes        │           │
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

### SQLite (Persistent Storage)

**Purpose**: Reliable, transactional storage for message data

**What it stores**:
- Message content and metadata
- User profiles
- Media references
- Channel information
- Full-Text Search Index (FTS5)

**Key features**:
- ACID compliance for reliability
- Foreign key constraints
- WAL mode for concurrent access
- Automatic index triggers

**File location**: `data/spectra.db`

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

### Qdrant (Vector Database)

**Purpose**: High-performance semantic search using embeddings

**What it stores**:
- Vector embeddings (384 dimensions by default)
- Metadata (message_id, channel_id, user_id, date, etc.)
- Points and collections
- Indexes for fast similarity search

**Key features**:
- Cosine similarity for measuring vector distance
- Metadata filtering
- Collection-based organization
- Quantization for memory efficiency
- Built-in scaling to billions of vectors

**Docker container**: `spectra-qdrant:6333`

**API endpoints**:
- REST API: `http://localhost:6333/`
- gRPC API: `localhost:6334`

---

## 3. Embedding Pipeline

### Process Flow

```
Message Input
    │
    ├─→ Store in SQLite ───→ Index in FTS5
    │
    ├─→ Extract text ─────→ SentenceTransformer Model
    │                        (all-MiniLM-L6-v2)
    │
    └─→ Generate embedding ──→ 384-dimensional vector
           (384D vector)       │
                               ├─→ Store in Qdrant
                               │
                               └─→ Link to message_id
```

### Embedding Model

**Model**: `all-MiniLM-L6-v2` (SentenceTransformers)
- **Output dimension**: 384 (can be up to 2048)
- **Training data**: General English text
- **Speed**: ~1000 sentences/second on CPU
- **Memory**: ~400MB for model

**Alternative models** (configurable):
- `all-mpnet-base-v2` (768D) - Better quality, slower
- `all-MiniLM-L6-v2` (384D) - Balanced quality/speed
- `all-MiniLM-L12-v2` (384D) - Lighter weight
- `multilingual-e5-base` (768D) - Multi-language support

### Automatic Indexing

New messages are automatically:
1. Stored in SQLite
2. Indexed in FTS5
3. Embedded and stored in Qdrant

All in a single atomic operation.

---

## 4. Search Methods

### 4.1 Full-Text Search (FTS5)

**How it works**: Keyword matching with BM25 ranking

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

**How it works**: Embedding similarity matching

**Process**:
1. Convert search query to 384D vector
2. Find most similar message vectors
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
- Scales to billions of vectors
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

**Output**:
```python
Cluster(
    cluster_id=0,
    label="Topic 0",
    size=150,
    messages=[123, 124, 125, ...],
    centroid_score=0.85,
    temporal_range=(datetime, datetime)
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

**Output**:
```python
Anomaly(
    message_id=123,
    content="...",
    anomaly_score=0.92,  # 0-1: higher = more anomalous
    anomaly_type="isolated_vector",
    reasoning="Unusual semantic pattern detected"
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

**Output**:
```python
Correlation(
    source_message_id=123,
    target_message_id=456,
    correlation_score=0.85,
    relationship_type="semantic_similarity"
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

# Returns: {
#     "overall_score": 0.72,
#     "factors": {
#         "anomaly_score": 0.8,
#         "keyword_score": 0.6,
#         "behavior_score": 0.75
#     },
#     "risk_level": "medium",  # low|medium|high|critical
#     "reasoning": "..."
# }
```

---

## 6. API Endpoints

### 6.1 Hybrid Search

```
POST /api/search/hybrid

Request:
{
    "query": "suspicious activity",
    "limit": 20,
    "search_type": "hybrid",
    "filters": {
        "channel_id": -1001234567890,
        "user_id": 12345,
        "date_from": "2024-01-01",
        "date_to": "2024-12-31"
    }
}

Response:
{
    "results": [{
        "message_id": 123,
        "content": "...",
        "relevance_score": 0.95,
        "match_type": "hybrid",
        "metadata": {...}
    }],
    "total": 100,
    "search_time_ms": 150,
    "search_type": "hybrid"
}
```

### 6.2 Semantic Search

```
POST /api/search/semantic

Request:
{
    "query": "describe what you're looking for",
    "limit": 20,
    "min_score": 0.5
}
```

### 6.3 Full-Text Search

```
POST /api/search/fulltext

Request:
{
    "query": "keyword search",
    "limit": 20,
    "match_type": "any"
}
```

### 6.4 Clustering

```
POST /api/search/clustering

Request:
{
    "algorithm": "kmeans",
    "n_clusters": 10,
    "parameters": {...}
}

Response:
{
    "clusters": [{
        "cluster_id": 0,
        "label": "Topic Name",
        "size": 150,
        "messages": [...],
        "centroid_score": 0.85
    }],
    "total_clusters": 10,
    "silhouette_score": 0.42
}
```

### 6.5 Anomaly Detection

```
POST /api/search/anomalies

Request:
{
    "algorithm": "isolation_forest",
    "contamination": 0.1
}

Response:
{
    "anomalies": [{
        "message_id": 123,
        "anomaly_score": 0.92,
        "anomaly_type": "isolated_vector",
        "reasoning": "..."
    }],
    "total_anomalies": 45
}
```

### 6.6 Correlation Analysis

```
GET /api/search/<message_id>/correlations?type=semantic&limit=20
```

### 6.7 Threat Scoring

```
GET /api/search/<message_id>/threat-score
```

---

## 7. Performance Characteristics

### Search Performance

| Method | Typical Time | Scales To | Trade-offs |
|--------|-------------|-----------|-----------|
| **FTS5 Keyword** | 10-50ms | 1M+ messages | Keyword matching only |
| **Vector Semantic** | 50-200ms | Billions of vectors | Concept matching |
| **Hybrid** | 100-250ms | Large scale | Combines both |
| **Clustering** | 1-10s | 100K messages | Compute intensive |
| **Anomaly** | 5-30s | 100K vectors | Statistical analysis |

### Memory Usage

| Component | Size |
|-----------|------|
| SQLite database (1M messages) | ~2-5 GB |
| FTS5 index | ~500MB-1GB |
| Qdrant (1M vectors @ 384D) | ~1.5-2 GB |
| Embedding model in RAM | ~400MB |

### Optimization Tips

**For FTS5**:
- Create indexes on frequently filtered columns
- Use composite indexes for common multi-field queries
- Rebuild indexes periodically: `fts5.rebuild_indexes()`

**For Qdrant**:
- Enable quantization for smaller memory footprint
- Use filtering to narrow search space
- Batch upsert operations for speed

**Hybrid**:
- Cache frequently searched queries
- Pre-compute clustering for known topics
- Use result pagination for large result sets

---

## 8. Docker Setup

### Quick Start

```bash
# Start with vector database
docker-compose up -d

# Verify services
docker-compose ps

# Check Qdrant health
curl http://localhost:6333/health

# View logs
docker-compose logs -f spectra
docker-compose logs -f qdrant
```

### Configuration

**Environment variables** (in docker-compose.yml):
```yaml
SPECTRA_QDRANT_ENABLED: "true"
SPECTRA_QDRANT_URL: "http://qdrant:6333"
SPECTRA_EMBEDDING_MODEL: "all-MiniLM-L6-v2"
SPECTRA_EMBEDDING_DIM: "384"
```

### Manual Qdrant Access

```bash
# REST API
curl http://localhost:6333/collections

# Interactive Web UI (if enabled)
# http://localhost:6333/dashboard

# Python client
from qdrant_client import QdrantClient
client = QdrantClient("http://localhost:6333")
collections = client.get_collections()
```

---

## 9. Data Flow Example

### Complete Workflow: New Message Ingestion

```
1. Message arrives from Telegram
   └─→ Extract: content, channel_id, user_id, date

2. Store in SQLite
   └─→ INSERT INTO messages(...)

3. Auto-trigger: FTS5 indexing
   └─→ INSERT INTO messages_fts(...)
   └─→ BM25 index created automatically

4. Generate embedding
   └─→ SentenceTransformer.encode(content)
   └─→ Output: 384D vector

5. Store in Qdrant
   └─→ client.upsert(
       id=message_id,
       vector=embedding,
       payload={channel_id, user_id, date, content}
   )

6. Message now searchable
   ├─→ Via keyword search (FTS5)
   ├─→ Via semantic search (Qdrant)
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
   │   └─→ Search Qdrant for similar vectors
   │   └─→ Results: 120 messages
   │
   └─→ Combine and rank
       ├─→ Normalize scores (0-1)
       ├─→ Weight: FTS5 (40%) + Vector (60%)
       ├─→ Sort by combined score
       └─→ Return top 20

3. Results returned to UI with:
   - Message content
   - Relevance score (0-1)
   - Match type (keyword/semantic/hybrid)
   - Metadata (channel, user, date)
```

---

## 10. Production Deployment

### Pre-deployment Checklist

- [ ] Verify Qdrant service is running
- [ ] Check vector database connection
- [ ] Test FTS5 indexing on sample data
- [ ] Monitor memory usage (Qdrant + embedding model)
- [ ] Set up backup strategy for Qdrant data
- [ ] Configure resource limits for containers
- [ ] Enable authentication for Qdrant API
- [ ] Set up monitoring/alerting for search performance
- [ ] Test failover if Qdrant unavailable
- [ ] Document embedding model version for reproducibility

### Scaling Considerations

**Single deployment** (current):
- SQLite: ~10M messages
- Qdrant: ~10M vectors
- Cost: ~$50-100/month

**Multi-deployment**:
- Qdrant: Scales independently to 100B+ vectors
- SQLite: Consider migration to PostgreSQL with vector extension
- Load balancing: API gateway for search requests

---

## 11. Troubleshooting

### Issue: Qdrant connection refused

```bash
# Check if Qdrant is running
docker-compose ps qdrant

# Check logs
docker-compose logs qdrant

# Restart if needed
docker-compose restart qdrant

# Test connection
curl http://localhost:6333/health
```

### Issue: Embedding model takes too long to download

```bash
# Pre-download model
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Or specify cache directory
export SENTENCE_TRANSFORMERS_HOME=/path/to/models
```

### Issue: Search results are slow

```bash
# Check Qdrant performance
curl http://localhost:6333/collections/spectra_messages

# Monitor resource usage
docker stats spectra-qdrant

# Optimize: Use smaller embedding model
# Or enable quantization in Qdrant
```

---

## 12. Future Enhancements

- [ ] Multi-language embedding support
- [ ] Custom embedding model training
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

- **Qdrant Documentation**: https://qdrant.tech/documentation/
- **SentenceTransformers**: https://www.sbert.net/
- **SQLite FTS5**: https://www.sqlite.org/fts5.html
- **scikit-learn**: https://scikit-learn.org/

---

**Last Updated**: 2024-11-25
**Version**: 1.0.0
**Status**: Production Ready
