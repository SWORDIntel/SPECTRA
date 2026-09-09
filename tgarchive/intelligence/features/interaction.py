"""
Interaction-Conditioned Style Feature Extraction for Persona Attribution (L11)
==============================================================================
Groups messages by interaction context (channel, recipient class, time period,
message type) and computes per-context style vectors, then measures style shifts
and cross-context consistency.

Standard library only (re, collections, math, statistics, datetime, unicodedata, logging).
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

# ── Built-in Lexical Lists ───────────────────────────────────────────────────

PROFANITY_WORDS: frozenset[str] = frozenset({
    "fuck", "fucking", "fucked", "fucker", "fucks", "fuckin", "motherfucker",
    "shit", "shitty", "shitting", "bullshit", "damn", "damned", "damnit",
    "ass", "asshole", "asses", "bitch", "bitches", "bitching", "bastard",
    "bastards", "cunt", "cunts", "dick", "dicks", "dickhead", "piss", "pissed",
    "pissing", "crap", "crappy", "hell", "cock", "cocksucker", "slut", "whore",
    "prick", "twat", "wanker", "bollocks", "bugger", "douche", "douchebag",
    "dipshit", "dumbass", "jackass",
})

SLANG_WORDS: frozenset[str] = frozenset({
    "bruh", "fam", "lit", "cap", "bet", "sus", "simp", "based", "cringe", "yeet",
    "flex", "vibe", "vibes", "drip", "lowkey", "highkey", "deadass", "finna",
    "gonna", "wanna", "gotta", "kinda", "sorta", "dunno", "ima", "tryna", "ain't",
    "homie", "dude", "bro", "sis", "pwn", "pwned", "rekt", "noob", "newb", "kek",
    "afaik", "idk", "smh", "tbh", "ngl", "fr", "rn", "wyd", "wbu", "gg", "ez",
    "glhf", "fwiw", "irl", "omg", "wtf", "fml", "imo", "imho", "brb", "gtg",
    "tldr", "fyi", "nsfw", "bussin", "sheesh", "rizz", "gyatt", "skibidi", "chad",
    "cope", "seethe", "mald", "dogwater", "trash", "clout", "ghosted", "salty",
    "shook", "tea", "woke", "yolo", "fomo", "hmu", "dm", "pm", "lmao", "lmfao",
    "rofl", "lol", "bop", "stan", "nocap", "mid", "opps", "slaps", "fire",
    "goat", "snack", "extra", "savage", "periodt", "cancelled",
})

TECHNICAL_JARGON: frozenset[str] = frozenset({
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
    "endianness", "buffer", "overflow", "heap", "stack", "pointer", "cpu", "gpu",
})

DISCOURSE_WORDS: frozenset[str] = frozenset({
    "actually", "basically", "literally", "honestly", "frankly", "obviously",
    "clearly", "definitely", "certainly", "surely", "maybe", "perhaps",
    "probably", "possibly", "supposedly", "apparently", "however", "therefore",
    "nevertheless", "furthermore", "moreover", "meanwhile", "anyway", "anyways",
    "besides", "instead", "otherwise", "consequently", "specifically", "namely",
    "indeed", "further", "nonetheless", "admittedly", "incidentally",
})

DISCOURSE_PHRASES: Tuple[str, ...] = (
    "i mean", "you know", "in fact", "of course", "as well", "for example",
    "for instance", "in other words", "to be honest", "as a result",
    "on the other hand", "at least", "first of all", "by the way",
    "as far as", "in my opinion", "to be fair", "that said",
)

# ── Regex Patterns ───────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"\b[a-zA-Z0-9_'’-]+\b")
_UPPERCASE_WORD_RE = re.compile(r"\b[A-Z]{2,}\b")

# ── Feature Keys & Default Schemas ───────────────────────────────────────────

STYLE_FEATURE_KEYS: Tuple[str, ...] = (
    "avg_length",
    "profanity_rate",
    "emoji_rate",
    "question_rate",
    "formality_score",
    "slang_rate",
    "technical_jargon_rate",
    "discourse_marker_rate",
)

DEFAULT_STYLE_VECTOR: Dict[str, float] = {
    "avg_length": 0.0,
    "profanity_rate": 0.0,
    "emoji_rate": 0.0,
    "question_rate": 0.0,
    "formality_score": 0.0,
    "slang_rate": 0.0,
    "technical_jargon_rate": 0.0,
    "discourse_marker_rate": 0.0,
}

DEFAULT_INTERACTION_FEATURES: Dict[str, Any] = {
    "style_by_channel": {},
    "style_by_recipient_class": {},
    "style_by_time_period": {},
    "style_by_message_type": {},
    "register_shift_score": 0.0,
    "recipient_style_distance": 0.0,
    "channel_style_distance": 0.0,
    "context_style_consistency": 1.0,
    "context_count": 0,
}


# ── Helper Functions ─────────────────────────────────────────────────────────

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


def _is_emoji_char(char: str) -> bool:
    """Determine if a single character is an emoji or pictorial symbol."""
    cp = ord(char)
    if (
        (0x1F600 <= cp <= 0x1F64F)     # Emoticons
        or (0x1F300 <= cp <= 0x1F5FF)   # Misc Symbols and Pictographs
        or (0x1F680 <= cp <= 0x1F6FF)   # Transport and Map
        or (0x1F700 <= cp <= 0x1F77F)   # Alchemical Symbols
        or (0x1F780 <= cp <= 0x1F7FF)   # Geometric Shapes Extended
        or (0x1F800 <= cp <= 0x1F8FF)   # Supplemental Arrows-C
        or (0x1F900 <= cp <= 0x1F9FF)   # Supplemental Symbols and Pictographs
        or (0x1FA00 <= cp <= 0x1FA6F)   # Chess Symbols
        or (0x1FA70 <= cp <= 0x1FAFF)   # Symbols and Pictographs Extended-A
        or (0x2600 <= cp <= 0x26FF)     # Misc symbols
        or (0x2700 <= cp <= 0x27BF)     # Dingbats
        or (0x1F1E6 <= cp <= 0x1F1FF)   # Regional indicator symbols (flags)
    ):
        return True
    cat = unicodedata.category(char)
    return cat in ("So", "Sk") and cp > 0x7F


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    """Parse an ISO string, unix timestamp, or datetime into a UTC datetime."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    if isinstance(ts, str):
        s = ts.strip()
        if not s:
            return None
        # Try ISO format
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
        # Try common datetime string formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        # Try unix timestamp string
        try:
            return datetime.fromtimestamp(float(s), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    return None


def _get_time_period(dt: datetime) -> str:
    """Classify UTC datetime into morning(6-11), afternoon(12-17), evening(18-23), night(0-5)."""
    hour = dt.hour
    if 6 <= hour <= 11:
        return "morning"
    elif 12 <= hour <= 17:
        return "afternoon"
    elif 18 <= hour <= 23:
        return "evening"
    else:  # 0 <= hour <= 5
        return "night"


def _infer_recipient_class(msg: Dict[str, Any]) -> Optional[str]:
    """Infer recipient class ('dm' vs 'group') from message metadata."""
    # 1. Explicit recipient_class field
    rc = msg.get("recipient_class")
    if isinstance(rc, str):
        rc_lower = rc.lower().strip()
        if rc_lower in ("dm", "private", "user", "direct"):
            return "dm"
        if rc_lower in ("group", "supergroup", "channel", "megagroup", "public"):
            return "group"

    # 2. chat_type or type field
    chat_type = msg.get("chat_type") or msg.get("type")
    if isinstance(chat_type, str):
        ct_lower = chat_type.lower().strip()
        if ct_lower in ("dm", "private", "user", "direct"):
            return "dm"
        if ct_lower in ("group", "supergroup", "channel", "megagroup", "gigagroup"):
            return "group"

    # 3. is_group boolean flag
    if "is_group" in msg:
        return "group" if bool(msg.get("is_group")) else "dm"

    # 4. channel_id / chat_id heuristics (Telegram convention: negative = group/channel, positive = dm)
    cid = msg.get("channel_id")
    if cid is None:
        cid = msg.get("chat_id")
    if cid is not None:
        if isinstance(cid, (int, float)):
            if cid < 0:
                return "group"
            elif cid > 0:
                return "dm"
        elif isinstance(cid, str):
            cid_str = cid.strip()
            if cid_str.startswith("-"):
                return "group"
            try:
                val = int(cid_str)
                if val < 0:
                    return "group"
                elif val > 0:
                    return "dm"
            except ValueError:
                pass

    return None


def _infer_message_type(msg: Dict[str, Any]) -> str:
    """Infer message type ('initiation' vs 'reply')."""
    reply_id = msg.get("reply_to_message_id")
    if reply_id is None:
        reply_id = msg.get("reply_to_msg_id")
    if reply_id is None:
        reply_id = msg.get("reply_to")

    if reply_id is not None and reply_id != 0 and reply_id != "" and reply_id is not False:
        return "reply"
    if msg.get("is_reply") is True:
        return "reply"
    return "initiation"


# ── Style Vector Computation ─────────────────────────────────────────────────

def compute_style_vector(messages: List[Dict[str, Any]]) -> Dict[str, float]:
    """Compute an 8-dimensional compact style vector for a list of messages.

    Args:
        messages: List of message dictionaries.

    Returns:
        Dictionary mapping feature name to float value rounded to 6 decimal places:
        - avg_length: average character length
        - profanity_rate: profanity words / total words
        - emoji_rate: emoji characters / total words
        - question_rate: messages containing question mark / total messages
        - formality_score: composite formality score (0.0 - 1.0)
        - slang_rate: slang words / total words
        - technical_jargon_rate: technical jargon words / total words
        - discourse_marker_rate: discourse markers / total words
    """
    if not messages:
        return dict(DEFAULT_STYLE_VECTOR)

    texts = [_extract_text(m) for m in messages]
    non_empty_texts = [t for t in texts if t]

    if not non_empty_texts:
        return dict(DEFAULT_STYLE_VECTOR)

    num_messages = len(non_empty_texts)
    corpus = "\n".join(non_empty_texts)
    corpus_lower = corpus.lower()

    # 1. Average length (character length per message)
    total_chars = sum(len(t) for t in non_empty_texts)
    avg_length = total_chars / num_messages

    # 2. Tokenize words
    words = _WORD_RE.findall(corpus)
    words_lower = [w.lower() for w in words]
    total_words = len(words)

    # 3. Profanity rate
    if total_words > 0:
        profanity_count = sum(1 for w in words_lower if w in PROFANITY_WORDS)
        profanity_rate = profanity_count / total_words
    else:
        profanity_count = 0
        profanity_rate = 0.0

    # 4. Emoji rate
    emoji_chars = [c for c in corpus if _is_emoji_char(c)]
    emoji_count = len(emoji_chars)
    if total_words > 0:
        emoji_rate = emoji_count / total_words
    elif total_chars > 0 and emoji_count > 0:
        emoji_rate = min(1.0, float(emoji_count) / total_chars)
    else:
        emoji_rate = 0.0

    # 5. Question rate (fraction of messages with a question mark)
    question_msgs = sum(1 for t in non_empty_texts if "?" in t)
    question_rate = question_msgs / num_messages

    # 6. Slang rate
    if total_words > 0:
        slang_count = sum(1 for w in words_lower if w in SLANG_WORDS)
        slang_rate = slang_count / total_words
    else:
        slang_count = 0
        slang_rate = 0.0

    # 7. Technical jargon rate
    if total_words > 0:
        jargon_count = sum(1 for w in words_lower if w in TECHNICAL_JARGON)
        technical_jargon_rate = jargon_count / total_words
    else:
        jargon_count = 0
        technical_jargon_rate = 0.0

    # 8. Discourse marker rate (single words + multi-word phrases)
    if total_words > 0:
        discourse_word_count = sum(1 for w in words_lower if w in DISCOURSE_WORDS)
        discourse_phrase_count = sum(
            len(re.findall(r"\b" + re.escape(p) + r"\b", corpus_lower))
            for p in DISCOURSE_PHRASES
        )
        total_discourse = discourse_word_count + discourse_phrase_count
        discourse_marker_rate = min(1.0, total_discourse / total_words)
    else:
        discourse_marker_rate = 0.0

    # 9. Formality composite score (0.0 - 1.0)
    if total_words > 0:
        # Word length factor: typical formal English ~5.5-6.5 chars, casual ~4.0 chars
        avg_word_len = sum(len(w) for w in words) / total_words
        word_len_score = max(0.0, min(1.0, (avg_word_len - 3.5) / 3.0))

        # Cleanliness factor: absence of profanity, slang, and emojis
        informal_density = (profanity_count + slang_count + emoji_count) / total_words
        cleanliness_score = max(0.0, min(1.0, 1.0 - informal_density * 4.0))

        # Sentence complexity
        raw_sentences = [s.strip() for s in re.split(r"[.!?\n]+", corpus) if s.strip()]
        if raw_sentences:
            avg_sentence_len = total_words / len(raw_sentences)
            sentence_score = max(0.0, min(1.0, (avg_sentence_len - 3.0) / 15.0))
        else:
            sentence_score = 0.5

        # Technical & discourse markers factor
        formal_markers = jargon_count + sum(
            1 for w in words_lower if w in ("therefore", "furthermore", "consequently", "however", "specifically")
        )
        formal_score = max(0.0, min(1.0, (formal_markers / total_words) * 8.0))

        # Screaming caps & excessive punctuation penalty
        screaming_caps = sum(
            1 for w in words if len(w) > 2 and w.isupper() and w.lower() not in TECHNICAL_JARGON
        )
        excessive_punct = len(re.findall(r"[!?]{2,}", corpus))
        screaming_penalty = min(0.3, ((screaming_caps + excessive_punct) / total_words) * 3.0)

        raw_formality = (
            0.35 * word_len_score
            + 0.35 * cleanliness_score
            + 0.15 * sentence_score
            + 0.15 * formal_score
            - screaming_penalty
        )
        formality_score = max(0.0, min(1.0, raw_formality))
    else:
        formality_score = 0.0

    return {
        "avg_length": round(float(avg_length), 6),
        "profanity_rate": round(float(profanity_rate), 6),
        "emoji_rate": round(float(emoji_rate), 6),
        "question_rate": round(float(question_rate), 6),
        "formality_score": round(float(formality_score), 6),
        "slang_rate": round(float(slang_rate), 6),
        "technical_jargon_rate": round(float(technical_jargon_rate), 6),
        "discourse_marker_rate": round(float(discourse_marker_rate), 6),
    }


# ── Distance Computations ────────────────────────────────────────────────────

def _style_vector_to_list(vec: Dict[str, float]) -> List[float]:
    """Convert style vector dict to normalized float list for distance computation."""
    res: List[float] = []
    for k in STYLE_FEATURE_KEYS:
        val = float(vec.get(k, 0.0))
        if k == "avg_length":
            # Scale avg_length so typical message lengths (0-200 chars) map to [0, 1]
            val = max(0.0, min(1.0, val / 200.0))
        else:
            val = max(0.0, min(1.0, val))
        res.append(val)
    return res


def cosine_distance(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Compute cosine distance (0.0 to 1.0) between two style vectors."""
    if not isinstance(vec_a, dict) or not isinstance(vec_b, dict) or not vec_a or not vec_b:
        return 0.0

    u = _style_vector_to_list(vec_a)
    v = _style_vector_to_list(vec_b)

    dot = sum(a * b for a, b in zip(u, v))
    norm_u = math.sqrt(sum(a * a for a in u))
    norm_v = math.sqrt(sum(b * b for b in v))

    if norm_u == 0.0 and norm_v == 0.0:
        return 0.0
    if norm_u == 0.0 or norm_v == 0.0:
        return 1.0

    cos_sim = dot / (norm_u * norm_v)
    cos_sim = max(0.0, min(1.0, cos_sim))
    cos_dist = 1.0 - cos_sim
    return round(float(cos_dist), 6)


# ── Main Feature Extractor ───────────────────────────────────────────────────

def extract_interaction_features(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract interaction-conditioned style features and cross-context distances.

    Groups messages by:
    - style_by_channel: per channel_id
    - style_by_recipient_class: 'dm' vs 'group'
    - style_by_time_period: 'morning'(6-11), 'afternoon'(12-17), 'evening'(18-23), 'night'(0-5)
    - style_by_message_type: 'initiation' vs 'reply'

    For each context, computes a compact 8-dim style vector:
    (avg_length, profanity_rate, emoji_rate, question_rate, formality_score,
     slang_rate, technical_jargon_rate, discourse_marker_rate)

    Then measures:
    - register_shift_score: max pairwise cosine distance across contexts (0-1)
    - recipient_style_distance: distance between dm and group styles
    - channel_style_distance: mean pairwise distance across channels
    - context_style_consistency: 1 - register_shift_score
    - context_count: total active context buckets evaluated

    Args:
        messages: List of message dicts with 'content'/'text' and optional
                  'channel_id', 'reply_to_message_id', 'date', 'user_id'.

    Returns:
        JSON-serializable dictionary of interaction style features.
    """
    if not messages:
        return {
            k: (dict(v) if isinstance(v, dict) else v)
            for k, v in DEFAULT_INTERACTION_FEATURES.items()
        }

    # Filter messages that have non-empty text
    valid_messages: List[Dict[str, Any]] = [
        m for m in messages if isinstance(m, dict) and _extract_text(m).strip()
    ]

    if not valid_messages:
        return {
            k: (dict(v) if isinstance(v, dict) else v)
            for k, v in DEFAULT_INTERACTION_FEATURES.items()
        }

    # ── Group Messages by Contexts ───────────────────────────────────────────
    channel_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    recipient_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    time_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    message_type_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for msg in valid_messages:
        # Channel grouping
        cid = msg.get("channel_id")
        if cid is not None and str(cid).strip():
            channel_groups[str(cid).strip()].append(msg)

        # Recipient class grouping ('dm' vs 'group')
        rc = _infer_recipient_class(msg)
        if rc:
            recipient_groups[rc].append(msg)

        # Time period grouping
        ts = msg.get("date") or msg.get("timestamp") or msg.get("created_at")
        dt = _parse_timestamp(ts)
        if dt:
            period = _get_time_period(dt)
            time_groups[period].append(msg)

        # Message type grouping ('initiation' vs 'reply')
        m_type = _infer_message_type(msg)
        message_type_groups[m_type].append(msg)

    # ── Compute Style Vectors per Context ────────────────────────────────────
    style_by_channel: Dict[str, Dict[str, float]] = {
        cid: compute_style_vector(msgs)
        for cid, msgs in channel_groups.items()
    }

    style_by_recipient_class: Dict[str, Dict[str, float]] = {
        rc: compute_style_vector(msgs)
        for rc, msgs in recipient_groups.items()
    }

    style_by_time_period: Dict[str, Dict[str, float]] = {
        period: compute_style_vector(msgs)
        for period, msgs in time_groups.items()
    }

    style_by_message_type: Dict[str, Dict[str, float]] = {
        m_type: compute_style_vector(msgs)
        for m_type, msgs in message_type_groups.items()
    }

    # ── Compute Distances ────────────────────────────────────────────────────
    # 1. Collect all active context style vectors for global register shift
    all_context_vectors: List[Dict[str, float]] = []
    all_context_vectors.extend(style_by_channel.values())
    all_context_vectors.extend(style_by_recipient_class.values())
    all_context_vectors.extend(style_by_time_period.values())
    all_context_vectors.extend(style_by_message_type.values())

    context_count = len(all_context_vectors)

    # 2. Register shift score (max pairwise cosine distance across contexts)
    if len(all_context_vectors) >= 2:
        pairwise_dists = [
            cosine_distance(all_context_vectors[i], all_context_vectors[j])
            for i in range(len(all_context_vectors))
            for j in range(i + 1, len(all_context_vectors))
        ]
        register_shift_score = max(pairwise_dists) if pairwise_dists else 0.0
    else:
        register_shift_score = 0.0

    register_shift_score = round(float(register_shift_score), 6)

    # 3. Context style consistency = 1 - register_shift_score
    context_style_consistency = round(
        max(0.0, min(1.0, 1.0 - register_shift_score)), 6
    )

    # 4. Recipient style distance between 'dm' and 'group'
    if "dm" in style_by_recipient_class and "group" in style_by_recipient_class:
        recipient_style_distance = cosine_distance(
            style_by_recipient_class["dm"], style_by_recipient_class["group"]
        )
    else:
        recipient_style_distance = 0.0

    recipient_style_distance = round(float(recipient_style_distance), 6)

    # 5. Channel style distance (mean pairwise distance across channels)
    channel_vectors = list(style_by_channel.values())
    if len(channel_vectors) >= 2:
        chan_dists = [
            cosine_distance(channel_vectors[i], channel_vectors[j])
            for i in range(len(channel_vectors))
            for j in range(i + 1, len(channel_vectors))
        ]
        channel_style_distance = (
            sum(chan_dists) / len(chan_dists) if chan_dists else 0.0
        )
    else:
        channel_style_distance = 0.0

    channel_style_distance = round(float(channel_style_distance), 6)

    return {
        "style_by_channel": style_by_channel,
        "style_by_recipient_class": style_by_recipient_class,
        "style_by_time_period": style_by_time_period,
        "style_by_message_type": style_by_message_type,
        "register_shift_score": register_shift_score,
        "recipient_style_distance": recipient_style_distance,
        "channel_style_distance": channel_style_distance,
        "context_style_consistency": context_style_consistency,
        "context_count": context_count,
    }


def compare_interaction_features(
    feat_a: Dict[str, Any],
    feat_b: Dict[str, Any],
) -> Tuple[float, float]:
    """Compare two interaction feature dictionaries.

    Args:
        feat_a: First interaction feature dict.
        feat_b: Second interaction feature dict.

    Returns:
        Tuple of (similarity_score 0-1, confidence 0-1).
    """
    if not isinstance(feat_a, dict) or not isinstance(feat_b, dict) or not feat_a or not feat_b:
        return (0.0, 0.0)

    # Compare core distance scalar metrics
    scalar_keys = [
        "register_shift_score",
        "recipient_style_distance",
        "channel_style_distance",
        "context_style_consistency",
    ]
    diffs: List[float] = []
    for k in scalar_keys:
        if k in feat_a and k in feat_b:
            val_a = float(feat_a[k])
            val_b = float(feat_b[k])
            diffs.append(abs(val_a - val_b))

    if not diffs:
        return (0.0, 0.0)

    mean_diff = sum(diffs) / len(diffs)
    sim = max(0.0, min(1.0, 1.0 - mean_diff))
    confidence = len(diffs) / len(scalar_keys)

    return (round(float(sim), 4), round(float(confidence), 4))
