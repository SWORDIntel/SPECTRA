"""
SPECTRA Intelligence — Dialogue Acts and Affective Expression (L11/L12)
========================================================================
Extracts dialogue act distributions, transition dynamics, and affective
linguistic encoding (sentiment, emotion markers, emphasis, intensifiers under
negative sentiment, conditional profanity/punctuation, and sarcasm/humor markers)
from messages to characterize an actor's communicative and emotional style.

Standard library only (re, collections, math, statistics, datetime, logging).
"""
from __future__ import annotations

import logging
import math
import re
import string
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

# ── Dialogue Acts Enumeration ────────────────────────────────────────────────

ALL_DIALOGUE_ACTS: Tuple[str, ...] = (
    "question",
    "answer",
    "request",
    "command",
    "suggestion",
    "correction",
    "challenge",
    "agreement",
    "disagreement",
    "clarification",
    "joke",
    "complaint",
    "observation",
    "hypothesis",
    "prediction",
)

# ── Imperative Verbs for Command Detection ────────────────────────────────────

IMPERATIVE_VERBS: frozenset[str] = frozenset({
    "add", "allow", "apply", "ask", "attach", "block", "build", "call", "cancel",
    "change", "check", "clean", "clear", "clone", "close", "compile", "configure",
    "connect", "copy", "create", "cut", "debug", "delete", "deploy", "disable",
    "disconnect", "do", "download", "drop", "dump", "edit", "enable", "enter",
    "execute", "extract", "fetch", "find", "fix", "flush", "format", "forward",
    "generate", "get", "give", "go", "grep", "halt", "help", "hide", "hold",
    "ignore", "import", "init", "initialize", "insert", "inspect", "install",
    "join", "keep", "kill", "launch", "leave", "let", "listen", "list", "load",
    "lock", "look", "make", "merge", "modify", "mount", "move", "mute", "notify",
    "open", "parse", "pass", "patch", "pause", "ping", "pipe", "post", "print",
    "proceed", "pull", "purge", "push", "put", "quit", "read", "reboot", "rebuild",
    "redirect", "refresh", "release", "reload", "remove", "rename", "replace",
    "reset", "resolve", "restart", "restore", "retry", "return", "revert",
    "revoke", "rollback", "route", "run", "save", "scan", "search", "select",
    "send", "set", "show", "shutdown", "skip", "start", "stop", "store", "submit",
    "switch", "sync", "take", "tell", "terminate", "test", "trace", "track",
    "try", "unblock", "undo", "unlock", "unmute", "unmount", "unpause", "update",
    "upgrade", "upload", "use", "validate", "verify", "view", "wait", "watch",
    "wipe", "write",
})

# ── Lexicons ──────────────────────────────────────────────────────────────────

POSITIVE_WORDS: frozenset[str] = frozenset({
    "good", "great", "excellent", "awesome", "fantastic", "amazing", "wonderful",
    "nice", "cool", "love", "loved", "loving", "best", "perfect", "beautiful",
    "brilliant", "super", "fine", "happy", "glad", "pleased", "joy", "enjoy",
    "enjoyed", "enjoying", "delicious", "exciting", "excited", "positive",
    "superior", "top", "win", "winner", "winning", "won", "success", "successful",
    "triumph", "sweet", "clean", "clear", "helpful", "safe", "secure", "easy",
    "fast", "quick", "smooth", "fix", "fixed", "solve", "solved", "honor",
    "proud", "smart", "clever", "pro", "upgrade", "improved", "improvement",
    "benefit", "lucky", "blessing", "welcome", "thanks", "thank", "appreciate",
    "appreciated", "friendly", "kind", "cheerful", "stellar", "outstanding",
    "remarkable", "phenomenal", "legendary", "masterpiece", "flawless", "valid",
    "correct", "right", "true", "solid", "reliable", "efficient", "optimal",
    "thrive", "profit", "delight", "delighted", "adore", "adored", "thrilled",
    "enthusiast", "admire", "impressed", "impressive", "kudos", "bravo", "yay",
    "cheer", "cheers", "respect", "worthy", "noble", "honest", "truth", "peace",
    "calm", "serene", "bliss", "paradise", "victorious", "victory", "splendid",
    "marvel", "marvelous", "terrific", "sublime", "exquisite", "genuine", "elite",
    "champion", "works", "working", "resolved", "agree", "agreed",
})

