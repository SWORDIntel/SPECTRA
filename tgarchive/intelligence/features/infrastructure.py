"""
SPECTRA Intelligence — Infrastructure Feature Extraction & Comparison
=====================================================================
Extracts and compares network and technical infrastructure identifiers across
actors (cryptocurrency wallets, URLs, domains, public IPs, Tor onion addresses,
Telegram bot IDs, Telegram handles, email addresses, phone numbers).

Includes anti-double-counting logic to prevent correlated artifacts (such as
a URL and its extracted domain) from artificially inflating confidence or scores.
"""
from __future__ import annotations

import ipaddress
import logging
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Try importing regex patterns from threat indicators engine; fallback inline
try:
    from ...threat.indicators import PatternDetector

    _BTC_PAT = getattr(PatternDetector, "BITCOIN_PATTERN", None)
    _ETH_PAT = getattr(PatternDetector, "ETHEREUM_PATTERN", None)
    _XMR_PAT = getattr(PatternDetector, "MONERO_PATTERN", None)
    _ONION_PAT = getattr(PatternDetector, "ONION_PATTERN", None)
    _IP_PAT = getattr(PatternDetector, "IP_PATTERN", None)
    _EMAIL_PAT = getattr(PatternDetector, "EMAIL_PATTERN", None)
    _URL_PAT = getattr(PatternDetector, "URL_PATTERN", None)
except Exception:
    _BTC_PAT = None
    _ETH_PAT = None
    _XMR_PAT = None
    _ONION_PAT = None
    _IP_PAT = None
    _EMAIL_PAT = None
    _URL_PAT = None

# Regex patterns (standalone and fallback)
BITCOIN_PATTERN: re.Pattern = (
    _BTC_PAT if _BTC_PAT is not None else re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")
)
ETHEREUM_PATTERN: re.Pattern = (
    _ETH_PAT if _ETH_PAT is not None else re.compile(r"\b0x[a-fA-F0-9]{40}\b")
)
MONERO_PATTERN: re.Pattern = (
    _XMR_PAT if _XMR_PAT is not None else re.compile(r"\b4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b")
)
ONION_PATTERN: re.Pattern = (
    _ONION_PAT if _ONION_PAT is not None else re.compile(r"\b[a-z2-7]{16,56}\.onion\b", re.IGNORECASE)
)
IP_PATTERN: re.Pattern = (
    _IP_PAT if _IP_PAT is not None else re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
)
EMAIL_PATTERN: re.Pattern = (
    _EMAIL_PAT if _EMAIL_PAT is not None else re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
)
URL_PATTERN: re.Pattern = (
    _URL_PAT if _URL_PAT is not None else re.compile(r"https?://[^\s<>\"']+")
)

# Telegram bot and handle patterns
BOT_HANDLE_PATTERN: re.Pattern = re.compile(r"(?<!\w)@([a-zA-Z0-9_]{3,32}[bB][oO][tT])\b")
TELEGRAM_HANDLE_PATTERN: re.Pattern = re.compile(r"(?<!\w)@([a-zA-Z0-9_]{4,32})\b")

# Phone number pattern (international E.164 and common formatted phone numbers)
PHONE_PATTERN: re.Pattern = re.compile(
    r"(?:(?:\+|00)[1-9]\d{0,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}\b"
)


def _is_public_ip(ip_str: str) -> bool:
    """Check if an IPv4/IPv6 string is a valid public IP address."""
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        return not (
            ip.is_private
            or ip.is_loopback
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_link_local
            or ip.is_unspecified
        )
    except ValueError:
        return False


def _extract_domain(url_str: str) -> Optional[str]:
    """Extract and normalize clean base domain from a URL."""
    try:
        cleaned = url_str.strip().rstrip(".,;:!?)>\"'")
        parsed = urlparse(cleaned)
        netloc = parsed.netloc.lower()
        if not netloc:
            return None
        # Strip port if present
        domain = netloc.split(":")[0].rstrip(".")
        if "." in domain and not domain.replace(".", "").isdigit():
            return domain
        return None
    except Exception:
        return None


