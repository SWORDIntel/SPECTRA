"""
SPECTRA Canonical Intelligence Evidence Schema
==============================================
Versioned, serializable object model for all analytical outputs.

Every conclusion produced by SPECTRA's analytical modules — attribution,
scoring, network analysis, temporal analysis, indicator detection — is
represented as one of the objects defined here.

Design rules:
1. score != confidence — score is the raw measurement, confidence is how
   much we trust it (sample size, model quality, etc.)
2. Every conclusion has provenance — the sources list is mandatory
3. Positive AND negative evidence — hypotheses carry both supporting and
   contradicting evidence IDs
4. Deterministic IDs — same inputs always produce the same evidence_id
5. Versioning — every object records model_version and feature_schema_version
6. JSON + SQL serializable — every dataclass has to_dict(), from_dict(),
   and to_sql_row()
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, fields, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


# ─── Enums ──────────────────────────────────────────────────────────────────

class EvidenceDirection(Enum):
    """Direction of evidence relative to a hypothesis."""
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"


class HypothesisType(Enum):
    """Types of actor identity hypotheses."""
    SAME_ACTOR = "same_actor"
    DIFFERENT_ACTOR = "different_actor"
    SHARED_ORGANIZATION = "shared_organization"
    AUTOMATION = "automation"
    COMPROMISED_ACCOUNT = "compromised_account"
    COPIED_CONTENT = "copied_content"


# ─── Helpers ────────────────────────────────────────────────────────────────

def canonical_id(platform: str, entity_type: str, numeric_id: Any) -> str:
    """Build a canonical entity ID: 'telegram:user:123'."""
    return f"{platform}:{entity_type}:{numeric_id}"


def _now_utc() -> datetime:
    """Current UTC-aware datetime."""
    return datetime.now(timezone.utc)


def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Serialize datetime to ISO string, handling naive datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _iso_to_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse ISO string back to datetime."""
    if s is None or s == "":
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def generate_evidence_id(
    evidence_type: str,
    subject: str,
    object: Optional[str],
    model: str,
    model_version: str,
    sources: List[EvidenceSource],
) -> str:
    """Deterministic 16-hex-char ID for an AnalysisEvidence.

    Same inputs always produce the same ID. Source order does not matter
    (source_ids are sorted before hashing).
    """
    source_ids = sorted(s.source_id for s in sources)
    payload = (
        evidence_type
        + "|"
        + subject
        + "|"
        + (object or "")
        + "|"
        + model
        + "|"
        + model_version
        + "|"
        + "".join(source_ids)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def generate_hypothesis_id(
    hypothesis_type: str,
    subject_a: str,
    subject_b: str,
    model: str,
    model_version: str,
) -> str:
    """Deterministic 16-hex-char ID for a hypothesis."""
    payload = (
        hypothesis_type
        + "|"
        + subject_a
        + "|"
        + subject_b
        + "|"
        + model
        + "|"
        + model_version
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def generate_inference_id(
    inference_type: str,
    model: str,
    model_version: str,
    inputs: List[str],
) -> str:
    """Deterministic 16-hex-char ID for a ModelInference."""
    sorted_inputs = sorted(inputs)
    payload = (
        inference_type
        + "|"
        + model
        + "|"
        + model_version
        + "|"
        + "".join(sorted_inputs)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def generate_campaign_id(
    name: str,
    actors: List[str],
    model: str,
    model_version: str,
) -> str:
    """Deterministic 16-hex-char ID for a Campaign."""
    sorted_actors = sorted(actors)
    payload = name + "|" + model + "|" + model_version + "|" + "".join(sorted_actors)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ─── EvidenceSource ─────────────────────────────────────────────────────────

@dataclass
class EvidenceSource:
    """Provenance for a piece of evidence — where it came from."""
    source_type: str           # "message", "media", "user", "wallet", "domain", "channel", "graph", "model_inference"
    source_id: str             # canonical ID: "telegram:user:123", "telegram:msg:456:789"
    source_table: str          # SQLite table: "messages", "users", "media", etc.
    source_row_id: int         # rowid in that table
    retrieved_at: datetime     # when SPECTRA accessed it
    raw_snapshot: Optional[str] = None  # optional JSON snapshot of source data

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_table": self.source_table,
            "source_row_id": self.source_row_id,
            "retrieved_at": _dt_to_iso(self.retrieved_at),
            "raw_snapshot": self.raw_snapshot,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvidenceSource":
        return cls(
            source_type=d["source_type"],
            source_id=d["source_id"],
            source_table=d["source_table"],
            source_row_id=d["source_row_id"],
            retrieved_at=_iso_to_dt(d.get("retrieved_at")) or _now_utc(),
            raw_snapshot=d.get("raw_snapshot"),
        )

    def to_sql_row(self) -> Tuple:
        """Return a tuple for SQL insert (as part of a JSON column)."""
        return (
            self.source_type,
            self.source_id,
            self.source_table,
            self.source_row_id,
            _dt_to_iso(self.retrieved_at),
            self.raw_snapshot,
        )


# ─── AnalysisEvidence ───────────────────────────────────────────────────────

@dataclass
class AnalysisEvidence:
    """
    A single observation or measurement — the atomic unit of intelligence.

    score: raw model output (similarity, severity, etc.) — scale depends on type.
    confidence: 0-1, how reliable this measurement is (sample size, model quality).
    These are NOT the same thing.
    """
    evidence_id: str
    evidence_type: str          # "stylometric_similarity", "keyword_indicator", etc.
    subject: str                # canonical entity ID "telegram:user:123"
    object: Optional[str]       # canonical entity ID for pairwise evidence
    score: float                # raw measurement
    confidence: float           # 0-1 reliability
    direction: EvidenceDirection
    model: str
    model_version: str
    feature_schema_version: str
    sources: List[EvidenceSource]
    observed_at: datetime
    generated_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Auto-generate ID if empty
        if not self.evidence_id:
            self.evidence_id = generate_evidence_id(
                self.evidence_type,
                self.subject,
                self.object,
                self.model,
                self.model_version,
                self.sources,
            )
        # Validate confidence range
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        # Validate sources non-empty
        if not self.sources:
            raise ValueError("AnalysisEvidence.sources must not be empty")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "subject": self.subject,
            "object": self.object,
            "score": self.score,
            "confidence": self.confidence,
            "direction": self.direction.value,
            "model": self.model,
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
            "sources": [s.to_dict() for s in self.sources],
            "observed_at": _dt_to_iso(self.observed_at),
            "generated_at": _dt_to_iso(self.generated_at),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AnalysisEvidence":
        direction = d["direction"]
        if isinstance(direction, str):
            direction = EvidenceDirection(direction)
        return cls(
            evidence_id=d.get("evidence_id", ""),
            evidence_type=d["evidence_type"],
            subject=d["subject"],
            object=d.get("object"),
            score=d["score"],
            confidence=d["confidence"],
            direction=direction,
            model=d["model"],
            model_version=d["model_version"],
            feature_schema_version=d["feature_schema_version"],
            sources=[EvidenceSource.from_dict(s) for s in d.get("sources", [])],
            observed_at=_iso_to_dt(d.get("observed_at")) or _now_utc(),
            generated_at=_iso_to_dt(d.get("generated_at")) or _now_utc(),
            metadata=d.get("metadata", {}),
        )

    def to_sql_row(self) -> Tuple:
        """Tuple matching intelligence_evidence table columns."""
        import json as _json
        return (
            self.evidence_id,
            self.evidence_type,
            self.subject,
            self.object,
            self.score,
            self.confidence,
            self.direction.value,
            self.model,
            self.model_version,
            self.feature_schema_version,
            _json.dumps([s.to_dict() for s in self.sources]),
            _dt_to_iso(self.observed_at),
            _dt_to_iso(self.generated_at),
            _json.dumps(self.metadata) if self.metadata else None,
        )


# ─── ModelInference ─────────────────────────────────────────────────────────

@dataclass
class ModelInference:
    """A model's structured output — wraps one or more evidence items."""
    inference_id: str
    inference_type: str        # "threat_score", "ai_detection", "actor_classification"
    model: str
    model_version: str
    inputs: List[str]          # evidence_ids that fed into this inference
    output: Dict[str, Any]
    confidence: float
    generated_at: datetime
    feature_schema_version: str

    def __post_init__(self):
        if not self.inference_id:
            self.inference_id = generate_inference_id(
                self.inference_type,
                self.model,
                self.model_version,
                self.inputs,
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inference_id": self.inference_id,
            "inference_type": self.inference_type,
            "model": self.model,
            "model_version": self.model_version,
            "inputs": self.inputs,
            "output": self.output,
            "confidence": self.confidence,
            "generated_at": _dt_to_iso(self.generated_at),
            "feature_schema_version": self.feature_schema_version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ModelInference":
        return cls(
            inference_id=d.get("inference_id", ""),
            inference_type=d["inference_type"],
            model=d["model"],
            model_version=d["model_version"],
            inputs=d.get("inputs", []),
            output=d.get("output", {}),
            confidence=d["confidence"],
            generated_at=_iso_to_dt(d.get("generated_at")) or _now_utc(),
            feature_schema_version=d["feature_schema_version"],
        )

    def to_sql_row(self) -> Tuple:
        import json as _json
        return (
            self.inference_id,
            self.inference_type,
            self.model,
            self.model_version,
            _json.dumps(self.inputs),
            _json.dumps(self.output),
            self.confidence,
            _dt_to_iso(self.generated_at),
            self.feature_schema_version,
        )


# ─── ActorHypothesis ────────────────────────────────────────────────────────

@dataclass
class ActorHypothesis:
    """
    A claim about actor identity — the core of attribution.

    Carries both supporting AND contradicting evidence, plus flags for
    feature families with insufficient data.
    """
    hypothesis_id: str
    hypothesis_type: HypothesisType
    subject_a: str
    subject_b: str
    probability: float          # 0-1 posterior
    confidence: float           # 0-1 confidence in the probability estimate
    supporting_evidence: List[str] = field(default_factory=list)
    contradicting_evidence: List[str] = field(default_factory=list)
    insufficient_evidence_flags: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=_now_utc)
    model: str = ""
    model_version: str = ""

    def __post_init__(self):
        if not self.hypothesis_id:
            htype = self.hypothesis_type.value if isinstance(self.hypothesis_type, HypothesisType) else str(self.hypothesis_type)
            self.hypothesis_id = generate_hypothesis_id(
                htype,
                self.subject_a,
                self.subject_b,
                self.model,
                self.model_version,
            )
        if not (0.0 <= self.probability <= 1.0):
            raise ValueError(
                f"probability must be in [0.0, 1.0], got {self.probability}"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )

    def to_dict(self) -> Dict[str, Any]:
        htype = self.hypothesis_type.value if isinstance(self.hypothesis_type, HypothesisType) else self.hypothesis_type
        return {
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_type": htype,
            "subject_a": self.subject_a,
            "subject_b": self.subject_b,
            "probability": self.probability,
            "confidence": self.confidence,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "insufficient_evidence_flags": self.insufficient_evidence_flags,
            "generated_at": _dt_to_iso(self.generated_at),
            "model": self.model,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActorHypothesis":
        htype = d["hypothesis_type"]
        if isinstance(htype, str):
            htype = HypothesisType(htype)
        return cls(
            hypothesis_id=d.get("hypothesis_id", ""),
            hypothesis_type=htype,
            subject_a=d["subject_a"],
            subject_b=d["subject_b"],
            probability=d["probability"],
            confidence=d["confidence"],
            supporting_evidence=d.get("supporting_evidence", []),
            contradicting_evidence=d.get("contradicting_evidence", []),
            insufficient_evidence_flags=d.get("insufficient_evidence_flags", []),
            generated_at=_iso_to_dt(d.get("generated_at")) or _now_utc(),
            model=d.get("model", ""),
            model_version=d.get("model_version", ""),
        )

    def to_sql_row(self) -> Tuple:
        import json as _json
        htype = self.hypothesis_type.value if isinstance(self.hypothesis_type, HypothesisType) else str(self.hypothesis_type)
        return (
            self.hypothesis_id,
            htype,
            self.subject_a,
            self.subject_b,
            self.probability,
            self.confidence,
            _json.dumps(self.supporting_evidence),
            _json.dumps(self.contradicting_evidence),
            _json.dumps(self.insufficient_evidence_flags),
            self.model,
            self.model_version,
            _dt_to_iso(self.generated_at),
        )


# ─── RelationshipHypothesis ─────────────────────────────────────────────────

@dataclass
class RelationshipHypothesis:
    """A claim about a relationship between entities (not necessarily actors)."""
    hypothesis_id: str
    hypothesis_type: str       # "operates", "associated_with", "uses_wallet", "shared_media", "predicted_link"
    subject: str
    object: str
    probability: float
    confidence: float
    supporting_evidence: List[str] = field(default_factory=list)
    contradicting_evidence: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=_now_utc)
    model: str = ""
    model_version: str = ""

    def __post_init__(self):
        if not self.hypothesis_id:
            self.hypothesis_id = generate_hypothesis_id(
                self.hypothesis_type,
                self.subject,
                self.object,
                self.model,
                self.model_version,
            )
        if not (0.0 <= self.probability <= 1.0):
            raise ValueError(
                f"probability must be in [0.0, 1.0], got {self.probability}"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_type": self.hypothesis_type,
            "subject": self.subject,
            "object": self.object,
            "probability": self.probability,
            "confidence": self.confidence,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "generated_at": _dt_to_iso(self.generated_at),
            "model": self.model,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RelationshipHypothesis":
        return cls(
            hypothesis_id=d.get("hypothesis_id", ""),
            hypothesis_type=d["hypothesis_type"],
            subject=d["subject"],
            object=d["object"],
            probability=d["probability"],
            confidence=d["confidence"],
            supporting_evidence=d.get("supporting_evidence", []),
            contradicting_evidence=d.get("contradicting_evidence", []),
            generated_at=_iso_to_dt(d.get("generated_at")) or _now_utc(),
            model=d.get("model", ""),
            model_version=d.get("model_version", ""),
        )

    def to_sql_row(self) -> Tuple:
        import json as _json
        return (
            self.hypothesis_id,
            self.hypothesis_type,
            self.subject,
            self.object,
            self.probability,
            self.confidence,
            _json.dumps(self.supporting_evidence),
            _json.dumps(self.contradicting_evidence),
            self.model,
            self.model_version,
            _dt_to_iso(self.generated_at),
        )


# ─── Campaign ───────────────────────────────────────────────────────────────

@dataclass
class Campaign:
    """An operational episode — a cluster of related activity."""
    campaign_id: str
    name: str
    actors: List[str] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)
    wallets: List[str] = field(default_factory=list)
    domains: List[str] = field(default_factory=list)
    message_ids: List[str] = field(default_factory=list)
    media_ids: List[str] = field(default_factory=list)
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    confidence: float = 0.0
    evidence_ids: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=_now_utc)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.campaign_id:
            self.campaign_id = generate_campaign_id(
                self.name,
                self.actors,
                "spectra-campaign",
                SCHEMA_VERSION,
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "actors": self.actors,
            "channels": self.channels,
            "wallets": self.wallets,
            "domains": self.domains,
            "message_ids": self.message_ids,
            "media_ids": self.media_ids,
            "start": _dt_to_iso(self.start),
            "end": _dt_to_iso(self.end),
            "confidence": self.confidence,
            "evidence_ids": self.evidence_ids,
            "generated_at": _dt_to_iso(self.generated_at),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Campaign":
        return cls(
            campaign_id=d.get("campaign_id", ""),
            name=d["name"],
            actors=d.get("actors", []),
            channels=d.get("channels", []),
            wallets=d.get("wallets", []),
            domains=d.get("domains", []),
            message_ids=d.get("message_ids", []),
            media_ids=d.get("media_ids", []),
            start=_iso_to_dt(d.get("start")),
            end=_iso_to_dt(d.get("end")),
            confidence=d.get("confidence", 0.0),
            evidence_ids=d.get("evidence_ids", []),
            generated_at=_iso_to_dt(d.get("generated_at")) or _now_utc(),
            metadata=d.get("metadata", {}),
        )

    def to_sql_row(self) -> Tuple:
        import json as _json
        return (
            self.campaign_id,
            self.name,
            _json.dumps(self.actors),
            _json.dumps(self.channels),
            _json.dumps(self.wallets) if self.wallets else None,
            _json.dumps(self.domains) if self.domains else None,
            _json.dumps(self.message_ids) if self.message_ids else None,
            _json.dumps(self.media_ids) if self.media_ids else None,
            _dt_to_iso(self.start),
            _dt_to_iso(self.end),
            self.confidence,
            _json.dumps(self.evidence_ids) if self.evidence_ids else None,
            _dt_to_iso(self.generated_at),
            _json.dumps(self.metadata) if self.metadata else None,
        )


# ─── Exports ────────────────────────────────────────────────────────────────

__all__ = [
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
]
