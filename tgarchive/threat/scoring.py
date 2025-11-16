"""
SPECTRA Threat Actor Scoring Engine
====================================
Calculates threat scores (1-10) for actors based on indicators, behavior, and network.

Features:
- Multi-factor threat scoring
- Confidence calculation
- Actor classification
- Temporal pattern analysis
- Behavioral profiling
"""
from __future__ import annotations

import logging
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from .indicators import ThreatIndicator, ThreatLevel

logger = logging.getLogger(__name__)


class ThreatClassification(Enum):
    """Actor threat classification levels."""
    HARMLESS = "Harmless"
    LOW_RISK = "Low Risk"
    MEDIUM_RISK = "Medium Risk"
    HIGH_RISK = "High Risk"
    CRITICAL_RISK = "Critical Risk - Nation State / APT"


@dataclass
class BehavioralFlag:
    """A behavioral indicator of threat activity."""
    flag_type: str
    description: str
    severity: float
    confidence: float = 1.0
    detected_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "flag_type": self.flag_type,
            "description": self.description,
            "severity": self.severity,
            "confidence": self.confidence,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
        }


@dataclass
class ThreatActorProfile:
    """Complete threat actor profile with scoring."""
    user_id: int
    username: str
    threat_score: float  # 1.0 - 10.0
    confidence: float    # 0.0 - 1.0
    classification: ThreatClassification

    # Indicators
    keyword_indicators: List[ThreatIndicator] = field(default_factory=list)
    pattern_indicators: List[ThreatIndicator] = field(default_factory=list)
    behavioral_flags: List[BehavioralFlag] = field(default_factory=list)

    # Activity metrics
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    message_count: int = 0
    channels: List[int] = field(default_factory=list)

    # Network metrics
    associate_count: int = 0
    network_threat_score: float = 0.0

    # Metadata
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    last_updated: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "threat_score": round(self.threat_score, 2),
            "confidence": round(self.confidence, 2),
            "classification": self.classification.value,
            "indicators": {
                "keyword_count": len(self.keyword_indicators),
                "pattern_count": len(self.pattern_indicators),
                "behavioral_count": len(self.behavioral_flags),
            },
            "activity": {
                "first_seen": self.first_seen.isoformat() if self.first_seen else None,
                "last_seen": self.last_seen.isoformat() if self.last_seen else None,
                "message_count": self.message_count,
                "channel_count": len(self.channels),
            },
            "network": {
                "associate_count": self.associate_count,
                "network_threat_score": round(self.network_threat_score, 2),
            },
            "tags": self.tags,
            "notes": self.notes,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


