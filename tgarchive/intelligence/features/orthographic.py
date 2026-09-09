"""
SPECTRA Intelligence — Orthographic Feature Extraction (L1 Character Fingerprint)
==================================================================================
Extracts low-level character n-grams, word boundary n-grams, punctuation sequences,
repeated punctuation, capitalization transitions, and digit formatting patterns to
characterize an author's orthographic writing habits and keyboard mechanics.

Standard library only (re, collections, math, hashlib, unicodedata).
"""
from __future__ import annotations

import json
import logging
import re
import string
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Canonical punctuation characters
ASCII_PUNCTUATION: str = string.punctuation

# Punctuation sequence pattern: clusters, spaced punctuation, and special symbols
PUNCT_SEQUENCE_PATTERN = re.compile(
    r"(?:"
    r"[ \t]+[-—–~]+[ \t]+"                  # Spaced dashes/hyphens (e.g. ' - ', ' — ')
    r"|\([ \t]+|[ \t]+\)"                    # Spaced parentheses (e.g. '( ', ' )')
    r"|[ \t]+[:;]+[ \t]+"                    # Spaced colons/semicolons
    r"|[ \t]+/[ \t]+"                        # Spaced slashes
    r"|[^\w\s]{2,}"                          # 2+ consecutive punctuation (e.g. '...', '?!', ':::')
    r"|[—–…¿¡«»“”‘’•·]"                      # Standalone unicode/special punctuation
    r")"
)

# Repeated punctuation pattern: 2+ identical consecutive punctuation marks
REPEATED_PUNCT_PATTERN = re.compile(r"([^\w\s])\1+")

# Digit format pattern: currencies, hex, units, dates, times, versions, separators, ranges
DIGIT_FORMAT_PATTERN = re.compile(
    r"(?:"
    r"[£$€¥₹₽₿]\s*\d+(?:[.,]\d+)*"                   # Currencies: £30, $100.50, €50
    r"|\b0x[0-9a-fA-F]+\b"                            # Hex literals: 0xFF, 0x1A2B
    r"|\b\d+(?:[.,]\d+)*\s*(?:[kKMmGgTt][bB]?|[mM][sS]|[kK]m|[mM]h[zZ]|[gG]h[zZ]|[fF][pP][sS]|[pP][xX]|%|°[CcFf]?|[vV]|[wW]|[vV][aA][rR]|quid|pounds|dollars|euros|cents)\b"  # 16GB, 100ms, £30
    r"|\b\d{1,4}[/-]\d{1,2}[/-]\d{1,4}\b"            # Dates: 23/08/26, 2026-08-23, 15-01-2024
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\b"                 # Times: 14:30, 09:15:00
    r"|\bv?\d+\.\d+(?:\.\d+)*\b"                     # Version numbers: v1.2.3, 3.11.0
    r"|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"             # Thousands separators: 1,000,000
    r"|\b\d+\.\d+\b"                                 # Decimals: 3.14159
    r"|\b\d+\s*[-–~]\s*\d+\b"                        # Numeric ranges: 10-20, 10..20
    r"|\b\d+\b"                                       # Plain digits
    r")"
)

# Default flat dictionary for orthographic features
DEFAULT_ORTHOGRAPHIC_FEATURES: Dict[str, Any] = {
    "char_ngram_freq_2": {},
    "char_ngram_freq_3": {},
    "char_ngram_freq_4": {},
    "char_ngram_freq_5": {},
    "char_ngram_freq_6": {},
    "word_initial_char_ngrams": {},
    "word_final_char_ngrams": {},
    "punctuation_sequence_freq": {},
    "repeated_punctuation_patterns": {},
    "capitalization_transition_patterns": {},
    "digit_format_patterns": {},
}


def _extract_text(msg: Any) -> str:
    """Safely extract string text from a message dictionary or string."""
    if isinstance(msg, dict):
        text = msg.get("content")
        if text is None:
            text = msg.get("text")
        if text is None:
            text = msg.get("message")
        if text is None:
            text = msg.get("caption")
        if text is None:
            text = msg.get("raw_text")
        if text is None:
            return ""
        return str(text)
    if isinstance(msg, str):
        return msg
    return ""