NEGATIVE_WORDS: frozenset[str] = frozenset({
    "bad", "terrible", "horrible", "awful", "poor", "worst", "worse", "suck",
    "sucks", "sucking", "sucked", "hate", "hated", "hating", "stupid", "idiot",
    "dumb", "useless", "garbage", "trash", "crap", "crappy", "shitty", "shit",
    "damn", "damned", "fucked", "fucking", "broken", "broke", "fail", "fails",
    "failed", "failure", "failing", "bug", "bugs", "buggy", "crash", "crashed",
    "crashing", "error", "errors", "flaw", "flawed", "glitch", "glitches",
    "slow", "lag", "lagging", "annoyed", "annoying", "annoy", "frustrate",
    "frustrated", "frustrating", "frustration", "anger", "angry", "mad", "pain",
    "painful", "hurt", "hurting", "sad", "depress", "depressed", "depressing",
    "grief", "sorrow", "misery", "miserable", "lose", "loser", "losing", "loss",
    "lost", "corrupt", "corrupted", "defect", "defective", "wrong", "incorrect",
    "false", "fake", "scam", "fraud", "toxic", "poison", "ruin", "ruined",
    "ruining", "destroy", "destroyed", "destruction", "disaster", "catastrophic",
    "danger", "dangerous", "unsafe", "vulnerable", "risk", "risky", "threat",
    "threaten", "abuse", "abusive", "hostile", "attack", "panic", "scare",
    "scared", "scary", "fear", "afraid", "terror", "trouble", "problematic",
    "issue", "issues", "breakdown", "mess", "messy", "foul", "nasty", "filthy",
    "ugly", "gross", "disgusting", "disgust", "shame", "shameful", "defeat",
    "despair", "hopeless", "helpless", "agony", "regret", "worthless", "inferior",
    "reject", "rejected", "denial", "fault", "blame", "suffering", "suffer",
    "ugh", "annoyance",
})

NEGATION_WORDS: frozenset[str] = frozenset({
    "not", "no", "never", "none", "neither", "nor", "hardly", "scarcely",
    "barely", "isn't", "isnt", "aren't", "arent", "wasn't", "wasnt", "weren't",
    "werent", "haven't", "havent", "hasn't", "hasnt", "hadn't", "hadnt",
    "won't", "wont", "wouldn't", "wouldnt", "don't", "dont", "doesn't", "doesnt",
    "didn't", "didnt", "can't", "cant", "couldn't", "couldnt", "shouldn't",
    "shouldnt", "without",
})

EMOTION_JOY: frozenset[str] = frozenset({
    "joy", "happy", "happiness", "glad", "gladness", "delight", "delighted",
    "cheerful", "cheer", "yay", "bliss", "smile", "smiling", "love", "loving",
    "loved", "enjoy", "enjoying", "enjoyed", "fun", "funny", "awesome",
    "wonderful", "fantastic", "amazing", "brilliant", "ecstatic", "thrilled",
    "pleased", "excited", "celebrate", "celebrating", "triumph", "win", "winner",
    "jubilant", "blessed", "laugh", "laughing", "laughter", "grateful",
    "gratitude", "glee",
})

EMOTION_ANGER: frozenset[str] = frozenset({
    "angry", "mad", "rage", "raging", "furious", "fury", "pissed", "piss",
    "annoyed", "annoying", "annoy", "infuriated", "outraged", "outrage",
    "hate", "hated", "hating", "hostile", "hostility", "irritated", "irritating",
    "irritation", "wrath", "bitter", "resent", "resentful", "resentment",
    "fuming", "indignant", "screaming", "livid", "temper", "provoked", "aggravated",
})

EMOTION_SADNESS: frozenset[str] = frozenset({
    "sad", "sadness", "depressed", "depressing", "depression", "unhappy",
    "sorrow", "sorrowful", "grief", "grieving", "cry", "crying", "cried",
    "tears", "weeping", "weep", "lonely", "loneliness", "heartbroken",
    "heartbreak", "miserable", "misery", "gloomy", "gloom", "despair",
    "down", "downcast", "helpless", "bummed", "hurt", "hurting", "mourning",
    "mourn", "melancholy", "hopeless", "hopelessness", "woe",
})

EMOTION_FEAR: frozenset[str] = frozenset({
    "fear", "fearful", "afraid", "scared", "scary", "frightened", "frightening",
    "terrified", "terrifying", "terror", "panic", "panicked", "panicking",
    "anxiety", "anxious", "nervous", "nervousness", "worried", "worry",
    "worrying", "horror", "dread", "dreading", "alarmed", "alarming",
    "threatened", "threatening", "uneasy", "phobia", "tense", "paranoid",
    "paranoia", "fright", "intimidation", "intimidated",
})

