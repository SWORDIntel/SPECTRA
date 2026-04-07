from __future__ import annotations

import re
import json
from collections import defaultdict
from typing import Dict, List, Any, Set
from tgarchive.db import SpectraDB

URL_PATTERN = r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+"
BOT_ID_PATTERN = r"(?i)bot_id[:=\s]+([0-9:A-Za-z_-]+)"

class InfrastructureNexus:
    """Maps shared infrastructure (URLs, Bot IDs, IPs) between different threat actors."""
    
    def __init__(self, db: SpectraDB):
        self.db = db

    def extract_artifacts(self, text: str) -> Dict[str, List[str]]:
        urls = re.findall(URL_PATTERN, text)
        bot_ids = re.findall(BOT_ID_PATTERN, text)
        return {
            "urls": list(set(urls)),
            "bot_ids": list(set(bot_ids))
        }

    def map_shared_nexus(self) -> List[Dict[str, Any]]:
        """Identifies actors sharing the same infrastructure artifacts."""
        query = "SELECT seller_aliases, content FROM caas_profile_queue q JOIN caas_message_profile p ON q.channel_id = p.channel_id AND q.message_id = p.message_id"
        cursor = self.db.conn.execute(query)
        
        artifact_to_actors = defaultdict(set)
        
        for aliases_json, content in cursor:
            aliases = json.loads(aliases_json or "[]")
            artifacts = self.extract_artifacts(content or "")
            
            for art_type in ["urls", "bot_ids"]:
                for val in artifacts[art_type]:
                    # Filter out common/noise URLs
                    if "t.me" in val or "google.com" in val: continue
                    for actor in aliases:
                        artifact_to_actors[val].add(actor)

        shared = []
        for artifact, actors in artifact_to_actors.items():
            if len(actors) > 1:
                shared.append({
                    "artifact": artifact,
                    "actors": list(actors),
                    "count": len(actors)
                })
        
        return sorted(shared, key=lambda x: x["count"], reverse=True)
