"""
Enhanced Attachment Forwarder with Topic Organization
=====================================================

Extended version of AttachmentForwarder that includes intelligent topic
organization and content routing capabilities.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple, Dict, Any, List

from telethon.errors import (
    AuthKeyError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
    RPCError,
    UserBannedInChannelError,
    UserDeactivatedError,
)

from tgarchive.attribution import AttributionFormatter
from tgarchive.core.config_models import Config
from tgarchive.db import SpectraDB

from .client import ClientManager
from ..core.deduplication import Deduplicator
from .grouping import MessageGrouper
from .organization_engine import OrganizationEngine, OrganizationConfig, OrganizationMode
from .topic_manager import TopicCreationStrategy
from ..db.topic_operations import (
    TopicOperations, ContentMetadataRecord, TopicAssignmentRecord,
    OrganizationStatsRecord
)


class EnhancedAttachmentForwarder:
    """
    Enhanced attachment forwarder with topic organization capabilities.

    Extends the core forwarding functionality with intelligent content
    classification and topic-based message routing for forum channels.
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
        # Topic organization parameters
        enable_topic_organization: bool = True,
        organization_config: Optional[OrganizationConfig] = None,
    ):
        """
        Initialize the enhanced attachment forwarder.

        Args:
            config: SPECTRA configuration
            db: Optional database instance
            forward_to_all_saved_messages: Forward to saved messages
            destination_topic_id: Specific topic ID (overrides organization)
            secondary_unique_destination: Secondary destination
            enable_deduplication: Enable message deduplication
            grouping_strategy: Message grouping strategy
            grouping_time_window_seconds: Time window for message grouping
            enable_topic_organization: Enable intelligent topic organization
            organization_config: Configuration for topic organization
        """
        self.config = config
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Core forwarding components
        self.client_manager = ClientManager(config)
        self.deduplicator = Deduplicator(db, enable_deduplication)
        self.grouper = MessageGrouper(grouping_strategy, grouping_time_window_seconds)
        self.attribution_formatter = AttributionFormatter(self.config.data)

        # Forwarding configuration
        self.forward_to_all_saved_messages = forward_to_all_saved_messages
        self.forward_with_attribution = self.config.forward_with_attribution
        self.destination_topic_id = destination_topic_id
        self.secondary_unique_destination = secondary_unique_destination

        # Topic organization components
        self.enable_topic_organization = enable_topic_organization
        self.organization_engine: Optional[OrganizationEngine] = None
        self.topic_operations: Optional[TopicOperations] = None

        # Organization configuration
        self.organization_config = organization_config or OrganizationConfig()

        # Statistics tracking
        self._daily_stats = {}

        self.logger.info(
            f"Enhanced forwarder initialized with topic organization: {enable_topic_organization}"
        )

    async def initialize(self, channel_id: int) -> bool:
        """
        Initialize the enhanced forwarder for a specific channel.

        Args:
            channel_id: Target channel ID for organization

        Returns:
            bool: True if initialization successful
        """
        try:
            # Initialize topic operations if database is available
            if self.db and self.enable_topic_organization:
                self.topic_operations = TopicOperations(str(self.db.db_path))

                # Load or use default organization configuration
                saved_config = self.topic_operations.get_organization_config(channel_id)
                if saved_config:
                    # Update configuration with saved settings
                    for key, value in saved_config.items():
                        if hasattr(self.organization_config, key):
                            setattr(self.organization_config, key, value)

                # Initialize organization engine
                client = await self.client_manager.get_client()
                self.organization_engine = OrganizationEngine(
                    client=client,
                    channel_id=channel_id,
                    config=self.organization_config,
                    db=self.db
                )

                if not await self.organization_engine.initialize():
                    self.logger.error("Failed to initialize organization engine")
                    return False

                self.logger.info(f"Topic organization initialized for channel {channel_id}")

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize enhanced forwarder: {e}")
            return False

    async def forward_messages(
        self,
        origin_id: int | str,
        destination_id: int | str,
        account_identifier: Optional[str] = None,
        start_message_id: Optional[int] = None,
    ) -> Tuple[Optional[int], dict]:
        """
        Forward messages with intelligent topic organization.

        Args:
            origin_id: Source channel/group ID
            destination_id: Destination channel/group ID
            account_identifier: Account to use for forwarding
            start_message_id: Starting message ID

        Returns:
            Tuple[Optional[int], dict]: Last message ID and statistics
        """
        stats = {
            "messages_forwarded": 0,
            "files_forwarded": 0,
            "bytes_forwarded": 0,
            "topics_created": 0,
            "topic_assignments": 0,
            "fallback_used": 0,
        }

        new_last_message_id = None
        client = None

        try:
            # Get client and resolve entities
            client = await self.client_manager.get_client(account_identifier)

            self.logger.info(f"Attempting to resolve origin: '{origin_id}'")
            origin_entity = await client.get_entity(origin_id)

            self.logger.info(f"Attempting to resolve destination: '{destination_id}'")
            destination_entity = await client.get_entity(destination_id)

            if not origin_entity or not destination_entity:
                raise ValueError("Could not resolve one or both Telegram entities.")

            # Initialize enhanced forwarder for destination channel
            destination_channel_id = getattr(destination_entity, 'id', destination_id)
            if not await self.initialize(destination_channel_id):
                self.logger.warning("Organization initialization failed, proceeding without topic organization")

            # Fetch all media messages
            self.logger.info(f"Fetching all media messages from origin: {origin_id}")
            all_media_messages = []
            async for msg in client.iter_messages(origin_entity, min_id=start_message_id or 0):
                if msg.media:
                    all_media_messages.append(msg)

            all_media_messages.reverse()
            self.logger.info(f"Fetched {len(all_media_messages)} media messages from {origin_id}")

            # Group messages
            message_groups = self.grouper.group_messages(all_media_messages)
            self.logger.info(f"Processing {len(message_groups)} message group(s)")

            # Process each message group
            for group_idx, message_group in enumerate(message_groups):
                if not message_group:
                    continue

                representative_message = message_group[0]

                # Check for duplicates
                if await self.deduplicator.is_duplicate(message_group, client):
                    self.logger.info(f"Skipping duplicate group {group_idx + 1}")
                    continue

                # Determine topic assignment
                topic_id = await self._determine_topic_assignment(
                    representative_message, destination_channel_id
                )

                if topic_id:
                    stats["topic_assignments"] += 1
                elif self.organization_engine:
                    stats["fallback_used"] += 1

                # Forward the message group
                success = await self._forward_message_group(
                    message_group,
                    origin_entity,
                    destination_entity,
                    client,
                    topic_id,
                    stats
                )

                if success:
                    new_last_message_id = representative_message.id
                    await self.deduplicator.record_forwarded(
                        message_group, origin_entity.id, str(destination_entity.id), client
                    )

                    # Record topic assignment and metadata
                    await self._record_message_metadata(
                        representative_message, destination_channel_id, topic_id
                    )

            # Update daily statistics
            await self._update_daily_statistics(destination_channel_id, stats)

            self.logger.info(f"Finished processing all message groups from {origin_id}")

        except Exception as e:
            self.logger.error(f"Error in enhanced forwarding: {e}")
            raise

        finally:
            if client and client.is_connected():
                await self.client_manager.close()

        return new_last_message_id, stats

    async def _determine_topic_assignment(
        self, message, destination_channel_id: int
    ) -> Optional[int]:
        """
        Determine the appropriate topic for message assignment.

        Args:
            message: Telegram message to analyze
            destination_channel_id: Destination channel ID

        Returns:
            Optional[int]: Topic ID or None
        """
        # If specific topic ID is set, use it (overrides organization)
        if self.destination_topic_id:
            return self.destination_topic_id

        # If organization is disabled, return None (no topic)
        if not self.enable_topic_organization or not self.organization_engine:
            return None

        try:
            # Use organization engine to determine topic
            result = await self.organization_engine.organize_message(message)

            if result.success and result.topic_id:
                return result.topic_id
            elif result.fallback_used and result.topic_id:
                return result.topic_id

        except Exception as e:
            self.logger.error(f"Error in topic determination: {e}")

        return None

    async def _forward_message_group(
        self,
        message_group: List,
        origin_entity,
        destination_entity,
        client,
        topic_id: Optional[int],
        stats: dict
    ) -> bool:
        """Forward a group of messages with proper topic assignment."""
        try:
            successfully_forwarded = False

            for msg_idx, current_message in enumerate(message_group):
                self.logger.info(
                    f"Forwarding message {msg_idx + 1}/{len(message_group)} "
                    f"(ID: {current_message.id})"
                    + (f" to topic {topic_id}" if topic_id else "")
                )

                # Determine reply_to parameter (topic_id for forum channels)
                reply_to_arg = topic_id if topic_id else None

                if self.forward_with_attribution and not topic_id:
                    # Send with attribution (for non-forum channels)
                    await self._send_with_attribution(
                        current_message, origin_entity, destination_entity,
                        client, reply_to_arg, msg_idx, len(message_group)
                    )
                else:
                    # Forward message normally
                    await client.forward_messages(
                        entity=destination_entity,
                        messages=[current_message.id],
                        from_peer=origin_entity,
                        reply_to=reply_to_arg,
                    )

                log_msg = (f"Successfully forwarded Message ID: {current_message.id} "
                          f"from '{origin_entity.id}' to '{destination_entity.id}'")
                if reply_to_arg:
                    log_msg += f" (Topic: {reply_to_arg})"
                self.logger.info(log_msg)

                # Brief delay between messages in group
                if msg_idx < len(message_group) - 1:
                    await asyncio.sleep(1)

            successfully_forwarded = True
            stats["messages_forwarded"] += 1

            # Update file statistics
            representative_message = message_group[0]
            if representative_message.file:
                stats["files_forwarded"] += 1
                stats["bytes_forwarded"] += representative_message.file.size

            return successfully_forwarded

        except FloodWaitError as e:
            self.logger.warning(f"Rate limit hit: waiting {e.seconds} seconds")
            await asyncio.sleep(e.seconds + 1)
            return False

        except (ChannelPrivateError, ChatAdminRequiredError, UserBannedInChannelError) as e:
            self.logger.error(f"Permission error: {e}")
            return False

        except RPCError as e:
            self.logger.error(f"RPC error: {e}")
            return False

        except Exception as e:
            self.logger.error(f"Unexpected error forwarding message group: {e}")
            return False

    async def _send_with_attribution(
        self, message, origin_entity, destination_entity, client,
        reply_to_arg, msg_idx, group_size
    ):
        """Send message with attribution information."""
        # Skip attribution for disabled groups
        if destination_entity.id in self.config.get("attribution", {}).get("disable_attribution_for_groups", []):
            attribution = ""
        else:
            sender = await message.get_sender()
            sender_name = getattr(sender, 'username',
                                f"{getattr(sender, 'first_name', '')} {getattr(sender, 'last_name', '')}".strip())

            attribution = self.attribution_formatter.format_attribution(
                message=message,
                source_channel_name=getattr(origin_entity, 'title', f"ID: {origin_entity.id}"),
                source_channel_id=origin_entity.id,
                sender_name=sender_name,
                sender_id=sender.id,
                timestamp=message.date,
            )

            if self.db:
                self.db.update_attribution_stats(origin_entity.id)

        # Prepare message content
        origin_title = getattr(origin_entity, 'title', f"ID: {origin_entity.id}")
        group_info_header = ""
        if group_size > 1:
            group_info_header = f"[Group item {msg_idx+1}/{group_size}] "

        header = f"{group_info_header}[Forwarded from {origin_title} (ID: {origin_entity.id})]\n"
        message_content = attribution + "\n\n" + (message.text or "")

        await client.send_message(
            entity=destination_entity,
            message=message_content,
            file=message.media,
            reply_to=reply_to_arg,
        )

    async def _record_message_metadata(
        self, message, channel_id: int, topic_id: Optional[int]
    ):
        """Record message metadata and topic assignment in database."""
        if not self.topic_operations or not self.organization_engine:
            return

        try:
            # Get content metadata from organization engine
            result = await self.organization_engine.organize_message(message)

            if result.metadata:
                # Record content metadata
                metadata_record = ContentMetadataRecord(
                    id=None,
                    message_id=message.id,
                    channel_id=channel_id,
                    content_type=result.metadata.content_type.value if result.metadata.content_type else 'unknown',
                    category=result.metadata.category,
                    subcategory=result.metadata.subcategory,
                    file_extension=result.metadata.file_extension,
                    file_size=result.metadata.file_size,
                    mime_type=result.metadata.mime_type,
                    duration=result.metadata.duration,
                    width=result.metadata.dimensions[0] if result.metadata.dimensions else None,
                    height=result.metadata.dimensions[1] if result.metadata.dimensions else None,
                    keywords=','.join(result.metadata.keywords) if result.metadata.keywords else None,
                    classification_confidence=result.metadata.confidence,
                    additional_metadata=str(result.metadata.additional_metadata) if result.metadata.additional_metadata else None
                )

                self.topic_operations.insert_content_metadata(metadata_record)

            # Record topic assignment
            assignment_record = TopicAssignmentRecord(
                id=None,
                message_id=message.id,
                channel_id=channel_id,
                topic_id=topic_id,
                topic_title=result.topic_title,
                category=result.category,
                assignment_method='auto' if result.success else 'fallback',
                confidence=result.metadata.confidence if result.metadata else 1.0,
                fallback_used=result.fallback_used
            )

            self.topic_operations.insert_topic_assignment(assignment_record)

        except Exception as e:
            self.logger.error(f"Error recording message metadata: {e}")

    async def _update_daily_statistics(self, channel_id: int, stats: dict):
        """Update daily organization statistics."""
        if not self.topic_operations:
            return

        try:
            today = str(datetime.utcnow().date())

            # Create organization stats record
            stats_record = OrganizationStatsRecord(
                id=None,
                channel_id=channel_id,
                date=today,
                messages_processed=stats.get("messages_forwarded", 0),
                topics_created=stats.get("topics_created", 0),
                successful_assignments=stats.get("topic_assignments", 0),
                failed_assignments=0,  # Could be enhanced to track this
                fallback_used=stats.get("fallback_used", 0),
                categories_data=None  # Could include category breakdown
            )

            self.topic_operations.upsert_organization_stats(stats_record)

        except Exception as e:
            self.logger.error(f"Error updating daily statistics: {e}")

    async def get_organization_report(self, channel_id: int, days: int = 7) -> dict:
        """
        Get organization effectiveness report.

        Args:
            channel_id: Channel ID to report on
            days: Number of days to include in report

        Returns:
            dict: Organization report data
        """
        if not self.topic_operations:
            return {"error": "Topic operations not initialized"}

        try:
            # Get efficiency report
            efficiency = self.topic_operations.get_organization_efficiency_report(channel_id, days)

            # Get topic performance
            topic_performance = self.topic_operations.get_topic_performance_report(channel_id, days)

            # Get category distribution
            categories = self.topic_operations.get_category_distribution(channel_id, days)

            return {
                "channel_id": channel_id,
                "period_days": days,
                "efficiency": efficiency,
                "top_topics": topic_performance[:10],
                "category_distribution": categories,
                "organization_config": self.organization_config.__dict__ if self.organization_config else {}
            }

        except Exception as e:
            self.logger.error(f"Error generating organization report: {e}")
            return {"error": str(e)}

    async def update_organization_config(
        self, channel_id: int, config_updates: dict
    ) -> bool:
        """
        Update organization configuration for a channel.

        Args:
            channel_id: Channel ID to update
            config_updates: Configuration updates to apply

        Returns:
            bool: True if successful
        """
        if not self.topic_operations:
            return False

        try:
            # Update in-memory configuration
            for key, value in config_updates.items():
                if hasattr(self.organization_config, key):
                    setattr(self.organization_config, key, value)

            # Save to database
            self.topic_operations.upsert_organization_config(channel_id, config_updates)

            # Update organization engine if initialized
            if self.organization_engine:
                await self.organization_engine.update_configuration(self.organization_config)

            self.logger.info(f"Updated organization config for channel {channel_id}")
            return True

        except Exception as e:
            self.logger.error(f"Error updating organization config: {e}")
            return False

    async def cleanup_empty_topics(self, channel_id: int) -> int:
        """Clean up empty topics for a channel."""
        if not self.organization_engine:
            return 0

        try:
            return await self.organization_engine.cleanup_empty_topics()
        except Exception as e:
            self.logger.error(f"Error cleaning up empty topics: {e}")
            return 0

    def get_organization_stats(self) -> dict:
        """Get current organization statistics."""
        if not self.organization_engine:
            return {"organization_enabled": False}

        return self.organization_engine.get_statistics()

    async def close(self):
        """Close the enhanced forwarder and clean up resources."""
        try:
            if self.client_manager:
                await self.client_manager.close()

            self.logger.info("Enhanced forwarder closed successfully")

        except Exception as e:
            self.logger.error(f"Error closing enhanced forwarder: {e}")

from datetime import datetime