def _char_case_category(char: str) -> str:
    """Classify a character into casing and type category for transition analysis."""
    if char.islower():
        return "lower"
    if char.isupper():
        return "Upper"
    if char.isdigit():
        return "digit"
    if char.isspace():
        return "space"
    if char in ASCII_PUNCTUATION or unicodedata.category(char).startswith("P"):
        return "punct"
    return "other"


def extract_orthographic_features(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract L1 character and orthographic fingerprint features from messages.

    Args:
        messages: List of message dictionaries, each containing 'content' or 'text'.

    Returns:
        JSON-serializable dictionary with 11 distribution dictionaries:
        - char_ngram_freq_2 .. char_ngram_freq_6 (top-200)
        - word_initial_char_ngrams (top-100, first 3 chars of words)
        - word_final_char_ngrams (top-100, last 3 chars of words)
        - punctuation_sequence_freq (top-100)
        - repeated_punctuation_patterns (top-50)
        - capitalization_transition_patterns (top-50)
        - digit_format_patterns (top-50)
    """
    if not messages:
        return dict(DEFAULT_ORTHOGRAPHIC_FEATURES)

    # Extract all non-empty texts
    texts = [_extract_text(m) for m in messages]
    non_empty_texts = [t for t in texts if t]

    if not non_empty_texts:
        return dict(DEFAULT_ORTHOGRAPHIC_FEATURES)

    corpus = "\n".join(non_empty_texts)
    total_chars = len(corpus)

    if total_chars == 0:
        return dict(DEFAULT_ORTHOGRAPHIC_FEATURES)

    corpus_lower = corpus.lower()
    features: Dict[str, Any] = dict(DEFAULT_ORTHOGRAPHIC_FEATURES)

    # ── 1. Character N-Gram Frequency Distributions (n=2..6, top-200) ────────
    for n in (2, 3, 4, 5, 6):
        feat_key = f"char_ngram_freq_{n}"
        if total_chars >= n:
            total_ngrams = total_chars - n + 1
            counts = Counter(corpus_lower[i:i + n] for i in range(total_ngrams))
            features[feat_key] = {
                ngram: round(cnt / total_ngrams, 6)
                for ngram, cnt in counts.most_common(200)
            }
        else:
            features[feat_key] = {}

    # ── 2. Word Boundary N-Grams (Initial & Final 3-grams, top-100) ──────────
    words = re.findall(r"\b\w+\b", corpus_lower)
    total_words = len(words)

    if total_words > 0:
        initial_counts = Counter(w[:3] for w in words if w)
        final_counts = Counter(w[-3:] for w in words if w)

        features["word_initial_char_ngrams"] = {
            prefix: round(cnt / total_words, 6)
            for prefix, cnt in initial_counts.most_common(100)
        }
        features["word_final_char_ngrams"] = {
            suffix: round(cnt / total_words, 6)
            for suffix, cnt in final_counts.most_common(100)
        }
    else:
        features["word_initial_char_ngrams"] = {}
        features["word_final_char_ngrams"] = {}

    # ── 3. Punctuation Sequence Frequencies (top-100) ───────────────────────
    punct_sequences: List[str] = []
    for t in non_empty_texts:
        punct_sequences.extend(PUNCT_SEQUENCE_PATTERN.findall(t))

    if punct_sequences:
        total_p_seqs = len(punct_sequences)
        seq_counts = Counter(punct_sequences)
        features["punctuation_sequence_freq"] = {
            seq: round(cnt / total_p_seqs, 6)
            for seq, cnt in seq_counts.most_common(100)
        }
    else:
        features["punctuation_sequence_freq"] = {}

    # ── 4. Repeated Punctuation Patterns (top-50) ───────────────────────────
    repeated_matches: List[str] = []
    for t in non_empty_texts:
        for m in REPEATED_PUNCT_PATTERN.finditer(t):
            repeated_matches.append(m.group(0))

    if repeated_matches:
        total_rep = len(repeated_matches)
        rep_counts = Counter(repeated_matches)
        features["repeated_punctuation_patterns"] = {
            pat: round(cnt / total_rep, 6)
            for pat, cnt in rep_counts.most_common(50)
        }
    else:
        features["repeated_punctuation_patterns"] = {}

    # ── 5. Capitalization Transition Patterns (top-50) ───────────────────────
    transitions: List[str] = []
    for t in non_empty_texts:
        t_len = len(t)
        for i in range(t_len - 1):
            cat1 = _char_case_category(t[i])
            cat2 = _char_case_category(t[i + 1])
            transitions.append(f"{cat1}->{cat2}")

    if transitions:
        total_trans = len(transitions)
        trans_counts = Counter(transitions)
        features["capitalization_transition_patterns"] = {
            pat: round(cnt / total_trans, 6)
            for pat, cnt in trans_counts.most_common(50)
        }
    else:
        features["capitalization_transition_patterns"] = {}

    # ── 6. Digit Format Patterns (top-50) ───────────────────────────────────
    digit_patterns: List[str] = []
    for t in non_empty_texts:
        digit_patterns.extend(DIGIT_FORMAT_PATTERN.findall(t))

    if digit_patterns:
        total_digits = len(digit_patterns)
        digit_counts = Counter(digit_patterns)
        features["digit_format_patterns"] = {
            pat: round(cnt / total_digits, 6)
            for pat, cnt in digit_counts.most_common(50)
        }
    else:
        features["digit_format_patterns"] = {}

    return features


def compare_orthographic_features(
    feat_a: Dict[str, Any],
    feat_b: Dict[str, Any],
) -> Tuple[float, float]:
    """Compare two orthographic feature profiles using distribution intersection.

    Args:
        feat_a: First feature dict.
        feat_b: Second feature dict.

    Returns:
        Tuple of (similarity_score 0-1, confidence 0-1).
    """
    if not isinstance(feat_a, dict) or not isinstance(feat_b, dict) or not feat_a or not feat_b:
        return (0.0, 0.0)

    distribution_keys = [
        ("char_ngram_freq_2", 0.10),
        ("char_ngram_freq_3", 0.15),
        ("char_ngram_freq_4", 0.15),
        ("char_ngram_freq_5", 0.10),
        ("char_ngram_freq_6", 0.05),
        ("word_initial_char_ngrams", 0.10),
        ("word_final_char_ngrams", 0.10),
        ("punctuation_sequence_freq", 0.10),
        ("repeated_punctuation_patterns", 0.05),
        ("capitalization_transition_patterns", 0.05),
        ("digit_format_patterns", 0.05),
    ]

    total_sim = 0.0
    active_weight = 0.0
    total_shared_items = 0

    for key, weight in distribution_keys:
        dist_a = feat_a.get(key, {})
        dist_b = feat_b.get(key, {})

        if isinstance(dist_a, dict) and isinstance(dist_b, dict) and (dist_a or dist_b):
            active_weight += weight
            shared_keys = set(dist_a.keys()) & set(dist_b.keys())
            total_shared_items += len(shared_keys)

            if dist_a and dist_b:
                # Histogram intersection / min-sum overlap
                all_items = set(dist_a.keys()) | set(dist_b.keys())
                intersection = sum(min(dist_a.get(k, 0.0), dist_b.get(k, 0.0)) for k in all_items)
                total_sim += intersection * weight

    if active_weight == 0.0:
        return (0.0, 0.0)

    sim = min(1.0, max(0.0, total_sim / active_weight))
    # Confidence scales with the volume of shared n-gram and pattern matches
    confidence = min(1.0, max(0.0, 1.0 - (1.0 / (1.0 + 0.05 * total_shared_items))))

    return (round(sim, 4), round(confidence, 4))


__all__ = [
    "extract_orthographic_features",
    "compare_orthographic_features",
    "DEFAULT_ORTHOGRAPHIC_FEATURES",
]
