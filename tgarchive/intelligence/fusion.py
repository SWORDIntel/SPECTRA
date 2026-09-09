"""
SPECTRA Evidence Fusion & Calibration Engine
=============================================
Combines multiple evidence sources into calibrated posterior probabilities
for competing hypotheses.

Supports competing hypotheses:
- H0: same human
- H1: different human
- H2: shared organization
- H3: automation/bot
- H4: copied/shared content
- H5: compromised account

Key principle: adding another weak evidence source cannot suddenly convert
42% → 96% just because five correlated heuristic scores all fired.

Anti-double-counting: correlated evidence is grouped and counted once.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .schema import (
    ActorHypothesis,
    AnalysisEvidence,
    EvidenceDirection,
    EvidenceSource,
    HypothesisType,
    canonical_id,
)

logger = logging.getLogger(__name__)

MODEL_VERSION = "1.0.0"
FEATURE_SCHEMA_VERSION = "1"


# ─── Hypothesis Definitions ─────────────────────────────────────────────────

HYPOTHESES = {
    HypothesisType.SAME_ACTOR: "same human operating both accounts",
    HypothesisType.DIFFERENT_ACTOR: "different humans, no coordination",
    HypothesisType.SHARED_ORGANIZATION: "different people in same organization",
    HypothesisType.AUTOMATION: "automated/bot-generated content",
    HypothesisType.COPIED_CONTENT: "copied/shared content, not same actor",
    HypothesisType.COMPROMISED_ACCOUNT: "account takeover, different operator",
}

# Prior probabilities (uniform — can be updated based on context)
DEFAULT_PRIORS = {
    HypothesisType.SAME_ACTOR: 0.15,
    HypothesisType.DIFFERENT_ACTOR: 0.50,
    HypothesisType.SHARED_ORGANIZATION: 0.15,
    HypothesisType.AUTOMATION: 0.05,
    HypothesisType.COPIED_CONTENT: 0.10,
    HypothesisType.COMPROMISED_ACCOUNT: 0.05,
}


@dataclass
class FusionResult:
    """Result of fusing evidence across competing hypotheses."""
    hypotheses: List[ActorHypothesis] = field(default_factory=list)
    best_hypothesis: Optional[ActorHypothesis] = None
    evidence_used: List[str] = field(default_factory=list)
    correlated_evidence_merged: int = 0
    insufficient_evidence: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "best_hypothesis": self.best_hypothesis.to_dict() if self.best_hypothesis else None,
            "evidence_used": self.evidence_used,
            "correlated_evidence_merged": self.correlated_evidence_merged,
            "insufficient_evidence": self.insufficient_evidence,
            "generated_at": self.generated_at.isoformat(),
        }


class EvidenceFusionEngine:
    """
    Fuses evidence from multiple sources into calibrated posterior
    probabilities for competing hypotheses.

    Uses a simplified Bayesian approach:
    1. Start with prior probabilities for each hypothesis
    2. For each evidence item, compute likelihood P(evidence | hypothesis)
    3. Update posterior using Bayes' rule
    4. Normalize across all hypotheses

    Anti-double-counting: correlated evidence is grouped, and only the
    highest-confidence evidence from each correlation group contributes
    to the likelihood update.
    """

    def __init__(
        self,
        priors: Optional[Dict[HypothesisType, float]] = None,
        correlation_threshold: float = 0.7,
    ):
        """
        Args:
            priors: Prior probabilities for each hypothesis (default: uniform-ish)
            correlation_threshold: Evidence items with Jaccard similarity of
                                   source IDs above this are considered correlated
        """
        self.priors = priors or dict(DEFAULT_PRIORS)
        self.correlation_threshold = correlation_threshold

    def fuse(
        self,
        evidence: List[AnalysisEvidence],
        subject_a: str,
        subject_b: str,
    ) -> FusionResult:
        """
        Fuse evidence into competing hypotheses.

        Args:
            evidence: List of AnalysisEvidence items from various feature families
            subject_a: Canonical entity ID for actor A
            subject_b: Canonical entity ID for actor B

        Returns:
            FusionResult with all hypotheses ranked by posterior probability
        """
        if not evidence:
            return FusionResult(
                insufficient_evidence=["all"],
            )

        # Step 1: Deduplicate correlated evidence
        deduped, merged_count = self._deduplicate_correlated(evidence)

        # Step 2: Compute unnormalized log-posteriors for each hypothesis
        log_posteriors: Dict[HypothesisType, float] = {}
        confidences: Dict[HypothesisType, float] = {}
        for h_type in HYPOTHESES:
            lp, conf = self._compute_log_posterior(h_type, deduped)
            log_posteriors[h_type] = lp
            confidences[h_type] = conf

        # Step 3: Normalize using softmax across all hypotheses
        max_lp = max(log_posteriors.values())
        exp_vals = {h: math.exp(lp - max_lp) for h, lp in log_posteriors.items()}
        total = sum(exp_vals.values())
        normalized = {h: v / total for h, v in exp_vals.items()} if total > 0 else {h: 1.0 / len(HYPOTHESES) for h in HYPOTHESES}

        # Step 4: Build hypothesis objects
        hypotheses = []
        for h_type in HYPOTHESES:
            posterior = normalized[h_type]
            confidence = confidences[h_type]
            supporting, contradicting = self._classify_evidence(h_type, deduped)
            h = ActorHypothesis(
                hypothesis_id="",
                hypothesis_type=h_type,
                subject_a=subject_a,
                subject_b=subject_b,
                probability=posterior,
                confidence=confidence,
                supporting_evidence=supporting,
                contradicting_evidence=contradicting,
                insufficient_evidence_flags=[],
                generated_at=datetime.now(timezone.utc),
                model="spectra-fusion",
                model_version=MODEL_VERSION,
            )
            hypotheses.append(h)

        # Sort by probability (highest first)
        hypotheses.sort(key=lambda h: h.probability, reverse=True)
        best = hypotheses[0] if hypotheses else None

        return FusionResult(
            hypotheses=hypotheses,
            best_hypothesis=best,
            evidence_used=[ev.evidence_id for ev in deduped],
            correlated_evidence_merged=merged_count,
            generated_at=datetime.now(timezone.utc),
        )

    def _deduplicate_correlated(
        self, evidence: List[AnalysisEvidence]
    ) -> Tuple[List[AnalysisEvidence], int]:
        """
        Group correlated evidence and keep only the highest-confidence
        item from each group.

        Two evidence items are correlated if their source ID sets
        have Jaccard similarity above the threshold.
        """
        if len(evidence) <= 1:
            return evidence, 0

        # Build correlation groups using union-find
        parent = list(range(len(evidence)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for i in range(len(evidence)):
            for j in range(i + 1, len(evidence)):
                if self._is_correlated(evidence[i], evidence[j]):
                    union(i, j)

        # Group by root
        groups: Dict[int, List[int]] = {}
        for i in range(len(evidence)):
            root = find(i)
            groups.setdefault(root, []).append(i)

        # Keep highest-confidence from each group
        result = []
        merged = 0
        for group_indices in groups.values():
            if len(group_indices) == 1:
                result.append(evidence[group_indices[0]])
            else:
                best_idx = max(group_indices, key=lambda i: evidence[i].confidence)
                result.append(evidence[best_idx])
                merged += len(group_indices) - 1

        return result, merged

    def _is_correlated(
        self, ev_a: AnalysisEvidence, ev_b: AnalysisEvidence
    ) -> bool:
        """Check if two evidence items are correlated via source overlap."""
        # Compute Jaccard similarity of source IDs
        sources_a = {s.source_id for s in ev_a.sources}
        sources_b = {s.source_id for s in ev_b.sources}

        if not sources_a or not sources_b:
            return False

        intersection = sources_a & sources_b
        union = sources_a | sources_b
        jaccard = len(intersection) / len(union) if union else 0

        # Correlated if source overlap is high (regardless of evidence type)
        # This catches the case where multiple heuristics fire on the same data
        return jaccard >= self.correlation_threshold

    def _compute_log_posterior(
        self,
        hypothesis_type: HypothesisType,
        evidence: List[AnalysisEvidence],
    ) -> Tuple[float, float]:
        """
        Compute unnormalized log-posterior for a hypothesis given evidence.

        Uses a simplified Bayesian update:
        log P(H|E) ∝ log P(H) + Σ log P(E_i | H) * confidence_i

        Returns (log_posterior, confidence) — caller normalizes across hypotheses.
        """
        prior = self.priors.get(hypothesis_type, 0.1)
        log_prior = math.log(max(prior, 1e-10))

        log_likelihood = log_prior
        total_confidence_weight = 0.0

        for ev in evidence:
            likelihood, conf_weight = self._evidence_likelihood(ev, hypothesis_type)
            if likelihood > 0 and conf_weight > 0:
                log_likelihood += math.log(likelihood) * conf_weight
                total_confidence_weight += conf_weight

        # Confidence: based on total evidence weight
        confidence = min(1.0, total_confidence_weight / 5.0)

        return log_likelihood, confidence

    def _evidence_likelihood(
        self, evidence: AnalysisEvidence, hypothesis_type: HypothesisType
    ) -> Tuple[float, float]:
        """
        Estimate P(evidence | hypothesis) and the confidence weight.

        For SAME_ACTOR:
        - High score + SUPPORTS direction → high likelihood
        - Low score + CONTRADICTS direction → low likelihood

        For DIFFERENT_ACTOR:
        - High score + SUPPORTS direction → low likelihood
        - Low score + CONTRADICTS direction → high likelihood

        For other hypotheses, use intermediate mappings.
        """
        score = evidence.score
        confidence = evidence.confidence
        direction = evidence.direction

        # Base likelihood from score
        if hypothesis_type == HypothesisType.SAME_ACTOR:
            if direction == EvidenceDirection.SUPPORTS:
                likelihood = score  # High score supports same-actor
            else:
                likelihood = 1.0 - score  # Low score contradicts same-actor
        elif hypothesis_type == HypothesisType.DIFFERENT_ACTOR:
            if direction == EvidenceDirection.SUPPORTS:
                likelihood = 1.0 - score  # High score contradicts different-actor
            else:
                likelihood = score  # Low score supports different-actor
        elif hypothesis_type == HypothesisType.SHARED_ORGANIZATION:
            # Shared org: moderate similarity, shared infrastructure
            if "infrastructure" in evidence.evidence_type:
                likelihood = score * 0.8
            else:
                likelihood = 0.3 + score * 0.4  # Moderate
        elif hypothesis_type == HypothesisType.AUTOMATION:
            # Automation: high temporal regularity, low linguistic diversity
            if "temporal" in evidence.evidence_type:
                likelihood = score * 0.7
            else:
                likelihood = 0.2 + (1.0 - score) * 0.3
        elif hypothesis_type == HypothesisType.COPIED_CONTENT:
            # Copied content: high linguistic similarity but different infrastructure
            if "linguistic" in evidence.evidence_type:
                likelihood = score * 0.9
            elif "infrastructure" in evidence.evidence_type:
                likelihood = 1.0 - score
            else:
                likelihood = 0.3
        elif hypothesis_type == HypothesisType.COMPROMISED_ACCOUNT:
            # Compromised: temporal change-point, style shift
            if "changepoint" in evidence.evidence_type or "temporal" in evidence.evidence_type:
                likelihood = score * 0.8
            else:
                likelihood = 0.2
        else:
            likelihood = 0.5

        # Confidence weight: how much this evidence should influence the posterior
        conf_weight = confidence

        return likelihood, conf_weight

    def _classify_evidence(
        self,
        hypothesis_type: HypothesisType,
        evidence: List[AnalysisEvidence],
    ) -> Tuple[List[str], List[str]]:
        """
        Classify evidence as supporting or contradicting a hypothesis.
        Returns (supporting_ids, contradicting_ids).
        """
        supporting = []
        contradicting = []

        for ev in evidence:
            likelihood, _ = self._evidence_likelihood(ev, hypothesis_type)
            if likelihood >= 0.5:
                supporting.append(ev.evidence_id)
            else:
                contradicting.append(ev.evidence_id)

        return supporting, contradicting


__all__ = ["EvidenceFusionEngine", "FusionResult", "HYPOTHESES", "DEFAULT_PRIORS"]
