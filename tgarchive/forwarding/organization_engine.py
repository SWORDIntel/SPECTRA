"""
Organization Engine for SPECTRA Topic Management
================================================

Orchestrates content classification and topic assignment for intelligent
message organization in Telegram forum channels.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, Union
from dataclasses import dataclass, asdict
from enum import Enum

from telethon import TelegramClient
from telethon.tl.types import Message

from .topic_manager import TopicManager, TopicCreationStrategy, TopicCreationRule
from .content_classifier import ContentClassifier, ContentMetadata, ClassificationRule
from ..db import SpectraDB


class OrganizationMode(Enum):
    """Organization mode for content routing."""
    DISABLED = "disabled"                    # No topic organization
    AUTO_CREATE = "auto_create"             # Automatically create topics
    EXISTING_ONLY = "existing_only"         # Use only existing topics
    HYBRID = "hybrid"                       # Combination approach


class FallbackStrategy(Enum):
    """Fallback strategy when topic creation fails."""
    GENERAL_TOPIC = "general_topic"         # Route to general topic
    NO_TOPIC = "no_topic"                   # Send without topic
    RETRY_ONCE = "retry_once"              # Retry creation once
    QUEUE_FOR_RETRY = "queue_for_retry"    # Queue for later retry


@dataclass
class OrganizationConfig:
    """Configuration for the organization engine."""
    mode: OrganizationMode = OrganizationMode.AUTO_CREATE
    topic_strategy: TopicCreationStrategy = TopicCreationStrategy.CONTENT_TYPE
    fallback_strategy: FallbackStrategy = FallbackStrategy.GENERAL_TOPIC
    auto_cleanup_empty_topics: bool = False
    max_topics_per_channel: int = 100
    topic_creation_cooldown_seconds: int = 30
    enable_content_analysis: bool = True
    classification_confidence_threshold: float = 0.7
    general_topic_title: str = "General Discussion"
    enable_statistics: bool = True
    debug_mode: bool = False


@dataclass
class OrganizationResult:
    """Result of content organization attempt."""
    success: bool
    topic_id: Optional[int] = None
    topic_title: Optional[str] = None
    category: Optional[str] = None
    fallback_used: bool = False
    error_message: Optional[str] = None
    metadata: Optional[ContentMetadata] = None


@dataclass
class OrganizationStats:
    """Statistics for organization operations."""
    messages_processed: int = 0
    topics_created: int = 0
    successful_assignments: int = 0
    failed_assignments: int = 0
    fallback_used: int = 0
    categories_processed: Dict[str, int] = None

    def __post_init__(self):
        if self.categories_processed is None:
            self.categories_processed = {}


class OrganizationEngine:
    """
    Main orchestration engine for content organization.

    Coordinates content classification and topic management to provide
    intelligent message routing in Telegram forum channels.
    """

    def __init__(self,
                 client: TelegramClient,
                 channel_id: int,
                 config: OrganizationConfig,
                 db: Optional[SpectraDB] = None):
        """
        Initialize the OrganizationEngine.

        Args:
            client: Telegram client instance
            channel_id: Target channel/group ID
            config: Organization configuration
            db: Optional database for persistence and statistics
        """
        self.client = client
        self.channel_id = channel_id
        self.config = config
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Initialize components
        self.topic_manager: Optional[TopicManager] = None
        self.classifier: Optional[ContentClassifier] = None

        # Statistics and caching
        self.stats = OrganizationStats()
        self._general_topic_id: Optional[int] = None
        self._failed_topic_cache: Dict[str, datetime] = {}

        # Organization queue for retry operations
        self._retry_queue: List[Tuple[Message, ContentMetadata]] = []

        self.logger.info(f"OrganizationEngine initialized for channel {channel_id}")

    async def initialize(self) -> bool:
        """
        Initialize the organization engine and its components.

        Returns:
            bool: True if initialization successful, False otherwise
        """
        try:
            if self.config.mode == OrganizationMode.DISABLED:
                self.logger.info("Organization mode disabled, skipping initialization")
                return True

            # Initialize content classifier
            self.classifier = ContentClassifier()

            # Initialize topic manager if needed
            if self.config.mode in [OrganizationMode.AUTO_CREATE, OrganizationMode.HYBRID]:
                self.topic_manager = TopicManager(
                    client=self.client,
                    channel_id=self.channel_id,
                    strategy=self.config.topic_strategy
                )

                if not await self.topic_manager.initialize():
                    self.logger.error("Failed to initialize TopicManager")
                    return False

            # Load or create general topic if needed
            if self.config.fallback_strategy == FallbackStrategy.GENERAL_TOPIC:
                await self._ensure_general_topic()

            # Load configuration rules if available
            await self._load_configuration_rules()

            self.logger.info("OrganizationEngine initialized successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize OrganizationEngine: {e}")
            return False

    async def organize_message(self, message: Message) -> OrganizationResult:
        """
        Organize a single message by determining appropriate topic assignment.

        Args:
            message: Telegram message to organize

        Returns:
            OrganizationResult: Result of organization attempt
        """
        self.stats.messages_processed += 1

        try:
            if self.config.mode == OrganizationMode.DISABLED:
                return OrganizationResult(success=True, fallback_used=True)

            # Classify message content
            metadata = None
            if self.classifier and self.config.enable_content_analysis:
                metadata = await self.classifier.classify_message(message)

                # Check confidence threshold
                if metadata.confidence < self.config.classification_confidence_threshold:
                    self.logger.warning(
                        f"Low classification confidence ({metadata.confidence:.2f}) "
                        f"for message {message.id}"
                    )

                # Update category statistics
                category = metadata.category
                self.stats.categories_processed[category] = \
                    self.stats.categories_processed.get(category, 0) + 1

            else:
                # Fallback metadata
                metadata = ContentMetadata(
                    content_type=self.classifier._detect_content_type(message) if self.classifier else None,
                    category='general'
                )

            # Determine target topic
            topic_id = await self._determine_topic(message, metadata)

            if topic_id:
                # Get topic title for result
                topic_title = await self._get_topic_title(topic_id)

                self.stats.successful_assignments += 1
                return OrganizationResult(
                    success=True,
                    topic_id=topic_id,
                    topic_title=topic_title,
                    category=metadata.category,
                    metadata=metadata
                )
            else:
                # Apply fallback strategy
                return await self._apply_fallback_strategy(message, metadata)

        except Exception as e:
            self.logger.error(f"Error organizing message {message.id}: {e}")
            self.stats.failed_assignments += 1
            return OrganizationResult(
                success=False,
                error_message=str(e),
                metadata=metadata
            )

    async def _determine_topic(self, message: Message, metadata: ContentMetadata) -> Optional[int]:
        """Determine the appropriate topic ID for a message."""
        try:
            if self.config.mode == OrganizationMode.EXISTING_ONLY:
                # Only use existing topics, don't create new ones
                return await self._find_existing_topic(metadata)

            elif self.config.mode in [OrganizationMode.AUTO_CREATE, OrganizationMode.HYBRID]:
                if not self.topic_manager:
                    self.logger.error("TopicManager not initialized for auto-create mode")
                    return None

                # Try to get or create topic
                content_dict = asdict(metadata)
                topic_id = await self.topic_manager.get_or_create_topic(content_dict, message)

                if topic_id:
                    return topic_id
                elif self.config.mode == OrganizationMode.HYBRID:
                    # Fallback to existing topics in hybrid mode
                    return await self._find_existing_topic(metadata)

        except Exception as e:
            self.logger.error(f"Error determining topic: {e}")

        return None

    async def _find_existing_topic(self, metadata: ContentMetadata) -> Optional[int]:
        """Find an existing topic that matches the content metadata."""
        if not self.topic_manager:
            return None

        # This is a simplified implementation
        # In practice, you might want more sophisticated matching
        cache_key = f"{self.channel_id}_{metadata.category}"
        cached_topic = self.topic_manager.cache.get(cache_key)

        if cached_topic:
            return cached_topic.id

        return None

    async def _apply_fallback_strategy(self, message: Message, metadata: ContentMetadata) -> OrganizationResult:
        """Apply the configured fallback strategy."""
        self.stats.fallback_used += 1

        try:
            if self.config.fallback_strategy == FallbackStrategy.GENERAL_TOPIC:
                if not self._general_topic_id:
                    await self._ensure_general_topic()

                return OrganizationResult(
                    success=True,
                    topic_id=self._general_topic_id,
                    topic_title=self.config.general_topic_title,
                    category=metadata.category,
                    fallback_used=True,
                    metadata=metadata
                )

            elif self.config.fallback_strategy == FallbackStrategy.NO_TOPIC:
                return OrganizationResult(
                    success=True,
                    fallback_used=True,
                    metadata=metadata
                )

            elif self.config.fallback_strategy == FallbackStrategy.RETRY_ONCE:
                # Implement retry logic here
                return OrganizationResult(
                    success=False,
                    error_message="Retry not implemented yet",
                    metadata=metadata
                )

            elif self.config.fallback_strategy == FallbackStrategy.QUEUE_FOR_RETRY:
                self._retry_queue.append((message, metadata))
                return OrganizationResult(
                    success=False,
                    error_message="Queued for retry",
                    metadata=metadata
                )

        except Exception as e:
            self.logger.error(f"Error applying fallback strategy: {e}")

        return OrganizationResult(
            success=False,
            error_message="All fallback strategies failed",
            metadata=metadata
        )

    async def _ensure_general_topic(self) -> None:
        """Ensure the general topic exists."""
        if self._general_topic_id:
            return

        if not self.topic_manager:
            self.logger.error("Cannot create general topic without TopicManager")
            return

        try:
            # Create general topic with neutral metadata
            general_metadata = {
                'content_type': 'general',
                'category': 'general'
            }

            self._general_topic_id = await self.topic_manager.get_or_create_topic(
                general_metadata,
                None
            )

            if self._general_topic_id:
                self.logger.info(f"General topic created with ID: {self._general_topic_id}")
            else:
                self.logger.error("Failed to create general topic")

        except Exception as e:
            self.logger.error(f"Error creating general topic: {e}")

    async def _get_topic_title(self, topic_id: int) -> Optional[str]:
        """Get the title of a topic by ID."""
        if not self.topic_manager:
            return None

        try:
            stats = await self.topic_manager.get_topic_stats(topic_id)
            return stats.get('title') if stats else None
        except Exception as e:
            self.logger.error(f"Error getting topic title for ID {topic_id}: {e}")
            return None

    async def _load_configuration_rules(self) -> None:
        """Load classification and topic creation rules from configuration."""
        try:
            if self.db:
                # Load rules from database (implementation depends on schema)
                pass

            # Load rules from config file or other sources
            # This is a placeholder for configuration loading

        except Exception as e:
            self.logger.error(f"Error loading configuration rules: {e}")

    async def batch_organize(self, messages: List[Message]) -> List[OrganizationResult]:
        """
        Organize multiple messages in batch.

        Args:
            messages: List of messages to organize

        Returns:
            List[OrganizationResult]: Results for each message
        """
        results = []

        for message in messages:
            try:
                result = await self.organize_message(message)
                results.append(result)

                # Add small delay to avoid rate limiting
                if len(results) % 10 == 0:
                    await asyncio.sleep(0.5)

            except Exception as e:
                self.logger.error(f"Error in batch processing message {message.id}: {e}")
                results.append(OrganizationResult(
                    success=False,
                    error_message=str(e)
                ))

        return results

    async def process_retry_queue(self) -> int:
        """
        Process queued messages that need retry.

        Returns:
            int: Number of messages successfully processed
        """
        if not self._retry_queue:
            return 0

        processed = 0
        failed_queue = []

        for message, metadata in self._retry_queue:
            try:
                result = await self.organize_message(message)
                if result.success:
                    processed += 1
                else:
                    failed_queue.append((message, metadata))
            except Exception as e:
                self.logger.error(f"Error processing retry message {message.id}: {e}")
                failed_queue.append((message, metadata))

        # Update retry queue with failed items
        self._retry_queue = failed_queue

        self.logger.info(f"Processed {processed} messages from retry queue, {len(failed_queue)} remaining")
        return processed

    async def cleanup_empty_topics(self) -> int:
        """
        Clean up empty topics if auto cleanup is enabled.

        Returns:
            int: Number of topics cleaned up
        """
        if not self.config.auto_cleanup_empty_topics or not self.topic_manager:
            return 0

        try:
            return await self.topic_manager.cleanup_empty_topics()
        except Exception as e:
            self.logger.error(f"Error during topic cleanup: {e}")
            return 0

    def get_statistics(self) -> Dict[str, Any]:
        """Get organization statistics."""
        stats_dict = asdict(self.stats)

        # Add additional metrics
        stats_dict.update({
            'success_rate': (
                self.stats.successful_assignments / self.stats.messages_processed
                if self.stats.messages_processed > 0 else 0.0
            ),
            'fallback_rate': (
                self.stats.fallback_used / self.stats.messages_processed
                if self.stats.messages_processed > 0 else 0.0
            ),
            'retry_queue_size': len(self._retry_queue),
            'cache_stats': (
                self.topic_manager.get_cache_stats()
                if self.topic_manager else {}
            ),
            'classification_stats': (
                self.classifier.get_classification_stats()
                if self.classifier else {}
            )
        })

        return stats_dict

    def reset_statistics(self) -> None:
        """Reset organization statistics."""
        self.stats = OrganizationStats()
        self.logger.info("Organization statistics reset")

    async def update_configuration(self, new_config: OrganizationConfig) -> bool:
        """
        Update organization configuration.

        Args:
            new_config: New configuration to apply

        Returns:
            bool: True if update successful, False otherwise
        """
        try:
            old_mode = self.config.mode
            self.config = new_config

            # Reinitialize if mode changed significantly
            if (old_mode != new_config.mode and
                new_config.mode in [OrganizationMode.AUTO_CREATE, OrganizationMode.HYBRID]):

                if not self.topic_manager:
                    self.topic_manager = TopicManager(
                        client=self.client,
                        channel_id=self.channel_id,
                        strategy=new_config.topic_strategy
                    )
                    await self.topic_manager.initialize()

                # Update topic manager strategy
                self.topic_manager.strategy = new_config.topic_strategy

            self.logger.info("Configuration updated successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error updating configuration: {e}")
            return False

    async def get_topic_usage_report(self) -> Dict[str, Any]:
        """Generate a report of topic usage and organization effectiveness."""
        if not self.topic_manager:
            return {'error': 'TopicManager not initialized'}

        try:
            report = {
                'total_topics': self.topic_manager.cache.size(),
                'organization_stats': self.get_statistics(),
                'top_categories': sorted(
                    self.stats.categories_processed.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:10],
                'configuration': asdict(self.config)
            }

            return report

        except Exception as e:
            self.logger.error(f"Error generating topic usage report: {e}")
            return {'error': str(e)}

    async def export_configuration(self) -> Dict[str, Any]:
        """Export current configuration for backup or sharing."""
        config_data = {
            'organization_config': asdict(self.config),
            'channel_id': self.channel_id,
            'statistics': asdict(self.stats)
        }

        if self.classifier:
            config_data['classification_rules'] = self.classifier.export_rules()

        if self.topic_manager:
            config_data['topic_rules'] = self.topic_manager.get_rules()

        return config_data

    async def import_configuration(self, config_data: Dict[str, Any]) -> bool:
        """Import configuration from exported data."""
        try:
            # Import organization config
            if 'organization_config' in config_data:
                org_config_data = config_data['organization_config']
                new_config = OrganizationConfig(**org_config_data)
                await self.update_configuration(new_config)

            # Import classification rules
            if 'classification_rules' in config_data and self.classifier:
                self.classifier.import_rules(config_data['classification_rules'])

            # Import topic rules
            if 'topic_rules' in config_data and self.topic_manager:
                for rule_data in config_data['topic_rules']:
                    rule = TopicCreationRule(**rule_data)
                    self.topic_manager.add_rule(rule)

            self.logger.info("Configuration imported successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error importing configuration: {e}")
            return False