def _clean_phone(raw_phone: str) -> Optional[str]:
    """Validate and normalize a phone number string."""
    digits = re.sub(r"\D", "", raw_phone)
    if not (7 <= len(digits) <= 15):
        return None
    # Must start with + or 00, or have standard delimiters/parentheses with >= 10 digits
    if raw_phone.startswith(("+", "00")):
        return "+" + digits if raw_phone.startswith("+") else "+" + digits[2:]
    if len(digits) >= 10 and any(c in raw_phone for c in "()-."):
        return digits
    return None


def _overlap_coefficient(set_a: Set[Any], set_b: Set[Any]) -> float:
    """Compute overlap coefficient between two sets."""
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / min(len(set_a), len(set_b))


def _unique_web_items(urls: Set[str], domains: Set[str]) -> Set[str]:
    """Anti-double-counting helper: deduplicates URLs against their extracted domains."""
    unique_items = set(urls)
    for d in domains:
        if not any(d in u for u in urls):
            unique_items.add(d)
    return unique_items


def extract_infrastructure_features(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract technical and network infrastructure identifiers from a list of messages.

    Args:
        messages: List of message dictionaries (with 'content', 'text', 'message', or 'caption')

    Returns:
        Dictionary with sorted list values for JSON serializability:
        - wallets: Cryptocurrency addresses (BTC, ETH, XMR)
        - urls: Web URLs
        - domains: Base domains extracted from URLs
        - ips: Public IP addresses
        - onions: Tor .onion addresses
        - bot_ids: Bot handles (@xxx_bot)
        - contact_handles: Non-bot Telegram user handles (@username)
        - emails: Email addresses
        - phone_numbers: Phone numbers
    """
    wallets: Set[str] = set()
    urls: Set[str] = set()
    domains: Set[str] = set()
    ips: Set[str] = set()
    onions: Set[str] = set()
    bot_ids: Set[str] = set()
    contact_handles: Set[str] = set()
    emails: Set[str] = set()
    phone_numbers: Set[str] = set()

    if not messages:
        return {
            "wallets": [],
            "urls": [],
            "domains": [],
            "ips": [],
            "onions": [],
            "bot_ids": [],
            "contact_handles": [],
            "emails": [],
            "phone_numbers": [],
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

        # 1. Wallets (BTC, ETH, XMR)
        for btc in BITCOIN_PATTERN.findall(text):
            wallets.add(btc)
        for eth in ETHEREUM_PATTERN.findall(text):
            wallets.add(eth.lower())
        for xmr in MONERO_PATTERN.findall(text):
            wallets.add(xmr)

        # 2. URLs and Domains
        found_urls = URL_PATTERN.findall(text)
        for raw_url in found_urls:
            cleaned_url = raw_url.rstrip(".,;:!?)>\"'")
            urls.add(cleaned_url)
            dom = _extract_domain(cleaned_url)
            if dom:
                domains.add(dom)

        # 3. Public IPs
        for ip in IP_PATTERN.findall(text):
            if _is_public_ip(ip):
                ips.add(ip)

        # 4. Tor Onion addresses
        for onion in ONION_PATTERN.findall(text):
            onions.add(onion.lower())

        # 5. Bot IDs vs Contact Handles
        # Find all telegram handles
        found_handles = TELEGRAM_HANDLE_PATTERN.findall(text)
        for handle in found_handles:
            norm_handle = "@" + handle.lower()
            if norm_handle.endswith("bot"):
                bot_ids.add(norm_handle)
            else:
                contact_handles.add(norm_handle)

        # 6. Emails
        for email in EMAIL_PATTERN.findall(text):
            emails.add(email.lower())

        # 7. Phone numbers
        for raw_phone in PHONE_PATTERN.findall(text):
            cleaned = _clean_phone(raw_phone)
            if cleaned:
                phone_numbers.add(cleaned)

    # Ensure no overlap between bot_ids and contact_handles
    contact_handles.difference_update(bot_ids)

    return {
        "wallets": sorted(wallets),
        "urls": sorted(urls),
        "domains": sorted(domains),
        "ips": sorted(ips),
        "onions": sorted(onions),
        "bot_ids": sorted(bot_ids),
        "contact_handles": sorted(contact_handles),
        "emails": sorted(emails),
        "phone_numbers": sorted(phone_numbers),
    }


def compare_infrastructure_features(
    feat_a: Dict[str, Any], feat_b: Dict[str, Any]
) -> Tuple[float, float]:
    """
    Compare infrastructure feature profiles between two actors using Jaccard
    similarity and anti-double-counting logic.

    Args:
        feat_a: Feature dictionary for Actor A
        feat_b: Feature dictionary for Actor B

    Returns:
        Tuple of (similarity_score, confidence) both bounded in [0.0, 1.0].
    """
    if not feat_a or not feat_b:
        return 0.0, 0.0

    wallets_a = set(feat_a.get("wallets", []))
    wallets_b = set(feat_b.get("wallets", []))

    urls_a = set(feat_a.get("urls", []))
    urls_b = set(feat_b.get("urls", []))

    domains_a = set(feat_a.get("domains", []))
    domains_b = set(feat_b.get("domains", []))

    ips_a = set(feat_a.get("ips", []))
    ips_b = set(feat_b.get("ips", []))

    onions_a = set(feat_a.get("onions", []))
    onions_b = set(feat_b.get("onions", []))

    bot_ids_a = set(feat_a.get("bot_ids", []))
    bot_ids_b = set(feat_b.get("bot_ids", []))

    handles_a = set(feat_a.get("contact_handles", []))
    handles_b = set(feat_b.get("contact_handles", []))

    emails_a = set(feat_a.get("emails", []))
    emails_b = set(feat_b.get("emails", []))

    phones_a = set(feat_a.get("phone_numbers", []))
    phones_b = set(feat_b.get("phone_numbers", []))

    # Anti-double-counting on web presence:
    # URL and domain are correlated; take max score of the cluster
    j_urls = _overlap_coefficient(urls_a, urls_b)
    j_domains = _overlap_coefficient(domains_a, domains_b)
    web_score = max(j_urls, j_domains) if (urls_a | urls_b or domains_a | domains_b) else 0.0

    # Category definitions: (name, similarity_score, has_data, weight)
    categories = [
        ("wallets", _overlap_coefficient(wallets_a, wallets_b), bool(wallets_a | wallets_b), 0.25),
        ("onions", _overlap_coefficient(onions_a, onions_b), bool(onions_a | onions_b), 0.20),
        ("web_presence", web_score, bool(urls_a | urls_b or domains_a | domains_b), 0.15),
        ("ips", _overlap_coefficient(ips_a, ips_b), bool(ips_a | ips_b), 0.10),
        ("emails", _overlap_coefficient(emails_a, emails_b), bool(emails_a | emails_b), 0.10),
        ("phones", _overlap_coefficient(phones_a, phones_b), bool(phones_a | phones_b), 0.10),
        ("bot_ids", _overlap_coefficient(bot_ids_a, bot_ids_b), bool(bot_ids_a | bot_ids_b), 0.05),
        ("contact_handles", _overlap_coefficient(handles_a, handles_b), bool(handles_a | handles_b), 0.05),
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

    # Anti-double-counting unique items across both actors for confidence
    unique_web = _unique_web_items(urls_a | urls_b, domains_a | domains_b)
    total_unique_items = (
        len(wallets_a | wallets_b)
        + len(onions_a | onions_b)
        + len(ips_a | ips_b)
        + len(emails_a | emails_b)
        + len(phones_a | phones_b)
        + len(bot_ids_a | bot_ids_b)
        + len(handles_a | handles_b)
        + len(unique_web)
    )

    if total_unique_items == 0:
        return 0.0, 0.0

    # Calibrated confidence curve based on total unique infrastructure items
    confidence = min(1.0, max(0.0, 1.0 - math.exp(-0.25 * total_unique_items)))

    return round(similarity_score, 4), round(confidence, 4)


__all__ = [
    "extract_infrastructure_features",
    "compare_infrastructure_features",
]
