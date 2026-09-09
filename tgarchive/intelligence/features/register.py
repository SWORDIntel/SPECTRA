"""
SPECTRA Intelligence — L7 Register/Formality Module
===================================================
Extracts formality scores, slang, profanity, abbreviations, technical jargon,
colloquialisms, politeness markers, greetings, signoffs, and honorifics from messages
to characterize an actor's social register and conversational tone.

Standard library only (re, collections, statistics, math).
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Built-in lexical lists for register and tone analysis
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
    "rofl", "lol", "bop", "stan", "cap", "nocap", "mid", "opps", "slaps", "fire",
    "goat", "snack", "extra", "savage", "periodt", "cancelled",
})

PROFANITY_WORDS: frozenset[str] = frozenset({
    "fuck", "fucking", "fucked", "fucker", "fucks", "fuckin", "motherfucker",
    "shit", "shitty", "shitting", "bullshit", "damn", "damned", "damnit",
    "ass", "asshole", "asses", "bitch", "bitches", "bitching", "bastard",
    "bastards", "cunt", "cunts", "dick", "dicks", "dickhead", "piss", "pissed",
    "pissing", "crap", "crappy", "hell", "cock", "cocksucker", "slut", "whore",
    "prick", "twat", "wanker", "bollocks", "bugger", "douche", "douchebag",
    "dipshit", "dumbass", "jackass",
})

# Slurs are kept separate from general profanity because they carry different
# attribution weight: profanity is common, slur usage is highly individuating.
SLUR_WORDS: frozenset[str] = frozenset({
    "nigger", "niggers", "nigga", "niggas", "nig", "nigs",
    "faggot", "faggots", "fag", "fags", "faggotry",
    "tranny", "trannies", "troon", "troons",
    "retard", "retards", "retarded",
    "spic", "spics", "wetback", "wetbacks",
    "chink", "chinks", "gook", "gooks",
    "kike", "kikes", "heeb", "heebs",
    "raghead", "ragheads", "towelhead", "towelheads",
    "paki", "pakis",
    "coon", "coons",
    "wop", "wops",
    "mick", "micks",
    "kraut", "krauts",
    "jap", "japs",
    "injun", "injuns",
    "savage", "savages",  # context-dependent, but common as slur
    "ape", "apes",  # dehumanizing
    "subhuman",  # dehumanizing
})

ABBREVIATIONS: frozenset[str] = frozenset({
    "tbh", "ngl", "idk", "afaik", "imo", "imho", "fwiw", "iirc", "brb", "gtg",
    "g2g", "tldr", "btw", "fyi", "atm", "omg", "wtf", "wth", "smh", "rofl",
    "lmao", "lmfao", "lol", "thx", "pls", "plz", "ty", "np", "yw", "dm",
    "pm", "msg", "aka", "etc", "vs", "approx", "def", "prob", "govt", "info",
    "pov", "tbf", "tia", "tba", "tbd", "faq", "eta", "asap", "diy", "nsfw",
    "op", "gg", "gl", "hf", "rn", "fr", "wyd", "wbu", "hmu", "idm", "idc",
    "omw", "bc", "w/", "w/o", "b/c",
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
    "endianness", "buffer", "overflow", "heap", "stack", "pointer",
})

COLLOQUIALISMS: frozenset[str] = frozenset({
    "gonna", "wanna", "gotta", "kinda", "sorta", "dunno", "y'all", "ain't",
    "yeah", "yep", "nope", "nah", "cool", "awesome", "stuff", "thingy",
    "whatchamacallit", "hang out", "chill", "screw up", "mess up", "freak out",
    "hit up", "show up", "catch up", "no biggie", "no sweat", "no problem",
    "you bet", "for sure", "my bad", "heads up", "check it out", "no worries",
    "folks", "bunch", "tons", "bucks", "quid",
})

IDIOMS: Tuple[str, ...] = (
    "piece of cake", "bite the bullet", "break a leg", "hit the nail on the head",
    "under the weather", "spill the beans", "ball is in your court",
    "barking up the wrong tree", "cost an arm and a leg", "cut corners",
    "devil's advocate", "beat around the bush", "burn the midnight oil",
    "back to the drawing board", "take it with a grain of salt",
    "through thick and thin", "hit the sack", "on the fence", "in a nutshell",
    "at the end of the day", "see eye to eye", "touch base", "low hanging fruit",
    "rule of thumb", "call it a day", "cut to the chase", "the best of both worlds",
    "wrap your head around", "by the book", "cross that bridge", "water under the bridge",
)

POLITENESS_MARKERS: frozenset[str] = frozenset({
    "please", "thank you", "thanks", "thank u", "thx", "sorry", "pardon",
    "excuse me", "apologies", "much appreciated", "kindly", "you're welcome",
    "my pleasure", "with respect", "beg your pardon", "appreciate it", "grateful",
    "many thanks", "warmest regards", "pardon me",
})

GREETINGS: frozenset[str] = frozenset({
    "hello", "hi", "hey", "howdy", "yo", "greetings", "good morning",
    "good afternoon", "good evening", "good day", "welcome", "what's up",
    "sup", "wassup", "hiya", "salutations", "hola", "bonjour", "ahoy",
})

SIGNOFFS: frozenset[str] = frozenset({
    "bye", "goodbye", "cheers", "regards", "best regards", "kind regards",
    "warm regards", "sincerely", "later", "laters", "cya", "see ya", "see you",
    "peace", "peace out", "take care", "have a good one", "talk soon", "best",
    "respectfully", "yours truly", "all the best", "until next time",
})

HONORIFICS: frozenset[str] = frozenset({
    "mr", "mrs", "ms", "miss", "dr", "prof", "sir", "madam", "lord", "lady",
    "judge", "officer", "captain", "sergeant", "colonel", "general", "reverend",
    "pastor", "father", "senator", "governor", "president", "chancellor",
    "ambassador", "honorable",
})

# Regex patterns
_WORD_RE = re.compile(r"\b[a-zA-Z0-9_'’-]+\b")
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")
_DIRECT_ADDRESS_HANDLE_RE = re.compile(r"@[a-zA-Z0-9_]{3,32}\b")
_DIRECT_ADDRESS_PRONOUN_RE = re.compile(r"\b(?:you|u|your|yours|yourself)\b", re.IGNORECASE)

DEFAULT_REGISTER_FEATURES: Dict[str, Any] = {
    "formality_score": 0.0,
    "slang_rate": 0.0,
    "profanity_rate": 0.0,
    "slur_rate": 0.0,
    "abbreviation_rate": 0.0,
    "acronym_rate": 0.0,
    "technical_jargon_rate": 0.0,
    "colloquialism_rate": 0.0,
    "idiom_rate": 0.0,
    "politeness_marker_rate": 0.0,
    "greeting_rate": 0.0,
    "signoff_rate": 0.0,
    "honorific_rate": 0.0,
    "direct_address_rate": 0.0,
    "profanity_vocabulary": {},
    "slur_vocabulary": {},
    "slang_vocabulary": {},
    "abbreviation_vocabulary": {},
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


def _count_phrase_matches(corpus_lower: str, phrases: Tuple[str, ...] | frozenset[str]) -> int:
    """Count non-overlapping occurrences of multi-word or single-word phrases."""
    count = 0
    for phrase in phrases:
        pattern = r"\b" + re.escape(phrase) + r"\b"
        matches = re.findall(pattern, corpus_lower)
        count += len(matches)
    return count


def extract_register_features(
    messages: List[Dict[str, Any]],
    *,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract social register, formality, and tone features from messages.

    Args:
        messages: List of dicts, each with a 'content' or 'text' field.
        config: Optional per-target feature config (from feature_config.get_config).

    Returns:
        JSON-serializable dictionary of register features.
    """
    if not messages:
        return {
            k: (dict(v) if isinstance(v, dict) else v)
            for k, v in DEFAULT_REGISTER_FEATURES.items()
        }

    texts = [_extract_text(m) for m in messages]
    non_empty_texts = [t for t in texts if t]
    num_messages = len(messages)

    if not non_empty_texts:
        return {
            k: (dict(v) if isinstance(v, dict) else v)
            for k, v in DEFAULT_REGISTER_FEATURES.items()
        }

    corpus = "\n".join(non_empty_texts)
    corpus_lower = corpus.lower()

    # ── Merge dynamic lexicon expansions (GLM-5.2 calibration loop) ────────
    try:
        from tgarchive.intelligence.lexicon_store import get_expanded_set
        _slang_words = get_expanded_set("slang", SLANG_WORDS)
        _profanity_words = get_expanded_set("profanity", PROFANITY_WORDS)
        _slur_words = get_expanded_set("slurs", SLUR_WORDS)
        _abbrev_words = get_expanded_set("acronyms", ABBREVIATIONS)
        _jargon_words = get_expanded_set("jargon", TECHNICAL_JARGON)
        _colloquial_words = get_expanded_set("colloquialisms", COLLOQUIALISMS)
    except ImportError:
        _slang_words = SLANG_WORDS
        _profanity_words = PROFANITY_WORDS
        _slur_words = SLUR_WORDS
        _abbrev_words = ABBREVIATIONS
        _jargon_words = TECHNICAL_JARGON
        _colloquial_words = COLLOQUIALISMS

    # ── Words & Tokens ──────────────────────────────────────────────────────
    words = _WORD_RE.findall(corpus)
    words_lower = [w.lower() for w in words]
    total_words = len(words)

    if total_words == 0:
        return {
            k: (dict(v) if isinstance(v, dict) else v)
            for k, v in DEFAULT_REGISTER_FEATURES.items()
        }

    # ── Slang, Profanity, Slurs, Abbreviations Detection ───────────────────
    slang_matches: List[str] = [w for w in words_lower if w in _slang_words]
    profanity_matches: List[str] = [w for w in words_lower if w in _profanity_words]
    slur_matches: List[str] = [w for w in words_lower if w in _slur_words]
    abbrev_matches: List[str] = [w for w in words_lower if w in _abbrev_words]

    slang_rate = len(slang_matches) / total_words
    profanity_rate = len(profanity_matches) / total_words
    slur_rate = len(slur_matches) / total_words
    abbreviation_rate = len(abbrev_matches) / total_words

    slang_vocab = {
        w: cnt for w, cnt in Counter(slang_matches).most_common(50)
    }
    profanity_vocab = {
        w: cnt for w, cnt in Counter(profanity_matches).most_common(50)
    }
    slur_vocab = {
        w: cnt for w, cnt in Counter(slur_matches).most_common(50)
    }
    abbrev_vocab = {
        w: cnt for w, cnt in Counter(abbrev_matches).most_common(50)
    }

    # ── Acronyms ────────────────────────────────────────────────────────────
    # Exclude common single uppercase words or standard short words
    acronym_matches = _ACRONYM_RE.findall(corpus)
    # Filter out single-letter words or all-caps common lowercase words
    acronym_matches = [
        a for a in acronym_matches
        if a not in ("I", "A", "AN", "THE", "AND", "OR", "IF", "IN", "ON", "TO", "AT", "BY", "IS", "IT")
    ]
    acronym_rate = len(acronym_matches) / total_words

    # ── Technical Jargon ────────────────────────────────────────────────────
    jargon_matches = [w for w in words_lower if w in _jargon_words]
    technical_jargon_rate = len(jargon_matches) / total_words

    # ── Colloquialisms & Idioms ─────────────────────────────────────────────
    colloquialism_count = _count_phrase_matches(corpus_lower, _colloquial_words)
    colloquialism_rate = colloquialism_count / total_words

    idiom_count = _count_phrase_matches(corpus_lower, IDIOMS)
    idiom_rate = idiom_count / num_messages

    # ── Politeness, Greetings, Signoffs, Honorifics ──────────────────────────
    politeness_count = _count_phrase_matches(corpus_lower, POLITENESS_MARKERS)
    politeness_marker_rate = politeness_count / num_messages

    greeting_count = _count_phrase_matches(corpus_lower, GREETINGS)
    greeting_rate = greeting_count / num_messages

    signoff_count = _count_phrase_matches(corpus_lower, SIGNOFFS)
    signoff_rate = signoff_count / num_messages

    # Honorifics can have trailing period (e.g. Dr., Mr., Prof.)
    honorific_matches = [
        w.rstrip(".") for w in words_lower if w.rstrip(".") in HONORIFICS
    ]
    honorific_rate = len(honorific_matches) / total_words

    # ── Direct Address ──────────────────────────────────────────────────────
    handle_matches = _DIRECT_ADDRESS_HANDLE_RE.findall(corpus)
    pronoun_matches = _DIRECT_ADDRESS_PRONOUN_RE.findall(corpus)
    direct_address_count = len(handle_matches) + len(pronoun_matches)
    direct_address_rate = direct_address_count / num_messages

    # ── Formality Score (Composite 0.0 - 1.0) ───────────────────────────────
    # Read config overrides (defaults match the original hardcoded values)
    cfg = config or {}
    fw = cfg.get("register_formality_weights", {})
    w_word_len = fw.get("word_length", 0.35)
    w_cleanliness = fw.get("cleanliness", 0.35)
    w_sentence = fw.get("sentence_complexity", 0.18)
    w_formal_marker = fw.get("formal_markers", 0.12)
    cleanliness_mult = cfg.get("register_cleanliness_multiplier", 8.0)
    formal_marker_mult = cfg.get("register_formal_marker_multiplier", 10.0)
    scream_mult = cfg.get("register_scream_penalty_multiplier", 4.0)
    scream_cap = cfg.get("register_scream_penalty_cap", 0.4)
    wl_offset = cfg.get("register_word_length_offset", 3.5)
    wl_scale = cfg.get("register_word_length_scale", 3.0)
    sl_offset = cfg.get("register_sentence_length_offset", 4.0)
    sl_scale = cfg.get("register_sentence_length_scale", 20.0)

    # Factor 1: Mean word length (formal English ~ 5.5-6.5+ chars, casual ~ 4.0 chars)
    avg_word_length = sum(len(w) for w in words) / total_words
    word_len_score = max(0.0, min(1.0, (avg_word_length - wl_offset) / wl_scale))

    # Factor 2: Absence of informal markers (slang, profanity, slurs, colloquialisms, chat abbreviations)
    informal_count = len(slang_matches) + len(profanity_matches) + len(slur_matches) + len(abbrev_matches) + colloquialism_count
    informal_density = informal_count / total_words
    cleanliness_score = max(0.0, 1.0 - (informal_density * cleanliness_mult))

    # Factor 3: Sentence complexity and length
    raw_sentences = [s.strip() for s in re.split(r"[.!?\n]+", corpus) if s.strip()]
    if raw_sentences:
        avg_sentence_len = total_words / len(raw_sentences)
        sentence_score = max(0.0, min(1.0, (avg_sentence_len - sl_offset) / sl_scale))
    else:
        sentence_score = 0.5

    # Factor 4: Formal marker presence (honorifics, polite markers, formal signoffs, technical jargon)
    formal_hits = len(honorific_matches) + politeness_count + signoff_count + len(jargon_matches)
    formal_marker_score = max(0.0, min(1.0, (formal_hits / total_words) * formal_marker_mult))

    # Factor 5: Screaming caps and excessive punctuation penalty
    screaming_caps = sum(
        1 for w in words if len(w) > 2 and w.isupper() and w.lower() not in _jargon_words
    )
    excessive_punct = len(re.findall(r"[!?]{2,}", corpus))
    screaming_penalty = min(scream_cap, ((screaming_caps + excessive_punct) / total_words) * scream_mult)

    # Composite calculation
    raw_formality = (
        w_word_len * word_len_score
        + w_cleanliness * cleanliness_score
        + w_sentence * sentence_score
        + w_formal_marker * formal_marker_score
        - screaming_penalty
    )
    formality_score = max(0.0, min(1.0, raw_formality))

    return {
        "formality_score": round(float(formality_score), 6),
        "slang_rate": round(float(slang_rate), 6),
        "profanity_rate": round(float(profanity_rate), 6),
        "slur_rate": round(float(slur_rate), 6),
        "abbreviation_rate": round(float(abbreviation_rate), 6),
        "acronym_rate": round(float(acronym_rate), 6),
        "technical_jargon_rate": round(float(technical_jargon_rate), 6),
        "colloquialism_rate": round(float(colloquialism_rate), 6),
        "idiom_rate": round(float(idiom_rate), 6),
        "politeness_marker_rate": round(float(politeness_marker_rate), 6),
        "greeting_rate": round(float(greeting_rate), 6),
        "signoff_rate": round(float(signoff_rate), 6),
        "honorific_rate": round(float(honorific_rate), 6),
        "direct_address_rate": round(float(direct_address_rate), 6),
        "profanity_vocabulary": profanity_vocab,
        "slur_vocabulary": slur_vocab,
        "slang_vocabulary": slang_vocab,
        "abbreviation_vocabulary": abbrev_vocab,
    }
