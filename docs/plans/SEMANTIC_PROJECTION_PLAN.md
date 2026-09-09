# Move Semantic Search Behind Outbox/QIHSE Projection

## Goal
Retire the standalone `semantic_search.py` (Chroma/numpy island with bugs) and make semantic embeddings a projection produced by the durable indexing pipeline (IndexOutbox → IndexProjector → QIHSE).

## Problem with Current semantic_search.py
- Separate SentenceTransformer → Chroma/numpy storage path
- Module description says Qdrant/hybrid/RAG but implementation is Chroma/numpy
- Documents supplied to Chroma but SearchResult.content populated from metadata["content"] which wasn't added to metadata
- Chroma's distance exposed directly as score despite distance/similarity having opposite interpretation
- numpy fallback doesn't implement same metadata-filter behavior

## Files to Modify
- `tgarchive/search/semantic_search.py` — rewrite to use QIHSE vector store instead of Chroma
- `tgarchive/db/index_projector.py` — add semantic embedding projection
- `tgarchive/db/index_outbox.py` — add semantic projection type (if needed)

## New Files
- `tgarchive/search/semantic_projection.py` — embedding generation + QIHSE projection
- `tgarchive/tests/test_semantic_projection.py` — tests

## Architecture
```
Message/Media saved → IndexOutbox
  → IndexProjector projects to:
      - qihse.content.v1 (existing — full-text + semantic content)
      - qihse.semantic.v1 (NEW — dense vector embeddings for similarity search)
        ↓
      EmbeddingGenerator produces 384-dim or 768-dim vector
        ↓
      QIHSE vector store (spectra.db.semantic.qdb)
        ↓
      semantic_search.py queries QIHSE vector store
```

## Embedding Generation
- Use SentenceTransformer if available (all-MiniLM-L6-v2 = 384 dims, fits under 2GB VRAM)
- Fallback: TF-IDF + TruncatedSVD for CPU-only environments
- Fallback: hash-based bag-of-words vector (no dependencies)
- Embedding model name + version stored as provenance

## Semantic Projection
```python
class SemanticProjection:
    """Project messages/media to QIHSE vector store as semantic embeddings."""
    
    def project(self, outbox_events: List[OutboxEvent]) -> ProjectionResult:
        for event in outbox_events:
            text = self._extract_text(event)
            vector = self._embed(text)
            self.qihse_store.upsert_vector(
                id=f"semantic:{event.source_table}:{event.source_id}",
                vector=vector,
                metadata={
                    "text": text[:500],
                    "source_table": event.source_table,
                    "source_id": event.source_id,
                    "model": self.model_name,
                    "model_version": self.model_version,
                }
            )
```

## Rewritten semantic_search.py
```python
def semantic_search(query, db_path, limit=50, threshold=0.5):
    """Search using QIHSE vector store (not Chroma)."""
    query_vector = embed(query)
    results = qihse_store.search_similar(query_vector, limit=limit, threshold=threshold)
    # Convert QIHSE distance to similarity (1 - distance for cosine)
    return [SearchResult(
        id=r.id,
        content=r.metadata["text"],
        score=1.0 - r.distance,  # FIX: distance != similarity
        metadata=r.metadata,
    ) for r in results]
```

## Key Constraints
- Must work without SentenceTransformer (fallback to TF-IDF or hash vectors)
- Must work without GPU (CPU inference for small models)
- Embedding model + version stored as provenance for replayability
- Do NOT modify schema.py
- Do NOT modify file_search.py or query_planner.py
- Tests must pass: `python3 -m pytest tgarchive/tests/test_semantic_projection.py -x`
- If QIHSE vector bindings unavailable, fall back to numpy with CORRECT distance→similarity conversion
