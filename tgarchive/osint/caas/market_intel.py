from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from tgarchive.db import SpectraDB

@dataclass
class ServiceStats:
    category: str
    mention_count: int
    avg_price: float
    max_price: float
    min_price: float
    currencies: List[str]
    volatility_index: float = 0.0
    p25: float = 0.0
    p50: float = 0.0
    p75: float = 0.0

class CurrencyConverter:
    """Hardcoded baseline rates for market normalization."""
    RATES = {
        "BTC": 65000.0,
        "XMR": 150.0,
        "USDT": 1.0,
        "USD": 1.0,
        "$": 1.0
    }

    @classmethod
    def convert_to_usd(cls, amount: float, currency: Optional[str]) -> float:
        if not currency:
            return amount
        rate = cls.RATES.get(currency.upper(), 1.0)
        return amount * rate

class MarketIntelligenceEngine:
    """Analyzes global CaaS market trends, pricing, and service demand."""

    def __init__(self, db: SpectraDB):
        self.db = db

    def get_market_snapshot(self, end_date: Optional[str] = None) -> Dict[str, Any]:
        """Returns a global snapshot of the CaaS economy normalized to USD."""
        query = "SELECT service_categories, raw_json FROM caas_message_profile"
        params = []
        if end_date:
            query += " WHERE detected_at <= ?"
            params.append(end_date)
            
        cursor = self.db.conn.execute(query, params)
        rows = cursor.fetchall()

        category_prices: Dict[str, List[float]] = defaultdict(list)
        category_counts: Counter[str] = Counter()
        currency_counts: Counter[str] = Counter()

        for s_cats_json, raw_json_str in rows:
            try:
                cats = json.loads(s_cats_json or "[]")
                raw_data = json.loads(raw_json_str or "{}")
                prices = raw_data.get("prices", [])

                for cat in cats:
                    category_counts[cat] += 1
                    for p in prices:
                        amount = p.get("amount_min") or p.get("amount_max")
                        if amount:
                            currency = p.get("currency", "USD")
                            usd_amount = CurrencyConverter.convert_to_usd(float(amount), currency)
                            category_prices[cat].append(usd_amount)
                            if p.get("currency"):
                                currency_counts[p["currency"]] += 1
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        stats: List[Dict[str, Any]] = []
        for cat, prices in category_prices.items():
            if not prices:
                continue
            
            prices.sort()
            avg = statistics.mean(prices)
            std_dev = statistics.stdev(prices) if len(prices) > 1 else 0.0
            
            # Calculate percentiles
            p25 = statistics.quantiles(prices, n=4)[0] if len(prices) >= 2 else prices[0]
            p50 = statistics.median(prices)
            p75 = statistics.quantiles(prices, n=4)[2] if len(prices) >= 2 else prices[0]

            stats.append({
                "category": cat,
                "mentions": category_counts[cat],
                "avg_price": round(avg, 2),
                "max_price": max(prices),
                "min_price": min(prices),
                "price_p25": round(p25, 2),
                "price_p50": round(p50, 2),
                "price_p75": round(p75, 2),
                "market_share_by_volume": round(category_counts[cat] / sum(category_counts.values()) * 100, 2),
                "estimated_market_value": round(category_counts[cat] * avg, 2),
                "volatility": round(std_dev / avg if avg > 0 else 0, 4)
            })

        # Sort by Estimated Market Value
        stats.sort(key=lambda x: x["estimated_market_value"], reverse=True)

        return {
            "total_profiles": len(rows),
            "top_currencies": currency_counts.most_common(5),
            "service_rankings": stats,
            "summary": self._generate_summary(stats)
        }

    def get_historical_comparison(self, days: int = 7) -> List[Dict[str, Any]]:
        """Compares current snapshot against a 7-day-old baseline."""
        import datetime
        
        current_snapshot = self.get_market_snapshot()
        
        cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        historical_snapshot = self.get_market_snapshot(end_date=cutoff_date)
        
        # If no historical data exists, simulate it using 0.9x multiplier as requested
        use_simulation = historical_snapshot["total_profiles"] == 0
        
        comparisons = []
        historical_map = {s["category"]: s for s in historical_snapshot["service_rankings"]}
        
        for curr in current_snapshot["service_rankings"]:
            cat = curr["category"]
            curr_emv = curr["estimated_market_value"]
            
            if use_simulation:
                hist_emv = curr_emv * 0.9
            else:
                hist_entry = historical_map.get(cat)
                hist_emv = hist_entry["estimated_market_value"] if hist_entry else 0
            
            if hist_emv > 0:
                growth = ((curr_emv - hist_emv) / hist_emv) * 100
            else:
                growth = 100.0 if curr_emv > 0 else 0.0
                
            comparisons.append({
                "category": cat,
                "current_val": curr_emv,
                "historical_val": round(hist_emv, 2),
                "growth_percent": round(growth, 2),
                "status": "Growth" if growth >= 0 else "Decline"
            })
            
        return comparisons

    def detect_market_shifts(self, days: int = 7) -> List[Dict[str, Any]]:
        """Implementation of Suggestion #1: Detects anomalous pricing/volume shifts."""
        # This would ideally compare two snapshots (Current vs Historical)
        # For now, we identify high-volatility services that are deviating from the norm
        snapshot = self.get_market_snapshot()
        shifts = []
        for s in snapshot["service_rankings"]:
            if s["volatility"] > 0.5: # 50% deviation from mean price
                shifts.append({
                    "category": s["category"],
                    "type": "price_instability",
                    "severity": "high" if s["volatility"] > 1.0 else "medium",
                    "description": f"Service '{s['category']}' shows high price variance (Volatility: {s['volatility']}). Potential market dumping or premium breach entry."
                })
        return shifts

    def _generate_summary(self, stats: List[Dict[str, Any]]) -> str:
        if not stats:
            return "No market data available."
        top = stats[0]
        return f"The most profitable sector is currently '{top['category']}' with an estimated GMV of {top['estimated_market_value']} (Avg Price: {top['avg_price']})."
