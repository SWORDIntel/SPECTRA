"""
Discourse and Rhetorical Feature Extraction for Persona Attribution (L4)
========================================================================
Extracts discourse markers, rhetorical devices, argumentation patterns, sentence
openers/closers, initial/final phrases, and n-gram distributions from messages
to characterize an actor's discourse habits.

Standard library only (re, collections, math, statistics, hashlib, logging).
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

# ── Discourse Marker Lexicons ────────────────────────────────────────────────

HEDGE_PHRASES: Tuple[str, ...] = (
    "i think", "i believe", "i guess", "i suppose", "i feel", "i suspect",
    "i assume", "i presume", "sort of", "kind of", "it seems", "it appears",
    "it looks like", "might be", "could be", "may be", "in my opinion",
    "in my view", "to my knowledge", "as far as i know", "to be honest",
    "honestly speaking", "if i recall", "if i remember", "more or less",
)
HEDGE_WORDS: Tuple[str, ...] = (
    "maybe", "perhaps", "possibly", "probably", "apparently", "seemingly",
    "presumably", "arguably", "somewhat", "supposedly", "tentatively",
    "imo", "imho", "tbh", "afaik",
)

CERTAINTY_PHRASES: Tuple[str, ...] = (
    "of course", "without a doubt", "no doubt", "for sure", "for certain",
    "in fact", "make sure", "beyond doubt", "without question", "as a matter of fact",
)
CERTAINTY_WORDS: Tuple[str, ...] = (
    "definitely", "absolutely", "clearly", "obviously", "certainly",
    "undoubtedly", "surely", "unquestionably", "indeed", "plainly",
    "positively", "undeniably", "categorically", "100%", "guaranteed", "truly",
)

INTENSIFIER_PHRASES: Tuple[str, ...] = (
    "so much", "way too", "a lot", "super much", "by far",
)
INTENSIFIER_WORDS: Tuple[str, ...] = (
    "very", "really", "extremely", "super", "highly", "so", "totally",
    "utterly", "insanely", "hugely", "deeply", "immensely", "incredibly",
    "terribly", "awfully", "wildly", "exceptionally", "drastically",
    "intensely", "massively", "profoundly", "extraordinarily",
)

QUALIFIER_PHRASES: Tuple[str, ...] = (
    "kind of", "sort of", "a bit", "a little", "more or less",
    "to some extent", "to a degree", "up to a point", "in part", "at least",
)
QUALIFIER_WORDS: Tuple[str, ...] = (
    "fairly", "somewhat", "quite", "rather", "pretty", "slightly",
    "relatively", "moderately", "partially", "partly", "marginally",
)

SELF_CORRECTION_PHRASES: Tuple[str, ...] = (
    "i mean", "or rather", "wait no", "that is", "let me rephrase",
    "scratch that", "or better", "my bad", "i meant",
)
SELF_CORRECTION_WORDS: Tuple[str, ...] = (
    "actually", "well", "correction", "rather", "sorry", "oops",
)

CLARIFICATION_PHRASES: Tuple[str, ...] = (
    "that is", "in other words", "to clarify", "specifically",
    "that means", "put another way", "to be clear", "to be specific",
    "that is to say", "i.e.", "ie",
)
CLARIFICATION_WORDS: Tuple[str, ...] = (
    "namely", "specifically", "meaning",
)

REFORMULATION_PHRASES: Tuple[str, ...] = (
    "or rather", "i mean", "in other words", "more precisely",
    "to rephrase", "put simply", "better yet", "or better",
    "simply put", "rephrased",
)
REFORMULATION_WORDS: Tuple[str, ...] = (
    "actually", "alternatively",
)

EXAMPLE_PHRASES: Tuple[str, ...] = (
    "for example", "for instance", "such as", "like for example",
    "as an example", "case in point", "to illustrate", "e.g.", "eg",
)
EXAMPLE_WORDS: Tuple[str, ...] = ()

ANALOGY_PHRASES: Tuple[str, ...] = (
    "as if", "similar to", "akin to", "comparable to", "much like",
    "just like", "analogous to", "the same way", "as though", "in comparison to",
)
ANALOGY_WORDS: Tuple[str, ...] = (
    "like", "alike",
)

CONTRAST_PHRASES: Tuple[str, ...] = (
    "on the other hand", "even though", "in contrast", "in spite of",
    "on the contrary", "at the same time", "even so",
)
CONTRAST_WORDS: Tuple[str, ...] = (
    "but", "however", "although", "though", "yet", "nevertheless",
    "nonetheless", "whereas", "while", "conversely", "despite", "still", "instead",
)

CAUSAL_PHRASES: Tuple[str, ...] = (
    "as a result", "due to", "for this reason", "because of",
    "owing to", "in order to",
)
CAUSAL_WORDS: Tuple[str, ...] = (
    "because", "so", "therefore", "since", "thus", "hence",
    "consequently", "thereby", "accordingly",
)

ASIDE_PHRASES: Tuple[str, ...] = (
    "by the way", "btw", "incidentally", "as an aside", "side note",
    "on a side note", "parenthetically", "speaking of which", "off topic",
)
ASIDE_WORDS: Tuple[str, ...] = ()

PARENTHETICAL_PATTERN = re.compile(
    r"\([^)]*\)|\[[^\]]*\]|—[^—]+—|--[^-]+--",
    re.DOTALL,
)

# ── Quotation / Literary Reference Detection ────────────────────────────────
# Quotation marks (straight, curly, guillemet, CJK)
_QUOTATION_MARK_RE = re.compile(
    r'[\"“”‘’«»‹›『』「」《》〈〉]'
)
# Paired quotation extraction — captures text inside matching quotes
_PAIRED_DOUBLE_QUOTE_RE = re.compile(
    r'"([^"]{3,})"'           # straight double quotes
    r'|“([^”]{3,})”'          # curly double quotes
    r'|«([^»]{3,})»'          # guillemets
    r'|\u201c([^\u201d]{3,})\u201d'  # explicit unicode curly
)
_PAIRED_SINGLE_QUOTE_RE = re.compile(
    r"'([^']{3,})'"           # straight single quotes (apostrophe-bounded)
    r"|‘([^’]{3,})’"          # curly single quotes
)
# Block quote markdown (lines starting with >)
_BLOCK_QUOTE_RE = re.compile(r"^\s*>\s+(.+)$", re.MULTILINE)
# Attribution patterns after quotes: "— Author", "- Author", "(Author)"
_QUOTE_ATTRIBUTION_RE = re.compile(
    r'[—\-–]\s*([A-Z][a-zA-Z\.\s]{2,40})\s*$'
)

# Well-known literary/cultural quotation fragments (lowercased for matching)
# These are short, highly recognizable phrases that indicate literary/cultural
# reference behavior — a strong individuating signal.
LITERARY_QUOTATION_FRAGMENTS: Tuple[str, ...] = (
    "to be or not to be", "all the world's a stage", "et tu brute",
    "veni vidi vici", "alea iacta est", "carpe diem", "memento mori",
    "the die is cast", "crossing the rubicon", "achilles heel",
    "pandora's box", "midas touch", "sour grapes", "wolf in sheep's",
    "cry wolf", "boy who cried wolf", "emperor's new clothes",
    "ugly truth", "naked truth", "sword of damocles", "pyrrhic victory",
    "catch-22", "big brother is watching", "war is peace",
    "all animals are equal", "we are all equal",
    "i think therefore i am", "cogito ergo sum",
    "the unexamined life", "know thyself", "nothing in excess",
    "the only thing we have to fear", "ask not what your country",
    "i have a dream", "four score and seven",
    "it was the best of times", "it was the worst of times",
    "a tale of two cities", "it is a truth universally acknowledged",
    "call me ishmael", "in the beginning",
    "the road not taken", "two roads diverged",
    "do not go gentle", "rage rage against",
    "tyger tyger burning bright",
    "once upon a time", "happily ever after",
    "elementary my dear", "the game is afoot",
    "i'll be back", "hasta la vista", "make my day",
    "may the force be with you", "i am your father",
    "winter is coming", "you know nothing",
    "the night is dark and full",
)


def _compile_marker_regex(marker: str) -> re.Pattern:
    """Build a regex pattern with word boundaries for arbitrary markers."""
    escaped = re.escape(marker)
    prefix = r"\b" if marker[0].isalnum() else r"(?:^|\s|[.,;:!?\"'(\[])"
    suffix = r"\b" if marker[-1].isalnum() else r"(?:$|\s|[.,;:!?\"')\]])"
    return re.compile(prefix + escaped + suffix, re.IGNORECASE)


# Precompiled marker regex mappings
_MARKER_CATEGORIES: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "hedge": (HEDGE_PHRASES, HEDGE_WORDS),
    "certainty": (CERTAINTY_PHRASES, CERTAINTY_WORDS),
    "intensifier": (INTENSIFIER_PHRASES, INTENSIFIER_WORDS),
    "qualifier": (QUALIFIER_PHRASES, QUALIFIER_WORDS),
    "self_correction": (SELF_CORRECTION_PHRASES, SELF_CORRECTION_WORDS),
    "clarification": (CLARIFICATION_PHRASES, CLARIFICATION_WORDS),
    "reformulation": (REFORMULATION_PHRASES, REFORMULATION_WORDS),
    "example": (EXAMPLE_PHRASES, EXAMPLE_WORDS),
    "analogy": (ANALOGY_PHRASES, ANALOGY_WORDS),
    "contrast": (CONTRAST_PHRASES, CONTRAST_WORDS),
    "causal": (CAUSAL_PHRASES, CAUSAL_WORDS),
    "aside": (ASIDE_PHRASES, ASIDE_WORDS),
}

_COMPILED_MARKERS: Dict[str, List[Tuple[str, re.Pattern]]] = {
    cat: [
        (phrase, _compile_marker_regex(phrase))
        for phrase in phrases + words
    ]
    for cat, (phrases, words) in _MARKER_CATEGORIES.items()
}

# Canonical default output structure
DEFAULT_DISCOURSE_FEATURES: Dict[str, Any] = {
    "hedge_rate": 0.0,
    "certainty_marker_rate": 0.0,
    "intensifier_rate": 0.0,
    "qualifier_rate": 0.0,
    "self_correction_rate": 0.0,
    "parenthetical_rate": 0.0,
    "aside_rate": 0.0,
    "clarification_rate": 0.0,
    "reformulation_rate": 0.0,
    "example_introduction_rate": 0.0,
    "analogy_rate": 0.0,
    "contrast_marker_rate": 0.0,
    "causal_marker_rate": 0.0,
    "quotation_rate": 0.0,
    "literary_reference_rate": 0.0,
    "block_quote_rate": 0.0,
    "quoted_phrase_distribution": {},
    "literary_reference_distribution": {},
    "discourse_marker_distribution": {},
    "sentence_initial_phrase_distribution": {},
    "sentence_final_phrase_distribution": {},
    "sentence_openers": {},
    "sentence_closers": {},
    "trigrams": {},
    "fourgrams": {},
    "skipgrams": {},
}


def _extract_text(msg: Any) -> str:
    """Safely extract string text from a message dictionary or string."""
    if isinstance(msg, dict):
        text = (
            msg.get("content")
            or msg.get("text")
            or msg.get("message")
            or msg.get("caption")
            or msg.get("raw_text")
        )
        if text is None:
            return ""
        return str(text)
    if isinstance(msg, str):
        return msg
    return ""


def extract_discourse_features(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract L4 discourse and rhetorical features from message dicts.

    Args:
        messages: List of dicts, each with a 'content' or 'text' field.

    Returns:
        Dictionary containing discourse rates (floats rounded to 6 decimals)
        and capped frequency distributions (JSON-serializable dicts).
    """
    if not messages:
        return {
            k: ({} if isinstance(v, dict) else v)
            for k, v in DEFAULT_DISCOURSE_FEATURES.items()
        }

    texts = [_extract_text(m) for m in messages]
    non_empty_texts = [t.strip() for t in texts if t and t.strip()]

    if not non_empty_texts:
        return {
            k: ({} if isinstance(v, dict) else v)
            for k, v in DEFAULT_DISCOURSE_FEATURES.items()
        }

    corpus = "\n".join(non_empty_texts)
    words = re.findall(r"\b[a-zA-Z0-9_'’]+\b", corpus.lower())
    total_words = len(words)

    if total_words == 0:
        return {
            k: ({} if isinstance(v, dict) else v)
            for k, v in DEFAULT_DISCOURSE_FEATURES.items()
        }

    features: Dict[str, Any] = {
        k: ({} if isinstance(v, dict) else 0.0)
        for k, v in DEFAULT_DISCOURSE_FEATURES.items()
    }

    # ── 1. Discourse Marker Counting & Rates ────────────────────────────────
    marker_dist_counter: Counter[str] = Counter()
    category_counts: Dict[str, int] = {cat: 0 for cat in _COMPILED_MARKERS}

    for cat, marker_list in _COMPILED_MARKERS.items():
        for marker_str, pattern in marker_list:
            matches = pattern.findall(corpus)
            cnt = len(matches)
            if cnt > 0:
                category_counts[cat] += cnt
                marker_dist_counter[marker_str.lower()] += cnt

    # Parentheticals
    parenthetical_matches = PARENTHETICAL_PATTERN.findall(corpus)
    parenthetical_count = len(parenthetical_matches)

    # Rates normalized by total words
    features["hedge_rate"] = round(category_counts["hedge"] / total_words, 6)
    features["certainty_marker_rate"] = round(category_counts["certainty"] / total_words, 6)
    features["intensifier_rate"] = round(category_counts["intensifier"] / total_words, 6)
    features["qualifier_rate"] = round(category_counts["qualifier"] / total_words, 6)
    features["self_correction_rate"] = round(category_counts["self_correction"] / total_words, 6)
    features["parenthetical_rate"] = round(parenthetical_count / total_words, 6)
    features["aside_rate"] = round((category_counts["aside"] + parenthetical_count) / total_words, 6)
    features["clarification_rate"] = round(category_counts["clarification"] / total_words, 6)
    features["reformulation_rate"] = round(category_counts["reformulation"] / total_words, 6)
    features["example_introduction_rate"] = round(category_counts["example"] / total_words, 6)
    features["analogy_rate"] = round(category_counts["analogy"] / total_words, 6)
    features["contrast_marker_rate"] = round(category_counts["contrast"] / total_words, 6)
    features["causal_marker_rate"] = round(category_counts["causal"] / total_words, 6)

    # Top-100 discourse marker distribution
    features["discourse_marker_distribution"] = dict(marker_dist_counter.most_common(100))

    # ── 1b. Quotation & Literary Reference Detection ───────────────────────
    # Merge dynamic literary quotation expansions from the calibration loop
    try:
        from tgarchive.intelligence.lexicon_store import get_expanded_set
        _literary_fragments = get_expanded_set("quotations", frozenset(LITERARY_QUOTATION_FRAGMENTS))
    except ImportError:
        _literary_fragments = LITERARY_QUOTATION_FRAGMENTS

    # Count quotation marks (any kind)
    quotation_mark_count = len(_QUOTATION_MARK_RE.findall(corpus))
    features["quotation_rate"] = round(quotation_mark_count / max(total_words, 1), 6)

    # Extract paired quoted phrases
    quoted_phrases: List[str] = []
    for m in _PAIRED_DOUBLE_QUOTE_RE.finditer(corpus):
        phrase = next((g for g in m.groups() if g), "")
        if phrase:
            quoted_phrases.append(phrase.strip())
    for m in _PAIRED_SINGLE_QUOTE_RE.finditer(corpus):
        phrase = next((g for g in m.groups() if g), "")
        if phrase:
            quoted_phrases.append(phrase.strip())

    # Block quotes (markdown >)
    block_quote_matches = _BLOCK_QUOTE_RE.findall(corpus)
    features["block_quote_rate"] = round(len(block_quote_matches) / max(total_words, 1), 6)

    # Literary reference detection — substring match against known fragments
    corpus_lower_for_lit = corpus.lower()
    literary_refs: List[str] = []
    for fragment in _literary_fragments:
        if fragment in corpus_lower_for_lit:
            literary_refs.append(fragment)
    features["literary_reference_rate"] = round(
        len(literary_refs) / max(total_words, 1), 6
    )

    # Distributions
    if quoted_phrases:
        qp_counts = Counter(p[:100] for p in quoted_phrases)  # cap phrase length
        features["quoted_phrase_distribution"] = dict(qp_counts.most_common(50))
    if literary_refs:
        lr_counts = Counter(literary_refs)
        features["literary_reference_distribution"] = dict(lr_counts.most_common(50))

    # ── 2. Sentences, Openers, Closers, Initial/Final Phrases ──────────────
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", corpus)
    sentence_openers_counter: Counter[str] = Counter()
    sentence_closers_counter: Counter[str] = Counter()
    initial_phrases_counter: Counter[str] = Counter()
    final_phrases_counter: Counter[str] = Counter()

    trigrams_counter: Counter[str] = Counter()
    fourgrams_counter: Counter[str] = Counter()
    skipgrams_counter: Counter[str] = Counter()

    for sent in raw_sentences:
        sent_cleaned = sent.strip()
        if not sent_cleaned:
            continue
        sent_words = re.findall(r"\b[a-zA-Z0-9_'’]+\b", sent_cleaned.lower())
        if not sent_words:
            continue

        # Openers & closers (first/last word)
        sentence_openers_counter[sent_words[0]] += 1
        sentence_closers_counter[sent_words[-1]] += 1

        # Initial phrases (first 3 words)
        initial_phrases_counter[" ".join(sent_words[:3])] += 1

        # Final phrases (last 3 words)
        final_phrases_counter[" ".join(sent_words[-3:])] += 1

        # Trigrams (3 consecutive words)
        for i in range(len(sent_words) - 2):
            trigrams_counter[" ".join(sent_words[i:i + 3])] += 1

        # Fourgrams (4 consecutive words)
        for i in range(len(sent_words) - 3):
            fourgrams_counter[" ".join(sent_words[i:i + 4])] += 1

        # Skipgrams (skip-2-grams: word _ word with 1 or 2 intervening words)
        for i in range(len(sent_words) - 2):
            skipgrams_counter[f"{sent_words[i]} _ {sent_words[i + 2]}"] += 1
        for i in range(len(sent_words) - 3):
            skipgrams_counter[f"{sent_words[i]} _ {sent_words[i + 3]}"] += 1

    # Capped distributions
    features["sentence_initial_phrase_distribution"] = dict(initial_phrases_counter.most_common(100))
    features["sentence_final_phrase_distribution"] = dict(final_phrases_counter.most_common(100))
    features["sentence_openers"] = dict(sentence_openers_counter.most_common(100))
    features["sentence_closers"] = dict(sentence_closers_counter.most_common(100))
    features["trigrams"] = dict(trigrams_counter.most_common(200))
    features["fourgrams"] = dict(fourgrams_counter.most_common(100))
    features["skipgrams"] = dict(skipgrams_counter.most_common(100))

    return features


