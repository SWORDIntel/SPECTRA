"""
Linguistic Feature Extraction and Comparison for Actor Attribution
==================================================================
Extracts stylometric, lexical, orthographic, and structural features from messages
to characterize an actor's unique writing fingerprints.

Standard library only (re, collections, statistics, math, hashlib, unicodedata).
"""
from __future__ import annotations

import logging
import math
import re
import string
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# Top 30 function words commonly referenced in stylometric analysis
TOP_30_FUNCTION_WORDS: Tuple[str, ...] = (
    "the", "and", "to", "of", "a", "in", "that", "is", "i", "it",
    "for", "as", "with", "on", "was", "at", "by", "an", "be", "this",
    "have", "from", "or", "one", "had", "not", "but", "what", "all", "were",
)

# Top 10 function words exported as flat keys: fw_the, fw_and, etc.
TOP_10_FUNCTION_WORDS: Tuple[str, ...] = (
    "the", "and", "to", "of", "a", "in", "that", "is", "i", "it",
)

# Canonical set of punctuation characters (32 standard ASCII punctuation chars)
POSSIBLE_PUNCTUATION: str = string.punctuation

# Common English contraction regex pattern
CONTRACTION_PATTERN = re.compile(
    r"\b[a-zA-Z]+['’](?:ve|ll|d|re|s|m|t)\b",
    re.IGNORECASE,
)

