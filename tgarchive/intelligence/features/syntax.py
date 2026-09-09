"""
Syntax Feature Extraction for Persona Attribution (L3 — Stdlib Approximation)
=============================================================================
Approximates Part-of-Speech (POS) tagging, syntactic structures, clause types,
voice (active/passive), sentence types, and characteristic POS sequences
using standard-library regex and rule-based heuristics (no spaCy/NLTK).

Standard library only (re, collections, math, statistics, string, logging).
"""
from __future__ import annotations

import logging
import math
import re
import string
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

# ── Universal POS Tag Set ───────────────────────────────────────────────────
# Canonical tags: NOUN, VERB, AUX, MODAL, DET, PREP, PRON, ADJ, ADV, CONJ, NUM, PUNCT, X

PUNCT_CHARS: Set[str] = set(string.punctuation) | {
    "—", "–", "…", "“", "”", "‘", "’", "«", "»", "•", "·",
}

NUMBER_WORDS: Set[str] = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
    "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
    "thousand", "million", "billion", "trillion", "first", "second", "third",
}

MODAL_WORDS: Set[str] = {
    "can", "could", "should", "would", "will", "must", "may", "might",
    "shall", "ought", "wo", "ca",
}

AUX_WORDS: Set[str] = {
    "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "having", "do", "does", "did", "am", "'s", "'re", "'m", "'ve",
    "'d", "ai", "get", "got", "gets", "getting",
}

DET_WORDS: Set[str] = {
    "the", "a", "an", "this", "that", "these", "those", "my", "your",
    "his", "her", "its", "our", "their", "each", "every", "either",
    "neither", "some", "any", "no", "all", "both", "half", "many",
    "much", "few", "several", "whose", "which", "what",
}

PREP_WORDS: Set[str] = {
    "in", "on", "at", "to", "for", "with", "by", "from", "of", "about",
    "into", "through", "over", "after", "before", "between", "under",
    "during", "without", "against", "within", "upon", "toward", "towards",
    "among", "throughout", "behind", "beyond", "above", "across", "onto",
    "off", "via", "per", "near", "despite", "except", "into", "unto",
}

PRON_WORDS: Set[str] = {
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
    "us", "them", "myself", "yourself", "himself", "herself", "itself",
    "ourselves", "themselves", "mine", "yours", "hers", "ours", "theirs",
    "who", "whom", "whoever", "whomever", "someone", "anyone", "everyone",
    "nobody", "no one", "somebody", "anybody", "everybody", "something",
    "anything", "everything", "nothing",
}

CONJ_WORDS: Set[str] = {
    "and", "but", "or", "nor", "so", "yet", "for", "although", "because",
    "since", "unless", "while", "whereas", "if", "though", "even though",
    "as", "whether", "once", "whenever", "wherever", "provided",
}

SUBORDINATE_CONJ_WORDS: Set[str] = {
    "because", "although", "since", "while", "whereas", "if", "unless",
    "though", "even though", "as long as", "provided", "after", "before",
    "once", "whenever", "wherever", "whether",
}

COORDINATE_CONJ_WORDS: Set[str] = {
    "and", "but", "or", "nor", "so", "yet", "for",
}

ADV_WORDS: Set[str] = {
    "not", "n't", "never", "always", "often", "sometimes", "usually",
    "seldom", "rarely", "very", "really", "just", "already", "still",
    "also", "even", "again", "then", "now", "here", "there", "why",
    "how", "when", "where", "soon", "quite", "almost", "rather",
    "perhaps", "maybe", "too", "well", "ever", "anyway", "somewhat",
    "together", "further", "back", "away", "only", "much", "more",
    "most", "less", "least", "please", "kindly",
}

ADJ_WORDS: Set[str] = {
    "good", "new", "first", "last", "long", "great", "little", "own",
    "other", "old", "right", "big", "high", "small", "large", "next",
    "early", "young", "important", "few", "public", "bad", "same",
    "able", "best", "better", "sure", "easy", "hard", "clear", "true",
    "real", "different", "fine", "full", "simple", "free", "strong",
    "special", "whole", "recent", "main", "major", "current", "late",
}

