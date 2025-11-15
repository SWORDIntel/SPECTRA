from __future__ import annotations

import asyncio
import logging
from pathlib import Path
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

    async def add_target(self, username: str, notes: str = "") -> None:
        """Adds a user to the OSINT targets list."""
        try:
            logger.info(f"Attempting to add OSINT target: {username}")
            entity = await self.client.get_entity(username)
            if not isinstance(entity, User):
                logger.error(f"{username} is not a user.")
                return

            async with self.db.connect() as conn:
                # First, ensure the user exists in the main 'users' table
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO users (id, username, first_name, last_name, last_updated)
                    VALUES (?, ?, ?, ?, datetime('now'))
                    """,
                    (entity.id, entity.username, entity.first_name, entity.last_name)
                )
                # Now, add to the osint_targets table
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO osint_targets (user_id, username, notes, created_at)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (entity.id, entity.username, notes)
                )
                await conn.commit()
            logger.info(f"Successfully added {username} (ID: {entity.id}) to OSINT targets.")

        except Exception as e:
            logger.error(f"Failed to add OSINT target {username}: {e}")

    async def remove_target(self, username: str) -> None:
        """Removes a user from the OSINT targets list."""
        try:
            logger.info(f"Attempting to remove OSINT target: {username}")
            async with self.db.connect() as conn:
                cursor = await conn.execute("SELECT user_id FROM osint_targets WHERE username = ?", (username,))
                target = await cursor.fetchone()
                if not target:
                    logger.warning(f"Target {username} not found in OSINT targets.")
                    return

                await conn.execute("DELETE FROM osint_targets WHERE user_id = ?", (target[0],))
                await conn.commit()
            logger.info(f"Successfully removed {username} from OSINT targets.")

        except Exception as e:
            logger.error(f"Failed to remove OSINT target {username}: {e}")

    async def list_targets(self) -> list[dict]:
        """Lists all OSINT targets."""
        try:
            async with self.db.connect() as conn:
                cursor = await conn.execute("SELECT user_id, username, notes, created_at FROM osint_targets")
                rows = await cursor.fetchall()
                return [{"user_id": r[0], "username": r[1], "notes": r[2], "created_at": r[3]} for r in rows]
        except Exception as e:
            logger.error(f"Failed to list OSINT targets: {e}")
            return []

    async def scan_channel(self, channel_id: int | str, username: str) -> None:
        """Scans a channel for interactions involving the target user."""
        try:
            logger.info(f"Starting OSINT scan for {username} in channel {channel_id}.")

            # Get the target user's ID
            async with self.db.connect() as conn:
                cursor = await conn.execute("SELECT user_id FROM osint_targets WHERE username = ?", (username,))
                target_row = await cursor.fetchone()
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
            async with self.db.connect() as conn:
                # Ensure both users are in the 'users' table
                for user_id in [source_user_id, target_user_id]:
                    user_entity = await self.client.get_entity(user_id)
                    if isinstance(user_entity, User):
                         await conn.execute(
                            """
                            INSERT OR IGNORE INTO users (id, username, first_name, last_name, last_updated)
                            VALUES (?, ?, ?, ?, datetime('now'))
                            """,
                            (user_entity.id, user_entity.username, user_entity.first_name, user_entity.last_name)
                        )

                # Log the interaction
                await conn.execute(
                    """
                    INSERT INTO osint_interactions (source_user_id, target_user_id, interaction_type, channel_id, message_id, timestamp)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (source_user_id, target_user_id, interaction_type, channel_id, message_id)
                )
                await conn.commit()
                logger.debug(f"Logged interaction: {source_user_id} -> {target_user_id} in channel {channel_id}")

        except Exception as e:
            logger.error(f"Failed to log interaction: {e}")

    async def get_network(self, username: str) -> list[dict]:
        """Retrieves the interaction network for a given user."""
        try:
            async with self.db.connect() as conn:
                cursor = await conn.execute("SELECT user_id FROM osint_targets WHERE username = ?", (username,))
                target_row = await cursor.fetchone()
                if not target_row:
                    logger.error(f"User {username} is not an OSINT target.")
                    return []
                target_user_id = target_row[0]

                cursor = await conn.execute(
                    """
                    SELECT source_user_id, target_user_id, interaction_type, channel_id, message_id, timestamp
                    FROM osint_interactions
                    WHERE source_user_id = ? OR target_user_id = ?
                    """,
                    (target_user_id, target_user_id)
                )
                rows = await cursor.fetchall()
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