EMOTION_SURPRISE: frozenset[str] = frozenset({
    "shocked", "shocking", "shock", "surprised", "surprising", "surprise",
    "astonished", "astonishing", "astonishment", "amazed", "amazing",
    "amazement", "stunned", "stunning", "unexpected", "disbelief", "wow",
    "whoa", "omg", "speechless", "mindblown", "gasp", "startled",
    "unbelievable", "unbelievably", "staggering", "astounded", "baffled",
    "flabbergasted", "blindsided",
})

EMOTION_DISGUST: frozenset[str] = frozenset({
    "disgusting", "disgusted", "disgust", "gross", "revolting", "repulsive",
    "sickening", "nausea", "nauseating", "abhorrent", "vile", "filthy", "foul",
    "nasty", "distasteful", "yuck", "ew", "eww", "repugnant", "loathsome",
    "detestable", "sickeningly", "repelled", "grotesque", "nauseous",
})

INTENSIFIER_WORDS: frozenset[str] = frozenset({
    "very", "really", "extremely", "super", "highly", "so", "totally",
    "utterly", "insanely", "hugely", "deeply", "immensely", "incredibly",
    "terribly", "awfully", "wildly", "exceptionally", "drastically",
    "intensely", "massively", "profoundly", "extraordinarily",
})

INTENSIFIER_PHRASES: Tuple[str, ...] = (
    "so much", "way too", "a lot", "super much", "by far",
)

PROFANITY_WORDS: frozenset[str] = frozenset({
    "fuck", "fucking", "fucked", "fucker", "fucks", "fuckin", "motherfucker",
    "shit", "shitty", "shitting", "bullshit", "damn", "damned", "damnit",
    "ass", "asshole", "asses", "bitch", "bitches", "bitching", "bastard",
    "bastards", "cunt", "cunts", "dick", "dicks", "dickhead", "piss", "pissed",
    "pissing", "crap", "crappy", "hell", "cock", "cocksucker", "slut", "whore",
    "prick", "twat", "wanker", "bollocks", "bugger", "douche", "douchebag",
    "dipshit", "dumbass", "jackass",
})

HUMOR_TOKENS: frozenset[str] = frozenset({
    "lol", "loll", "lolol", "haha", "hahaha", "hahahaha", "hehe", "hehehe",
    "lmao", "lmfao", "rofl", "roflmao", "xd", "kek", "jajaja", "jk",
})

HUMOR_EMOJIS: frozenset[str] = frozenset({
    "😂", "🤣", "😆", "😹", "😅",
})

SARCASM_PHRASES: Tuple[str, ...] = (
    "yeah right", "yeah sure", "right...", "as if", "oh great",
    "oh fantastic", "oh wonderful", "sure thing", "big deal",
)

ACRONYM_WHITELIST: frozenset[str] = frozenset({
    "ID", "API", "URL", "URI", "HTTP", "HTTPS", "TCP", "UDP", "IP", "DNS",
    "SSH", "SSL", "TLS", "CLI", "GUI", "OS", "CPU", "RAM", "ROM", "GPU",
    "VRAM", "DB", "SQL", "VFS", "JSON", "CSV", "HTML", "XML", "CSS", "JS",
    "AI", "ML", "GNN", "LLM", "NLP", "AST", "CFG", "CI", "CD", "PR", "OK",
    "DM", "PM", "USA", "UK", "EU", "UTC", "EST", "PST", "GMT",
})

# ── Canonical Default Feature Output Structure ───────────────────────────────

DEFAULT_DIALOGUE_ACTS_FEATURES: Dict[str, Any] = {
    "dialogue_act_distribution": {},
    "dialogue_act_transition_matrix": {},
    "sentiment_distribution": {
        "positive": 0.0,
        "neutral": 0.0,
        "negative": 0.0,
    },
    "emotion_marker_distribution": {
        "joy": 0.0,
        "anger": 0.0,
        "sadness": 0.0,
        "fear": 0.0,
        "surprise": 0.0,
        "disgust": 0.0,
    },
    "emphasis_rate": 0.0,
    "intensification_under_negative_sentiment": 0.0,
    "profanity_given_negative_sentiment": 0.0,
    "punctuation_given_emotion": {
        "positive": {"exclaim": 0.0},
        "negative": {"exclaim": 0.0, "ellipsis": 0.0},
    },
    "message_length_given_emotion": {
        "positive": 0.0,
        "neutral": 0.0,
        "negative": 0.0,
    },
    "sarcasm_marker_rate": 0.0,
    "humor_marker_rate": 0.0,
}

# ── Helper Functions ──────────────────────────────────────────────────────────

