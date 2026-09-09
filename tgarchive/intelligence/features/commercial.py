"""
SPECTRA Intelligence — Commercial Feature Extraction & Comparison
==================================================================
Extracts and compares commercial, monetization, and vendor behavioral patterns
across actors:
- Price points and pricing distribution
- Currencies and cryptocurrency transaction preferences
- Minimum order sizes / MOQs
- Cybercrime and market product taxonomy / category profiles
- Boilerplate sales phrasing and customer communication templates
- Escrow and guarantor transaction habits
- Promotional discount and bulk sales patterns
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Price extraction patterns
PRICE_PATTERN: re.Pattern = re.compile(
    r"(?:([\$€£₽¥])\s*(\d+(?:[.,]\d+)?\s*[kmb]?))|"
    r"(?:(\d+(?:[.,]\d+)?\s*[kmb]?)\s*(usd|eur|gbp|rub|btc|xmr|eth|usdt|usdc|bucks|dollars?|euros?))\b|"
    r"(?:price[:\s]+([\$€£₽¥])?\s*(\d+(?:[.,]\d+)?\s*[kmb]?))\b",
    re.IGNORECASE,
)

# Minimum order size patterns
MIN_ORDER_PATTERN: re.Pattern = re.compile(
    r"(?:min(?:imum)?\s*order|moq|min\s*purchase|min(?:imum)?\s*amount)\s*[:=-]?\s*"
    r"(\$?\d+(?:[.,]\d+)?\s*(?:pcs|units|items|usd|\$|k|logs|accounts|cards|lines)?)\b|"
    r"\bmin(?:imum)?\s*(\d+)\s*(?:pcs|units|items|logs|accounts|cards|lines)\b",
    re.IGNORECASE,
)

# Escrow patterns
ESCROW_PATTERN: re.Pattern = re.compile(
    r"\b(?:escrow|middleman|guarantor|escrow\s*accepted|deal\s*through\s*escrow|verified\s*escrow)\b",
    re.IGNORECASE,
)

# Discount patterns
DISCOUNT_PATTERN: re.Pattern = re.compile(
    r"(?:\b\d+%\s*off\b|\bdiscount\b|\bbulk\s*(?:discount|price|deal|order)\b|\bsale\b|\bpromo(?:tion|code)?\b|\bbuy\s*\d+\s*get\s*\d+\b|\bspecial\s*offer\b)",
    re.IGNORECASE,
)

# Currency mappings
CURRENCY_MAP: Dict[str, str] = {
    "$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "bucks": "USD",
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "₽": "RUB",
    "rub": "RUB",
    "ruble": "RUB",
    "rubles": "RUB",
    "btc": "BTC",
    "bitcoin": "BTC",
    "xmr": "XMR",
    "monero": "XMR",
    "eth": "ETH",
    "ethereum": "ETH",
    "usdt": "USDT",
    "tether": "USDT",
    "usdc": "USDC",
    "ltc": "LTC",
    "litecoin": "LTC",
}

# Product Taxonomy Keywords
PRODUCT_TAXONOMY: Dict[str, Tuple[str, ...]] = {
    "malware": (
        "malware", "trojan", "stealer", "keylogger", "rat", "botnet",
        "loader", "cryptor", "stub", "builder", "c2", "implant",
        "clipper", "rootkit", "infostealer",
    ),
    "ransomware": (
        "ransomware", "locker", "decryptor", "leak site",
    ),
    "initial_access": (
        "initial access", "rdp", "vpn", "ssh", "webshell", "cpanel",
        "root access", "domain admin", "admin access", "network access",
        "citrix", "shell",
    ),
    "logs_credentials": (
        "logs", "redline", "vidar", "racoon", "lumma", "stealer logs",
        "creds", "credentials", "combos", "user:pass", "mail:pass",
    ),
    "carding_financial": (
        "cc", "dumps", "cvv", "tracks", "cards", "fullz", "bank logs",
        "paypal", "stripe", "cashout", "clone cards", "bincode",
    ),
    "databases_dumps": (
        "db dump", "sql dump", "database leak", "user dump", "leaked database",
        "breach data", "database", "leaks", "leaked db",
    ),
    "exploits": (
        "exploit", "0day", "zero-day", "1day", "poc", "rce",
        "privilege escalation", "bypass", "vulnerability", "cve",
    ),
    "bulletproof_infra": (
        "bulletproof hosting", "bulletproof vps", "bulletproof server",
        "bulletproof", "fast flux", "reverse proxy",
    ),
    "phishing_scam": (
        "phishing kit", "scampage", "smishing", "mailer", "spam service",
        "smtp", "lead list", "phishing",
    ),
    "crypto_laundering": (
        "mixer", "tumbler", "clean crypto", "flash btc", "crypto cashout",
        "laundering",
    ),
    "identity_docs": (
        "fake id", "passport", "dl", "utility bill", "selfie with id",
        "kyc bypass", "ssn", "drivers license",
    ),
    "osint_dox": (
        "lookup", "dox", "sim swap", "lookup bot", "ssn lookup",
        "background check", "deanon",
    ),
}

# Standard Boilerplate Sales Phrases
SALES_PHRASES: Tuple[str, ...] = (
    "dm for info", "pm for price", "dm for price", "pm for info",
    "in stock", "available", "verified", "escrow accepted",
    "instant delivery", "fast support", "24/7 support", "24/7",
    "contact support", "vouch", "vouches", "rep", "best quality",
    "limited stock", "auto buy", "autobuy", "shop link",
    "fresh logs", "daily update", "guarantee", "replacement warranty",
    "proof available", "bulk discount", "serious buyers only",
    "dm me", "pm me", "write in pm", "contact me",
)


def _overlap_coefficient(set_a: Set[Any], set_b: Set[Any]) -> float:
    """Compute overlap coefficient between two sets."""
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / min(len(set_a), len(set_b))


def _parse_amount(raw_num: str) -> Optional[float]:
    """Parse numeric amount from price string, handling k/m suffixes."""
    if not raw_num:
        return None
    clean = raw_num.strip().lower().replace(",", "")
    multiplier = 1.0
    if clean.endswith("k"):
        multiplier = 1000.0
        clean = clean[:-1].strip()
    elif clean.endswith("m"):
        multiplier = 1000000.0
        clean = clean[:-1].strip()
    elif clean.endswith("b"):
        multiplier = 1000000000.0
        clean = clean[:-1].strip()
    try:
        val = float(clean) * multiplier
        if 0.0 < val < 1e12:
            return round(val, 2)
        return None
    except ValueError:
        return None


def extract_commercial_features(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract commercial and marketplace behaviors from message logs.

    Args:
        messages: List of message dictionaries

    Returns:
        Dictionary with list and integer values:
        - price_points: list of numerical prices extracted
        - currencies: list of currency identifiers (USD, EUR, BTC, XMR, USDT, etc.)
        - min_order_sizes: list of minimum order size / MOQ mentions
        - product_categories: list of detected product categories
        - sales_phrases: list of detected boilerplate sales phrases
        - escrow_mentions: count of escrow-related mentions
        - discount_patterns: list of detected discount / promo phrases
    """
    price_points: Set[float] = set()
    currencies: Set[str] = set()
    min_order_sizes: Set[str] = set()
    product_categories: Set[str] = set()
    sales_phrases: Set[str] = set()
    discount_patterns: Set[str] = set()
    escrow_mentions = 0

    if not messages:
        return {
            "price_points": [],
            "currencies": [],
            "min_order_sizes": [],
            "product_categories": [],
            "sales_phrases": [],
            "escrow_mentions": 0,
            "discount_patterns": [],
        }

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        text = (
            msg.get("content")
            or msg.get("text")
            or msg.get("message")
            or msg.get("caption")
            or msg.get("raw_text")
            or ""
        )
        if not isinstance(text, str) or not text.strip():
            continue

        text_lower = text.lower()

        # 1. Price points & Currencies
        for match in PRICE_PATTERN.finditer(text):
            # Groups: (sym, num1), (num2, curr_code), (prefix_sym, num3)
            sym1, num1, num2, code2, sym3, num3 = match.groups()
            raw_sym = sym1 or sym3
            raw_num = num1 or num2 or num3
            raw_code = code2

            if raw_num:
                amount = _parse_amount(raw_num)
                if amount is not None:
                    price_points.add(amount)

            if raw_sym and raw_sym in CURRENCY_MAP:
                currencies.add(CURRENCY_MAP[raw_sym])
            if raw_code and raw_code.lower() in CURRENCY_MAP:
                currencies.add(CURRENCY_MAP[raw_code.lower()])

        # Standalone currency checks in text
        for token, canonical in CURRENCY_MAP.items():
            if len(token) > 1 and re.search(rf"\b{re.escape(token)}\b", text_lower):
                currencies.add(canonical)
            elif len(token) == 1 and token in text:
                currencies.add(canonical)

        # 2. Minimum order sizes
        for match in MIN_ORDER_PATTERN.finditer(text):
            groups = [g for g in match.groups() if g is not None]
            for g in groups:
                clean_g = g.strip()
                if clean_g:
                    min_order_sizes.add(clean_g)

        # 3. Product categories
        for cat_name, keywords in PRODUCT_TAXONOMY.items():
            for kw in keywords:
                if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                    product_categories.add(cat_name)
                    break

        # 4. Sales phrases
        for phrase in SALES_PHRASES:
            if phrase in text_lower:
                sales_phrases.add(phrase)

        # 5. Escrow mentions count
        escrow_matches = ESCROW_PATTERN.findall(text)
        escrow_mentions += len(escrow_matches)

        # 6. Discount patterns
        for disc_match in DISCOUNT_PATTERN.finditer(text):
            val = disc_match.group(0).strip().lower()
            if val:
                discount_patterns.add(val)

    return {
        "price_points": sorted(price_points),
        "currencies": sorted(currencies),
        "min_order_sizes": sorted(min_order_sizes),
        "product_categories": sorted(product_categories),
        "sales_phrases": sorted(sales_phrases),
        "escrow_mentions": escrow_mentions,
        "discount_patterns": sorted(discount_patterns),
    }


