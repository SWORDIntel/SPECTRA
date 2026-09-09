"""
SPECTRA Intelligence Module
===========================
Canonical evidence schema and analytical pipeline.

All analytical outputs — attribution, scoring, network analysis, temporal
analysis, indicator detection — produce objects defined in ``schema``.
Adapter functions in ``adapters`` convert existing module outputs into
the canonical schema.

The ``resolver`` combines evidence from 6 feature families to produce
P(A=B | E_1, ..., E_n) with full provenance.

The ``fusion`` engine fuses multiple evidence sources into calibrated
posteriors for 6 competing hypotheses with anti-double-counting.

The ``labels`` module provides an append-only analyst label store for
ground-truth feedback (Confirm/Reject/Unsure).

The ``vectors`` module provides a QIHSE-backed vector index for semantic
similarity search on evidence feature vectors.

The ``patterns`` module provides pattern matching — clustering evidence,
detecting recurring behavioral signatures, and finding cross-actor patterns.

The ``conclusions`` module fuses all intelligence about an entity into
ranked conclusions with probability, confidence, and provenance.
"""
from __future__ import annotations

from .schema import (
    SCHEMA_VERSION,
    EvidenceDirection,
    HypothesisType,
    EvidenceSource,
    AnalysisEvidence,
    ModelInference,
    ActorHypothesis,
    RelationshipHypothesis,
    Campaign,
    canonical_id,
    generate_evidence_id,
    generate_hypothesis_id,
    generate_inference_id,
    generate_campaign_id,
)
from .resolver import ActorIdentityResolver
from .fusion import EvidenceFusionEngine, FusionResult
from .labels import (
    AnalystLabel,
    AnalystLabelStore,
    AnalystLabelType,
    AnalystVerdict,
)
from .vectors import (
    IntelligenceVectorIndex,
    evidence_to_vector,
    INTELLIGENCE_VECTOR_DIMENSIONS,
)
from .conclusions import (
    Conclusion,
    draw_conclusions,
    conclude_actor,
    generate_conclusion_id,
)
from .patterns import (
    Pattern,
    PatternMatcher,
    generate_pattern_id,
)
from .network_expansion import (
    NetworkMember,
    NetworkExpansionResult,
    expand_network,
)

__all__ = [
    # Schema
    "SCHEMA_VERSION",
    "EvidenceDirection",
    "HypothesisType",
    "EvidenceSource",
    "AnalysisEvidence",
    "ModelInference",
    "ActorHypothesis",
    "RelationshipHypothesis",
    "Campaign",
    "canonical_id",
    "generate_evidence_id",
    "generate_hypothesis_id",
    "generate_inference_id",
    "generate_campaign_id",
    # Resolver
    "ActorIdentityResolver",
    # Fusion
    "EvidenceFusionEngine",
    "FusionResult",
    # Labels
    "AnalystLabel",
    "AnalystLabelStore",
    "AnalystLabelType",
    "AnalystVerdict",
    # Vectors
    "IntelligenceVectorIndex",
    "evidence_to_vector",
    "INTELLIGENCE_VECTOR_DIMENSIONS",
    # Conclusions
    "Conclusion",
    "draw_conclusions",
    "conclude_actor",
    "generate_conclusion_id",
    # Patterns
    "Pattern",
    "PatternMatcher",
    "generate_pattern_id",
    # Network Expansion
    "NetworkMember",
    "NetworkExpansionResult",
    "expand_network",
]
