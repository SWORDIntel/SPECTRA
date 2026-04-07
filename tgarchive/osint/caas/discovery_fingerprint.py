from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

SERVICE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "initial_access": [
        re.compile(r"\b(rdp|vpn access|ssh access|corp access|domain admin|panel access|shell access)\b", re.I),
    ],
    "phishing_kit": [
        re.compile(r"\b(phish(?:ing)? kit|mailer|landing page|telegram bot panel)\b", re.I),
    ],
    "stealer_logs": [
        re.compile(r"\b(logs?|stealer|redline|vidar|raccoon|cookies|sessions)\b", re.I),
    ],
    "malware_loader": [
        re.compile(r"\b(loader|crypter|fud|stub|dropper)\b", re.I),
    ],
    "bulletproof_hosting": [
        re.compile(r"\b(bulletproof|bph|offshore hosting|no kyc hosting)\b", re.I),
    ],
    "otp_bypass": [
        re.compile(r"\b(otp|2fa bypass|sim|swap|call service)\b", re.I),
    ],
    "cashout_service": [
        re.compile(r"\b(cashout|withdrawal|mule|drop service)\b", re.I),
    ],
    "credentials_combo": [
        re.compile(r"\b(combo(?: list)?|credentials|mail access|accounts)\b", re.I),
    ],
}

ENTERPRISE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "marketplace": [re.compile(r"\bmarket(place)?|shop\b", re.I)],
    "storefront": [re.compile(r"\bmenu\b|catalog|available now|price list", re.I)],
    "broker": [re.compile(r"\bbroker\b|direct source|supplier", re.I)],
    "affiliate_program": [re.compile(r"\baffiliate\b|revshare|profit share", re.I)],
    "escrow_middleman": [re.compile(r"\bescrow\b|middleman|\bmm\b", re.I)],
}

PRICE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?P<currency>\$|£|€)\s?(?P<amount>\d+(?:[\.,]\d{1,2})?)", re.I),
    re.compile(r"(?P<amount>\d+(?:[\.,]\d{1,2})?)\s?(?P<currency>usd|eur|gbp|usdt|btc|xmr)", re.I),
    re.compile(r"(?P<amount_min>\d+(?:[\.,]\d{1,2})?)\s?-\s?(?P<amount_max>\d+(?:[\.,]\d{1,2})?)\s?(?P<currency>usd|eur|gbp|usdt|btc|xmr|\$|£|€)?", re.I),
]

URGENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(limited|today only|urgent|fresh|exclusive|big lot|bulk|wholesale)\b", re.I),
    re.compile(r"\b(1000\+|10k\+|massive|huge amount|large volume)\b", re.I),
]

PAYMENT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "btc": [re.compile(r"\bbtc\b|bitcoin", re.I)],
    "xmr": [re.compile(r"\bxmr\b|monero", re.I)],
    "usdt": [re.compile(r"\busdt\b|tether", re.I)],
    "escrow": [re.compile(r"\bescrow\b|middleman|\bmm\b", re.I)],
}

GEO_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "uk": [re.compile(r"\buk\b|\bgb\b|british", re.I)],
    "us": [re.compile(r"\bus\b|\busa\b|american", re.I)],
    "eu": [re.compile(r"\beu\b|europe", re.I)],
    "ru": [re.compile(r"\bru\b|russia|russian", re.I)],
}

BOT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bmenu\b|catalog|autoshop|instant delivery|vouches?", re.I),
    re.compile(r"\b24/7\b|support|replacement|guarantee|warranty", re.I),
]

HANDLE_RE = re.compile(r"@([A-Za-z0-9_]{4,32})")


