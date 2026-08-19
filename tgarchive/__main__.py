"""
SPECTRA — Telegram Network Discovery & Archiving System
=======================================================

Main entry point for the integrated SPECTRA system.
Provides access to both archiving and discovery capabilities.
"""
from __future__ import annotations

# ── Standard Library ──────────────────────────────────────────────────────
import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# ── Local Imports ──────────────────────────────────────────────────────────
from .core.sync import Config, runner, logger
from .utils.discovery import (
    GroupDiscovery,
    NetworkAnalyzer,
    GroupManager,
    SpectraCrawlerManager,
    ParallelTaskScheduler,
    enhance_config_with_gen_accounts
)
from .db import SpectraDB
from .utils.channel_utils import populate_account_channel_access
from .forwarding import AttachmentForwarder
from .services.scheduler_service import SchedulerDaemon
from .services.mass_migration import MassMigrationManager
from .services.group_mirror import GroupMirrorManager
from .osint.intelligence import IntelligenceCollector
from .services.file_sorting_manager import FileSortingManager
from .services.file_system_watcher import start_watching

# ── Conditional Imports ──────────────────────────────────────────────────
try:
    from .forwarding_processor import CloudProcessor
except ImportError:
    CloudProcessor = None # Or handle more gracefully if forwarding mode is essential
    logger.debug("CloudProcessor could not be imported. A portion of forwarding functionality might be unavailable.")

try:
    from .ui.tui import main as tui_main
    HAS_TUI = True
except ImportError:
    HAS_TUI = False

# ── CLI Parser ─────────────────────────────────────────────────────────────
class GroupedHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Custom help formatter that groups commands by category"""

    def _format_action(self, action):
        # Store original metavar
        original_metavar = action.metavar

        # For subparsers, group commands by category
        if action.choices is not None:
            # Build a {cmd: help} lookup from the subparser action's
            # _choices_actions (where add_parser(help=...) actually stores it).
            choice_helps = {ca.dest: ca.help for ca in getattr(action, '_choices_actions', [])}
            # Define command groups
            command_groups = {
                'Core Operations': ['archive', 'discover', 'network'],
                'Batch/Parallel Operations': ['batch', 'parallel'],
                'Account Management': ['accounts', 'tdata2session'],
                'Forwarding': ['forward'],
                'Configuration': ['config'],
                'Channel Management': ['channels'],
                'Scheduling': ['schedule'],
                'Migration': ['migrate', 'migrate-report', 'rollback'],
                'Advanced Tools': ['download-users', 'mirror', 'osint', 'sort', 'stickers']
            }

            # Build grouped help text
            parts = ['\nAvailable commands (grouped by category):\n']

            for group_name, commands in command_groups.items():
                parts.append(f'\n  {group_name}:')
                for cmd in commands:
                    if cmd in action.choices:
                        help_text = choice_helps.get(cmd, '') or ''
                        parts.append(f'    {cmd:<20}  {help_text}')

            parts.append('\nUse "spectra <command> --help" for more information on a specific command.\n')
            action.metavar = ''.join(parts)

        result = super()._format_action(action)
        action.metavar = original_metavar
        return result


def setup_parser() -> argparse.ArgumentParser:
    """Set up command-line argument parser"""
    parser = argparse.ArgumentParser(
        description="SPECTRA - Telegram Network Discovery & Archiving System",
        formatter_class=GroupedHelpFormatter,
        epilog="""
Examples:
  # Archive a channel
  spectra archive --entity @channel_name

  # Discover groups with depth 2
  spectra discover --seed @seed_channel --depth 2

  # Forward messages for recovery
  spectra forward --origin @source --destination @dest --total-mode

  # Run in TUI mode (default)
  spectra