class BehavioralAnalyzer:
    """Analyzes behavioral patterns for threat indicators."""

    @staticmethod
    def analyze_activity_patterns(
        message_timestamps: List[datetime],
    ) -> List[BehavioralFlag]:
        """Analyze activity patterns for suspicious behavior."""
        flags = []

        if not message_timestamps or len(message_timestamps) < 5:
            return flags

        # Sort timestamps
        timestamps = sorted(message_timestamps)

        # Check for activity spikes
        # Compare recent activity to historical average
        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(days=7)
        historical_cutoff = now - timedelta(days=90)

        recent_messages = [t for t in timestamps if t >= recent_cutoff]
        historical_messages = [t for t in timestamps if historical_cutoff <= t < recent_cutoff]

        if historical_messages:
            historical_rate = len(historical_messages) / 83  # messages per day
            recent_rate = len(recent_messages) / 7 if recent_messages else 0

            if recent_rate > historical_rate * 3:  # 3x spike
                flags.append(BehavioralFlag(
                    flag_type="activity_spike",
                    description=f"Activity spike: {recent_rate:.1f} msgs/day (historical: {historical_rate:.1f})",
                    severity=2.0,
                    confidence=0.8,
                ))

        # Check for unusual posting hours (potential OPSEC)
        hours = [t.hour for t in timestamps]
        night_posts = len([h for h in hours if 0 <= h < 6])  # Midnight to 6am

        if night_posts > len(hours) * 0.6:  # More than 60% night posts
            flags.append(BehavioralFlag(
                flag_type="unusual_hours",
                description=f"Unusual posting hours: {night_posts}/{len(hours)} during night (0-6am)",
                severity=1.0,
                confidence=0.6,
            ))

        # Check for regular intervals (bot-like behavior)
        if len(timestamps) >= 10:
            intervals = [(timestamps[i+1] - timestamps[i]).total_seconds() / 60
                        for i in range(len(timestamps) - 1)]

            if len(set(int(i) for i in intervals)) < len(intervals) * 0.3:  # High regularity
                flags.append(BehavioralFlag(
                    flag_type="regular_intervals",
                    description="Highly regular posting intervals (potential automation)",
                    severity=1.5,
                    confidence=0.7,
                ))

        return flags

    @staticmethod
    def analyze_content_patterns(messages: List[str]) -> List[BehavioralFlag]:
        """Analyze message content for behavioral indicators."""
        flags = []

        if not messages:
            return flags

        # Check for OPSEC/encryption mentions
        opsec_keywords = ["opsec", "pgp", "gpg", "encryption", "secure communication",
                         "signal", "telegram secret chat", "tor", "vpn", "dead drop"]

        opsec_count = sum(1 for msg in messages
                         if any(k in msg.lower() for k in opsec_keywords))

        if opsec_count > len(messages) * 0.2:  # More than 20% mention OPSEC
            flags.append(BehavioralFlag(
                flag_type="opsec_aware",
                description=f"OPSEC-aware communication: {opsec_count}/{len(messages)} messages",
                severity=2.0,
                confidence=0.8,
            ))

        # Check for code snippets (potential exploits)
        code_indicators = ["```", "function", "class ", "import ", "def ", "void ",
                          "int main", "#include"]

        code_count = sum(1 for msg in messages
                        if any(ind in msg for ind in code_indicators))

        if code_count > len(messages) * 0.15:  # More than 15% contain code
            flags.append(BehavioralFlag(
                flag_type="code_sharing",
                description=f"Frequent code sharing: {code_count}/{len(messages)} messages",
                severity=1.5,
                confidence=0.7,
            ))

        # Check for link sharing patterns
        link_count = sum(1 for msg in messages if "http://" in msg or "https://" in msg)

        if link_count > len(messages) * 0.5:  # More than 50% contain links
            flags.append(BehavioralFlag(
                flag_type="link_sharing",
                description=f"High link sharing activity: {link_count}/{len(messages)} messages",
                severity=1.0,
                confidence=0.6,
            ))

        return flags


