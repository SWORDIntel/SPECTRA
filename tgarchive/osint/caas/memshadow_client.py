from __future__ import annotations

import os
import json
import logging
import requests
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class MemshadowClient:
    """
    Client for interacting with the MEMSHADOW sidecar.
    Provides advanced semantic memory persistence for SPECTRA intelligence.
    """
    
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = base_url or os.getenv("SPECTRA_MEMSHADOW_URL", "http://memshadow:18080")
        self.api_key = api_key or os.getenv("SPECTRA_MEMSHADOW_API_KEY", "1786")
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def index_actor_dossier(self, dossier: Dict[str, Any]) -> bool:
        """Indexes a threat actor dossier into MEMSHADOW semantic memory."""
        handle = dossier.get("actor_handle", "UNKNOWN")
        content = f"THREAT ACTOR DOSSIER: @{handle}\n"
        content += f"Services: {', '.join([s[0] for s in dossier.get('top_services', [])])}\n"
        content += f"CaaS Severity: {dossier.get('caas_severity', 0.0)}\n"
        
        # Add price history context
        if dossier.get("price_history"):
            content += "Price Observations:\n"
            for p in dossier["price_history"][:5]:
                content += f"- {p.get('amount_min')} {p.get('currency')} for {p.get('billing_model')}\n"

        payload = {
            "content": content,
            "extra_data": {
                "source": "SPECTRA",
                "type": "actor_dossier",
                "handle": handle,
                "severity": dossier.get("caas_severity", 0.0)
            }
        }
        
        try:
            res = requests.post(f"{self.base_url}/api/v1/memories", json=payload, headers=self.headers, timeout=5)
            return res.status_code == 200
        except Exception as e:
            logger.error(f"Failed to index dossier in MEMSHADOW: {e}")
            return False

    def semantic_recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Performs semantic search across indexed SPECTRA memories."""
        payload = {
            "query": query,
            "expand_query": True
        }
        
        try:
            res = requests.post(f"{self.base_url}/api/v1/memories/search?limit={limit}", json=payload, headers=self.headers, timeout=5)
            if res.status_code == 200:
                return res.json()
            return []
        except Exception as e:
            logger.error(f"MEMSHADOW semantic recall failed: {e}")
            return []

    def get_health(self) -> Dict[str, Any]:
        """Checks the health of the MEMSHADOW sidecar."""
        try:
            res = requests.get(f"{self.base_url}/health", timeout=2)
            return res.json() if res.status_code == 200 else {"status": "unhealthy"}
        except Exception as e:
            return {"status": "unavailable", "error": str(e)}
