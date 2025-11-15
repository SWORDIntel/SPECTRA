"""
Group Mirroring Manager for SPECTRA
===================================

This module contains the GroupMirrorManager class for managing the mirroring of
a Telegram group to another, using two separate client accounts.
"""
from __future__ import annotations

import logging
import asyncio
from typing import Optional, Dict

from telethon import TelegramClient
from telethon.tl import types, functions
from telethon.tl.types import User, Channel
from telethon.errors import (
    FloodWaitError,
    UserNotParticipantError,
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    ChannelPrivateError,
)
from tgarchive.core.config_models import Config
from tgarchive.db.spectra_db import SpectraDB


class GroupMirrorManager:
    """
    Manages the mirroring of one group to another using two separate accounts.
    """

    def __init__(self, config: Config, db: SpectraDB, source_account_id: str, dest_account_id: str):
        """
        Initializes the GroupMirrorManager.

        :param config: The application's configuration object.
        :param db: The application's database object.
        :param source_account_id: The session name or phone number for the source account.
        :param dest_account_id: The session name or phone number for the destination account.
        """
        self.config = config
        self.db = db
        self.source_account_id = source_account_id
        self.dest_account_id = dest_account_id
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.source_client: Optional[TelegramClient] = None
        self.dest_client: Optional[TelegramClient] = None

    async def _get_client_for_account(self, account_identifier: str) -> TelegramClient:
        """
        Creates and connects a Telethon client for a specific account identifier.
        """
        selected_account = next((acc for acc in self.config.accounts if acc.get("phone_number") == account_identifier or acc.get("session_name") == account_identifier), None)
        if not selected_account:
            raise ValueError(f"Account '{account_identifier}' not found in configuration.")

        session_name = selected_account["session_name"]
        client_path = str(self.config.path.parent / f"{session_name}.session")
        client = TelegramClient(client_path, selected_account["api_id"], selected_account["api_hash"])

        self.logger.info(f"Connecting to Telegram with account: {session_name}")
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            raise ValueError(f"Account {session_name} is not authorized.")

        self.logger.info(f"Successfully connected and authorized as {session_name}.")
        return client

    async def connect(self):
        """Connects both the source and destination clients."""
        self.logger.info(f"Initializing source client for account: {self.source_account_id}")
        self.source_client = await self._get_client_for_account(self.source_account_id)

        self.logger.info(f"Initializing destination client for account: {self.dest_account_id}")
        self.dest_client = await self._get_client_for_account(self.dest_account_id)

        self.logger.info("Both source and destination clients are connected.")

    async def close(self):
        """Gracefully disconnects both clients."""
        if self.source_client and self.source_client.is_connected():
            self.logger.info(f"Disconnecting source client ({self.source_account_id}).")
            await self.source_client.disconnect()

        if self.dest_client and self.dest_client.is_connected():
            self.logger.info(f"Disconnecting destination client ({self.dest_account_id}).")
            await self.dest_client.disconnect()

    def _get_sender_name(self, sender: types.TypeUser | types.TypeChannel) -> str:
        """Constructs a display name for a sender entity."""
        if isinstance(sender, (User, types.User)):
            name = sender.first_name or ""
            if sender.last_name:
                name = f"{name} {sender.last_name}".strip()
            return name or "Unknown User"
        elif isinstance(sender, (Channel, types.Channel)):
            return sender.title or "Unknown Channel"
        return "Unknown"

    async def _mirror_topics(self, source_channel: Channel, dest_channel: Channel) -> Dict[int, int]:
        """Mirrors topics from source to destination and returns a mapping."""
        from datetime import datetime
        self.logger.info(f"Mirroring topics from {source_channel.id} to {dest_channel.id}")
        topic_map = {}

        # Get existing topics in destination to avoid duplicates
        existing_dest_topics = await self.dest_client(functions.channels.GetForumTopicsRequest(
            channel=dest_channel,
            offset_date=datetime.now(),
            offset_id=0,
            offset_topic=0,
            limit=100  # Adjust limit as needed
        ))
        existing_topic_titles = {t.title: t.id for t in existing_dest_topics.topics}

        source_topics = await self.source_client(functions.channels.GetForumTopicsRequest(
            channel=source_channel,
            offset_date=datetime.now(),
            offset_id=0,
            offset_topic=0,
            limit=100 # Adjust limit as needed
        ))

        for topic in source_topics.topics:
            if topic.title in existing_topic_titles:
                self.logger.info(f"Topic '{topic.title}' already exists in destination. Mapping.")
                topic_map[topic.id] = existing_topic_titles[topic.title]
                continue

            self.logger.info(f"Creating topic '{topic.title}' in destination group.")
            try:
                # Basic random_id generation, can be improved
                random_id = int.from_bytes(asyncio.get_event_loop().time().hex().encode(), 'big') & (2**63 - 1)

                updates = await self.dest_client(functions.channels.CreateForumTopicRequest(
                    channel=dest_channel,
                    title=topic.title,
                    random_id=random_id,
                ))
                # The new topic ID is typically in the updates object
                new_topic_message = next((u.message for u in updates.updates if isinstance(u, types.UpdateNewChannelMessage)), None)
                if new_topic_message and new_topic_message.action and isinstance(new_topic_message.action, types.MessageActionTopicCreate):
                    new_topic_id = new_topic_message.id
                    topic_map[topic.id] = new_topic_id
                    self.logger.info(f"Successfully created topic '{topic.title}' with ID {new_topic_id}")
                else:
                    self.logger.warning(f"Could not determine new topic ID for '{topic.title}' from response.")

            except FloodWaitError as e:
                self.logger.warning(f"Flood wait error when creating topic: sleeping for {e.seconds}s")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                self.logger.error(f"Failed to create topic '{topic.title}': {e}")

        self.logger.info("Finished topic mirroring.")
        return topic_map

    async def mirror_group(self, source_entity_id, dest_entity_id):
        """The main method to perform the group mirroring."""
        try:
            if not self.source_client or not self.dest_client:
                await self.connect()

            self.logger.info(f"Starting mirror from '{source_entity_id}' to '{dest_entity_id}'")

            source_channel = await self.source_client.get_entity(source_entity_id)
            dest_channel = await self.dest_client.get_entity(dest_entity_id)

            if not (hasattr(source_channel, 'forum') and source_channel.forum and hasattr(dest_channel, 'forum') and dest_channel.forum):
                self.logger.error("Both source and destination must be supergroups with Topics enabled.")
                return

            topic_map = await self._mirror_topics(source_channel, dest_channel)

            # State management
            last_message_id = self.db.get_mirror_progress(str(source_channel.id), str(dest_channel.id))
            if last_message_id is None or last_message_id == 0:
                self.logger.info("No previous mirror progress found. Starting new mirror.")
                self.db.add_mirror_progress(str(source_channel.id), str(dest_channel.id), "in_progress")
                last_message_id = 0
            else:
                self.logger.info(f"Resuming mirror from message ID: {last_message_id}")

            async for message in self.source_client.iter_messages(source_channel, min_id=last_message_id, reverse=True):
                try:
                    sender = await message.get_sender()
                    sender_name = self._get_sender_name(sender)

                    content = f"**{sender_name}**: {message.text or ''}"

                    # Determine destination topic
                    dest_topic_id = None
                    if message.is_reply and hasattr(message.reply_to, 'forum_topic') and message.reply_to.forum_topic:
                        source_topic_id = message.reply_to.reply_to_msg_id
                        if source_topic_id in topic_map:
                            dest_topic_id = topic_map[source_topic_id]

                    file_to_send = await self.source_client.download_media(message.media, file=bytes) if message.media else None

                    await self.dest_client.send_file(
                        dest_channel,
                        file=file_to_send,
                        caption=content,
                        reply_to=dest_topic_id
                    )

                    self.logger.debug(f"Mirrored message ID {message.id}")
                    self.db.update_mirror_progress(str(source_channel.id), str(dest_channel.id), message.id)

                except FloodWaitError as e:
                    self.logger.warning(f"Flood wait error: sleeping for {e.seconds}s")
                    await asyncio.sleep(e.seconds)
                except (ChatWriteForbiddenError, ChatAdminRequiredError) as e:
                    self.logger.error(f"Permissions error in destination group {dest_entity_id}: {e}. Halting mirror.")
                    break
                except Exception as e:
                    self.logger.error(f"Failed to mirror message {message.id}: {e}")

            self.logger.info("Group mirroring process completed.")

        except UserNotParticipantError as e:
            self.logger.error(f"Source account is not a participant in the source group '{source_entity_id}': {e}")
        except ChannelPrivateError as e:
            self.logger.error(f"A group is private and the client is not a participant: {e}")
        except ValueError as e:
            self.logger.error(f"Invalid entity ID or account configuration: {e}")
        except Exception as e:
            self.logger.critical(f"An unexpected error occurred during the mirroring process: {e}", exc_info=True)
