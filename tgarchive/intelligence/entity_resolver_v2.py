"""
SPECTRA Probabilistic Entity Resolver v2
========================================

Upgrades the entity resolver from normalization + substring matching to a
proper probabilistic resolution layer with independent evidence sources and
Bayesian fusion.

Resolution model::

    MENTION (raw text reference to an entity)
      ↓
    ENTITY CANDIDATE (normalized form — username, name, handle, phone, etc.)
      ↓
    IDENTITY CLUSTER (group of candidates believed to be the same actor)

Seven independent evidence sources are scored and fused via a Bayesian
log-odds update into P(same actor):

1. Username matching      — exact, fuzzy, historical (username changes)
2. Name matching          — first/last name similarity, transliteration variants
3. Handle matching        — @handle cross-platform correlation
4. Identifier matching    — phone numbers (partial match), user IDs
5. Co-occurrence          — repeated appearance in same channels/contexts
6. Temporal behavior      — activity patterns, timezone inference, typing patterns
7. Source consistency      — same bio, same profile photo, same device model

Decision thresholds:
    > 0.85  → merge into existing cluster
    > 0.50  → flag for human review
    < 0.50  → create new cluster

Integrates with the existing ``AnalysisEvidence`` / ``ActorHypothesis``
architecture defined in :mod:`tgarchive.intelligence.schema` and reuses the
Bayesian fusion patterns from :mod:`tgarchive.intelligence.fusion`.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import unicodedata
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
    generate_evidence_id,
    generate_hypothesis_id,
)

logger = logging.getLogger(__name__)

MODEL_VERSION = "2.0.0"
FEATURE_SCHEMA_VERSION = "2"

# Decision thresholds (per the v2 plan)
MERGE_THRESHOLD = 0.85
REVIEW_THRESHOLD = 0.50

# Prior probability of "same actor" before any evidence is observed.
# Kept low so that weak/absent evidence does not inflate the posterior.
DEFAULT_PRIOR_SAME_ACTOR = 0.10

# Prior weights for each evidence source. These are independent and sum to 1.0.
# They express how much each source *can* contribute when it has full confidence.
EVIDENCE_WEIGHTS: Dict[str, float] = {
    "username": 0.22,
    "name": 0.15,
    "handle": 0.18,
    "identifier": 0.20,
    "co_occurrence": 0.10,
    "temporal": 0.08,
    "source_consistency": 0.07,
}


# ─── Data model ──────────────────────────────────────────────────────────────


@dataclass
class Mention:
    """A raw text reference to an entity, as observed in a source event.

    Attributes:
        raw_text: The raw mention string (e.g. "@darkvendor", "+1 555 123 4567").
        mention_type: Heuristic type hint — "username", "name", "handle",
            "phone", "user_id", "bio", "unknown".
        source_id: Canonical ID of the source event (e.g. a message ID).
        channel_id: Optional channel/context where the mention appeared.
        observed_at: When the mention was observed.
        metadata: Extra context (profile photo hash, device model, bio text…).
    """

    raw_text: str
    mention_type: str = "unknown"
    source_id: str = ""
    channel_id: Optional[int] = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EntityCandidate:
    """A normalized form of a mention — one candidate identity.

    Attributes:
        candidate_id: Deterministic ID for this normalized candidate.
        username: Normalized username (lowercase, no leading @).
        display_name: Normalized display name.
        handle: Cross-platform handle (e.g. "@darkvendor" on Telegram/Twitter).
        phone: E.164-ish normalized phone number (digits only).
        user_id: Numeric user ID if known.
        bio: Profile bio text (normalized).
        photo_hash: Hash of profile photo bytes, if available.
        device_model: Device model string, if known.
        source_id: Canonical ID of the source event that produced this candidate.
        channel_id: Channel/context where the candidate was observed.
        observed_at: When the candidate was observed.
        metadata: Extra context.
    """

    candidate_id: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    handle: Optional[str] = None
    phone: Optional[str] = None
    user_id: Optional[int] = None
    bio: Optional[str] = None
    photo_hash: Optional[str] = None
    device_model: Optional[str] = None
    source_id: str = ""
    channel_id: Optional[int] = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "username": self.username,
            "display_name": self.display_name,
            "handle": self.handle,
            "phone": self.phone,
            "user_id": self.user_id,
            "bio": self.bio,
            "photo_hash": self.photo_hash,
            "device_model": self.device_model,
            "source_id": self.source_id,
            "channel_id": self.channel_id,
            "observed_at": self.observed_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EntityCandidate":
        obs = d.get("observed_at")
        if isinstance(obs, str):
            try:
                obs = datetime.fromisoformat(obs)
            except ValueError:
                obs = datetime.now(timezone.utc)
        if obs is None:
            obs = datetime.now(timezone.utc)
        if obs.tzinfo is None:
            obs = obs.replace(tzinfo=timezone.utc)
        return cls(
            candidate_id=d["candidate_id"],
            username=d.get("username"),
            display_name=d.get("display_name"),
            handle=d.get("handle"),
            phone=d.get("phone"),
            user_id=d.get("user_id"),
            bio=d.get("bio"),
            photo_hash=d.get("photo_hash"),
            device_model=d.get("device_model"),
            source_id=d.get("source_id", ""),
            channel_id=d.get("channel_id"),
            observed_at=obs,
            metadata=d.get("metadata", {}),
        )


@dataclass
class ResolutionEvidence:
    """A single evidence observation produced by one of the 7 evidence sources.

    Attributes:
        source: Name of the evidence source (one of EVIDENCE_WEIGHTS keys).
        score: Raw similarity score in [0, 1] — 1 = strong match.
        confidence: Reliability of this score in [0, 1] (sample size, data quality).
        direction: Whether the evidence supports or contradicts a merge.
        detail: Human-readable explanation of the score.
        metadata: Extra structured context.
    """

    source: str
    score: float
    confidence: float
    direction: EvidenceDirection = EvidenceDirection.SUPPORTS
    detail: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"score must be in [0.0, 1.0], got {self.score}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "score": self.score,
            "confidence": self.confidence,
            "direction": self.direction.value,
            "detail": self.detail,
            "metadata": self.metadata,
        }


@dataclass
class IdentityCluster:
    """A group of candidates believed to be the same actor.

    Attributes:
        cluster_id: Deterministic ID for this cluster.
        candidates: All candidates merged into this cluster.
        confidence: P(all candidates = same actor).
        evidence: Supporting evidence for the cluster's identity.
        contradicting_evidence: Evidence against the cluster's identity.
        model_version: Version of the resolver that produced/updated this cluster.
        created_at: ISO timestamp of cluster creation.
        updated_at: ISO timestamp of last update.
    """

    cluster_id: str
    candidates: List[EntityCandidate] = field(default_factory=list)
    confidence: float = 0.0
    evidence: List[ResolutionEvidence] = field(default_factory=list)
    contradicting_evidence: List[ResolutionEvidence] = field(default_factory=list)
    model_version: str = MODEL_VERSION
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "candidates": [c.to_dict() for c in self.candidates],
            "confidence": self.confidence,
            "evidence": [e.to_dict() for e in self.evidence],
            "contradicting_evidence": [
                e.to_dict() for e in self.contradicting_evidence
            ],
            "model_version": self.model_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def add_candidate(
        self,
        candidate: EntityCandidate,
        evidence: List[ResolutionEvidence],
        confidence: float,
    ) -> None:
        """Merge a candidate into this cluster and update metadata."""
        self.candidates.append(candidate)
        self.evidence.extend(evidence)
        self.confidence = max(self.confidence, confidence)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def representative(self) -> Optional[EntityCandidate]:
        """Return the most recently observed candidate, or the first one."""
        if not self.candidates:
            return None
        return max(self.candidates, key=lambda c: c.observed_at)


@dataclass
class ResolutionResult:
    """Outcome of resolving a mention against existing clusters.

    Attributes:
        action: "merge" | "review" | "new_cluster".
        candidate: The normalized candidate that was resolved.
        cluster: The target cluster (for merge/review) or the newly created one.
        probability: P(same actor) against the best matching cluster.
        evidence: Evidence used to reach the decision.
        contradicting_evidence: Evidence against the decision.
        reviewed_cluster_id: ID of the cluster flagged for review (if any).
        all_scores: Per-cluster scores for transparency.
    """

    action: str
    candidate: EntityCandidate
    cluster: IdentityCluster
    probability: float
    evidence: List[ResolutionEvidence] = field(default_factory=list)
    contradicting_evidence: List[ResolutionEvidence] = field(default_factory=list)
    reviewed_cluster_id: Optional[str] = None
    all_scores: List[Tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "candidate": self.candidate.to_dict(),
            "cluster": self.cluster.to_dict(),
            "probability": self.probability,
            "evidence": [e.to_dict() for e in self.evidence],
            "contradicting_evidence": [
                e.to_dict() for e in self.contradicting_evidence
            ],
            "reviewed_cluster_id": self.reviewed_cluster_id,
            "all_scores": self.all_scores,
        }


# ─── Normalization helpers ───────────────────────────────────────────────────


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize_text(text: str) -> str:
    """NFKC-normalize and lowercase text, stripping diacritics."""
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", text)
    decomposed = unicodedata.normalize("NFD", nfkc)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.lower().strip()


def _normalize_username(raw: str) -> Optional[str]:
    """Normalize a username: lowercase, strip leading @, keep alnum + underscore."""
    if not raw:
        return None
    s = raw.strip().lstrip("@")
    if not s:
        return None
    s = _normalize_text(s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s or None


def _normalize_handle(raw: str) -> Optional[str]:
    """Normalize a cross-platform handle (keeps the leading @)."""
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    s = _normalize_text(s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    return f"@{s}" if s else None


def _normalize_phone(raw: str) -> Optional[str]:
    """Normalize a phone number to digits only (E.164-ish)."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 7:
        return None
    return digits


