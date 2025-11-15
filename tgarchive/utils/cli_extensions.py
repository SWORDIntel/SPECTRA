"""
CLI Extensions for Topic Organization
=====================================

Additional command-line arguments and handlers for the topic organization system.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from ..core.config_models import Config
from ..db import SpectraDB
from ..forwarding.enhanced_forwarder import EnhancedAttachmentForwarder
from ..forwarding.organization_engine import OrganizationConfig, OrganizationMode
from ..forwarding.topic_manager import TopicCreationStrategy
from .discovery import enhance_config_with_gen_accounts


logger = logging.getLogger(__name__)


def add_topic_organization_arguments(parser: argparse.ArgumentParser) -> None:
    """Add topic organization arguments to the forward command parser."""

    # Topic organization enable/disable
    topic_group = parser.add_mutually_exclusive_group()
    topic_group.add_argument(
        "--enable-topic-organization",
        action="store_true",
        dest="enable_topic_organization",
        default=None,
        help="Enable intelligent topic organization for forum channels (overrides config)"
    )
    topic_group.add_argument(
        "--disable-topic-organization",
        action="store_false",
        dest="enable_topic_organization",
        help="Disable topic organization, use manual topic assignment only"
    )

    # Organization mode
    parser.add_argument(
        "--organization-mode",
        choices=["disabled", "auto_create", "existing_only", "hybrid"],
        help="Topic organization mode (auto_create, existing_only, hybrid, disabled)"
    )

    # Topic creation strategy
    parser.add_argument(
        "--topic-strategy",
        choices=["content_type", "date_based", "file_extension", "source_channel", "custom_rules", "hybrid"],
        help="Strategy for topic creation (content_type, date_based, file_extension, etc.)"
    )

    # Fallback strategy
    parser.add_argument(
        "--fallback-strategy",
        choices=["general_topic", "no_topic", "retry_once", "queue_for_retry"],
        help="Fallback strategy when topic creation fails"
    )

    # Topic creation parameters
    parser.add_argument(
        "--max-topics-per-channel",
        type=int,
        help="Maximum number of topics per channel (default: 100)"
    )

    parser.add_argument(
        "--topic-creation-cooldown",
        type=int,
        help="Minimum seconds between topic creations (default: 30)"
    )

    parser.add_argument(
        "--classification-confidence-threshold",
        type=float,
        help="Minimum confidence threshold for content classification (0.0-1.0, default: 0.7)"
    )

    parser.add_argument(
        "--general-topic-title",
        type=str,
        help="Title for the general fallback topic (default: 'General Discussion')"
    )

    # Content analysis options
    parser.add_argument(
        "--disable-content-analysis",
        action="store_true",
        help="Disable content analysis and use basic categorization only"
    )

    # Statistics and maintenance
    parser.add_argument(
        "--enable-auto-cleanup",
        action="store_true",
        help="Enable automatic cleanup of empty topics"
    )

    parser.add_argument(
        "--disable-statistics",
        action="store_true",
        help="Disable organization statistics collection"
    )

    # Debug mode
    parser.add_argument(
        "--topic-debug",
        action="store_true",
        help="Enable debug mode for topic organization"
    )


def add_topic_management_command(subparsers) -> None:
    """Add the topic management command to the CLI parser."""

    topic_parser = subparsers.add_parser("topics", help="Manage forum topics and organization")
    topic_subparsers = topic_parser.add_subparsers(dest="topic_command", help="Topic management command")

    # List topics
    list_parser = topic_subparsers.add_parser("list", help="List forum topics for a channel")
    list_parser.add_argument("--channel", required=True, type=str, help="Channel ID or username")
    list_parser.add_argument("--category", type=str, help="Filter by category")
    list_parser.add_argument("--active-only", action="store_true", help="Show only active topics")

    # Create topic
    create_parser = topic_subparsers.add_parser("create", help="Create a new forum topic")
    create_parser.add_argument("--channel", required=True, type=str, help="Channel ID or username")
    create_parser.add_argument("--title", required=True, type=str, help="Topic title")
    create_parser.add_argument("--category", type=str, help="Topic category")
    create_parser.add_argument("--icon-color", type=str, help="Topic icon color (hex format)")
    create_parser.add_argument("--description", type=str, help="Topic description")

    # Update topic
    update_parser = topic_subparsers.add_parser("update", help="Update an existing topic")
    update_parser.add_argument("--channel", required=True, type=str, help="Channel ID or username")
    update_parser.add_argument("--topic-id", required=True, type=int, help="Topic ID to update")
    update_parser.add_argument("--title", type=str, help="New topic title")
    update_parser.add_argument("--category", type=str, help="New topic category")
    update_parser.add_argument("--description", type=str, help="New topic description")

    # Delete topic
    delete_parser = topic_subparsers.add_parser("delete", help="Delete/deactivate a topic")
    delete_parser.add_argument("--channel", required=True, type=str, help="Channel ID or username")
    delete_parser.add_argument("--topic-id", required=True, type=int, help="Topic ID to delete")
    delete_parser.add_argument("--confirm", action="store_true", help="Confirm deletion")

    # Topic statistics
    stats_parser = topic_subparsers.add_parser("stats", help="Show topic usage statistics")
    stats_parser.add_argument("--channel", required=True, type=str, help="Channel ID or username")
    stats_parser.add_argument("--days", type=int, default=30, help="Number of days to analyze")
    stats_parser.add_argument("--export", type=str, help="Export statistics to file")

    # Organization report
    report_parser = topic_subparsers.add_parser("report", help="Generate organization effectiveness report")
    report_parser.add_argument("--channel", required=True, type=str, help="Channel ID or username")
    report_parser.add_argument("--days", type=int, default=7, help="Number of days to analyze")
    report_parser.add_argument("--format", choices=["json", "text", "csv"], default="text", help="Output format")
    report_parser.add_argument("--output", type=str, help="Output file (default: stdout)")

    # Configuration management
    config_parser = topic_subparsers.add_parser("config", help="Manage topic organization configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_action", help="Configuration action")

    # View config
    config_view = config_subparsers.add_parser("view", help="View current configuration")
    config_view.add_argument("--channel", required=True, type=str, help="Channel ID or username")

    # Set config
    config_set = config_subparsers.add_parser("set", help="Set configuration option")
    config_set.add_argument("--channel", required=True, type=str, help="Channel ID or username")
    config_set.add_argument("--mode", choices=["disabled", "auto_create", "existing_only", "hybrid"], help="Organization mode")
    config_set.add_argument("--strategy", choices=["content_type", "date_based", "file_extension", "hybrid"], help="Topic creation strategy")
    config_set.add_argument("--max-topics", type=int, help="Maximum topics per channel")
    config_set.add_argument("--cooldown", type=int, help="Topic creation cooldown seconds")

    # Cleanup command
    cleanup_parser = topic_subparsers.add_parser("cleanup", help="Clean up empty or unused topics")
    cleanup_parser.add_argument("--channel", required=True, type=str, help="Channel ID or username")
    cleanup_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without actually deleting")
    cleanup_parser.add_argument("--min-age-hours", type=int, default=24, help="Minimum age in hours for cleanup")


async def handle_topic_management(args: argparse.Namespace) -> int:
    """Handle topic management commands."""
    try:
        cfg = Config(Path(args.config))

        # Import accounts if requested
        if args.import_accounts:
            cfg = enhance_config_with_gen_accounts(cfg)

        db_path = Path(args.db)
        db = SpectraDB(db_path) if db_path.exists() else None

        if not db:
            logger.error(f"Database not found at {db_path}. Topic management requires database.")
            return 1

        # Route to appropriate handler
        if args.topic_command == "list":
            return await handle_list_topics(args, cfg, db)
        elif args.topic_command == "create":
            return await handle_create_topic(args, cfg, db)
        elif args.topic_command == "update":
            return await handle_update_topic(args, cfg, db)
        elif args.topic_command == "delete":
            return await handle_delete_topic(args, cfg, db)
        elif args.topic_command == "stats":
            return await handle_topic_stats(args, cfg, db)
        elif args.topic_command == "report":
            return await handle_organization_report(args, cfg, db)
        elif args.topic_command == "config":
            return await handle_topic_config(args, cfg, db)
        elif args.topic_command == "cleanup":
            return await handle_topic_cleanup(args, cfg, db)
        else:
            logger.error(f"Unknown topic command: {args.topic_command}")
            return 1

    except Exception as e:
        logger.error(f"Error in topic management: {e}")
        return 1


async def handle_list_topics(args: argparse.Namespace, cfg: Config, db: SpectraDB) -> int:
    """Handle listing forum topics."""
    from .forwarding.topic_manager import TopicManager
    from .forwarding.client import ClientManager

    try:
        client_manager = ClientManager(cfg)
        client = await client_manager.get_client()

        # Resolve channel
        channel_entity = await client.get_entity(args.channel)
        channel_id = channel_entity.id

        # Initialize topic manager
        topic_manager = TopicManager(client, channel_id)

        if not await topic_manager.initialize():
            logger.error("Failed to initialize topic manager")
            return 1

        # Get topic information from cache (loaded during initialization)
        cache_stats = topic_manager.get_cache_stats()
        logger.info(f"Found {cache_stats['size']} topics in {args.channel}")

        # TODO: Implement topic listing from database
        # This would require extending TopicManager to work with TopicOperations

        await client_manager.close()
        return 0

    except Exception as e:
        logger.error(f"Error listing topics: {e}")
        return 1


async def handle_create_topic(args: argparse.Namespace, cfg: Config, db: SpectraDB) -> int:
    """Handle creating a new forum topic."""
    from .forwarding.topic_manager import TopicManager
    from .forwarding.client import ClientManager

    try:
        client_manager = ClientManager(cfg)
        client = await client_manager.get_client()

        # Resolve channel
        channel_entity = await client.get_entity(args.channel)
        channel_id = channel_entity.id

        # Initialize topic manager
        topic_manager = TopicManager(client, channel_id)

        if not await topic_manager.initialize():
            logger.error("Failed to initialize topic manager")
            return 1

        # Parse icon color if provided
        icon_color = 0x3498db  # Default blue
        if args.icon_color:
            try:
                icon_color = int(args.icon_color.replace('#', ''), 16)
            except ValueError:
                logger.warning(f"Invalid icon color format: {args.icon_color}, using default")

        # Create topic
        content_metadata = {
            'content_type': 'manual',
            'category': args.category or 'general',
            'title': args.title
        }

        topic_id = await topic_manager.get_or_create_topic(content_metadata)

        if topic_id:
            logger.info(f"Created topic '{args.title}' with ID {topic_id}")

            # TODO: Record in database via TopicOperations

            await client_manager.close()
            return 0
        else:
            logger.error(f"Failed to create topic '{args.title}'")
            return 1

    except Exception as e:
        logger.error(f"Error creating topic: {e}")
        return 1


async def handle_organization_report(args: argparse.Namespace, cfg: Config, db: SpectraDB) -> int:
    """Handle generating organization effectiveness report."""
    from .db.topic_operations import TopicOperations

    try:
        # Resolve channel ID
        from .forwarding.client import ClientManager
        client_manager = ClientManager(cfg)
        client = await client_manager.get_client()

        channel_entity = await client.get_entity(args.channel)
        channel_id = channel_entity.id

        # Initialize topic operations
        topic_ops = TopicOperations(str(db.db_path))

        # Generate report
        efficiency_report = topic_ops.get_organization_efficiency_report(channel_id, args.days)
        topic_performance = topic_ops.get_topic_performance_report(channel_id, args.days)
        category_distribution = topic_ops.get_category_distribution(channel_id, args.days)

        # Format and output report
        if args.format == "json":
            import json
            report_data = {
                "channel_id": channel_id,
                "period_days": args.days,
                "efficiency": efficiency_report,
                "topic_performance": topic_performance,
                "category_distribution": category_distribution
            }

            output_text = json.dumps(report_data, indent=2)
        else:
            # Text format
            output_lines = [
                f"Organization Report for Channel {channel_id}",
                f"Period: {args.days} days",
                "=" * 50,
                "",
                "Efficiency Metrics:",
                f"  Total Messages Processed: {efficiency_report.get('total_messages_processed', 0)}",
                f"  Success Rate: {efficiency_report.get('success_rate_percent', 0):.1f}%",
                f"  Fallback Rate: {efficiency_report.get('fallback_rate_percent', 0):.1f}%",
                f"  Topics Created: {efficiency_report.get('topics_created', 0)}",
                f"  Average Messages/Day: {efficiency_report.get('avg_messages_per_day', 0):.1f}",
                "",
                "Top Performing Topics:",
            ]

            for i, topic in enumerate(topic_performance[:5], 1):
                output_lines.append(
                    f"  {i}. {topic['title']} ({topic['category']}) - "
                    f"{topic['total_assignments']} messages, "
                    f"{topic['avg_confidence']:.2f} confidence"
                )

            output_lines.extend([
                "",
                "Category Distribution:",
            ])

            for category, count in list(category_distribution.items())[:10]:
                output_lines.append(f"  {category}: {count}")

            output_text = "\n".join(output_lines)

        # Output to file or stdout
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output_text)
            logger.info(f"Report saved to {args.output}")
        else:
            print(output_text)

        await client_manager.close()
        return 0

    except Exception as e:
        logger.error(f"Error generating organization report: {e}")
        return 1


async def handle_topic_config(args: argparse.Namespace, cfg: Config, db: SpectraDB) -> int:
    """Handle topic organization configuration."""
    from .db.topic_operations import TopicOperations
    from .forwarding.client import ClientManager

    try:
        # Resolve channel ID
        client_manager = ClientManager(cfg)
        client = await client_manager.get_client()

        channel_entity = await client.get_entity(args.channel)
        channel_id = channel_entity.id

        # Initialize topic operations
        topic_ops = TopicOperations(str(db.db_path))

        if args.config_action == "view":
            # View current configuration
            config = topic_ops.get_organization_config(channel_id)

            if config:
                logger.info(f"Organization Configuration for Channel {channel_id}:")
                for key, value in config.items():
                    logger.info(f"  {key}: {value}")
            else:
                logger.info(f"No configuration found for channel {channel_id}")

        elif args.config_action == "set":
            # Set configuration options
            config_updates = {}

            if args.mode:
                config_updates['mode'] = args.mode
            if args.strategy:
                config_updates['topic_strategy'] = args.strategy
            if args.max_topics:
                config_updates['max_topics_per_channel'] = args.max_topics
            if args.cooldown:
                config_updates['topic_creation_cooldown'] = args.cooldown

            if config_updates:
                topic_ops.upsert_organization_config(channel_id, config_updates)
                logger.info(f"Updated configuration for channel {channel_id}")

                # Show updated config
                updated_config = topic_ops.get_organization_config(channel_id)
                for key, value in config_updates.items():
                    logger.info(f"  {key}: {updated_config.get(key, 'Not set')}")
            else:
                logger.warning("No configuration options specified")

        await client_manager.close()
        return 0

    except Exception as e:
        logger.error(f"Error managing topic configuration: {e}")
        return 1


def create_organization_config_from_args(args: argparse.Namespace) -> OrganizationConfig:
    """Create OrganizationConfig from command-line arguments."""
    config = OrganizationConfig()

    # Map arguments to configuration
    if hasattr(args, 'organization_mode') and args.organization_mode:
        config.mode = OrganizationMode(args.organization_mode)

    if hasattr(args, 'topic_strategy') and args.topic_strategy:
        config.topic_strategy = TopicCreationStrategy(args.topic_strategy)

    if hasattr(args, 'fallback_strategy') and args.fallback_strategy:
        from .forwarding.organization_engine import FallbackStrategy
        config.fallback_strategy = FallbackStrategy(args.fallback_strategy)

    if hasattr(args, 'max_topics_per_channel') and args.max_topics_per_channel:
        config.max_topics_per_channel = args.max_topics_per_channel

    if hasattr(args, 'topic_creation_cooldown') and args.topic_creation_cooldown:
        config.topic_creation_cooldown_seconds = args.topic_creation_cooldown

    if hasattr(args, 'classification_confidence_threshold') and args.classification_confidence_threshold:
        config.classification_confidence_threshold = args.classification_confidence_threshold

    if hasattr(args, 'general_topic_title') and args.general_topic_title:
        config.general_topic_title = args.general_topic_title

    if hasattr(args, 'disable_content_analysis') and args.disable_content_analysis:
        config.enable_content_analysis = False

    if hasattr(args, 'enable_auto_cleanup') and args.enable_auto_cleanup:
        config.auto_cleanup_empty_topics = True

    if hasattr(args, 'disable_statistics') and args.disable_statistics:
        config.enable_statistics = False

    if hasattr(args, 'topic_debug') and args.topic_debug:
        config.debug_mode = True

    return config


# Placeholder handlers for other topic commands
async def handle_update_topic(args: argparse.Namespace, cfg: Config, db: SpectraDB) -> int:
    logger.info("Topic update functionality not yet implemented")
    return 0

async def handle_delete_topic(args: argparse.Namespace, cfg: Config, db: SpectraDB) -> int:
    logger.info("Topic deletion functionality not yet implemented")
    return 0

async def handle_topic_stats(args: argparse.Namespace, cfg: Config, db: SpectraDB) -> int:
    logger.info("Topic statistics functionality not yet implemented")
    return 0

async def handle_topic_cleanup(args: argparse.Namespace, cfg: Config, db: SpectraDB) -> int:
    logger.info("Topic cleanup functionality not yet implemented")
    return 0