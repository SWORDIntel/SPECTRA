"""
SPECTRA Behavioral Change-Point Detection & Campaign Segmentation Engine
========================================================================
Detects behavioral regime changes in threat actor activity histories and segments
multi-actor operations into coherent operational campaign episodes.

Tracks behavioral shifts across:
- Stylometry (vocabulary richness, sentence length, punctuation patterns)
- Message rate (messages per day)
- Active hours (circadian distribution shifts)
- Response latency (inter-message interval dynamics)
- Topic distribution (keyword-based category distribution)
- Language & script shifts

Exports:
- ChangePoint: Dataclass representing a detected regime change.
- ChangePointDetector: Engine for sliding-window change detection and description.
- detect_campaigns: Operational episode clustering across multiple actors.
"""
from __future__ import annotations

import collections
import dataclasses
import datetime
import hashlib
import logging
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from tgarchive.intelligence.schema import (
    AnalysisEvidence,
    Campaign,
    EvidenceDirection,
    EvidenceSource,
    canonical_id,
)

logger = logging.getLogger(__name__)

# Optional: langdetect for language identification
try:
    from langdetect import detect as lang_detect
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False


# ==============================================================================
# CONSTANTS & REGEX PATTERNS
# ==============================================================================

# Cryptocurrency wallet regex patterns
BITCOIN_LEGACY_P2SH_REGEX = re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")
BITCOIN_BECH32_REGEX = re.compile(r"\bbc1[a-z0-9]{38,59}\b")
ETHEREUM_REGEX = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
MONERO_REGEX = re.compile(r"\b4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b")
TON_REGEX = re.compile(r"\b(?:EQ|UQ)[a-zA-Z0-9_-]{46}\b")
TRON_REGEX = re.compile(r"\bT[a-km-zA-HJ-NP-Z1-9]{33}\b")

# Domain regex pattern
DOMAIN_REGEX = re.compile(
    r"\b(?:https?://)?(?:www\.)?([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+([a-zA-Z]{2,63})\b",
    re.IGNORECASE,
)

# File extensions to ignore when extracting domains
EXCLUDED_EXTENSIONS: Set[str] = {
    "py", "pyc", "json", "txt", "csv", "db", "sqlite", "log", "md", "html", "htm",
    "js", "ts", "css", "png", "jpg", "jpeg", "gif", "svg", "webp", "zip", "tar",
    "gz", "bz2", "xz", "7z", "rar", "sh", "bat", "exe", "dll", "so", "bin", "iso",
    "apk", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "c", "cpp", "h",
    "hpp", "rs", "go", "java", "xml", "yml", "yaml", "ini", "cfg", "conf",
}

