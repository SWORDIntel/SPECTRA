from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx
from telethon import TelegramClient
from telethon.tl.types import User

from ..db import SpectraDB
from ..core.sync import Config

logger = logging.getLogger(__name__)

class IntelligenceCollector:
    """Collects and analyzes intelligence data from Telegram."""

    def __init__(self, config: Config, db: SpectraDB, client: TelegramClient):
        self.config = config
        self.db = db
        self.client = client
        # Determine data directory
        if isinstance(config.data, dict):
            self.data_dir = Path(config.data.get("data_dir", "spectra_data"))
        else:
            self.data_dir = Path("spectra_data")
            
        self.osint_dir = self.data_dir / "osint"
        self.osint_dir.mkdir(parents=True, exist_ok=True)

    async def add_target(self, username: str, notes: str = "") -> None:
        """Adds a user to the OSINT targets list."""
        try:
            logger.info(f"Attempting to add OSINT target: {username}")
            entity = await self.client.get_entity(username)
            if not isinstance(entity, User):
                logger.error(f"{username} is not a user.")
                return

            # Use db.conn directly for transactions
            self.db.conn.execute(
                """
                INSERT OR IGNORE INTO users (id, username, first_name, last_name, last_updated)
                VALUES (?, ?, ?, ?, ?)
                """,
                (entity.id, entity.username, entity.first_name, entity.last_name, datetime.now(timezone.utc).isoformat())
            )
            # Now, add to the osint_targets table
            self.db.conn.execute(
                """
                INSERT OR REPLACE INTO osint_targets (user_id, username, notes, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (entity.id, entity.username, notes, datetime.now(timezone.utc).isoformat())
            )
            # Add initial classification as target
            self.db.conn.execute(
                """
                INSERT OR IGNORE INTO actor_classification (user_id, category, confidence, last_classified_at)
                VALUES (?, ?, ?, ?)
                """,
                (entity.id, "target", 1.0, datetime.now(timezone.utc).isoformat())
            )
            self.db.conn.commit()
            logger.info(f"Successfully added {username} (ID: {entity.id}) to OSINT targets.")

        except Exception as e:
            logger.error(f"Failed to add OSINT target {username}: {e}")

    async def remove_target(self, username: str) -> None:
        """Removes a user from the OSINT targets list."""
        try:
            logger.info(f"Attempting to remove OSINT target: {username}")
            cursor = self.db.conn.execute("SELECT user_id FROM osint_targets WHERE username = ?", (username,))
            target = cursor.fetchone()
            if not target:
                logger.warning(f"Target {username} not found in OSINT targets.")
                return

            self.db.conn.execute("DELETE FROM osint_targets WHERE user_id = ?", (target[0],))
            self.db.conn.commit()
            logger.info(f"Successfully removed {username} from OSINT targets.")

        except Exception as e:
            logger.error(f"Failed to remove OSINT target {username}: {e}")

    async def list_targets(self) -> list[dict]:
        """Lists all OSINT targets."""
        try:
            cursor = self.db.conn.execute("SELECT user_id, username, notes, created_at FROM osint_targets")
            rows = cursor.fetchall()
            return [{"user_id": r[0], "username": r[1], "notes": r[2], "created_at": r[3]} for r in rows]
        except Exception as e:
            logger.error(f"Failed to list OSINT targets: {e}")
            return []

    async def scan_channel(self, channel_id: int | str, username: str) -> None:
        """Scans a channel for interactions involving the target user."""
        try:
            logger.info(f"Starting OSINT scan for {username} in channel {channel_id}.")

            # Get the target user's ID
            cursor = self.db.conn.execute("SELECT user_id FROM osint_targets WHERE username = ?", (username,))
            target_row = cursor.fetchone()
            if not target_row:
                logger.error(f"User {username} is not an OSINT target.")
                return
            target_user_id = target_row[0]

            channel_entity = await self.client.get_entity(channel_id)

            async for message in self.client.iter_messages(channel_entity, limit=1000): # Limit for safety
                if not message.sender_id:
                    continue

                # Interaction type 1: Target user replies to someone
                if message.sender_id == target_user_id and message.reply_to_msg_id:
                    reply_to_msg = await self.client.get_messages(channel_entity, ids=message.reply_to_msg_id)
                    if reply_to_msg and reply_to_msg.sender_id:
                        interaction_user_id = reply_to_msg.sender_id
                        await self._log_interaction(target_user_id, interaction_user_id, "reply_to", channel_entity.id, message.id)

                # Interaction type 2: Someone replies to the target user
                if message.reply_to_msg_id:
                    reply_to_msg = await self.client.get_messages(channel_entity, ids=message.reply_to_msg_id)
                    if reply_to_msg and reply_to_msg.sender_id == target_user_id:
                        interaction_user_id = message.sender_id
                        await self._log_interaction(interaction_user_id, target_user_id, "reply_from", channel_entity.id, message.id)

            logger.info(f"Finished OSINT scan for {username} in channel {channel_id}.")

        except Exception as e:
            logger.error(f"Failed to scan channel {channel_id} for {username}: {e}")

    async def _log_interaction(self, source_user_id: int, target_user_id: int, interaction_type: str, channel_id: int, message_id: int):
        """Saves an interaction to the database."""
        try:
            # Ensure both users are in the 'users' table
            for user_id in [source_user_id, target_user_id]:
                try:
                    user_entity = await self.client.get_entity(user_id)
                    if isinstance(user_entity, User):
                        self.db.conn.execute(
                            """
                            INSERT OR IGNORE INTO users (id, username, first_name, last_name, last_updated)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (user_entity.id, user_entity.username, user_entity.first_name, user_entity.last_name, datetime.now(timezone.utc).isoformat())
                        )
                except Exception as e:
                    logger.debug(f"Could not resolve user {user_id}: {e}")

            # Log the interaction
            self.db.conn.execute(
                """
                INSERT INTO osint_interactions (source_user_id, target_user_id, interaction_type, channel_id, message_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (source_user_id, target_user_id, interaction_type, channel_id, message_id, datetime.now(timezone.utc).isoformat())
            )
            self.db.conn.commit()
            logger.debug(f"Logged interaction: {source_user_id} -> {target_user_id} in channel {channel_id}")

        except Exception as e:
            logger.error(f"Failed to log interaction: {e}")

    async def get_network(self, username: str) -> list[dict]:
        """Retrieves the interaction network for a given user."""
        try:
            cursor = self.db.conn.execute("SELECT user_id FROM osint_targets WHERE username = ?", (username,))
            target_row = cursor.fetchone()
            if not target_row:
                logger.error(f"User {username} is not an OSINT target.")
                return []
            target_user_id = target_row[0]

            cursor = self.db.conn.execute(
                """
                SELECT source_user_id, target_user_id, interaction_type, channel_id, message_id, timestamp
                FROM osint_interactions
                WHERE source_user_id = ? OR target_user_id = ?
                """,
                (target_user_id, target_user_id)
            )
            rows = cursor.fetchall()
            return [
                {
                    "source_user_id": r[0],
                    "target_user_id": r[1],
                    "interaction_type": r[2],
                    "channel_id": r[3],
                    "message_id": r[4],
                    "timestamp": r[5],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get network for {username}: {e}")
            return []

    async def classify_actor(self, user_id: int) -> Dict[str, Any]:
        """
        Classifies a threat actor based on their activity patterns.
        Categories: scammer, vendor, broker, bot, target, researcher, unknown
        """
        try:
            # 1. Get user messages
            cursor = self.db.conn.execute(
                "SELECT content, date FROM messages WHERE user_id = ? ORDER BY date DESC LIMIT 100",
                (user_id,)
            )
            messages = cursor.fetchall()
            
            if not messages:
                # Check if it's already a target
                cursor = self.db.conn.execute("SELECT 1 FROM osint_targets WHERE user_id = ?", (user_id,))
                if cursor.fetchone():
                    return {"category": "target", "confidence": 1.0}
                return {"category": "unknown", "confidence": 0.0}

            # 2. Get CAAS profile if exists
            # Note: We need to handle the case where CAAS tables might not be fully initialized or linked
            caas_rows = []
            try:
                cursor = self.db.conn.execute(
                    """
                    SELECT service_categories, confidence FROM caas_message_profile 
                    WHERE (channel_id, message_id) IN (SELECT channel_id, id FROM messages WHERE user_id = ?) 
                    LIMIT 10
                    """,
                    (user_id,)
                )
                caas_rows = cursor.fetchall()
            except Exception:
                pass
            
            # Analyze patterns
            content_stream = " ".join([m[0] for m in messages if m[0]]).lower()
            
            category = "unknown"
            confidence = 0.5
            
            # Simple keyword-based classification logic
            scam_keywords = ["scam", "fraud", "fake", "ripped", "blacklist", "scammer"]
            vendor_keywords = ["sell", "buy", "price", "stock", "shop", "service", "payment", "escrow", "crypto", "btc", "usdt"]
            broker_keywords = ["middleman", "dm for info", "verified", "vouch", "trusted", "broker", "escrow"]
            
            scam_hits = sum(1 for k in scam_keywords if k in content_stream)
            vendor_hits = sum(1 for k in vendor_keywords if k in content_stream)
            broker_hits = sum(1 for k in broker_keywords if k in content_stream)
            
            if scam_hits > vendor_hits and scam_hits > broker_hits:
                category = "scammer"
            elif vendor_hits > scam_hits and vendor_hits > broker_hits:
                category = "vendor"
            elif broker_hits > vendor_hits:
                category = "broker"
            
            # Refine with CAAS data
            if caas_rows:
                category = "vendor"
                confidence = max(confidence, max(r[1] for r in caas_rows))

            # Save classification
            activity_profile = {
                "message_count": len(messages),
                "scam_hits": scam_hits,
                "vendor_hits": vendor_hits,
                "broker_hits": broker_hits,
                "last_active": messages[0][1] if messages else None
            }
            
            self.db.conn.execute(
                """
                INSERT INTO actor_classification (user_id, category, confidence, activity_profile, last_classified_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    category=excluded.category,
                    confidence=excluded.confidence,
                    activity_profile=excluded.activity_profile,
                    last_classified_at=excluded.last_classified_at
                """,
                (user_id, category, confidence, json.dumps(activity_profile), datetime.now(timezone.utc).isoformat())
            )
            self.db.conn.commit()
            
            return {"category": category, "confidence": confidence, "profile": activity_profile}

        except Exception as e:
            logger.error(f"Failed to classify actor {user_id}: {e}")
            return {"category": "error", "error": str(e)}

    async def generate_interaction_web(self, username: str, output_file: Optional[str] = None) -> str:
        """
        Generates a visual interaction web for a target user.
        Returns the path to the generated image.
        """
        try:
            from matplotlib import pyplot as plt
            
            network = await self.get_network(username)
            if not network:
                logger.warning(f"No interactions found for {username}")
                return ""

            G = nx.MultiDiGraph()
            
            # Add nodes and edges
            user_labels = {}
            for interaction in network:
                src = interaction["source_user_id"]
                dst = interaction["target_user_id"]
                itype = interaction["interaction_type"]
                
                G.add_edge(src, dst, type=itype)
                
                # Attempt to get usernames for labels
                for uid in [src, dst]:
                    if uid not in user_labels:
                        cursor = self.db.conn.execute("SELECT username FROM users WHERE id = ?", (uid,))
                        row = cursor.fetchone()
                        user_labels[uid] = row[0] if row and row[0] else str(uid)

            # Draw the graph
            plt.figure(figsize=(12, 12))
            pos = nx.spring_layout(G, k=0.5, iterations=50)
            
            # Draw nodes
            nx.draw_networkx_nodes(G, pos, node_size=2000, node_color='skyblue', alpha=0.8)
            
            # Draw labels
            nx.draw_networkx_labels(G, pos, labels=user_labels, font_size=10, font_weight='bold')
            
            # Draw edges with different colors for different types
            edge_colors = {'reply_to': 'blue', 'reply_from': 'green', 'mention': 'orange'}
            for itype, color in edge_colors.items():
                edges = [(u, v) for u, v, d in G.edges(data=True) if d['type'] == itype]
                if edges:
                    nx.draw_networkx_edges(G, pos, edgelist=edges, edge_color=color, 
                                         arrowsize=20, label=itype, connectionstyle='arc3,rad=0.1')

            plt.title(f"Interaction Web for {username}")
            plt.legend(scatterpoints=1)
            plt.axis('off')

            if not output_file:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = str(self.osint_dir / f"interaction_web_{username}_{timestamp}.png")
            
            plt.savefig(output_file, bbox_inches='tight', dpi=300)
            plt.close()
            
            logger.info(f"Interaction web generated: {output_file}")
            return output_file

        except ImportError:
            logger.error("matplotlib is required for interaction web generation.")
            return "error: matplotlib_missing"
        except Exception as e:
            logger.error(f"Failed to generate interaction web for {username}: {e}")
            return f"error: {str(e)}"
