"""
SPECTRA Intelligence — L6 Numeric/Notation Style Module
======================================================
Extracts numeric formatting, notation patterns, date/time styles, and unit conventions
from messages to characterize an actor's quantitative and technical style.

Standard library only (re, collections, statistics, math).
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Word-form numbers (cardinal)
NUMBER_WORDS: Tuple[str, ...] = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety", "hundred", "thousand", "million", "billion", "trillion",
)
_NUMBER_WORDS_RE = re.compile(
    r"\b(?:" + "|".join(NUMBER_WORDS) + r")\b",
    re.IGNORECASE,
)

# Units of measurement for spacing and abbreviation checks
_UNIT_NAMES = (
    "GB", "MB", "KB", "TB", "PB", "B", "kg", "mg", "g", "km", "cm", "mm", "m",
    "ms", "s", "sec", "min", "hr", "hrs", "hz", "GHz", "MHz", "kHz",
    "V", "mV", "kV", "W", "kW", "MW", "A", "mA", "px", "pt", "em", "rem",
    "bit", "bits", "byte", "bytes", "fps", "mph", "kph", "km/h", "%",
)
_UNIT_SPELLED = (
    "gigabytes?", "megabytes?", "kilobytes?", "terabytes?", "bytes?",
    "kilograms?", "milligrams?", "grams?", "kilometers?", "centimeters?", "millimeters?", "meters?",
    "milliseconds?", "seconds?", "minutes?", "hours?",
    "percent", "percentage", "pixels?", "points?", "volts?", "watts?", "amperes?",
)

_UNIT_NO_SPACE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?(?:GB|MB|KB|TB|PB|kg|mg|km|cm|mm|ms|GHz|MHz|kHz|fps|mph|kph|px|pt|%))\b",
    re.IGNORECASE,
)
_UNIT_SPACE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?\s+(?:GB|MB|KB|TB|PB|B|kg|mg|g|km|cm|mm|m|ms|s|sec|min|hr|hrs|hz|GHz|MHz|kHz|V|W|A|px|pt|bit|bits|byte|bytes|fps|mph|kph|%))\b",
    re.IGNORECASE,
)

# Date regexes
_DATE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("YYYY-MM-DD", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    ("YYYY/MM/DD", re.compile(r"\b\d{4}/\d{2}/\d{2}\b")),
    ("YYYY.MM.DD", re.compile(r"\b\d{4}\.\d{2}\.\d{2}\b")),
    ("DD/MM/YYYY", re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")),
    ("DD/MM/YY", re.compile(r"\b\d{1,2}/\d{1,2}/\d{2}\b")),
    ("DD-MM-YYYY", re.compile(r"\b\d{1,2}-\d{1,2}-\d{4}\b")),
    ("DD-MM-YY", re.compile(r"\b\d{1,2}-\d{1,2}-\d{2}\b")),
    ("DD.MM.YYYY", re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b")),
    ("DD.MM.YY", re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2}\b")),
    ("DD Mon YYYY", re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}\b", re.IGNORECASE)),
    ("Mon DD, YYYY", re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4}\b", re.IGNORECASE)),
]

# Time regexes
_TIME_12H_RE = re.compile(r"\b\d{1,2}(?::\d{2})?(?::\d{2})?\s*(?:am|pm|AM|PM)\b")
_TIME_24H_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\b(?!\s*(?:am|pm|AM|PM))")
_TIME_MILITARY_RE = re.compile(r"\b[0-2]\d[0-5]\d\s*(?:hrs|hours|h)\b", re.IGNORECASE)

# Hex, Binary, Version, Range regexes
_HEX_0X_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_HEX_H_RE = re.compile(r"\b[0-9][0-9a-fA-F]*h\b|\b[a-fA-F][0-9a-fA-F]*h\b")
_HEX_DOLLAR_RE = re.compile(r"\$[0-9a-fA-F]{2,}\b")
_HEX_ESCAPE_RE = re.compile(r"\\x[0-9a-fA-F]{2}")
_HEX_RAW_RE = re.compile(r"\b(?:[0-9A-F]{2}:){2,}[0-9A-F]{2}\b|\b[0-9A-F]{4,}\b")

_BIN_0B_RE = re.compile(r"\b0b[01]+\b")
_BIN_B_RE = re.compile(r"\b[01]{4,}b\b")
_BIN_PERCENT_RE = re.compile(r"\%[01]+\b")

_VER_SEMVER_RE = re.compile(r"\b\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?\b")
_VER_V_RE = re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b")
_VER_WORD_RE = re.compile(r"\b(?:version|ver)\s+\d+\.\d+(?:\.\d+)?\b", re.IGNORECASE)
_VER_RELEASE_RE = re.compile(r"\br\d+(?:\.\d+)?\b", re.IGNORECASE)

_RANGE_HYPHEN_RE = re.compile(r"\b\d+\s*[-—–]\s*\d+\b")
_RANGE_DOTS_RE = re.compile(r"\b\d+\.\.\d+\b")
_RANGE_TO_RE = re.compile(r"\b\d+\s+to\s+\d+\b", re.IGNORECASE)
_RANGE_THROUGH_RE = re.compile(r"\b\d+\s+(?:through|thru)\s+\d+\b", re.IGNORECASE)
_RANGE_TILDE_RE = re.compile(r"\b\d+\s*~\s*\d+\b")

# Default flat feature structure
DEFAULT_NOTATION_FEATURES: Dict[str, Any] = {
    "number_word_preference": 0.0,
    "decimal_precision_distribution": {},
    "thousands_separator_style": {},
    "currency_format_style": {},
    "date_format_distribution": {},
    "time_format_distribution": {},
    "unit_spacing_style": {},
    "unit_abbreviation_style": {},
    "hex_notation_style": {},
    "binary_notation_style": {},
    "version_number_style": {},
    "range_notation_style": {},
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


def extract_notation_features(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract numeric, notation, currency, and date/time style features from messages.

    Args:
        messages: List of dicts, each with a 'content' or 'text' field.

    Returns:
        JSON-serializable dictionary of notation features.
    """
    if not messages:
        return {
            k: (dict(v) if isinstance(v, dict) else v)
            for k, v in DEFAULT_NOTATION_FEATURES.items()
        }

    texts = [_extract_text(m) for m in messages]
    non_empty_texts = [t for t in texts if t]

    if not non_empty_texts:
        return {
            k: (dict(v) if isinstance(v, dict) else v)
            for k, v in DEFAULT_NOTATION_FEATURES.items()
        }

    corpus = "\n".join(non_empty_texts)

    # ── Mask URLs before notation extraction ────────────────────────────────
    # URL path/query fragments (e.g. "v2", "2024", "1.0", "0x1a") produce
    # false positives for version numbers, dates, hex, etc.  We replace
    # URLs with a placeholder so their internal tokens are not extracted.
    _URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
    corpus_masked = _URL_RE.sub(" ", corpus)

    # ── Number Word Preference (word vs digit form) ─────────────────────────
    word_numbers = _NUMBER_WORDS_RE.findall(corpus_masked)
    digit_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", corpus_masked)
    total_number_tokens = len(word_numbers) + len(digit_numbers)
    number_word_preference = (
        (len(word_numbers) / total_number_tokens) if total_number_tokens > 0 else 0.0
    )

    # ── Decimal Precision Distribution ──────────────────────────────────────
    precisions: List[str] = []
    # Floating point numbers
    float_matches = re.findall(r"\b\d+\.(\d+)\b", corpus_masked)
    for m in float_matches:
        precisions.append(str(len(m)))

    # Integer numbers (precision 0)
    int_matches = re.findall(r"\b(?<!\.)\d+(?!\.)\b", corpus_masked)
    for _ in int_matches:
        precisions.append("0")

    if precisions:
        prec_counts = Counter(precisions)
        total_prec = len(precisions)
        decimal_precision_dist = {
            k: round(cnt / total_prec, 6)
            for k, cnt in prec_counts.most_common(50)
        }
    else:
        decimal_precision_dist = {}

    # ── Thousands Separator Style ───────────────────────────────────────────
    comma_sep = len(re.findall(r"\b\d{1,3}(?:,\d{3})+\b", corpus_masked))
    space_sep = len(re.findall(r"\b\d{1,3}(?:\s\d{3})+\b", corpus_masked))
    underscore_sep = len(re.findall(r"\b\d{1,3}(?:_\d{3})+\b", corpus_masked))
    dot_sep = len(re.findall(r"\b\d{1,3}(?:\.\d{3}){2,}\b", corpus_masked))
    # Plain 4+ digit numbers with no separators
    none_sep = len(re.findall(r"\b\d{4,}\b", corpus_masked)) - (comma_sep + space_sep + underscore_sep + dot_sep)
    none_sep = max(0, none_sep)

    sep_counts: Dict[str, int] = {}
    if comma_sep > 0:
        sep_counts["comma"] = comma_sep
    if none_sep > 0:
        sep_counts["none"] = none_sep
    if space_sep > 0:
        sep_counts["space"] = space_sep
    if underscore_sep > 0:
        sep_counts["underscore"] = underscore_sep
    if dot_sep > 0:
        sep_counts["dot"] = dot_sep

    total_sep = sum(sep_counts.values())
    if total_sep > 0:
        thousands_sep_dist = {
            k: round(v / total_sep, 6)
            for k, v in sorted(sep_counts.items(), key=lambda x: x[1], reverse=True)[:50]
        }
    else:
        thousands_sep_dist = {}

    # ── Currency Format Style ───────────────────────────────────────────────
    currency_styles: List[str] = []
    # Symbol prefix e.g. £30, $50, €100
    for match in re.findall(r"([$£€¥₽₿]\s*\d+(?:\.\d+)?)", corpus_masked):
        currency_styles.append(re.sub(r"\s+", "", match))

    # Symbol suffix e.g. 30$, 50€
    for match in re.findall(r"(\d+(?:\.\d+)?\s*[$£€¥₽₿])", corpus_masked):
        currency_styles.append(re.sub(r"\s+", "", match))

    # Word currencies e.g. 30 quid, 50 bucks, 100 dollars, 30 pounds
    for match in re.findall(
        r"(\d+(?:\.\d+)?\s+(?:quid|bucks|dollars?|pounds?|euros?|usd|eur|gbp|rub|btc|eth|xmr|usdt))\b",
        corpus_masked,
        re.IGNORECASE,
    ):
        currency_styles.append(match.lower())

    if currency_styles:
        curr_counts = Counter(currency_styles)
        total_curr = len(currency_styles)
        currency_format_dist = {
            k: round(cnt / total_curr, 6)
            for k, cnt in curr_counts.most_common(50)
        }
    else:
        currency_format_dist = {}

    # ── Date Format Distribution ────────────────────────────────────────────
    date_counts: Dict[str, int] = {}
    for fmt_name, pat in _DATE_PATTERNS:
        matches = pat.findall(corpus_masked)
        if matches:
            date_counts[fmt_name] = len(matches)

    total_dates = sum(date_counts.values())
    if total_dates > 0:
        date_format_dist = {
            k: round(v / total_dates, 6)
            for k, v in sorted(date_counts.items(), key=lambda x: x[1], reverse=True)[:50]
        }
    else:
        date_format_dist = {}

    # ── Time Format Distribution ────────────────────────────────────────────
    time_12h_cnt = len(_TIME_12H_RE.findall(corpus_masked))
    time_24h_cnt = len(_TIME_24H_RE.findall(corpus_masked))
    time_mil_cnt = len(_TIME_MILITARY_RE.findall(corpus_masked))

    time_counts: Dict[str, int] = {}
    if time_12h_cnt > 0:
        time_counts["12h"] = time_12h_cnt
    if time_24h_cnt > 0:
        time_counts["24h"] = time_24h_cnt
    if time_mil_cnt > 0:
        time_counts["military"] = time_mil_cnt

    total_times = sum(time_counts.values())
    if total_times > 0:
        time_format_dist = {
            k: round(v / total_times, 6)
            for k, v in sorted(time_counts.items(), key=lambda x: x[1], reverse=True)
        }
    else:
        time_format_dist = {}

    # ── Unit Spacing Style ──────────────────────────────────────────────────
    no_space_matches = _UNIT_NO_SPACE_RE.findall(corpus_masked)
    space_matches = _UNIT_SPACE_RE.findall(corpus_masked)

    unit_spacing_samples: List[str] = []
    unit_spacing_samples.extend(no_space_matches)
    unit_spacing_samples.extend(space_matches)

    if unit_spacing_samples:
        us_counts = Counter(unit_spacing_samples)
        total_us = len(unit_spacing_samples)
        unit_spacing_dist = {
            k: round(cnt / total_us, 6)
            for k, cnt in us_counts.most_common(50)
        }
    else:
        unit_spacing_dist = {}

    # ── Unit Abbreviation Style ─────────────────────────────────────────────
    unit_abbr_tokens: List[str] = []
    # Extract units from expressions
    for match in _UNIT_NO_SPACE_RE.finditer(corpus_masked):
        # Extract unit part
        u = re.sub(r"^\d+(?:\.\d+)?", "", match.group(1))
        if u:
            unit_abbr_tokens.append(u)

    for match in _UNIT_SPACE_RE.finditer(corpus_masked):
        parts = match.group(1).split()
        if len(parts) >= 2:
            unit_abbr_tokens.append(parts[1])

    # Also match spelled out units
    for sp in _UNIT_SPELLED:
        for match in re.finditer(r"\b\d+\s+(" + sp + r")\b", corpus_masked, re.IGNORECASE):
            unit_abbr_tokens.append(match.group(1).lower())

    if unit_abbr_tokens:
        u_counts = Counter(unit_abbr_tokens)
        total_u = len(unit_abbr_tokens)
        unit_abbr_dist = {
            k: round(cnt / total_u, 6)
            for k, cnt in u_counts.most_common(50)
        }
    else:
        unit_abbr_dist = {}

    # ── Hex Notation Style ──────────────────────────────────────────────────
    hex_samples: List[str] = []
    for m in _HEX_0X_RE.findall(corpus_masked):
        hex_samples.append(m)
    for m in _HEX_H_RE.findall(corpus_masked):
        hex_samples.append(m)
    for m in _HEX_DOLLAR_RE.findall(corpus_masked):
        hex_samples.append(m)
    for m in _HEX_ESCAPE_RE.findall(corpus_masked):
        hex_samples.append(m)
    for m in _HEX_RAW_RE.findall(corpus_masked):
        if not m.startswith("0x") and not m.endswith("h"):
            hex_samples.append(m)

    if hex_samples:
        h_counts = Counter(hex_samples)
        total_h = len(hex_samples)
        hex_notation_dist = {
            k: round(cnt / total_h, 6)
            for k, cnt in h_counts.most_common(50)
        }
    else:
        hex_notation_dist = {}

    # ── Binary Notation Style ───────────────────────────────────────────────
    bin_samples: List[str] = []
    bin_samples.extend(_BIN_0B_RE.findall(corpus_masked))
    bin_samples.extend(_BIN_B_RE.findall(corpus_masked))
    bin_samples.extend(_BIN_PERCENT_RE.findall(corpus_masked))

    if bin_samples:
        b_counts = Counter(bin_samples)
        total_b = len(bin_samples)
        bin_notation_dist = {
            k: round(cnt / total_b, 6)
            for k, cnt in b_counts.most_common(50)
        }
    else:
        bin_notation_dist = {}

    # ── Version Number Style ────────────────────────────────────────────────
    ver_samples: List[str] = []
    ver_samples.extend(_VER_SEMVER_RE.findall(corpus_masked))
    ver_samples.extend(_VER_V_RE.findall(corpus_masked))
    ver_samples.extend(_VER_WORD_RE.findall(corpus_masked))
    ver_samples.extend(_VER_RELEASE_RE.findall(corpus_masked))

    if ver_samples:
        v_counts = Counter(ver_samples)
        total_v = len(ver_samples)
        version_number_dist = {
            k: round(cnt / total_v, 6)
            for k, cnt in v_counts.most_common(50)
        }
    else:
        version_number_dist = {}

    # ── Range Notation Style ────────────────────────────────────────────────
    range_samples: List[str] = []
    range_samples.extend(_RANGE_HYPHEN_RE.findall(corpus_masked))
    range_samples.extend(_RANGE_DOTS_RE.findall(corpus_masked))
    range_samples.extend(_RANGE_TO_RE.findall(corpus_masked))
    range_samples.extend(_RANGE_THROUGH_RE.findall(corpus_masked))
    range_samples.extend(_RANGE_TILDE_RE.findall(corpus_masked))

    if range_samples:
        r_counts = Counter(range_samples)
        total_r = len(range_samples)
        range_notation_dist = {
            k: round(cnt / total_r, 6)
            for k, cnt in r_counts.most_common(50)
        }
    else:
        range_notation_dist = {}

    return {
        "number_word_preference": round(float(number_word_preference), 6),
        "decimal_precision_distribution": decimal_precision_dist,
        "thousands_separator_style": thousands_sep_dist,
        "currency_format_style": currency_format_dist,
        "date_format_distribution": date_format_dist,
        "time_format_distribution": time_format_dist,
        "unit_spacing_style": unit_spacing_dist,
        "unit_abbreviation_style": unit_abbr_dist,
        "hex_notation_style": hex_notation_dist,
        "binary_notation_style": bin_notation_dist,
        "version_number_style": version_number_dist,
        "range_notation_style": range_notation_dist,
    }
