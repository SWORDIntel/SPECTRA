"""
SPECTRA Intelligence Adapters
=============================
Adapter functions that convert analytical outputs from SPECTRA modules into
canonical AnalysisEvidence, EvidenceSource, and ModelInference objects.

Supported modules:
- threat/indicators.py (ThreatIndicator)
- threat/scoring.py (ThreatActorProfile, BehavioralFlag)
- threat/attribution.py (WritingStyleProfile, AI content detection)
- threat/network.py (ActorRelationship, Interaction)
- threat/temporal.py (Activity pattern analysis)
- osint/intelligence.py (Actor classification)
- ml/pattern_detector.py (Pattern detection)
- ml/correlation_engine.py (Cross-entity correlation)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .schema import (
    AnalysisEvidence,
    EvidenceDirection,
    EvidenceSource,
    ModelInference,
    canonical_id,
)

# Optional / dynamic imports for source types
try:
    from ..threat.indicators import IndicatorType, ThreatIndicator, ThreatLevel
except ImportError:  # pragma: no cover
    IndicatorType = Any  # type: ignore
    ThreatIndicator = Any  # type: ignore
    ThreatLevel = Any  # type: ignore

try:
    from ..threat.scoring import (
        BehavioralFlag,
        ThreatActorProfile,
        ThreatClassification,
    )
except ImportError:  # pragma: no cover
    BehavioralFlag = Any  # type: ignore
    ThreatActorProfile = Any  # type: ignore
    ThreatClassification = Any  # type: ignore

try:
    from ..threat.attribution import WritingStyleProfile
except ImportError:  # pragma: no cover
    WritingStyleProfile = Any  # type: ignore

try:
    from ..threat.network import ActorRelationship, Interaction
except ImportError:  # pragma: no cover
    ActorRelationship = Any  # type: ignore
    Interaction = Any  # type: ignore

try:
    from ..threat.temporal import TemporalAnalyzer
except ImportError:  # pragma: no cover
    TemporalAnalyzer = Any  # type: ignore

try:
    from ..osint.intelligence import IntelligenceCollector
except ImportError:  # pragma: no cover
    IntelligenceCollector = Any  # type: ignore

try:
    from ..ml.pattern_detector import PatternDetector
except ImportError:  # pragma: no cover
    PatternDetector = Any  # type: ignore

try:
    from ..ml.correlation_engine import CorrelationEngine
except ImportError:  # pragma: no cover
    CorrelationEngine = Any  # type: ignore

logger = logging.getLogger(__name__)

FEATURE_SCHEMA_VERSION = "1"
DEFAULT_MODEL_VERSION = "1.0.0"


def _ensure_utc(dt: Optional[datetime]) -> datetime:
    """Ensure a datetime is timezone-aware UTC, or return now(timezone.utc)."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _clamp_confidence(conf: Any, default: float = 0.5) -> float:
    """Clamp confidence score to the valid [0.0, 1.0] range."""
    try:
        val = float(conf)
        if val < 0.0:
            return 0.0
        if val > 1.0:
            return 1.0
        return val
    except (TypeError, ValueError):
        return default


# ==============================================================================
# 1. Threat Indicator Adapter
# ==============================================================================

