# WP1: Canonical Analysis/Evidence Schema — Implementation Plan

## Context

SPECTRA has 6+ analytical modules each producing incompatible score/dict outputs:
- `threat/indicators.py` → `ThreatIndicator` dataclass (type, value, severity 0-5, level, confidence, context, metadata)
- `threat/scoring.py` → `ThreatActorProfile` dataclass (threat_score 1-10, confidence 0-1, classification, indicators, behavioral_flags, network metrics, CaaS metrics)
- `threat/network.py` → `ActorRelationship` dataclass (interaction_count, total_weight, interaction_types, channels)
- `threat/attribution.py` → `WritingStyleProfile` (vocabulary_size, avg_sentence_length, etc.) + cosine similarity scores + AI likelihood dict
- `threat/temporal.py` → activity patterns dict (peak_hours, inferred_timezone, burst_periods, regularity_score 0-10)
- `osint/intelligence.py` → `classify_actor()` returns {category, confidence, profile}
- `ml/pattern_detector.py` → pattern dicts {type, pattern, frequency, confidence}
- `ml/correlation_engine.py` → correlation dicts {entity1, entity2, strength, type}

**Problem:** Every module has its own score scale, its own confidence semantics, no provenance tracking, no versioning, no negative evidence, no deterministic IDs. Score and confidence are conflated in some modules.

## Goal

Create `tgarchive/intelligence/schema.py` — one versioned, serializable object model for all analytical outputs.

## Objects to Define

### 1. EvidenceSource
Provenance for any evidence — where it came from.
```python
@dataclass
class EvidenceSource:
    source_type: str          # "message", "media", "user", "wallet", "domain", "channel", "graph", "model_inference"
    source_id: str            # canonical ID like "telegram:user:123", "telegram:msg:456:789"
    source_table: str         # SQLite table: "messages", "users", "media", etc.
    source_row_id: int        # rowid in that table
    retrieved_at: datetime    # when SPECTRA accessed it
    raw_snapshot: Optional[str]  # optional JSON snapshot of the source data at time of analysis
```

### 2. AnalysisEvidence
A single observation or measurement. The atomic unit.
```python
@dataclass
class AnalysisEvidence:
    evidence_id: str          # deterministic hash
    evidence_type: str        # "stylometric_similarity", "keyword_indicator", "temporal_overlap", "wallet_overlap", etc.
    subject: str              # canonical entity ID "telegram:user:123"
    object: Optional[str]     # canonical entity ID for pairwise evidence
    score: float              # raw model output (similarity, severity, etc.) — scale depends on type
    confidence: float         # 0-1, how reliable this measurement is (sample size, model quality)
    direction: str            # "supports" | "contradicts" | "neutral"
    model: str                # which model/algorithm produced this
    model_version: str        # semantic version of the model
    feature_schema_version: str  # version of the feature extraction schema
    sources: List[EvidenceSource]  # provenance — which messages/artifacts produced this
    observed_at: datetime     # when the underlying phenomenon occurred
    generated_at: datetime    # when SPECTRA computed this evidence
    metadata: Dict[str, Any]  # type-specific extras (e.g., matched keyword, regex pattern, n-gram)
```

### 3. ModelInference
A model's output — wraps one or more evidence items into a named inference.
```python
@dataclass
class ModelInference:
    inference_id: str         # deterministic hash
    inference_type: str       # "threat_score", "ai_detection", "actor_classification", "stylometric_profile"
    model: str
    model_version: str
    inputs: List[str]         # evidence_ids that fed into this inference
    output: Dict[str, Any]    # the model's structured output
    confidence: float         # 0-1
    generated_at: datetime
    feature_schema_version: str
```

### 4. ActorHypothesis
A claim about actor identity — the core of attribution.
```python
@dataclass
class ActorHypothesis:
    hypothesis_id: str        # deterministic hash
    hypothesis_type: str      # "same_actor", "different_actor", "shared_organization", "automation", "compromised_account", "copied_content"
    subject_a: str            # canonical entity ID
    subject_b: str            # canonical entity ID
    probability: float        # 0-1 posterior probability
    confidence: float         # 0-1 confidence in the probability estimate
    supporting_evidence: List[str]   # evidence_ids
    contradicting_evidence: List[str] # evidence_ids
    insufficient_evidence_flags: List[str]  # feature families with insufficient data
    generated_at: datetime
    model: str
    model_version: str
```

### 5. RelationshipHypothesis
A claim about a relationship between entities (not necessarily actors).
```python
@dataclass
class RelationshipHypothesis:
    hypothesis_id: str
    hypothesis_type: str      # "operates", "associated_with", "uses_wallet", "shared_media", "predicted_link"
    subject: str
    object: str
    probability: float
    confidence: float
    supporting_evidence: List[str]
    contradicting_evidence: List[str]
    generated_at: datetime
    model: str
    model_version: str
```