def compare_discourse_features(
    feat_a: Dict[str, Any],
    feat_b: Dict[str, Any],
) -> Tuple[float, float]:
    """Compare two discourse feature dicts using cosine similarity on numeric rates
    and Jaccard overlap on distribution keys.

    Args:
        feat_a: First discourse feature dict.
        feat_b: Second discourse feature dict.

    Returns:
        Tuple of (similarity_score 0-1, confidence 0-1).
    """
    if not isinstance(feat_a, dict) or not isinstance(feat_b, dict) or not feat_a or not feat_b:
        return (0.0, 0.0)

    numeric_keys = [
        k for k, v in DEFAULT_DISCOURSE_FEATURES.items()
        if isinstance(v, (int, float))
    ]

    vec_a = [float(feat_a.get(k, 0.0)) for k in numeric_keys]
    vec_b = [float(feat_b.get(k, 0.0)) for k in numeric_keys]

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    rate_sim = 0.0
    if norm_a > 0.0 and norm_b > 0.0:
        rate_sim = max(0.0, min(1.0, dot / (norm_a * norm_b)))

    # Distribution overlap across discourse markers, n-grams, openers
    dist_keys = [
        "discourse_marker_distribution",
        "sentence_openers",
        "sentence_closers",
        "trigrams",
    ]
    overlaps: List[float] = []
    for dk in dist_keys:
        d_a = set(feat_a.get(dk, {}).keys())
        d_b = set(feat_b.get(dk, {}).keys())
        if d_a or d_b:
            jaccard = len(d_a & d_b) / len(d_a | d_b) if (d_a | d_b) else 0.0
            overlaps.append(jaccard)

    dist_sim = (sum(overlaps) / len(overlaps)) if overlaps else 0.0

    if overlaps and (norm_a > 0.0 or norm_b > 0.0):
        similarity = 0.6 * rate_sim + 0.4 * dist_sim
    elif norm_a > 0.0 or norm_b > 0.0:
        similarity = rate_sim
    else:
        similarity = dist_sim

    # Confidence calculation based on non-zero feature presence
    non_zero_a = sum(1 for v in vec_a if v > 0) + sum(len(feat_a.get(k, {})) for k in dist_keys)
    non_zero_b = sum(1 for v in vec_b if v > 0) + sum(len(feat_b.get(k, {})) for k in dist_keys)
    avg_evidence = (non_zero_a + non_zero_b) / 2.0
    confidence = max(0.0, min(1.0, 1.0 - math.exp(-0.1 * avg_evidence)))

    return (round(similarity, 4), round(confidence, 4))


__all__ = [
    "extract_discourse_features",
    "compare_discourse_features",
    "DEFAULT_DISCOURSE_FEATURES",
]