COMMON_VERB_WORDS: Set[str] = {
    "go", "get", "make", "know", "think", "take", "see", "come", "want",
    "look", "use", "find", "give", "tell", "work", "call", "try", "ask",
    "need", "feel", "become", "leave", "put", "mean", "keep", "let",
    "begin", "seem", "help", "talk", "turn", "start", "show", "hear",
    "play", "run", "move", "like", "live", "believe", "hold", "bring",
    "happen", "write", "provide", "sit", "stand", "lose", "pay", "meet",
    "include", "continue", "set", "learn", "change", "lead", "understand",
    "watch", "follow", "stop", "create", "speak", "read", "allow", "add",
    "spend", "grow", "open", "walk", "win", "offer", "remember", "love",
    "consider", "appear", "buy", "wait", "serve", "die", "send", "expect",
    "build", "stay", "fall", "cut", "reach", "kill", "remain", "check",
    "click", "download", "upload", "verify", "install", "test", "export",
    "import", "save", "load", "drop", "pass", "fail", "dump", "crack",
    "contain", "exist", "consist", "require", "support", "operate",
    "execute", "produce", "protect", "store", "process", "handle", "transmit",
    "receive", "generate", "detect", "extract", "deploy", "configure", "connect",
    "respond", "perform", "maintain", "prevent", "trigger", "halt", "terminate",
    "inspect", "investigate", "scan", "probe", "catch", "patch", "break",
    "said", "went", "got", "made", "knew", "thought", "took", "saw",
    "came", "gave", "told", "found", "felt", "left", "kept", "began",
    "seemed", "ran", "held", "brought", "wrote", "sat", "stood", "lost",
    "paid", "met", "led", "spoke", "spent", "grew", "won", "bought",
    "sent", "built", "fell",
}

IRREGULAR_PAST_PARTICIPLES: Set[str] = {
    "done", "made", "seen", "given", "taken", "written", "known",
    "broken", "built", "sent", "lost", "found", "chosen", "hidden",
    "killed", "executed", "created", "loaded", "dumped", "hacked",
    "compromised", "intercepted", "encrypted", "decrypted", "stolen",
    "patched", "discovered", "configured", "deployed", "extracted",
    "tested", "downloaded", "uploaded", "banned", "suspended", "sold",
    "purchased", "paid", "received", "caught", "struck", "bound",
}

