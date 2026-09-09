"""
SPECTRA Intelligence — Conditional Behavioral Probabilities Module
==================================================================
Extracts context-conditioned behavioral rates: P(feature | context),
context distributions, context entropy, and context-conditioned variance.

Contexts are derived from message metadata:
- channel_id -> 'channel:<id>'
- reply_to_message_id -> 'reply' (present) vs 'initiation' (absent)
- Hour of day -> 'morning'(6-11), 'afternoon'(12-17), 'evening'(18-23), 'night'(0-5)
- Message length -> 'short'(<50), 'medium'(50-200), 'long'(>200)
- Custom context -> via context_fn(msg) -> str | List[str]

Features computed per context:
- profanity_rate: P(profanity | context)
- long_message_rate: P(long_message | context) (length > 200 chars)
- question_rate: P(question | context) (ends with '?')
- emoji_rate: P(emoji | context)
- codeblock_rate: P(codeblock | context)
- url_rate: P(url | context)
- technical_jargon_rate: P(technical_jargon | context)

Standard library only (re, collections, math, statistics, datetime, logging).
"""
from __future__ import annotations

import copy
import logging
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

# Max number of contexts retained in distributions
MAX_CONTEXTS: int = 50

# Canonical feature names
CONDITIONAL_FEATURE_NAMES: Tuple[str, ...] = (
    "profanity_rate",
    "long_message_rate",
    "question_rate",
    "emoji_rate",
    "codeblock_rate",
    "url_rate",
    "technical_jargon_rate",
)

# Built-in lexical lists
PROFANITY_WORDS: frozenset[str] = frozenset({
    "fuck", "fucking", "fucked", "fucker", "fucks", "fuckin", "motherfucker",
    "shit", "shitty", "shitting", "bullshit", "damn", "damned", "damnit",
    "ass", "asshole", "asses", "bitch", "bitches", "bitching", "bastard",
    "bastards", "cunt", "cunts", "dick", "dicks", "dickhead", "piss", "pissed",
    "pissing", "crap", "crappy", "hell", "cock", "cocksucker", "slut", "whore",
    "prick", "twat", "wanker", "bollocks", "bugger", "douche", "douchebag",
    "dipshit", "dumbass", "jackass",
})

TECHNICAL_JARGON_WORDS: frozenset[str] = frozenset({
    "kernel", "compiler", "bytecode", "opcode", "exploit", "payload", "shellcode",
    "vulnerability", "backdoor", "rootkit", "ransomware", "phishing", "sandbox",
    "honeypot", "firewall", "endpoint", "packet", "handshake", "mutex", "semaphore",
    "daemon", "syscall", "firmware", "docker", "kubernetes", "microservice",
    "middleware", "database", "postgres", "sqlite", "redis", "async", "concurrency",
    "threading", "serialization", "deserialization", "refactoring", "debugging",
    "profiling", "latency", "throughput", "bandwidth", "subdomain", "certificate",
    "telemetry", "vector", "embedding", "pipeline", "heuristic", "algorithm",
    "hash", "crypto", "cipher", "encryption", "decryption", "token", "session",
    "authentication", "authorization", "proxy", "vpn", "tcp", "udp", "dns",
    "http", "https", "rest", "graphql", "grpc", "api", "cli", "sdk", "gui",
    "vfs", "sqlite3", "cypher", "gnn", "ast", "cfg", "llvm", "binary",
    "endianness", "buffer", "overflow", "heap", "stack", "pointer",
})

