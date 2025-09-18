"""
Database Operations for Topic Organization
==========================================

Database operations and utilities for topic management and content organization.
Provides CRUD operations and analytics for the topic organization system.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple, Union
from dataclasses import dataclass, asdict

from .db_base import BaseDB


@dataclass
class ForumTopicRecord:
    """Database record for forum topics."""
    id: Optional[int]
    channel_id: int
    topic_id: int
    title: str
    icon_color: int
    icon_emoji_id: Optional[int] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    description: Optional[str] = None
    message_count: int = 0
    created_at: Optional[str] = None
    last_activity: Optional[str] = None
    is_active: bool = True


@dataclass
class ContentMetadataRecord:
    """Database record for message content metadata."""
    id: Optional[int]
    message_id: int
    channel_id: int
    content_type: str
    category: str
    subcategory: Optional[str] = None
    file_extension: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    keywords: Optional[str] = None  # JSON array
    classification_confidence: float = 1.0
    additional_metadata: Optional[str] = None  # JSON data
    created_at: Optional[str] = None


@dataclass
class TopicAssignmentRecord:
    """Database record for topic assignments."""
    id: Optional[int]
    message_id: int
    channel_id: int
    topic_id: Optional[int]
    topic_title: Optional[str]
    category: Optional[str]
    assignment_method: str
    confidence: float = 1.0
    fallback_used: bool = False
    created_at: Optional[str] = None


@dataclass
class OrganizationStatsRecord:
    """Database record for organization statistics."""
    id: Optional[int]
    channel_id: int
    date: str
    messages_processed: int = 0
    topics_created: int = 0
    successful_assignments: int = 0
    failed_assignments: int = 0
    fallback_used: int = 0
    categories_data: Optional[str] = None  # JSON
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TopicOperations(BaseDB):
    """Database operations for topic management."""

    def __init__(self, db_path: str):
        """Initialize topic operations."""
        super().__init__(db_path)

    # Forum Topics Operations
    def insert_forum_topic(self, topic: ForumTopicRecord) -> int:
        """Insert a new forum topic record."""
        query = """
        INSERT INTO forum_topics (
            channel_id, topic_id, title, icon_color, icon_emoji_id,
            category, subcategory, description, message_count,
            created_at, last_activity, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        created_at = topic.created_at or datetime.utcnow().isoformat()

        params = (
            topic.channel_id, topic.topic_id, topic.title, topic.icon_color,
            topic.icon_emoji_id, topic.category, topic.subcategory,
            topic.description, topic.message_count, created_at,
            topic.last_activity, topic.is_active
        )

        return self.execute_insert(query, params)

    def get_forum_topic(self, channel_id: int, topic_id: int) -> Optional[ForumTopicRecord]:
        """Get a forum topic by channel and topic ID."""
        query = """
        SELECT id, channel_id, topic_id, title, icon_color, icon_emoji_id,
               category, subcategory, description, message_count,
               created_at, last_activity, is_active
        FROM forum_topics
        WHERE channel_id = ? AND topic_id = ?
        """

        result = self.execute_query(query, (channel_id, topic_id))
        if result:
            return ForumTopicRecord(*result[0])
        return None

    def get_forum_topics_by_channel(self, channel_id: int, active_only: bool = True) -> List[ForumTopicRecord]:
        """Get all forum topics for a channel."""
        query = """
        SELECT id, channel_id, topic_id, title, icon_color, icon_emoji_id,
               category, subcategory, description, message_count,
               created_at, last_activity, is_active
        FROM forum_topics
        WHERE channel_id = ?
        """

        params = [channel_id]
        if active_only:
            query += " AND is_active = TRUE"

        query += " ORDER BY created_at DESC"

        results = self.execute_query(query, params)
        return [ForumTopicRecord(*row) for row in results]

    def update_forum_topic(self, topic: ForumTopicRecord) -> bool:
        """Update a forum topic record."""
        if not topic.id:
            return False

        query = """
        UPDATE forum_topics SET
            title = ?, icon_color = ?, icon_emoji_id = ?,
            category = ?, subcategory = ?, description = ?,
            message_count = ?, last_activity = ?, is_active = ?
        WHERE id = ?
        """

        params = (
            topic.title, topic.icon_color, topic.icon_emoji_id,
            topic.category, topic.subcategory, topic.description,
            topic.message_count, topic.last_activity, topic.is_active,
            topic.id
        )

        return self.execute_update(query, params)

    def delete_forum_topic(self, topic_id: int) -> bool:
        """Delete a forum topic (soft delete by setting is_active = FALSE)."""
        query = "UPDATE forum_topics SET is_active = FALSE WHERE id = ?"
        return self.execute_update(query, (topic_id,))

    def find_topic_by_title(self, channel_id: int, title: str) -> Optional[ForumTopicRecord]:
        """Find a topic by title within a channel."""
        query = """
        SELECT id, channel_id, topic_id, title, icon_color, icon_emoji_id,
               category, subcategory, description, message_count,
               created_at, last_activity, is_active
        FROM forum_topics
        WHERE channel_id = ? AND title = ? AND is_active = TRUE
        """

        result = self.execute_query(query, (channel_id, title))
        if result:
            return ForumTopicRecord(*result[0])
        return None

    def get_topics_by_category(self, channel_id: int, category: str) -> List[ForumTopicRecord]:
        """Get topics by category."""
        query = """
        SELECT id, channel_id, topic_id, title, icon_color, icon_emoji_id,
               category, subcategory, description, message_count,
               created_at, last_activity, is_active
        FROM forum_topics
        WHERE channel_id = ? AND category = ? AND is_active = TRUE
        ORDER BY message_count DESC
        """

        results = self.execute_query(query, (channel_id, category))
        return [ForumTopicRecord(*row) for row in results]

    # Content Metadata Operations
    def insert_content_metadata(self, metadata: ContentMetadataRecord) -> int:
        """Insert content metadata record."""
        query = """
        INSERT OR REPLACE INTO message_content_metadata (
            message_id, channel_id, content_type, category, subcategory,
            file_extension, file_size, mime_type, duration, width, height,
            keywords, classification_confidence, additional_metadata, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        created_at = metadata.created_at or datetime.utcnow().isoformat()

        params = (
            metadata.message_id, metadata.channel_id, metadata.content_type,
            metadata.category, metadata.subcategory, metadata.file_extension,
            metadata.file_size, metadata.mime_type, metadata.duration,
            metadata.width, metadata.height, metadata.keywords,
            metadata.classification_confidence, metadata.additional_metadata,
            created_at
        )

        return self.execute_insert(query, params)

    def get_content_metadata(self, message_id: int, channel_id: int) -> Optional[ContentMetadataRecord]:
        """Get content metadata for a message."""
        query = """
        SELECT id, message_id, channel_id, content_type, category, subcategory,
               file_extension, file_size, mime_type, duration, width, height,
               keywords, classification_confidence, additional_metadata, created_at
        FROM message_content_metadata
        WHERE message_id = ? AND channel_id = ?
        """

        result = self.execute_query(query, (message_id, channel_id))
        if result:
            return ContentMetadataRecord(*result[0])
        return None

    def get_content_by_category(self, channel_id: int, category: str, limit: int = 100) -> List[ContentMetadataRecord]:
        """Get content metadata by category."""
        query = """
        SELECT id, message_id, channel_id, content_type, category, subcategory,
               file_extension, file_size, mime_type, duration, width, height,
               keywords, classification_confidence, additional_metadata, created_at
        FROM message_content_metadata
        WHERE channel_id = ? AND category = ?
        ORDER BY created_at DESC
        LIMIT ?
        """

        results = self.execute_query(query, (channel_id, category, limit))
        return [ContentMetadataRecord(*row) for row in results]

    # Topic Assignment Operations
    def insert_topic_assignment(self, assignment: TopicAssignmentRecord) -> int:
        """Insert a topic assignment record."""
        query = """
        INSERT OR REPLACE INTO topic_assignments (
            message_id, channel_id, topic_id, topic_title, category,
            assignment_method, confidence, fallback_used, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        created_at = assignment.created_at or datetime.utcnow().isoformat()

        params = (
            assignment.message_id, assignment.channel_id, assignment.topic_id,
            assignment.topic_title, assignment.category, assignment.assignment_method,
            assignment.confidence, assignment.fallback_used, created_at
        )

        return self.execute_insert(query, params)

    def get_topic_assignment(self, message_id: int, channel_id: int) -> Optional[TopicAssignmentRecord]:
        """Get topic assignment for a message."""
        query = """
        SELECT id, message_id, channel_id, topic_id, topic_title, category,
               assignment_method, confidence, fallback_used, created_at
        FROM topic_assignments
        WHERE message_id = ? AND channel_id = ?
        """

        result = self.execute_query(query, (message_id, channel_id))
        if result:
            return TopicAssignmentRecord(*result[0])
        return None

    def get_assignments_by_topic(self, channel_id: int, topic_id: int, limit: int = 100) -> List[TopicAssignmentRecord]:
        """Get all assignments for a specific topic."""
        query = """
        SELECT id, message_id, channel_id, topic_id, topic_title, category,
               assignment_method, confidence, fallback_used, created_at
        FROM topic_assignments
        WHERE channel_id = ? AND topic_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """

        results = self.execute_query(query, (channel_id, topic_id, limit))
        return [TopicAssignmentRecord(*row) for row in results]

    # Organization Statistics Operations
    def upsert_organization_stats(self, stats: OrganizationStatsRecord) -> int:
        """Insert or update organization statistics."""
        # First try to get existing record
        existing_query = """
        SELECT id FROM organization_stats
        WHERE channel_id = ? AND date = ?
        """

        existing = self.execute_query(existing_query, (stats.channel_id, stats.date))

        if existing:
            # Update existing record
            query = """
            UPDATE organization_stats SET
                messages_processed = messages_processed + ?,
                topics_created = topics_created + ?,
                successful_assignments = successful_assignments + ?,
                failed_assignments = failed_assignments + ?,
                fallback_used = fallback_used + ?,
                categories_data = ?,
                updated_at = ?
            WHERE id = ?
            """

            updated_at = datetime.utcnow().isoformat()
            params = (
                stats.messages_processed, stats.topics_created,
                stats.successful_assignments, stats.failed_assignments,
                stats.fallback_used, stats.categories_data, updated_at,
                existing[0][0]
            )

            self.execute_update(query, params)
            return existing[0][0]
        else:
            # Insert new record
            query = """
            INSERT INTO organization_stats (
                channel_id, date, messages_processed, topics_created,
                successful_assignments, failed_assignments, fallback_used,
                categories_data, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            now = datetime.utcnow().isoformat()
            created_at = stats.created_at or now
            updated_at = stats.updated_at or now

            params = (
                stats.channel_id, stats.date, stats.messages_processed,
                stats.topics_created, stats.successful_assignments,
                stats.failed_assignments, stats.fallback_used,
                stats.categories_data, created_at, updated_at
            )

            return self.execute_insert(query, params)

    def get_organization_stats(self, channel_id: int, date: str) -> Optional[OrganizationStatsRecord]:
        """Get organization statistics for a specific date."""
        query = """
        SELECT id, channel_id, date, messages_processed, topics_created,
               successful_assignments, failed_assignments, fallback_used,
               categories_data, created_at, updated_at
        FROM organization_stats
        WHERE channel_id = ? AND date = ?
        """

        result = self.execute_query(query, (channel_id, date))
        if result:
            return OrganizationStatsRecord(*result[0])
        return None

    def get_organization_stats_range(self, channel_id: int, start_date: str, end_date: str) -> List[OrganizationStatsRecord]:
        """Get organization statistics for a date range."""
        query = """
        SELECT id, channel_id, date, messages_processed, topics_created,
               successful_assignments, failed_assignments, fallback_used,
               categories_data, created_at, updated_at
        FROM organization_stats
        WHERE channel_id = ? AND date BETWEEN ? AND ?
        ORDER BY date DESC
        """

        results = self.execute_query(query, (channel_id, start_date, end_date))
        return [OrganizationStatsRecord(*row) for row in results]

    # Topic Usage Statistics
    def update_topic_usage_stats(self, channel_id: int, topic_id: int, date: str, increment_messages: int = 1) -> None:
        """Update topic usage statistics."""
        query = """
        INSERT INTO topic_usage_stats (
            channel_id, topic_id, topic_title, category, messages_assigned,
            last_message_date, date, created_at, updated_at
        )
        SELECT ?, ?, ft.title, ft.category, ?, ?, ?, ?, ?
        FROM forum_topics ft
        WHERE ft.channel_id = ? AND ft.topic_id = ?
        ON CONFLICT(channel_id, topic_id, date) DO UPDATE SET
            messages_assigned = messages_assigned + ?,
            last_message_date = ?,
            updated_at = ?
        """

        now = datetime.utcnow().isoformat()
        params = (
            channel_id, topic_id, increment_messages, now, date, now, now,
            channel_id, topic_id, increment_messages, now, now
        )

        self.execute_update(query, params)

    def get_topic_usage_stats(self, channel_id: int, date: str) -> List[Dict[str, Any]]:
        """Get topic usage statistics for a date."""
        query = """
        SELECT channel_id, topic_id, topic_title, category, messages_assigned,
               last_message_date, total_file_size, unique_senders
        FROM topic_usage_stats
        WHERE channel_id = ? AND date = ?
        ORDER BY messages_assigned DESC
        """

        results = self.execute_query(query, (channel_id, date))
        return [
            {
                'channel_id': row[0], 'topic_id': row[1], 'topic_title': row[2],
                'category': row[3], 'messages_assigned': row[4],
                'last_message_date': row[5], 'total_file_size': row[6],
                'unique_senders': row[7]
            }
            for row in results
        ]

    # Analytics and Reporting
    def get_category_distribution(self, channel_id: int, days: int = 30) -> Dict[str, int]:
        """Get distribution of categories over the last N days."""
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days)

        query = """
        SELECT category, COUNT(*) as count
        FROM message_content_metadata
        WHERE channel_id = ? AND DATE(created_at) BETWEEN ? AND ?
        GROUP BY category
        ORDER BY count DESC
        """

        results = self.execute_query(query, (channel_id, start_date.isoformat(), end_date.isoformat()))
        return {row[0]: row[1] for row in results}

    def get_topic_performance_report(self, channel_id: int, days: int = 30) -> List[Dict[str, Any]]:
        """Get topic performance report."""
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days)

        query = """
        SELECT
            ft.topic_id,
            ft.title,
            ft.category,
            COUNT(ta.id) as total_assignments,
            AVG(ta.confidence) as avg_confidence,
            SUM(CASE WHEN ta.fallback_used THEN 1 ELSE 0 END) as fallback_count,
            COUNT(DISTINCT DATE(ta.created_at)) as active_days
        FROM forum_topics ft
        LEFT JOIN topic_assignments ta ON ft.channel_id = ta.channel_id AND ft.topic_id = ta.topic_id
        WHERE ft.channel_id = ? AND DATE(ta.created_at) BETWEEN ? AND ?
        GROUP BY ft.topic_id, ft.title, ft.category
        ORDER BY total_assignments DESC
        """

        results = self.execute_query(query, (channel_id, start_date.isoformat(), end_date.isoformat()))
        return [
            {
                'topic_id': row[0], 'title': row[1], 'category': row[2],
                'total_assignments': row[3], 'avg_confidence': round(row[4] or 0, 3),
                'fallback_count': row[5], 'active_days': row[6]
            }
            for row in results
        ]

    def get_organization_efficiency_report(self, channel_id: int, days: int = 30) -> Dict[str, Any]:
        """Get organization efficiency report."""
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days)

        # Get aggregated statistics
        query = """
        SELECT
            SUM(messages_processed) as total_messages,
            SUM(topics_created) as total_topics_created,
            SUM(successful_assignments) as total_successful,
            SUM(failed_assignments) as total_failed,
            SUM(fallback_used) as total_fallback
        FROM organization_stats
        WHERE channel_id = ? AND date BETWEEN ? AND ?
        """

        result = self.execute_query(query, (channel_id, start_date.isoformat(), end_date.isoformat()))

        if result and result[0][0]:  # Check if we have data
            total_messages, topics_created, successful, failed, fallback = result[0]

            success_rate = (successful / total_messages) * 100 if total_messages > 0 else 0
            fallback_rate = (fallback / total_messages) * 100 if total_messages > 0 else 0

            return {
                'period_days': days,
                'total_messages_processed': total_messages,
                'topics_created': topics_created,
                'successful_assignments': successful,
                'failed_assignments': failed,
                'fallback_used': fallback,
                'success_rate_percent': round(success_rate, 2),
                'fallback_rate_percent': round(fallback_rate, 2),
                'avg_messages_per_day': round(total_messages / days, 1) if days > 0 else 0
            }

        return {
            'period_days': days,
            'total_messages_processed': 0,
            'topics_created': 0,
            'successful_assignments': 0,
            'failed_assignments': 0,
            'fallback_used': 0,
            'success_rate_percent': 0.0,
            'fallback_rate_percent': 0.0,
            'avg_messages_per_day': 0.0
        }

    # Configuration Operations
    def get_organization_config(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Get organization configuration for a channel."""
        query = """
        SELECT mode, topic_strategy, fallback_strategy, max_topics_per_channel,
               topic_creation_cooldown, enable_content_analysis, confidence_threshold,
               general_topic_title, auto_cleanup_empty, enable_statistics, debug_mode
        FROM organization_configs
        WHERE channel_id = ?
        """

        result = self.execute_query(query, (channel_id,))
        if result:
            row = result[0]
            return {
                'mode': row[0],
                'topic_strategy': row[1],
                'fallback_strategy': row[2],
                'max_topics_per_channel': row[3],
                'topic_creation_cooldown': row[4],
                'enable_content_analysis': bool(row[5]),
                'confidence_threshold': row[6],
                'general_topic_title': row[7],
                'auto_cleanup_empty': bool(row[8]),
                'enable_statistics': bool(row[9]),
                'debug_mode': bool(row[10])
            }
        return None

    def upsert_organization_config(self, channel_id: int, config: Dict[str, Any]) -> None:
        """Insert or update organization configuration."""
        query = """
        INSERT INTO organization_configs (
            channel_id, mode, topic_strategy, fallback_strategy,
            max_topics_per_channel, topic_creation_cooldown,
            enable_content_analysis, confidence_threshold, general_topic_title,
            auto_cleanup_empty, enable_statistics, debug_mode, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            mode = excluded.mode,
            topic_strategy = excluded.topic_strategy,
            fallback_strategy = excluded.fallback_strategy,
            max_topics_per_channel = excluded.max_topics_per_channel,
            topic_creation_cooldown = excluded.topic_creation_cooldown,
            enable_content_analysis = excluded.enable_content_analysis,
            confidence_threshold = excluded.confidence_threshold,
            general_topic_title = excluded.general_topic_title,
            auto_cleanup_empty = excluded.auto_cleanup_empty,
            enable_statistics = excluded.enable_statistics,
            debug_mode = excluded.debug_mode,
            updated_at = excluded.updated_at
        """

        now = datetime.utcnow().isoformat()
        params = (
            channel_id,
            config.get('mode', 'auto_create'),
            config.get('topic_strategy', 'content_type'),
            config.get('fallback_strategy', 'general_topic'),
            config.get('max_topics_per_channel', 100),
            config.get('topic_creation_cooldown', 30),
            config.get('enable_content_analysis', True),
            config.get('confidence_threshold', 0.7),
            config.get('general_topic_title', 'General Discussion'),
            config.get('auto_cleanup_empty', False),
            config.get('enable_statistics', True),
            config.get('debug_mode', False),
            now, now
        )

        self.execute_update(query, params)

    # Cleanup and Maintenance
    def cleanup_old_stats(self, days_to_keep: int = 90) -> int:
        """Clean up old organization statistics."""
        cutoff_date = (datetime.utcnow().date() - timedelta(days=days_to_keep)).isoformat()

        query = "DELETE FROM organization_stats WHERE date < ?"
        cursor = self.get_connection().cursor()
        cursor.execute(query, (cutoff_date,))
        deleted_count = cursor.rowcount
        self.get_connection().commit()

        return deleted_count

    def get_empty_topics(self, channel_id: int, min_age_hours: int = 24) -> List[int]:
        """Get topics that have no messages assigned and are older than specified age."""
        cutoff_time = (datetime.utcnow() - timedelta(hours=min_age_hours)).isoformat()

        query = """
        SELECT ft.topic_id
        FROM forum_topics ft
        LEFT JOIN topic_assignments ta ON ft.channel_id = ta.channel_id AND ft.topic_id = ta.topic_id
        WHERE ft.channel_id = ? AND ft.created_at < ? AND ta.id IS NULL AND ft.is_active = TRUE
        """

        results = self.execute_query(query, (channel_id, cutoff_time))
        return [row[0] for row in results]