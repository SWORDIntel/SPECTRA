"""
SPECTRA Threat Indicator Detection Engine
==========================================
Detects threat indicators in messages using keywords, patterns, and behavioral analysis.

Features:
- Multi-level keyword detection (critical, moderate, low severity)
- Pattern matching (CVEs, IPs, hashes, crypto addresses, Tor addresses)
- Contextual analysis
- Indicator scoring and confidence calculation
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class ThreatLevel(Enum):
    """Threat indicator severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    INFO = "info"


class IndicatorType(Enum):
    """Types of threat indicators."""
    KEYWORD = "keyword"
    PATTERN = "pattern"
    BEHAVIORAL = "behavioral"
    NETWORK = "network"


@dataclass
class ThreatIndicator:
    """A single threat indicator detected in a message."""
    type: IndicatorType
    value: str
    severity: float  # 0.0 to 5.0
    level: ThreatLevel
    confidence: float = 1.0
    context: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type.value,
            "value": self.value,
            "severity": self.severity,
            "level": self.level.value,
            "confidence": self.confidence,
            "context": self.context,
            "metadata": self.metadata,
        }


# ==============================================================================
# KEYWORD DETECTION
# ==============================================================================

# Critical Keywords (Score Impact: +3 to +5)
CRITICAL_KEYWORDS = {
    # Exploits & Vulnerabilities
    "zero-day", "0day", "zero day", "0-day",
    "exploit kit", "rce", "remote code execution",
    "privilege escalation", "privesc",
    "weaponized exploit", "exploit framework",

    # Malware & Tools
    "ransomware", "backdoor", "trojan", "rootkit",
    "botnet", "c2 server", "c&c server", "command and control",
    "rat", "remote access trojan", "remote administration tool",
    "keylogger", "spyware", "cryptojacker",

    # Nation-State & APT Groups
    "apt28", "fancy bear", "apt29", "cozy bear",
    "lazarus group", "sandworm", "equation group",
    "carbanak", "fin7", "dragonfly", "energetic bear",
    "state-sponsored", "nation-state", "state actor",

    # Infrastructure
    "tor hidden service", ".onion",
    "darknet market", "dark web marketplace",
    "bulletproof hosting", "bulletproof vps",
    "anonymous infrastructure", "covert channel",

    # Operations
    "cyber warfare", "information operations", "psyops",
    "disinformation campaign", "influence operation",
    "targeted attack", "spear phishing", "watering hole",
    "supply chain attack", "island hopping",

    # Data Exfiltration
    "data exfiltration", "data theft", "credential dump",
    "database dump", "leaked database", "data breach",

    # Cryptocurrency (in malicious context)
    "crypto mixer", "tumbler", "monero laundering",
    "ransom payment", "bitcoin ransom",
}

# Moderate Keywords (Score Impact: +1 to +2)
MODERATE_KEYWORDS = {
    # Security Research
    "vulnerability research", "security research",
    "penetration testing", "pentest", "security audit",
    "red team", "blue team", "purple team",
    "capture the flag", "ctf challenge",

    # Technical Topics
    "buffer overflow", "heap spray", "use after free",
    "sql injection", "sqli", "xss", "cross-site scripting",
    "csrf", "cross-site request forgery",
    "ssrf", "server-side request forgery",
    "deserialization", "xml external entity", "xxe",

    # Tools (legitimate use possible)
    "metasploit", "cobalt strike", "empire framework",
    "burp suite", "nmap", "wireshark", "kali linux",
    "ghidra", "ida pro", "binary ninja",
    "volatility", "rekall", "mimikatz",

    # Cryptography
    "encryption", "decryption", "cryptanalysis",
    "cipher", "hash function", "key exchange",

    # Reconnaissance
    "osint", "open source intelligence",
    "reconnaissance", "footprinting", "enumeration",
    "port scanning", "vulnerability scanning",
}

# Low-Severity Keywords (Score Impact: +0.5)
LOW_KEYWORDS = {
    # General Security
    "cybersecurity", "information security", "infosec",
    "bug bounty", "responsible disclosure",
    "security patch", "security update",
    "firewall", "antivirus", "endpoint protection",
    "security awareness", "security training",

    # Compliance
    "gdpr", "hipaa", "pci-dss", "sox compliance",
    "security audit", "compliance check",
}


# ==============================================================================
# PATTERN DETECTION
# ==============================================================================

