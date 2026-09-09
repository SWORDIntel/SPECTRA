# Entity Resolution v2 + Temporal/Provenance Graph

## Goal
Upgrade the entity resolver from normalization + substring matching to a proper probabilistic resolution layer with independent evidence, and add a temporal/provenance graph that records the full chain of transformations.

## New Files (do not modify existing resolver.py)
- `tgarchive/intelligence/entity_resolver_v2.py` — probabilistic resolver
- `tgarchive/intelligence/provenance_graph.py` — provenance chain tracking
- `tgarchive/intelligence/temporal_graph.py` — temporal behavior graph
- `tgarchive/tests/test_entity_resolver_v2.py` — tests
- `tgarchive/tests/test_provenance_graph.py` — tests

## Entity Resolution Model
```
MENTION (raw text reference to an entity)
  ↓
ENTITY CANDIDATE (normalized form — username, name, handle, phone, etc.)
  ↓
IDENTITY CLUSTER (group of candidates believed to be the same actor)
```

Each identity cluster maintains:
```python
@dataclass
class IdentityCluster:
    cluster_id: str
    candidates: List[EntityCandidate]
    confidence: float                    # P(all candidates = same actor)
    evidence: List[ResolutionEvidence]
    contradicting_evidence: List[ResolutionEvidence]
    model_version: str
    created_at: str
    updated_at: str
```

## Independent Evidence Sources
1. **Username matching** — exact, fuzzy, historical (username changes)
2. **Name matching** — first/last name similarity, transliteration variants
3. **Handle matching** — @handle cross-platform correlation
4. **Identifier matching** — phone numbers (partial match), user IDs
5. **Co-occurrence** — repeated appearance in same channels/contexts
6. **Temporal behavior** — activity patterns, timezone inference, typing patterns
7. **Source consistency** — same bio, same profile photo, same device model

## Probabilistic Resolution
```python
class EntityResolverV2:
    def resolve(self, mention: Mention, existing_clusters: List[IdentityCluster]) -> ResolutionResult:
        # 1. Generate candidate from mention
        candidate = self._normalize(mention)
        
        # 2. Score against each existing cluster
        scores = []
        for cluster in existing_clusters:
            score, evidence = self._score_match(candidate, cluster)
            scores.append((cluster, score, evidence))
        
        # 3. Apply Bayesian fusion
        best_cluster, best_score, best_evidence = self._fuse(scores)
        
        # 4. Decision: merge, create new, or flag for review
        if best_score > 0.85:
            return ResolutionResult(action="merge", cluster=best_cluster, ...)
        elif best_score > 0.5:
            return ResolutionResult(action="review", cluster=best_cluster, ...)
        else:
            return ResolutionResult(action="new_cluster", ...)
```

## Provenance Graph
Every derived object records its full provenance chain:
```python
@dataclass
class ProvenanceNode:
    node_id: str
    node_type: str          # "source_event" | "entity" | "media" | "message" | "evidence" | "hypothesis" | "conclusion"
    algorithm: str          # what produced this
    version: str            # algorithm version
    parameters: Dict        # algorithm parameters
    timestamp: str
    input_ids: List[str]    # what this was derived from
    input_hashes: List[str] # content hashes of inputs
    output_id: str          # this node's ID
    confidence: float
```

```python
class ProvenanceGraph:
    def record_derivation(self, output_id, input_ids, algorithm, version, parameters, confidence):
        """Record that output_id was derived from input_ids by algorithm."""
        
    def trace_provenance(self, object_id) -> List[ProvenanceNode]:
        """Trace full provenance chain backwards from object_id to source events."""
        
    def explain(self, object_id) -> str:
        """Generate human-readable explanation of how object_id was derived."""
```

## Temporal Graph
```python
@dataclass
class TemporalEvent:
    entity_id: str
    event_type: str         # "message" | "join" | "leave" | "name_change" | "username_change"
    timestamp: str
    channel_id: Optional[int]
    metadata: Dict

class TemporalGraph:
    def add_event(self, event: TemporalEvent): ...
    def get_activity_pattern(self, entity_id) -> ActivityPattern: ...
    def infer_timezone(self, entity_id) -> Optional[str]: ...
    def detect_behavioral_change(self, entity_id, window_days=30) -> List[ChangePoint]: ...
```

## Key Constraints
- Do NOT modify existing resolver.py, fusion.py, or schema.py
- New files only in tgarchive/intelligence/ and tgarchive/tests/
- Must integrate with existing AnalysisEvidence / ActorHypothesis architecture
- Provenance must be replayable (change algorithm → replay → new provenance chain)
- Tests must pass: `python3 -m pytest tgarchive/tests/test_entity_resolver_v2.py tgarchive/tests/test_provenance_graph.py -x`
