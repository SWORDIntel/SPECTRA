from __future__ import annotations

import json
from typing import Dict, Any, List, Optional

class NarrativeSynthesisEngine:
    """Generates high-level intelligence summaries from actor dossiers."""
    
    def synthesize_actor_brief(self, dossier: Dict[str, Any], wallets: Dict[str, List[str]], nexus: List[str]) -> str:
        """Creates a readable intelligence briefing."""
        handle = dossier.get("actor_handle", "UNKNOWN")
        services = [s[0] for s in dossier.get("top_services", [])]
        msgs = dossier.get("message_count", 0)
        sev = dossier.get("caas_severity", 0.0)
        
        # Determine archetype
        archetype = "General Vendor"
        if "initial_access" in services:
            archetype = "Initial Access Broker (IAB)"
        elif "malware_loader" in services:
            archetype = "Malware Distributor"
        elif "cashout_service" in services:
            archetype = "Financial Launderer"
            
        summary = f"Actor @{handle} is profiled as a high-risk {archetype}. "
        summary += f"Operational footprint includes {msgs} recorded events across multiple CaaS channels. "
        
        if services:
            summary += f"Specializes in {', '.join(services[:3])}. "
        
        if wallets:
            summary += f"Observed payment methods involve {', '.join(wallets.keys())} infrastructure. "
            
        if nexus:
            summary += f"Infrastructure nexus analysis links this entity to {len(nexus)} shared artifacts, indicating coordinated group activity. "
            
        if sev > 0.7:
            summary += "STRATEGIC STATUS: CRITICAL THREAT. Recommend immediate escalation and infrastructure pivot analysis."
        elif sev > 0.4:
            summary += "STRATEGIC STATUS: ACTIVE INTEREST. Ongoing monitoring of service evolution required."
        else:
            summary += "STRATEGIC STATUS: MONITORING. Low-level commoditized activity."
            
        return summary.upper()

    def get_market_briefing(self, snapshot: Dict[str, Any]) -> str:
        """Synthesizes a global market briefing."""
        top = snapshot["service_rankings"][0] if snapshot["service_rankings"] else None
        if not top:
            return "NO MARKET DATA AVAILABLE FOR SYNTHESIS."
            
        brief = f"GLOBAL CAAS MARKET ANALYSIS: '{top['category'].upper()}' IS THE DOMINANT PROFIT DRIVER WITH AN ESTIMATED GMV PROXY OF ${top['estimated_market_value']:,.2f}. "
        brief += f"MARKET VOLUME IS CURRENTLY CONCENTRATED ACROSS {snapshot['total_profiles']} PROFILED ENTITIES. "
        
        currencies = [c[0] for c in snapshot.get("top_currencies", [])]
        if currencies:
            brief += f"ECONOMY REMAINS ANCHORED BY {', '.join(currencies[:3])} LIQUIDITY. "
            
        return brief