# Default flat feature dictionary with zero values
DEFAULT_LINGUISTIC_FEATURES: Dict[str, float] = {
    "char_2gram_diversity": 0.0,
    "char_3gram_diversity": 0.0,
    "char_4gram_diversity": 0.0,
    **{f"fw_{w}": 0.0 for w in TOP_10_FUNCTION_WORDS},
    "punctuation_density": 0.0,
    "punctuation_diversity": 0.0,
    "whitespace_trailing_ratio": 0.0,
    "whitespace_double_space_ratio": 0.0,
    "typo_rate": 0.0,
    "contraction_rate": 0.0,
    "emoji_density": 0.0,
    "emoji_diversity": 0.0,
    "lexical_richness_ttr": 0.0,
    "lexical_richness_yule_k": 0.0,
    "code_switching_score": 0.0,
    "avg_line_breaks": 0.0,
    "avg_message_length": 0.0,
    "avg_word_length": 0.0,
    "avg_sentence_length": 0.0,
    "uppercase_ratio": 0.0,
    "digit_ratio": 0.0,
    "special_char_ratio": 0.0,
    "single_word_utterance_rate": 0.0,
    "single_sentence_utterance_rate": 0.0,
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


def _is_emoji_char(char: str) -> bool:
    """Determine if a single character is an emoji or pictorial symbol."""
    cp = ord(char)
    if (
        (0x1F600 <= cp <= 0x1F64F)   # Emoticons
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
    # Check general Unicode category for symbols/pictographs
    cat = unicodedata.category(char)
    return cat in ("So", "Sk") and cp > 0x7F


def _detect_scripts(text: str) -> Set[str]:
    """Identify unicode script families present in text."""
    scripts: Set[str] = set()
    for char in text:
        if not char.isalpha():
            continue
        cp = ord(char)
        if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A) or (0x00C0 <= cp <= 0x024F):
            scripts.add("latin")
        elif (0x0400 <= cp <= 0x04FF) or (0x0500 <= cp <= 0x052F):
            scripts.add("cyrillic")
        elif (0x0600 <= cp <= 0x06FF) or (0x0750 <= cp <= 0x077F):
            scripts.add("arabic")
        elif (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF):
            scripts.add("cjk")
        elif (0x0370 <= cp <= 0x03FF):
            scripts.add("greek")
        elif (0x0590 <= cp <= 0x05FF):
            scripts.add("hebrew")
        elif (0x0900 <= cp <= 0x097F):
            scripts.add("devanagari")
        elif (0x3040 <= cp <= 0x309F) or (0x30A0 <= cp <= 0x30FF):
            scripts.add("japanese")
        elif (0xAC00 <= cp <= 0xD7AF):
            scripts.add("korean")
        else:
            scripts.add("other")
    return scripts


def extract_linguistic_features(messages: List[Dict[str, Any]]) -> Dict[str, float]:
    """Extract stylometric and linguistic features from a list of message dicts.

    Args:
        messages: List of dicts, each with a 'content' or 'text' field.

    Returns:
        Flat dictionary of feature name -> float value.
    """
    if not messages:
        return dict(DEFAULT_LINGUISTIC_FEATURES)

    # Extract text from all messages
    texts = [_extract_text(m) for m in messages]
    non_empty_texts = [t for t in texts if t]
    num_messages = len(messages)

    if not non_empty_texts:
        return dict(DEFAULT_LINGUISTIC_FEATURES)

    corpus = "\n".join(non_empty_texts)
    total_chars = len(corpus)

    if total_chars == 0:
        return dict(DEFAULT_LINGUISTIC_FEATURES)

    features: Dict[str, float] = dict(DEFAULT_LINGUISTIC_FEATURES)

    # ── Character N-Grams Diversity ─────────────────────────────────────────
    for n, feat_key in ((2, "char_2gram_diversity"), (3, "char_3gram_diversity"), (4, "char_4gram_diversity")):
        if total_chars >= n:
            ngrams = [corpus[i:i + n] for i in range(total_chars - n + 1)]
            features[feat_key] = len(set(ngrams)) / len(ngrams)
        else:
            features[feat_key] = 0.0

    # ── Words & Vocabulary ──────────────────────────────────────────────────
    words = re.findall(r"\b\w+\b", corpus.lower())
    total_words = len(words)
    word_counts = Counter(words)

    # Top-10 Function word frequencies (normalized by total_words)
    for fw in TOP_10_FUNCTION_WORDS:
        features[f"fw_{fw}"] = (word_counts.get(fw, 0) / total_words) if total_words > 0 else 0.0

    # ── Punctuation ─────────────────────────────────────────────────────────
    punct_chars = [c for c in corpus if c in POSSIBLE_PUNCTUATION]
    features["punctuation_density"] = len(punct_chars) / total_chars
    features["punctuation_diversity"] = len(set(punct_chars)) / len(POSSIBLE_PUNCTUATION)

    # ── Whitespace Habits ───────────────────────────────────────────────────
    trailing_ws_count = sum(
        1 for t in texts if bool(re.search(r"[ \t]+(?:\r?\n|$)", t)) or t.endswith((" ", "\t"))
    )
    double_space_count = sum(1 for t in texts if "  " in t)
    features["whitespace_trailing_ratio"] = trailing_ws_count / num_messages
    features["whitespace_double_space_ratio"] = double_space_count / num_messages

    # ── Typos & Contractions ────────────────────────────────────────────────
    # Typo heuristic: repeated characters (3+ consecutive identical characters)
    if total_words > 0:
        repeated_char_words = sum(1 for w in words if re.search(r"(\w)\1{2,}", w))
        features["typo_rate"] = repeated_char_words / total_words

        # Contractions count
        contractions = CONTRACTION_PATTERN.findall(corpus)
        features["contraction_rate"] = len(contractions) / total_words
    else:
        features["typo_rate"] = 0.0
        features["contraction_rate"] = 0.0

    # ── Emoji ───────────────────────────────────────────────────────────────
    emoji_chars = [c for c in corpus if _is_emoji_char(c)]
    features["emoji_density"] = len(emoji_chars) / total_chars
    features["emoji_diversity"] = (len(set(emoji_chars)) / len(emoji_chars)) if emoji_chars else 0.0

    # ── Lexical Richness ────────────────────────────────────────────────────
    if total_words > 0:
        # Type-Token Ratio (TTR)
        features["lexical_richness_ttr"] = len(word_counts) / total_words

        # Yule's K measure: 10^4 * (sum(f^2) - N) / N^2
        if total_words > 1:
            s2 = sum(c * c for c in word_counts.values())
            yule_k = 10000.0 * (s2 - total_words) / (total_words * total_words)
            features["lexical_richness_yule_k"] = max(0.0, float(yule_k))
        else:
            features["lexical_richness_yule_k"] = 0.0
    else:
        features["lexical_richness_ttr"] = 0.0
        features["lexical_richness_yule_k"] = 0.0

    # ── Code Switching (Script mixing) ──────────────────────────────────────
    mixed_script_count = sum(1 for t in texts if len(_detect_scripts(t)) >= 2)
    features["code_switching_score"] = mixed_script_count / num_messages

    # ── Structural & Length Metrics ─────────────────────────────────────────
    total_line_breaks = sum(t.count("\n") for t in texts)
    features["avg_line_breaks"] = total_line_breaks / num_messages
    features["avg_message_length"] = sum(len(t) for t in texts) / num_messages
    features["avg_word_length"] = (sum(len(w) for w in words) / total_words) if total_words > 0 else 0.0

    # Sentence segmentation and length
    raw_sentences = re.split(r"[.!?\n]+", corpus)
    sentence_word_counts = [len(re.findall(r"\b\w+\b", s)) for s in raw_sentences]
    valid_sentence_word_counts = [cnt for cnt in sentence_word_counts if cnt > 0]
    if valid_sentence_word_counts:
        features["avg_sentence_length"] = sum(valid_sentence_word_counts) / len(valid_sentence_word_counts)
    else:
        features["avg_sentence_length"] = 0.0

    # ── Character Type Ratios ───────────────────────────────────────────────
    uppercase_count = sum(1 for c in corpus if c.isupper())
    digit_count = sum(1 for c in corpus if c.isdigit())
    special_char_count = sum(1 for c in corpus if not c.isalnum() and not c.isspace())

    features["uppercase_ratio"] = uppercase_count / total_chars
    features["digit_ratio"] = digit_count / total_chars
    features["special_char_ratio"] = special_char_count / total_chars

    # ── Utterance Shape Rates ───────────────────────────────────────────────
    # single-word utterances: messages with exactly 1 word token
    # single-sentence utterances: messages with exactly 1 sentence
    per_msg_word_counts = [len(re.findall(r"\b\w+\b", t)) for t in non_empty_texts]
    single_word_count = sum(1 for c in per_msg_word_counts if c == 1)
    features["single_word_utterance_rate"] = single_word_count / num_messages

    per_msg_sentence_counts = [
        max(1, len([s for s in re.split(r"[.!?\n]+", t) if s.strip()]))
        for t in non_empty_texts
    ]
    single_sentence_count = sum(1 for c in per_msg_sentence_counts if c == 1)
    features["single_sentence_utterance_rate"] = single_sentence_count / num_messages

    # Round all values for consistency
    return {k: round(float(v), 6) for k, v in features.items()}


def compare_linguistic_features(
    feat_a: Dict[str, Any],
    feat_b: Dict[str, Any],
) -> Tuple[float, float]:
    """Compare two linguistic feature dicts using cosine similarity on numeric features.

    Args:
        feat_a: First feature dict.
        feat_b: Second feature dict.

    Returns:
        Tuple of (similarity_score 0-1, confidence 0-1).
        Confidence is based on how many features are present in both dicts.
    """
    if not isinstance(feat_a, dict) or not isinstance(feat_b, dict) or not feat_a or not feat_b:
        return (0.0, 0.0)

    # Extract shared numeric keys
    numeric_keys_a = {k for k, v in feat_a.items() if isinstance(v, (int, float))}
    numeric_keys_b = {k for k, v in feat_b.items() if isinstance(v, (int, float))}
    common_keys = sorted(numeric_keys_a & numeric_keys_b)
    all_keys = numeric_keys_a | numeric_keys_b

    if not common_keys:
        return (0.0, 0.0)

    vec_a = [float(feat_a[k]) for k in common_keys]
    vec_b = [float(feat_b[k]) for k in common_keys]

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0.0 or norm_b == 0.0:
        return (0.0, 0.0)

    raw_cos = dot / (norm_a * norm_b)
    sim = max(0.0, min(1.0, raw_cos))

    # Calculate confidence based on key coverage relative to canonical feature space
    total_expected = max(len(all_keys), len(DEFAULT_LINGUISTIC_FEATURES))
    key_coverage = len(common_keys) / total_expected if total_expected > 0 else 0.0
    confidence = max(0.0, min(1.0, key_coverage))

    return (round(sim, 4), round(confidence, 4))
