"""
Topic Management System for SPECTRA
====================================

Manages Telegram forum topics for content organization and auto-categorization.
Provides intelligent topic creation, caching, and management capabilities.
"""
from __future__ import annotations

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

from telethon import TelegramClient
from telethon.errors import (
    ChatAdminRequiredError,
    RPCError,
    FloodWaitError
)

# Custom exceptions for topic-specific errors
class TopicClosedError(RPCError):
    """Topic is closed for posting."""
    pass

class TopicDeletedError(RPCError):
    """Topic has been deleted."""
    pass

class TopicExistsError(RPCError):
    """Topic already exists."""
    pass
from telethon.tl.types import ForumTopic, Message
from telethon.tl.functions.channels import CreateForumTopicRequest, GetForumTopicsRequest


class TopicCreationStrategy(Enum):
    """Strategy for topic creation based on content analysis."""
    CONTENT_TYPE = "content_type"  # Group by media type (photos, videos, documents)
    DATE_BASED = "date_based"      # Group by date (daily, weekly, monthly)
    FILE_EXTENSION = "file_extension"  # Group by file type (.pdf, .zip, etc.)
    SOURCE_CHANNEL = "source_channel"  # Group by source channel
    CUSTOM_RULES = "custom_rules"  # User-defined classification rules
    HYBRID = "hybrid"              # Combine multiple strategies


@dataclass
class TopicInfo:
    """Information about a forum topic."""
    id: int
    title: str
    icon_color: int
    icon_emoji_id: Optional[int] = None
    created_at: Optional[datetime] = None
    message_count: int = 0
    last_activity: Optional[datetime] = None
    category: Optional[str] = None
    description: Optional[str] = None


@dataclass
class TopicCreationRule:
    """Rules for creating topics based on content analysis."""
    name: str
    strategy: TopicCreationStrategy
    pattern: str
    title_template: str
    icon_color: int
    icon_emoji_id: Optional[int] = None
    priority: int = 0
    conditions: Dict[str, Any] = None


class TopicCache:
    """LRU cache for topic information to reduce API calls."""

    def __init__(self, max_size: int = 1000, ttl_hours: int = 24):
        self.max_size = max_size
        self.ttl = timedelta(hours=ttl_hours)
        self._cache: Dict[str, Tuple[TopicInfo, datetime]] = {}
        self._access_order: List[str] = []

    def get(self, key: str) -> Optional[TopicInfo]:
        """Get topic from cache if not expired."""
        if key not in self._cache:
            return None

        topic_info, timestamp = self._cache[key]

        # Check if expired
        if datetime.utcnow() - timestamp > self.ttl:
            self._remove(key)
            return None

        # Update access order
        self._access_order.remove(key)
        self._access_order.append(key)

        return topic_info

    def put(self, key: str, topic_info: TopicInfo) -> None:
        """Add topic to cache with LRU eviction."""
        if key in self._cache:
            self._cache[key] = (topic_info, datetime.utcnow())
            self._access_order.remove(key)
            self._access_order.append(key)
            return

        # Evict if at capacity
        if len(self._cache) >= self.max_size:
            oldest_key = self._access_order.pop(0)
            del self._cache[oldest_key]

        self._cache[key] = (topic_info, datetime.utcnow())
        self._access_order.append(key)

    def _remove(self, key: str) -> None:
        """Remove key from cache."""
        if key in self._cache:
            del self._cache[key]
            self._access_order.remove(key)

    def clear(self) -> None:
        """Clear all cached topics."""
        self._cache.clear()
        self._access_order.clear()

    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)


