"""
SPECTRA Intelligence — Media Feature Extraction & Comparison
============================================================
Extracts and compares media forensic artifacts across actors:
- Perceptual image hashes (pHash / dHash) with bitwise distance matching
- Exact cryptographic hashes (SHA256, MD5)
- OCR text snippets and optical extraction content
- File names and naming pattern conventions
- File extensions and MIME content types
"""
from __future__ import annotations

import difflib
import logging
import math
import os
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def _overlap_coefficient(set_a: Set[Any], set_b: Set[Any]) -> float:
    """Compute overlap coefficient between two sets."""
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / min(len(set_a), len(set_b))


def _hex_hamming_similarity(hash_a: str, hash_b: str) -> float:
    """
    Calculate bitwise similarity between two hex-encoded perceptual hashes.
    Returns value between 0.0 and 1.0 (1.0 = identical).
    """
    clean_a = hash_a.strip().lower().lstrip("0x")
    clean_b = hash_b.strip().lower().lstrip("0x")

    if not clean_a or not clean_b or len(clean_a) != len(clean_b):
        return 1.0 if clean_a == clean_b and clean_a else 0.0

    try:
        val_a = int(clean_a, 16)
        val_b = int(clean_b, 16)
        total_bits = len(clean_a) * 4
        xor_diff = val_a ^ val_b
        diff_bits = bin(xor_diff).count("1")
        return max(0.0, 1.0 - (diff_bits / total_bits))
    except ValueError:
        return 1.0 if clean_a == clean_b else 0.0


def _compare_phash_sets(hashes_a: Set[str], hashes_b: Set[str]) -> float:
    """Compute maximum pairwise perceptual hash similarity between two sets."""
    if not hashes_a or not hashes_b:
        return 0.0

    # Exact overlap fast-path
    if hashes_a & hashes_b:
        return 1.0

    max_sim = 0.0
    for ha in hashes_a:
        for hb in hashes_b:
            sim = _hex_hamming_similarity(ha, hb)
            if sim > max_sim:
                max_sim = sim
            if max_sim >= 0.95:
                return 1.0

    # If similarity is above 0.80 (standard pHash threshold), scale it
    return max_sim if max_sim >= 0.80 else 0.0


def _compare_text_sets(strings_a: Set[str], strings_b: Set[str]) -> float:
    """Compare two sets of text strings (OCR or file names) using SequenceMatcher and token overlap."""
    if not strings_a or not strings_b:
        return 0.0

    # Exact overlap fast-path
    if strings_a & strings_b:
        return 1.0

    # Token-level Jaccard across combined text
    tokens_a = {t.lower() for s in strings_a for t in s.split() if len(t) > 2}
    tokens_b = {t.lower() for s in strings_b for t in s.split() if len(t) > 2}
    token_sim = _overlap_coefficient(tokens_a, tokens_b)

    # Best string matching ratio
    max_ratio = 0.0
    for sa in strings_a:
        for sb in strings_b:
            ratio = difflib.SequenceMatcher(None, sa.lower(), sb.lower()).ratio()
            if ratio > max_ratio:
                max_ratio = ratio
            if max_ratio >= 0.95:
                break

    return max(token_sim, max_ratio)


