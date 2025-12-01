"""
The core forwarding logic.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Sequence, Tuple

from telethon.errors import (
    AuthKeyError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
    RPCError,
    UserBannedInChannelError,
    UserDeactivatedError,
)
from telethon.tl.types import Channel, Chat, User

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
        prepend_origin_info: bool = False,
        copy_messages_into_destination: bool = False,
    ):
        self.config = config
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.client_manager = ClientManager(config)
        self.deduplicator = Deduplicator(db, enable_deduplication)
        self.grouper = MessageGrouper(grouping_strategy, grouping_time_window_seconds)
        self.attribution_formatter = AttributionFormatter(self.config.data)

        self.forward_to_all_saved_messages = forward_to_all_saved_messages
        self.force_prepend_origin_info = prepend_origin_info
        self.forward_with_attribution = self.force_prepend_origin_info or self.config.forward_with_attribution
        self.destination_topic_id = destination_topic_id
        self.secondary_unique_destination = secondary_unique_destination
        self.copy_messages_into_destination = copy_messages_into_destination

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
                        if self.copy_messages_into_destination:
                            await client.send_message(
                                entity=destination_entity,
                                message=current_message_in_group.text or "",
                                file=current_message_in_group.media,
                                reply_to=main_reply_to_arg,
                            )
                            log_msg = (
                                f"Copied Message ID: {current_message_in_group.id} from '{origin_id}' to"
                                f" '{destination_id}' without forward attribution"
                            )
                            if main_reply_to_arg:
                                log_msg += f" (Topic/ReplyTo: {main_reply_to_arg})"
                            self.logger.info(log_msg)
                        elif self.forward_with_attribution and not self.destination_topic_id:
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
                                if self.db:
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
                                if self.copy_messages_into_destination:
                                    await client.send_message(
                                        entity=secondary_dest_entity,
                                        message=msg_in_group_secondary.text or "",
                                        file=msg_in_group_secondary.media,
                                    )
                                    copy_log = f"  Copied item {msg_s_idx+1}/{len(message_group)} (Msg ID: {msg_in_group_secondary.id}) to secondary dest '{self.secondary_unique_destination}'."
                                    self.logger.info(copy_log)
                                else:
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
                                    if self.copy_messages_into_destination:
                                        await target_client.send_message(
                                            entity='me',
                                            message=msg_in_group_saved.text or "",
                                            file=msg_in_group_saved.media,
                                        )
                                        self.logger.info(
                                            f"  Copied item {msg_sv_idx+1}/{len(message_group)} (Msg ID: {msg_in_group_saved.id}) of group to Saved Messages for {saved_messages_account_id}."
                                        )
                                    else:
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

    async def forward_all_accessible_channels(
        self,
        destination_id: int | str,
        orchestration_account_identifier: Optional[str] = None,
        allowed_accounts: Optional[Sequence[str]] = None,
    ) -> dict:
        """
        Forward all accessible channels (from account_channel_access) to a destination.

        Args:
            destination_id: Target channel/chat to forward into.
            orchestration_account_identifier: Explicit account to orchestrate forwarding with.
            allowed_accounts: Optional list of phone numbers or session names to limit processing.
        """
        if not self.db:
            raise ValueError("Database instance is required for total forward mode.")

        try:
            unique_channels_with_accounts = self.db.get_all_unique_channels()
        except Exception as e_db:
            self.logger.error(f"Failed to retrieve channels from database: {e_db}", exc_info=True)
            raise

        if allowed_accounts:
            allowed_set = {acc.strip() for acc in allowed_accounts if acc and acc.strip()}
            unique_channels_with_accounts = [
                (channel_id, acc)
                for channel_id, acc in unique_channels_with_accounts
                if str(acc) in allowed_set
            ]
            self.logger.info(
                f"Filtered total forward mode to {len(unique_channels_with_accounts)} channel(s) across"
                f" {len(allowed_set)} specified account(s)."
            )
        else:
            self.logger.info(
                f"Total forward mode will process {len(unique_channels_with_accounts)} channel(s) discovered in the database."
            )

        if not unique_channels_with_accounts:
            self.logger.warning("No channels available to forward after filtering.")
            return {"channels_processed": 0, "messages_forwarded": 0, "files_forwarded": 0, "bytes_forwarded": 0}

        aggregate_stats = {
            "channels_processed": 0,
            "messages_forwarded": 0,
            "files_forwarded": 0,
            "bytes_forwarded": 0,
        }

        for channel_id, accessing_account_phone in unique_channels_with_accounts:
            account_for_channel = orchestration_account_identifier or accessing_account_phone
            self.logger.info(
                f"--- Forwarding channel {channel_id} using account: {account_for_channel} (discovered via {accessing_account_phone}) ---"
            )
            try:
                _, stats = await self.forward_messages(
                    origin_id=channel_id,
                    destination_id=destination_id,
                    account_identifier=account_for_channel,
                )
                aggregate_stats["channels_processed"] += 1
                aggregate_stats["messages_forwarded"] += stats.get("messages_forwarded", 0)
                aggregate_stats["files_forwarded"] += stats.get("files_forwarded", 0)
                aggregate_stats["bytes_forwarded"] += stats.get("bytes_forwarded", 0)
                self.logger.info(
                    f"Completed channel {channel_id}: {stats.get('messages_forwarded', 0)} message group(s) forwarded."
                )
            except Exception as e_fwd_all:
                self.logger.error(
                    f"Failed to forward channel {channel_id} with account {account_for_channel}: {e_fwd_all}",
                    exc_info=True,
                )
                continue

        self.logger.info(
            "Total forward mode finished."
            f" Channels processed: {aggregate_stats['channels_processed']},"
            f" messages forwarded: {aggregate_stats['messages_forwarded']},"
            f" files forwarded: {aggregate_stats['files_forwarded']}."
        )
        return aggregate_stats

    async def forward_all_dialogs(
        self,
        destination_id: int | str,
        *,
        orchestration_account_identifier: Optional[str] = None,
        allowed_accounts: Optional[Sequence[str]] = None,
        include_private_chats: bool = True,
        include_saved_messages: bool = False,
    ) -> dict:
        """Forward media from every accessible dialog to a destination."""

        accounts: list[str] = []
        if allowed_accounts:
            accounts = [acc.strip() for acc in allowed_accounts if acc and acc.strip()]
        elif orchestration_account_identifier:
            accounts = [orchestration_account_identifier]
        else:
            for acc in self.config.accounts:
                ident = acc.get("session_name") or acc.get("phone_number")
                if ident:
                    accounts.append(str(ident))
        if not accounts:
            raise ValueError("No accounts available for dialog sweep forwarding.")

        aggregate_stats = {
            "accounts_processed": 0,
            "dialogs_processed": 0,
            "messages_forwarded": 0,
            "files_forwarded": 0,
            "bytes_forwarded": 0,
        }

        for account_identifier in accounts:
            self.logger.info(f"Starting dialog sweep forwarding using account: {account_identifier}")
            try:
                _, stats = await self._forward_dialogs_for_account(
                    account_identifier=account_identifier,
                    destination_id=destination_id,
                    include_private_chats=include_private_chats,
                    include_saved_messages=include_saved_messages,
                )
                aggregate_stats["accounts_processed"] += 1
                aggregate_stats["dialogs_processed"] += stats.get("dialogs_processed", 0)
                aggregate_stats["messages_forwarded"] += stats.get("messages_forwarded", 0)
                aggregate_stats["files_forwarded"] += stats.get("files_forwarded", 0)
                aggregate_stats["bytes_forwarded"] += stats.get("bytes_forwarded", 0)
            except Exception as e:
                self.logger.error(
                    f"Dialog sweep failed for account {account_identifier}: {e}",
                    exc_info=True,
                )

        self.logger.info(
            "Dialog sweep forwarding finished.",
            f" Accounts processed: {aggregate_stats['accounts_processed']},",
            f" dialogs processed: {aggregate_stats['dialogs_processed']},",
            f" messages forwarded: {aggregate_stats['messages_forwarded']}.",
        )
        return aggregate_stats

    async def _forward_dialogs_for_account(
        self,
        *,
        account_identifier: str,
        destination_id: int | str,
        include_private_chats: bool,
        include_saved_messages: bool,
    ) -> Tuple[str, dict]:
        """Forward all dialogs for a single account."""

        stats = {
            "dialogs_processed": 0,
            "messages_forwarded": 0,
            "files_forwarded": 0,
            "bytes_forwarded": 0,
        }

        client = None
        try:
            client = await self.client_manager.get_client(account_identifier)
            me = await client.get_me()
            destination_entity = await client.get_entity(destination_id)

            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                if not entity:
                    continue
                if entity.id == destination_entity.id:
                    continue

                if isinstance(entity, User):
                    if entity.id == getattr(me, "id", None):
                        if not include_saved_messages:
                            continue
                        origin = "me"
                    else:
                        if not include_private_chats:
                            continue
                        if getattr(entity, "bot", False):
                            continue
                        origin = entity.id
                elif isinstance(entity, (Channel, Chat)):
                    origin = entity.id
                else:
                    continue

                try:
                    _, forward_stats = await self.forward_messages(
                        origin_id=origin,
                        destination_id=destination_entity,
                        account_identifier=account_identifier,
                    )
                    stats["dialogs_processed"] += 1
                    stats["messages_forwarded"] += forward_stats.get("messages_forwarded", 0)
                    stats["files_forwarded"] += forward_stats.get("files_forwarded", 0)
                    stats["bytes_forwarded"] += forward_stats.get("bytes_forwarded", 0)
                except ChannelPrivateError:
                    self.logger.warning(
                        f"Skipping private dialog {getattr(entity, 'id', 'unknown')} due to access restrictions."
                    )
                    continue
                except FloodWaitError as e_flood:
                    self.logger.warning(
                        f"Rate limit while forwarding dialog {getattr(entity, 'id', 'unknown')}: waiting {e_flood.seconds}s"
                    )
                    await asyncio.sleep(e_flood.seconds + 1)
                    continue
                except Exception as e_dialog:
                    self.logger.error(
                        f"Failed to forward dialog {getattr(entity, 'id', 'unknown')}: {e_dialog}",
                        exc_info=True,
                    )
                    continue

        finally:
            if client and client.is_connected():
                await self.client_manager.close()

        return account_identifier, stats

    async def close(self):
        """Close the underlying client manager connection."""
        await self.client_manager.close()
