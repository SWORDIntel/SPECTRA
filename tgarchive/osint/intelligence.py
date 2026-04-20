from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import networkx as nx
from telethon import TelegramClient
from telethon.tl.types import User

from ..db import SpectraDB
from ..core.sync import Config

logger = logging.getLogger(__name__)


class _SyncAsyncConnection:
    """Async context manager over a synchronous sqlite connection."""

    def __init__(self, connection):
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type:
            self._connection.rollback()
        else:
            self._connection.commit()
        return False


class IntelligenceCollector:
    """Collects and analyzes intelligence data from Telegram."""

    def __init__(self, config: Config, db: SpectraDB, client: TelegramClient):
        self.config = config
        self.db = db
        self.client = client

        if isinstance(config.data, dict):
            self.data_dir = Path(config.data.get("data_dir", "spectra_data"))
        else:
            self.data_dir = Path("spectra_data")

        self.osint_dir = self.data_dir / "osint"
        self.osint_dir.mkdir(parents=True, exist_ok=True)

    async def _connection_cm(self):
        """Return an async context manager for either a real or mocked DB."""
        connect = getattr(self.db, "connect", None)
        if connect is not None:
            candidate = connect()
            if asyncio.iscoroutine(candidate):
                candidate = await candidate
            if hasattr(candidate, "__aenter__") and hasattr(candidate, "__aexit__"):
                return candidate

        connection = getattr(self.db, "conn", None)
        if connection is None:
            raise AttributeError("Database object does not expose a usable connection")
        return _SyncAsyncConnection(connection)

    async def _execute(self, conn, sql: str, params=()):
        """Execute SQL against either async or sync connection implementations."""
        result = conn.execute(sql, params)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    async def _fetchone(self, cursor):
        result = cursor.fetchone()
        if asyncio.iscoroutine(result):
            result = await result
        return result

    async def _fetchall(self, cursor):
        result = cursor.fetchall()
        if asyncio.iscoroutine(result):
            result = await result
        return result

    async def add_target(self, username: str, notes: str = "") -> None:
        """Adds a user to the OSINT targets list."""
        try:
            logger.info(f"Attempting to add OSINT target: {username}")
            entity = await self.client.get_entity(username)
            if not isinstance(entity, User) and not hasattr(entity, "id"):
                logger.error(f"{username} is not a user.")
                return

            now = datetime.now(timezone.utc).isoformat()

            async with await self._connection_cm() as conn:
                await self._execute(
                    conn,
                    """
                    INSERT OR IGNORE INTO users (id, username, first_name, last_name, last_updated)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (entity.id, entity.username, entity.first_name, entity.last_name, now),
                )

                await self._execute(
                    conn,
                    """
                    INSERT OR REPLACE INTO osint_targets (user_id, username, notes, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (entity.id, entity.username, notes, now),
                )

                await self._execute(
                    conn,
                    """
                    INSERT OR IGNORE INTO actor_classification (user_id, category, confidence, last_classified_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (entity.id, "target", 1.0, now),
                )

            logger.info(f"Successfully added {username} (ID: {entity.id}) to OSINT targets.")

        except Exception as e:
            logger.error(f"Failed to add OSINT target {username}: {e}")

    async def remove_target(self, username: str) -> None:
        """Removes a user from the OSINT targets list."""
        try:
            logger.info(f"Attempting to remove OSINT target: {username}")

            async with await self._connection_cm() as conn:
                cursor = await self._execute(
                    conn,
                    "SELECT user_id FROM osint_targets WHERE username = ?",
                    (username,),
                )
                target = await self._fetchone(cursor)

                if not target:
                    logger.warning(f"Target {username} not found in OSINT targets.")
                    return

                await self._execute(
                    conn,
                    "DELETE FROM osint_targets WHERE user_id = ?",
                    (target[0],),
                )

            logger.info(f"Successfully removed {username} from OSINT targets.")

        except Exception as e:
            logger.error(f"Failed to remove OSINT target {username}: {e}")

    async def list_targets(self) -> list[dict]:
        """Lists all OSINT targets."""
        try:
            async with await self._connection_cm() as conn:
                cursor = await self._execute(
                    conn,
                    "SELECT user_id, username, notes, created_at FROM osint_targets",
                )
                rows = await self._fetchall(cursor)
                return [
                    {
                        "user_id": r[0],
                        "username": r[1],
                        "notes": r[2],
                        "created_at": r[3],
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"Failed to list OSINT targets: {e}")
            return []

    async def scan_channel(self, channel_id: int | str, username: str) -> None:
        """Scans a channel for interactions involving the target user."""
        try:
            logger.info(f"Starting OSINT scan for {username} in channel {channel_id}.")

            async with await self._connection_cm() as conn:
                cursor = await self._execute(
                    conn,
                    "SELECT user_id FROM osint_targets WHERE username = ?",
                    (username,),
                )
                target_row = await self._fetchone(cursor)
                if not target_row:
                    logger.error(f"User {username} is not an OSINT target.")
                    return
                target_user_id = target_row[0]

            channel_entity = await self.client.get_entity(channel_id)

            messages_iter = self.client.iter_messages(channel_entity, limit=1000)
            if asyncio.iscoroutine(messages_iter):
                messages_iter = await messages_iter

            async for message in messages_iter:
                if not message.sender_id:
                    continue

                if message.sender_id == target_user_id and message.reply_to_msg_id:
                    reply_to_msg = await self.client.get_messages(
                        channel_entity, ids=message.reply_to_msg_id
                    )
                    if reply_to_msg and reply_to_msg.sender_id:
                        interaction_user_id = reply_to_msg.sender_id
                        await self._log_interaction(
                            target_user_id,
                            interaction_user_id,
                            "reply_to",
                            channel_entity.id,
                            message.id,
                        )

                if message.reply_to_msg_id:
                    reply_to_msg = await self.client.get_messages(
                        channel_entity, ids=message.reply_to_msg_id
                    )
                    if reply_to_msg and reply_to_msg.sender_id == target_user_id:
                        interaction_user_id = message.sender_id
                        await self._log_interaction(
                            interaction_user_id,
                            target_user_id,
                            "reply_from",
                            channel_entity.id,
                            message.id,
                        )

            logger.info(f"Finished OSINT scan for {username} in channel {channel_id}.")

        except Exception as e:
            logger.error(f"Failed to scan channel {channel_id} for {username}: {e}")

    async def _log_interaction(
        self,
        source_user_id: int,
        target_user_id: int,
        interaction_type: str,
        channel_id: int,
        message_id: int,
    ) -> None:
        """Saves an interaction to the database."""
        try:
            now = datetime.now(timezone.utc).isoformat()

            async with await self._connection_cm() as conn:
                for user_id in [source_user_id, target_user_id]:
                    try:
                        user_entity = await self.client.get_entity(user_id)
                        if isinstance(user_entity, User):
                            await self._execute(
                                conn,
                                """
                                INSERT OR IGNORE INTO users (id, username, first_name, last_name, last_updated)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    user_entity.id,
                                    user_entity.username,
                                    user_entity.first_name,
                                    user_entity.last_name,
                                    now,
                                ),
                            )
                    except Exception as e:
                        logger.debug(f"Could not resolve user {user_id}: {e}")

                await self._execute(
                    conn,
                    """
                    INSERT INTO osint_interactions
                    (source_user_id, target_user_id, interaction_type, channel_id, message_id, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_user_id,
                        target_user_id,
                        interaction_type,
                        channel_id,
                        message_id,
                        now,
                    ),
                )

            logger.debug(
                f"Logged interaction: {source_user_id} -> {target_user_id} in channel {channel_id}"
            )

        except Exception as e:
            logger.error(f"Failed to log interaction: {e}")

    async def get_network(self, username: str) -> list[dict]:
        """Retrieves the interaction network for a given user."""
        try:
            async with await self._connection_cm() as conn:
                cursor = await self._execute(
                    conn,
                    "SELECT user_id FROM osint_targets WHERE username = ?",
                    (username,),
                )
                target_row = await self._fetchone(cursor)
                if not target_row:
                    logger.error(f"User {username} is not an OSINT target.")
                    return []
                target_user_id = target_row[0]

                cursor = await self._execute(
                    conn,
                    """
                    SELECT source_user_id, target_user_id, interaction_type, channel_id, message_id, timestamp
                    FROM osint_interactions
                    WHERE source_user_id = ? OR target_user_id = ?
                    """,
                    (target_user_id, target_user_id),
                )
                rows = await self._fetchall(cursor)

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
            async with await self._connection_cm() as conn:
                cursor = await self._execute(
                    conn,
                    "SELECT content, date FROM messages WHERE user_id = ? ORDER BY date DESC LIMIT 100",
                    (user_id,),
                )
                messages = await self._fetchall(cursor)

                if not messages:
                    cursor = await self._execute(
                        conn,
                        "SELECT 1 FROM osint_targets WHERE user_id = ?",
                        (user_id,),
                    )
                    if await self._fetchone(cursor):
                        return {"category": "target", "confidence": 1.0}
                    return {"category": "unknown", "confidence": 0.0}

                caas_rows = []
                try:
                    cursor = await self._execute(
                        conn,
                        """
                        SELECT service_categories, confidence FROM caas_message_profile
                        WHERE (channel_id, message_id) IN (
                            SELECT channel_id, id FROM messages WHERE user_id = ?
                        )
                        LIMIT 10
                        """,
                        (user_id,),
                    )
                    caas_rows = await self._fetchall(cursor)
                except Exception:
                    pass

                content_stream = " ".join([m[0] for m in messages if m[0]]).lower()

                category = "unknown"
                confidence = 0.5

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

                if caas_rows:
                    category = "vendor"
                    confidence = max(confidence, max(r[1] for r in caas_rows))

                activity_profile = {
                    "message_count": len(messages),
                    "scam_hits": scam_hits,
                    "vendor_hits": vendor_hits,
                    "broker_hits": broker_hits,
                    "last_active": messages[0][1] if messages else None,
                }

                await self._execute(
                    conn,
                    """
                    INSERT INTO actor_classification
                    (user_id, category, confidence, activity_profile, last_classified_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        category=excluded.category,
                        confidence=excluded.confidence,
                        activity_profile=excluded.activity_profile,
                        last_classified_at=excluded.last_classified_at
                    """,
                    (
                        user_id,
                        category,
                        confidence,
                        json.dumps(activity_profile),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

            return {
                "category": category,
                "confidence": confidence,
                "profile": activity_profile,
            }

        except Exception as e:
            logger.error(f"Failed to classify actor {user_id}: {e}")
            return {"category": "error", "error": str(e)}

    async def generate_interaction_web(
        self, username: str, output_file: Optional[str] = None
    ) -> str:
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
            user_labels = {}

            async with await self._connection_cm() as conn:
                for interaction in network:
                    src = interaction["source_user_id"]
                    dst = interaction["target_user_id"]
                    itype = interaction["interaction_type"]

                    G.add_edge(src, dst, type=itype)

                    for uid in [src, dst]:
                        if uid not in user_labels:
                            cursor = await self._execute(
                                conn,
                                "SELECT username FROM users WHERE id = ?",
                                (uid,),
                            )
                            row = await self._fetchone(cursor)
                            user_labels[uid] = row[0] if row and row[0] else str(uid)

            plt.figure(figsize=(12, 12))
            pos = nx.spring_layout(G, k=0.5, iterations=50)

            nx.draw_networkx_nodes(G, pos, node_size=2000, alpha=0.8)
            nx.draw_networkx_labels(G, pos, labels=user_labels, font_size=10, font_weight="bold")

            edge_colors = {"reply_to": "blue", "reply_from": "green", "mention": "orange"}
            for itype, color in edge_colors.items():
                edges = [(u, v) for u, v, d in G.edges(data=True) if d["type"] == itype]
                if edges:
                    nx.draw_networkx_edges(
                        G,
                        pos,
                        edgelist=edges,
                        edge_color=color,
                        arrowsize=20,
                        label=itype,
                        connectionstyle="arc3,rad=0.1",
                    )

            plt.title(f"Interaction Web for {username}")
            plt.legend(scatterpoints=1)
            plt.axis("off")

            if not output_file:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = str(self.osint_dir / f"interaction_web_{username}_{timestamp}.png")

            plt.savefig(output_file, bbox_inches="tight", dpi=300)
            plt.close()

            logger.info(f"Interaction web generated: {output_file}")
            return output_file

        except ImportError:
            logger.error("matplotlib is required for interaction web generation.")
            return "error: matplotlib_missing"
        except Exception as e:
            logger.error(f"Failed to generate interaction web for {username}: {e}")
            return f"error: {str(e)}"