# Semantic topic keyword clusters
TOPIC_CATEGORIES: Dict[str, Set[str]] = {
    "cyber_technical": {
        "exploit", "vuln", "0day", "zeroday", "payload", "shell", "root", "bypass",
        "botnet", "malware", "reverse", "rat", "injection", "ddos", "c2", "proxy",
        "vpn", "tor", "backdoor", "nmap", "meterpreter", "cobalt", "poc", "sqli",
        "rce", "privesc", "metasploit", "wireshark", "burp", "beacon", "stager",
    },
    "financial_crypto": {
        "btc", "eth", "usdt", "wallet", "crypto", "payment", "xmr", "address",
        "transfer", "monero", "bitcoin", "cash", "bank", "dollar", "binance", "pay",
        "invoice", "fee", "transaction", "usdc", "trx", "ton", "deposit", "withdraw",
    },
    "operational_logistics": {
        "admin", "target", "server", "channel", "drop", "setup", "config", "test",
        "update", "check", "backup", "online", "offline", "link", "schedule",
        "account", "session", "host", "domain", "ip", "vps", "tunnel", "route",
    },
    "marketplace_trading": {
        "buy", "sell", "price", "market", "shop", "deal", "account", "dump",
        "leak", "database", "fullz", "logs", "combo", "order", "escrow", "vendor",
        "bulk", "discount", "cost", "seller", "buyer", "stock", "guarantee",
    },
    "social_communication": {
        "hello", "hi", "hey", "thanks", "please", "bro", "yes", "no", "ok", "bye",
        "lol", "haha", "friend", "group", "chat", "good", "morning", "night", "welcome",
        "bro", "man", "mate", "dude", "agree", "sure",
    },
}


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _now_utc() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _ensure_utc(dt: Optional[datetime]) -> datetime:
    """Ensure datetime is UTC-aware."""
    if dt is None:
        return _now_utc()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_datetime(val: Any) -> Optional[datetime]:
    """Parse various timestamp representations into a timezone-aware UTC datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return _ensure_utc(val)
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            return None
        try:
            iso_str = cleaned.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_str)
            return _ensure_utc(dt)
        except Exception:
            pass
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%d.%m.%Y %H:%M:%S",
        ):
            try:
                return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _get_msg_date(msg: Dict[str, Any]) -> Optional[datetime]:
    """Extract and parse timestamp from a message dict."""
    if not isinstance(msg, dict):
        return None
    for key in ("date", "timestamp", "created_at", "datetime", "time"):
        if key in msg and msg[key] is not None:
            dt = _parse_datetime(msg[key])
            if dt is not None:
                return dt
    return None


def _get_msg_text(msg: Dict[str, Any]) -> str:
    """Extract text content from a message dict."""
    if not isinstance(msg, dict):
        return str(msg) if msg is not None else ""
    for key in ("text", "content", "message", "body", "raw_text"):
        if key in msg and msg[key] is not None:
            return str(msg[key])
    return ""


def _get_msg_id(msg: Dict[str, Any], default: int = 0) -> int:
    """Extract integer message ID from a message dict."""
    if not isinstance(msg, dict):
        return default
    for key in ("id", "message_id", "msg_id", "mid"):
        if key in msg and msg[key] is not None:
            try:
                return int(msg[key])
            except (ValueError, TypeError):
                pass
    return default


def _get_msg_user_id(msg: Dict[str, Any]) -> Optional[int]:
    """Extract sender / user ID from a message dict."""
    if not isinstance(msg, dict):
        return None
    for key in ("user_id", "from_id", "sender_id", "actor_id", "author_id"):
        if key in msg and msg[key] is not None:
            try:
                return int(msg[key])
            except (ValueError, TypeError):
                pass
    return None


def _get_msg_channel_id(msg: Dict[str, Any]) -> Optional[str]:
    """Extract channel / chat ID from a message dict."""
    if not isinstance(msg, dict):
        return None
    for key in ("channel_id", "chat_id", "peer_id", "group_id"):
        if key in msg and msg[key] is not None:
            return str(msg[key])
    return None


def _extract_words(text: str) -> List[str]:
    """Extract alphanumeric word tokens in lowercase."""
    return re.findall(r"\b\w+\b", text.lower())


def _split_sentences(text: str) -> List[str]:
    """Split text into sentence chunks."""
    sentences = re.split(r"[.!?]+", text)
    return [s.strip() for s in sentences if s.strip()]


def _is_emoji(char: str) -> bool:
    """Determine if a character is within common emoji Unicode ranges."""
    cp = ord(char)
    return (
        (0x1F600 <= cp <= 0x1F64F)
        or (0x1F300 <= cp <= 0x1F5FF)
        or (0x1F680 <= cp <= 0x1F6FF)
        or (0x1F700 <= cp <= 0x1F77F)
        or (0x1F780 <= cp <= 0x1F7FF)
        or (0x1F800 <= cp <= 0x1F8FF)
        or (0x1F900 <= cp <= 0x1F9FF)
        or (0x1FA00 <= cp <= 0x1FA6F)
        or (0x1FA70 <= cp <= 0x1FAFF)
        or (0x2600 <= cp <= 0x26FF)
        or (0x2700 <= cp <= 0x27BF)
        or (0x1F1E6 <= cp <= 0x1F1FF)
    )


def extract_wallets(text: str) -> List[str]:
    """Extract cryptocurrency wallet addresses from text."""
    if not text:
        return []
    wallets: Set[str] = set()
    for pattern in (
        BITCOIN_LEGACY_P2SH_REGEX,
        BITCOIN_BECH32_REGEX,
        ETHEREUM_REGEX,
        MONERO_REGEX,
        TON_REGEX,
        TRON_REGEX,
    ):
        for match in pattern.finditer(text):
            wallets.add(match.group(0))
    return sorted(wallets)


def extract_domains(text: str) -> List[str]:
    """Extract domain names from text, ignoring file extensions and numeric IP segments."""
    if not text:
        return []
    domains: Set[str] = set()
    for match in DOMAIN_REGEX.finditer(text):
        full_match = match.group(0).lower()
        if "://" in full_match:
            full_match = full_match.split("://", 1)[1]
        if "/" in full_match:
            full_match = full_match.split("/", 1)[0]
        if ":" in full_match:
            full_match = full_match.split(":", 1)[0]
        full_match = full_match.strip(". ")
        parts = full_match.split(".")
        if len(parts) >= 2:
            tld = parts[-1]
            if tld not in EXCLUDED_EXTENSIONS and not tld.isdigit() and len(tld) >= 2:
                if all(len(p) > 0 for p in parts):
                    domains.add(full_match)
    return sorted(domains)


def _cosine_distance(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine distance (1 - cosine_similarity) between two vectors."""
    if len(vec1) != len(vec2) or not vec1 or not vec2:
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 < 1e-9 or norm2 < 1e-9:
        if norm1 < 1e-9 and norm2 < 1e-9:
            return 0.0
        return 1.0
    sim = dot / (norm1 * norm2)
    sim = max(-1.0, min(1.0, sim))
    return max(0.0, 1.0 - sim)


