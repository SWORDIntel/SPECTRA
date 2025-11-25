"""
The core forwarding logic.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple

from telethon.errors import (
    AuthKeyError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
    RPCError,
    UserBannedInChannelError,
    UserDeactivatedError,
)

from tgarchive.utils.attribution import AttributionFormatter
from tgarchive.core.config_models import Config
from tgarchive.db import SpectraDB

from .client import ClientManager
from .deduplication import Deduplicator
from .grouping import MessageGrouper


class AttachmentForwarder:
    """
    Manages forwarding of attachments from an origin to a destination Telegram entity.
    """

    def __init__(
        self,
        config: Config,
        db: Optional[SpectraDB] = None,
        forward_to_all_saved_messages: bool = False,
        destination_topic_id: Optional[int] = None,
        secondary_unique_destination: Optional[str] = None,
        enable_deduplication: bool = True,
        grouping_strategy: str = "none",
        grouping_time_window_seconds: int = 300,
    ):
        self.config = config
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.client_manager = ClientManager(config)
        self.deduplicator = Deduplicator(db, enable_deduplication)
        self.grouper = MessageGrouper(grouping_strategy, grouping_time_window_seconds)
        self.attribution_formatter = AttributionFormatter(self.config.data)

        self.forward_to_all_saved_messages = forward_to_all_saved_messages
        self.forward_with_attribution = self.config.forward_with_attribution
        self.destination_topic_id = destination_topic_id
        self.secondary_unique_destination = secondary_unique_destination

    async def forward_messages(
        self,
        origin_id: int | str,
        destination_id: int | str,
        account_identifier: Optional[str] = None,
        start_message_id: Optional[int] = None,
    ) -> Tuple[Optional[int], dict]:
        stats = {
            "messages_forwarded": 0,
            "files_forwarded": 0,
            "bytes_forwarded": 0,
        }
        new_last_message_id = None
        client = None
        try:
            client = await self.client_manager.get_client(account_identifier)
            self.logger.info(f"Attempting to resolve origin: '{origin_id}'")
            origin_entity = await client.get_entity(origin_id)
            self.logger.info(f"Origin '{origin_id}' resolved to: {origin_entity.id if hasattr(origin_entity, 'id') else 'Unknown ID'}")
            self.logger.info(f"Attempting to resolve destination: '{destination_id}'")
            destination_entity = await client.get_entity(destination_id)
            self.logger.info(f"Destination '{destination_id}' resolved to: {destination_entity.id if hasattr(destination_entity, 'id') else 'Unknown ID'}")

            if not origin_entity or not destination_entity:
                raise ValueError("Could not resolve one or both Telegram entities.")

            self.logger.info(f"Fetching all media messages from origin: {origin_id} before grouping and forwarding.")
            all_media_messages = []
            async for msg in client.iter_messages(origin_entity, min_id=start_message_id or 0):
                if msg.media:
                    all_media_messages.append(msg)
            all_media_messages.reverse()
            self.logger.info(f"Fetched {len(all_media_messages)} media messages from {origin_id}.")

            message_groups = self.grouper.group_messages(all_media_messages)
            self.logger.info(f"Processing {len(message_groups)} message group(s) after applying '{self.grouper.grouping_strategy}' strategy.")

            for group_idx, message_group in enumerate(message_groups):
                if not message_group:
                    self.logger.warning(f"Skipping empty message group at index {group_idx}.")
                    continue
                representative_message = message_group[0]
                message = representative_message
                self.logger.debug(f"Processing Group {group_idx + 1}/{len(message_groups)}, Representative Msg ID: {message.id} from {origin_id}. Items in group: {len(message_group)}")

                if await self.deduplicator.is_duplicate(message_group, client):
                    self.logger.info(f"Message group starting with ID: {representative_message.id} (from {origin_id}) contains a duplicate file. Skipping forwarding of the entire group.")
                    continue
                self.logger.info(f"Group (representative Msg ID: {message.id}) has media. Attempting to forward to {destination_id}.")
                successfully_forwarded_main = False
                main_reply_to_arg = self.destination_topic_id
                try:
                    for msg_in_group_idx, current_message_in_group in enumerate(message_group):
                        self.logger.info(f"Forwarding item {msg_in_group_idx + 1}/{len(message_group)} (Msg ID: {current_message_in_group.id}) of current group.")
                        if self.forward_with_attribution and not self.destination_topic_id:
                            if destination_entity.id in self.config.get("attribution", {}).get("disable_attribution_for_groups", []):
                                attribution = ""
                            else:
                                sender = await current_message_in_group.get_sender()
                                sender_name = getattr(sender, 'username', f"{getattr(sender, 'first_name', '')} {getattr(sender, 'last_name', '')}".strip())
                                attribution = self.attribution_formatter.format_attribution(
                                    message=current_message_in_group,
                                    source_channel_name=getattr(origin_entity, 'title', f"ID: {origin_entity.id}"),
                                    source_channel_id=origin_entity.id,
                                    sender_name=sender_name,
                                    sender_id=sender.id,
                                    timestamp=current_message_in_group.date,
                                )
                                self.db.update_attribution_stats(origin_entity.id)
                            origin_title = getattr(origin_entity, 'title', f"ID: {origin_entity.id}")
                            group_info_header = ""
                            if len(message_group) > 1:
                                group_info_header = f"[Group item {msg_in_group_idx+1}/{len(message_group)}] "
                            header = f"{group_info_header}[Forwarded from {origin_title} (ID: {origin_entity.id})]\n"
                            message_content = attribution + "\n\n" + (current_message_in_group.text or "")
                            await client.send_message(
                                entity=destination_entity,
                                message=message_content,
                                file=current_message_in_group.media,
                                reply_to=main_reply_to_arg,
                            )
                            self.logger.info(f"Successfully sent Message ID: {current_message_in_group.id} with origin info from '{origin_id}' to '{destination_id}'.")
                        else:
                            await client.forward_messages(
                                entity=destination_entity,
                                messages=[current_message_in_group.id],
                                from_peer=origin_entity,
                                reply_to=main_reply_to_arg,
                            )
                            log_msg = f"Successfully forwarded Message ID: {current_message_in_group.id} from '{origin_id}' to main destination '{destination_id}'"
                            if main_reply_to_arg:
                                log_msg += f" (Topic/ReplyTo: {main_reply_to_arg})"
                            self.logger.info(log_msg)
                        if len(message_group) > 1 and msg_in_group_idx < len(message_group) - 1:
                            await asyncio.sleep(1)
                    successfully_forwarded_main = True
                    stats["messages_forwarded"] += 1
                    if message.file:
                        stats["files_forwarded"] += 1
                        stats["bytes_forwarded"] += message.file.size
                    new_last_message_id = message.id
                except FloodWaitError as e_flood:
                    self.logger.warning(f"Rate limit hit (main destination) while processing group (representative Msg ID: {message.id}). Waiting for {e_flood.seconds} seconds.")
                    await asyncio.sleep(e_flood.seconds + 1)
                    self.logger.info(f"Skipping rest of Message Group (representative Msg ID: {message.id}) for main destination due to FloodWait.")
                    continue
                except (ChannelPrivateError, ChatAdminRequiredError, UserBannedInChannelError) as e_perm:
                    self.logger.error(f"Permission error forwarding Message Group (representative Msg ID: {message.id}) to main destination: {e_perm}")
                    continue
                except RPCError as rpc_error:
                    self.logger.error(f"RPCError forwarding Message Group (representative Msg ID: {message.id}) to main destination: {rpc_error}")
                    continue
                except Exception as e_fwd:
                    self.logger.exception(f"Unexpected error forwarding Message Group (representative Msg ID: {message.id}) to main destination: {e_fwd}")
                    continue
                if successfully_forwarded_main:
                    await self.deduplicator.record_forwarded(message_group, origin_entity.id, str(destination_entity.id), client)
                    if self.secondary_unique_destination:
                        self.logger.info(f"Attempting to forward unique Message Group (representative Msg ID: {message.id}) to secondary destination: {self.secondary_unique_destination}")
                        try:
                            secondary_dest_entity = await client.get_entity(self.secondary_unique_destination)
                            for msg_s_idx, msg_in_group_secondary in enumerate(message_group):
                                await client.forward_messages(
                                    entity=secondary_dest_entity,
                                    messages=[msg_in_group_secondary.id],
                                    from_peer=origin_entity,
                                )
                                self.logger.info(f"  Forwarded item {msg_s_idx+1}/{len(message_group)} (Msg ID: {msg_in_group_secondary.id}) of group to secondary_dest '{self.secondary_unique_destination}'.")
                                if len(message_group) > 1 and msg_s_idx < len(message_group) - 1:
                                    await asyncio.sleep(1)
                        except FloodWaitError as e_flood_sec:
                            self.logger.warning(f"Rate limit hit (secondary destination: {self.secondary_unique_destination}). Waiting for {e_flood_sec.seconds} seconds.")
                            await asyncio.sleep(e_flood_sec.seconds + 1)
                            self.logger.info(f"Skipping secondary forward for Message Group (representative Msg ID: {message.id}) due to FloodWait.")
                        except Exception as e_sec_fwd:
                            self.logger.error(f"Error forwarding unique Message Group (representative Msg ID: {message.id}) to secondary destination '{self.secondary_unique_destination}': {e_sec_fwd}", exc_info=True)
                    if self.forward_to_all_saved_messages:
                        self.logger.info(f"Forwarding Message Group (representative Msg ID: {message.id}) to 'Saved Messages' of all configured accounts.")
                        original_main_account_id = client.session.filename
                        for acc_config in self.config.accounts:
                            saved_messages_account_id = acc_config.get("session_name") or acc_config.get("phone_number")
                            if not saved_messages_account_id:
                                self.logger.warning("Skipping an account for 'Saved Messages' forwarding due to missing identifier.")
                                continue
                            self.logger.info(f"Attempting to forward Message Group (representative Msg ID: {message.id}) to 'Saved Messages' for account: {saved_messages_account_id}")
                            try:
                                if self.client_manager._client and self.client_manager._client.session.filename != str(Config().path.parent / saved_messages_account_id):
                                    await self.client_manager.close()
                                target_client = await self.client_manager.get_client(saved_messages_account_id)
                                for msg_sv_idx, msg_in_group_saved in enumerate(message_group):
                                    await target_client.forward_messages(
                                        entity='me',
                                        messages=[msg_in_group_saved.id],
                                        from_peer=origin_entity,
                                    )
                                    self.logger.info(f"  Forwarded item {msg_sv_idx+1}/{len(message_group)} (Msg ID: {msg_in_group_saved.id}) of group to Saved Messages for {saved_messages_account_id}.")
                                    if len(message_group) > 1 and msg_sv_idx < len(message_group) - 1:
                                        await asyncio.sleep(1)
                                await asyncio.sleep(1)
                            except FloodWaitError as e_flood_saved:
                                self.logger.warning(f"Rate limit hit (Saved Messages for {saved_messages_account_id}). Waiting for {e_flood_saved.seconds} seconds.")
                                await asyncio.sleep(e_flood_saved.seconds + 1)
                            except (UserDeactivatedError, AuthKeyError) as e_auth_saved:
                                self.logger.error(f"Auth error for account {saved_messages_account_id} when forwarding to Saved Messages: {e_auth_saved}. Skipping this account.")
                            except RPCError as e_rpc_saved:
                                self.logger.error(f"RPCError for account {saved_messages_account_id} when forwarding to Saved Messages: {e_rpc_saved}. Skipping this account.")
                            except Exception as e_saved:
                                self.logger.exception(f"Unexpected error for account {saved_messages_account_id} when forwarding to Saved Messages: {e_saved}. Skipping this account.")
                        if self.client_manager._client and self.client_manager._client.session.filename != original_main_account_id:
                            await self.client_manager.close()
            self.logger.info(f"Finished processing all message groups from {origin_id}.")
        except ValueError as e:
            self.logger.error(f"Configuration or resolution error: {e}")
            raise
        except (ChannelPrivateError, ChatAdminRequiredError) as e:
            self.logger.error(f"Telegram channel access error: {e}")
            raise
        except (AuthKeyError, UserDeactivatedError) as e:
            self.logger.error(f"Telegram authentication error with account {account_identifier or 'default'}: {e}. This account might be banned or need re-authentication.")
            raise
        except RPCError as e:
            self.logger.error(f"Telegram API RPCError (potentially during entity resolution or initial connection phase): {e}")
            raise
        except ConnectionError as e:
            self.logger.error(f"Connection error: {e}")
            raise
        except Exception as e:
            self.logger.exception(f"An unexpected error occurred during forwarding: {e}")
            raise
        finally:
            if client and client.is_connected():
                await self.client_manager.close()
        return new_last_message_id, stats
