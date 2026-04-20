from __future__ import annotations

import asyncio
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from tgarchive.db import SpectraDB
from tgarchive.osint.caas.discovery_ops import discover_with_caas
from tgarchive.osint.caas.queue_worker import process_queue
from tgarchive.osint.caas.aggregator import ActorDossierAggregator

logger = logging.getLogger(__name__)

class AutonomousIntelligenceCoordinator:
    """
    Orchestrates the autonomous lifecycle of Telegram intelligence:
    Discovery -> Archival -> Profiling -> Analysis.
    """
    
    def __init__(self, config_path: Path, db_path: Path):
        self.config_path = config_path
        self.db_path = db_path
        self.db = SpectraDB(db_path)
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        
        # Operational stats
        self.stats = {
            "last_discovery": None,
            "last_profiling": None,
            "total_cycles": 0,
            "active_tasks": [],
            "errors": []
        }

    async def run_cycle(self):
        """Runs a single autonomous intelligence cycle."""
        logger.info("Starting autonomous intelligence cycle...")
        self.stats["total_cycles"] += 1
        
        try:
            # 1. Discovery Phase (Target Harvesting)
            # Pull high-probability seeds from existing profiles or config
            seeds = self._get_discovery_seeds()
            for seed in seeds:
                logger.info(f"Initiating autonomous discovery for seed: {seed}")
                self.stats["active_tasks"].append(f"Discovery: {seed}")
                await discover_with_caas(
                    config_path=str(self.config_path),
                    db_path=str(self.db_path),
                    data_dir="spectra_data",
                    seed=seed,
                    depth=1,
                    max_messages=200
                )
                self.stats["active_tasks"].pop()
            
            self.stats["last_discovery"] = datetime.now().isoformat()

            # 2. Profiling Phase (Message Triage)
            logger.info("Initiating autonomous queue profiling...")
            self.stats["active_tasks"].append("Profiling Queue")
            processed = process_queue(db_path=str(self.db_path), batch_size=500, once=True)
            logger.info(f"Processed {processed} items from intelligence queue.")
            self.stats["active_tasks"].pop()
            self.stats["last_profiling"] = datetime.now().isoformat()

            # 3. Analysis Phase (Dossier Update)
            # (Aggregation is lazy-loaded in the UI, but we could pre-cache here)
            
        except Exception as e:
            logger.exception("Error in autonomous intelligence cycle")
            self.stats["errors"].append(f"{datetime.now().isoformat()}: {str(e)}")
            if len(self.stats["errors"]) > 10:
                self.stats["errors"].pop(0)

    def _get_discovery_seeds(self) -> List[str]:
        """Harvests seeds for the next discovery pass, prioritizing high-risk sectors."""
        # Logic: Pick channels with high critical_alert_score or those linked to profitable services
        query = """
            SELECT channel_link FROM caas_channel_profile 
            WHERE (critical_alert_score > 0.7 OR caas_likelihood > 0.8)
            AND (last_crawled IS NULL OR last_crawled < datetime('now', '-24 hours'))
            ORDER BY critical_alert_score DESC LIMIT 5
        """
        rows = self.db.conn.execute(query).fetchall()
        seeds = [r[0] for r in rows if r[0]]
        
        # Fallback to defaults if no high-risk targets found
        if not seeds:
            seeds = ["@seed_caas_example", "@iab_market_monitor"]
            
        return seeds

    async def _rotate_accounts(self):
        """[POLISH] Logic to check for account health and rotate session strings."""
        # This hook allows the coordinator to swap accounts in the config
        # if a FloodWaitError is detected in the underlying sync/discovery modules.
        pass

    async def start(self, interval_minutes: int = 60):
        """Starts the autonomous coordinator loop."""
        if self.is_running:
            return
        
        self.is_running = True
        logger.info(f"Autonomous Intelligence Coordinator started (Interval: {interval_minutes}m)")
        
        while self.is_running:
            await self.run_cycle()
            logger.info(f"Cycle complete. Sleeping for {interval_minutes} minutes...")
            await asyncio.sleep(interval_minutes * 60)

    def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