def threat_indicator_to_evidence(
    indicator: ThreatIndicator,
    message_id: int,
    channel_id: int,
    user_id: int,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> AnalysisEvidence:
    """
    Convert a ThreatIndicator object to an AnalysisEvidence object.

    Args:
        indicator: The detected ThreatIndicator
        message_id: Associated Telegram message ID
        channel_id: Associated Telegram channel ID
        user_id: Associated Telegram user ID
        model_version: Version of the threat indicator detector

    Returns:
        Canonical AnalysisEvidence object
    """
    now = datetime.now(timezone.utc)

    raw_type = getattr(indicator, "type", "keyword")
    if hasattr(raw_type, "value"):
        type_str = str(raw_type.value)
    else:
        type_str = str(raw_type)

    if type_str.lower() in ("keyword", "pattern", "behavioral", "network"):
        evidence_type = f"{type_str.lower()}_indicator"
    else:
        evidence_type = f"{type_str}_indicator"

    if user_id:
        subject = canonical_id("telegram", "user", user_id)
    elif channel_id and message_id:
        subject = canonical_id("telegram", "msg", f"{channel_id}:{message_id}")
    elif message_id:
        subject = canonical_id("telegram", "msg", message_id)
    else:
        subject = "telegram:message:0"

    if channel_id and message_id:
        source_id = canonical_id("telegram", "msg", f"{channel_id}:{message_id}")
        source_row_id = message_id
        source_type = "message"
        source_table = "messages"
    elif message_id:
        source_id = canonical_id("telegram", "msg", message_id)
        source_row_id = message_id
        source_type = "message"
        source_table = "messages"
    elif user_id:
        source_id = canonical_id("telegram", "user", user_id)
        source_row_id = user_id
        source_type = "user"
        source_table = "users"
    else:
        source_id = "telegram:message:0"
        source_row_id = 0
        source_type = "message"
        source_table = "messages"

    snapshot = None
    if getattr(indicator, "context", None) or getattr(indicator, "value", None):
        snapshot = json.dumps(
            {
                "value": getattr(indicator, "value", ""),
                "context": getattr(indicator, "context", None),
            }
        )

    sources = [
        EvidenceSource(
            source_type=source_type,
            source_id=source_id,
            source_table=source_table,
            source_row_id=source_row_id,
            retrieved_at=now,
            raw_snapshot=snapshot,
        )
    ]

    level = getattr(indicator, "level", "unknown")
    level_val = level.value if hasattr(level, "value") else str(level)

    metadata: Dict[str, Any] = {
        "indicator_value": getattr(indicator, "value", ""),
        "indicator_type": type_str,
        "severity": float(getattr(indicator, "severity", 0.0)),
        "level": level_val,
        "context": getattr(indicator, "context", None),
        "message_id": message_id,
        "channel_id": channel_id,
        "user_id": user_id,
    }
    if getattr(indicator, "metadata", None):
        metadata.update(indicator.metadata)

    return AnalysisEvidence(
        evidence_id="",
        evidence_type=evidence_type,
        subject=subject,
        object=None,
        score=float(getattr(indicator, "severity", 0.0)),
        confidence=_clamp_confidence(getattr(indicator, "confidence", 1.0), 1.0),
        direction=EvidenceDirection.SUPPORTS,
        model="spectra-threat-indicators",
        model_version=model_version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        sources=sources,
        observed_at=now,
        generated_at=now,
        metadata=metadata,
    )


# ==============================================================================
# 2. Behavioral Flag Adapter
# ==============================================================================

def behavioral_flag_to_evidence(
    flag: BehavioralFlag,
    user_id: int,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> AnalysisEvidence:
    """
    Convert a BehavioralFlag object to an AnalysisEvidence object.

    Args:
        flag: The detected BehavioralFlag
        user_id: Associated Telegram user ID
        model_version: Version of the behavioral analyzer

    Returns:
        Canonical AnalysisEvidence object
    """
    now = datetime.now(timezone.utc)
    obs_at = (
        _ensure_utc(flag.detected_at)
        if getattr(flag, "detected_at", None)
        else now
    )

    sources = [
        EvidenceSource(
            source_type="user",
            source_id=canonical_id("telegram", "user", user_id),
            source_table="users",
            source_row_id=user_id,
            retrieved_at=now,
            raw_snapshot=None,
        )
    ]

    flag_type = getattr(flag, "flag_type", "unknown")
    evidence_type = f"behavioral_{flag_type}"

    metadata: Dict[str, Any] = {
        "flag_type": flag_type,
        "description": getattr(flag, "description", ""),
        "severity": float(getattr(flag, "severity", 1.0)),
        "user_id": user_id,
    }

    return AnalysisEvidence(
        evidence_id="",
        evidence_type=evidence_type,
        subject=canonical_id("telegram", "user", user_id),
        object=None,
        score=float(getattr(flag, "severity", 1.0)),
        confidence=_clamp_confidence(getattr(flag, "confidence", 1.0), 1.0),
        direction=EvidenceDirection.SUPPORTS,
        model="spectra-behavioral-analyzer",
        model_version=model_version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        sources=sources,
        observed_at=obs_at,
        generated_at=now,
        metadata=metadata,
    )


# ==============================================================================
# 3. Threat Actor Profile Adapter (Model Inferences)
# ==============================================================================

def threat_profile_to_inferences(
    profile: ThreatActorProfile,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> List[ModelInference]:
    """
    Convert a ThreatActorProfile into a list of ModelInference objects.

    Args:
        profile: The ThreatActorProfile object
        model_version: Version of the threat scorer / classifier

    Returns:
        List of ModelInference objects
    """
    now = datetime.now(timezone.utc)
    gen_at = (
        _ensure_utc(profile.last_updated)
        if getattr(profile, "last_updated", None)
        else now
    )
    subject_id = canonical_id("telegram", "user", profile.user_id)

    class_obj = getattr(profile, "classification", None)
    class_val = class_obj.value if hasattr(class_obj, "value") else str(class_obj or "unknown")

    threat_output: Dict[str, Any] = {
        "user_id": profile.user_id,
        "username": profile.username,
        "threat_score": float(profile.threat_score),
        "confidence": float(profile.confidence),
        "classification": class_val,
        "keyword_indicators_count": len(getattr(profile, "keyword_indicators", [])),
        "pattern_indicators_count": len(getattr(profile, "pattern_indicators", [])),
        "behavioral_flags_count": len(getattr(profile, "behavioral_flags", [])),
        "message_count": getattr(profile, "message_count", 0),
        "channel_count": len(getattr(profile, "channels", [])),
        "associate_count": getattr(profile, "associate_count", 0),
        "network_threat_score": float(getattr(profile, "network_threat_score", 0.0)),
        "caas_severity": float(getattr(profile, "caas_severity", 0.0)),
        "caas_confidence": float(getattr(profile, "caas_confidence", 0.0)),
        "tags": getattr(profile, "tags", []),
        "first_seen": (
            profile.first_seen.isoformat()
            if getattr(profile, "first_seen", None)
            else None
        ),
        "last_seen": (
            profile.last_seen.isoformat()
            if getattr(profile, "last_seen", None)
            else None
        ),
    }

    inferences: List[ModelInference] = [
        ModelInference(
            inference_id="",
            inference_type="threat_score",
            model="spectra-threat-scorer",
            model_version=model_version,
            inputs=[subject_id],
            output=threat_output,
            confidence=_clamp_confidence(profile.confidence, 0.8),
            generated_at=gen_at,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
        ),
        ModelInference(
            inference_id="",
            inference_type="actor_classification",
            model="spectra-threat-classifier",
            model_version=model_version,
            inputs=[subject_id],
            output={
                "user_id": profile.user_id,
                "username": profile.username,
                "classification": class_val,
                "threat_score": float(profile.threat_score),
                "tags": getattr(profile, "tags", []),
            },
            confidence=_clamp_confidence(profile.confidence, 0.8),
            generated_at=gen_at,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
        ),
    ]

    if getattr(profile, "caas_severity", 0.0) > 0.0:
        caas_conf = getattr(profile, "caas_confidence", 0.0)
        inferences.append(
            ModelInference(
                inference_id="",
                inference_type="caas_profile",
                model="spectra-caas-profiler",
                model_version=model_version,
                inputs=[subject_id],
                output={
                    "user_id": profile.user_id,
                    "caas_severity": float(profile.caas_severity),
                    "caas_confidence": float(caas_conf),
                },
                confidence=_clamp_confidence(
                    caas_conf if caas_conf > 0.0 else profile.confidence, 0.5
                ),
                generated_at=gen_at,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
            )
        )

    return inferences


# ==============================================================================
# 4. Writing Style Similarity Adapter
# ==============================================================================

def writing_style_similarity_to_evidence(
    profile_a_user_id: int,
    profile_b_user_id: int,
    similarity_score: float,
    confidence: float,
    message_ids_a: List[int],
    message_ids_b: List[int],
    model_version: str = DEFAULT_MODEL_VERSION,
) -> AnalysisEvidence:
    """
    Convert writing style similarity comparison into an AnalysisEvidence object.

    Args:
        profile_a_user_id: User ID for subject profile
        profile_b_user_id: User ID for candidate profile
        similarity_score: Cosine similarity measurement (0.0 to 1.0)
        confidence: Measurement confidence estimate (0.0 to 1.0)
        message_ids_a: Message IDs used for profile A
        message_ids_b: Message IDs used for profile B
        model_version: Version of the stylometric model

    Returns:
        Canonical AnalysisEvidence object
    """
    now = datetime.now(timezone.utc)

    subject_id = canonical_id("telegram", "user", profile_a_user_id)
    object_id = canonical_id("telegram", "user", profile_b_user_id)

    sources: List[EvidenceSource] = []
    for mid in message_ids_a:
        sources.append(
            EvidenceSource(
                source_type="message",
                source_id=canonical_id("telegram", "msg", mid),
                source_table="messages",
                source_row_id=mid,
                retrieved_at=now,
                raw_snapshot=None,
            )
        )
    for mid in message_ids_b:
        sources.append(
            EvidenceSource(
                source_type="message",
                source_id=canonical_id("telegram", "msg", mid),
                source_table="messages",
                source_row_id=mid,
                retrieved_at=now,
                raw_snapshot=None,
            )
        )

    if not sources:
        sources.append(
            EvidenceSource(
                source_type="user",
                source_id=subject_id,
                source_table="users",
                source_row_id=profile_a_user_id,
                retrieved_at=now,
                raw_snapshot=None,
            )
        )
        sources.append(
            EvidenceSource(
                source_type="user",
                source_id=object_id,
                source_table="users",
                source_row_id=profile_b_user_id,
                retrieved_at=now,
                raw_snapshot=None,
            )
        )

    direction = (
        EvidenceDirection.SUPPORTS
        if similarity_score >= 0.5
        else EvidenceDirection.CONTRADICTS
    )

    metadata: Dict[str, Any] = {
        "cosine_similarity": float(similarity_score),
        "message_count_a": len(message_ids_a),
        "message_count_b": len(message_ids_b),
        "user_id_a": profile_a_user_id,
        "user_id_b": profile_b_user_id,
    }

    return AnalysisEvidence(
        evidence_id="",
        evidence_type="stylometric_similarity",
        subject=subject_id,
        object=object_id,
        score=float(similarity_score),
        confidence=_clamp_confidence(confidence, 0.5),
        direction=direction,
        model="spectra-stylometry",
        model_version=model_version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        sources=sources,
        observed_at=now,
        generated_at=now,
        metadata=metadata,
    )


# ==============================================================================
# 5. AI Detection Adapter
# ==============================================================================

def ai_detection_to_evidence(
    ai_result: dict,
    message_ids: List[int],
    user_id: int,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> AnalysisEvidence:
    """
    Convert AI-generated content detection output into an AnalysisEvidence object.

    Args:
        ai_result: Dict containing ai_likelihood, indicators, confidence
        message_ids: List of message IDs analyzed
        user_id: User ID of the author
        model_version: Version of the AI detector

    Returns:
        Canonical AnalysisEvidence object
    """
    now = datetime.now(timezone.utc)

    if user_id:
        subject = canonical_id("telegram", "user", user_id)
    elif message_ids:
        subject = canonical_id("telegram", "msg", message_ids[0])
    else:
        subject = "telegram:user:0"

    sources: List[EvidenceSource] = []
    for mid in message_ids:
        sources.append(
            EvidenceSource(
                source_type="message",
                source_id=canonical_id("telegram", "msg", mid),
                source_table="messages",
                source_row_id=mid,
                retrieved_at=now,
                raw_snapshot=None,
            )
        )

    if not sources:
        sources.append(
            EvidenceSource(
                source_type="user",
                source_id=canonical_id("telegram", "user", user_id),
                source_table="users",
                source_row_id=user_id,
                retrieved_at=now,
                raw_snapshot=None,
            )
        )

    ai_likelihood = float(ai_result.get("ai_likelihood", 0.0))
    direction = (
        EvidenceDirection.SUPPORTS
        if ai_likelihood >= 0.5
        else EvidenceDirection.CONTRADICTS
    )

    metadata: Dict[str, Any] = {
        "ai_likelihood": ai_likelihood,
        "indicators": ai_result.get("indicators", []),
        "message_count": len(message_ids),
        "user_id": user_id,
    }

    return AnalysisEvidence(
        evidence_id="",
        evidence_type="ai_content_detection",
        subject=subject,
        object=None,
        score=ai_likelihood,
        confidence=_clamp_confidence(ai_result.get("confidence", 0.5), 0.5),
        direction=direction,
        model="spectra-ai-detector",
        model_version=model_version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        sources=sources,
        observed_at=now,
        generated_at=now,
        metadata=metadata,
    )


# ==============================================================================
# 6. Actor Relationship Adapter
# ==============================================================================

def actor_relationship_to_evidence(
    rel: ActorRelationship,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> AnalysisEvidence:
    """
    Convert an ActorRelationship into an AnalysisEvidence object.

    Args:
        rel: The ActorRelationship object
        model_version: Version of the network tracker

    Returns:
        Canonical AnalysisEvidence object
    """
    now = datetime.now(timezone.utc)
    obs_at = (
        _ensure_utc(rel.last_interaction or rel.first_interaction)
        if (getattr(rel, "last_interaction", None) or getattr(rel, "first_interaction", None))
        else now
    )

    source_subject = canonical_id("telegram", "user", rel.source_id)
    target_object = canonical_id("telegram", "user", rel.target_id)

    sources: List[EvidenceSource] = [
        EvidenceSource(
            source_type="user",
            source_id=source_subject,
            source_table="users",
            source_row_id=rel.source_id,
            retrieved_at=now,
            raw_snapshot=None,
        ),
        EvidenceSource(
            source_type="user",
            source_id=target_object,
            source_table="users",
            source_row_id=rel.target_id,
            retrieved_at=now,
            raw_snapshot=None,
        ),
    ]

    for ch in getattr(rel, "channels", set()):
        sources.append(
            EvidenceSource(
                source_type="channel",
                source_id=canonical_id("telegram", "channel", ch),
                source_table="channels",
                source_row_id=ch,
                retrieved_at=now,
                raw_snapshot=None,
            )
        )

    interaction_count = getattr(rel, "interaction_count", 0)
    confidence = min(1.0, max(0.1, interaction_count / 10.0))

    metadata: Dict[str, Any] = {
        "interaction_count": interaction_count,
        "total_weight": float(getattr(rel, "total_weight", 0.0)),
        "avg_weight": float(rel.total_weight / max(interaction_count, 1)),
        "interaction_types": getattr(rel, "interaction_types", {}),
        "first_interaction": (
            rel.first_interaction.isoformat()
            if getattr(rel, "first_interaction", None)
            else None
        ),
        "last_interaction": (
            rel.last_interaction.isoformat()
            if getattr(rel, "last_interaction", None)
            else None
        ),
        "channel_count": len(getattr(rel, "channels", set())),
        "channels": list(getattr(rel, "channels", set())),
    }

    return AnalysisEvidence(
        evidence_id="",
        evidence_type="actor_relationship",
        subject=source_subject,
        object=target_object,
        score=float(getattr(rel, "total_weight", 0.0)),
        confidence=_clamp_confidence(confidence, 0.5),
        direction=EvidenceDirection.SUPPORTS,
        model="spectra-network-tracker",
        model_version=model_version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        sources=sources,
        observed_at=obs_at,
        generated_at=now,
        metadata=metadata,
    )


# ==============================================================================
# 7. Temporal Analysis Adapter
# ==============================================================================

def temporal_analysis_to_evidence(
    analysis: dict,
    user_id: int,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> List[AnalysisEvidence]:
    """
    Convert temporal activity patterns into a list of AnalysisEvidence objects.

    Args:
        analysis: Dict returned by TemporalAnalyzer.analyze_activity_patterns
        user_id: Telegram user ID
        model_version: Version of the temporal analyzer

    Returns:
        List of AnalysisEvidence objects (regularity, timezone, bursts)
    """
    now = datetime.now(timezone.utc)

    last_seen = analysis.get("last_seen")
    if isinstance(last_seen, str):
        try:
            last_seen = datetime.fromisoformat(last_seen)
        except Exception:
            last_seen = None
    obs_at = _ensure_utc(last_seen) if last_seen else now

    subject = canonical_id("telegram", "user", user_id)
    user_source = EvidenceSource(
        source_type="user",
        source_id=subject,
        source_table="users",
        source_row_id=user_id,
        retrieved_at=now,
        raw_snapshot=None,
    )

    evidences: List[AnalysisEvidence] = []

    # 1. Regularity evidence
    total_messages = analysis.get("total_messages", 0)
    regularity_score = float(analysis.get("regularity_score", 0.0))
    regularity_conf = min(1.0, max(0.1, total_messages / 50.0))

    evidences.append(
        AnalysisEvidence(
            evidence_id="",
            evidence_type="temporal_regularity",
            subject=subject,
            object=None,
            score=regularity_score,
            confidence=_clamp_confidence(regularity_conf, 0.5),
            direction=EvidenceDirection.SUPPORTS,
            model="spectra-temporal-analyzer",
            model_version=model_version,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            sources=[user_source],
            observed_at=obs_at,
            generated_at=now,
            metadata={
                "regularity_score": regularity_score,
                "total_messages": total_messages,
                "active_days": analysis.get("active_days", 0),
                "peak_hours": analysis.get("peak_hours", []),
                "peak_days": analysis.get("peak_days", []),
            },
        )
    )

    # 2. Inferred timezone evidence
    inferred_tz = analysis.get("inferred_timezone")
    if inferred_tz and not str(inferred_tz).lower().startswith("unknown"):
        tz_conf = min(1.0, max(0.2, total_messages / 30.0))
        evidences.append(
            AnalysisEvidence(
                evidence_id="",
                evidence_type="inferred_timezone",
                subject=subject,
                object=None,
                score=float(len(analysis.get("peak_hours", []))),
                confidence=_clamp_confidence(tz_conf, 0.5),
                direction=EvidenceDirection.SUPPORTS,
                model="spectra-temporal-analyzer",
                model_version=model_version,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                sources=[user_source],
                observed_at=obs_at,
                generated_at=now,
                metadata={
                    "inferred_timezone": inferred_tz,
                    "peak_hours": analysis.get("peak_hours", []),
                    "peak_days": analysis.get("peak_days", []),
                },
            )
        )

    # 3. Burst periods
    burst_periods = analysis.get("burst_periods", [])
    for burst in burst_periods:
        burst_dt = burst.get("end") or burst.get("start")
        if isinstance(burst_dt, str):
            try:
                burst_dt = datetime.fromisoformat(burst_dt)
            except Exception:
                burst_dt = now
        burst_obs_at = _ensure_utc(burst_dt) if burst_dt else obs_at

        intensity = float(burst.get("intensity", 1.0))
        msg_count = burst.get("message_count", 0)
        burst_conf = min(1.0, max(0.4, msg_count / 20.0))

        burst_meta = {}
        for k, v in burst.items():
            if isinstance(v, datetime):
                burst_meta[k] = v.isoformat()
            else:
                burst_meta[k] = v

        evidences.append(
            AnalysisEvidence(
                evidence_id="",
                evidence_type="temporal_burst",
                subject=subject,
                object=None,
                score=intensity,
                confidence=_clamp_confidence(burst_conf, 0.5),
                direction=EvidenceDirection.SUPPORTS,
                model="spectra-temporal-analyzer",
                model_version=model_version,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                sources=[user_source],
                observed_at=burst_obs_at,
                generated_at=now,
                metadata=burst_meta,
            )
        )

    return evidences


# ==============================================================================
# 8. CaaS / OSINT Actor Classification Adapter
# ==============================================================================

def caas_classification_to_evidence(
    classification: dict,
    user_id: int,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> AnalysisEvidence:
    """
    Convert an actor classification dictionary to an AnalysisEvidence object.

    Args:
        classification: Dict returned by IntelligenceCollector.classify_actor
        user_id: Telegram user ID
        model_version: Version of the classification engine

    Returns:
        Canonical AnalysisEvidence object
    """
    now = datetime.now(timezone.utc)

    subject = canonical_id("telegram", "user", user_id)
    profile = classification.get("profile", {})
    last_active = profile.get("last_active") if isinstance(profile, dict) else None

    obs_at = now
    if last_active:
        if isinstance(last_active, datetime):
            obs_at = _ensure_utc(last_active)
        elif isinstance(last_active, str):
            try:
                obs_at = _ensure_utc(datetime.fromisoformat(last_active))
            except Exception:
                obs_at = now

    sources = [
        EvidenceSource(
            source_type="user",
            source_id=subject,
            source_table="users",
            source_row_id=user_id,
            retrieved_at=now,
            raw_snapshot=None,
        )
    ]

    category = classification.get("category", "unknown")
    if category in ("unknown", "error"):
        direction = EvidenceDirection.NEUTRAL
    else:
        direction = EvidenceDirection.SUPPORTS

    raw_score = (
        float(profile.get("message_count", 1.0))
        if isinstance(profile, dict)
        else 1.0
    )

    metadata: Dict[str, Any] = {
        "category": category,
        "profile": profile,
        "user_id": user_id,
    }

    return AnalysisEvidence(
        evidence_id="",
        evidence_type="actor_classification",
        subject=subject,
        object=None,
        score=raw_score,
        confidence=_clamp_confidence(classification.get("confidence", 0.5), 0.5),
        direction=direction,
        model="spectra-osint-classifier",
        model_version=model_version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        sources=sources,
        observed_at=obs_at,
        generated_at=now,
        metadata=metadata,
    )


# ==============================================================================
# 9. ML Pattern Adapter
# ==============================================================================

def pattern_to_evidence(
    pattern: dict,
    message_ids: List[int],
    model_version: str = DEFAULT_MODEL_VERSION,
) -> AnalysisEvidence:
    """
    Convert an ML pattern detector output into an AnalysisEvidence object.

    Args:
        pattern: Dict from PatternDetector (content, user behavior, temporal)
        message_ids: Associated Telegram message IDs
        model_version: Version of the pattern detector

    Returns:
        Canonical AnalysisEvidence object
    """
    now = datetime.now(timezone.utc)

    if pattern.get("user_id"):
        subject = canonical_id("telegram", "user", pattern["user_id"])
    elif message_ids:
        subject = canonical_id("telegram", "msg", message_ids[0])
    else:
        subject = "telegram:corpus:messages"

    sources: List[EvidenceSource] = []
    for mid in message_ids:
        sources.append(
            EvidenceSource(
                source_type="message",
                source_id=canonical_id("telegram", "msg", mid),
                source_table="messages",
                source_row_id=mid,
                retrieved_at=now,
                raw_snapshot=None,
            )
        )

    if not sources:
        if pattern.get("user_id"):
            sources.append(
                EvidenceSource(
                    source_type="user",
                    source_id=canonical_id("telegram", "user", pattern["user_id"]),
                    source_table="users",
                    source_row_id=int(pattern["user_id"]),
                    retrieved_at=now,
                    raw_snapshot=None,
                )
            )
        else:
            sources.append(
                EvidenceSource(
                    source_type="corpus",
                    source_id="telegram:corpus:messages",
                    source_table="messages",
                    source_row_id=0,
                    retrieved_at=now,
                    raw_snapshot=None,
                )
            )

    pattern_type = str(pattern.get("type", "content"))
    evidence_type = f"pattern_{pattern_type}"

    score_val = pattern.get("frequency", pattern.get("mean_interval_hours", 1.0))
    try:
        score = float(score_val)
    except (TypeError, ValueError):
        score = 1.0

    return AnalysisEvidence(
        evidence_id="",
        evidence_type=evidence_type,
        subject=subject,
        object=None,
        score=score,
        confidence=_clamp_confidence(pattern.get("confidence", 0.5), 0.5),
        direction=EvidenceDirection.SUPPORTS,
        model="spectra-pattern-detector",
        model_version=model_version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        sources=sources,
        observed_at=now,
        generated_at=now,
        metadata=dict(pattern),
    )


# ==============================================================================
# 10. ML Correlation Adapter
# ==============================================================================

def correlation_to_evidence(
    correlation: dict,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> AnalysisEvidence:
    """
    Convert an ML correlation discovery output into an AnalysisEvidence object.

    Args:
        correlation: Dict from CorrelationEngine (cross_channel, user_user, etc.)
        model_version: Version of the correlation engine

    Returns:
        Canonical AnalysisEvidence object
    """
    now = datetime.now(timezone.utc)

    e1 = correlation.get("entity1", {})
    e2 = correlation.get("entity2", {})
    e1_type = str(e1.get("type", "entity"))
    e2_type = str(e2.get("type", "entity"))
    e1_id = e1.get("id", 0)
    e2_id = e2.get("id", 0)

    subject = canonical_id("telegram", e1_type, e1_id)
    object_id = canonical_id("telegram", e2_type, e2_id)

    try:
        row_id_1 = int(e1_id)
    except (TypeError, ValueError):
        row_id_1 = 0

    try:
        row_id_2 = int(e2_id)
    except (TypeError, ValueError):
        row_id_2 = 0

    sources = [
        EvidenceSource(
            source_type=e1_type,
            source_id=subject,
            source_table=f"{e1_type}s" if not e1_type.endswith("s") else e1_type,
            source_row_id=row_id_1,
            retrieved_at=now,
            raw_snapshot=None,
        ),
        EvidenceSource(
            source_type=e2_type,
            source_id=object_id,
            source_table=f"{e2_type}s" if not e2_type.endswith("s") else e2_type,
            source_row_id=row_id_2,
            retrieved_at=now,
            raw_snapshot=None,
        ),
    ]

    corr_type = str(correlation.get("type", "cross_entity_correlation"))
    strength = float(correlation.get("strength", 0.0))

    if strength >= 0.3:
        direction = EvidenceDirection.SUPPORTS
    else:
        direction = EvidenceDirection.NEUTRAL

    conf = correlation.get("confidence", strength if strength > 0 else 0.5)

    metadata: Dict[str, Any] = {
        "correlation_type": corr_type,
        "strength": strength,
        "entity1": e1,
        "entity2": e2,
    }

    return AnalysisEvidence(
        evidence_id="",
        evidence_type=corr_type,
        subject=subject,
        object=object_id,
        score=strength,
        confidence=_clamp_confidence(conf, 0.5),
        direction=direction,
        model="spectra-correlation-engine",
        model_version=model_version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        sources=sources,
        observed_at=now,
        generated_at=now,
        metadata=metadata,
    )


__all__ = [
    "threat_indicator_to_evidence",
    "behavioral_flag_to_evidence",
    "threat_profile_to_inferences",
    "writing_style_similarity_to_evidence",
    "ai_detection_to_evidence",
    "actor_relationship_to_evidence",
    "temporal_analysis_to_evidence",
    "caas_classification_to_evidence",
    "pattern_to_evidence",
    "correlation_to_evidence",
]