def extract_media_features(media_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract forensic media attributes from a list of media records.

    Args:
        media_items: List of media dictionaries

    Returns:
        Dictionary with list values:
        - perceptual_hashes: list of perceptual hashes (pHash/dHash)
        - exact_hashes: list of SHA256/MD5/checksum hashes
        - ocr_strings: list of OCR text extractions
        - file_names: list of original file names
        - file_extensions: list of file extensions (without leading dot)
        - mime_types: list of MIME content types
    """
    perceptual_hashes: Set[str] = set()
    exact_hashes: Set[str] = set()
    ocr_strings: Set[str] = set()
    file_names: Set[str] = set()
    file_extensions: Set[str] = set()
    mime_types: Set[str] = set()

    if not media_items:
        return {
            "perceptual_hashes": [],
            "exact_hashes": [],
            "ocr_strings": [],
            "file_names": [],
            "file_extensions": [],
            "mime_types": [],
        }

    for item in media_items:
        if not isinstance(item, dict):
            continue

        # 1. Perceptual hashes
        for key in ("phash", "dhash", "perceptual_hash", "p_hash", "image_hash"):
            val = item.get(key)
            if val and isinstance(val, str) and val.strip():
                perceptual_hashes.add(val.strip().lower())

        # 2. Exact hashes
        for key in ("sha256", "sha256_hash", "exact_hash", "hash", "checksum", "md5", "sha1"):
            val = item.get(key)
            if val and isinstance(val, str) and val.strip():
                exact_hashes.add(val.strip().lower())

        # 3. OCR strings
        ocr_val = (
            item.get("ocr_text")
            or item.get("ocr_strings")
            or item.get("ocr")
            or item.get("extracted_text")
            or item.get("text")
        )
        if ocr_val:
            if isinstance(ocr_val, (list, set, tuple)):
                for s in ocr_val:
                    if s and isinstance(s, str) and s.strip():
                        ocr_strings.add(s.strip())
            elif isinstance(ocr_val, str) and ocr_val.strip():
                ocr_strings.add(ocr_val.strip())

        # 4. File names
        fn_val = (
            item.get("file_name")
            or item.get("filename")
            or item.get("name")
            or item.get("original_name")
        )
        if fn_val and isinstance(fn_val, str) and fn_val.strip():
            cleaned_fn = fn_val.strip()
            file_names.add(cleaned_fn)
            # Extract extension if not explicitly specified
            _, ext = os.path.splitext(cleaned_fn)
            if ext:
                file_extensions.add(ext.lstrip(".").lower())

        # 5. File extensions
        ext_val = item.get("file_ext") or item.get("extension") or item.get("ext")
        if ext_val and isinstance(ext_val, str) and ext_val.strip():
            file_extensions.add(ext_val.strip().lstrip(".").lower())

        # 6. MIME types
        mime_val = item.get("mime_type") or item.get("mime") or item.get("content_type")
        if mime_val and isinstance(mime_val, str) and mime_val.strip():
            mime_types.add(mime_val.strip().lower())

    return {
        "perceptual_hashes": sorted(perceptual_hashes),
        "exact_hashes": sorted(exact_hashes),
        "ocr_strings": sorted(ocr_strings),
        "file_names": sorted(file_names),
        "file_extensions": sorted(file_extensions),
        "mime_types": sorted(mime_types),
    }


def compare_media_features(
    feat_a: Dict[str, Any], feat_b: Dict[str, Any]
) -> Tuple[float, float]:
    """
    Compare media feature sets using cryptographic and perceptual hash matching,
    plus string similarity for OCR extractions and file names.

    Args:
        feat_a: Feature dictionary for Actor A
        feat_b: Feature dictionary for Actor B

    Returns:
        Tuple of (similarity_score, confidence) both bounded in [0.0, 1.0].
    """
    if not feat_a or not feat_b:
        return 0.0, 0.0

    exact_a = set(feat_a.get("exact_hashes", []))
    exact_b = set(feat_b.get("exact_hashes", []))

    phash_a = set(feat_a.get("perceptual_hashes", []))
    phash_b = set(feat_b.get("perceptual_hashes", []))

    ocr_a = set(feat_a.get("ocr_strings", []))
    ocr_b = set(feat_b.get("ocr_strings", []))

    names_a = set(feat_a.get("file_names", []))
    names_b = set(feat_b.get("file_names", []))

    exts_a = set(feat_a.get("file_extensions", []))
    exts_b = set(feat_b.get("file_extensions", []))

    mime_a = set(feat_a.get("mime_types", []))
    mime_b = set(feat_b.get("mime_types", []))

    exact_sim = _overlap_coefficient(exact_a, exact_b)
    phash_sim = _compare_phash_sets(phash_a, phash_b)
    ocr_sim = _compare_text_sets(ocr_a, ocr_b)
    name_sim = _compare_text_sets(names_a, names_b)
    ext_sim = _overlap_coefficient(exts_a, exts_b)
    mime_sim = _overlap_coefficient(mime_a, mime_b)

    # Categories: (name, similarity, has_data, weight)
    categories = [
        ("exact_hashes", exact_sim, bool(exact_a | exact_b), 0.35),
        ("perceptual_hashes", phash_sim, bool(phash_a | phash_b), 0.25),
        ("ocr_strings", ocr_sim, bool(ocr_a | ocr_b), 0.20),
        ("file_names", name_sim, bool(names_a | names_b), 0.10),
        ("file_extensions", ext_sim, bool(exts_a | exts_b), 0.05),
        ("mime_types", mime_sim, bool(mime_a | mime_b), 0.05),
    ]

    active_weight = 0.0
    weighted_sum = 0.0

    for _, sim, has_data, weight in categories:
        if has_data:
            weighted_sum += sim * weight
            active_weight += weight

    if active_weight == 0.0:
        return 0.0, 0.0

    similarity_score = weighted_sum / active_weight

    total_items = (
        len(exact_a | exact_b)
        + len(phash_a | phash_b)
        + len(ocr_a | ocr_b)
        + len(names_a | names_b)
        + len(exts_a | exts_b)
        + len(mime_a | mime_b)
    )

    if total_items == 0:
        return 0.0, 0.0

    confidence = min(1.0, max(0.0, 1.0 - math.exp(-0.25 * total_items)))

    return round(similarity_score, 4), round(confidence, 4)


__all__ = [
    "extract_media_features",
    "compare_media_features",
]
