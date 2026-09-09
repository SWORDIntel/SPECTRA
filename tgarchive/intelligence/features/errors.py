"""
SPECTRA Intelligence — Error & Typo Feature Extraction (L2 Typo Fingerprint)
=============================================================================
Extracts typo frequencies, error mechanisms (deletion, insertion, substitution,
transposition, adjacent QWERTY keys), word merge/split rates, missing apostrophes,
repeated character distributions, and typo signature mappings.

Standard library only (re, collections, math, hashlib, unicodedata).
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# QWERTY physical keyboard key adjacency map (US/UK standard keyboard layout)
QWERTY_ADJACENCY: Dict[str, Set[str]] = {
    "a": {"q", "w", "s", "z"},
    "b": {"v", "g", "h", "n", " "},
    "c": {"x", "d", "f", "v", " "},
    "d": {"w", "e", "r", "s", "f", "x", "c"},
    "e": {"w", "r", "s", "d", "f", "3", "4"},
    "f": {"e", "r", "t", "d", "g", "c", "v"},
    "g": {"r", "t", "y", "f", "h", "v", "b"},
    "h": {"t", "y", "u", "g", "j", "b", "n"},
    "i": {"u", "o", "j", "k", "l", "8", "9"},
    "j": {"y", "u", "i", "h", "k", "n", "m"},
    "k": {"u", "i", "o", "j", "l", "m"},
    "l": {"i", "o", "p", "k", ";"},
    "m": {"n", "j", "k", ",", " "},
    "n": {"b", "h", "j", "m", " "},
    "o": {"i", "p", "k", "l", "9", "0"},
    "p": {"o", "l", "[", "-", "0"},
    "q": {"w", "a", "s", "1", "2"},
    "r": {"e", "t", "d", "f", "g", "4", "5"},
    "s": {"q", "w", "e", "a", "d", "z", "x"},
    "t": {"r", "y", "f", "g", "h", "5", "6"},
    "u": {"y", "i", "h", "j", "k", "7", "8"},
    "v": {"c", "f", "g", "b", " "},
    "w": {"q", "e", "a", "s", "d", "2", "3"},
    "x": {"z", "s", "d", "c"},
    "y": {"t", "u", "g", "h", "j", "6", "7"},
    "z": {"a", "s", "x"},
}

# Ranked common words list (lower index = higher frequency in English)
COMMON_WORDS_RANKED: Tuple[str, ...] = (
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
    "or", "an", "will", "my", "one", "all", "would", "there", "their", "what",
    "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
    "when", "make", "can", "like", "time", "no", "just", "him", "know", "take",
    "people", "into", "year", "your", "good", "some", "could", "them", "see", "other",
    "than", "then", "now", "look", "only", "come", "its", "over", "think", "also",
    "back", "after", "use", "two", "how", "our", "work", "first", "well", "way",
    "even", "new", "want", "because", "any", "these", "give", "day", "most", "us",
    "is", "are", "was", "were", "been", "has", "had", "does", "did", "doing",
    "am", "should", "must", "might", "may", "here", "where", "why", "again", "further",
    "before", "down", "between", "both", "through", "during", "under", "while", "never", "same",
    "another", "much", "many", "such", "very", "own", "too", "great", "small", "every",
    "found", "still", "name", "sentence", "man", "help", "line", "right", "mean",
    "old", "tell", "boy", "follow", "came", "show", "around", "farm", "three",
    "set", "put", "end", "large", "big", "turn", "ask", "went", "men",
    "read", "need", "land", "different", "home", "move", "try", "kind", "hand",
    "picture", "change", "off", "play", "spell", "air", "away", "house", "point",
    "page", "letter", "mother", "answer", "study", "learn", "world", "high",
    "near", "add", "food", "below", "country", "plant", "last", "school", "father",
    "keep", "tree", "start", "city", "earth", "eye", "light", "thought", "head",
    "story", "saw", "left", "few", "along", "close", "something", "seem",
    "next", "hard", "open", "example", "begin", "life", "always", "those", "paper",
    "together", "got", "group", "often", "run", "important", "until", "children", "side",
    "feet", "car", "mile", "night", "walk", "white", "sea", "began", "grow",
    "took", "river", "four", "carry", "state", "once", "book", "hear", "stop",
    "without", "second", "late", "miss", "idea", "enough", "eat", "face", "watch",
    "far", "really", "almost", "let", "above", "girl", "sometimes", "mountain", "cut",
    "young", "talk", "soon", "list", "song", "being", "leave", "family", "it's",
    "don't", "can't", "won't", "i'm", "you're", "they're", "we're", "that's",
    "what's", "there's", "here's", "didn't", "doesn't", "isn't", "aren't", "wasn't",
)

COMMON_WORDS_RANK_MAP: Dict[str, int] = {w: i for i, w in enumerate(COMMON_WORDS_RANKED)}
COMMON_WORDS: Set[str] = set(COMMON_WORDS_RANKED)

# Extended dictionary of common English words (vocabulary, colors, animals, verbs, nouns)
# used to verify valid words so standard English terms aren't falsely flagged as misspellings
VALID_ENGLISH_WORDS: Set[str] = COMMON_WORDS | {
    "quick", "brown", "fox", "foxes", "jump", "jumps", "jumped", "jumping",
    "lazy", "dog", "dogs", "bark", "barks", "barked", "barking", "loud", "loudly",
    "moon", "sun", "star", "stars", "sky", "blue", "red", "green", "black", "yellow",
    "weather", "cold", "hot", "warm", "rain", "snow", "wind", "screen", "park",
    "active", "member", "team", "channel", "message", "test", "testing", "energy",
    "funny", "cool", "agree", "busy", "check", "clean", "send", "sent", "look",
    "looking", "looked", "post", "posts", "posted", "read", "reading", "write",
    "writing", "wrote", "code", "system", "data", "file", "files", "server",
    "user", "users", "chat", "chats", "online", "offline", "level", "price",
    "cost", "costs", "buy", "sell", "sold", "order", "orders", "group", "groups",
    "link", "links", "site", "sites", "web", "page", "pages", "admin", "bot",
    "hello", "hey", "hi", "yes", "yeah", "yep", "no", "nope", "okay", "ok",
    "please", "thanks", "thank", "sorry", "welcome", "friend", "friends",
    "good", "better", "best", "bad", "worse", "worst", "great", "nice", "fine",
    "real", "true", "false", "sure", "maybe", "probably", "definitely",
    "today", "yesterday", "tomorrow", "now", "later", "soon", "never", "always",
    "morning", "afternoon", "evening", "night", "week", "month", "year",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "zero", "one", "two", "three",
    "four", "five", "six", "seven", "eight", "nine", "ten", "hundred", "thousand",
    "million", "billion", "first", "second", "third", "last", "next", "previous",
    "start", "started", "stop", "stopped", "finish", "finished", "open", "opened",
    "close", "closed", "run", "running", "ran", "walk", "walking", "walked",
    "talk", "talking", "talked", "tell", "telling", "told", "ask", "asking", "asked",
    "give", "giving", "gave", "given", "take", "taking", "took", "taken",
    "find", "finding", "found", "think", "thinking", "thought", "know", "knowing", "knew",
    "known", "feel", "feeling", "felt", "leave", "leaving", "left", "keep", "keeping", "kept",
    "hold", "holding", "held", "bring", "bringing", "brought", "begin", "beginning", "began",
    "begun", "stand", "standing", "stood", "hear", "hearing", "heard", "let", "letting",
    "help", "helping", "helped", "show", "showing", "showed", "shown", "play", "playing", "played",
}

# Common words missing an apostrophe -> canonical correction
APOSTROPHE_OMISSIONS: Dict[str, str] = {
    "dont": "don't",
    "cant": "can't",
    "wont": "won't",
    "didnt": "didn't",
    "doesnt": "doesn't",
    "isnt": "isn't",
    "arent": "aren't",
    "wasnt": "wasn't",
    "werent": "weren't",
    "hasnt": "hasn't",
    "havent": "haven't",
    "hadnt": "hadn't",
    "couldnt": "couldn't",
    "shouldnt": "shouldn't",
    "wouldnt": "wouldn't",
    "theyre": "they're",
    "youre": "you're",
    "weve": "we've",
    "theyve": "they've",
    "youve": "you've",
    "ill": "i'll",
    "youll": "you'll",
    "theyll": "they'll",
    "hell": "he'll",
    "shell": "she'll",
    "thats": "that's",
    "whats": "what's",
    "theres": "there's",
    "heres": "here's",
    "im": "i'm",
    "ive": "i've",
    "lets": "let's",
}

# Common multi-syllable words for split/space insertion detection
COMPOUND_CANDIDATES: Set[str] = {
    "because", "always", "together", "without", "something", "into", "before",
    "after", "another", "between", "during", "around", "different", "picture",
    "almost", "sometimes", "important", "children", "enough", "today", "tomorrow",
    "forever", "under", "behind", "outside", "inside", "anyone", "everyone", "someone",
}

# Regex for repeated characters (3 or more consecutive identical letters)
REPEATED_CHARS_PATTERN = re.compile(r"([a-zA-Z])\1{2,}")

# Regex for chat typo correction markers (e.g. *word, word*, s/typo/fix/)
CORRECTION_PATTERN = re.compile(
    r"(?:\*\b[a-zA-Z]+\b|\b[a-zA-Z]+\*\b|^\*[a-zA-Z]+|\bs/[a-zA-Z]+/[a-zA-Z]+)"
)

# Regex for sentence boundaries
SENTENCE_START_PATTERN = re.compile(r"(?:^|[.!?]\s+)([a-zA-Z])")

# Default flat dictionary for error features
DEFAULT_ERROR_FEATURES: Dict[str, Any] = {
    "misspelling_frequency": 0.0,
    "misspelling_dictionary": {},
    "edit_distance_error_distribution": {},
    "character_deletion_rate": 0.0,
    "character_insertion_rate": 0.0,
    "character_substitution_rate": 0.0,
    "character_transposition_rate": 0.0,
    "adjacent_keyboard_error_rate": 0.0,
    "space_omission_rate": 0.0,
    "space_insertion_rate": 0.0,
    "apostrophe_omission_rate": 0.0,
    "capitalization_error_rate": 0.0,
    "repeated_character_distribution": {},
    "word_merge_rate": 0.0,
    "word_split_rate": 0.0,
    "correction_after_typo_rate": 0.0,
    "typo_signature": {},
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


def _damerau_levenshtein(s1: str, s2: str) -> int:
    """Calculate Damerau-Levenshtein distance between two strings."""
    len1, len2 = len(s1), len(s2)
    d = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(len1 + 1):
        d[i][0] = i
    for j in range(len2 + 1):
        d[0][j] = j
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,        # deletion
                d[i][j - 1] + 1,        # insertion
                d[i - 1][j - 1] + cost  # substitution
            )
            if (
                i > 1
                and j > 1
                and s1[i - 1] == s2[j - 2]
                and s1[i - 2] == s2[j - 1]
            ):
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)  # transposition
    return d[len1][len2]


def _is_transposition(w: str, c: str) -> bool:
    """Check if w is an adjacent character transposition of c."""
    if len(w) != len(c):
        return False
    diffs = [i for i in range(len(w)) if w[i] != c[i]]
    return (
        len(diffs) == 2
        and diffs[1] == diffs[0] + 1
        and w[diffs[0]] == c[diffs[1]]
        and w[diffs[1]] == c[diffs[0]]
    )


def _find_closest_common_word(word: str, max_dist: int = 2) -> Optional[Tuple[str, int]]:
    """Find the closest valid common word within max_dist Damerau-Levenshtein distance,
    ranked by edit distance, error mechanism priority, and word frequency."""
    best_candidate: Optional[str] = None
    best_score: Tuple[int, int, int] = (max_dist + 1, 99, 999999)

    word_len = len(word)
    for rank, common in enumerate(COMMON_WORDS_RANKED):
        # Optimization: prune by length difference
        if abs(len(common) - word_len) > max_dist:
            continue
        dist = _damerau_levenshtein(word, common)
        if dist > max_dist or dist == 0:
            continue

        # Priority penalty: transpositions are most common typos (0), then length-diff 1 (1), then substitutions (2)
        if _is_transposition(word, common):
            err_priority = 0
        elif abs(word_len - len(common)) == 1:
            err_priority = 1
        else:
            err_priority = 2

        score = (dist, err_priority, rank)
        if score < best_score:
            best_score = score
            best_candidate = common

    if best_candidate is not None and best_score[0] <= max_dist:
        return (best_candidate, best_score[0])
    return None


def extract_error_features(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract L2 typo and error fingerprint features from messages.

    Args:
        messages: List of message dictionaries, each containing 'content' or 'text'.

    Returns:
        JSON-serializable dictionary with 17 error and typo features:
        - misspelling_frequency (float)
        - misspelling_dictionary (dict, top-100)
        - edit_distance_error_distribution (dict)
        - character_deletion_rate (float)
        - character_insertion_rate (float)
        - character_substitution_rate (float)
        - character_transposition_rate (float)
        - adjacent_keyboard_error_rate (float)
        - space_omission_rate (float)
        - space_insertion_rate (float)
        - apostrophe_omission_rate (float)
        - capitalization_error_rate (float)
        - repeated_character_distribution (dict, top-50)
        - word_merge_rate (float)
        - word_split_rate (float)
        - correction_after_typo_rate (float)
        - typo_signature (dict, top-50)
    """
    if not messages:
        return dict(DEFAULT_ERROR_FEATURES)

    texts = [_extract_text(m) for m in messages]
    non_empty_texts = [t for t in texts if t]
    num_messages = len(messages)

    if not non_empty_texts:
        return dict(DEFAULT_ERROR_FEATURES)

    corpus = "\n".join(non_empty_texts)
    raw_tokens = re.findall(r"\b[a-zA-Z']+\b", corpus)
    total_words = len(raw_tokens)

    if total_words == 0:
        return dict(DEFAULT_ERROR_FEATURES)

    words = [t.lower() for t in raw_tokens]

    # Accumulators
    misspelling_counts: Counter[str] = Counter()
    edit_distance_counts: Counter[str] = Counter()
    typo_signatures: Counter[str] = Counter()
    repeated_chars_counts: Counter[str] = Counter()

    deletions = 0
    insertions = 0
    substitutions = 0
    transpositions = 0
    adjacent_keyboard_errors = 0
    space_omissions = 0
    space_insertions = 0
    apostrophe_omissions = 0
    capitalization_errors = 0
    typo_corrections = 0

    # ── 1. Repeated Characters Distribution (top-50) ────────────────────────
    for m in REPEATED_CHARS_PATTERN.finditer(corpus):
        matched = m.group(0).lower()
        repeated_chars_counts[matched] += 1

    # ── 2. Misspelling & Edit Distance Analysis ──────────────────────────────
    for w in words:
        # Check apostrophe omission first (e.g. 'dont' -> "don't")
        if w in APOSTROPHE_OMISSIONS:
            apostrophe_omissions += 1
            corr = APOSTROPHE_OMISSIONS[w]
            misspelling_counts[f"{w}->{corr}"] += 1
            typo_signatures[f"{corr}->{w}"] += 1
            deletions += 1
            edit_distance_counts["1"] += 1
            continue

        # Skip known valid English words
        clean_w = w.replace("'", "")
        if w in VALID_ENGLISH_WORDS or clean_w in VALID_ENGLISH_WORDS:
            continue

        # Check for space omission / word merge: e.g. "ofthe", "inthat"
        w_len = len(w)
        is_merge = False
        if w_len >= 4:
            for split_idx in range(2, w_len - 1):
                part1, part2 = w[:split_idx], w[split_idx:]
                if part1 in COMMON_WORDS and part2 in COMMON_WORDS:
                    space_omissions += 1
                    is_merge = True
                    misspelling_counts[f"{w}->{part1} {part2}"] += 1
                    typo_signatures[f"{part1} {part2}->{w}"] += 1
                    break
        if is_merge:
            continue

        # Look for closest common word with edit distance <= 2
        match_result = _find_closest_common_word(w, max_dist=2)
        if match_result is not None:
            target_word, dist = match_result
            misspelling_counts[f"{w}->{target_word}"] += 1
            edit_distance_counts[str(dist)] += 1
            typo_signatures[f"{target_word}->{w}"] += 1

            # Classify specific error mechanisms
            w_len_m = len(w)
            t_len = len(target_word)

            if w_len_m == t_len:
                # Check for adjacent transposition (e.g. "teh" for "the")
                diff_indices = [idx for idx in range(w_len_m) if w[idx] != target_word[idx]]
                if (
                    len(diff_indices) == 2
                    and diff_indices[1] == diff_indices[0] + 1
                    and w[diff_indices[0]] == target_word[diff_indices[1]]
                    and w[diff_indices[1]] == target_word[diff_indices[0]]
                ):
                    transpositions += 1
                    idx0, idx1 = diff_indices[0], diff_indices[1]
                    typo_signatures[f"{target_word[idx0:idx1+1]}->{w[idx0:idx1+1]}"] += 1
                else:
                    # Substitutions
                    for idx in diff_indices:
                        substitutions += 1
                        char_typed = w[idx]
                        char_target = target_word[idx]
                        typo_signatures[f"{char_target}->{char_typed}"] += 1
                        if char_typed in QWERTY_ADJACENCY.get(char_target, set()):
                            adjacent_keyboard_errors += 1
            elif w_len_m < t_len:
                # Deletion (user omitted letters)
                deletions += (t_len - w_len_m)
            else:
                # Insertion (user inserted extra letters)
                insertions += (w_len_m - t_len)

    # ── 3. Space Insertion (Word Split) Detection ────────────────────────────
    for t in non_empty_texts:
        t_words = re.findall(r"\b[a-zA-Z]+\b", t.lower())
        for i in range(len(t_words) - 1):
            w1, w2 = t_words[i], t_words[i + 1]
            combined = w1 + w2
            if combined in COMPOUND_CANDIDATES or (
                len(w1) >= 2 and len(w2) >= 2 and combined in COMMON_WORDS
            ):
                space_insertions += 1
                typo_signatures[f"{combined}->{w1} {w2}"] += 1

    # ── 4. Capitalization Errors ─────────────────────────────────────────────
    for t in non_empty_texts:
        # Caps lock reversal / accidental caps: e.g. "tHIS", "hELLO"
        for _ in re.finditer(r"\b[a-z][A-Z]{2,}\b", t):
            capitalization_errors += 1

        # Mid-word uppercase: e.g. "tHe", "wOrk", "sOmething"
        for _ in re.finditer(r"\b[a-z]+[A-Z]+[a-z]+\b", t):
            capitalization_errors += 1

        # Missing sentence initial capitalization
        for m in SENTENCE_START_PATTERN.finditer(t):
            first_char = m.group(1)
            if first_char.islower():
                capitalization_errors += 1

    # ── 5. Correction After Typo Rate ────────────────────────────────────────
    for t in non_empty_texts:
        corrections = CORRECTION_PATTERN.findall(t)
        typo_corrections += len(corrections)

    # ── 6. Build Normalized Output Dict ──────────────────────────────────────
    total_misspellings = sum(misspelling_counts.values())
    total_typo_sigs = sum(typo_signatures.values())
    total_edit_dists = sum(edit_distance_counts.values())

    edit_dist_distrib = (
        {
            k: round(cnt / total_edit_dists, 6)
            for k, cnt in sorted(edit_distance_counts.items())
        }
        if total_edit_dists > 0
        else {}
    )

    typo_sig_distrib = (
        {
            sig: round(cnt / total_typo_sigs, 6)
            for sig, cnt in typo_signatures.most_common(50)
        }
        if total_typo_sigs > 0
        else {}
    )

    features: Dict[str, Any] = {
        "misspelling_frequency": round(total_misspellings / total_words, 6),
        "misspelling_dictionary": dict(misspelling_counts.most_common(100)),
        "edit_distance_error_distribution": edit_dist_distrib,
        "character_deletion_rate": round(deletions / total_words, 6),
        "character_insertion_rate": round(insertions / total_words, 6),
        "character_substitution_rate": round(substitutions / total_words, 6),
        "character_transposition_rate": round(transpositions / total_words, 6),
        "adjacent_keyboard_error_rate": round(adjacent_keyboard_errors / total_words, 6),
        "space_omission_rate": round(space_omissions / total_words, 6),
        "space_insertion_rate": round(space_insertions / total_words, 6),
        "apostrophe_omission_rate": round(apostrophe_omissions / total_words, 6),
        "capitalization_error_rate": round(capitalization_errors / total_words, 6),
        "repeated_character_distribution": dict(repeated_chars_counts.most_common(50)),
        "word_merge_rate": round(space_omissions / total_words, 6),
        "word_split_rate": round(space_insertions / total_words, 6),
        "correction_after_typo_rate": round(typo_corrections / num_messages, 6),
        "typo_signature": typo_sig_distrib,
    }

    return features


