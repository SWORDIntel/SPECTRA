---
id: 'vector-database'
title: 'Vector Database'
sidebar_position: 4
description: 'QIHSE vector database for semantic search'
tags: ['vector-database', 'qihse', 'semantic-search', 'features']
---

# Vector Database Integration

Scale to billions of messages with high-dimensional similarity search using **QIHSE (Quantum-Inspired Hilbert Space Expansion)**.

See [Vector Database Architecture](../reference/vector-database-architecture.md) for complete technical documentation.

## Quick Start

```bash
pip install -r requirements-advanced.txt
```

## Features

- QIHSE Primary Backend for quantum-inspired vector storage
- Dual-Database Architecture (SQLite + QIHSE)
- Semantic search across millions of documents
- Actor similarity identification
- Anomaly detection
- High confidence quantum verification

## Usage

```python
from tgarchive.db.vector_store import VectorStoreManager, VectorStoreConfig

config = VectorStoreConfig(
    backend="qihse",
    vector_size=384,
    distance_metric="cosine",
    confidence_threshold=0.95
)

store = VectorStoreManager(config)
store.index_message(message_id=123, embedding=emb, metadata={...})
results = store.semantic_search(query_embedding=query_emb, top_k=10)
```