### 6. Campaign
An operational episode — a cluster of related activity.
```python
@dataclass
class Campaign:
    campaign_id: str          # deterministic or sequential "CAMPAIGN-2026-00981"
    name: str
    actors: List[str]         # canonical entity IDs
    channels: List[str]
    wallets: List[str]
    domains: List[str]
    message_ids: List[str]
    media_ids: List[str]
    start: Optional[datetime]
    end: Optional[datetime]
    confidence: float
    evidence_ids: List[str]   # evidence supporting this campaign grouping
    generated_at: datetime
    metadata: Dict[str, Any]
```

## Critical Design Rules

1. **score != confidence** — score is the raw measurement, confidence is how much we trust it
2. **Every conclusion has provenance** — sources list is mandatory, not optional
3. **Positive AND negative evidence** — ActorHypothesis has both supporting and contradicting evidence
4. **Deterministic IDs** — `evidence_id = sha256(evidence_type + subject + object + model + model_version + sorted source_ids)` truncated to 16 hex chars
5. **Versioning** — every object has model_version and feature_schema_version
6. **JSON serializable** — every dataclass has `to_dict()` and `from_dict()` 
7. **SQL serializable** — every dataclass has `to_sql_row()` returning a tuple for INSERT
8. **Canonical entity IDs** — format: `platform:entity_type:numeric_id` (e.g., `telegram:user:123`)

## SQL Schema Addition

Add to `tgarchive/db/schema.py`:
```sql
CREATE TABLE IF NOT EXISTS intelligence_evidence (
    evidence_id          TEXT PRIMARY KEY,
    evidence_type        TEXT NOT NULL,
    subject              TEXT NOT NULL,
    object               TEXT,
    score                REAL,
    confidence           REAL NOT NULL,
    direction            TEXT NOT NULL DEFAULT 'supports',
    model                TEXT NOT NULL,
    model_version        TEXT NOT NULL,
    feature_schema_version TEXT NOT NULL,
    sources_json         TEXT NOT NULL,    -- JSON array of EvidenceSource
    observed_at          TEXT,
    generated_at         TEXT NOT NULL,
    metadata_json        TEXT
);

CREATE TABLE IF NOT EXISTS intelligence_hypotheses (
    hypothesis_id        TEXT PRIMARY KEY,
    hypothesis_type      TEXT NOT NULL,
    subject_a            TEXT NOT NULL,
    subject_b            TEXT,
    probability          REAL NOT NULL,
    confidence           REAL NOT NULL,
    supporting_evidence  TEXT,    -- JSON array of evidence_ids
    contradicting_evidence TEXT,
    insufficient_flags   TEXT,    -- JSON array
    model                TEXT NOT NULL,
    model_version        TEXT NOT NULL,
    generated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intelligence_campaigns (
    campaign_id          TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    actors_json          TEXT NOT NULL,
    channels_json        TEXT NOT NULL,
    wallets_json         TEXT,
    domains_json         TEXT,
    message_ids_json     TEXT,
    media_ids_json       TEXT,
    start                TEXT,
    end                  TEXT,
    confidence           REAL NOT NULL,
    evidence_ids_json    TEXT,
    generated_at         TEXT NOT NULL,
    metadata_json        TEXT
);
```

## File Structure

```
tgarchive/intelligence/
├── __init__.py
├── schema.py          # All dataclasses + serialization + ID generation
└── (future: fusion.py, resolver.py, etc.)
```

## Tests

```
tgarchive/tests/test_intelligence_schema.py
```

Tests:
- Evidence ID determinism (same inputs → same ID)
- Evidence ID uniqueness (different inputs → different IDs)
- to_dict / from_dict round-trip for all objects
- to_sql_row produces correct tuple
- score != confidence enforced (validation on construction)
- sources list is non-empty (validation)
- JSON serialization is stable
- Canonical entity ID format validation

## Adapter Functions

Add `tgarchive/intelligence/adapters.py` with functions that convert existing module outputs to AnalysisEvidence:

- `threat_indicator_to_evidence(indicator, message_id, user_id, model_version)`
- `threat_profile_to_inferences(profile, model_version)`
- `writing_style_to_evidence(profile_a, profile_b, similarity, model_version)`
- `actor_relationship_to_evidence(rel, model_version)`
- `temporal_analysis_to_evidence(analysis, user_id, model_version)`
- `ai_detection_to_evidence(ai_result, message_ids, model_version)`
- `caas_classification_to_evidence(classification, user_id, model_version)`