def compare_error_features(
    feat_a: Dict[str, Any],
    feat_b: Dict[str, Any],
) -> Tuple[float, float]:
    """Compare two typo/error feature profiles using weighted similarity and Jaccard overlap.

    Args:
        feat_a: First error feature dict.
        feat_b: Second error feature dict.

    Returns:
        Tuple of (similarity_score 0-1, confidence 0-1).
    """
    if not isinstance(feat_a, dict) or not isinstance(feat_b, dict) or not feat_a or not feat_b:
        return (0.0, 0.0)

    # Scalar rate comparison via relative closeness
    scalar_keys = [
        ("misspelling_frequency", 0.15),
        ("character_deletion_rate", 0.10),
        ("character_insertion_rate", 0.10),
        ("character_substitution_rate", 0.10),
        ("character_transposition_rate", 0.10),
        ("adjacent_keyboard_error_rate", 0.10),
        ("space_omission_rate", 0.05),
        ("space_insertion_rate", 0.05),
        ("apostrophe_omission_rate", 0.05),
        ("capitalization_error_rate", 0.05),
    ]

    total_sim = 0.0
    total_weight = 0.0

    for key, weight in scalar_keys:
        val_a = float(feat_a.get(key, 0.0))
        val_b = float(feat_b.get(key, 0.0))
        denom = max(val_a, val_b, 0.001)
        closeness = max(0.0, 1.0 - abs(val_a - val_b) / denom)
        total_sim += closeness * weight
        total_weight += weight

    # Distribution comparison on typo signatures & repeated chars
    sig_a = feat_a.get("typo_signature", {})
    sig_b = feat_b.get("typo_signature", {})
    shared_sigs = 0

    if isinstance(sig_a, dict) and isinstance(sig_b, dict) and (sig_a or sig_b):
        shared_sigs = len(set(sig_a.keys()) & set(sig_b.keys()))
        all_sigs = set(sig_a.keys()) | set(sig_b.keys())
        intersection = sum(min(sig_a.get(k, 0.0), sig_b.get(k, 0.0)) for k in all_sigs)
        total_sim += intersection * 0.15
        total_weight += 0.15

    sim = min(1.0, max(0.0, total_sim / total_weight if total_weight > 0 else 0.0))
    # Confidence scales with error volume observed in profiles
    data_volume = (
        len(feat_a.get("misspelling_dictionary", {}))
        + len(feat_b.get("misspelling_dictionary", {}))
        + shared_sigs
    )
    confidence = min(1.0, max(0.0, 1.0 - (1.0 / (1.0 + 0.1 * data_volume))))

    return (round(sim, 4), round(confidence, 4))


__all__ = [
    "extract_error_features",
    "compare_error_features",
    "DEFAULT_ERROR_FEATURES",
    "QWERTY_ADJACENCY",
    "COMMON_WORDS",
]