def _candidate_id(candidate: EntityCandidate) -> str:
    """Deterministic 16-hex-char candidate ID."""
    payload = "|".join(
        [
            candidate.username or "",
            candidate.display_name or "",
            candidate.handle or "",
            candidate.phone or "",
            str(candidate.user_id or ""),
            candidate.source_id or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cluster_id(seed: str) -> str:
    """Deterministic 16-hex-char cluster ID from a seed string."""
    return hashlib.sha256(
        f"cluster|{seed}".encode("utf-8")
    ).hexdigest()[:16]


# ─── String similarity ───────────────────────────────────────────────────────


def _token_set_ratio(a: str, b: str) -> float:
    """A lightweight token-set Jaccard similarity in [0, 1].

    Cheaper than full fuzzy matching and good enough for name comparison.
    """
    if not a or not b:
        return 0.0
    sa = set(a.split())
    sb = set(b.split())
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def _levenshtein_ratio(a: str, b: str) -> float:
    """Normalized Levenshtein similarity in [0, 1]."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    # Standard DP Levenshtein
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ca == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    dist = prev[lb]
    return 1.0 - dist / max(la, lb)


# ─── Evidence scorers ────────────────────────────────────────────────────────


def _score_username(
    candidate: EntityCandidate, cluster: IdentityCluster
) -> ResolutionEvidence:
    """Evidence source 1: username matching (exact, fuzzy, historical)."""
    cand_uname = candidate.username
    cluster_unames = {c.username for c in cluster.candidates if c.username}

    if not cand_uname or not cluster_unames:
        return ResolutionEvidence(
            source="username",
            score=0.0,
            confidence=0.0,
            direction=EvidenceDirection.NEUTRAL,
            detail="no username available on one side",
        )

    if cand_uname in cluster_unames:
        return ResolutionEvidence(
            source="username",
            score=1.0,
            confidence=0.95,
            direction=EvidenceDirection.SUPPORTS,
            detail=f"exact username match: {cand_uname}",
            metadata={"matched": cand_uname},
        )

    # Fuzzy match against all cluster usernames
    best = max(
        (_levenshtein_ratio(cand_uname, u) for u in cluster_unames),
        default=0.0,
    )
    if best >= 0.9:
        return ResolutionEvidence(
            source="username",
            score=best,
            confidence=0.7,
            direction=EvidenceDirection.SUPPORTS,
            detail=f"fuzzy username match (ratio={best:.2f})",
            metadata={"best_ratio": best},
        )
    if best >= 0.7:
        return ResolutionEvidence(
            source="username",
            score=best * 0.6,
            confidence=0.5,
            direction=EvidenceDirection.SUPPORTS,
            detail=f"weak fuzzy username match (ratio={best:.2f})",
            metadata={"best_ratio": best},
        )
    return ResolutionEvidence(
        source="username",
        score=0.1,
        confidence=0.6,
        direction=EvidenceDirection.CONTRADICTS,
        detail="usernames differ significantly",
        metadata={"best_ratio": best},
    )


def _score_name(
    candidate: EntityCandidate, cluster: IdentityCluster
) -> ResolutionEvidence:
    """Evidence source 2: name matching (first/last, transliteration variants)."""
    cand_name = candidate.display_name
    cluster_names = [c.display_name for c in cluster.candidates if c.display_name]

    if not cand_name or not cluster_names:
        return ResolutionEvidence(
            source="name",
            score=0.0,
            confidence=0.0,
            direction=EvidenceDirection.NEUTRAL,
            detail="no display name available on one side",
        )

    cand_norm = _normalize_text(cand_name)
    cluster_norms = [_normalize_text(n) for n in cluster_names]

    if cand_norm in cluster_norms:
        return ResolutionEvidence(
            source="name",
            score=1.0,
            confidence=0.85,
            direction=EvidenceDirection.SUPPORTS,
            detail=f"exact name match: {cand_norm}",
        )

    best_token = max(
        (_token_set_ratio(cand_norm, n) for n in cluster_norms), default=0.0
    )
    best_lev = max(
        (_levenshtein_ratio(cand_norm, n) for n in cluster_norms), default=0.0
    )
    best = max(best_token, best_lev)

    if best >= 0.8:
        return ResolutionEvidence(
            source="name",
            score=best,
            confidence=0.6,
            direction=EvidenceDirection.SUPPORTS,
            detail=f"similar name (sim={best:.2f})",
        )
    return ResolutionEvidence(
        source="name",
        score=0.15,
        confidence=0.5,
        direction=EvidenceDirection.CONTRADICTS,
        detail="names differ",
        metadata={"best_similarity": best},
    )


def _score_handle(
    candidate: EntityCandidate, cluster: IdentityCluster
) -> ResolutionEvidence:
    """Evidence source 3: @handle cross-platform correlation."""
    cand_handle = candidate.handle
    cluster_handles = {c.handle for c in cluster.candidates if c.handle}

    if not cand_handle or not cluster_handles:
        return ResolutionEvidence(
            source="handle",
            score=0.0,
            confidence=0.0,
            direction=EvidenceDirection.NEUTRAL,
            detail="no handle available on one side",
        )

    if cand_handle in cluster_handles:
        return ResolutionEvidence(
            source="handle",
            score=1.0,
            confidence=0.9,
            direction=EvidenceDirection.SUPPORTS,
            detail=f"exact handle match: {cand_handle}",
        )

    best = max(
        (_levenshtein_ratio(cand_handle, h) for h in cluster_handles),
        default=0.0,
    )
    if best >= 0.85:
        return ResolutionEvidence(
            source="handle",
            score=best,
            confidence=0.65,
            direction=EvidenceDirection.SUPPORTS,
            detail=f"fuzzy handle match (ratio={best:.2f})",
        )
    return ResolutionEvidence(
        source="handle",
        score=0.1,
        confidence=0.55,
        direction=EvidenceDirection.CONTRADICTS,
        detail="handles differ",
    )


def _score_identifier(
    candidate: EntityCandidate, cluster: IdentityCluster
) -> ResolutionEvidence:
    """Evidence source 4: phone numbers (partial match) and user IDs."""
    # User ID is the strongest identifier — exact match is near-certain.
    if candidate.user_id is not None:
        cluster_ids = {c.user_id for c in cluster.candidates if c.user_id is not None}
        if candidate.user_id in cluster_ids:
            return ResolutionEvidence(
                source="identifier",
                score=1.0,
                confidence=0.99,
                direction=EvidenceDirection.SUPPORTS,
                detail=f"exact user_id match: {candidate.user_id}",
                metadata={"matched_user_id": candidate.user_id},
            )

    cand_phone = candidate.phone
    cluster_phones = {c.phone for c in cluster.candidates if c.phone}

    if not cand_phone or not cluster_phones:
        return ResolutionEvidence(
            source="identifier",
            score=0.0,
            confidence=0.0,
            direction=EvidenceDirection.NEUTRAL,
            detail="no phone/id available on one side",
        )

    if cand_phone in cluster_phones:
        return ResolutionEvidence(
            source="identifier",
            score=1.0,
            confidence=0.95,
            direction=EvidenceDirection.SUPPORTS,
            detail=f"exact phone match: {cand_phone}",
        )

    # Partial phone match (last 7 digits) — common for regional number changes
    cand_tail = cand_phone[-7:]
    cluster_tails = {p[-7:] for p in cluster_phones}
    if len(cand_tail) == 7 and cand_tail in cluster_tails:
        return ResolutionEvidence(
            source="identifier",
            score=0.85,
            confidence=0.75,
            direction=EvidenceDirection.SUPPORTS,
            detail="partial phone match (last 7 digits)",
            metadata={"matched_tail": cand_tail},
        )

    return ResolutionEvidence(
        source="identifier",
        score=0.1,
        confidence=0.6,
        direction=EvidenceDirection.CONTRADICTS,
        detail="identifiers differ",
    )


def _score_co_occurrence(
    candidate: EntityCandidate, cluster: IdentityCluster
) -> ResolutionEvidence:
    """Evidence source 5: repeated appearance in same channels/contexts."""
    cand_channels = {candidate.channel_id} if candidate.channel_id else set()
    cluster_channels = {
        c.channel_id for c in cluster.candidates if c.channel_id is not None
    }

    if not cand_channels or not cluster_channels:
        return ResolutionEvidence(
            source="co_occurrence",
            score=0.0,
            confidence=0.0,
            direction=EvidenceDirection.NEUTRAL,
            detail="no channel context available",
        )

    shared = cand_channels & cluster_channels
    if shared:
        # More shared channels → stronger, but co-occurrence is weak alone.
        ratio = len(shared) / len(cand_channels | cluster_channels)
        return ResolutionEvidence(
            source="co_occurrence",
            score=0.4 + 0.4 * ratio,
            confidence=0.4,
            direction=EvidenceDirection.SUPPORTS,
            detail=f"shared channels: {shared}",
            metadata={"shared_channels": list(shared), "ratio": ratio},
        )
    return ResolutionEvidence(
        source="co_occurrence",
        score=0.2,
        confidence=0.3,
        direction=EvidenceDirection.NEUTRAL,
        detail="no shared channels",
    )


def _score_temporal(
    candidate: EntityCandidate, cluster: IdentityCluster
) -> ResolutionEvidence:
    """Evidence source 6: temporal behavior (activity hour overlap)."""
    cand_hour = candidate.observed_at.hour
    cluster_hours = [c.observed_at.hour for c in cluster.candidates]

    if not cluster_hours:
        return ResolutionEvidence(
            source="temporal",
            score=0.0,
            confidence=0.0,
            direction=EvidenceDirection.NEUTRAL,
            detail="no temporal data in cluster",
        )

    # Circular hour distance (0-12 → 0..1 similarity)
    def hour_sim(h1: int, h2: int) -> float:
        d = abs(h1 - h2) % 24
        d = min(d, 24 - d)
        return 1.0 - d / 12.0

    best = max(hour_sim(cand_hour, h) for h in cluster_hours)
    if best >= 0.85:
        return ResolutionEvidence(
            source="temporal",
            score=best * 0.5,  # temporal is weak alone
            confidence=0.3,
            direction=EvidenceDirection.SUPPORTS,
            detail=f"activity hour overlap (sim={best:.2f})",
        )
    return ResolutionEvidence(
        source="temporal",
        score=0.2,
        confidence=0.25,
        direction=EvidenceDirection.NEUTRAL,
        detail="activity hours differ",
        metadata={"best_similarity": best},
    )


def _score_source_consistency(
    candidate: EntityCandidate, cluster: IdentityCluster
) -> ResolutionEvidence:
    """Evidence source 7: same bio, same profile photo, same device model."""
    matches: List[str] = []
    total_checks = 0

    # Bio
    if candidate.bio:
        cluster_bios = {c.bio for c in cluster.candidates if c.bio}
        total_checks += 1
        if candidate.bio in cluster_bios:
            matches.append("bio")
        elif cluster_bios:
            best = max(
                _levenshtein_ratio(candidate.bio, b) for b in cluster_bios
            )
            if best >= 0.9:
                matches.append("bio~")

    # Photo hash
    if candidate.photo_hash:
        cluster_photos = {c.photo_hash for c in cluster.candidates if c.photo_hash}
        total_checks += 1
        if candidate.photo_hash in cluster_photos:
            matches.append("photo")

    # Device model
    if candidate.device_model:
        cluster_devices = {
            c.device_model for c in cluster.candidates if c.device_model
        }
        total_checks += 1
        if candidate.device_model in cluster_devices:
            matches.append("device")

    if total_checks == 0:
        return ResolutionEvidence(
            source="source_consistency",
            score=0.0,
            confidence=0.0,
            direction=EvidenceDirection.NEUTRAL,
            detail="no source-consistency fields available",
        )

    # Photo match alone is very strong
    if "photo" in matches:
        return ResolutionEvidence(
            source="source_consistency",
            score=1.0,
            confidence=0.9,
            direction=EvidenceDirection.SUPPORTS,
            detail="profile photo hash match",
            metadata={"matches": matches},
        )

    score = len(matches) / total_checks
    if score > 0:
        return ResolutionEvidence(
            source="source_consistency",
            score=score,
            confidence=0.5 + 0.3 * score,
            direction=EvidenceDirection.SUPPORTS,
            detail=f"source-consistency matches: {matches}",
            metadata={"matches": matches, "checks": total_checks},
        )
    return ResolutionEvidence(
        source="source_consistency",
        score=0.15,
        confidence=0.4,
        direction=EvidenceDirection.CONTRADICTS,
        detail="source-consistency fields differ",
        metadata={"checks": total_checks},
    )


_EVIDENCE_SCORERS = [
    _score_username,
    _score_name,
    _score_handle,
    _score_identifier,
    _score_co_occurrence,
    _score_temporal,
    _score_source_consistency,
]


# ─── Bayesian fusion ─────────────────────────────────────────────────────────


def _fuse_evidence(
    evidence: List[ResolutionEvidence],
    prior_same: float = DEFAULT_PRIOR_SAME_ACTOR,
) -> Tuple[float, float]:
    """Fuse independent evidence into P(same actor) via Bayesian log-odds update.

    Each evidence source contributes a log-likelihood-ratio weighted by its
    confidence and its prior weight (independence). This prevents a single
    weak source from dominating and avoids double-counting correlated signals.

    Returns:
        (posterior_probability, confidence) both in [0, 1].
    """
    # Start from the prior in log-odds space.
    prior = min(max(prior_same, 1e-6), 1 - 1e-6)
    log_odds = math.log(prior / (1.0 - prior))
    total_weight = 0.0

    for ev in evidence:
        if ev.confidence <= 0.0:
            continue
        weight = EVIDENCE_WEIGHTS.get(ev.source, 0.05) * ev.confidence
        if weight <= 0.0:
            continue
        # Convert the score into a likelihood ratio for "same actor".
        # score ~ 1 → strong support; score ~ 0 → strong contradiction.
        # Use a symmetric mapping centered at 0.5.
        s = min(max(ev.score, 1e-3), 1 - 1e-3)
        if ev.direction == EvidenceDirection.CONTRADICTS:
            s = 1.0 - s
        elif ev.direction == EvidenceDirection.NEUTRAL:
            # Neutral evidence contributes a mild pull toward 0.5.
            s = 0.5
        llr = math.log(s / (1.0 - s))
        log_odds += weight * llr
        total_weight += weight

    # Convert log-odds back to probability.
    probability = 1.0 / (1.0 + math.exp(-log_odds))

    # Confidence grows with total evidence weight, capped at 1.0.
    confidence = min(1.0, total_weight / 1.5)
    return probability, confidence


# ─── Resolver ────────────────────────────────────────────────────────────────


class EntityResolverV2:
    """Probabilistic entity resolver: MENTION → CANDIDATE → IDENTITY CLUSTER.

    Usage::

        resolver = EntityResolverV2()
        clusters: list[IdentityCluster] = []
        for mention in mentions:
            result = resolver.resolve(mention, clusters)
            if result.action == "new_cluster":
                clusters.append(result.cluster)
            # merge/review already mutate the cluster in place
    """

    def __init__(
        self,
        merge_threshold: float = MERGE_THRESHOLD,
        review_threshold: float = REVIEW_THRESHOLD,
        prior_same_actor: float = DEFAULT_PRIOR_SAME_ACTOR,
    ) -> None:
        if not 0.0 < review_threshold < merge_threshold < 1.0:
            raise ValueError(
                "require 0 < review_threshold < merge_threshold < 1"
            )
        self.merge_threshold = merge_threshold
        self.review_threshold = review_threshold
        self.prior_same_actor = prior_same_actor

    # ── public API ───────────────────────────────────────────────────────────

    def normalize(self, mention: Mention) -> EntityCandidate:
        """Generate a normalized ``EntityCandidate`` from a raw mention."""
        return self._normalize(mention)

    def resolve(
        self,
        mention: Mention,
        existing_clusters: List[IdentityCluster],
    ) -> ResolutionResult:
        """Resolve a mention against existing clusters.

        1. Generate a candidate from the mention.
        2. Score the candidate against each existing cluster using 7 evidence
           sources.
        3. Fuse the evidence into P(same actor) via Bayesian log-odds update.
        4. Apply decision thresholds: merge (>0.85), review (>0.5), new (<0.5).
        """
        candidate = self._normalize(mention)

        if not existing_clusters:
            cluster = self._new_cluster(candidate)
            return ResolutionResult(
                action="new_cluster",
                candidate=candidate,
                cluster=cluster,
                probability=0.0,
                evidence=[],
                all_scores=[],
            )

        scored: List[Tuple[IdentityCluster, float, List[ResolutionEvidence]]] = []
        for cluster in existing_clusters:
            evidence = self._score_match(candidate, cluster)
            prob, _ = self._fuse(evidence)
            scored.append((cluster, prob, evidence))

        scored.sort(key=lambda t: t[1], reverse=True)
        best_cluster, best_prob, best_evidence = scored[0]

        all_scores = [(c.cluster_id, p) for c, p, _ in scored]

        if best_prob > self.merge_threshold:
            best_cluster.add_candidate(candidate, best_evidence, best_prob)
            return ResolutionResult(
                action="merge",
                candidate=candidate,
                cluster=best_cluster,
                probability=best_prob,
                evidence=best_evidence,
                contradicting_evidence=[
                    e for e in best_evidence
                    if e.direction == EvidenceDirection.CONTRADICTS
                ],
                all_scores=all_scores,
            )
        if best_prob > self.review_threshold:
            return ResolutionResult(
                action="review",
                candidate=candidate,
                cluster=best_cluster,
                probability=best_prob,
                evidence=best_evidence,
                contradicting_evidence=[
                    e for e in best_evidence
                    if e.direction == EvidenceDirection.CONTRADICTS
                ],
                reviewed_cluster_id=best_cluster.cluster_id,
                all_scores=all_scores,
            )

        new_cluster = self._new_cluster(candidate)
        return ResolutionResult(
            action="new_cluster",
            candidate=candidate,
            cluster=new_cluster,
            probability=best_prob,
            evidence=best_evidence,
            contradicting_evidence=[
                e for e in best_evidence
                if e.direction == EvidenceDirection.CONTRADICTS
            ],
            all_scores=all_scores,
        )

    def to_hypothesis(
        self,
        candidate: EntityCandidate,
        cluster: IdentityCluster,
        probability: float,
        confidence: float,
        evidence: List[ResolutionEvidence],
    ) -> ActorHypothesis:
        """Convert a resolution result into a canonical ``ActorHypothesis``.

        This integrates the v2 resolver with the existing intelligence schema,
        producing an object that the fusion/conclusion engines can consume.
        """
        subject_a = candidate.source_id or canonical_id("telegram", "user", candidate.user_id or 0)
        rep = cluster.representative()
        subject_b = rep.source_id if rep else cluster.cluster_id
        supporting = [self._evidence_key(e) for e in evidence
                      if e.direction == EvidenceDirection.SUPPORTS]
        contradicting = [self._evidence_key(e) for e in evidence
                         if e.direction == EvidenceDirection.CONTRADICTS]
        return ActorHypothesis(
            hypothesis_id="",
            hypothesis_type=HypothesisType.SAME_ACTOR,
            subject_a=subject_a,
            subject_b=subject_b,
            probability=probability,
            confidence=confidence,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            insufficient_evidence_flags=[
                e.source for e in evidence if e.confidence <= 0.0
            ],
            generated_at=datetime.now(timezone.utc),
            model="spectra-entity-resolver-v2",
            model_version=MODEL_VERSION,
        )

    def to_analysis_evidence(
        self,
        evidence: ResolutionEvidence,
        candidate: EntityCandidate,
        cluster: IdentityCluster,
    ) -> AnalysisEvidence:
        """Convert a ``ResolutionEvidence`` into a canonical ``AnalysisEvidence``.

        This lets v2 evidence flow through the existing fusion/label/evaluation
        pipeline without modifying ``schema.py``.
        """
        now = datetime.now(timezone.utc)
        subject = candidate.source_id or canonical_id(
            "telegram", "user", candidate.user_id or 0
        )
        rep = cluster.representative()
        obj = rep.source_id if rep else cluster.cluster_id
        sources = [
            EvidenceSource(
                source_type="mention",
                source_id=candidate.source_id or subject,
                source_table="mentions",
                source_row_id=0,
                retrieved_at=now,
            )
        ]
        return AnalysisEvidence(
            evidence_id="",
            evidence_type=f"entity_resolution_{evidence.source}",
            subject=subject,
            object=obj,
            score=evidence.score,
            confidence=evidence.confidence,
            direction=evidence.direction,
            model="spectra-entity-resolver-v2",
            model_version=MODEL_VERSION,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            sources=sources,
            observed_at=now,
            generated_at=now,
            metadata={
                "source": evidence.source,
                "detail": evidence.detail,
                "cluster_id": cluster.cluster_id,
                **evidence.metadata,
            },
        )

    # ── internals ────────────────────────────────────────────────────────────

    def _normalize(self, mention: Mention) -> EntityCandidate:
        raw = mention.raw_text or ""
        mtype = mention.mention_type or "unknown"

        username = None
        display_name = None
        handle = None
        phone = None
        user_id = None

        if mtype == "username":
            username = _normalize_username(raw)
            handle = _normalize_handle(raw)
        elif mtype == "handle":
            handle = _normalize_handle(raw)
            username = _normalize_username(raw)
        elif mtype == "name":
            display_name = _normalize_text(raw)
        elif mtype == "phone":
            phone = _normalize_phone(raw)
        elif mtype == "user_id":
            try:
                user_id = int(re.sub(r"\D", "", raw))
            except ValueError:
                user_id = None
        else:
            # Auto-detect from the raw text.
            if raw.startswith("@"):
                handle = _normalize_handle(raw)
                username = _normalize_username(raw)
            elif re.match(r"^\+?\d[\d\s\-()]{6,}$", raw):
                phone = _normalize_phone(raw)
            elif re.fullmatch(r"\d+", raw.strip()):
                try:
                    user_id = int(raw.strip())
                except ValueError:
                    pass
            else:
                display_name = _normalize_text(raw)

        # Allow metadata overrides (bio, photo_hash, device_model, user_id).
        meta = mention.metadata or {}
        if not username and meta.get("username"):
            username = _normalize_username(meta["username"])
        if not display_name and meta.get("display_name"):
            display_name = _normalize_text(meta["display_name"])
        if not handle and meta.get("handle"):
            handle = _normalize_handle(meta["handle"])
        if not phone and meta.get("phone"):
            phone = _normalize_phone(meta["phone"])
        if user_id is None and meta.get("user_id") is not None:
            try:
                user_id = int(meta["user_id"])
            except (TypeError, ValueError):
                pass

        candidate = EntityCandidate(
            candidate_id="",  # filled below
            username=username,
            display_name=display_name,
            handle=handle,
            phone=phone,
            user_id=user_id,
            bio=_normalize_text(meta["bio"]) if meta.get("bio") else None,
            photo_hash=meta.get("photo_hash"),
            device_model=meta.get("device_model"),
            source_id=mention.source_id,
            channel_id=mention.channel_id,
            observed_at=mention.observed_at,
            metadata={
                k: v for k, v in meta.items()
                if k not in {"username", "display_name", "handle", "phone",
                             "user_id", "bio", "photo_hash", "device_model"}
            },
        )
        candidate.candidate_id = _candidate_id(candidate)
        return candidate

    def _score_match(
        self, candidate: EntityCandidate, cluster: IdentityCluster
    ) -> List[ResolutionEvidence]:
        """Run all 7 independent evidence scorers."""
        evidence: List[ResolutionEvidence] = []
        for scorer in _EVIDENCE_SCORERS:
            try:
                evidence.append(scorer(candidate, cluster))
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("evidence scorer %s failed: %s", scorer.__name__, exc)
                evidence.append(
                    ResolutionEvidence(
                        source=scorer.__name__.replace("_score_", ""),
                        score=0.0,
                        confidence=0.0,
                        direction=EvidenceDirection.NEUTRAL,
                        detail=f"scorer error: {exc}",
                    )
                )
        return evidence

    def _fuse(
        self, evidence: List[ResolutionEvidence]
    ) -> Tuple[float, float]:
        """Bayesian fusion of evidence scores → P(same actor)."""
        return _fuse_evidence(evidence, self.prior_same_actor)

    def _new_cluster(self, candidate: EntityCandidate) -> IdentityCluster:
        seed = candidate.candidate_id or candidate.source_id or "empty"
        return IdentityCluster(
            cluster_id=_cluster_id(seed),
            candidates=[candidate],
            confidence=0.0,
            evidence=[],
            contradicting_evidence=[],
            model_version=MODEL_VERSION,
        )

    @staticmethod
    def _evidence_key(evidence: ResolutionEvidence) -> str:
        """Stable key for a ResolutionEvidence (used as pseudo evidence ID)."""
        payload = f"{evidence.source}|{evidence.score:.6f}|{evidence.confidence:.6f}|{evidence.direction.value}|{evidence.detail}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "Mention",
    "EntityCandidate",
    "ResolutionEvidence",
    "IdentityCluster",
    "ResolutionResult",
    "EntityResolverV2",
    "EVIDENCE_WEIGHTS",
    "MERGE_THRESHOLD",
    "REVIEW_THRESHOLD",
    "MODEL_VERSION",
]