def compare_commercial_features(
    feat_a: Dict[str, Any], feat_b: Dict[str, Any]
) -> Tuple[float, float]:
    """
    Compare commercial features between two actors using set similarity for
    taxonomies, currencies, and phrases, plus distribution comparison for prices.

    Args:
        feat_a: Feature dictionary for Actor A
        feat_b: Feature dictionary for Actor B

    Returns:
        Tuple of (similarity_score, confidence) both bounded in [0.0, 1.0].
    """
    if not feat_a or not feat_b:
        return 0.0, 0.0

    prices_a = [float(p) for p in feat_a.get("price_points", [])]
    prices_b = [float(p) for p in feat_b.get("price_points", [])]

    curr_a = set(feat_a.get("currencies", []))
    curr_b = set(feat_b.get("currencies", []))

    moq_a = set(feat_a.get("min_order_sizes", []))
    moq_b = set(feat_b.get("min_order_sizes", []))

    cat_a = set(feat_a.get("product_categories", []))
    cat_b = set(feat_b.get("product_categories", []))

    phrases_a = set(feat_a.get("sales_phrases", []))
    phrases_b = set(feat_b.get("sales_phrases", []))

    disc_a = set(feat_a.get("discount_patterns", []))
    disc_b = set(feat_b.get("discount_patterns", []))

    escrow_a = int(feat_a.get("escrow_mentions", 0))
    escrow_b = int(feat_b.get("escrow_mentions", 0))

    # 1. Category and currency similarity
    cat_sim = _overlap_coefficient(cat_a, cat_b)
    curr_sim = _overlap_coefficient(curr_a, curr_b)
    phrases_sim = _overlap_coefficient(phrases_a, phrases_b)
    moq_sim = _overlap_coefficient(moq_a, moq_b)
    disc_sim = _overlap_coefficient(disc_a, disc_b)

    # 2. Price distribution comparison
    has_prices = bool(prices_a and prices_b)
    price_sim = 0.0
    if has_prices:
        min_a, max_a = min(prices_a), max(prices_a)
        min_b, max_b = min(prices_b), max(prices_b)
        overlap = max(0.0, min(max_a, max_b) - max(min_a, min_b))
        union = max(max_a, max_b) - min(min_a, min_b)
        range_sim = overlap / union if union > 0 else (1.0 if min_a == min_b else 0.0)

        sorted_a = sorted(prices_a)
        sorted_b = sorted(prices_b)
        med_a = sorted_a[len(sorted_a) // 2]
        med_b = sorted_b[len(sorted_b) // 2]
        med_sim = min(med_a, med_b) / max(med_a, med_b) if max(med_a, med_b) > 0 else 1.0

        price_sim = 0.5 * range_sim + 0.5 * med_sim

    # 3. Escrow habit comparison
    has_escrow_data = (escrow_a > 0 or escrow_b > 0)
    escrow_sim = 0.0
    if has_escrow_data:
        if (escrow_a > 0 and escrow_b > 0):
            ratio = min(escrow_a, escrow_b) / max(escrow_a, escrow_b)
            escrow_sim = max(0.5, ratio)
        else:
            escrow_sim = 0.0

    # Categories: (name, similarity, has_data, weight)
    categories = [
        ("product_categories", cat_sim, bool(cat_a | cat_b), 0.30),
        ("currencies", curr_sim, bool(curr_a | curr_b), 0.20),
        ("sales_phrases", phrases_sim, bool(phrases_a | phrases_b), 0.20),
        ("price_distribution", price_sim, has_prices, 0.15),
        ("discount_patterns", disc_sim, bool(disc_a | disc_b), 0.05),
        ("min_order_sizes", moq_sim, bool(moq_a | moq_b), 0.05),
        ("escrow_habits", escrow_sim, has_escrow_data, 0.05),
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

    total_signals = (
        len(cat_a | cat_b)
        + len(curr_a | curr_b)
        + len(phrases_a | phrases_b)
        + len(moq_a | moq_b)
        + len(disc_a | disc_b)
        + len(prices_a)
        + len(prices_b)
        + (1 if has_escrow_data else 0)
    )

    if total_signals == 0:
        return 0.0, 0.0

    confidence = min(1.0, max(0.0, 1.0 - math.exp(-0.25 * total_signals)))

    return round(similarity_score, 4), round(confidence, 4)


__all__ = [
    "extract_commercial_features",
    "compare_commercial_features",
]