class ThreatScorer:
    """
    Calculates comprehensive threat scores for actors.

    Scoring Factors:
    1. Keyword indicators (30% weight)
    2. Pattern indicators (25% weight)
    3. Behavioral analysis (20% weight)
    4. Network associations (15% weight)
    5. Temporal patterns (10% weight)
    """

    # Scoring weights
    KEYWORD_WEIGHT = 0.30
    PATTERN_WEIGHT = 0.25
    BEHAVIORAL_WEIGHT = 0.20
    NETWORK_WEIGHT = 0.15
    TEMPORAL_WEIGHT = 0.10

    @classmethod
    def calculate_threat_score(
        cls,
        keyword_indicators: List[ThreatIndicator],
        pattern_indicators: List[ThreatIndicator],
        behavioral_flags: List[BehavioralFlag],
        network_threat_score: float = 0.0,
        message_count: int = 1,
        time_span_days: int = 1,
    ) -> Tuple[float, float]:
        """
        Calculate threat score and confidence.

        Args:
            keyword_indicators: List of keyword indicators
            pattern_indicators: List of pattern indicators
            behavioral_flags: List of behavioral flags
            network_threat_score: Threat score from network associations
            message_count: Total message count
            time_span_days: Days between first and last message

        Returns:
            (threat_score, confidence) tuple
        """
        # Base score
        base_score = 1.0

        # Factor 1: Keyword indicators
        keyword_score = 0.0
        if keyword_indicators:
            total_keyword_severity = sum(i.severity for i in keyword_indicators)
            keyword_score = min(5.0, total_keyword_severity / max(message_count, 1))

        # Factor 2: Pattern indicators
        pattern_score = 0.0
        if pattern_indicators:
            total_pattern_severity = sum(i.severity for i in pattern_indicators)
            pattern_score = min(5.0, total_pattern_severity / max(message_count, 1))

        # Factor 3: Behavioral analysis
        behavioral_score = 0.0
        if behavioral_flags:
            total_behavioral_severity = sum(f.severity for f in behavioral_flags)
            behavioral_score = min(3.0, total_behavioral_severity)

        # Factor 4: Network associations (passed in pre-calculated)
        network_score = min(3.0, network_threat_score)

        # Factor 5: Temporal patterns
        temporal_score = 0.0
        if time_span_days > 30:  # Sustained activity bonus
            temporal_score = min(1.0, time_span_days / 365)

        # Weighted sum
        total_score = (
            keyword_score * cls.KEYWORD_WEIGHT +
            pattern_score * cls.PATTERN_WEIGHT +
            behavioral_score * cls.BEHAVIORAL_WEIGHT +
            network_score * cls.NETWORK_WEIGHT +
            temporal_score * cls.TEMPORAL_WEIGHT
        )

        # Final score (1-10 scale)
        final_score = min(10.0, max(1.0, base_score + total_score))

        # Calculate confidence
        confidence = cls._calculate_confidence(
            keyword_indicators,
            pattern_indicators,
            behavioral_flags,
            message_count,
            time_span_days,
        )

        return final_score, confidence

    @staticmethod
    def _calculate_confidence(
        keyword_indicators: List[ThreatIndicator],
        pattern_indicators: List[ThreatIndicator],
        behavioral_flags: List[BehavioralFlag],
        message_count: int,
        time_span_days: int,
    ) -> float:
        """
        Calculate confidence score (0-1) for threat assessment.

        Higher confidence when:
        - More indicators detected
        - Multiple indicator types
        - Higher message count
        - Longer observation period
        """
        # Indicator diversity
        indicator_types = set()
        if keyword_indicators:
            indicator_types.add("keyword")
        if pattern_indicators:
            indicator_types.add("pattern")
        if behavioral_flags:
            indicator_types.add("behavioral")

        diversity_score = len(indicator_types) / 3.0  # Max 3 types

        # Indicator count (normalized to 0-1)
        total_indicators = len(keyword_indicators) + len(pattern_indicators) + len(behavioral_flags)
        count_score = min(1.0, total_indicators / 10.0)  # 10+ indicators = max

        # Message volume (normalized to 0-1)
        volume_score = min(1.0, message_count / 100.0)  # 100+ messages = max

        # Time span (normalized to 0-1)
        time_score = min(1.0, time_span_days / 365.0)  # 365+ days = max

        # Weighted confidence
        confidence = (
            diversity_score * 0.4 +
            count_score * 0.3 +
            volume_score * 0.2 +
            time_score * 0.1
        )

        return min(1.0, max(0.0, confidence))

    @staticmethod
    def classify_threat_level(score: float) -> ThreatClassification:
        """Classify threat based on score."""
        if score >= 9.0:
            return ThreatClassification.CRITICAL_RISK
        elif score >= 7.0:
            return ThreatClassification.HIGH_RISK
        elif score >= 5.0:
            return ThreatClassification.MEDIUM_RISK
        elif score >= 3.0:
            return ThreatClassification.LOW_RISK
        else:
            return ThreatClassification.HARMLESS