_WORD_TOKEN_RE = re.compile(r"\b[a-zA-Z0-9_'’-]+\b")


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


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    """Parse an ISO string or unix timestamp into a UTC datetime."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    if isinstance(ts, str):
        s = ts.strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
        try:
            return datetime.fromtimestamp(float(s), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    return None


def _tokenize_words(text: str) -> List[str]:
    """Extract lowercase word tokens from text."""
    return [w.lower() for w in _WORD_TOKEN_RE.findall(text)]


# ── Affective Linguistic Analysis Helpers ────────────────────────────────────

def classify_sentiment(text: str) -> str:
    """Classify text into 'positive', 'neutral', or 'negative' using lexicon matching."""
    tokens = _tokenize_words(text)
    if not tokens:
        return "neutral"

    pos_count = 0
    neg_count = 0

    for i, token in enumerate(tokens):
        negated = False
        if i > 0 and tokens[i - 1] in NEGATION_WORDS:
            negated = True
        elif i > 1 and tokens[i - 2] in NEGATION_WORDS:
            negated = True

        if token in POSITIVE_WORDS:
            if negated:
                neg_count += 1
            else:
                pos_count += 1
        elif token in NEGATIVE_WORDS:
            if negated:
                pos_count += 1
            else:
                neg_count += 1

    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    return "neutral"


def detect_emotion_markers(text: str) -> Set[str]:
    """Detect presence of Ekman's 6 basic emotion markers in text."""
    tokens = set(_tokenize_words(text))
    emotions: Set[str] = set()

    if tokens & EMOTION_JOY:
        emotions.add("joy")
    if tokens & EMOTION_ANGER:
        emotions.add("anger")
    if tokens & EMOTION_SADNESS:
        emotions.add("sadness")
    if tokens & EMOTION_FEAR:
        emotions.add("fear")
    if tokens & EMOTION_SURPRISE:
        emotions.add("surprise")
    if tokens & EMOTION_DISGUST:
        emotions.add("disgust")

    return emotions


def _has_emphasis(text: str) -> bool:
    """Check if message contains linguistic emphasis (ALL CAPS, exclamations, bold)."""
    if "!" in text:
        return True
    if "**" in text or "<b>" in text or "__" in text or "<i>" in text:
        return True
    # Check for ALL CAPS words of length >= 2
    raw_words = re.findall(r"\b[A-Z]{2,}\b", text)
    for rw in raw_words:
        if rw not in ACRONYM_WHITELIST:
            return True
    return False


def _has_intensifier(text: str) -> bool:
    """Check if message contains intensifying words or phrases."""
    lower = text.lower()
    for phrase in INTENSIFIER_PHRASES:
        if phrase in lower:
            return True
    tokens = set(_tokenize_words(text))
    return bool(tokens & INTENSIFIER_WORDS)


def _has_profanity(text: str) -> bool:
    """Check if message contains profanity."""
    tokens = set(_tokenize_words(text))
    return bool(tokens & PROFANITY_WORDS)


def _has_sarcasm(text: str, sentiment: str) -> bool:
    """Check for sarcasm markers (/s, sarcasm phrases, or cynical words in negative context)."""
    lower = text.lower()
    if "/s" in lower or "[sarcasm]" in lower or "(sarcasm)" in lower:
        return True
    for phrase in SARCASM_PHRASES:
        if phrase in lower:
            return True
    if sentiment == "negative":
        if "obviously" in lower or "clearly" in lower or "yeah right" in lower or "sure" in lower:
            return True
    return False


def _has_humor(text: str) -> bool:
    """Check for humor / laughter markers."""
    lower = text.lower()
    if any(emoji in text for emoji in HUMOR_EMOJIS):
        return True
    if "just kidding" in lower or "jk" in lower or "only joking" in lower:
        return True
    tokens = set(_tokenize_words(text))
    if tokens & HUMOR_TOKENS:
        return True
    if re.search(r"\b(ha(ha)+|he(he)+|lol+|lmao+|lmfao+|rofl+|xd+)\b", lower):
        return True
    return False


# ── Dialogue Act Classification ───────────────────────────────────────────────

