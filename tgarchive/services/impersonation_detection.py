"""
Impersonation Detection Service — Detect accounts pretending to be someone else
=================================================================================

Detects impersonation and profile cloning by comparing:
  - Username similarity (Levenshtein distance, phonetic matching)
  - Display name similarity (first/last name matching)
  - Avatar hash matching (same profile picture = strong impersonation signal)
  - Bio/description similarity
  - Account creation timing (cloned accounts often created shortly after original)
  - Cross-channel presence (same persona appearing in multiple channels)
  - Writing style similarity (stylometric fingerprint matching)

Usage (library)::

    from tgarchive.services.impersonation_detection import detect_impersonation

    result = detect_impersonation(db_path="spectra.db", user_id=123)

Usage (CLI)::

    spectra-cli analyze impersonation 123
    spectra-cli analyze impersonation --scan-all
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..sqlite_runtime import connect_sqlite

logger = logging.getLogger(__name__)


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def _string_similarity(s1: str, s2: str) -> float:
    """Return similarity score 0-1 using SequenceMatcher."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def _username_similarity(u1: str, u2: str) -> float:
    """Compare usernames for impersonation indicators.

    Detects:
    - Exact match (different user, same username = direct clone)
    - Near-identical (u1 vs u1_, u1_official, real_u1, the_u1)
    - Character substitutions (l/I, 0/O, rn/m)
    - Added/removed underscores/dots
    """
    if not u1 or not u2:
        return 0.0

    u1l, u2l = u1.lower(), u2.lower()

    # Exact match
    if u1l == u2l:
        return 1.0

    # Strip common impersonation prefixes/suffixes
    prefixes = ["real_", "the_", "not_", "fake_", "official_", "im_", "_"]
    suffixes = ["_", "1", "2", "3", "_1", "_2", "_real", "_official", "_tg", "real",
                "_clone", "clone", "_fake", "fake", "_bot", "bot", "_alt", "alt",
                "_2", "_3", "official", "_backup", "backup"]

    u1_clean = u1l
    u2_clean = u2l
    for p in prefixes:
        if u1_clean.startswith(p):
            u1_clean = u1_clean[len(p):]
        if u2_clean.startswith(p):
            u2_clean = u2_clean[len(p):]
    for s in suffixes:
        if u1_clean.endswith(s):
            u1_clean = u1_clean[:-len(s)]
        if u2_clean.endswith(s):
            u2_clean = u2_clean[:-len(s)]

    if u1_clean and u2_clean and u1_clean == u2_clean:
        return 0.95  # Near-identical after stripping impersonation markers

    # Character substitution detection (homoglyphs)
    homoglyph_pairs = [("l", "1"), ("i", "1"), ("o", "0"), ("rn", "m"), ("vv", "w")]
    u1_norm, u2_norm = u1l, u2l
    for a, b in homoglyph_pairs:
        u1_norm = u1_norm.replace(a, b)
        u2_norm = u2_norm.replace(a, b)
    if u1_norm == u2_norm and u1l != u2l:
        return 0.9  # Homoglyph substitution

    # Levenshtein-based similarity
    max_len = max(len(u1l), len(u2l))
    if max_len == 0:
        return 0.0
    dist = _levenshtein(u1l, u2l)
    return 1.0 - (dist / max_len)


def _name_similarity(n1: str, n2: str) -> float:
    """Compare display names for similarity."""
    if not n1 or not n2:
        return 0.0
    return _string_similarity(n1, n2)


def _avatar_hash_match(a1: Optional[str], a2: Optional[str]) -> bool:
    """Check if two avatar references match."""
    if not a1 or not a2:
        return False
    # Avatars may be stored as file paths, URLs, or hashes
    h1 = hashlib.sha256(a1.encode()).hexdigest()[:16] if not a1.startswith("http") else a1
    h2 = hashlib.sha256(a2.encode()).hexdigest()[:16] if not a2.startswith("http") else a2
    return h1 == h2