class ThreatProfiler:
    """
    Main threat profiling engine.
    Combines all analysis components to create actor profiles.
    """

    def __init__(self):
        """Initialize threat profiler."""
        self.behavioral_analyzer = BehavioralAnalyzer()
        self.scorer = ThreatScorer()

    def create_profile(
        self,
        user_id: int,
        username: str,
        keyword_indicators: List[ThreatIndicator],
        pattern_indicators: List[ThreatIndicator],
        messages: List[Dict[str, Any]],
        network_threat_score: float = 0.0,
        associate_count: int = 0,
    ) -> ThreatActorProfile:
        """
        Create comprehensive threat actor profile.

        Args:
            user_id: User ID
            username: Username
            keyword_indicators: Detected keyword indicators
            pattern_indicators: Detected pattern indicators
            messages: List of message dictionaries
            network_threat_score: Pre-calculated network threat score
            associate_count: Number of associates

        Returns:
            ThreatActorProfile object
        """
        # Extract message content and timestamps
        message_texts = [m.get('content', m.get('text', '')) for m in messages]
        message_timestamps = []

        for msg in messages:
            if 'date' in msg:
                try:
                    if isinstance(msg['date'], datetime):
                        message_timestamps.append(msg['date'])
                    else:
                        message_timestamps.append(datetime.fromisoformat(msg['date']))
                except (ValueError, TypeError):
                    pass

        # Behavioral analysis
        activity_flags = self.behavioral_analyzer.analyze_activity_patterns(message_timestamps)
        content_flags = self.behavioral_analyzer.analyze_content_patterns(message_texts)
        all_behavioral_flags = activity_flags + content_flags

        # Calculate time span
        time_span_days = 1
        if len(message_timestamps) >= 2:
            first_time = min(message_timestamps)
            last_time = max(message_timestamps)
            time_span_days = max(1, (last_time - first_time).days)

        # Calculate threat score
        threat_score, confidence = self.scorer.calculate_threat_score(
            keyword_indicators=keyword_indicators,
            pattern_indicators=pattern_indicators,
            behavioral_flags=all_behavioral_flags,
            network_threat_score=network_threat_score,
            message_count=len(messages),
            time_span_days=time_span_days,
        )

        # Classify threat
        classification = self.scorer.classify_threat_level(threat_score)

        # Auto-generate tags
        tags = self._generate_tags(
            threat_score,
            keyword_indicators,
            pattern_indicators,
            all_behavioral_flags,
        )

        # Create profile
        profile = ThreatActorProfile(
            user_id=user_id,
            username=username,
            threat_score=threat_score,
            confidence=confidence,
            classification=classification,
            keyword_indicators=keyword_indicators,
            pattern_indicators=pattern_indicators,
            behavioral_flags=all_behavioral_flags,
            first_seen=min(message_timestamps) if message_timestamps else None,
            last_seen=max(message_timestamps) if message_timestamps else None,
            message_count=len(messages),
            channels=list(set(m.get('channel_id', 0) for m in messages)),
            associate_count=associate_count,
            network_threat_score=network_threat_score,
            tags=tags,
            last_updated=datetime.now(timezone.utc),
        )

        return profile

    @staticmethod
    def _generate_tags(
        threat_score: float,
        keyword_indicators: List[ThreatIndicator],
        pattern_indicators: List[ThreatIndicator],
        behavioral_flags: List[BehavioralFlag],
    ) -> List[str]:
        """Auto-generate tags based on indicators."""
        tags = []

        # Threat level tag
        if threat_score >= 9.0:
            tags.append("APT")
            tags.append("Nation-State")
        elif threat_score >= 7.0:
            tags.append("Advanced-Threat")
        elif threat_score >= 5.0:
            tags.append("Cybercriminal")

        # Keyword-based tags
        keyword_values = [k.value.lower() for k in keyword_indicators]

        if any("ransomware" in k for k in keyword_values):
            tags.append("Ransomware")
        if any("apt" in k for k in keyword_values):
            tags.append("APT-Indicators")
        if any(k in ["zero-day", "0day"] for k in keyword_values):
            tags.append("Zero-Day")
        if any("darknet" in k or "dark web" in k for k in keyword_values):
            tags.append("Darknet")

        # Pattern-based tags
        pattern_types = set(p.metadata.get("pattern_type", "") for p in pattern_indicators)

        if "bitcoin" in pattern_types or "monero" in pattern_types:
            tags.append("Cryptocurrency")
        if "onion" in pattern_types:
            tags.append("Tor")
        if "cve" in pattern_types:
            tags.append("Vulnerability-Research")

        # Behavioral tags
        for flag in behavioral_flags:
            if flag.flag_type == "opsec_aware":
                tags.append("OPSEC-Aware")
            elif flag.flag_type == "code_sharing":
                tags.append("Technical")

        return list(set(tags))  # Remove duplicates


__all__ = [
    "ThreatClassification",
    "BehavioralFlag",
    "ThreatActorProfile",
    "BehavioralAnalyzer",
    "ThreatScorer",
    "ThreatProfiler",
]
