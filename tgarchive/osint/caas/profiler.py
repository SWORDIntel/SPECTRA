from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from typing import Any, Optional

HANDLE_RE = re.compile(r"@([A-Za-z0-9_]{4,32})")
PRICE_PATTERNS = [
    re.compile(r"(?P<currency>\$|£|€)\s?(?P<amount>\d+(?:[\.,]\d{1,2})?)", re.I),
    re.compile(r"(?P<amount>\d+(?:[\.,]\d{1,2})?)\s?(?P<currency>usd|eur|gbp|usdt|btc|xmr)", re.I),
    re.compile(r"(?P<amount_min>\d+(?:[\.,]\d{1,2})?)\s?-\s?(?P<amount_max>\d+(?:[\.,]\d{1,2})?)\s?(?P<currency>usd|eur|gbp|usdt|btc|xmr|\$|£|€)?", re.I),
]
SERVICE_PATTERNS = {
    "initial_access": [r"\brdp\b", r"\bcorp access\b", r"\bvpn access\b", r"\bpanel access\b", r"\bdomain admin\b"],
    "stealer_logs": [r"\blogs?\b", r"\bstealer\b", r"\bredline\b", r"\bvidar\b"],
    "phishing_kit": [r"\bphish(?:ing)? kit\b", r"\bmailer\b", r"\blanding page\b"],
    "malware_loader": [r"\bloader\b", r"\bcrypter\b", r"\bfud\b", r"\bdropper\b"],
    "otp_bypass": [r"\botp\b", r"\b2fa bypass\b", r"\bsim\b", r"\bswap\b"],
    "cashout_service": [r"\bcashout\b", r"\bmule\b", r"\bwithdrawal\b"],
}
ENTERPRISE_PATTERNS = {
    "marketplace": [r"\bmarket(place)?\b", r"\bshop\b"],
    "storefront": [r"\bcatalog\b", r"\bprice list\b", r"\bmenu\b"],
    "broker": [r"\bbroker\b", r"\bdirect source\b", r"\bsupplier\b"],
    "affiliate_program": [r"\baffiliate\b", r"\brevshare\b", r"\bprofit share\b"],
}
PAYMENT_PATTERNS = {
    "btc": [r"\bbtc\b", r"\bbitcoin\b"],
    "xmr": [r"\bxmr\b", r"\bmonero\b"],
    "usdt": [r"\busdt\b", r"\btether\b"],
    "escrow": [r"\bescrow\b", r"\bmiddleman\b", r"\bmm\b"],
}


def _normalize_currency(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    lookup = {
        "$": "USD",
        "£": "GBP",
        "€": "EUR",
        "usd": "USD",
        "eur": "EUR",
        "gbp": "GBP",
        "btc": "BTC",
        "xmr": "XMR",
        "usdt": "USDT",
    }
    return lookup.get(value.lower(), value.upper())


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value.replace(",", ""))
    except Exception:
        return None


@dataclass
class PriceObservation:
    raw_price_text: str
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    currency: Optional[str] = None
    billing_model: Optional[str] = None
    confidence: float = 0.0


@dataclass
class MessageProfile:
    confidence: float
    service_categories: list[str] = field(default_factory=list)
    enterprise_model: list[str] = field(default_factory=list)
    seller_aliases: list[str] = field(default_factory=list)
    payment_methods: list[str] = field(default_factory=list)
    delivery_model: Optional[str] = None
    prices: list[PriceObservation] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({
            "confidence": self.confidence,
            "service_categories": self.service_categories,
            "enterprise_model": self.enterprise_model,
            "seller_aliases": self.seller_aliases,
            "payment_methods": self.payment_methods,
            "delivery_model": self.delivery_model,
            "prices": [asdict(p) for p in self.prices],
        }, ensure_ascii=False)


class CAASProfiler:
    """Layer 1: slower message-level profiler for queue processing.

    This remains deterministic in the first pass so it is auditable and easy
    to iterate against archived historical data.
    """

    def _find_labels(self, text: str, mapping: dict[str, list[str]]) -> list[str]:
        out: list[str] = []
        for label, patterns in mapping.items():
            if any(re.search(pattern, text, re.I) for pattern in patterns):
                out.append(label)
        return sorted(set(out))

    def _extract_prices(self, text: str) -> list[PriceObservation]:
        prices: list[PriceObservation] = []
        for pattern in PRICE_PATTERNS:
            for match in pattern.finditer(text):
                gd = match.groupdict()
                amount = _to_float(gd.get("amount"))
                amount_min = _to_float(gd.get("amount_min"))
                amount_max = _to_float(gd.get("amount_max"))
                prices.append(
                    PriceObservation(
                        raw_price_text=match.group(0),
                        amount_min=amount if amount is not None else amount_min,
                        amount_max=amount if amount is not None else amount_max,
                        currency=_normalize_currency(gd.get("currency")),
                        billing_model="subscription" if re.search(r"/month|monthly|/week|weekly", text, re.I) else "one_off",
                        confidence=0.75,
                    )
                )
        return prices

    def profile_message(self, content: str, sender_username: Optional[str] = None) -> MessageProfile:
        normalized = re.sub(r"\s+", " ", (content or "").strip().lower())
        service_categories = self._find_labels(normalized, SERVICE_PATTERNS)
        enterprise_model = self._find_labels(normalized, ENTERPRISE_PATTERNS)
        payment_methods = self._find_labels(normalized, PAYMENT_PATTERNS)
        aliases = sorted(set(HANDLE_RE.findall(content or "")))
        if sender_username:
            aliases = sorted(set(aliases + [sender_username]))
        prices = self._extract_prices(normalized)

        confidence = 0.10
        if service_categories:
            confidence += 0.45
        if prices:
            confidence += 0.20
        if payment_methods:
            confidence += 0.10
        if enterprise_model:
            confidence += 0.10
        if aliases:
            confidence += 0.05

        delivery_model = None
        if re.search(r"\b(per month|monthly|/month|weekly|/week)\b", normalized, re.I):
            delivery_model = "subscription"
        elif re.search(r"\brevshare\b|profit share", normalized, re.I):
            delivery_model = "revshare"
        elif re.search(r"\bdeposit\b|upfront", normalized, re.I):
            delivery_model = "deposit"
        else:
            delivery_model = "one_off"

        return MessageProfile(
            confidence=min(confidence, 0.99),
            service_categories=service_categories,
            enterprise_model=enterprise_model,
            seller_aliases=aliases,
            payment_methods=payment_methods,
            delivery_model=delivery_model,
            prices=prices,
        )

    def save_profile(self, db: Any, channel_id: int, message_id: int, profile: MessageProfile) -> None:
        now = __import__("datetime").datetime.utcnow().isoformat()
        db.conn.execute(
            """
            INSERT INTO caas_message_profile
            (channel_id, message_id, detected_at, confidence, service_categories, enterprise_model, seller_aliases, delivery_model, payment_methods, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                channel_id,
                message_id,
                now,
                profile.confidence,
                json.dumps(profile.service_categories),
                json.dumps(profile.enterprise_model),
                json.dumps(profile.seller_aliases),
                profile.delivery_model,
                json.dumps(profile.payment_methods),
                profile.to_json(),
            ),
        )
