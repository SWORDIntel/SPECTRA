"""Local fallback for the optional ssdeep dependency."""

from difflib import SequenceMatcher
import re


def _normalize(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read().lower()
    except Exception:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def hash_from_file(file_path):
    normalized = _normalize(file_path)
    if not normalized:
        return None
    return f"fallback:{normalized}"


def compare(hash1, hash2):
    if not hash1 or not hash2:
        return 0
    if hash1 == hash2:
        return 100
    if hash1.startswith("fallback:") and hash2.startswith("fallback:"):
        text1 = hash1.removeprefix("fallback:")
        text2 = hash2.removeprefix("fallback:")
        return int(round(SequenceMatcher(None, text1, text2).ratio() * 100))
    return 0
