# Agent Tool Surface

## Goal
Expose SPECTRA's retrieval and intelligence capabilities as a very small, clean tool surface that an LLM agent can call. SPECTRA does deterministic retrieval and evidence construction; the LLM reasons over the results.

## New Files
- `tgarchive/agent/__init__.py`
- `tgarchive/agent/tools.py` — the 5 tool functions
- `tgarchive/agent/tool_schema.py` — JSON schema for each tool
- `tgarchive/tests/test_agent_tools.py` — tests

## The 5 Tools

### 1. spectra.search(query, limit=50, subsystems=None) -> Dict
Unified search across all SPECTRA retrieval subsystems.
```python
def search(query: str, limit: int = 50, subsystems: Optional[List[str]] = None) -> Dict:
    """Search across file, semantic, graph, entity, and hash search.
    
    Returns:
        {
            "candidates": [
                {
                    "object_id": "media:123",
                    "object_type": "media",
                    "score": 0.93,
                    "matched_by": ["filename_fuzzy", "semantic"],
                    "summary": "archive.zip — uploaded by user:456 in channel:789",
                    "context": [...],
                    "provenance": [...]
                }
            ],
            "total_found": 42,
            "subsystems_queried": ["file", "semantic", "graph"],
            "elapsed_ms": 127.3
        }
    """
```

### 2. spectra.expand(object_id, depth=1, relationship_types=None) -> Dict
Expand from a known object to find related objects via graph edges.
```python
def expand(object_id: str, depth: int = 1, relationship_types: Optional[List[str]] = None) -> Dict:
    """Expand network from an object via graph traversal.
    
    Returns:
        {
            "root": {"object_id": "...", "object_type": "..."},
            "neighbors": [
                {"object_id": "...", "object_type": "...", "relationship": "same_actor", "confidence": 0.81}
            ],
            "edges": [...],
            "depth_reached": 1
        }
    """
```

### 3. spectra.timeline(entity_id, start=None, end=None, event_types=None) -> Dict
Get temporal activity for an entity.
```python
def timeline(entity_id: str, start: Optional[str] = None, end: Optional[str] = None, event_types: Optional[List[str]] = None) -> Dict:
    """Get chronological activity for an entity.
    
    Returns:
        {
            "entity_id": "...",
            "events": [
                {"timestamp": "...", "event_type": "message", "channel_id": ..., "summary": "..."}
            ],
            "activity_pattern": {"peak_hours": [...], "inferred_timezone": "..."},
            "change_points": [...]
        }
    """
```

### 4. spectra.resolve(query_or_id) -> Dict
Resolve an entity reference to identity clusters.
```python
def resolve(query_or_id: str) -> Dict:
    """Resolve a mention/username/name/user_id to identity clusters.
    
    Returns:
        {
            "query": "...",
            "clusters": [
                {
                    "cluster_id": "...",
                    "confidence": 0.81,
                    "candidates": [{"type": "username", "value": "..."}, ...],
                    "evidence": [...],
                    "contradicting_evidence": [...]
                }
            ],
            "explanation": "X↔Y has confidence 0.81, derived from 5 observations..."
        }
    """
```

### 5. spectra.evidence(object_id) -> Dict
Get full evidence chain for a conclusion or hypothesis.
```python
def evidence(object_id: str) -> Dict:
    """Get full provenance and evidence chain for an object.
    
    Returns:
        {
            "object_id": "...",
            "object_type": "conclusion",
            "provenance_chain": [
                {"node_id": "...", "algorithm": "...", "version": "...", "confidence": ...}
            ],
            "supporting_evidence": [...],
            "contradicting_evidence": [...],
            "explanation": "This conclusion was derived from..."
        }
    """
```

## Implementation Pattern
Each tool is a thin wrapper that:
1. Validates input
2. Calls the appropriate SPECTRA service (query_planner, cross_index, etc.)
3. Formats output as JSON-serializable dict
4. Includes provenance/explanation where applicable

```python
# tools.py
from ..search.query_planner import QueryPlanner
from ..services.cross_index import cross_index_intelligence
from ..intelligence.entity_resolver_v2 import EntityResolverV2
from ..intelligence.provenance_graph import ProvenGraph

_planner = None
_resolver = None
_provenance = None

def _get_planner():
    global _planner
    if _planner is None:
        _planner = QueryPlanner("spectra.db")
    return _planner

def search(query, limit=50, subsystems=None):
    planner = _get_planner()
    bundle = planner.plan(query, limit=limit, subsystems=subsystems)
    return bundle.to_dict()
```

## CLI Integration
```
spectra agent search "query"
spectra agent expand "media:123" --depth 2
spectra agent timeline "user:456" --start 2026-01-01
spectra agent resolve "@username"
spectra agent evidence "conclusion:789"
```

## Key Constraints
- Tools must be simple functions in tools.py — no classes, no complex state
- Each tool must return a plain dict (JSON-serializable)
- Tools must degrade gracefully if underlying services are unavailable
- Do NOT modify existing service files — only wrap them
- New files only in tgarchive/agent/ and tgarchive/tests/
- Tests must pass: `python3 -m pytest tgarchive/tests/test_agent_tools.py -x`
- Tools should include human-readable "explanation" or "summary" fields for LLM consumption