class PatternDetector:
    """Detects threat patterns using regex."""

    # CVE Pattern
    CVE_PATTERN = re.compile(r'\b(CVE-\d{4}-\d{4,7})\b', re.IGNORECASE)

    # IP Address Pattern
    IP_PATTERN = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')

    # Malware Hash Patterns
    MD5_PATTERN = re.compile(r'\b[a-fA-F0-9]{32}\b')
    SHA1_PATTERN = re.compile(r'\b[a-fA-F0-9]{40}\b')
    SHA256_PATTERN = re.compile(r'\b[a-fA-F0-9]{64}\b')

    # Cryptocurrency Addresses
    BITCOIN_PATTERN = re.compile(r'\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b')
    ETHEREUM_PATTERN = re.compile(r'\b0x[a-fA-F0-9]{40}\b')
    MONERO_PATTERN = re.compile(r'\b4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b')

    # Onion Addresses (Tor)
    ONION_PATTERN = re.compile(r'\b[a-z2-7]{16,56}\.onion\b', re.IGNORECASE)

    # Credentials Pattern
    CREDS_PATTERN = re.compile(
        r'(password|passwd|pwd|login|user|username)\s*[:=]\s*\S+',
        re.IGNORECASE
    )

    # Email Pattern
    EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

    # URL Pattern
    URL_PATTERN = re.compile(r'https?://[^\s]+')

    # Encoded Data (Base64-like)
    BASE64_PATTERN = re.compile(r'\b[A-Za-z0-9+/]{40,}={0,2}\b')

    @classmethod
    def detect_patterns(cls, text: str) -> List[ThreatIndicator]:
        """Detect all threat patterns in text."""
        indicators = []

        # CVE References
        cve_matches = cls.CVE_PATTERN.findall(text)
        for cve in cve_matches:
            indicators.append(ThreatIndicator(
                type=IndicatorType.PATTERN,
                value=cve,
                severity=2.0,
                level=ThreatLevel.MODERATE,
                context=f"CVE reference: {cve}",
                metadata={"pattern_type": "cve"}
            ))

        # IP Addresses
        ip_matches = cls.IP_PATTERN.findall(text)
        for ip in ip_matches:
            # Filter out common private/local IPs
            if not cls._is_private_ip(ip):
                indicators.append(ThreatIndicator(
                    type=IndicatorType.PATTERN,
                    value=ip,
                    severity=1.5,
                    level=ThreatLevel.MODERATE,
                    context=f"IP address: {ip}",
                    metadata={"pattern_type": "ip"}
                ))

        # Malware Hashes
        sha256_matches = cls.SHA256_PATTERN.findall(text)
        for hash_val in sha256_matches:
            indicators.append(ThreatIndicator(
                type=IndicatorType.PATTERN,
                value=hash_val,
                severity=3.0,
                level=ThreatLevel.HIGH,
                context=f"SHA256 hash: {hash_val[:16]}...",
                metadata={"pattern_type": "sha256"}
            ))

        # Cryptocurrency Addresses
        btc_matches = cls.BITCOIN_PATTERN.findall(text)
        for addr in btc_matches:
            # Check if in ransomware context
            context_severity = 4.0 if any(k in text.lower() for k in ["ransom", "payment", "decrypt"]) else 2.0
            indicators.append(ThreatIndicator(
                type=IndicatorType.PATTERN,
                value=addr,
                severity=context_severity,
                level=ThreatLevel.HIGH if context_severity > 3 else ThreatLevel.MODERATE,
                context=f"Bitcoin address: {addr}",
                metadata={"pattern_type": "bitcoin", "currency": "BTC"}
            ))

        # Monero Addresses (often used in ransomware)
        xmr_matches = cls.MONERO_PATTERN.findall(text)
        for addr in xmr_matches:
            indicators.append(ThreatIndicator(
                type=IndicatorType.PATTERN,
                value=addr,
                severity=3.5,
                level=ThreatLevel.HIGH,
                context=f"Monero address: {addr[:16]}...",
                metadata={"pattern_type": "monero", "currency": "XMR"}
            ))

        # Onion Addresses
        onion_matches = cls.ONION_PATTERN.findall(text)
        for onion in onion_matches:
            # Higher severity if associated with market/shop keywords
            context_severity = 4.0 if any(k in text.lower() for k in ["market", "shop", "vendor"]) else 2.5
            indicators.append(ThreatIndicator(
                type=IndicatorType.PATTERN,
                value=onion,
                severity=context_severity,
                level=ThreatLevel.HIGH if context_severity > 3 else ThreatLevel.MODERATE,
                context=f"Tor hidden service: {onion}",
                metadata={"pattern_type": "onion"}
            ))

        # Credentials
        creds_matches = cls.CREDS_PATTERN.findall(text)
        if creds_matches:
            indicators.append(ThreatIndicator(
                type=IndicatorType.PATTERN,
                value="<redacted_credentials>",
                severity=3.0,
                level=ThreatLevel.HIGH,
                context="Potential leaked credentials",
                metadata={"pattern_type": "credentials", "count": len(creds_matches)}
            ))

        return indicators

    @staticmethod
    def _is_private_ip(ip: str) -> bool:
        """Check if IP is private/local."""
        parts = ip.split('.')
        if len(parts) != 4:
            return False

        try:
            octets = [int(p) for p in parts]
        except ValueError:
            return True

        # Check private ranges
        if octets[0] == 10:
            return True
        if octets[0] == 172 and 16 <= octets[1] <= 31:
            return True
        if octets[0] == 192 and octets[1] == 168:
            return True
        if octets[0] == 127:  # Localhost
            return True

        return False


# ==============================================================================
# KEYWORD DETECTOR
# ==============================================================================