class ChannelFingerprintEngine:
    """Layer 0: fast semantic triage for discovery expansion.

    The goal here is speed and recall, not deep precision. This class is
    intentionally regex and rule based so it can run inline with crawling.
    """

    def __init__(self, taxonomy_config: Optional[dict[str, Any]] = None):
        self.taxonomy_config = taxonomy_config or {}

    def _find_labels(self, text: str, mapping: dict[str, list[re.Pattern[str]]]) -> list[str]:
        labels: list[str] = []
        for label, patterns in mapping.items():
            if any(p.search(text) for p in patterns):
                labels.append(label)
        return sorted(set(labels))

    def _count_hits(self, text: str, patterns: Iterable[re.Pattern[str]]) -> int:
        count = 0
        for pattern in patterns:
            count += len(pattern.findall(text))
        return count

    def score_message(self, text: str, sender_username: str | None = None) -> Dict[str, Any]:
        if not text:
            return {
                "caas_score": 0.0,
                "bot_score": 0.0,
                "categories": [],
                "enterprise_model": [],
                "urgency_cues": [],
                "payment_methods": [],
                "geo_signals": [],
                "prices_found": 0,
                "actor_aliases": [],
                "critical_signal": 0.0,
            }

        normalized = re.sub(r"\s+", " ", text.strip().lower())
        categories = self._find_labels(normalized, SERVICE_PATTERNS)
        enterprise_model = self._find_labels(normalized, ENTERPRISE_PATTERNS)
        payment_methods = self._find_labels(normalized, PAYMENT_PATTERNS)
        geo_signals = self._find_labels(normalized, GEO_PATTERNS)
        urgency_cues = [m.group(0).lower() for p in URGENT_PATTERNS for m in p.finditer(normalized)]
        actor_aliases = sorted(set(HANDLE_RE.findall(text)))
        prices_found = sum(len(p.findall(normalized)) for p in PRICE_PATTERNS)
        bot_hits = self._count_hits(normalized, BOT_PATTERNS)

        caas_score = 0.0
        if categories:
            caas_score += 0.45
        if prices_found:
            caas_score += 0.20
        if payment_methods:
            caas_score += 0.10
        if enterprise_model:
            caas_score += 0.10
        if urgency_cues:
            caas_score += 0.10
        if actor_aliases:
            caas_score += 0.05

        bot_score = min(1.0, bot_hits * 0.25)
        critical_signal = 0.0
        if urgency_cues:
            critical_signal += 0.20
        if prices_found >= 2:
            critical_signal += 0.15
        if any(c in categories for c in ("initial_access", "otp_bypass", "cashout_service")):
            critical_signal += 0.20
        if re.search(r"\b(10k\+|1000\+|massive|huge amount|large volume)\b", normalized, re.I):
            critical_signal += 0.35

        return {
            "caas_score": min(1.0, caas_score),
            "bot_score": bot_score,
            "categories": categories,
            "enterprise_model": enterprise_model,
            "urgency_cues": sorted(set(urgency_cues)),
            "payment_methods": payment_methods,
            "geo_signals": geo_signals,
            "prices_found": prices_found,
            "actor_aliases": actor_aliases,
            "critical_signal": min(1.0, critical_signal),
        }

    def score_batch(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not messages:
            return {
                "caas_likelihood": 0.0,
                "bot_shop_likelihood": 0.0,
                "critical_alert_score": 0.0,
                "criminal_categories": [],
                "enterprise_model": [],
                "geo_signals": [],
                "payment_methods": [],
                "urgency_signals": [],
                "actor_aliases": [],
                "recommended_action": "ignore",
                "evidence_json": json.dumps({"reason": "empty batch"}),
            }

        caas_total = 0.0
        bot_total = 0.0
        critical_total = 0.0
        categories = Counter()
        enterprise = Counter()
        geo = Counter()
        payments = Counter()
        urgency = Counter()
        aliases = Counter()
        price_hits = 0

        for msg in messages:
            result = self.score_message(msg.get("text", ""), msg.get("sender_username"))
            caas_total += result["caas_score"]
            bot_total += result["bot_score"]
            critical_total += result["critical_signal"]
            price_hits += result["prices_found"]
            categories.update(result["categories"])
            enterprise.update(result["enterprise_model"])
            geo.update(result["geo_signals"])
            payments.update(result["payment_methods"])
            urgency.update(result["urgency_cues"])
            aliases.update(result["actor_aliases"])

        message_count = max(1, len(messages))
        caas_likelihood = min(1.0, caas_total / message_count)
        bot_shop_likelihood = min(1.0, bot_total / message_count)
        critical_alert_score = min(1.0, critical_total / message_count)

        recommended_action = "ignore"
        if critical_alert_score >= 0.70 or caas_likelihood >= 0.80:
            recommended_action = "priority_archive"
        elif caas_likelihood >= 0.45:
            recommended_action = "watch"

        evidence = {
            "message_count": message_count,
            "price_hits": price_hits,
            "categories": categories.most_common(),
            "enterprise_model": enterprise.most_common(),
            "geo_signals": geo.most_common(),
            "payment_methods": payments.most_common(),
            "urgency_signals": urgency.most_common(),
            "actor_aliases": aliases.most_common(25),
        }

        return {
            "caas_likelihood": caas_likelihood,
            "bot_shop_likelihood": bot_shop_likelihood,
            "critical_alert_score": critical_alert_score,
            "criminal_categories": [label for label, _ in categories.most_common()],
            "enterprise_model": [label for label, _ in enterprise.most_common()],
            "geo_signals": [label for label, _ in geo.most_common()],
            "payment_methods": [label for label, _ in payments.most_common()],
            "urgency_signals": [label for label, _ in urgency.most_common()],
            "actor_aliases": [label for label, _ in aliases.most_common(25)],
            "recommended_action": recommended_action,
            "evidence_json": json.dumps(evidence, ensure_ascii=False),
        }
