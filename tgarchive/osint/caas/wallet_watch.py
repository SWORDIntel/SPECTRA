from __future__ import annotations

import re
import json
from typing import Dict, List, Any, Optional
from tgarchive.db import SpectraDB

# Regex for common crypto addresses
CRYPTO_PATTERNS = {
    "BTC": r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b|bc1[ac-hj-np-z02-9]{11,71}\b",
    "XMR": r"\b4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b",
    "ETH_ERC20": r"\b0x[a-fA-F0-9]{40}\b",
    "TRX_TRC20": r"\bT[A-Za-z1-9]{33}\b"
}

class WalletWatcher:
    """Extracts and tracks cryptocurrency wallets for threat actor attribution."""
    
    def __init__(self, db: SpectraDB):
        self.db = db

    def extract_wallets(self, text: str) -> Dict[str, List[str]]:
        found = {}
        for symbol, pattern in CRYPTO_PATTERNS.items():
            matches = re.findall(pattern, text)
            if matches:
                found[symbol] = list(set(matches))
        return found

    def get_actor_wallets(self, actor_handle: str) -> Dict[str, List[str]]:
        """Aggregates all wallets associated with an actor."""
        query = "SELECT content FROM caas_profile_queue q JOIN caas_message_profile p ON q.channel_id = p.channel_id AND q.message_id = p.message_id WHERE p.seller_aliases LIKE ?"
        cursor = self.db.conn.execute(query, (f'%"{actor_handle}"%',))
        
        all_wallets = defaultdict(set)
        for (content,) in cursor:
            wallets = self.extract_wallets(content or "")
            for sym, addrs in wallets.items():
                all_wallets[sym].update(addrs)
        
        return {sym: list(addrs) for sym, addrs in all_wallets.items()}

from collections import defaultdict

class DirectEyeLinker:
    """
    Hooks for DIRECTEYE (https://github.com/SWORDIntel/DIRECTEYE) integration.
    This class handles the handoff for advanced blockchain forensic analysis.
    """
    
    def __init__(self, api_endpoint: Optional[str] = None):
        self.api_endpoint = api_endpoint

    def query_attribution(self, wallet_address: str, currency: str) -> Dict[str, Any]:
        """
        [HOOK] Placeholder for DIRECTEYE API/Library call.
        Will return attribution data (exchanges, mixers, historical volume).
        """
        # Integration Logic:
        # try:
        #     from directeye.client import DirectEyeClient
        #     client = DirectEyeClient(self.api_endpoint)
        #     return client.analyze_address(wallet_address, currency)
        # except ImportError:
        return {"status": "directeye_not_loaded", "wallet": wallet_address, "currency": currency}
