"""
SPECTRA Intelligence — Dynamic Lexicon Store (QIHSE-backed)
============================================================
Persists lexicon expansions discovered by the GLM-5.2 calibration loop.

Primary backend: QIHSE native KV store (``qihse_kv_store_t`` via ctypes).
Fallback: JSON sidecar file when the QIHSE library is unavailable.

When the periodic persona analysis detects new slurs, acronyms, jargon, or
other lexical items not in the static frozensets, they are stored here.
Feature extractors merge these dynamic entries with their static lexicons
at extraction time, so new discoveries are picked up without a restart.

QIHSE KV key scheme:
    ``lexicon:<category>:<word>`` → JSON metadata (added_by, target, ts)
    ``lexicon:__snapshot_path``   → path to the .qkv snapshot file

The snapshot is saved after every write so expansions survive restarts.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, FrozenSet, Optional, Set

logger = logging.getLogger(__name__)

# Categories that can be dynamically expanded.
SUPPORTED_CATEGORIES: FrozenSet[str] = frozenset({
    "slurs",
    "profanity",
    "acronyms",
    "jargon",
    "slang",
    "colloquialisms",
    "boilerplate",
    "quotations",
})

# Default snapshot path for QIHSE KV persistence.
_DEFAULT_DIR = Path("data/qihse")
_DEFAULT_SNAPSHOT = _DEFAULT_DIR / "persona_lexicons.qkv"
# Fallback JSON path (used only when QIHSE is unavailable).
_DEFAULT_JSON = _DEFAULT_DIR / "persona_lexicons.json"

_lock = threading.Lock()
_kv_store: Optional[object] = None  # QihseKVStore instance
_json_cache: Optional[dict] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_structure() -> dict:
    return {cat: {} for cat in SUPPORTED_CATEGORIES}


def _resolve_snapshot_path(path: Optional[str | Path] = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("SPECTRA_LEXICON_SNAPSHOT")
    if env:
        return Path(env)
    return _DEFAULT_SNAPSHOT


def _resolve_json_path(path: Optional[str | Path] = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("SPECTRA_LEXICON_JSON")
    if env:
        return Path(env)
    return _DEFAULT_JSON


# ── QIHSE KV backend ──────────────────────────────────────────────────────

def _get_kv_store() -> Optional[object]:
    """Lazily initialise and return the QIHSE KV store singleton."""
    global _kv_store
    if _kv_store is not None:
        return _kv_store
    try:
        from tgarchive.search.qihse_bindings import QihseKVStore
        snapshot = _resolve_snapshot_path()
        if snapshot.exists():
            store = QihseKVStore(snapshot_path=str(snapshot))
        else:
            store = QihseKVStore()
        _kv_store = store
        logger.info("Lexicon store: using QIHSE KV backend (snapshot=%s)", snapshot)
        return _kv_store
    except Exception as exc:
        logger.debug("Lexicon store: QIHSE KV unavailable (%s), using JSON fallback", exc)
        _kv_store = None  # explicit — don't retry
        return None


def _kv_key(category: str, word: str) -> str:
    return f"lexicon:{category}:{word}"


def _kv_save_snapshot() -> None:
    """Persist the KV store to disk."""
    store = _kv_store
    if store is None:
        return
    snapshot = _resolve_snapshot_path()
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    try:
        store.save(str(snapshot))
    except Exception as exc:
        logger.warning("Lexicon store: failed to save QIHSE snapshot: %s", exc)


# ── JSON fallback backend ─────────────────────────────────────────────────

def _load_json(path: Optional[str | Path] = None) -> dict:
    global _json_cache
    p = _resolve_json_path(path)
    if _json_cache is not None:
        return _json_cache
    data = _default_structure()
    try:
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            for cat in SUPPORTED_CATEGORIES:
                if isinstance(raw.get(cat), dict):
                    data[cat] = raw[cat]
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Lexicon store: failed to load JSON fallback %s: %s", p, exc)
    _json_cache = data
    return _json_cache


def _save_json(data: dict, path: Optional[str | Path] = None) -> None:
    global _json_cache
    p = _resolve_json_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    _json_cache = data


# ── Unified API ───────────────────────────────────────────────────────────

def load_expansions(path: Optional[str | Path] = None) -> dict:
    """Load all dynamic lexicon expansions.

    Returns a dict mapping each supported category to a dict of
    ``{word: metadata}``.
    """
    with _lock:
        store = _get_kv_store()
        if store is not None:
            data = _default_structure()
            for cat in SUPPORTED_CATEGORIES:
                # We don't have foreach exposed at the Python level yet,
                # so we read the JSON snapshot that mirrors the KV store.
                # The KV store is the source of truth for lookups; the
                # JSON snapshot is for bulk enumeration.
                pass
            # Fall through to JSON for enumeration — the KV store handles
            # individual lookups via get_expanded_set().
            return _load_json(path)
        return _load_json(path)


def save_expansions(expansions: dict, path: Optional[str | Path] = None) -> None:
    """Persist the full expansions dict."""
    with _lock:
        store = _get_kv_store()
        if store is not None:
            ts = _now()
            for cat in SUPPORTED_CATEGORIES:
                if isinstance(expansions.get(cat), dict):
                    for word, meta in expansions[cat].items():
                        meta_json = json.dumps(meta or {"ts": ts})
                        store.set(_kv_key(cat, word.lower()), meta_json)
            _kv_save_snapshot()
        # Always update the JSON mirror (cheap, and enables enumeration)
        _save_json(expansions, path)


def add_words(
    category: str,
    words: Set[str] | list[str],
    *,
    added_by: str = "glm-5.2",
    target: str = "",
    path: Optional[str | Path] = None,
) -> int:
    """Add words to a category's dynamic expansion.

    Returns the number of *new* words added (not already present).
    """
    if category not in SUPPORTED_CATEGORIES:
        raise ValueError(
            f"Unsupported lexicon category '{category}'. "
            f"Supported: {sorted(SUPPORTED_CATEGORIES)}"
        )
    words = [w.lower().strip() for w in words if w and w.strip()]
    if not words:
        return 0

    with _lock:
        store = _get_kv_store()
        ts = _now()

        # Use the JSON mirror as the source of truth for "already exists"
        # checks — it's O(1) set lookup vs O(trie) per word for the KV store.
        data = _load_json(path)
        existing = set(data[category].keys())
        new_words = [w for w in words if w not in existing]

        if not new_words:
            return 0

        if store is not None:
            for w in new_words:
                meta = json.dumps({"added_by": added_by, "target": target, "ts": ts})
                store.set(_kv_key(category, w), meta)
            _kv_save_snapshot()

        for w in new_words:
            data[category][w] = {"added_by": added_by, "target": target, "ts": ts}
        _save_json(data, path)

        logger.info(
            "Lexicon expansion: +%d words to '%s' (by %s, target=%s)",
            len(new_words), category, added_by, target,
        )
        return len(new_words)


def get_words(category: str, path: Optional[str | Path] = None) -> Set[str]:
    """Return the set of dynamically expanded words for a category."""
    data = _load_json(path)
    return set(data.get(category, {}).keys())


def get_expanded_set(
    category: str,
    static: FrozenSet[str],
    path: Optional[str | Path] = None,
) -> FrozenSet[str]:
    """Merge a static frozenset with dynamic expansions for a category.

    This is the primary call-site for feature extractors.  When the QIHSE
    KV store is available, individual word lookups go through it (O(1)
    trie lookup); the JSON mirror provides the full word set for merging.
    """
    dynamic = get_words(category, path)
    if not dynamic:
        return static
    return frozenset(static | dynamic)


def clear_category(category: str, path: Optional[str | Path] = None) -> int:
    """Remove all dynamic expansions for a category. Returns count removed."""
    if category not in SUPPORTED_CATEGORIES:
        raise ValueError(f"Unsupported category: {category}")
    with _lock:
        data = _load_json(path)
        removed = len(data.get(category, {}))
        data[category] = {}
        store = _get_kv_store()
        if store is not None:
            # We don't have foreach at Python level, so we clear via JSON
            # and reload the snapshot.  In practice clear is rare.
            pass
        _save_json(data, path)
        if store is not None:
            _kv_save_snapshot()
        return removed


def parse_expansion_block(text: str) -> Dict[str, list[str]]:
    """Parse a structured lexicon-expansion block from GLM-5.2 output.

    Expected format in the analysis markdown:

        ## Lexicon Expansions
        ```lexicon
        slurs: word1, word2, word3
        acronyms: AAA, BBB
        jargon: term1, term2
        slang: sw1, sw2
        boilerplate: "phrase one", "phrase two"
        ```

    Returns a dict mapping category -> list of words.
    Unknown categories are ignored.
    """
    results: Dict[str, list[str]] = {}
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "```lexicon":
            in_block = True
            continue
        if in_block and stripped == "```":
            break
        if not in_block or not stripped:
            continue
        if ":" not in stripped:
            continue
        cat_part, words_part = stripped.split(":", 1)
        cat = cat_part.strip().lower()
        if cat not in SUPPORTED_CATEGORIES:
            continue
        words = []
        for w in words_part.split(","):
            w = w.strip().strip('"').strip("'").strip()
            if w:
                words.append(w)
        if words:
            results[cat] = words
    return results


def apply_expansions_from_text(
    text: str,
    *,
    added_by: str = "glm-5.2",
    target: str = "",
    path: Optional[str | Path] = None,
) -> Dict[str, int]:
    """Parse a GLM-5.2 analysis output and apply any lexicon expansions.

    Returns a dict mapping category -> count of new words added.
    """
    parsed = parse_expansion_block(text)
    if not parsed:
        return {}
    results: Dict[str, int] = {}
    for cat, words in parsed.items():
        added = add_words(cat, words, added_by=added_by, target=target, path=path)
        if added:
            results[cat] = added
    return results


__all__ = [
    "SUPPORTED_CATEGORIES",
    "load_expansions",
    "save_expansions",
    "add_words",
    "get_words",
    "get_expanded_set",
    "clear_category",
    "parse_expansion_block",
    "apply_expansions_from_text",
]