def classify_dialogue_act(msg: Any, text: Optional[str] = None) -> str:
    """Classify a message into one of 15 dialogue acts.

    Categories:
    - question: ends with ? or starts with question word
    - answer: reply (has reply_to) and does not end with ?
    - request: starts with please, can you, could you, would you mind
    - command: imperative (starts with verb, no subject) without please
    - suggestion: maybe, how about, you could, I suggest, perhaps
    - correction: actually, no, that's wrong, I think you mean, not quite
    - challenge: why, how come, are you sure, really, seriously
    - agreement: yes, yeah, agree, true, exactly, right, correct
    - disagreement: no, nope, disagree, not really, I dont think
    - clarification: I mean, i.e., that is, in other words, basically
    - joke: lol, haha, lmao, rofl, joke markers
    - complaint: ugh, annoying, frustrating, stupid, hate, broken
    - observation: declarative statement of fact (default)
    - hypothesis: maybe, perhaps, I wonder, could be, might be
    - prediction: will, going to, I bet, expect, predict
    """
    if text is None:
        text = _extract_text(msg)
    clean_text = text.strip()
    if not clean_text:
        return "observation"

    lower = clean_text.lower()
    has_reply = False
    if isinstance(msg, dict):
        has_reply = bool(
            msg.get("reply_to_message_id") is not None
            or msg.get("reply_to") is not None
        )

    ends_with_question = bool(re.search(r"\?\s*$", clean_text))

    # 1. Request: explicit polite request / imperative starting with please / modal
    if re.match(
        r"^(please\b|can you\b|could you\b|would you mind\b|would you please\b|"
        r"could you please\b|can you please\b|kindly\b|will you please\b|"
        r"mind if you\b|do you mind\b)",
        lower,
    ):
        return "request"

    # 2. Correction: explicit correction markers
    if (
        re.match(
            r"^(actually\b|that['’]?s wrong\b|i think you mean\b|not quite\b|"
            r"correction\b|no[,!.]?\s+(that['’]?s|it['’]?s|wrong|incorrect)\b|"
            r"wrong[,!]?\s|incorrect[,!]?\s)",
            lower,
        )
        or "that's wrong" in lower
        or "thats wrong" in lower
        or "i think you mean" in lower
        or "not quite" in lower
    ):
        return "correction"

    # 3. Clarification: clarifying previous statements
    if (
        re.match(
            r"^(i mean\b|i\.e\.|ie\b|that is\b|in other words\b|basically\b|"
            r"to clarify\b|to be clear\b|what i meant\b|let me clarify\b)",
            lower,
        )
        or "in other words" in lower
        or "that is to say" in lower
    ):
        return "clarification"

    # 4. Challenge: questioning veracity, asking "are you sure", "how come", "why?"
    if (
        re.match(
            r"^(how come\b|are you sure\b|are you certain\b|really\?|seriously\?|"
            r"why would\b|why should\b|says who\b|is that so\b)",
            lower,
        )
        or lower in (
            "why?", "why", "really?", "really", "seriously?", "seriously",
            "are you sure?", "are you sure", "how come?", "how come",
        )
    ):
        return "challenge"

    # 5. Suggestion: proposing ideas or actions
    if re.match(
        r"^(how about\b|you could\b|we could\b|i suggest\b|i propose\b|"
        r"what if we\b|why don['’]?t we\b|perhaps we\b|maybe we\b|maybe you\b|"
        r"try to\b|consider\b)",
        lower,
    ):
        return "suggestion"

    # 6. Hypothesis: conjectures, wondering, possibility
    if (
        re.match(
            r"^(i wonder\b|could be\b|might be\b|maybe it['’]?s\b|hypothetically\b|"
            r"my guess is\b|it is possible\b|presumably\b|i suspect\b)",
            lower,
        )
        or (
            lower.startswith(("maybe", "perhaps"))
            and not re.match(r"^(maybe|perhaps)\s+(we|you|i suggest)\b", lower)
        )
    ):
        return "hypothesis"

    # 7. Prediction: forecasting future events
    if (
        re.match(
            r"^(i bet\b|i predict\b|i expect\b|going to\b|will probably\b|"
            r"will definitely\b|bound to\b|forecast\b)",
            lower,
        )
        or re.search(r"\b(i bet|i predict|i expect|going to|will probably|will definitely|bound to)\b", lower)
    ):
        return "prediction"

    # 8. Joke / Humor: laughter, sarcasm tags, joke tokens
    if (
        re.match(r"^(lol+|haha+|hehe+|lmao+|lmfao+|rofl+|xd+|/s|jk\b|just kidding\b)", lower)
        or lower in ("lol", "haha", "lmao", "rofl", "xd", "/s", "jk", "kek")
        or (any(tok in lower for tok in ("lol", "haha", "lmao", "rofl", "xd")) and len(lower.split()) <= 4)
    ):
        return "joke"

    # 9. Complaint: dissatisfaction, broken things, frustration
    if (
        re.match(
            r"^(ugh\b|annoying\b|frustrating\b|stupid\b|hate\b|broken\b|"
            r"sucks\b|fml\b|garbage\b|trash\b|waste of time\b)",
            lower,
        )
        or (
            any(w in lower for w in ("annoying", "frustrating", "broken", "stupid", "sucks", "hate this", "hate that"))
            and classify_sentiment(clean_text) == "negative"
        )
    ):
        return "complaint"

    # 10. Agreement: affirmative expressions
    if re.match(
        r"^(yes\b|yeah\b|yep\b|yup\b|agree\b|i agree\b|agreed\b|true\b|"
        r"exactly\b|right\b|correct\b|indeed\b|fair enough\b|makes sense\b|"
        r"sounds good\b|\+1\b|100%\b)",
        lower,
    ):
        return "agreement"

    # 11. Disagreement: negative expressions / rejection
    if re.match(
        r"^(no\b|nope\b|nah\b|disagree\b|i disagree\b|not really\b|"
        r"i don['’]?t think\b|don['’]?t agree\b|not true\b|false\b|hard no\b|no way\b)",
        lower,
    ):
        return "disagreement"

    # 12. Command (negated imperatives: do not, don't, never + verb)
    if (
        re.match(r"^(don['’]?t|do not|never)\s+[a-z]+", lower)
        and not ends_with_question
    ):
        return "command"

    # 13. Question: interrogative ending with ? or starting with question word
    if ends_with_question:
        return "question"

    if re.match(
        r"^(what|why|how|when|where|who|which|whose|whom|are|is|does|did|"
        r"can|could|would|will|should|shall|may|might|am|was|were|"
        r"haven['’]?t|hasn['’]?t|hadn['’]?t|isn['’]?t|aren['’]?t|doesn['’]?t|"
        r"didn['’]?t|won['’]?t|can['’]?t|couldn['’]?t)\b",
        lower,
    ) or re.match(r"^do\s+(you|we|i|they|the|this|that|these|those|any|all|anyone|someone)\b", lower):
        return "question"

    # 14. Command: imperative starting with action verb without subject or please
    tokens = _tokenize_words(clean_text)
    if tokens and not ends_with_question:
        first_word = tokens[0]
        subjects = {
            "i", "you", "we", "he", "she", "it", "they", "this", "that",
            "there", "my", "your", "our", "their", "the", "a", "an",
        }
        if first_word in IMPERATIVE_VERBS and first_word not in subjects:
            return "command"

    # 15. Answer: reply message that is not a question
    if has_reply and not ends_with_question:
        return "answer"

    # Observation: declarative statement of fact (default)
    return "observation"