For more help, visit: https://github.com/SWORDIntel/SPECTRA
        """
    )

    # Main mode selection
    parser.add_argument("--no-tui", action="store_true", help="Run without TUI interface")

    # Global options
    parser.add_argument("--db", type=str, help="Path to SQLite database", default="spectra.db")
    parser.add_argument("--data-dir", type=str, help="Directory for cached data", default="spectra_data")
    parser.add_argument("--config", type=str, help="Path to config file", default="spectra_config.json")
    parser.add_argument("--parallel", action="store_true", help="Enable parallel processing")
    parser.add_argument("--max-workers", type=int, help="Maximum number of parallel workers")
    parser.add_argument("--import-accounts", action="store_true", help="Import accounts from gen_config.py")

    # Add subcommands
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Archive command
    archive_parser = subparsers.add_parser("archive", help="Archive a Telegram channel/group")
    archive_parser.add_argument("--entity", required=True, help="Channel/group to archive (e.g. @channel)")
    archive_parser.add_argument("--no-media", action="store_true", help="Don't download media")
    archive_parser.add_argument("--no-avatars", action="store_true", help="Don't download avatars")
    archive_parser.add_argument("--no-topics", action="store_true", help="Don't archive topics/threads")
    archive_parser.add_argument("--auto", action="store_true", help="Use auto-selected account")

    # Discover command
    discover_parser = subparsers.add_parser("discover", help="Discover Telegram groups")
    discover_parser.add_argument("--seed", help="Seed entity to start discovery from")
    discover_parser.add_argument("--seeds-file", help="File with multiple seed entities (one per line)")
    discover_parser.add_argument("--depth", type=int, default=1, help="Discovery depth (1-3)")
    discover_parser.add_argument("--export", help="Export discovered groups to file")
    discover_parser.add_argument("--crawler-dir", help="Load data from crawler directory")
    discover_parser.add_argument("--messages", type=int, default=1000, help="Maximum messages to check per entity")

    # Network command
    network_parser = subparsers.add_parser("network", help="Analyze network of Telegram groups")
    network_parser.add_argument("--crawler-dir", help="Crawler data directory")
    network_parser.add_argument("--plot", action="store_true", help="Generate network visualization")
    network_parser.add_argument("--metric", default="combined",
                                  choices=["degree", "in_degree", "betweenness", "pagerank", "combined"],
                                  help="Metric for importance calculation")
    network_parser.add_argument("--export", help="Export priority targets to file")
    network_parser.add_argument("--top", type=int, default=20, help="Number of top groups to include")
    network_parser.add_argument("--from-db", action="store_true", help="Use groups from database for analysis")

    # Batch command
    batch_parser = subparsers.add_parser("batch", help="Batch operations on multiple groups")
    batch_parser.add_argument("--file", help="File with list of groups to process")
    batch_parser.add_argument("--from-db", action="store_true", help="Use priority groups from database")
    batch_parser.add_argument("--delay", type=int, default=60, help="Delay between operations (seconds)")
    batch_parser.add_argument("--limit", type=int, default=10, help="Limit number of groups to process")
    batch_parser.add_argument("--min-priority", type=float, default=0.0, help="Minimum priority score")
    batch_parser.add_argument("--no-leave", action="store_true", help="Don't leave groups after archiving")

    # Parallel command
    parallel_parser = subparsers.add_parser("parallel", help="Run operations in parallel across multiple accounts")
    parallel_subparsers = parallel_parser.add_subparsers(dest="parallel_command", help="Parallel command")

    # Parallel discover
    parallel_discover = parallel_subparsers.add_parser("discover", help="Parallel discovery")
    parallel_discover.add_argument("--seeds-file", required=True, help="File with seed entities (one per line)")
    parallel_discover.add_argument("--depth", type=int, default=1, help="Discovery depth (1-3)")
    parallel_discover.add_argument("--max-workers", type=int, help="Maximum parallel workers")
    parallel_discover.add_argument("--export", help="Export discovered groups to file")

    # Parallel join
    parallel_join = parallel_subparsers.add_parser("join", help="Parallel group joining")
    parallel_join.add_argument("--file", required=True, help="File with groups to join (one per line)")
    parallel_join.add_argument("--max-workers", type=int, help="Maximum parallel workers")

    # Parallel archive
    parallel_archive = parallel_subparsers.add_parser("archive", help="Parallel archiving")
    parallel_archive.add_argument("--file", help="File with entities to archive (one per line)")
    parallel_archive.add_argument("--from-db", action="store_true", help="Use priority groups from database")
    parallel_archive.add_argument("--limit", type=int, default=10, help="Limit number of groups")
    parallel_archive.add_argument("--min-priority", type=float, default=0.0, help="Minimum priority score")
    parallel_archive.add_argument("--max-workers", type=int, help="Maximum parallel workers")

    # Account command
    account_parser = subparsers.add_parser("accounts", help="Manage Telegram accounts")
    account_parser.add_argument("--list", action="store_true", help="List all accounts and their status")
    account_parser.add_argument("--reset", action="store_true", help="Reset usage counts for all accounts")
    account_parser.add_argument("--test", action="store_true", help="Test all accounts for connectivity")
    account_parser.add_argument("--import", action="store_true", dest="import_accs", help="Import accounts from gen_config.py")
    account_parser.add_argument("--rotation-stats", action="store_true", help="Show detailed rotation strategy stats (circuit breaker, FloodWait, latency, channel locks)")
    account_parser.add_argument("--set-rotation", type=str, default=None, help="Set rotation mode: sequential, random, weighted, smart, floodwait_adaptive, circuit_breaker, latency, sticky, sharded, primary_fallback")

    # Forwarding command (MERGED)
    forward_parser = subparsers.add_parser("forward", help="Forward messages between channels or perform targeted traversal and downloading. Useful for channel recovery when owner has been banned.")
    # Args for CloudProcessor-based forwarding
    forward_parser.add_argument("--channels-file", type=str, help="Path to a file with initial channel URLs for traversal mode.")
    forward_parser.add_argument("--output-dir", type=str, help="Directory to store downloaded files for traversal mode.")
    forward_parser.add_argument("--max-depth", type=int, default=2, help="Maximum depth to follow channel links during traversal (default: 2).")
    forward_parser.add_argument("--min-files-gateway", type=int, default=100, help="Minimum files for a channel to be a 'gateway' in traversal mode (default: 100).")
    # Args for AttachmentForwarder-based forwarding
    forward_parser.add_argument("--origin", help="Origin channel/chat ID for direct forwarding. Can be channel ID, username, or invite link.")
    forward_parser.add_argument("--destination", help="Destination channel/chat ID for direct forwarding. Can be channel ID, username, or invite link. (uses config default if not set)")
    forward_parser.add_argument("--account", help="Specific account (phone or session name) to use for forwarding")
    forward_parser.add_argument("--total-mode", action="store_true", help="[RECOVERY MODE] Forward from ALL accessible channels in the database to the destination. Used when channel owner is banned and needs to recover all content.")
    forward_parser.add_argument("--all-dialogs", action="store_true", help="Sweep and forward every accessible dialog (groups, channels, private chats) to the destination.")
    forward_parser.add_argument("--forward-to-all-saved", action="store_true", help="Also forward to 'Saved Messages' of all configured accounts (for backup)")
    forward_parser.add_argument("--prepend-origin-info", action="store_true", help="Prepend origin channel info to the message text (useful for recovery tracking)")
    forward_mode_group = forward_parser.add_mutually_exclusive_group()
    forward_mode_group.add_argument(
        "--copy-into-destination",
        "--copy-mode",
        dest="copy_into_destination",
        action="store_true",
        default=False,
        help=(
            "Repost messages into the destination as native posts from the active account instead of using"
            " Telegram's forward header."
        ),
    )
    forward_mode_group.add_argument(
        "--preserve-forward-header",
        "--forward-mode",
        dest="copy_into_destination",
        action="store_false",
        help="Use Telegram's native forward behavior and preserve the forwarded attribution/header.",
    )
    forward_parser.add_argument(
        "--source-topic-id",
        "--source-room-id",
        type=int,
        help="Restrict a single-origin forward to one source forum topic/thread.",
    )
    forward_parser.add_argument(
        "--destination-topic-id",
        "--destination-room-id",
        type=int,
        help="Post forwarded content into a specific destination topic/room inside a forum group.",
    )
    forward_parser.add_argument(
        "--include-text-messages",
        action="store_true",
        help="Include text-only messages in addition to media. Automatically enabled for topic/thread forwarding.",
    )
    forward_parser.add_argument(
        "--quote-copied-messages",
        action="store_true",
        help="When using copy mode, render the original text as a quote block inside the copied post.",
    )
    forward_parser.add_argument("--secondary-unique-destination", type=str, default=None, help="Secondary destination for unique messages only (deduplication required)")
    forward_parser.add_argument("--source-accounts", nargs="+", help="Limit total-mode forwarding to these account identifiers (phone number or session name). Uses all accounts if omitted.")
    forward_parser.add_argument("--include-saved-messages", action="store_true", help="Include Saved Messages when sweeping all dialogs.")
    dialog_private_group = forward_parser.add_mutually_exclusive_group()
    dialog_private_group.add_argument("--include-private-chats", action="store_true", dest="include_private_chats", default=True, help="Include private chats when sweeping all dialogs (default).")
    dialog_private_group.add_argument("--exclude-private-chats", action="store_false", dest="include_private_chats", help="Exclude private chats when sweeping all dialogs.")
    dedup_group = forward_parser.add_mutually_exclusive_group()
    dedup_group.add_argument("--enable-deduplication", action="store_true", dest="enable_deduplication", default=None, help="Enable message deduplication to avoid duplicates (overrides config, recommended for recovery)")
    dedup_group.add_argument("--disable-deduplication", action="store_false", dest="enable_deduplication", help="Disable message deduplication (overrides config)")
    auto_invite_group = forward_parser.add_mutually_exclusive_group()
    auto_invite_group.add_argument("--enable-auto-invites", action="store_true", dest="auto_invite_accounts", default=None, help="Enable automatic account invitations to discovered channels (overrides config)")
    auto_invite_group.add_argument("--disable-auto-invites", action="store_false", dest="auto_invite_accounts", help="Disable automatic account invitations (overrides config)")

    # Config command
    config_parser = subparsers.add_parser("config", help="Manage SPECTRA configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_command", help="Configuration command")
    config_set_fwd_parser = config_subparsers.add_parser("set-forward-dest", help="Set the default forwarding destination ID")
    config_set_fwd_parser.add_argument("destination_id", type=str, help="The destination ID (e.g., channel ID, user ID)")
    config_subparsers.add_parser("view-forward-dest", help="View the default forwarding destination ID")

    # Channels command
    channels_parser = subparsers.add_parser("channels", help="Manage channel-related information")
    channels_subparsers = channels_parser.add_subparsers(dest="channels_command", help="Channel command")
    channels_subparsers.add_parser("update-access", help="Update the list of channels accessible by each account")

    # Scheduler command
    scheduler_parser = subparsers.add_parser("schedule", help="Manage scheduled tasks")
    scheduler_subparsers = scheduler_parser.add_subparsers(dest="schedule_command", help="Scheduler command")
    schedule_add_parser = scheduler_subparsers.add_parser("add", help="Add a new scheduled task")
    schedule_add_parser.add_argument("--name", required=True, help="Name of the task")
    schedule_add_parser.add_argument("--schedule", required=True, help="Cron-style schedule (e.g., '*/5 * * * *')")
    schedule_add_parser.add_argument("--command", required=True, help="Command to execute")
    scheduler_subparsers.add_parser("list", help="List all scheduled tasks")
    schedule_remove_parser = scheduler_subparsers.add_parser("remove", help="Remove a scheduled task")
    schedule_remove_parser.add_argument("--name", required=True, help="Name of the task to remove")
    scheduler_subparsers.add_parser("run", help="Run the scheduler daemon")
    channel_forward_parser = scheduler_subparsers.add_parser("add-channel-forward", help="Add a new channel forwarding schedule")
    channel_forward_parser.add_argument("--channel-id", required=True, type=int, help="ID of the channel to forward from")
    channel_forward_parser.add_argument("--destination", required=True, help="Destination to forward to")
    channel_forward_parser.add_argument("--schedule", required=True, help="Cron-style schedule")
    file_forward_parser = scheduler_subparsers.add_parser("add-file-forward", help="Add a new file forwarding schedule")
    file_forward_parser.add_argument("--source", required=True, help="Source to forward from")
    file_forward_parser.add_argument("--destination", required=True, help="Destination to forward to")
    file_forward_parser.add_argument("--schedule", required=True, help="Cron-style schedule")
    file_forward_parser.add_argument("--file-types", help="Comma-separated list of file types to forward")
    file_forward_parser.add_argument("--min-file-size", type=int, help="Minimum file size in bytes")
    file_forward_parser.add_argument("--max-file-size", type=int, help="Maximum file size in bytes")
    file_forward_parser.add_argument("--priority", type=int, default=0, help="Priority of the schedule")
    report_parser = scheduler_subparsers.add_parser("report", help="Report the status of a file forwarding schedule")
    report_parser.add_argument("--schedule-id", required=True, type=int, help="ID of the schedule to report on")

    # Migrate command
    migrate_parser = subparsers.add_parser("migrate", help="Perform a one-time migration")
    migrate_parser.add_argument("--source", required=True, help="Source to migrate from")
    migrate_parser.add_argument("--destination", required=True, help="Destination to migrate to")
    migrate_parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without actually migrating any files")
    migrate_parser.add_argument("--parallel", action="store_true", help="Use parallel processing for the migration")

    # Migration report command
    migrate_report_parser = subparsers.add_parser("migrate-report", help="Generate a report for a migration")
    migrate_report_parser.add_argument("--migration-id", required=True, type=int, help="ID of the migration to report on")

    # Rollback command
    rollback_parser = subparsers.add_parser("rollback", help="Roll back a migration")
    rollback_parser.add_argument("--migration-id", required=True, type=int, help="ID of the migration to roll back")

    # Download users command
    download_users_parser = subparsers.add_parser("download-users", help="Download user list from a server")
    download_users_parser.add_argument("--server-id", required=True, type=int, help="ID of the server to download users from")
    download_users_parser.add_argument("--output-file", required=True, help="Path to the output file")
    download_users_parser.add_argument("--output-format", default="csv", choices=["csv", "json", "sqlite"], help="Output format")
    download_users_parser.add_argument("--rotate-ip", action="store_true", help="Enable IP rotation on flood wait errors")
    download_users_parser.add_argument("--rate-limit-delay", type=int, default=1, help="Delay in seconds between requests")

    # Mirror command
    mirror_parser = subparsers.add_parser("mirror", help="Mirror a group to another group using two separate accounts")
    mirror_parser.add_argument("--source", required=True, help="Source group ID or username")
    mirror_parser.add_argument("--destination", required=True, help="Destination group ID or username")
    mirror_parser.add_argument("--source-account", required=True, help="Session name or phone number of the account for the source group")
    mirror_parser.add_argument("--destination-account", required=True, help="Session name or phone number of the account for the destination group")

    # OSINT command
    osint_parser = subparsers.add_parser("osint", help="OSINT commands for tracking users and their interactions")
    osint_subparsers = osint_parser.add_subparsers(dest="osint_command", help="OSINT command")
    osint_add_target_parser = osint_subparsers.add_parser("add-target", help="Add a user to the OSINT targets list")
    osint_add_target_parser.add_argument("--user", required=True, help="Username of the user to add")
    osint_add_target_parser.add_argument("--notes", default="", help="Notes about the target")
    osint_remove_target_parser = osint_subparsers.add_parser("remove-target", help="Remove a user from the OSINT targets list")
    osint_remove_target_parser.add_argument("--user", required=True, help="Username of the user to remove")
    osint_subparsers.add_parser("list-targets", help="List all OSINT targets")
    osint_scan_parser = osint_subparsers.add_parser("scan", help="Scan a channel for interactions involving a target user")
    osint_scan_parser.add_argument("--channel", required=True, help="Channel ID or username to scan")
    osint_scan_parser.add_argument("--user", required=True, help="Username of the target user to scan for")
    osint_show_network_parser = osint_subparsers.add_parser("show-network", help="Show the interaction network for a target user")
    osint_show_network_parser.add_argument("--user", required=True, help="Username of the target user")

    # Sort command
    sort_parser = subparsers.add_parser("sort", help="Watch a directory and sort new files by type")
    sort_parser.add_argument("--directory", required=True, help="Directory to watch for new files")
    sort_parser.add_argument("--output-directory", required=True, help="Directory to move sorted files to")

    # tdata2session — convert Telegram Desktop / Alternatives tdata folders into
    # Telethon .session files (no re-login required).
    tdata_parser = subparsers.add_parser(
        "tdata2session",
        help="Convert logged-in Telegram Desktop / Alternatives tdata folders into Telethon .session files",
    )
    tdata_parser.add_argument(
        "--tdata",
        type=str,
        default=None,
        help="Path to the tdata folder. Defaults to auto-detection (Telegram Desktop / Alternatives).",
    )
    tdata_parser.add_argument(
        "--output",
        type=str,
        default="sessions",
        help="Directory to write .session + .json files (default: ./sessions).",
    )
    tdata_parser.add_argument(
        "--passcode",
        type=str,
        default="",
        help="Local passcode if the tdata folder is passcode-protected.",
    )
    tdata_parser.add_argument(
        "--string-sessions",
        action="store_true",
        help="Also emit Telethon StringSession strings in the JSON sidecars.",
    )
    tdata_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .session files instead of skipping them.",
    )
    tdata_parser.add_argument(
        "--register",
        action="store_true",
        help="Register the converted accounts into spectra_config.json so SPECTRA can use them.",
    )
    tdata_parser.add_argument(
        "--account",
        type=str,
        default="all",
        help="Which account(s) to convert: 'all' (default), a numeric user_id, or comma-separated user_ids (e.g., 8011484242,8199441474).",
    )
    tdata_parser.add_argument(
        "--username",
        type=str,
        default=None,
        help="Convert only the account matching this Telegram username (e.g., @someuser). Requires network access to resolve.",
    )
    tdata_parser.add_argument(
        "--list-accounts",
        action="store_true",
        help="List all accounts found in the tdata folder (with --resolve, connects to Telegram to show usernames/names).",
    )
    tdata_parser.add_argument(
        "--resolve",
        action="store_true",
        help="When used with --list-accounts, connect to Telegram to resolve usernames, phones, and display names.",
    )

    # Stickers command — download and archive sticker sets
    stickers_parser = subparsers.add_parser(
        "stickers",
        aliases=["download-stickers"],
        help="Download and archive Telegram sticker sets (.webp, .tgs, .webm) with metadata",
    )
    stickers_parser.add_argument(
        "stickerset",
        type=str,
        help="Sticker set short name or URL (e.g., atklib, https://t.me/addstickers/atklib)",
    )
    stickers_parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output directory (default: ./data/stickers/<set_name>)",
    )
    stickers_parser.add_argument(
        "-s", "--session",
        type=str,
        default=None,
        help="Specific .session file or name in sessions/ to use",
    )
    stickers_parser.add_argument(
        "--sessions-dir",
        type=str,
        default="sessions",
        help="Directory containing converted .session files (default: ./sessions)",
    )
    stickers_parser.add_argument(
        "--info-only",
        action="store_true",
        help="Inspect and display sticker set metadata without downloading",
    )
    stickers_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing sticker files",
    )
    stickers_parser.add_argument(
        "--png", "--convert-png",
        dest="png",
        action="store_true",
        help="Convert downloaded static WebP stickers into PNG format",
    )

    return parser

# ── Command handlers ───────────────────────────────────────────────────────
async def handle_archive(args: argparse.Namespace) -> int:
    """Handle archive command"""
    cfg = Config(Path(args.config))

    # Import accounts from gen_config if requested
    if args.import_accounts:
        cfg = enhance_config_with_gen_accounts(cfg)

    # Set entity and options
    cfg.data["entity"] = args.entity
    cfg.data["download_media"] = not args.no_media
    cfg.data["download_avatars"] = not args.no_avatars
    cfg.data["archive_topics"] = not args.no_topics
    cfg.data["db_path"] = args.db

    # Use auto-selected account or default
    account = cfg.auto_select_account() if args.auto else None

    try:
        await runner(cfg, account)
        logger.info(f"Archive of {args.entity} complete")
        return 0
    except Exception as e:
        logger.error(f"Archive failed: {e}")
        return 1

async def handle_discover(args: argparse.Namespace) -> int:
    """Handle discover command"""
    cfg = Config(Path(args.config))

    # Import accounts from gen_config if requested
    if args.import_accounts:
        cfg = enhance_config_with_gen_accounts(cfg)

    data_dir = Path(args.data_dir)
    db_path = Path(args.db)

    # Use parallel processing if requested
    if args.parallel and args.seeds_file:
        return await handle_parallel_discover(args)

    # Initialize manager with database support
    manager = SpectraCrawlerManager(
        config=cfg,
        data_dir=data_dir,
        db_path=db_path
    )

    if not await manager.initialize():
        logger.error("Failed to initialize crawler manager")
        return 1

    try:
        if args.seed:
            # Discover from seed
            logger.info(f"Starting discovery from {args.seed} with depth {args.depth}")
            discovered = await manager.discover_from_seed(
                args.seed,
                depth=args.depth,
                max_messages=args.messages
            )
            logger.info(f"Discovered {len(discovered)} groups")
        elif args.seeds_file:
            # Load seeds from file
            seeds_path = Path(args.seeds_file)
            if not seeds_path.exists():
                logger.error(f"Seeds file not found: {seeds_path}")
                return 1

            with open(seeds_path, 'r') as f:
                seeds = [line.strip() for line in f if line.strip()]

            if not seeds:
                logger.error(f"No seeds found in {seeds_path}")
                return 1

            # Process each seed sequentially
            all_discovered = set()
            for i, seed in enumerate(seeds):
                logger.info(f"Processing seed {i+1}/{len(seeds)}: {seed}")
                discovered = await manager.discover_from_seed(
                    seed,
                    depth=args.depth,
                    max_messages=args.messages
                )
                all_discovered.update(discovered)

            logger.info(f"Discovered {len(all_discovered)} groups from {len(seeds)} seeds")
        elif args.crawler_dir:
            # Load from crawler data
            crawler_dir = Path(args.crawler_dir)
            if not crawler_dir.exists():
                logger.error(f"Crawler directory not found: {crawler_dir}")
                return 1

            if not manager.discovery:
                logger.error("Discovery component not initialized")
                return 1

            discovered = await manager.discovery.load_crawler_data(crawler_dir)

            # Save to database if using db
            if db_path.exists():
                await manager._save_discovered_groups(discovered, "crawler_import")
                logger.info(f"Saved {len(discovered)} groups to database")

            logger.info(f"Loaded {len(discovered)} groups from crawler data")
        else:
            logger.error("Either --seed, --seeds-file or --crawler-dir must be specified")
            return 1

        # Export if requested
        if args.export:
            if manager.discovery and manager.discovery.discovered_groups:
                output_path = manager.discovery.export_groups_to_file(args.export)
                if output_path:
                    logger.info(f"Exported {len(manager.discovery.discovered_groups)} groups to {output_path}")
                else:
                    logger.error("Failed to export groups")
                    return 1
            else:
                logger.error("No groups to export")
                return 1

        await manager.close()
        return 0

    except Exception as e:
        logger.error(f"Discovery failed: {e}")
        await manager.close()
        return 1

async def handle_network(args: argparse.Namespace) -> int:
    """Handle network command"""
    cfg = Config(Path(args.config))

    # Import accounts from gen_config if requested
    if args.import_accounts:
        cfg = enhance_config_with_gen_accounts(cfg)

    data_dir = Path(args.data_dir)
    db_path = Path(args.db)

    # Initialize manager with database support
    manager = SpectraCrawlerManager(
        config=cfg,
        data_dir=data_dir,
        db_path=db_path
    )

    try:
        if args.from_db and db_path.exists():
            # Use database for network analysis
            logger.info("Using database for network analysis")
            await manager.initialize()
            await manager._update_group_priorities()

            # Get priority targets
            targets = await manager.get_priority_targets(args.top)
            if not targets:
                logger.error("No groups found in database for analysis")
                return 1

            logger.info(f"Analyzed {len(targets)} groups from database")

            # Export if requested
            if args.export and targets:
                try:
                    # Write targets to JSON file
                    import json
                    with open(args.export, 'w') as f:
                        json.dump(targets, f, indent=2)
                    logger.info(f"Exported {len(targets)} priority targets to {args.export}")
                except Exception as e:
                    logger.error(f"Failed to export targets: {e}")

            # Display top targets
            for i, target in enumerate(targets[:5]):  # Show top 5
                logger.info(f"  {i+1}. {target['id']} (Score: {target['priority']})")

        elif args.crawler_dir:
            crawler_dir = Path(args.crawler_dir)
            if not crawler_dir.exists():
                logger.error(f"Crawler directory not found: {crawler_dir}")
                return 1

            # Initialize with db support
            await manager.initialize()

            # Load and analyze network
            targets = await manager.load_and_analyze_network(crawler_dir)
            if not targets:
                logger.error("Failed to analyze network data")
                return 1

            logger.info(f"Analyzed network with {len(targets)} priority targets")

            # Plot if requested
            if args.plot:
                output_file = manager.network_analyzer.plot_network(metric=args.metric)
                if output_file:
                    logger.info(f"Network visualization saved to {output_file}")
                else:
                    logger.error("Failed to generate visualization")

            # Export if requested
            if args.export and targets:
                # Already exported via load_and_analyze_network if using db
                if not db_path.exists():
                    try:
                        # Write targets to JSON file
                        import json
                        with open(args.export, 'w') as f:
                            json.dump(targets, f, indent=2)
                        logger.info(f"Exported {len(targets)} priority targets to {args.export}")
                    except Exception as e:
                        logger.error(f"Failed to export targets: {e}")

            # Display top targets
            for i, target in enumerate(targets[:5]):  # Show top 5
                score_key = "priority" if "priority" in target else "score"
                logger.info(f"  {i+1}. {target['id']} (Score: {target.get(score_key, 0.0)})")
        else:
            logger.error("Either --crawler-dir or --from-db must be specified")
            return 1

        await manager.close()
        return 0

    except Exception as e:
        logger.error(f"Network analysis failed: {e}")
        if manager:
            await manager.close()
        return 1

async def handle_batch(args: argparse.Namespace) -> int:
    """Handle batch command"""
    cfg = Config(Path(args.config))

    # Import accounts from gen_config if requested
    if args.import_accounts:
        cfg = enhance_config_with_gen_accounts(cfg)

    data_dir = Path(args.data_dir)
    db_path = Path(args.db)

    # Use parallel processing if requested
    if args.parallel:
        return await handle_parallel_archive(args)

    # Initialize manager with database support
    manager = SpectraCrawlerManager(
        config=cfg,
        data_dir=data_dir,
        db_path=db_path
    )

    if not await manager.initialize():
        logger.error("Failed to initialize crawler manager")
        return 1

    try:
        groups_to_process = []

        if args.file:
            # Load groups from file
            file_path = Path(args.file)
            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return 1

            with open(file_path, 'r') as f:
                groups_to_process = [line.strip() for line in f if line.strip()]

            logger.info(f"Loaded {len(groups_to_process)} groups from file")

        elif args.from_db:
            # Get priority groups from database
            targets = await manager.get_priority_targets(
                top_n=args.limit,
                min_priority=args.min_priority
            )

            if not targets:
                logger.error("No suitable targets found in database")
                return 1

            groups_to_process = [t["id"] for t in targets]
            logger.info(f"Selected {len(groups_to_process)} priority groups from database")

        else:
            logger.error("Either --file or --from-db must be specified")
            return 1

        # Limit number of groups if needed
        if args.limit and len(groups_to_process) > args.limit:
            groups_to_process = groups_to_process[:args.limit]
            logger.info(f"Limited to {len(groups_to_process)} groups")

        # Process groups
        leave_after = not args.no_leave
        results = await manager.group_manager.batch_join_archive(
            groups_to_process,
            delay=args.delay,
            leave_after=leave_after
        )

        # Show results
        success_count = sum(1 for v in results.values() if v)
        logger.info(f"Processed {len(results)} groups: {success_count} succeeded, {len(results) - success_count} failed")

        await manager.close()
        return 0

    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        await manager.close()
        return 1

async def handle_accounts(args: argparse.Namespace) -> int:
    """Handle accounts command"""
    cfg = Config(Path(args.config))
    db_path = Path(args.db)

    # Set rotation mode if requested
    if getattr(args, "set_rotation", None):
        valid_modes = {
            "sequential", "random", "weighted", "smart",
            "floodwait_adaptive", "circuit_breaker", "latency",
            "sticky", "sharded", "primary_fallback",
        }
        mode = args.set_rotation
        if mode not in valid_modes:
            logger.error(f"Invalid rotation mode: {mode}. Valid: {', '.join(sorted(valid_modes))}")
            return 1
        cfg.data["account_rotation"] = cfg.data.get("account_rotation", {})
        cfg.data["account_rotation"]["mode"] = mode
        cfg.data["account_rotation_mode"] = mode  # legacy flat key
        cfg.save()
        logger.info(f"Rotation mode set to '{mode}' and saved to {args.config}")
        return 0

    # Show rotation strategy stats
    if getattr(args, "rotation_stats", False):
        from .utils.rotation_strategies import AdvancedAccountRotator
        rotator = AdvancedAccountRotator(cfg.active_accounts, config=cfg.data, db_path=db_path)
        stats = rotator.get_stats()
        print(f"\n{'='*60}")
        print(f"  Rotation Strategy Stats")
        print(f"{'='*60}")
        print(f"  Mode:                 {stats['mode']}")
        print(f"  Total accounts:       {stats['accounts']}")
        print(f"  Available:            {stats['available']}")
        print(f"  Archived channels:    {stats['archived_channels']}")
        print()
        print(f"  Circuit Breaker States:")
        for session, state in stats["circuit_breaker_states"].items():
            print(f"    {session:<40} {state}")
        print()
        if stats["floodwait_cooldowns"]:
            print(f"  FloodWait Cooldowns:")
            for session, secs in stats["floodwait_cooldowns"].items():
                print(f"    {session:<40} {secs}s remaining")
            print()
        if stats["latency_ms"]:
            print(f"  Latency (avg ms):")
            for session, ms in sorted(stats["latency_ms"].items(), key=lambda x: x[1]):
                print(f"    {session:<40} {ms:.0f}ms")
            print()
        if stats["sticky_mapping"]:
            print(f"  Sticky Affinity Mapping:")
            for channel, session in stats["sticky_mapping"].items():
                print(f"    {channel:<30} → {session}")
            print()
        if stats["shards"]:
            print(f"  Shard Assignments:")
            for shard, session in sorted(stats["shards"].items()):
                print(f"    Shard {shard}: {session}")
            print()
        if stats["locked_channels"]:
            print(f"  Locked Channels (in progress):")
            for channel, session in stats["locked_channels"].items():
                print(f"    {channel:<30} ← {session}")
            print()
        if stats["primary"]:
            print(f"  Primary account:      {stats['primary']}")
        print(f"{'='*60}\n")
        return 0

    # Import accounts from gen_config if requested
    if args.import_accounts or getattr(args, "import_accs", False):
        cfg = enhance_config_with_gen_accounts(cfg)
        cfg.save()
        logger.info("Saved updated config with imported accounts")

    # Create an account rotator to manage accounts
    manager = GroupManager(cfg, db_path=db_path)

    try:
        if args.list:
            # List all accounts and their status
            account_stats = manager.account_rotator.get_account_stats()

            if not account_stats:
                logger.info("No account statistics available")
                return 0

            logger.info(f"Account statistics ({len(account_stats)} accounts):")
            for i, stats in enumerate(account_stats):
                status = "BANNED" if stats.get("is_banned") else "OK"
                cooldown = f" (cooldown until {stats.get('cooldown_until')})" if stats.get("cooldown_until") else ""
                logger.info(f"  {i+1}. {stats['session']}: Usage: {stats['usage']}, Status: {status}{cooldown}")
                if stats.get("last_error"):
                    logger.info(f"      Last error: {stats['last_error']}")

        if args.reset:
            # Reset usage counts
            manager.account_rotator.reset_usage_counts()
            logger.info("Reset usage counts for all accounts")

        if args.test:
            # Test all accounts
            await manager.init_clients()

            if not manager.clients:
                logger.error("No clients initialized - check account credentials")
                return 1

            logger.info(f"Successfully connected to {len(manager.clients)} accounts:")
            for session_name in manager.clients:
                logger.info(f"  - {session_name}")

        return 0

    except Exception as e:
        logger.error(f"Account management failed: {e}")
        return 1

async def handle_cloud_forwarding(args: argparse.Namespace) -> int:
    """Handle forwarding in traversal/downloading mode via CloudProcessor."""
    logger.info("Cloud forwarding mode invoked:")
    logger.info(f"  Channels file: {args.channels_file}")
    logger.info(f"  Output directory: {args.output_dir}")
    logger.info(f"  Max depth: {args.max_depth}")
    logger.info(f"  Min files for gateway: {args.min_files_gateway}")

    # Load configuration
    cfg = Config(Path(args.config))
    accounts = cfg.accounts
    if not accounts:
        logger.error("No accounts configured. Please import or add accounts to spectra_config.json.")
        return 1

    if CloudProcessor is None:
        logger.error("CloudProcessor is not available. Please check for import errors.")
        return 1

    selected_account = accounts[0]
    logger.info(f"Cloud forwarding will use account: {selected_account.get('session_name', 'N/A')}")

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    processor = CloudProcessor(
        selected_account=selected_account,
        channels_file=args.channels_file,
        output_dir=args.output_dir,
        max_depth=args.max_depth,
        min_files_gateway=args.min_files_gateway,
        config=cfg
    )

    try:
        logger.info("Starting cloud forwarding channel processing...")
        await processor.process_channels()
        logger.info("Cloud forwarding processing completed successfully.")
        return 0
    except Exception as e:
        logger.error(f"A critical error occurred during cloud forwarding: {e}", exc_info=True)
        return 1

async def handle_attachment_forwarding(args: argparse.Namespace) -> int:
    """Handles direct forwarding of messages via AttachmentForwarder."""
    try:
        cfg = Config(Path(args.config))
        db_path = Path(args.db)
        if args.total_mode and not db_path.exists():
            logger.error(f"Database not found at {db_path}. --total-mode requires the database.")
            return 1
        db = SpectraDB(db_path) if db_path.exists() else None

        destination = args.destination or cfg.default_forwarding_destination_id
        if not destination:
            logger.error("Destination ID is required, either via --destination or a config default.")
            return 1
        logger.info(f"Using forwarding destination: {destination}")

        enable_dedup = cfg.data.get("forwarding", {}).get("enable_deduplication", True)
        if args.enable_deduplication is not None:
            enable_dedup = args.enable_deduplication

        secondary_dest = args.secondary_unique_destination or cfg.data.get("forwarding", {}).get("secondary_unique_destination")

        allowed_accounts = args.source_accounts if args.source_accounts else None

        include_private_chats = args.include_private_chats if hasattr(args, "include_private_chats") else True
        include_saved_messages = args.include_saved_messages if hasattr(args, "include_saved_messages") else False
        copy_into_destination = args.copy_into_destination if hasattr(args, "copy_into_destination") else False
        quote_copied_messages = bool(getattr(args, "quote_copied_messages", False))
        source_topic_id = args.source_topic_id if hasattr(args, "source_topic_id") else None
        destination_topic_id = args.destination_topic_id if hasattr(args, "destination_topic_id") else None
        include_text_messages = bool(getattr(args, "include_text_messages", False) or source_topic_id is not None)

        if source_topic_id is not None and (args.all_dialogs or args.total_mode):
            logger.error("--source-topic-id is only supported for single-origin forwarding.")
            return 1

        forwarder = AttachmentForwarder(
            config=cfg,
            db=db,
            forward_to_all_saved_messages=args.forward_to_all_saved,
            prepend_origin_info=args.prepend_origin_info,
            enable_deduplication=enable_dedup,
            secondary_unique_destination=secondary_dest,
            copy_messages_into_destination=copy_into_destination,
            quote_copied_messages=quote_copied_messages,
            destination_topic_id=destination_topic_id,
            source_topic_id=source_topic_id,
            include_text_messages=include_text_messages,
        )
        try:
            if args.all_dialogs:
                logger.info("Starting dialog sweep forwarding across all accessible dialogs.")
                await forwarder.forward_all_dialogs(
                    destination_id=destination,
                    orchestration_account_identifier=args.account,
                    allowed_accounts=allowed_accounts,
                    include_private_chats=include_private_chats,
                    include_saved_messages=include_saved_messages,
                )
                logger.info("Dialog sweep forwarding completed.")
            elif args.total_mode:
                if not db:
                    logger.error("Database connection required for --total-mode.")
                    return 1
                logger.info(f"Starting 'Total Forward Mode' to '{destination}'.")
                await forwarder.forward_all_accessible_channels(
                    destination_id=destination,
                    orchestration_account_identifier=args.account,
                    allowed_accounts=allowed_accounts,
                )
                logger.info("'Total Forward Mode' completed.")
            else:
                if allowed_accounts:
                    logger.warning("--source-accounts is only applied in --total-mode. Ignoring for single origin forwarding.")
                if not args.origin:
                    logger.error("--origin is required when not using --total-mode.")
                    return 1
                logger.info(f"Starting single forward from '{args.origin}' to '{destination}'.")
                await forwarder.forward_messages(
                    origin_id=args.origin,
                    destination_id=destination,
                    account_identifier=args.account
                )
                logger.info("Single forwarding completed.")
            return 0
        finally:
            await forwarder.close()

    except ValueError as ve:
        logger.error(f"Configuration error: {ve}")
        return 1
    except Exception as e:
        logger.error(f"Failed to forward messages: {e}", exc_info=True)
        return 1

# ── Config command handlers ────────────────────────────────────────────────
async def handle_set_forward_dest(args: argparse.Namespace, cfg: Config) -> int:
    """Handle setting the default forwarding destination."""
    try:
        destination_id = args.destination_id
        cfg.default_forwarding_destination_id = destination_id
        cfg.save()
        logger.info(f"Default forwarding destination ID set to: {destination_id}")
        return 0
    except Exception as e:
        logger.error(f"Failed to set forwarding destination ID: {e}")
        return 1

async def handle_view_forward_dest(args: argparse.Namespace, cfg: Config) -> int:
    """Handle viewing the default forwarding destination."""
    try:
        destination_id = cfg.default_forwarding_destination_id
        if destination_id:
            print(f"Default forwarding destination ID: {destination_id}")
        else:
            print("Default forwarding destination ID is not set.")
        return 0
    except Exception as e:
        logger.error(f"Failed to view forwarding destination ID: {e}")
        return 1

async def handle_config(args: argparse.Namespace, cfg: Config) -> int:
    """Handle config commands"""
    if args.config_command == "set-forward-dest":
        return await handle_set_forward_dest(args, cfg)
    elif args.config_command == "view-forward-dest":
        return await handle_view_forward_dest(args, cfg)
    else:
        logger.error(f"Unknown config command: {args.config_command}")
        return 1

# ── Channel command handlers ─────────────────────────────────────────────────
async def handle_update_channel_access(args: argparse.Namespace) -> int:
    """Handle updating the account_channel_access table."""
    try:
        cfg = Config(Path(args.config))
        db = SpectraDB(Path(args.db))

        if args.import_accounts:
            cfg = enhance_config_with_gen_accounts(cfg)

        logger.info("Starting population of account_channel_access table...")
        await populate_account_channel_access(db, cfg)
        logger.info("Finished updating account_channel_access table.")
        return 0
    except Exception as e:
        logger.error(f"Failed to update channel access information: {e}", exc_info=True)
        return 1

# ── Parallel operation handlers ───────────────────────────────────────────────
async def handle_parallel_discover(args: argparse.Namespace) -> int:
    """Handle parallel discover command"""
    cfg = Config(Path(args.config))

    if args.import_accounts:
        cfg = enhance_config_with_gen_accounts(cfg)

    db_path = Path(args.db)
    seeds_file = args.seeds_file

    if not seeds_file:
        logger.error("Missing --seeds-file argument")
        return 1

    seeds_path = Path(seeds_file)
    if not seeds_path.exists():
        logger.error(f"Seeds file not found: {seeds_path}")
        return 1

    with open(seeds_path, 'r') as f:
        seeds = [line.strip() for line in f if line.strip()]

    if not seeds:
        logger.error(f"No seeds found in {seeds_path}")
        return 1

    logger.info(f"Loaded {len(seeds)} seed entities")

    scheduler = ParallelTaskScheduler(
        config=cfg,
        db_path=db_path,
        max_workers=args.max_workers
    )

    try:
        if not await scheduler.initialize():
            logger.error("Failed to initialize parallel scheduler")
            return 1

        logger.info(f"Starting parallel discovery of {len(seeds)} seeds with depth {args.depth}")
        results = await scheduler.parallel_discovery(
            seeds,
            depth=args.depth,
            max_messages=getattr(args, 'messages', 1000),
            max_concurrent=args.max_workers
        )

        total_discovered = sum(len(d) for d in results.values() if d)
        logger.info(f"Parallel discovery complete: {total_discovered} groups discovered.")

        if args.export:
            all_discovered = {group for discovered in results.values() for group in discovered}
            try:
                with open(args.export, 'w') as f:
                    for group in sorted(all_discovered):
                        f.write(f"{group}\n")
                logger.info(f"Exported {len(all_discovered)} groups to {args.export}")
            except Exception as e:
                logger.error(f"Failed to export discovered groups: {e}")

        await scheduler.close()
        return 0
    except Exception as e:
        logger.error(f"Parallel discovery failed: {e}")
        await scheduler.close()
        return 1

async def handle_parallel_join(args: argparse.Namespace) -> int:
    """Handle parallel join command"""
    cfg = Config(Path(args.config))

    if args.import_accounts:
        cfg = enhance_config_with_gen_accounts(cfg)

    db_path = Path(args.db)
    file_path = Path(args.file)

    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return 1

    with open(file_path, 'r') as f:
        groups = [line.strip() for line in f if line.strip()]

    if not groups:
        logger.error(f"No groups found in {file_path}")
        return 1

    logger.info(f"Loaded {len(groups)} groups to join")

    scheduler = ParallelTaskScheduler(
        config=cfg,
        db_path=db_path,
        max_workers=getattr(args, 'max_workers', None)
    )

    try:
        if not await scheduler.initialize():
            logger.error("Failed to initialize parallel scheduler")
            return 1

        logger.info(f"Starting parallel join of {len(groups)} groups")
        results = await scheduler.parallel_join(
            groups,
            max_concurrent=getattr(args, 'max_workers', None)
        )

        success_count = sum(1 for v in results.values() if v is not None)
        logger.info(f"Parallel join complete: {success_count}/{len(groups)} groups joined successfully")

        await scheduler.close()
        return 0
    except Exception as e:
        logger.error(f"Parallel join failed: {e}")
        await scheduler.close()
        return 1

async def handle_parallel_archive(args: argparse.Namespace) -> int:
    """Handle parallel archive command"""
    cfg = Config(Path(args.config))

    if args.import_accounts:
        cfg = enhance_config_with_gen_accounts(cfg)

    data_dir = Path(args.data_dir)
    db_path = Path(args.db)
    entities = []

    if getattr(args, 'file', None):
        file_path = Path(args.file)
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return 1
        with open(file_path, 'r') as f:
            entities = [line.strip() for line in f if line.strip()]
        logger.info(f"Loaded {len(entities)} entities from file")
    elif getattr(args, 'from_db', None):
        manager = SpectraCrawlerManager(config=cfg, data_dir=data_dir, db_path=db_path)
        if not await manager.initialize():
            logger.error("Failed to initialize manager for DB access")
            return 1
        targets = await manager.get_priority_targets(
            top_n=getattr(args, 'limit', 10),
            min_priority=getattr(args, 'min_priority', 0.0)
        )
        await manager.close()
        if not targets:
            logger.error("No suitable targets found in database")
            return 1
        entities = [t["id"] for t in targets]
        logger.info(f"Selected {len(entities)} priority entities from database")
    else:
        logger.error("Either --file or --from-db must be specified for parallel archive")
        return 1

    scheduler = ParallelTaskScheduler(
        config=cfg,
        db_path=db_path,
        max_workers=getattr(args, 'max_workers', None)
    )

    try:
        if not await scheduler.initialize():
            logger.error("Failed to initialize parallel scheduler")
            return 1

        logger.info(f"Starting parallel archive of {len(entities)} entities")
        results = await scheduler.parallel_archive(
            entities,
            max_concurrent=getattr(args, 'max_workers', None)
        )

        success_count = sum(1 for success in results.values() if success)
        logger.info(f"Parallel archive complete: {success_count}/{len(entities)} archived successfully")

        await scheduler.close()
        return 0
    except Exception as e:
        logger.error(f"Parallel archive failed: {e}")
        await scheduler.close()
        return 1

# ── Parallel command handler ───────────────────────────────────────────────
async def handle_parallel(args: argparse.Namespace) -> int:
    """Handle parallel command and its subcommands"""
    command_map = {
        "discover": handle_parallel_discover,
        "join": handle_parallel_join,
        "archive": handle_parallel_archive,
    }
    handler = command_map.get(args.parallel_command)
    if handler:
        return await handler(args)
    else:
        logger.error(f"Unknown parallel command: {args.parallel_command}")
        return 1

# ── Scheduler and Migration Handlers ─────────────────────────────────────
async def handle_schedule(args: argparse.Namespace) -> int:
    """Handle schedule command"""
    cfg = Config(Path(args.config))
    state_path = cfg.data.get("scheduler", {}).get("state_file", "scheduler_state.json")
    scheduler = SchedulerDaemon(args.config, state_path)
    db_path = cfg.data.get("db", {}).get("path", "spectra.db")

    if args.schedule_command == "add":
        scheduler.add_job(args.name, args.schedule, args.command)
        logger.info(f"Added job: {args.name}")
    elif args.schedule_command == "list":
        scheduler.list_jobs()
    elif args.schedule_command == "remove":
        scheduler.remove_job(args.name)
        logger.info(f"Removed job: {args.name}")
    elif args.schedule_command == "run":
        logger.info("Starting scheduler daemon...")
        scheduler.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping scheduler daemon...")
            scheduler.stop()
    elif args.schedule_command == "add-channel-forward":
        db = SpectraDB(db_path)
        db.add_channel_forward_schedule(args.channel_id, args.destination, args.schedule)
        logger.info(f"Added channel forwarding schedule for channel {args.channel_id}")
    elif args.schedule_command == "add-file-forward":
        db = SpectraDB(db_path)
        db.add_file_forward_schedule(args.source, args.destination, args.schedule, args.file_types, args.min_file_size, args.max_file_size, args.priority)
        logger.info(f"Added file forwarding schedule for source {args.source}")
    elif args.schedule_command == "report":
        db = SpectraDB(db_path)
        status_list = db.get_file_forward_queue_status_by_schedule_id(args.schedule_id)
        if not status_list:
            print("No files found for this schedule.")
        else:
            for message_id, file_id, status in status_list:
                print(f"  - Message ID: {message_id}, File ID: {file_id}, Status: {status}")
    else:
        logger.error(f"Unknown schedule command: {args.schedule_command}")
        return 1
    return 0

async def handle_migrate(args: argparse.Namespace) -> int:
    """Handle migrate command"""
    cfg = Config(Path(args.config))
    db = SpectraDB(cfg.data.get("db", {}).get("path", "spectra.db"))
    from telethon import TelegramClient
    account = cfg.auto_select_account()
    if not account:
        logger.error("No account available for this operation.")
        return 1

    client = TelegramClient(account['session_name'], account['api_id'], account['api_hash'])
    await client.connect()
    try:
        manager = MassMigrationManager(cfg, db, client)
        await manager.one_time_migration(args.source, args.destination, args.dry_run, args.parallel)
        return 0
    finally:
        await client.disconnect()

async def handle_rollback(args: argparse.Namespace) -> int:
    """Handle rollback command"""
    cfg = Config(Path(args.config))
    db = SpectraDB(cfg.data.get("db", {}).get("path", "spectra.db"))
    from telethon import TelegramClient
    account = cfg.auto_select_account()
    if not account:
        logger.error("No account available for this operation.")
        return 1

    client = TelegramClient(account['session_name'], account['api_id'], account['api_hash'])
    await client.connect()
    try:
        manager = MassMigrationManager(cfg, db, client)
        return 0 if manager.rollback_migration(args.migration_id) else 1
    finally:
        await client.disconnect()

async def handle_migrate_report(args: argparse.Namespace) -> int:
    """Handle migrate-report command"""
    db = SpectraDB(Config(Path(args.config)).data.get("db", {}).get("path", "spectra.db"))
    report = db.get_migration_report(args.migration_id)
    if not report:
        print(f"No migration found with ID: {args.migration_id}")
        return 1
    source, destination, last_message_id, status, created_at, updated_at = report
    print(f"Migration Report for ID: {args.migration_id}\n  Source: {source}\n  Destination: {destination}\n  Status: {status}\n  Last Message ID: {last_message_id}\n  Started At: {created_at}\n  Last Updated At: {updated_at}")
    return 0

async def handle_download_users(args: argparse.Namespace) -> int:
    """Handle download-users command"""
    cfg = Config(Path(args.config))
    if args.import_accounts:
        cfg = enhance_config_with_gen_accounts(cfg)
    from .utils.user_operations import get_server_users
    from telethon import TelegramClient
    account = cfg.auto_select_account()
    if not account:
        logger.error("No account available for this operation.")
        return 1
    client = TelegramClient(account['session_name'], account['api_id'], account['api_hash'])
    await client.connect()
    try:
        await get_server_users(client, args.server_id, args.output_file, args.output_format, args.rotate_ip, args.rate_limit_delay)
        return 0
    finally:
        await client.disconnect()

async def handle_osint(args: argparse.Namespace) -> int:
    """Handle OSINT commands"""
    cfg = Config(Path(args.config))
    db = SpectraDB(Path(args.db))
    from telethon import TelegramClient
    account = cfg.auto_select_account()
    if not account:
        logger.error("No account available for this operation.")
        return 1
    client = TelegramClient(account['session_name'], account['api_id'], account['api_hash'])
    await client.connect()
    collector = IntelligenceCollector(cfg, db, client)
    try:
        if args.osint_command == "add-target":
            await collector.add_target(args.user, args.notes)
        elif args.osint_command == "remove-target":
            await collector.remove_target(args.user)
        elif args.osint_command == "list-targets":
            await collector.list_targets()
        elif args.osint_command == "scan":
            await collector.scan_channel(args.channel, args.user)
        elif args.osint_command == "show-network":
            await collector.show_network(args.user)
        else:
            logger.error(f"Unknown osint command: {args.osint_command}")
            return 1
        return 0
    finally:
        await client.disconnect()

async def handle_mirror(args: argparse.Namespace) -> int:
    """Handle mirror command"""
    cfg = Config(Path(args.config))
    db = SpectraDB(cfg.data.get("db", {}).get("path", "spectra.db"))
    manager = GroupMirrorManager(
        config=cfg,
        db=db,
        source_account_id=args.source_account,
        dest_account_id=args.destination_account
    )
    try:
        await manager.mirror_group(args.source, args.destination)
        return 0
    finally:
        await manager.close()

async def handle_sort(args: argparse.Namespace) -> int:
    """Handle sort command"""
    cfg = Config(Path(args.config))
    db = SpectraDB(cfg.data.get("db", {}).get("path", "spectra.db"))
    sorting_manager = FileSortingManager(
        config=cfg.data,
        output_dir=args.output_directory,
        db=db
    )
    start_watching(args.directory, sorting_manager)
    return 0

async def handle_tdata2session(args: argparse.Namespace) -> int:
    """Handle tdata2session command — convert tdata folders into Telethon .session files."""
    from .utils.tdata_converter import (
        autodetect_tdata,
        convert_tdata,
        register_into_config,
        parse_account_filter,
        list_tdata_accounts,
        resolve_account_info_async,
        filter_by_username_async,
    )

    # Resolve the tdata folder (explicit flag → auto-detection).
    tdata_path = args.tdata
    if tdata_path:
        tdata_path = Path(tdata_path).expanduser().resolve()
    else:
        tdata_path = autodetect_tdata()
        if tdata_path is None:
            logger.error(
                "No tdata folder found. Pass --tdata /path/to/tdata explicitly."
            )
            return 1
        logger.info(f"Auto-detected tdata folder: {tdata_path}")

    output_dir = Path(args.output).expanduser().resolve()

    # ── --list-accounts: inspect tdata and exit ──
    if args.list_accounts:
        try:
            accounts = list_tdata_accounts(tdata_path, passcode=args.passcode)
        except (FileNotFoundError, RuntimeError) as exc:
            logger.error(str(exc))
            return 1

        if args.resolve:
            logger.info("Resolving usernames via Telegram (requires network)...")
            accounts = await resolve_account_info_async(
                accounts, tdata_path, args.passcode, output_dir
            )

        print(f"\nFound {len(accounts)} account(s) in {tdata_path}:\n")
        print(f"  {'#':<4} {'User ID':<16} {'DC':<4} {'API ID':<10} {'Username':<20} {'Name':<24} {'Phone':<16}")
        print(f"  {'─'*4} {'─'*16} {'─'*4} {'─'*10} {'─'*20} {'─'*24} {'─'*16}")
        for a in accounts:
            name = f"{a.get('first_name') or ''} {a.get('last_name') or ''}".strip() or "-"
            print(
                f"  {a['index']:<4} {a['user_id']:<16} {a['dc_id']:<4} {a['api_id']:<10} "
                f"{a.get('username') or '-':<20} {name:<24} {a.get('phone') or '-':<16}"
            )
        print()
        return 0

    # ── Parse account filter ──
    try:
        user_id_filter, username_filter = parse_account_filter(args.account, args.username)
    except ValueError as exc:
        logger.error(str(exc))
        return 1

    if user_id_filter:
        logger.info(f"Filtering by user_id(s): {sorted(user_id_filter)}")
    elif username_filter:
        logger.info(f"Filtering by username: @{username_filter} (requires network)")

    try:
        report = convert_tdata(
            tdata_path=tdata_path,
            output_dir=output_dir,
            passcode=args.passcode,
            string_sessions=args.string_sessions,
            overwrite=args.overwrite,
            user_id_filter=user_id_filter,
        )
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1

    # ── Username filtering (async — requires connecting to Telegram) ──
    if username_filter and report.converted:
        logger.info("Resolving usernames to filter accounts...")
        report = await filter_by_username_async(report, username_filter)

    # Register into SPECTRA config if requested.
    registered = 0
    if args.register and report.converted:
        try:
            registered = register_into_config(
                report, Path(args.config), session_dir=output_dir
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to register accounts into config: {exc}")

    # Print a human-readable summary.
    print()
    print(report.summary())
    if args.register:
        print(f"\nRegistered into config: {registered} new account(s) → {args.config}")
    print()

    if report.errors:
        for err in report.errors:
            logger.warning(f"Error: {err}")
    if report.skipped:
        for skip in report.skipped:
            logger.info(f"Skipped: {skip}")

    return 0 if report.converted else 1

async def handle_stickers(args: argparse.Namespace) -> int:
    """Handle stickers command — download and archive Telegram sticker sets."""
    from .utils.sticker_downloader import StickerDownloader

    try:
        downloader = StickerDownloader(
            sessions_dir=args.sessions_dir,
            explicit_session=args.session,
        )
    except Exception as exc:
        logger.error(f"Initialization error: {exc}")
        return 1

    if args.info_only:
        try:
            info = await downloader.get_stickerset_info(args.stickerset)
            print(f"\n📦 Sticker Set: {info['title']} (@{info['short_name']})")
            print(f"   Total Stickers: {info['count']}")
            print(f"   Set Type:       {'Animated (.tgs)' if info['is_animated'] else 'Video (.webm)' if info['is_video'] else 'Static (.webp)'}")
            print(f"   Internal ID:    {info['id']}\n")
            return 0
        except Exception as exc:
            logger.error(f"Failed to inspect sticker set: {exc}")
            return 1

    def on_progress(idx: int, total: int, filename: str, skipped: bool):
        action = "⏭️  [SKIPPED]" if skipped else "⬇️  [SAVED]  "
        print(f"[{idx:03d}/{total:03d}] {action} {filename}")

    try:
        res = await downloader.download(
            stickerset_input=args.stickerset,
            output_dir=args.output,
            overwrite=args.overwrite,
            convert_to_png=args.png,
            progress_callback=on_progress,
        )
        png_note = f", {res['converted_png']} converted to PNG" if args.png else ""
        print(f"\n✅ Successfully archived '{res['title']}' ({res['downloaded']} downloaded, {res['skipped']} cached{png_note})")
        print(f"   📁 Destination:   {res['output_dir']}")
        print(f"   📋 Metadata file: {res['metadata_file']}\n")
        return 0
    except Exception as exc:
        logger.error(f"Failed to download sticker set: {exc}")
        return 1

# ── Main function ───────────────────────────────────────────────────────────
async def async_main(args: argparse.Namespace) -> int:
    """Async entry point for command-line application"""

    if args.import_accounts:
        cfg = Config(Path(args.config))
        cfg = enhance_config_with_gen_accounts(cfg)
        cfg.save()
        logger.info(f"Imported accounts and saved to {args.config}")

    tui_options = {
        "db_path": args.db, "data_dir": args.data_dir, "config_path": args.config,
        "parallel": args.parallel, "max_workers": args.max_workers
    }
    if not args.command and not args.no_tui and HAS_TUI:
        return await tui_main(tui_options)

    command_map = {
        "archive": handle_archive,
        "discover": handle_discover,
        "network": handle_network,
        "batch": handle_batch,
        "accounts": handle_accounts,
        "parallel": handle_parallel,
        "schedule": handle_schedule,
        "migrate": handle_migrate,
        "rollback": handle_rollback,
        "migrate-report": handle_migrate_report,
        "osint": handle_osint,
        "mirror": handle_mirror,
        "sort": handle_sort,
        "download-users": handle_download_users,
        "tdata2session": handle_tdata2session,
        "stickers": handle_stickers,
        "download-stickers": handle_stickers,
    }

    if args.command in command_map:
        return await command_map[args.command](args)
    elif args.command == "config":
        return await handle_config(args, Config(Path(args.config)))
    elif args.command == "channels":
        if args.channels_command == "update-access":
            return await handle_update_channel_access(args)
        else:
            logger.error(f"Unknown channels command: {args.channels_command}")
            return 1
    elif args.command == "forward":
        # Decide which forwarding handler to use based on arguments
        if args.channels_file and args.output_dir:
            return await handle_cloud_forwarding(args)
        else:
            return await handle_attachment_forwarding(args)
    else:
        if HAS_TUI and not args.no_tui:
            return await tui_main(tui_options)
        else:
            logger.error("No command specified. Use --help to see available commands.")
            return 1

def main() -> int:
    """Command-line entry point"""
    parser = setup_parser()
    args = parser.parse_args()

    # Default to TUI if no command is given
    if not hasattr(args, 'command') or not args.command:
        if not args.no_tui and HAS_TUI:
            # This is a bit conceptual as tui_main is async.
            # The async_main handles this logic properly.
            return asyncio.run(async_main(args))
        else:
            parser.print_help()
            return 1

    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        logger.info("Operation interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Unhandled error: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
