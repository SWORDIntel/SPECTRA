# Query Planner + SearchCandidate/EvidenceBundle Schema

## Goal
Build a unified retrieval planner that fuses results from file search, semantic search, QIHSE, entity search, graph search, message search, and hash search using Reciprocal Rank Fusion (RRF).

## New Files (do not modify existing search services)
- `tgarchive/search/query_planner.py` — main planner
- `tgarchive/search/search_candidate.py` — SearchCandidate dataclass
- `tgarchive/search/evidence_bundle.py` — EvidenceBundle dataclass
- `tgarchive/search/rank_fusion.py` — RRF implementation
- `tgarchive/tests/test_query_planner.py` — tests

## SearchCandidate Schema
```python
@dataclass
class SearchCandidate:
    object_id: str          # e.g. "media:123", "message:456", "user:789"
    object_type: str        # "media" | "message" | "person" | "channel" | "entity" | "evidence"
    score: float            # fused score 0-1
    matched_by: List[str]   # ["filename_fuzzy", "semantic", "graph_1hop"]
    sources: List[Dict]     # original source results from each subsystem
    context: List[Dict]     # surrounding context (messages, channels, etc.)
    provenance: List[Dict]  # chain of transformations
```

## EvidenceBundle Schema
```python
@dataclass
class EvidenceBundle:
    query: str
    candidates: List[SearchCandidate]
    total_found: int
    fusion_method: str      # "rrf"
    subsystems_queried: List[str]
    elapsed_ms: float
```

## Query Planner Architecture
```
QUERY
  │
  QueryPlanner.plan(query)
  │
  ├── Determine which subsystems to query based on query type
  │     - filename-like → file_search + hash_search
  │     - text query → semantic_search + message_search + QIHSE
  │     - entity name → entity_search + graph_search
  │     - mixed → all relevant subsystems
  │
  ├── Execute subsystem searches in parallel (asyncio)
  │     Each returns List[SearchCandidate] with subsystem-specific scores
  │
  ├── Reciprocal Rank Fusion
  │     For each candidate across all subsystems:
  │     fused_score = sum(1 / (k + rank_in_subsystem)) for each subsystem
  │     k = 60 (standard RRF constant)
  │     Normalize to 0-1
  │
  ├── Merge matched_by[] from all subsystems for each object_id
  ├── Top-K selection
  └── Return EvidenceBundle
```

## RRF Implementation
```python
def reciprocal_rank_fusion(
    results: Dict[str, List[SearchCandidate]],  # subsystem_name → ranked candidates
    k: int = 60,
    limit: int = 50,
) -> List[SearchCandidate]:
    """Fuse ranked results from multiple subsystems using RRF."""
    scores: Dict[str, float] = {}
    candidates: Dict[str, SearchCandidate] = {}
    
    for subsystem_name, ranked in results.items():
        for rank, candidate in enumerate(ranked, start=1):
            oid = candidate.object_id
            rrf_score = 1.0 / (k + rank)
            scores[oid] = scores.get(oid, 0.0) + rrf_score
            if oid not in candidates:
                candidates[oid] = candidate
            candidates[oid].matched_by.extend(candidate.matched_by)
            candidates[oid].sources.extend(candidate.sources)
    
    # Normalize scores to 0-1
    max_score = max(scores.values()) if scores else 1.0
    for oid in scores:
        candidates[oid].score = scores[oid] / max_score
    
    return sorted(candidates.values(), key=lambda c: c.score, reverse=True)[:limit]
```

## Subsystem Adapters
Each existing search system needs a thin adapter that converts its output to `List[SearchCandidate]`:
- `file_search.py` → adapter wraps `search_files()` results
- `hybrid_search.py` → adapter wraps QIHSE/KEYSTONE results
- `semantic_search.py` → adapter wraps vector results
- Message search → adapter wraps SQLite FTS5 results

Adapters should be in `query_planner.py` as private methods, not separate files.

## CLI Integration
Add `spectra search` command that uses the query planner:
```
spectra search "query" [--subsystems all|file|semantic|graph|entity] [--limit 50] [--json]
```

## Key Constraints
- Do NOT modify existing search service files — only add adapters in query_planner.py
- Do NOT modify schema.py
- All new files in tgarchive/search/ and tgarchive/tests/
- Must work even if some subsystems are unavailable (graceful degradation)
- Each subsystem query should have a timeout (asyncio.wait_for)
- Tests must pass: `python3 -m pytest tgarchive/tests/test_query_planner.py -x`