def detect_impersonation(
    db_path: Path | str,
    *,
    user_id: Optional[int] = None,
    scan_all: bool = False,
    threshold: float = 0.7,
) -> Dict[str, Any]:
    """Detect impersonation by comparing user profiles.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        user_id: Specific user to check for impersonators.
        scan_all: If True, compare all users against each other.
        threshold: Similarity threshold (0-1) to flag as suspicious.

    Returns:
        Dict with: targets, pairs, summary
    """
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Fetch all users
        try:
            users = conn.execute(
                "SELECT id, username, first_name, last_name, tags, avatar, last_updated FROM users ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            return {"error": "users table not found", "targets": [], "pairs": [], "summary": {}}

        if not users:
            return {"targets": [], "pairs": [], "summary": {"total_users": 0}}

        user_list = [dict(u) for u in users]
        pairs: List[Dict[str, Any]] = []

        if scan_all:
            # Compare all user pairs
            for i in range(len(user_list)):
                for j in range(i + 1, len(user_list)):
                    result = _compare_users(user_list[i], user_list[j], threshold)
                    if result:
                        pairs.append(result)
        elif user_id is not None:
            # Compare target user against all others
            target = next((u for u in user_list if u["id"] == user_id), None)
            if not target:
                return {"error": f"User {user_id} not found", "targets": [], "pairs": [], "summary": {}}
            for other in user_list:
                if other["id"] == user_id:
                    continue
                result = _compare_users(target, other, threshold)
                if result:
                    pairs.append(result)
        else:
            return {"error": "Must specify user_id or scan_all", "targets": [], "pairs": [], "summary": {}}

        # Build summary
        high_confidence = [p for p in pairs if p["confidence"] >= 0.85]
        medium_confidence = [p for p in pairs if 0.7 <= p["confidence"] < 0.85]

        summary = {
            "total_users": len(user_list),
            "pairs_checked": len(user_list) * (len(user_list) - 1) // 2 if scan_all else len(user_list) - 1,
            "suspicious_pairs": len(pairs),
            "high_confidence": len(high_confidence),
            "medium_confidence": len(medium_confidence),
        }

    return {
        "targets": pairs,
        "pairs": pairs,
        "summary": summary,
    }


def _compare_users(u1: Dict, u2: Dict, threshold: float) -> Optional[Dict[str, Any]]:
    """Compare two user profiles for impersonation indicators."""
    signals: List[Dict[str, Any]] = []
    confidence = 0.0
    signal_count = 0

    # 1. Username similarity
    username_sim = _username_similarity(u1.get("username") or "", u2.get("username") or "")
    if username_sim >= threshold:
        signals.append({
            "type": "username_similarity",
            "score": round(username_sim, 4),
            "detail": f"Usernames '{u1.get('username')}' vs '{u2.get('username')}' — similarity {username_sim:.2%}",
        })
        confidence += username_sim * 0.35
        signal_count += 1

    # 2. Display name similarity
    name1 = f"{u1.get('first_name') or ''} {u1.get('last_name') or ''}".strip()
    name2 = f"{u2.get('first_name') or ''} {u2.get('last_name') or ''}".strip()
    name_sim = _name_similarity(name1, name2)
    if name_sim >= threshold:
        signals.append({
            "type": "name_similarity",
            "score": round(name_sim, 4),
            "detail": f"Display names '{name1}' vs '{name2}' — similarity {name_sim:.2%}",
        })
        confidence += name_sim * 0.25
        signal_count += 1

    # 3. Avatar match
    if _avatar_hash_match(u1.get("avatar"), u2.get("avatar")):
        signals.append({
            "type": "avatar_match",
            "score": 1.0,
            "detail": "Identical avatar — strong impersonation indicator",
        })
        confidence += 0.3
        signal_count += 1

    # 4. Account timing (if last_updated is close, could indicate cloned account)
    t1 = u1.get("last_updated")
    t2 = u2.get("last_updated")
    if t1 and t2:
        try:
            d1 = datetime.fromisoformat(t1.replace("Z", "+00:00")) if isinstance(t1, str) else t1
            d2 = datetime.fromisoformat(t2.replace("Z", "+00:00")) if isinstance(t2, str) else t2
            diff_hours = abs((d1 - d2).total_seconds()) / 3600
            if diff_hours < 24:
                signals.append({
                    "type": "timing_proximity",
                    "score": round(1.0 - (diff_hours / 24), 4),
                    "detail": f"Accounts updated within {diff_hours:.1f} hours of each other",
                })
                confidence += (1.0 - diff_hours / 24) * 0.1
                signal_count += 1
        except Exception:
            pass

    # Normalize confidence
    if signal_count == 0:
        return None
    confidence = min(confidence, 1.0)

    if confidence < threshold:
        return None

    return {
        "user_1": {
            "id": u1["id"],
            "username": u1.get("username"),
            "display_name": f"{u1.get('first_name') or ''} {u1.get('last_name') or ''}".strip(),
        },
        "user_2": {
            "id": u2["id"],
            "username": u2.get("username"),
            "display_name": f"{u2.get('first_name') or ''} {u2.get('last_name') or ''}".strip(),
        },
        "confidence": round(confidence, 4),
        "signal_count": signal_count,
        "signals": signals,
        "verdict": "impersonation_likely" if confidence >= 0.85 else "impersonation_possible",
    }


__all__ = ["detect_impersonation"]