# ==============================================================================
# CHANGEPOINT DATACLASS
# ==============================================================================

@dataclass
class ChangePoint:
    """Represents a detected behavioral change point / regime shift."""

    timestamp: datetime
    probability: float  # 0-1, probability of genuine regime change
    features_changed: Dict[str, float]  # feature_name -> sigma_change
    before_window: List[int]  # message IDs before change
    after_window: List[int]  # message IDs after change
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert ChangePoint to dictionary representation."""
        ts = self.timestamp
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_str = ts.isoformat()
        else:
            ts_str = str(ts)

        return {
            "timestamp": ts_str,
            "probability": round(float(self.probability), 4),
            "features_changed": {k: round(float(v), 3) for k, v in self.features_changed.items()},
            "before_window": [int(x) for x in self.before_window],
            "after_window": [int(x) for x in self.after_window],
            "confidence": round(float(self.confidence), 4),
        }

    def to_evidence(self, user_id: int) -> AnalysisEvidence:
        """Convert to AnalysisEvidence with proper provenance."""
        obs_at = _ensure_utc(self.timestamp)
        sources: List[EvidenceSource] = []

        all_ids = self.before_window + self.after_window
        for mid in all_ids:
            try:
                row_id = int(mid)
            except (ValueError, TypeError):
                row_id = 0
            sources.append(
                EvidenceSource(
                    source_type="message",
                    source_id=canonical_id("telegram", "msg", mid),
                    source_table="messages",
                    source_row_id=row_id,
                    retrieved_at=obs_at,
                    raw_snapshot=None,
                )
            )

        if not sources:
            try:
                user_row_id = int(user_id)
            except (ValueError, TypeError):
                user_row_id = 0
            sources.append(
                EvidenceSource(
                    source_type="user",
                    source_id=canonical_id("telegram", "user", user_id),
                    source_table="users",
                    source_row_id=user_row_id,
                    retrieved_at=obs_at,
                    raw_snapshot=None,
                )
            )

        prob = min(1.0, max(0.0, float(self.probability)))
        conf = min(1.0, max(0.0, float(self.confidence)))

        direction = (
            EvidenceDirection.SUPPORTS
            if prob >= 0.5
            else EvidenceDirection.CONTRADICTS
        )

        metadata: Dict[str, Any] = {
            "features_changed": self.features_changed,
            "before_message_count": len(self.before_window),
            "after_message_count": len(self.after_window),
            "probability": prob,
            "user_id": user_id,
        }

        return AnalysisEvidence(
            evidence_id="",
            evidence_type="behavioral_change_point",
            subject=canonical_id("telegram", "user", user_id),
            object=None,
            score=prob,
            confidence=conf,
            direction=direction,
            model="spectra-changepoint-detector",
            model_version="1.0.0",
            feature_schema_version="1.0.0",
            sources=sources,
            observed_at=obs_at,
            generated_at=_now_utc(),
            metadata=metadata,
        )


# ==============================================================================
# CHANGEPOINT DETECTOR
# ==============================================================================

class ChangePointDetector:
    """Detects behavioral regime changes in actor activity."""

    def __init__(self, threshold_std: float = 2.0, min_window_size: int = 5):
        self.threshold_std = threshold_std
        self.min_window_size = min_window_size

    def _extract_window_features(self, messages: List[Dict[str, Any]]) -> List[float]:
        """
        Compute continuous numerical feature vector for a window of messages.

        Vector components:
        - Stylometry (6 dims): vocab_richness, avg_sentence_len, punct_density,
                               avg_word_len, uppercase_ratio, emoji_density
        - Message rate (1 dim): log1p(messages_per_day)
        - Active hours (24 dims): normalized 24-hour histogram
        - Latency (2 dims): log1p(median_latency_hrs), log1p(mean_latency_hrs)
        - Topic distribution (5 dims): topic keyword densities
        - Script / Language (5 dims): latin, cyrillic, arabic, cjk, digit ratios
        """
        if not messages:
            return [0.0] * 43

        texts = [_get_msg_text(m) for m in messages]
        dates = [_get_msg_date(m) for m in messages]
        valid_dates = [d for d in dates if d is not None]

        full_corpus = " ".join(texts)
        words = _extract_words(full_corpus)
        total_words = len(words)
        total_chars = len(full_corpus)

        # 1. Stylometry
        vocab_richness = len(set(words)) / max(1, total_words)

        sentences = _split_sentences(full_corpus)
        if sentences:
            sentence_lengths = [len(_extract_words(s)) for s in sentences]
            avg_sentence_len = statistics.mean(sentence_lengths) / 20.0
        else:
            avg_sentence_len = 0.0

        punct_count = len(re.findall(r"[!?.,;:]", full_corpus))
        punct_density = punct_count / max(1, total_chars)

        avg_word_len = (statistics.mean(len(w) for w in words) / 10.0) if words else 0.0

        uppercase_count = sum(1 for c in full_corpus if c.isupper())
        uppercase_ratio = uppercase_count / max(1, total_chars)

        emoji_count = sum(1 for c in full_corpus if _is_emoji(c))
        emoji_density = emoji_count / max(1, total_chars)

        stylometry_vector = [
            vocab_richness,
            avg_sentence_len,
            punct_density,
            avg_word_len,
            uppercase_ratio,
            emoji_density,
        ]

        # 2. Message rate (messages per day)
        if len(valid_dates) >= 2:
            span_days = max(0.04, (max(valid_dates) - min(valid_dates)).total_seconds() / 86400.0)
            msg_rate = len(messages) / span_days
        else:
            msg_rate = float(len(messages))
        msg_rate_feat = math.log1p(msg_rate) / 5.0

        # 3. Active hours (24-dim distribution)
        hour_counts = [0.0] * 24
        for d in valid_dates:
            hour_counts[d.hour] += 1.0
        total_hour_events = max(1.0, float(len(valid_dates)))
        hour_distribution = [c / total_hour_events for c in hour_counts]

        # 4. Latency dynamics
        intervals: List[float] = []
        if len(valid_dates) >= 2:
            sorted_d = sorted(valid_dates)
            intervals = [
                (sorted_d[i + 1] - sorted_d[i]).total_seconds()
                for i in range(len(sorted_d) - 1)
            ]

        if intervals:
            median_latency_hrs = statistics.median(intervals) / 3600.0
            mean_latency_hrs = statistics.mean(intervals) / 3600.0
            median_latency_feat = math.log1p(median_latency_hrs) / 5.0
            mean_latency_feat = math.log1p(mean_latency_hrs) / 5.0
        else:
            median_latency_feat = 0.0
            mean_latency_feat = 0.0
        latency_vector = [median_latency_feat, mean_latency_feat]

        # 5. Topic distribution
        topic_vector: List[float] = []
        words_set_counter = collections.Counter(words)
        for cat_name, kw_set in TOPIC_CATEGORIES.items():
            cat_count = sum(words_set_counter[w] for w in kw_set if w in words_set_counter)
            cat_ratio = cat_count / max(1, total_words)
            topic_vector.append(cat_ratio * 10.0)  # scale for weighting

        # 6. Language scripts
        latin_count = len(re.findall(r"[a-zA-Z]", full_corpus))
        cyrillic_count = len(re.findall(r"[\u0400-\u04FF]", full_corpus))
        arabic_count = len(re.findall(r"[\u0600-\u06FF]", full_corpus))
        cjk_count = len(re.findall(r"[\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]", full_corpus))
        digit_count = len(re.findall(r"[0-9]", full_corpus))

        denom = max(1, total_chars)
        script_vector = [
            latin_count / denom,
            cyrillic_count / denom,
            arabic_count / denom,
            cjk_count / denom,
            digit_count / denom,
        ]

        return (
            stylometry_vector
            + [msg_rate_feat]
            + hour_distribution
            + latency_vector
            + topic_vector
            + script_vector
        )

    def detect_change_points(
        self, messages: List[Dict[str, Any]], window_size: int = 50
    ) -> List[ChangePoint]:
        """
        Detect change points in an actor's message history.

        Tracks changes in:
        - stylometry (vocabulary richness, sentence length, punctuation)
        - message rate (messages per day)
        - active hours (hour distribution shift)
        - response latency
        - topic distribution (simple keyword-based)
        - language detection

        Uses a sliding window approach:
        1. Split messages into windows of window_size messages
        2. Compute feature vector for each window
        3. Compare adjacent windows using cosine distance
        4. Flag windows where distance > threshold (default 2 standard deviations)

        Returns list of ChangePoint objects sorted by timestamp.
        """
        if not messages or len(messages) < self.min_window_size * 2:
            return []

        # Filter valid messages and sort chronologically
        valid_msgs = []
        for m in messages:
            if isinstance(m, dict) and _get_msg_date(m) is not None:
                valid_msgs.append(m)

        if len(valid_msgs) < self.min_window_size * 2:
            return []

        valid_msgs.sort(key=lambda m: _get_msg_date(m))  # type: ignore

        eff_window_size = max(self.min_window_size, min(window_size, len(valid_msgs) // 2))
        step_size = max(1, eff_window_size // 2)

        # Build sliding windows
        windows: List[List[Dict[str, Any]]] = []
        i = 0
        while i + eff_window_size <= len(valid_msgs):
            windows.append(valid_msgs[i : i + eff_window_size])
            i += step_size

        # Handle remaining messages if at least min_window_size
        if i < len(valid_msgs) and (len(valid_msgs) - i) >= self.min_window_size:
            windows.append(valid_msgs[i:])

        if len(windows) < 2:
            return []

        # Compute feature vector for each window
        vectors = [self._extract_window_features(w) for w in windows]

        # Compare adjacent windows using cosine distance
        distances: List[float] = []
        for j in range(len(vectors) - 1):
            dist = _cosine_distance(vectors[j], vectors[j + 1])
            distances.append(dist)

        if not distances:
            return []

        # Statistical threshold calculation
        mean_dist = statistics.mean(distances)
        if len(distances) >= 2:
            std_dist = statistics.stdev(distances)
        else:
            std_dist = 0.0

        if std_dist < 1e-4:
            threshold = max(mean_dist + 0.15, 0.20)
        else:
            threshold = mean_dist + self.threshold_std * std_dist

        change_points: List[ChangePoint] = []

        for idx, dist in enumerate(distances):
            if dist >= threshold:
                before_w = windows[idx]
                after_w = windows[idx + 1]

                # Transition timestamp
                after_start_dt = _get_msg_date(after_w[0])
                if after_start_dt is None:
                    after_start_dt = _ensure_utc(_get_msg_date(before_w[-1]))
                else:
                    after_start_dt = _ensure_utc(after_start_dt)

                # Probability calculation via calibrated sigmoid
                if std_dist > 1e-4:
                    z_score = (dist - mean_dist) / std_dist
                else:
                    z_score = (dist / max(0.1, mean_dist)) * 2.0

                prob = 1.0 / (1.0 + math.exp(-1.5 * (z_score - 1.5)))
                prob = min(1.0, max(0.0, prob))

                # Confidence based on sample volume and signal strength
                sample_ratio = min(
                    1.0, (len(before_w) + len(after_w)) / (2.0 * float(eff_window_size))
                )
                conf = min(1.0, max(0.1, sample_ratio * 0.7 + min(1.0, dist) * 0.3))

                # Describe feature differences
                features_changed = self.describe_change(before_w, after_w)

                before_ids = [_get_msg_id(m) for m in before_w]
                after_ids = [_get_msg_id(m) for m in after_w]

                change_points.append(
                    ChangePoint(
                        timestamp=after_start_dt,
                        probability=prob,
                        features_changed=features_changed,
                        before_window=before_ids,
                        after_window=after_ids,
                        confidence=conf,
                    )
                )

        change_points.sort(key=lambda cp: cp.timestamp)
        return change_points

    def describe_change(
        self, before_messages: List[Dict[str, Any]], after_messages: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """
        Describe what changed between two periods.
        Returns dict of feature_name -> sigma_change (e.g., +1.8sigma, -71%).
        Tracks: vocabulary_richness, sentence_length, punctuation_pattern,
        response_latency, activity_period, message_rate, semantic_interests.
        """
        default_result: Dict[str, float] = {
            "vocabulary_richness": 0.0,
            "sentence_length": 0.0,
            "punctuation_pattern": 0.0,
            "response_latency": 0.0,
            "activity_period": 0.0,
            "message_rate": 0.0,
            "semantic_interests": 0.0,
        }

        if not before_messages or not after_messages:
            return default_result

        def compute_sigma(
            vals_before: List[float], vals_after: List[float], default_std: float = 1.0
        ) -> float:
            if not vals_before and not vals_after:
                return 0.0
            mean_b = statistics.mean(vals_before) if vals_before else 0.0
            mean_a = statistics.mean(vals_after) if vals_after else 0.0
            combined = vals_before + vals_after
            if len(combined) >= 2:
                std = statistics.stdev(combined)
                if std < 1e-6:
                    std = default_std
            else:
                std = default_std
            return round((mean_a - mean_b) / std, 3)

        # 1. Vocabulary richness per message
        ttr_before = []
        for m in before_messages:
            w = _extract_words(_get_msg_text(m))
            if w:
                ttr_before.append(len(set(w)) / len(w))

        ttr_after = []
        for m in after_messages:
            w = _extract_words(_get_msg_text(m))
            if w:
                ttr_after.append(len(set(w)) / len(w))

        vocab_change = compute_sigma(ttr_before, ttr_after, default_std=0.2)

        # 2. Sentence length per message
        sl_before = []
        for m in before_messages:
            sents = _split_sentences(_get_msg_text(m))
            for s in sents:
                sl_before.append(float(len(_extract_words(s))))

        sl_after = []
        for m in after_messages:
            sents = _split_sentences(_get_msg_text(m))
            for s in sents:
                sl_after.append(float(len(_extract_words(s))))

        sent_change = compute_sigma(sl_before, sl_after, default_std=3.0)

        # 3. Punctuation pattern density per message
        punct_before = []
        for m in before_messages:
            t = _get_msg_text(m)
            if t:
                punct_before.append(len(re.findall(r"[!?.,;:]", t)) / len(t))

        punct_after = []
        for m in after_messages:
            t = _get_msg_text(m)
            if t:
                punct_after.append(len(re.findall(r"[!?.,;:]", t)) / len(t))

        punct_change = compute_sigma(punct_before, punct_after, default_std=0.05)

        # 4. Response latency intervals
        dates_b = sorted([d for d in (_get_msg_date(m) for m in before_messages) if d is not None])
        lat_before = [
            (dates_b[i + 1] - dates_b[i]).total_seconds() / 60.0
            for i in range(len(dates_b) - 1)
        ]

        dates_a = sorted([d for d in (_get_msg_date(m) for m in after_messages) if d is not None])
        lat_after = [
            (dates_a[i + 1] - dates_a[i]).total_seconds() / 60.0
            for i in range(len(dates_a) - 1)
        ]

        lat_change = compute_sigma(lat_before, lat_after, default_std=60.0)

        # 5. Activity period (Hour of day)
        hours_before = [float(d.hour) for d in dates_b]
        hours_after = [float(d.hour) for d in dates_a]
        activity_change = compute_sigma(hours_before, hours_after, default_std=4.0)

        # 6. Message rate (Daily counts)
        daily_counts_b = collections.Counter(d.date() for d in dates_b)
        daily_counts_a = collections.Counter(d.date() for d in dates_a)
        rate_b = [float(c) for c in daily_counts_b.values()] if daily_counts_b else [float(len(before_messages))]
        rate_a = [float(c) for c in daily_counts_a.values()] if daily_counts_a else [float(len(after_messages))]
        rate_change = compute_sigma(rate_b, rate_a, default_std=5.0)

        # 7. Semantic interests topic shift
        words_b = collections.Counter(_extract_words(" ".join(_get_msg_text(m) for m in before_messages)))
        words_a = collections.Counter(_extract_words(" ".join(_get_msg_text(m) for m in after_messages)))
        tot_b = max(1, sum(words_b.values()))
        tot_a = max(1, sum(words_a.values()))

        cat_shifts = []
        for cat_name, kw_set in TOPIC_CATEGORIES.items():
            cnt_b = sum(words_b[w] for w in kw_set) / tot_b
            cnt_a = sum(words_a[w] for w in kw_set) / tot_a
            cat_shifts.append(cnt_a - cnt_b)

        # Topic distribution shift magnitude
        shift_magnitude = math.sqrt(sum(s * s for s in cat_shifts))
        semantic_change = round(shift_magnitude * 10.0, 3)

        return {
            "vocabulary_richness": vocab_change,
            "sentence_length": sent_change,
            "punctuation_pattern": punct_change,
            "response_latency": lat_change,
            "activity_period": activity_change,
            "message_rate": rate_change,
            "semantic_interests": semantic_change,
        }


# ==============================================================================
# CAMPAIGN SEGMENTATION & CLUSTERING
# ==============================================================================

class _UnionFind:
    """Disjoint Set Union for grouping connected segments."""

    def __init__(self, size: int):
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        rx = self.find(x)
        ry = self.find(y)
        if rx != ry:
            if self.rank[rx] < self.rank[ry]:
                self.parent[rx] = ry
            elif self.rank[rx] > self.rank[ry]:
                self.parent[ry] = rx
            else:
                self.parent[ry] = rx
                self.rank[rx] += 1


@dataclass
class _SegmentMetadata:
    """Internal representation of a candidate temporal segment."""

    segment_id: int
    messages: List[Dict[str, Any]]
    actors: Set[str]
    channels: Set[str]
    wallets: Set[str]
    domains: Set[str]
    message_ids: List[str]
    start: datetime
    end: datetime


def detect_campaigns(
    messages: List[Dict[str, Any]],
    actors: Dict[int, List[Dict[str, Any]]],
    min_actors: int = 2,
    min_messages: int = 10,
    gap_threshold_hours: int = 48,
) -> List[Campaign]:
    """
    Segment messages into coherent operational episodes (campaigns).

    Algorithm:
    1. Sort all messages chronologically across all actors
    2. Split at gaps > gap_threshold_hours
    3. For each segment, check if it has >= min_actors and >= min_messages
    4. Group segments that share actors/wallets/domains
    5. Return Campaign objects with actors, channels, message_ids, start, end, confidence

    Confidence is based on:
    - Actor overlap between segments
    - Infrastructure overlap (shared wallets/domains)
    - Temporal proximity
    """
    # 1. Consolidate and sort all messages across all actors
    pool: List[Dict[str, Any]] = []
    seen_keys: Set[Tuple[Optional[int], int, Optional[datetime]]] = set()

    def add_msg(m: Dict[str, Any], explicit_user_id: Optional[int] = None) -> None:
        if not isinstance(m, dict):
            return
        dt = _get_msg_date(m)
        if dt is None:
            return
        dt = _ensure_utc(dt)
        mid = _get_msg_id(m)
        uid = explicit_user_id if explicit_user_id is not None else _get_msg_user_id(m)
        key = (uid, mid, dt)
        if key in seen_keys:
            return
        seen_keys.add(key)
        item = dict(m)
        item["_parsed_date"] = dt
        item["_parsed_user_id"] = uid
        item["_parsed_msg_id"] = mid
        item["_parsed_channel_id"] = _get_msg_channel_id(m)
        item["_parsed_text"] = _get_msg_text(m)
        pool.append(item)

    if messages:
        for m in messages:
            add_msg(m)

    if actors:
        for uid, user_msgs in actors.items():
            if isinstance(user_msgs, list):
                for m in user_msgs:
                    add_msg(m, explicit_user_id=uid)

    if not pool:
        return []

    pool.sort(key=lambda m: m["_parsed_date"])

    # 2. Split at gaps > gap_threshold_hours
    gap_seconds = float(gap_threshold_hours * 3600)
    raw_segments: List[List[Dict[str, Any]]] = []
    current_segment: List[Dict[str, Any]] = []

    for msg in pool:
        if not current_segment:
            current_segment.append(msg)
        else:
            prev_dt = current_segment[-1]["_parsed_date"]
            curr_dt = msg["_parsed_date"]
            if (curr_dt - prev_dt).total_seconds() > gap_seconds:
                raw_segments.append(current_segment)
                current_segment = [msg]
            else:
                current_segment.append(msg)

    if current_segment:
        raw_segments.append(current_segment)

    # 3. Filter segments with >= min_actors and >= min_messages
    qualified_segments: List[_SegmentMetadata] = []
    seg_counter = 0

    for raw_seg in raw_segments:
        if len(raw_seg) < min_messages:
            continue

        seg_actors: Set[str] = set()
        seg_channels: Set[str] = set()
        seg_wallets: Set[str] = set()
        seg_domains: Set[str] = set()
        seg_msg_ids: List[str] = []

        for m in raw_seg:
            uid = m.get("_parsed_user_id")
            if uid is not None:
                seg_actors.add(canonical_id("telegram", "user", uid))
            cid = m.get("_parsed_channel_id")
            if cid:
                seg_channels.add(str(cid))
            mid = m.get("_parsed_msg_id")
            if mid:
                seg_msg_ids.append(str(mid))

            txt = m.get("_parsed_text", "")
            if txt:
                for w in extract_wallets(txt):
                    seg_wallets.add(w)
                for d in extract_domains(txt):
                    seg_domains.add(d)

        if len(seg_actors) >= min_actors:
            qualified_segments.append(
                _SegmentMetadata(
                    segment_id=seg_counter,
                    messages=raw_seg,
                    actors=seg_actors,
                    channels=seg_channels,
                    wallets=seg_wallets,
                    domains=seg_domains,
                    message_ids=seg_msg_ids,
                    start=raw_seg[0]["_parsed_date"],
                    end=raw_seg[-1]["_parsed_date"],
                )
            )
            seg_counter += 1

    if not qualified_segments:
        return []

    # 4. Group segments that share actors, wallets, or domains using Union-Find
    num_segs = len(qualified_segments)
    uf = _UnionFind(num_segs)

    for i in range(num_segs):
        for j in range(i + 1, num_segs):
            si = qualified_segments[i]
            sj = qualified_segments[j]

            actor_shared = bool(si.actors & sj.actors)
            wallet_shared = bool(si.wallets & sj.wallets)
            domain_shared = bool(si.domains & sj.domains)

            if actor_shared or wallet_shared or domain_shared:
                uf.union(i, j)

    clusters: Dict[int, List[_SegmentMetadata]] = collections.defaultdict(list)
    for i in range(num_segs):
        root = uf.find(i)
        clusters[root].append(qualified_segments[i])

    # 5. Build Campaign objects from grouped segment clusters
    campaigns: List[Campaign] = []

    for cluster_id, cluster_segs in clusters.items():
        all_actors: Set[str] = set()
        all_channels: Set[str] = set()
        all_wallets: Set[str] = set()
        all_domains: Set[str] = set()
        all_msg_ids: List[str] = []

        for seg in cluster_segs:
            all_actors.update(seg.actors)
            all_channels.update(seg.channels)
            all_wallets.update(seg.wallets)
            all_domains.update(seg.domains)
            all_msg_ids.extend(seg.message_ids)

        start_time = min(seg.start for seg in cluster_segs)
        end_time = max(seg.end for seg in cluster_segs)

        # Confidence calculation
        actor_factor = min(1.0, len(all_actors) / 5.0)
        msg_factor = min(1.0, len(all_msg_ids) / 50.0)
        base_confidence = 0.40 + 0.20 * actor_factor + 0.15 * msg_factor

        if len(cluster_segs) > 1:
            # Multi-segment overlap bonuses
            pairwise_actor_overlaps = []
            for i in range(len(cluster_segs)):
                for j in range(i + 1, len(cluster_segs)):
                    union_size = len(cluster_segs[i].actors | cluster_segs[j].actors)
                    if union_size > 0:
                        jaccard = len(cluster_segs[i].actors & cluster_segs[j].actors) / union_size
                        pairwise_actor_overlaps.append(jaccard)
            avg_actor_overlap = (
                statistics.mean(pairwise_actor_overlaps) if pairwise_actor_overlaps else 0.0
            )

            shared_wallets_across_segs = sum(
                1 for i in range(len(cluster_segs)) for j in range(i + 1, len(cluster_segs))
                if (cluster_segs[i].wallets & cluster_segs[j].wallets)
            )
            shared_domains_across_segs = sum(
                1 for i in range(len(cluster_segs)) for j in range(i + 1, len(cluster_segs))
                if (cluster_segs[i].domains & cluster_segs[j].domains)
            )

            # Temporal proximity between consecutive segments in cluster
            sorted_cluster = sorted(cluster_segs, key=lambda s: s.start)
            inter_segment_gaps = [
                (sorted_cluster[k + 1].start - sorted_cluster[k].end).total_seconds()
                for k in range(len(sorted_cluster) - 1)
            ]
            avg_gap_days = (
                (statistics.mean(inter_segment_gaps) / 86400.0) if inter_segment_gaps else 1.0
            )
            temporal_proximity = max(0.0, 1.0 - min(1.0, avg_gap_days / 30.0))

            conf = (
                base_confidence
                + 0.10 * avg_actor_overlap
                + (0.10 if shared_wallets_across_segs > 0 else 0.0)
                + (0.05 if shared_domains_across_segs > 0 else 0.0)
                + 0.05 * temporal_proximity
            )
        else:
            # Single segment confidence
            conf = base_confidence
            if all_wallets:
                conf += 0.10
            if all_domains:
                conf += 0.05

        final_conf = min(1.0, max(0.1, conf))
        start_str = start_time.strftime("%Y%m%d")
        campaign_name = f"Campaign-{start_str}-{len(all_actors)}actors"

        metadata: Dict[str, Any] = {
            "segment_count": len(cluster_segs),
            "total_messages": len(all_msg_ids),
            "actor_count": len(all_actors),
            "channel_count": len(all_channels),
            "wallet_count": len(all_wallets),
            "domain_count": len(all_domains),
            "duration_hours": round((end_time - start_time).total_seconds() / 3600.0, 2),
        }

        campaign = Campaign(
            campaign_id="",  # Auto-generated by __post_init__
            name=campaign_name,
            actors=sorted(all_actors),
            channels=sorted(all_channels),
            wallets=sorted(all_wallets),
            domains=sorted(all_domains),
            message_ids=sorted(all_msg_ids),
            media_ids=[],
            start=start_time,
            end=end_time,
            confidence=round(final_conf, 4),
            evidence_ids=[],
            generated_at=_now_utc(),
            metadata=metadata,
        )
        campaigns.append(campaign)

    campaigns.sort(key=lambda c: c.start or _now_utc())
    return campaigns