# Canonical default output structure
DEFAULT_SYNTAX_FEATURES: Dict[str, Any] = {
    "pos_unigram_distribution": {},
    "pos_bigram_distribution": {},
    "sentence_type_distribution": {
        "declarative": 0.0,
        "question": 0.0,
        "imperative": 0.0,
        "fragment": 0.0,
    },
    "characteristic_pos_sequences": [],
    "question_rate": 0.0,
    "imperative_rate": 0.0,
    "declarative_rate": 0.0,
    "sentence_fragment_rate": 0.0,
    "run_on_sentence_rate": 0.0,
    "avg_clause_count": 0.0,
    "subordinate_clause_rate": 0.0,
    "coordinate_clause_rate": 0.0,
    "active_voice_rate": 0.0,
    "passive_voice_rate": 0.0,
    "avg_noun_phrase_length": 0.0,
    "avg_verb_phrase_length": 0.0,
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


def tag_token(token: str) -> str:
    """Assign a coarse POS tag to a token using lexicon lookup and suffix rules."""
    if not token:
        return "X"

    # Punctuation check
    if all(c in PUNCT_CHARS for c in token):
        return "PUNCT"

    # Numeric check
    clean_num = token.rstrip("%")
    if clean_num.isdigit() or re.match(r"^\d+(?:[.,]\d+)*$", clean_num):
        return "NUM"

    w = token.lower()
    if w in NUMBER_WORDS:
        return "NUM"

    # Function word lexicons
    if w in MODAL_WORDS:
        return "MODAL"
    if w in AUX_WORDS:
        return "AUX"
    if w in DET_WORDS:
        return "DET"
    if w in PRON_WORDS:
        return "PRON"
    if w in PREP_WORDS:
        return "PREP"
    if w in CONJ_WORDS:
        return "CONJ"
    if w in ADV_WORDS:
        return "ADV"
    if w in ADJ_WORDS:
        return "ADJ"
    if w in COMMON_VERB_WORDS or w in IRREGULAR_PAST_PARTICIPLES:
        return "VERB"

    # 3rd-person singular inflection check against verb lexicon
    if len(w) >= 3 and w.endswith("s") and not w.endswith("ss"):
        if w[:-1] in COMMON_VERB_WORDS:
            return "VERB"
        if w.endswith("es") and len(w) >= 4 and w[:-2] in COMMON_VERB_WORDS:
            return "VERB"
        if w.endswith("ies") and len(w) >= 4 and (w[:-3] + "y") in COMMON_VERB_WORDS:
            return "VERB"

    # Suffix-based morphological rules
    if len(w) >= 4:
        if w.endswith("ly"):
            return "ADV"
        if w.endswith("ing"):
            return "VERB"
        if w.endswith("ed"):
            return "VERB"

    if len(w) >= 5:
        if w.endswith(("tion", "sion", "ment", "ness", "ity", "ance", "ence", "ism", "ist", "ship", "hood")):
            return "NOUN"
        if w.endswith(("ous", "ful", "less", "able", "ible", "ive", "ish", "ary", "ic", "al")):
            return "ADJ"
        if w.endswith(("ize", "ise", "ate", "ify")):
            return "VERB"
        if w.endswith(("er", "or")):
            return "NOUN"

    # Fallback heuristic: alphabetic words default to NOUN
    if any(c.isalpha() for c in token):
        return "NOUN"

    return "X"


def tokenize_and_tag(sentence: str) -> List[Tuple[str, str]]:
    """Tokenize a sentence into words/punctuation and assign POS tags."""
    raw_tokens = re.findall(r"[A-Za-z0-9_'’]+|[^\w\s]", sentence)
    return [(tok, tag_token(tok)) for tok in raw_tokens if tok.strip()]


def _classify_sentence_type(
    sentence_text: str,
    tagged: List[Tuple[str, str]],
) -> str:
    """Classify sentence into question, imperative, declarative, or fragment."""
    clean_text = sentence_text.strip()
    if not clean_text or not tagged:
        return "fragment"

    # 1. Question: explicit '?' or interrogative opener
    if clean_text.endswith("?") or "?" in clean_text:
        return "question"

    words_only = [(w, tag) for w, tag in tagged if tag != "PUNCT"]
    if not words_only:
        return "fragment"

    first_word, first_tag = words_only[0]
    first_w_lower = first_word.lower()

    if first_w_lower in ("who", "what", "where", "when", "why", "how", "whose", "which"):
        return "question"

    # 2. Fragment: no finite verb / aux / modal present
    has_finite_verb = any(tag in ("VERB", "AUX", "MODAL") for _, tag in words_only)
    if not has_finite_verb:
        return "fragment"

    # 3. Imperative: starts with verb or command auxiliary with no subject
    if first_tag == "VERB":
        return "imperative"

    if first_w_lower in ("please", "kindly", "just", "always", "never") and len(words_only) > 1:
        if words_only[1][1] == "VERB":
            return "imperative"

    if first_w_lower in ("do", "don't") and len(words_only) > 1:
        if words_only[1][1] == "VERB" or (len(words_only) > 2 and words_only[2][1] == "VERB"):
            return "imperative"

    # 4. Declarative: standard statement
    return "declarative"


def _has_passive_voice(tagged: List[Tuple[str, str]]) -> bool:
    """Check if tagged sentence exhibits passive voice ('aux + past participle')."""
    words_only = [(w, tag) for w, tag in tagged if tag != "PUNCT"]
    n = len(words_only)

    for i in range(n - 1):
        w_i, tag_i = words_only[i]
        w_lower = w_i.lower()

        # Check for auxiliary (was, is, were, are, been, being, be, got, get)
        if tag_i == "AUX" or w_lower in ("was", "is", "were", "are", "been", "being", "be", "get", "got"):
            # Check next 1-2 tokens for past participle
            for offset in (1, 2):
                if i + offset < n:
                    target_w, target_tag = words_only[i + offset]
                    target_lower = target_w.lower()
                    if target_lower in IRREGULAR_PAST_PARTICIPLES or (
                        target_tag == "VERB" and target_lower.endswith("ed")
                    ):
                        return True
                    # If intermediary token is not an adverb, stop looking
                    if offset == 1 and target_tag != "ADV":
                        break
    return False


def _has_active_voice(tagged: List[Tuple[str, str]], is_passive: bool) -> bool:
    """Check if tagged sentence exhibits active voice structure."""
    if is_passive:
        return False
    words_only = [(w, tag) for w, tag in tagged if tag != "PUNCT"]
    has_verb = any(tag in ("VERB", "AUX", "MODAL") for _, tag in words_only)
    has_subject = any(tag in ("PRON", "NOUN", "DET") for _, tag in words_only)
    return has_verb and has_subject


def _extract_noun_phrases(tagged: List[Tuple[str, str]]) -> List[int]:
    """Find contiguous noun phrase lengths (tokens) matching [DET] [NUM]* [ADJ]* [NOUN]+."""
    words_only = [tag for _, tag in tagged if tag != "PUNCT"]
    lengths: List[int] = []
    i = 0
    n = len(words_only)

    while i < n:
        start = i
        if words_only[i] == "DET":
            i += 1
        while i < n and words_only[i] == "NUM":
            i += 1
        while i < n and words_only[i] == "ADJ":
            i += 1
        noun_count = 0
        while i < n and words_only[i] == "NOUN":
            noun_count += 1
            i += 1
        if noun_count > 0:
            lengths.append(i - start)
        else:
            if i == start:
                i += 1

    return lengths


def _extract_verb_phrases(tagged: List[Tuple[str, str]]) -> List[int]:
    """Find contiguous verb phrase lengths (tokens) matching [MODAL]* [AUX]* [ADV]* [VERB]+ [ADV]*."""
    words_only = [tag for _, tag in tagged if tag != "PUNCT"]
    lengths: List[int] = []
    i = 0
    n = len(words_only)

    while i < n:
        start = i
        while i < n and words_only[i] == "MODAL":
            i += 1
        while i < n and words_only[i] == "AUX":
            i += 1
        while i < n and words_only[i] == "ADV":
            i += 1
        verb_count = 0
        while i < n and words_only[i] == "VERB":
            verb_count += 1
            i += 1
        while i < n and words_only[i] == "ADV":
            i += 1
        if verb_count > 0:
            lengths.append(i - start)
        else:
            if i == start:
                i += 1

    return lengths


def extract_syntax_features(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract L3 syntax and structural features from message dicts.

    Args:
        messages: List of dicts, each with a 'content' or 'text' field.

    Returns:
        Dictionary containing syntax rates (floats rounded to 6 decimals),
        POS unigram/bigram distributions, sentence type distribution, and
        characteristic POS sequences.
    """
    if not messages:
        return {
            k: (
                {} if isinstance(v, dict) and k != "sentence_type_distribution"
                else (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v))
            )
            for k, v in DEFAULT_SYNTAX_FEATURES.items()
        }

    texts = [_extract_text(m) for m in messages]
    non_empty_texts = [t.strip() for t in texts if t and t.strip()]

    if not non_empty_texts:
        return {
            k: (
                {} if isinstance(v, dict) and k != "sentence_type_distribution"
                else (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v))
            )
            for k, v in DEFAULT_SYNTAX_FEATURES.items()
        }

    corpus = "\n".join(non_empty_texts)
    raw_sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+|\n+", corpus)
        if s.strip()
    ]

    if not raw_sentences:
        return {
            k: (
                {} if isinstance(v, dict) and k != "sentence_type_distribution"
                else (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v))
            )
            for k, v in DEFAULT_SYNTAX_FEATURES.items()
        }

    features: Dict[str, Any] = {
        k: (
            {} if isinstance(v, dict) and k != "sentence_type_distribution"
            else (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else 0.0))
        )
        for k, v in DEFAULT_SYNTAX_FEATURES.items()
    }

    # Tracking counters
    pos_unigram_counter: Counter[str] = Counter()
    pos_bigram_counter: Counter[str] = Counter()
    pos_seq_counter: Counter[str] = Counter()

    sentence_type_counts: Dict[str, int] = {
        "declarative": 0,
        "question": 0,
        "imperative": 0,
        "fragment": 0,
    }

    passive_count = 0
    active_count = 0
    run_on_count = 0
    subordinate_clause_count = 0
    coordinate_clause_count = 0
    clause_counts: List[int] = []

    noun_phrase_lengths: List[int] = []
    verb_phrase_lengths: List[int] = []

    total_sentences = len(raw_sentences)

    for sent in raw_sentences:
        tagged = tokenize_and_tag(sent)
        if not tagged:
            continue

        words_only_tags = [tag for _, tag in tagged if tag != "PUNCT"]
        words_only_tokens = [w.lower() for w, tag in tagged if tag != "PUNCT"]

        # POS Unigrams (non-punct)
        for tag in words_only_tags:
            pos_unigram_counter[tag] += 1

        # POS Bigrams (adjacent non-punct tag pairs)
        for i in range(len(words_only_tags) - 1):
            pos_bigram_counter[f"{words_only_tags[i]} {words_only_tags[i + 1]}"] += 1

        # Characteristic POS sequences (3-5 tag chains)
        for n in (3, 4, 5):
            for i in range(len(words_only_tags) - n + 1):
                pos_seq_counter[" ".join(words_only_tags[i:i + n])] += 1

        # Sentence Type
        stype = _classify_sentence_type(sent, tagged)
        sentence_type_counts[stype] += 1

        # Voice detection
        is_passive = _has_passive_voice(tagged)
        if is_passive:
            passive_count += 1
        if _has_active_voice(tagged, is_passive):
            active_count += 1

        # Clauses
        sub_count = sum(1 for w in words_only_tokens if w in SUBORDINATE_CONJ_WORDS)
        coord_count = sum(1 for w in words_only_tokens if w in COORDINATE_CONJ_WORDS)
        subordinate_clause_count += sub_count
        coordinate_clause_count += coord_count

        semi_count = sent.count(";")
        est_clauses = max(1, 1 + sub_count + coord_count + semi_count)
        clause_counts.append(est_clauses)

        # Run-on detection: excessively long (> 35 words) or comma-splice heuristic
        if len(words_only_tokens) > 35 or (
            "," in sent and sub_count == 0 and coord_count == 0 and len(words_only_tokens) > 20
        ):
            run_on_count += 1

        # Phrase length analysis
        noun_phrase_lengths.extend(_extract_noun_phrases(tagged))
        verb_phrase_lengths.extend(_extract_verb_phrases(tagged))

    # ── POS Distributions ───────────────────────────────────────────────────
    total_unigrams = sum(pos_unigram_counter.values())
    if total_unigrams > 0:
        features["pos_unigram_distribution"] = {
            tag: round(cnt / total_unigrams, 6)
            for tag, cnt in pos_unigram_counter.most_common(50)
        }

    total_bigrams = sum(pos_bigram_counter.values())
    if total_bigrams > 0:
        features["pos_bigram_distribution"] = {
            bg: round(cnt / total_bigrams, 6)
            for bg, cnt in pos_bigram_counter.most_common(50)
        }

    # Top-20 characteristic POS sequences
    features["characteristic_pos_sequences"] = [
        seq for seq, _ in pos_seq_counter.most_common(20)
    ]

    # ── Sentence Type Distribution & Rates ──────────────────────────────────
    if total_sentences > 0:
        features["sentence_type_distribution"] = {
            st: round(cnt / total_sentences, 6)
            for st, cnt in sentence_type_counts.items()
        }
        features["question_rate"] = round(sentence_type_counts["question"] / total_sentences, 6)
        features["imperative_rate"] = round(sentence_type_counts["imperative"] / total_sentences, 6)
        features["declarative_rate"] = round(sentence_type_counts["declarative"] / total_sentences, 6)
        features["sentence_fragment_rate"] = round(sentence_type_counts["fragment"] / total_sentences, 6)

        features["passive_voice_rate"] = round(passive_count / total_sentences, 6)
        features["active_voice_rate"] = round(active_count / total_sentences, 6)
        features["run_on_sentence_rate"] = round(run_on_count / total_sentences, 6)
        features["subordinate_clause_rate"] = round(subordinate_clause_count / total_sentences, 6)
        features["coordinate_clause_rate"] = round(coordinate_clause_count / total_sentences, 6)
        features["avg_clause_count"] = round(sum(clause_counts) / total_sentences, 6) if clause_counts else 0.0

    # ── Phrase Length Averages ──────────────────────────────────────────────
    if noun_phrase_lengths:
        features["avg_noun_phrase_length"] = round(sum(noun_phrase_lengths) / len(noun_phrase_lengths), 6)
    else:
        features["avg_noun_phrase_length"] = 0.0

    if verb_phrase_lengths:
        features["avg_verb_phrase_length"] = round(sum(verb_phrase_lengths) / len(verb_phrase_lengths), 6)
    else:
        features["avg_verb_phrase_length"] = 0.0

    return features


def compare_syntax_features(
    feat_a: Dict[str, Any],
    feat_b: Dict[str, Any],
) -> Tuple[float, float]:
    """Compare two syntax feature dicts using cosine similarity on POS distributions
    and sentence type metrics.

    Args:
        feat_a: First syntax feature dict.
        feat_b: Second syntax feature dict.

    Returns:
        Tuple of (similarity_score 0-1, confidence 0-1).
    """
    if not isinstance(feat_a, dict) or not isinstance(feat_b, dict) or not feat_a or not feat_b:
        return (0.0, 0.0)

    numeric_keys = [
        "question_rate", "imperative_rate", "declarative_rate",
        "sentence_fragment_rate", "run_on_sentence_rate", "avg_clause_count",
        "subordinate_clause_rate", "coordinate_clause_rate",
        "active_voice_rate", "passive_voice_rate",
        "avg_noun_phrase_length", "avg_verb_phrase_length",
    ]

    vec_a = [float(feat_a.get(k, 0.0)) for k in numeric_keys]
    vec_b = [float(feat_b.get(k, 0.0)) for k in numeric_keys]

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    rate_sim = 0.0
    if norm_a > 0.0 and norm_b > 0.0:
        rate_sim = max(0.0, min(1.0, dot / (norm_a * norm_b)))

    # POS unigram distribution similarity (cosine over shared POS tags)
    unigrams_a = feat_a.get("pos_unigram_distribution", {})
    unigrams_b = feat_b.get("pos_unigram_distribution", {})
    all_tags = sorted(set(unigrams_a.keys()) | set(unigrams_b.keys()))

    pos_sim = 0.0
    if all_tags:
        u_vec_a = [float(unigrams_a.get(t, 0.0)) for t in all_tags]
        u_vec_b = [float(unigrams_b.get(t, 0.0)) for t in all_tags]
        u_dot = sum(a * b for a, b in zip(u_vec_a, u_vec_b))
        u_norm_a = math.sqrt(sum(a * a for a in u_vec_a))
        u_norm_b = math.sqrt(sum(b * b for b in u_vec_b))
        if u_norm_a > 0.0 and u_norm_b > 0.0:
            pos_sim = max(0.0, min(1.0, u_dot / (u_norm_a * u_norm_b)))

    # Sequence overlap
    seqs_a = set(feat_a.get("characteristic_pos_sequences", []))
    seqs_b = set(feat_b.get("characteristic_pos_sequences", []))
    seq_sim = len(seqs_a & seqs_b) / len(seqs_a | seqs_b) if (seqs_a | seqs_b) else 0.0

    similarity = 0.45 * pos_sim + 0.35 * rate_sim + 0.20 * seq_sim

    non_zero_a = sum(1 for v in vec_a if v > 0) + len(unigrams_a)
    non_zero_b = sum(1 for v in vec_b if v > 0) + len(unigrams_b)
    avg_evidence = (non_zero_a + non_zero_b) / 2.0
    confidence = max(0.0, min(1.0, 1.0 - math.exp(-0.12 * avg_evidence)))

    return (round(similarity, 4), round(confidence, 4))


__all__ = [
    "extract_syntax_features",
    "compare_syntax_features",
    "tag_token",
    "tokenize_and_tag",
    "DEFAULT_SYNTAX_FEATURES",
]