# Compiled regex patterns
_PROFANITY_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(PROFANITY_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

_JARGON_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(TECHNICAL_JARGON_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

_URL_RE = re.compile(
    r"https?://[^\s<>\"']+|ftp://[^\s<>\"']+|www\.[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^\s<>\"']*|t\.me/[^\s<>\"']+",
    re.IGNORECASE,
)

_CODEBLOCK_RE = re.compile(r"```[\s\S]*?```|```")

_QUESTION_RE = re.compile(r"\?[!?\"'\s\U00010000-\U0010ffff\u2600-\u27bf]*$")

# Default template
DEFAULT_CONDITIONAL_FEATURES: Dict[str, Any] = {
    "conditional_probabilities": {},
    "context_distribution": {},
    "context_count": 0,
    "context_entropy": 0.0,
    "context_conditioned_variance": {
        feat: 0.0 for feat in CONDITIONAL_FEATURE_NAMES
    },
}


def _extract_text(msg: Any) -> str:
    """Safely extract string text from a message dictionary or string."""
    if isinstance(msg, dict):
        text = msg.get("content")
        if text is None:
            text = msg.get("text")
        if text is None:
            return ""
        return str(text)
    if isinstance(msg, str):
        return msg
    return ""


def _parse_datetime(val: Any) -> Optional[datetime]:
    """Parse various timestamp representations into a naive UTC datetime object."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is not None:
            return val.astimezone(timezone.utc).replace(tzinfo=None)
        return val
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            return None
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            return None
        try:
            iso_str = cleaned.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
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
                return datetime.strptime(cleaned, fmt)
            except Exception:
                pass
    return None


def _is_emoji_char(char: str) -> bool:
    """Determine if a single character is an emoji or pictorial symbol."""
    cp = ord(char)
    if (
        (0x1F600 <= cp <= 0x1F64F)    # Emoticons
        or (0x1F300 <= cp <= 0x1F5FF) # Misc Symbols and Pictographs
        or (0x1F680 <= cp <= 0x1F6FF) # Transport and Map
        or (0x1F700 <= cp <= 0x1F77F) # Alchemical Symbols
        or (0x1F780 <= cp <= 0x1F7FF) # Geometric Shapes Extended
        or (0x1F800 <= cp <= 0x1F8FF) # Supplemental Arrows-C
        or (0x1F900 <= cp <= 0x1F9FF) # Supplemental Symbols and Pictographs
        or (0x1FA00 <= cp <= 0x1FA6F) # Chess Symbols
        or (0x1FA70 <= cp <= 0x1FAFF) # Symbols and Pictographs Extended-A
        or (0x2600 <= cp <= 0x26FF)   # Misc symbols
        or (0x2700 <= cp <= 0x27BF)   # Dingbats
        or (0x1F1E6 <= cp <= 0x1F1FF) # Regional indicator symbols (flags)
    ):
        return True
    return False


def _has_profanity(text: str) -> bool:
    """Check if text contains profanity words."""
    if not text:
        return False
    return _PROFANITY_RE.search(text) is not None


def _is_question(text: str) -> bool:
    """Check if text represents a question (ends with '?')."""
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_QUESTION_RE.search(stripped))


def _has_emoji(text: str) -> bool:
    """Check if text contains any emoji character."""
    if not text:
        return False
    return any(_is_emoji_char(c) for c in text)


def _has_codeblock(text: str) -> bool:
    """Check if text contains code blocks."""
    if not text:
        return False
    return bool(_CODEBLOCK_RE.search(text))


def _has_url(text: str) -> bool:
    """Check if text contains URLs."""
    if not text:
        return False
    return bool(_URL_RE.search(text))


def _has_technical_jargon(text: str) -> bool:
    """Check if text contains technical jargon terms."""
    if not text:
        return False
    return _JARGON_RE.search(text) is not None


def _get_length_bucket(text: str) -> str:
    """Return length bucket: 'short' (<50), 'medium' (50-200), 'long' (>200)."""
    length = len(text)
    if length < 50:
        return "short"
    if length <= 200:
        return "medium"
    return "long"


def _get_hour_bucket(dt: datetime) -> str:
    """Return hour bucket: 'morning'(6-11), 'afternoon'(12-17), 'evening'(18-23), 'night'(0-5)."""
    hour = dt.hour
    if 6 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 17:
        return "afternoon"
    if 18 <= hour <= 23:
        return "evening"
    return "night"


def _extract_contexts(
    msg: Any,
    text: str,
    context_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Set[str]:
    """Derive all applicable context keys for a message."""
    contexts: Set[str] = set()

    # 1. Length bucket (always present)
    contexts.add(_get_length_bucket(text))

    if isinstance(msg, dict):
        # 2. Channel ID
        channel_id = msg.get("channel_id")
        if channel_id is not None:
            cid_str = str(channel_id).strip()
            if cid_str:
                contexts.add(f"channel:{cid_str}")

        # 3. Reply vs Initiation
        reply_to = msg.get("reply_to_message_id")
        if reply_to is not None and reply_to != "" and reply_to != 0 and reply_to is not False:
            contexts.add("reply")
        else:
            contexts.add("initiation")

        # 4. Hour bucket from date
        date_val = msg.get("date")
        if date_val is None:
            date_val = msg.get("timestamp")
        if date_val is None:
            date_val = msg.get("created_at")

        dt = _parse_datetime(date_val)
        if dt is not None:
            contexts.add(_get_hour_bucket(dt))

        # 5. Custom context function
        if context_fn is not None and callable(context_fn):
            try:
                custom = context_fn(msg)
                if isinstance(custom, str):
                    c = custom.strip()
                    if c:
                        contexts.add(c)
                elif isinstance(custom, (list, tuple, set)):
                    for item in custom:
                        if isinstance(item, str):
                            c = item.strip()
                            if c:
                                contexts.add(c)
            except Exception as exc:
                logger.debug("Failed executing custom context_fn: %s", exc)
    else:
        # Fallback if msg is not a dict
        contexts.add("initiation")

    return contexts


def extract_conditional_features(
    messages: List[Dict[str, Any]],
    context_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Extract conditional behavioral probabilities and cross-context statistics.

    Args:
        messages: List of message dictionaries containing text/content and metadata.
        context_fn: Optional custom callable taking a message dict and returning context(s).

    Returns:
        Dictionary containing:
            - conditional_probabilities: Dict mapping context -> feature rates
            - context_distribution: Dict mapping context -> proportion of context occurrences
            - context_count: Total number of retained contexts (capped at 50)
            - context_entropy: Shannon entropy of the context distribution
            - context_conditioned_variance: Variance of each feature rate across contexts
    """
    if not messages:
        return copy.deepcopy(DEFAULT_CONDITIONAL_FEATURES)

    context_counts: Counter[str] = Counter()
    context_feature_sums: Dict[str, Dict[str, float]] = defaultdict(lambda: {f: 0.0 for f in CONDITIONAL_FEATURE_NAMES})

    valid_messages_count = 0

    for msg in messages:
        text = _extract_text(msg)
        contexts = _extract_contexts(msg, text, context_fn=context_fn)
        if not contexts:
            continue

        valid_messages_count += 1

        # Calculate message feature flags (1.0 if present, 0.0 otherwise)
        feature_flags = {
            "profanity_rate": 1.0 if _has_profanity(text) else 0.0,
            "long_message_rate": 1.0 if len(text) > 200 else 0.0,
            "question_rate": 1.0 if _is_question(text) else 0.0,
            "emoji_rate": 1.0 if _has_emoji(text) else 0.0,
            "codeblock_rate": 1.0 if _has_codeblock(text) else 0.0,
            "url_rate": 1.0 if _has_url(text) else 0.0,
            "technical_jargon_rate": 1.0 if _has_technical_jargon(text) else 0.0,
        }

        for ctx in contexts:
            context_counts[ctx] += 1
            for f_name, val in feature_flags.items():
                context_feature_sums[ctx][f_name] += val

    if not context_counts:
        return copy.deepcopy(DEFAULT_CONDITIONAL_FEATURES)

    # Sort contexts by occurrence count descending, then alphabetically for determinism
    sorted_contexts = sorted(context_counts.keys(), key=lambda c: (-context_counts[c], c))
    selected_contexts = sorted_contexts[:MAX_CONTEXTS]

    # Compute conditional probabilities per selected context
    conditional_probabilities: Dict[str, Dict[str, float]] = {}
    for ctx in selected_contexts:
        n_ctx = context_counts[ctx]
        conditional_probabilities[ctx] = {
            f: round(context_feature_sums[ctx][f] / n_ctx, 6)
            for f in CONDITIONAL_FEATURE_NAMES
        }

    # Compute context distribution over selected contexts
    total_ctx_occurrences = sum(context_counts[c] for c in selected_contexts)
    context_distribution: Dict[str, float] = {}
    entropy = 0.0

    if total_ctx_occurrences > 0:
        for ctx in selected_contexts:
            p = context_counts[ctx] / total_ctx_occurrences
            context_distribution[ctx] = round(p, 6)
            if p > 0.0:
                entropy -= p * math.log2(p)

    context_entropy = round(max(0.0, float(entropy)), 6)
    context_count = len(selected_contexts)

    # Compute context-conditioned variance across contexts
    context_conditioned_variance: Dict[str, float] = {}
    num_contexts = len(selected_contexts)

    for f_name in CONDITIONAL_FEATURE_NAMES:
        if num_contexts <= 1:
            context_conditioned_variance[f_name] = 0.0
        else:
            rates = [conditional_probabilities[c][f_name] for c in selected_contexts]
            mean_rate = sum(rates) / num_contexts
            variance = sum((r - mean_rate) ** 2 for r in rates) / num_contexts
            context_conditioned_variance[f_name] = round(max(0.0, float(variance)), 6)

    return {
        "conditional_probabilities": conditional_probabilities,
        "context_distribution": context_distribution,
        "context_count": context_count,
        "context_entropy": context_entropy,
        "context_conditioned_variance": context_conditioned_variance,
    }


def compare_conditional_features(
    feat_a: Dict[str, Any],
    feat_b: Dict[str, Any],
) -> Tuple[float, float]:
    """Compare two conditional feature sets using cosine similarity across shared contexts.

    Args:
        feat_a: First feature dict.
        feat_b: Second feature dict.

    Returns:
        Tuple of (similarity_score 0-1, confidence 0-1).
    """
    if not isinstance(feat_a, dict) or not isinstance(feat_b, dict) or not feat_a or not feat_b:
        return (0.0, 0.0)

    probs_a = feat_a.get("conditional_probabilities", {})
    probs_b = feat_b.get("conditional_probabilities", {})

    if not isinstance(probs_a, dict) or not isinstance(probs_b, dict) or not probs_a or not probs_b:
        return (0.0, 0.0)

    shared_contexts = sorted(set(probs_a.keys()) & set(probs_b.keys()))
    all_contexts = set(probs_a.keys()) | set(probs_b.keys())

    if not shared_contexts:
        return (0.0, 0.0)

    vec_a: List[float] = []
    vec_b: List[float] = []

    for ctx in shared_contexts:
        ctx_a = probs_a[ctx]
        ctx_b = probs_b[ctx]
        if isinstance(ctx_a, dict) and isinstance(ctx_b, dict):
            for f in CONDITIONAL_FEATURE_NAMES:
                vec_a.append(float(ctx_a.get(f, 0.0)))
                vec_b.append(float(ctx_b.get(f, 0.0)))

    # Also incorporate context-conditioned variance
    var_a = feat_a.get("context_conditioned_variance", {})
    var_b = feat_b.get("context_conditioned_variance", {})
    if isinstance(var_a, dict) and isinstance(var_b, dict):
        for f in CONDITIONAL_FEATURE_NAMES:
            vec_a.append(float(var_a.get(f, 0.0)))
            vec_b.append(float(var_b.get(f, 0.0)))

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0.0 or norm_b == 0.0:
        return (0.0, 0.0)

    raw_cos = dot / (norm_a * norm_b)
    sim = max(0.0, min(1.0, raw_cos))

    coverage = len(shared_contexts) / len(all_contexts) if all_contexts else 0.0
    confidence = max(0.0, min(1.0, coverage))

    return (round(sim, 4), round(confidence, 4))
