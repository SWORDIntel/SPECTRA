# Intelligence Cross-Index, Pattern Matching, Conclusion Engine & Network Expansion — Plan

**Status: COMPLETE** — All components implemented, tested (42 tests, 130 total passing),
and documented in AGENTS.md.

## Goal

Make intelligence data fully cross-indexed with all other SPECTRA data so
analysts can:

1. Given any entity (user, channel, message, wallet, domain), pull **all**
   evidence, hypotheses, campaigns, and graph edges involving it
2. Run **semantic similarity search** on evidence vectors to find similar
   patterns across actors
3. **Cluster evidence** into patterns and detect recurring behavioral signatures
4. **Draw conclusions** — fuse all evidence about an entity into a ranked
   conclusion with confidence and provenance

## Architecture

```
Entity ID (e.g. telegram:user:123)
  │
  ├── cross_index_intelligence()
  │     ├── SQLite: evidence WHERE subject = ID OR object = ID
  │     ├── SQLite: hypotheses WHERE subject_a = ID OR subject_b = ID
  │     ├── SQLite: campaigns WHERE actors/channels contain ID
  │     ├── KEYSTONE: anchor lookup (intel-evidence, intel-hypotheses)
  │     ├── QIHSE graph: neighbors of entity node
  │     └── QIHSE content: projection records for entity
  │
  ├── pattern_match()
  │     ├── QIHSE vector search: find similar evidence by feature vector
  │     ├── Cluster evidence by type + subject overlap
  │     └── Detect recurring patterns (same evidence_type across actors)
  │
  └── conclude()
        ├── Gather all evidence about entity
        ├── Run fusion engine (EvidenceFusionEngine)
        ├── Add graph context (neighbors, campaigns)
        └── Produce Conclusion with probability, confidence, provenance
```

## Files to Create/Modify

### 1. `tgarchive/services/cross_index.py` (modify)
Add `cross_index_intelligence()` function:
- Input: canonical entity ID (e.g. `telegram:user:123`) or (entity_id, entity_type)
- Query `intelligence_evidence` WHERE subject = ID OR object = ID
- Query `intelligence_hypotheses` WHERE subject_a = ID OR subject_b = ID
- Query `intelligence_campaigns` WHERE actors_json/channels_json contains ID
- Query `index_graph_nodes` + `index_graph_edges` for entity's graph neighborhood
- Query `index_projection_records` for QIHSE content about the entity
- Return structured dict with all intelligence data

Update existing `cross_index()` to also call `cross_index_intelligence()`
and include intelligence data in the result.

### 2. `tgarchive/intelligence/vectors.py` (new)
Intelligence-specific vector backend:
- `IntelligenceVectorIndex` — wraps QihseVectorIndex with a separate .qdb file
  (spectra.db.intelligence.qdb) for evidence feature vectors
- `evidence_to_vector(evidence)` — convert AnalysisEvidence to a feature vector:
  - evidence_type → one-hot encoding
  - score → scaled
  - confidence → scaled
  - direction → one-hot
  - model → hash to vector position
  - metadata keys → hash to vector positions
  - This produces a fixed-dimension vector (64-dim to match VECTOR_DIMENSIONS)
- `upsert_evidence(index, evidence)` — compute vector + upsert
- `search_similar(index, evidence, limit)` — find similar evidence
- `search_by_vector(index, vector, limit)` — raw vector search

### 3. `tgarchive/intelligence/patterns.py` (new)
Pattern matching engine:
- `PatternMatcher` class
- `find_similar_evidence(db_path, evidence, limit)` — vector similarity search
- `cluster_evidence(db_path, entity_id)` — group evidence by type + subject
- `detect_recurring_patterns(db_path, min_cluster_size)` — find evidence types
  that appear across multiple actors (behavioral signatures)
- `find_evidence_clusters(db_path, entity_id)` — connected components of
  evidence sharing subjects/objects
- `Pattern` dataclass: pattern_type, entities, evidence_ids, frequency, confidence

### 4. `tgarchive/intelligence/conclusions.py` (new)
Conclusion engine:
- `Conclusion` dataclass: subject, conclusion_type, probability, confidence,
  supporting_evidence, contradicting_evidence, related_hypotheses,
  campaigns, graph_context, generated_at
- `draw_conclusions(db_path, entity_id)` — given an entity:
  1. Gather all evidence (via cross_index_intelligence)
  2. Gather all hypotheses involving the entity
  3. Gather graph neighborhood
  4. Run fusion on the evidence
  5. Add campaign context
  6. Produce Conclusion with full provenance
- `conclude_actor(db_path, user_id)` — specialized for actor conclusions
  (same-actor hypotheses, threat scores, classifications)

### 5. `tgarchive/intelligence/__init__.py` (modify)
Export new classes: IntelligenceVectorIndex, PatternMatcher, Conclusion,
draw_conclusions, conclude_actor

### 6. `tgarchive/cli/app.py` (modify)
Add CLI commands under `intel` group:
- `spectra intel cross-index <entity_id> --type user|channel|message`
  — full cross-index including intelligence data
- `spectra intel patterns [--entity ID] [--min-cluster N]`
  — find evidence patterns and clusters
- `spectra intel conclude <entity_id> --type user`
  — draw conclusions about an entity
- `spectra intel similar <evidence_id>`
  — find similar evidence via vector search

### 7. Tests
- `tgarchive/tests/test_intelligence_crossindex.py`
- `tgarchive/tests/test_intelligence_patterns.py`

## Key Design Decisions

1. **Separate vector index for intelligence** — don't pollute the content
   vector index with evidence feature vectors. Use a separate .qdb file.

2. **Evidence feature vectors are NOT text vectors** — they encode the
   evidence's analytical properties (type, score, confidence, direction,
   model) so similar evidence (same type, similar score) clusters together.

3. **Cross-index is bidirectional** — evidence points to subjects/objects,
   and the cross-index traverses both directions (find evidence ABOUT an
   entity, not just evidence FROM an entity).

4. **Pattern matching uses vector similarity + structural clustering** —
   vector search finds similar evidence, then clustering groups them by
   shared entities to find patterns.

5. **Conclusions are transparent** — every conclusion shows its provenance
   (which evidence, which hypotheses, which campaigns support it).

6. **Network expansion is analyst-driven** — the analyst provides known
   leaders, the engine discovers connected actors and scores them. Actors
   above a probability threshold are automatically added to a campaign.
   This lets analysts grow their network map from known bad actors to
   the full network of connected actors.

## Network Expansion (Added)

### `tgarchive/intelligence/network_expansion.py` (new)

Given known bad actors (leaders), discovers other actors likely part of
their network:

- **Graph traversal** — hypothesis edges (SAME_ACTOR, ASSOCIATED_WITH)
- **Contact network** — reply/mention interactions
- **Co-channel co-occurrence** — actors posting in same channels
- **Hypothesis links** — existing intelligence hypotheses

Each discovered actor is scored with Bayesian fusion. Actors above
`min_probability` are added to a campaign as network members.

### CLI: `spectra intel expand-network`

```bash
spectra intel expand-network \
  --leaders 123,456,789 \
  --campaign "Op NetworkX" \
  --min-probability 0.6 \
  --max-depth 2
```

Output shows leaders, discovered members (with probability, confidence,
evidence sources, linked-to), suspected actors (below threshold), and
the full graph.