class TopicManager:
    """
    Manages Telegram forum topics for content organization.

    Provides intelligent topic creation, caching, and management with
    support for multiple organization strategies and graceful fallback.
    """

    def __init__(self,
                 client: TelegramClient,
                 channel_id: int,
                 strategy: TopicCreationStrategy = TopicCreationStrategy.CONTENT_TYPE,
                 cache_ttl_hours: int = 24,
                 max_cache_size: int = 1000):
        """
        Initialize TopicManager.

        Args:
            client: Telegram client instance
            channel_id: Target channel/group ID where topics will be managed
            strategy: Default strategy for topic creation
            cache_ttl_hours: Cache TTL in hours
            max_cache_size: Maximum number of topics to cache
        """
        self.client = client
        self.channel_id = channel_id
        self.strategy = strategy
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Topic cache for performance
        self.cache = TopicCache(max_cache_size, cache_ttl_hours)

        # Topic creation rules
        self.rules: List[TopicCreationRule] = []

        # Rate limiting for topic creation
        self._last_topic_creation = {}
        self._min_creation_interval = timedelta(seconds=30)  # Minimum 30s between topic creations

        # Default topic templates
        self._default_templates = {
            TopicCreationStrategy.CONTENT_TYPE: {
                "photo": ("📸 Photos", 0x3498db),
                "video": ("🎬 Videos", 0xe74c3c),
                "document": ("📄 Documents", 0xf39c12),
                "audio": ("🎵 Audio", 0x9b59b6),
                "voice": ("🎤 Voice Messages", 0x1abc9c),
                "sticker": ("😄 Stickers", 0xf1c40f),
                "animation": ("🎭 GIFs", 0x34495e),
                "contact": ("👥 Contacts", 0x95a5a6),
                "location": ("📍 Locations", 0x27ae60),
                "poll": ("📊 Polls", 0x8e44ad),
                "game": ("🎮 Games", 0xe67e22),
            },
            TopicCreationStrategy.DATE_BASED: {
                "daily": ("{date} - Daily Archive", 0x3498db),
                "weekly": ("Week {week_num} - {year}", 0x2ecc71),
                "monthly": ("{month} {year}", 0xe74c3c),
            }
        }

        self.logger.info(f"TopicManager initialized for channel {channel_id} with strategy: {strategy.value}")

    async def initialize(self) -> bool:
        """
        Initialize the topic manager by loading existing topics.

        Returns:
            bool: True if initialization successful, False otherwise
        """
        try:
            await self._load_existing_topics()
            self.logger.info(f"TopicManager initialized with {self.cache.size()} cached topics")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize TopicManager: {e}")
            return False

    async def _load_existing_topics(self) -> None:
        """Load existing forum topics into cache."""
        try:
            # Get forum topics from the channel
            result = await self.client(GetForumTopicsRequest(
                channel=self.channel_id,
                offset_date=None,
                offset_id=0,
                offset_topic=0,
                limit=100
            ))

            for topic in result.topics:
                if isinstance(topic, ForumTopic):
                    topic_info = TopicInfo(
                        id=topic.id,
                        title=topic.title,
                        icon_color=topic.icon_color,
                        icon_emoji_id=getattr(topic, 'icon_emoji_id', None),
                        created_at=topic.date,
                        message_count=getattr(topic, 'messages', 0),
                        last_activity=getattr(topic, 'last_message_date', None)
                    )

                    cache_key = f"{self.channel_id}_{topic.id}"
                    self.cache.put(cache_key, topic_info)

            self.logger.info(f"Loaded {len(result.topics)} existing topics into cache")

        except Exception as e:
            self.logger.warning(f"Could not load existing topics (may not be a forum): {e}")

    async def get_or_create_topic(self,
                                content_metadata: Dict[str, Any],
                                message: Optional[Message] = None) -> Optional[int]:
        """
        Get existing topic or create new one based on content analysis.

        Args:
            content_metadata: Dictionary with content analysis results
            message: Optional message object for additional context

        Returns:
            Optional[int]: Topic ID if successful, None if failed
        """
        try:
            # Determine topic based on strategy and rules
            topic_candidate = await self._determine_topic(content_metadata, message)

            if not topic_candidate:
                self.logger.warning("Could not determine appropriate topic for content")
                return None

            # Check if topic exists in cache
            cache_key = f"{self.channel_id}_{topic_candidate['title']}"
            cached_topic = self.cache.get(cache_key)

            if cached_topic:
                self.logger.debug(f"Using cached topic: {cached_topic.title} (ID: {cached_topic.id})")
                return cached_topic.id

            # Try to find existing topic by title
            existing_topic = await self._find_topic_by_title(topic_candidate['title'])
            if existing_topic:
                self.cache.put(cache_key, existing_topic)
                return existing_topic.id

            # Create new topic if it doesn't exist
            new_topic = await self._create_topic(
                title=topic_candidate['title'],
                icon_color=topic_candidate.get('icon_color', 0x3498db),
                icon_emoji_id=topic_candidate.get('icon_emoji_id')
            )

            if new_topic:
                self.cache.put(cache_key, new_topic)
                return new_topic.id

            return None

        except Exception as e:
            self.logger.error(f"Failed to get or create topic: {e}")
            return None

    async def _determine_topic(self,
                             content_metadata: Dict[str, Any],
                             message: Optional[Message] = None) -> Optional[Dict[str, Any]]:
        """
        Determine appropriate topic based on content analysis and configured rules.

        Args:
            content_metadata: Content analysis results
            message: Optional message for additional context

        Returns:
            Optional[Dict]: Topic creation parameters or None
        """
        # Apply custom rules first (highest priority)
        for rule in sorted(self.rules, key=lambda r: r.priority, reverse=True):
            topic_params = await self._apply_rule(rule, content_metadata, message)
            if topic_params:
                return topic_params

        # Fallback to default strategy
        return await self._apply_default_strategy(content_metadata, message)

    async def _apply_rule(self,
                         rule: TopicCreationRule,
                         content_metadata: Dict[str, Any],
                         message: Optional[Message] = None) -> Optional[Dict[str, Any]]:
        """Apply a specific topic creation rule."""
        try:
            # Check if rule conditions are met
            if rule.conditions:
                if not self._check_conditions(rule.conditions, content_metadata):
                    return None

            # Generate topic parameters based on rule strategy
            if rule.strategy == TopicCreationStrategy.CONTENT_TYPE:
                content_type = content_metadata.get('content_type', 'unknown')
                if content_type in rule.pattern or rule.pattern == '*':
                    return {
                        'title': rule.title_template.format(
                            content_type=content_type,
                            date=datetime.now().strftime('%Y-%m-%d'),
                            **content_metadata
                        ),
                        'icon_color': rule.icon_color,
                        'icon_emoji_id': rule.icon_emoji_id,
                        'category': rule.name
                    }

            elif rule.strategy == TopicCreationStrategy.FILE_EXTENSION:
                file_ext = content_metadata.get('file_extension', '').lower()
                if file_ext in rule.pattern.split(',') or rule.pattern == '*':
                    return {
                        'title': rule.title_template.format(
                            extension=file_ext,
                            date=datetime.now().strftime('%Y-%m-%d'),
                            **content_metadata
                        ),
                        'icon_color': rule.icon_color,
                        'icon_emoji_id': rule.icon_emoji_id,
                        'category': rule.name
                    }

            elif rule.strategy == TopicCreationStrategy.DATE_BASED:
                now = datetime.now()
                return {
                    'title': rule.title_template.format(
                        date=now.strftime('%Y-%m-%d'),
                        week_num=now.strftime('%U'),
                        month=now.strftime('%B'),
                        year=now.strftime('%Y'),
                        **content_metadata
                    ),
                    'icon_color': rule.icon_color,
                    'icon_emoji_id': rule.icon_emoji_id,
                    'category': rule.name
                }

        except Exception as e:
            self.logger.warning(f"Failed to apply rule {rule.name}: {e}")

        return None

    async def _apply_default_strategy(self,
                                    content_metadata: Dict[str, Any],
                                    message: Optional[Message] = None) -> Optional[Dict[str, Any]]:
        """Apply default topic creation strategy."""
        if self.strategy == TopicCreationStrategy.CONTENT_TYPE:
            content_type = content_metadata.get('content_type', 'unknown')
            template_data = self._default_templates[self.strategy].get(content_type)

            if template_data:
                title, color = template_data
                return {
                    'title': title,
                    'icon_color': color,
                    'category': 'content_type'
                }

        elif self.strategy == TopicCreationStrategy.DATE_BASED:
            now = datetime.now()
            template_data = self._default_templates[self.strategy]['daily']
            title_template, color = template_data

            return {
                'title': title_template.format(date=now.strftime('%Y-%m-%d')),
                'icon_color': color,
                'category': 'date_based'
            }

        # Fallback to generic topic
        return {
            'title': f"General - {datetime.now().strftime('%Y-%m-%d')}",
            'icon_color': 0x95a5a6,
            'category': 'fallback'
        }

    def _check_conditions(self, conditions: Dict[str, Any], content_metadata: Dict[str, Any]) -> bool:
        """Check if rule conditions are satisfied."""
        for key, expected_value in conditions.items():
            actual_value = content_metadata.get(key)

            if isinstance(expected_value, list):
                if actual_value not in expected_value:
                    return False
            elif isinstance(expected_value, dict):
                if 'min' in expected_value and actual_value < expected_value['min']:
                    return False
                if 'max' in expected_value and actual_value > expected_value['max']:
                    return False
            else:
                if actual_value != expected_value:
                    return False

        return True

    async def _find_topic_by_title(self, title: str) -> Optional[TopicInfo]:
        """Find existing topic by title."""
        try:
            result = await self.client(GetForumTopicsRequest(
                channel=self.channel_id,
                offset_date=None,
                offset_id=0,
                offset_topic=0,
                limit=100
            ))

            for topic in result.topics:
                if isinstance(topic, ForumTopic) and topic.title == title:
                    return TopicInfo(
                        id=topic.id,
                        title=topic.title,
                        icon_color=topic.icon_color,
                        icon_emoji_id=getattr(topic, 'icon_emoji_id', None),
                        created_at=topic.date,
                        message_count=getattr(topic, 'messages', 0)
                    )

        except Exception as e:
            self.logger.warning(f"Could not search for topic '{title}': {e}")

        return None

    async def _create_topic(self,
                          title: str,
                          icon_color: int = 0x3498db,
                          icon_emoji_id: Optional[int] = None) -> Optional[TopicInfo]:
        """
        Create a new forum topic with rate limiting.

        Args:
            title: Topic title
            icon_color: Topic icon color (RGB hex)
            icon_emoji_id: Optional custom emoji ID

        Returns:
            Optional[TopicInfo]: Created topic info or None if failed
        """
        try:
            # Check rate limiting
            now = datetime.utcnow()
            last_creation = self._last_topic_creation.get(self.channel_id)

            if last_creation and now - last_creation < self._min_creation_interval:
                wait_time = (self._min_creation_interval - (now - last_creation)).total_seconds()
                self.logger.info(f"Rate limiting: waiting {wait_time:.1f}s before creating topic")
                await asyncio.sleep(wait_time)

            # Create the topic
            result = await self.client(CreateForumTopicRequest(
                channel=self.channel_id,
                title=title,
                icon_color=icon_color,
                icon_emoji_id=icon_emoji_id,
                random_id=self.client._get_random_id()
            ))

            # Update rate limiting tracker
            self._last_topic_creation[self.channel_id] = datetime.utcnow()

            # Extract topic info from result
            if hasattr(result, 'updates') and result.updates:
                for update in result.updates:
                    if hasattr(update, 'topic'):
                        topic = update.topic
                        topic_info = TopicInfo(
                            id=topic.id,
                            title=title,
                            icon_color=icon_color,
                            icon_emoji_id=icon_emoji_id,
                            created_at=datetime.utcnow()
                        )

                        self.logger.info(f"Created new topic: '{title}' (ID: {topic.id})")
                        return topic_info

        except TopicExistsError:
            self.logger.warning(f"Topic '{title}' already exists, attempting to find it")
            return await self._find_topic_by_title(title)

        except ChatAdminRequiredError:
            self.logger.error("Insufficient permissions to create topics - admin rights required")

        except FloodWaitError as e:
            self.logger.warning(f"Rate limited: waiting {e.seconds}s before retry")
            await asyncio.sleep(e.seconds)
            return await self._create_topic(title, icon_color, icon_emoji_id)

        except RPCError as e:
            self.logger.error(f"Failed to create topic '{title}': {e}")

        except Exception as e:
            self.logger.error(f"Unexpected error creating topic '{title}': {e}")

        return None

    def add_rule(self, rule: TopicCreationRule) -> None:
        """Add a custom topic creation rule."""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
        self.logger.info(f"Added topic creation rule: {rule.name} (priority: {rule.priority})")

    def remove_rule(self, rule_name: str) -> bool:
        """Remove a topic creation rule by name."""
        for i, rule in enumerate(self.rules):
            if rule.name == rule_name:
                del self.rules[i]
                self.logger.info(f"Removed topic creation rule: {rule_name}")
                return True
        return False

    def get_rules(self) -> List[TopicCreationRule]:
        """Get all configured topic creation rules."""
        return self.rules.copy()

    async def get_topic_stats(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific topic."""
        cache_key = f"{self.channel_id}_{topic_id}"
        cached_topic = self.cache.get(cache_key)

        if cached_topic:
            return {
                'id': cached_topic.id,
                'title': cached_topic.title,
                'message_count': cached_topic.message_count,
                'last_activity': cached_topic.last_activity,
                'category': cached_topic.category
            }

        return None

    async def cleanup_empty_topics(self, max_age_days: int = 7) -> int:
        """
        Clean up empty topics older than specified age.

        Args:
            max_age_days: Maximum age in days for empty topics

        Returns:
            int: Number of topics cleaned up
        """
        # This would require additional API calls and admin permissions
        # Implementation would depend on specific requirements
        self.logger.info("Topic cleanup not implemented yet")
        return 0

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            'size': self.cache.size(),
            'max_size': self.cache.max_size,
            'ttl_hours': self.cache.ttl.total_seconds() / 3600
        }