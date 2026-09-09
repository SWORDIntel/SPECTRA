---
id: 'vector-database'
title: 'Vector Database'
sidebar_position: 4
description: 'QIHSE vector database for semantic search'
tags: ['vector-database', 'qihse', 'semantic-search', 'features']
---

# Vector Database Integration

Semantic similarity search over archived messages using **QIHSE (Quantum-Inspired Hilbert Space Expansion)** — the sole production vector backend. No external services (Qdrant, ChromaDB) required.

See [Vector Database Architecture](../reference/vector-database-architecture.md) for complete technical documentation.

## Quick Start

No additional packages required — QIHSE is bundled as a C library (`QIHSE/libqihse.so`). For real semantic embeddings (optional but recommended):

```bash
pip install sentence-transformers
# Pre-cache the model (requires network once):
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

If `sentence_transformers` is not installed, a deterministic hash-based fallback embedding is used (search still works, but without real semantic meaning).

## Features

- QIHSE native vector engine (C-level, in-process, no Docker)
- SQLite via QIHSE VFS for transactional storage
- Semantic search across millions of documents
- Actor similarity identification
- Anomaly detection
- High confidence quantum verification
- Air-gapped — no network dependencies at runtime

## Usage

```python
from tgarchive.db.vector_store import VectorStoreManager, VectorStoreConfig

config = VectorStoreConfig(
    backend="qihse",          # Always "qihse" in production
    vector_size=384,
    distance_metric="cosine",
    confidence_threshold=0.95,
)

store = VectorStoreManager(config)
store.index_message(message_id=123, embedding=emb, metadata={...})
results = store.semantic_search(query_embedding=query_emb, top_k=10)
```

## QIHSE RESP Coordination

For distributed file search and password finding across multiple Telegram sessions, QIHSE also provides a RESP-compatible server for atomic work assignment. See [QIHSE RESP Swarm Plan](../../QIHSE_RESP_SWARM_PLAN.md) for details.
