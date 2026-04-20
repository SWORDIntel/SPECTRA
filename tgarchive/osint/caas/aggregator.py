from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List

from tgarchive.db import SpectraDB

class ActorDossierAggregator:
    """Aggregates CaaS message profiles into a comprehensive threat actor dossier."""
    
    def __init__(self, db: SpectraDB):
        self.db = db

    def generate_dossier(self, actor_handle: str) -> Dict[str, Any]:
        """Generates a comprehensive CaaS dossier for a specific threat actor."""
        query = "SELECT detected_at, service_categories, enterprise_model, payment_methods, delivery_model, raw_json FROM caas_message_profile WHERE seller_aliases LIKE ?"
        cursor = self.db.conn.execute(query, (f'%"{actor_handle}"%',))
        rows = cursor.fetchall()

        services: Counter[str] = Counter()
        enterprise_models: Counter[str] = Counter()
        payments: Counter[str] = Counter()
        prices: List[Dict[str, Any]] = []

        for row in rows:
            detected_at, s_cats_json, e_model_json, p_meth_json, delivery, raw_json_str = row
            try:
                services.update(json.loads(s_cats_json or "[]"))
                enterprise_models.update(json.loads(e_model_json or "[]"))
                payments.update(json.loads(p_meth_json or "[]"))
                
                raw_data = json.loads(raw_json_str or "{}")
                for price_obs in raw_data.get("prices", []):
                    price_obs["detected_at"] = detected_at
                    prices.append(price_obs)
            except Exception:
                continue

        prices.sort(key=lambda x: x.get("detected_at", ""))

        caas_severity = 0.0
        if "initial_access" in services or "malware_loader" in services:
            caas_severity += 0.8
        elif "phishing_kit" in services or "stealer_logs" in services:
            caas_severity += 0.6
        elif "cashout_service" in services:
            caas_severity += 0.5
        elif services:
            caas_severity += 0.3

        if len(prices) > 5:
            caas_severity += 0.2

        caas_severity = min(1.0, caas_severity)

        # Calculate service consistency score: (most common service count / total service mentions)
        total_service_mentions = sum(services.values())
        consistency_score = 0.0
        if total_service_mentions > 0:
            most_common_count = services.most_common(1)[0][1]
            consistency_score = round(most_common_count / total_service_mentions, 2)

        return {
            "actor_handle": actor_handle,
            "message_count": len(rows),
            "top_services": services.most_common(),
            "enterprise_models": enterprise_models.most_common(),
            "payment_methods": payments.most_common(),
            "price_history": prices,
            "caas_severity": caas_severity,
            "service_consistency_score": consistency_score
        }

    def get_top_actors(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Returns actors enriched with their top services."""
        query = "SELECT canonical_handle FROM actor_entity ORDER BY last_seen DESC LIMIT ?"
        cursor = self.db.conn.execute(query, (limit,))
        actors = []
        for (handle,) in cursor:
            dossier = self.generate_dossier(handle)
            if dossier["message_count"] > 0:
                actors.append(dossier)
        return sorted(actors, key=lambda x: x["caas_severity"], reverse=True)