class KeywordDetector:
    """Detects threat keywords in text."""

    def __init__(self):
        """Initialize keyword detector with compiled keyword sets."""
        # Convert to lowercase for case-insensitive matching
        self.critical_keywords = {k.lower() for k in CRITICAL_KEYWORDS}
        self.moderate_keywords = {k.lower() for k in MODERATE_KEYWORDS}
        self.low_keywords = {k.lower() for k in LOW_KEYWORDS}

    def detect_keywords(self, text: str) -> List[ThreatIndicator]:
        """Detect all threat keywords in text."""
        text_lower = text.lower()
        indicators = []

        # Critical keywords
        for keyword in self.critical_keywords:
            if keyword in text_lower:
                # Get context (50 chars before and after)
                idx = text_lower.find(keyword)
                context_start = max(0, idx - 50)
                context_end = min(len(text), idx + len(keyword) + 50)
                context = text[context_start:context_end]

                indicators.append(ThreatIndicator(
                    type=IndicatorType.KEYWORD,
                    value=keyword,
                    severity=4.0,
                    level=ThreatLevel.CRITICAL,
                    context=context,
                    metadata={"keyword_level": "critical"}
                ))

        # Moderate keywords
        for keyword in self.moderate_keywords:
            if keyword in text_lower:
                idx = text_lower.find(keyword)
                context_start = max(0, idx - 50)
                context_end = min(len(text), idx + len(keyword) + 50)
                context = text[context_start:context_end]

                indicators.append(ThreatIndicator(
                    type=IndicatorType.KEYWORD,
                    value=keyword,
                    severity=2.0,
                    level=ThreatLevel.MODERATE,
                    context=context,
                    metadata={"keyword_level": "moderate"}
                ))

        # Low keywords
        for keyword in self.low_keywords:
            if keyword in text_lower:
                idx = text_lower.find(keyword)
                context_start = max(0, idx - 50)
                context_end = min(len(text), idx + len(keyword) + 50)
                context = text[context_start:context_end]

                indicators.append(ThreatIndicator(
                    type=IndicatorType.KEYWORD,
                    value=keyword,
                    severity=0.5,
                    level=ThreatLevel.LOW,
                    context=context,
                    metadata={"keyword_level": "low"}
                ))

        return indicators


# ==============================================================================
# THREAT INDICATOR DETECTOR (Main Class)
# ==============================================================================

class ThreatIndicatorDetector:
    """
    Main threat indicator detection engine.
    Combines keyword and pattern detection.
    """

    def __init__(self):
        """Initialize detector with all detection modules."""
        self.keyword_detector = KeywordDetector()
        self.pattern_detector = PatternDetector()

    def detect_indicators(
        self,
        text: str,
        min_severity: float = 0.0,
        deduplicate: bool = True,
    ) -> List[ThreatIndicator]:
        """
        Detect all threat indicators in text.

        Args:
            text: Text to analyze
            min_severity: Minimum severity threshold
            deduplicate: Remove duplicate indicators

        Returns:
            List of ThreatIndicator objects
        """
        if not text or len(text.strip()) == 0:
            return []

        indicators = []

        # Keyword detection
        keyword_indicators = self.keyword_detector.detect_keywords(text)
        indicators.extend(keyword_indicators)

        # Pattern detection
        pattern_indicators = self.pattern_detector.detect_patterns(text)
        indicators.extend(pattern_indicators)

        # Filter by severity
        if min_severity > 0:
            indicators = [i for i in indicators if i.severity >= min_severity]

        # Deduplicate
        if deduplicate:
            indicators = self._deduplicate_indicators(indicators)

        # Sort by severity (highest first)
        indicators.sort(key=lambda x: x.severity, reverse=True)

        return indicators

    @staticmethod
    def _deduplicate_indicators(indicators: List[ThreatIndicator]) -> List[ThreatIndicator]:
        """Remove duplicate indicators, keeping highest severity."""
        seen = {}

        for indicator in indicators:
            key = (indicator.type.value, indicator.value)

            if key not in seen or indicator.severity > seen[key].severity:
                seen[key] = indicator

        return list(seen.values())

    def get_stats(self, indicators: List[ThreatIndicator]) -> Dict[str, Any]:
        """Get statistics about detected indicators."""
        if not indicators:
            return {
                "total_indicators": 0,
                "by_type": {},
                "by_level": {},
                "total_severity": 0.0,
                "avg_severity": 0.0,
            }

        by_type = {}
        by_level = {}

        for indicator in indicators:
            by_type[indicator.type.value] = by_type.get(indicator.type.value, 0) + 1
            by_level[indicator.level.value] = by_level.get(indicator.level.value, 0) + 1

        total_severity = sum(i.severity for i in indicators)

        return {
            "total_indicators": len(indicators),
            "by_type": by_type,
            "by_level": by_level,
            "total_severity": total_severity,
            "avg_severity": total_severity / len(indicators) if indicators else 0.0,
        }


__all__ = [
    "ThreatLevel",
    "IndicatorType",
    "ThreatIndicator",
    "KeywordDetector",
    "PatternDetector",
    "ThreatIndicatorDetector",
]