# ── Main Feature Extraction Function ──────────────────────────────────────────

def extract_dialogue_acts_features(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract dialogue acts and affective expression features from messages.

    Args:
        messages: List of dicts, each with 'content'/'text' and optional 'date',
                  'reply_to_message_id' (or 'reply_to').

    Returns:
        Dictionary containing dialogue act distributions, transition matrix,
        sentiment distribution, emotion marker distribution, and affective
        expression metrics.
    """
    if not messages:
        return dict(DEFAULT_DIALOGUE_ACTS_FEATURES)

    # Filter messages that have non-empty text
    valid_items: List[Tuple[Dict[str, Any], str, Optional[datetime]]] = []
    for m in messages:
        text = _extract_text(m)
        if text and text.strip():
            dt = _parse_timestamp(m.get("date") if isinstance(m, dict) else None)
            valid_items.append((m if isinstance(m, dict) else {"content": text}, text.strip(), dt))

    if not valid_items:
        return dict(DEFAULT_DIALOGUE_ACTS_FEATURES)

    total_messages = len(valid_items)

    # ── Dialogue Acts Classification & Transition Dynamics ───────────────────
    act_counts: Counter[str] = Counter()
    classified_acts: List[Tuple[str, Optional[datetime]]] = []

    for msg, text, dt in valid_items:
        act = classify_dialogue_act(msg, text)
        act_counts[act] += 1
        classified_acts.append((act, dt))

    # Compute Dialogue Act Distribution (capped at 50)
    dialogue_act_distribution: Dict[str, float] = {
        act: round(count / total_messages, 6)
        for act, count in act_counts.most_common(50)
    }

    # Compute Transition Matrix (requires temporal ordering by date)
    # Sort stably by timestamp if present
    has_any_dates = any(dt is not None for _, dt in classified_acts)
    if has_any_dates:
        # Stable sort with fallback for None dates to preserve order
        indexed_acts = list(enumerate(classified_acts))
        indexed_acts.sort(
            key=lambda x: (
                x[1][1] if x[1][1] is not None else datetime.min.replace(tzinfo=timezone.utc),
                x[0],
            )
        )
        ordered_acts = [item[1][0] for item in indexed_acts]
    else:
        ordered_acts = [act for act, _ in classified_acts]

    transition_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    for i in range(len(ordered_acts) - 1):
        src_act = ordered_acts[i]
        dst_act = ordered_acts[i + 1]
        transition_counts[src_act][dst_act] += 1

    dialogue_act_transition_matrix: Dict[str, Dict[str, float]] = {}
    for src_act, dst_counter in sorted(transition_counts.items()):
        total_src = sum(dst_counter.values())
        if total_src > 0:
            dialogue_act_transition_matrix[src_act] = {
                dst: round(count / total_src, 6)
                for dst, count in dst_counter.most_common(50)
            }

    # ── Affective Expression Analysis ─────────────────────────────────────────
    sentiment_counts: Counter[str] = Counter()
    emotion_counts: Counter[str] = Counter()

    emphasis_count = 0
    sarcasm_count = 0
    humor_count = 0

    negative_messages_count = 0
    negative_with_intensifier = 0
    negative_with_profanity = 0
    negative_with_exclaim = 0
    negative_with_ellipsis = 0

    positive_messages_count = 0
    positive_with_exclaim = 0

    msg_lens_by_sentiment: Dict[str, List[int]] = defaultdict(list)

    for msg, text, _ in valid_items:
        sent = classify_sentiment(text)
        sentiment_counts[sent] += 1
        msg_lens_by_sentiment[sent].append(len(text))

        emotions = detect_emotion_markers(text)
        for em in emotions:
            emotion_counts[em] += 1

        if _has_emphasis(text):
            emphasis_count += 1

        if _has_sarcasm(text, sent):
            sarcasm_count += 1

        if _has_humor(text):
            humor_count += 1

        if sent == "negative":
            negative_messages_count += 1
            if _has_intensifier(text):
                negative_with_intensifier += 1
            if _has_profanity(text):
                negative_with_profanity += 1
            if "!" in text:
                negative_with_exclaim += 1
            if "..." in text or "…" in text or re.search(r"\.{3,}", text):
                negative_with_ellipsis += 1

        elif sent == "positive":
            positive_messages_count += 1
            if "!" in text:
                positive_with_exclaim += 1

    # Sentiment distribution
    sentiment_distribution: Dict[str, float] = {
        "positive": round(sentiment_counts["positive"] / total_messages, 6),
        "neutral": round(sentiment_counts["neutral"] / total_messages, 6),
        "negative": round(sentiment_counts["negative"] / total_messages, 6),
    }

    # Emotion marker distribution (Ekman's 6 basic emotions)
    emotion_marker_distribution: Dict[str, float] = {
        "joy": round(emotion_counts["joy"] / total_messages, 6),
        "anger": round(emotion_counts["anger"] / total_messages, 6),
        "sadness": round(emotion_counts["sadness"] / total_messages, 6),
        "fear": round(emotion_counts["fear"] / total_messages, 6),
        "surprise": round(emotion_counts["surprise"] / total_messages, 6),
        "disgust": round(emotion_counts["disgust"] / total_messages, 6),
    }

    # Emphasis and rates
    emphasis_rate = round(emphasis_count / total_messages, 6)
    sarcasm_marker_rate = round(sarcasm_count / total_messages, 6)
    humor_marker_rate = round(humor_count / total_messages, 6)

    # Conditionals under negative sentiment
    intensification_under_negative_sentiment = (
        round(negative_with_intensifier / negative_messages_count, 6)
        if negative_messages_count > 0
        else 0.0
    )
    profanity_given_negative_sentiment = (
        round(negative_with_profanity / negative_messages_count, 6)
        if negative_messages_count > 0
        else 0.0
    )

    # Punctuation given emotion
    pos_exclaim_rate = (
        round(positive_with_exclaim / positive_messages_count, 6)
        if positive_messages_count > 0
        else 0.0
    )
    neg_exclaim_rate = (
        round(negative_with_exclaim / negative_messages_count, 6)
        if negative_messages_count > 0
        else 0.0
    )
    neg_ellipsis_rate = (
        round(negative_with_ellipsis / negative_messages_count, 6)
        if negative_messages_count > 0
        else 0.0
    )

    punctuation_given_emotion: Dict[str, Dict[str, float]] = {
        "positive": {
            "exclaim": pos_exclaim_rate,
        },
        "negative": {
            "exclaim": neg_exclaim_rate,
            "ellipsis": neg_ellipsis_rate,
        },
    }

    # Message length given emotion (average character length)
    pos_lens = msg_lens_by_sentiment.get("positive", [])
    neu_lens = msg_lens_by_sentiment.get("neutral", [])
    neg_lens = msg_lens_by_sentiment.get("negative", [])

    message_length_given_emotion: Dict[str, float] = {
        "positive": round(sum(pos_lens) / len(pos_lens), 6) if pos_lens else 0.0,
        "neutral": round(sum(neu_lens) / len(neu_lens), 6) if neu_lens else 0.0,
        "negative": round(sum(neg_lens) / len(neg_lens), 6) if neg_lens else 0.0,
    }

    return {
        "dialogue_act_distribution": dialogue_act_distribution,
        "dialogue_act_transition_matrix": dialogue_act_transition_matrix,
        "sentiment_distribution": sentiment_distribution,
        "emotion_marker_distribution": emotion_marker_distribution,
        "emphasis_rate": emphasis_rate,
        "intensification_under_negative_sentiment": intensification_under_negative_sentiment,
        "profanity_given_negative_sentiment": profanity_given_negative_sentiment,
        "punctuation_given_emotion": punctuation_given_emotion,
        "message_length_given_emotion": message_length_given_emotion,
        "sarcasm_marker_rate": sarcasm_marker_rate,
        "humor_marker_rate": humor_marker_rate,
    }


# ── Feature Profile Comparison ────────────────────────────────────────────────

def compare_dialogue_acts_features(
    feat_a: Dict[str, Any],
    feat_b: Dict[str, Any],
) -> Tuple[float, float]:
    """Compare two dialogue acts & affective feature profiles.

    Args:
        feat_a: First feature dictionary.
        feat_b: Second feature dictionary.

    Returns:
        Tuple of (similarity_score 0-1, confidence 0-1).
    """
    if not isinstance(feat_a, dict) or not isinstance(feat_b, dict) or not feat_a or not feat_b:
        return (0.0, 0.0)

    # 1. Compare scalar rates
    scalar_keys = [
        "emphasis_rate",
        "intensification_under_negative_sentiment",
        "profanity_given_negative_sentiment",
        "sarcasm_marker_rate",
        "humor_marker_rate",
    ]
    vec_a = [float(feat_a.get(k, 0.0)) for k in scalar_keys]
    vec_b = [float(feat_b.get(k, 0.0)) for k in scalar_keys]

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    rate_sim = 0.0
    if norm_a > 0.0 and norm_b > 0.0:
        rate_sim = max(0.0, min(1.0, dot / (norm_a * norm_b)))

    # 2. Compare sentiment distribution
    sent_keys = ["positive", "neutral", "negative"]
    sent_a = feat_a.get("sentiment_distribution", {})
    sent_b = feat_b.get("sentiment_distribution", {})
    svec_a = [float(sent_a.get(k, 0.0)) for k in sent_keys]
    svec_b = [float(sent_b.get(k, 0.0)) for k in sent_keys]

    sdot = sum(a * b for a, b in zip(svec_a, svec_b))
    snorm_a = math.sqrt(sum(a * a for a in svec_a))
    snorm_b = math.sqrt(sum(b * b for b in svec_b))
    sent_sim = (sdot / (snorm_a * snorm_b)) if (snorm_a > 0.0 and snorm_b > 0.0) else 0.0

    # 3. Compare dialogue acts distribution
    acts_a = set(feat_a.get("dialogue_act_distribution", {}).keys())
    acts_b = set(feat_b.get("dialogue_act_distribution", {}).keys())
    act_jaccard = len(acts_a & acts_b) / len(acts_a | acts_b) if (acts_a | acts_b) else 0.0

    # Combined similarity score
    similarity = 0.4 * sent_sim + 0.3 * act_jaccard + 0.3 * rate_sim

    # Confidence based on non-zero presence
    non_zero_a = sum(1 for v in vec_a if v > 0) + len(acts_a)
    non_zero_b = sum(1 for v in vec_b if v > 0) + len(acts_b)
    avg_evidence = (non_zero_a + non_zero_b) / 2.0
    confidence = max(0.0, min(1.0, 1.0 - math.exp(-0.15 * avg_evidence)))

    return (round(similarity, 4), round(confidence, 4))


__all__ = [
    "extract_dialogue_acts_features",
    "compare_dialogue_acts_features",
    "classify_dialogue_act",
    "classify_sentiment",
    "detect_emotion_markers",
    "DEFAULT_DIALOGUE_ACTS_FEATURES",
    "ALL_DIALOGUE_ACTS",
]
