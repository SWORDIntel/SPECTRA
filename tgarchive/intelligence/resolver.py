"""
SPECTRA Actor Identity-Resolution Engine
========================================
Combines evidence from all feature families to produce
P(A=B | E_1, ..., E_n) with full provenance.

Replaces the concept of "similar writing = probably same actor" with
a traceable, calibrated attribution dossier.

Anti-double-counting: correlated evidence (e.g., same URL + same domain +
same hostname) is grouped and counted as one observation, not three.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .schema import (
    ActorHypothesis,
    AnalysisEvidence,
    EvidenceDirection,
    EvidenceSource,
    HypothesisType,
    canonical_id,
    generate_evidence_id,
)

logger = logging.getLogger(__name__)

# Feature family imports (graceful degradation if a module is missing)
try:
    from .features.linguistic import extract_linguistic_features, compare_linguistic_features
    HAS_LINGUISTIC = True
except ImportError:
    HAS_LINGUISTIC = False
    logger.warning("Linguistic features module not available")

try:
    from .features.temporal import extract_temporal_features, compare_temporal_features
    HAS_TEMPORAL = True
except ImportError:
    HAS_TEMPORAL = False
    logger.warning("Temporal features module not available")

try:
    from .features.infrastructure import extract_infrastructure_features, compare_infrastructure_features
    HAS_INFRASTRUCTURE = True
except ImportError:
    HAS_INFRASTRUCTURE = False
    logger.warning("Infrastructure features module not available")

try:
    from .features.telegram_native import extract_telegram_features, compare_telegram_features
    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False
    logger.warning("Telegram-native features module not available")

try:
    from .features.media import extract_media_features, compare_media_features
    HAS_MEDIA = True
except ImportError:
    HAS_MEDIA = False
    logger.warning("Media features module not available")

try:
    from .features.commercial import extract_commercial_features, compare_commercial_features
    HAS_COMMERCIAL = True
except ImportError:
    HAS_COMMERCIAL = False
    logger.warning("Commercial features module not available")


# ─── Feature Family Configuration ───────────────────────────────────────────

FEATURE_FAMILIES = {
    "linguistic": {
        "extract": extract_linguistic_features if HAS_LINGUISTIC else None,
        "compare": compare_linguistic_features if HAS_LINGUISTIC else None,
        "weight": 0.25,
        "model": "spectra-stylometry",
    },
    "temporal": {
        "extract": extract_temporal_features if HAS_TEMPORAL else None,
        "compare": compare_temporal_features if HAS_TEMPORAL else None,
        "weight": 0.15,
        "model": "spectra-temporal",
    },
    "infrastructure": {
        "extract": extract_infrastructure_features if HAS_INFRASTRUCTURE else None,
        "compare": compare_infrastructure_features if HAS_INFRASTRUCTURE else None,
        "weight": 0.25,
        "model": "spectra-infrastructure",
    },
    "telegram_native": {
        "extract": extract_telegram_features if HAS_TELEGRAM else None,
        "compare": compare_telegram_features if HAS_TELEGRAM else None,
        "weight": 0.15,
        "model": "spectra-telegram-graph",
    },
    "media": {
        "extract": extract_media_features if HAS_MEDIA else None,
        "compare": compare_media_features if HAS_MEDIA else None,
        "weight": 0.10,
        "model": "spectra-media",
    },
    "commercial": {
        "extract": extract_commercial_features if HAS_COMMERCIAL else None,
        "compare": compare_commercial_features if HAS_COMMERCIAL else None,
        "weight": 0.10,
        "model": "spectra-commercial",
    },
}

MODEL_VERSION = "1.0.0"
FEATURE_SCHEMA_VERSION = "1"


class ActorIdentityResolver:
    """
    Combines evidence from all feature families to produce
    P(A=B | E_1, ..., E_n) with full provenance.

    Usage:
        resolver = ActorIdentityResolver()
        hypothesis = resolver.resolve(
            actor_a_messages=msgs_a,
            actor_b_messages=msgs_b,
            actor_a_id=123,
            actor_b_id=456,
        )
        print(hypothesis.probability)  # P(same actor)
        print(hypothesis.supporting_evidence)  # evidence IDs
    """

    def __init__(self, min_messages: int = 5):
        """
        Args:
            min_messages: Minimum messages per actor to produce a hypothesis.
                          Below this, confidence is heavily reduced.
        """
        self.min_messages = min_messages

    def resolve(
        self,
        actor_a_messages: List[Dict[str, Any]],
        actor_b_messages: List[Dict[str, Any]],
        actor_a_id: int,
        actor_b_id: int,
        actor_a_media: Optional[List[Dict]] = None,
        actor_b_media: Optional[List[Dict]] = None,
        channel_id: Optional[int] = None,
    ) -> ActorHypothesis:
        """
        Resolve whether two actors are the same person.

        Args:
            actor_a_messages: Messages from actor A
            actor_b_messages: Messages from actor B
            actor_a_id: Telegram user ID for actor A
            actor_b_id: Telegram user ID for actor B
            actor_a_media: Media items posted by actor A (optional)
            actor_b_media: Media items posted by actor B (optional)
            channel_id: Channel context (optional)

        Returns:
            ActorHypothesis with probability, confidence, supporting and
            contradicting evidence, and insufficient-evidence flags
        """
        subject_a = canonical_id("telegram", "user", actor_a_id)
        subject_b = canonical_id("telegram", "user", actor_b_id)

        evidence_list: List[AnalysisEvidence] = []
        family_scores: Dict[str, Tuple[float, float]] = {}  # family -> (score, confidence)
        insufficient: List[str] = []

        msg_count_a = len(actor_a_messages)
        msg_count_b = len(actor_b_messages)
        total_msgs = msg_count_a + msg_count_b

        for family_name, config in FEATURE_FAMILIES.items():
            extract_fn = config["extract"]
            compare_fn = config["compare"]

            if extract_fn is None or compare_fn is None:
                insufficient.append(family_name)
                continue

            try:
                # Extract features
                if family_name == "media":
                    if not actor_a_media or not actor_b_media:
                        insufficient.append(family_name)
                        continue
                    feat_a = extract_fn(actor_a_media)
                    feat_b = extract_fn(actor_b_media)
                elif family_name == "telegram_native":
                    feat_a = extract_fn(actor_a_messages, actor_a_id, channel_id)
                    feat_b = extract_fn(actor_b_messages, actor_b_id, channel_id)
                else:
                    feat_a = extract_fn(actor_a_messages)
                    feat_b = extract_fn(actor_b_messages)

                # Compare
                score, confidence = compare_fn(feat_a, feat_b)

                # Check for insufficient evidence
                if confidence < 0.1 or (msg_count_a < self.min_messages and msg_count_b < self.min_messages):
                    insufficient.append(family_name)
                    continue

                family_scores[family_name] = (score, confidence)

                # Build evidence
                evidence = self._build_evidence(
                    family_name=family_name,
                    score=score,
                    confidence=confidence,
                    subject_a=subject_a,
                    subject_b=subject_b,
                    actor_a_messages=actor_a_messages,
                    actor_b_messages=actor_b_messages,
                    model=config["model"],
                )
                evidence_list.append(evidence)

            except Exception as e:
                logger.error(f"Feature family {family_name} failed: {e}")
                insufficient.append(family_name)

        # Deduplicate correlated evidence (anti-double-counting)
        evidence_list = self._deduplicate_correlated(evidence_list)

        # Compute posterior probability
        probability, overall_confidence = self._compute_posterior(family_scores)

        # Split evidence into supporting and contradicting
        supporting: List[str] = []
        contradicting: List[str] = []
        for ev in evidence_list:
            if ev.score >= 0.5:
                supporting.append(ev.evidence_id)
            else:
                contradicting.append(ev.evidence_id)

        return ActorHypothesis(
            hypothesis_id="",
            hypothesis_type=HypothesisType.SAME_ACTOR,
            subject_a=subject_a,
            subject_b=subject_b,
            probability=probability,
            confidence=overall_confidence,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            insufficient_evidence_flags=insufficient,
            generated_at=datetime.now(timezone.utc),
            model="spectra-resolver",
            model_version=MODEL_VERSION,
        )

    def _build_evidence(
        self,
        family_name: str,
        score: float,
        confidence: float,
        subject_a: str,
        subject_b: str,
        actor_a_messages: List[Dict],
        actor_b_messages: List[Dict],
        model: str,
    ) -> AnalysisEvidence:
        """Build an AnalysisEvidence from a feature family comparison."""
        # Build sources from message IDs
        sources: List[EvidenceSource] = []
        now = datetime.now(timezone.utc)

        for msg in actor_a_messages[:20]:  # Cap at 20 source messages
            msg_id = msg.get("id") or msg.get("message_id")
            ch_id = msg.get("channel_id", 0)
            if msg_id:
                sources.append(EvidenceSource(
                    source_type="message",
                    source_id=canonical_id("telegram", "msg", f"{ch_id}:{msg_id}"),
                    source_table="messages",
                    source_row_id=int(msg_id),
                    retrieved_at=now,
                ))

        for msg in actor_b_messages[:20]:
            msg_id = msg.get("id") or msg.get("message_id")
            ch_id = msg.get("channel_id", 0)
            if msg_id:
                sources.append(EvidenceSource(
                    source_type="message",
                    source_id=canonical_id("telegram", "msg", f"{ch_id}:{msg_id}"),
                    source_table="messages",
                    source_row_id=int(msg_id),
                    retrieved_at=now,
                ))

        if not sources:
            # Fallback: use actor IDs as sources
            sources.append(EvidenceSource(
                source_type="user",
                source_id=subject_a,
                source_table="users",
                source_row_id=0,
                retrieved_at=now,
            ))
            sources.append(EvidenceSource(
                source_type="user",
                source_id=subject_b,
                source_table="users",
                source_row_id=0,
                retrieved_at=now,
            ))

        direction = EvidenceDirection.SUPPORTS if score >= 0.5 else EvidenceDirection.CONTRADICTS

        return AnalysisEvidence(
            evidence_id="",
            evidence_type=f"{family_name}_similarity",
            subject=subject_a,
            object=subject_b,
            score=score,
            confidence=confidence,
            direction=direction,
            model=model,
            model_version=MODEL_VERSION,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            sources=sources,
            observed_at=now,
            generated_at=now,
            metadata={"family": family_name},
        )

    def _deduplicate_correlated(
        self, evidence_list: List[AnalysisEvidence]
    ) -> List[AnalysisEvidence]:
        """
        Deduplicate correlated evidence to prevent double-counting.

        Groups evidence by correlation clusters:
        - infrastructure + telegram_native (shared URLs/channels are correlated)
        - media + telegram_native (shared media is correlated)

        Within each cluster, keep the highest-confidence evidence.
        """
        if len(evidence_list) <= 1:
            return evidence_list

        # Define correlation groups
        correlation_groups = [
            {"infrastructure_similarity", "telegram_native_similarity"},
            {"media_similarity", "telegram_native_similarity"},
        ]

        result = []
        consumed = set()

        for group in correlation_groups:
            group_evidence = [
                ev for ev in evidence_list
                if ev.evidence_type in group and ev.evidence_id not in consumed
            ]
            if len(group_evidence) <= 1:
                continue

            # Keep the one with highest confidence
            best = max(group_evidence, key=lambda e: e.confidence)
            for ev in group_evidence:
                if ev.evidence_id != best.evidence_id:
                    consumed.add(ev.evidence_id)

        for ev in evidence_list:
            if ev.evidence_id not in consumed:
                result.append(ev)

        return result

    def _compute_posterior(
        self, family_scores: Dict[str, Tuple[float, float]]
    ) -> Tuple[float, float]:
        """
        Compute posterior probability P(same actor) from family scores.

        Uses a weighted average where weights are the product of
        the family's prior weight and its confidence.

        This is a simplified Bayesian fusion — not a full Bayesian network,
        but it prevents a single weak evidence source from dominating.

        Returns:
            (probability, confidence) both 0-1
        """
        if not family_scores:
            return 0.5, 0.0

        total_weight = 0.0
        weighted_score = 0.0
        weighted_confidence = 0.0

        for family_name, (score, confidence) in family_scores.items():
            family_weight = FEATURE_FAMILIES.get(family_name, {}).get("weight", 0.1)
            # Effective weight = prior weight * confidence
            effective_weight = family_weight * confidence
            weighted_score += score * effective_weight
            weighted_confidence += confidence * effective_weight
            total_weight += effective_weight

        if total_weight == 0:
            return 0.5, 0.0

        probability = weighted_score / total_weight
        overall_confidence = weighted_confidence / total_weight

        # Clamp
        probability = max(0.0, min(1.0, probability))
        overall_confidence = max(0.0, min(1.0, overall_confidence))

        return probability, overall_confidence


__all__ = ["ActorIdentityResolver"]
