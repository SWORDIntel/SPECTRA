"""
SPECTRA-003 TUI — Advanced Telegram Archiving & Discovery Interface
==================================================================
*Integrated TUI* · *Group Discovery* · *Network Analysis* · *Batch Operations*

Comprehensive npyscreen-based Terminal UI for the SPECTRA system, integrating
both archiving and discovery capabilities.
"""
from __future__ import annotations

# ── Standard Library ──────────────────────────────────────────────────────
import asyncio
import curses
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast

# ── Third-party ───────────────────────────────────────────────────────────
import npyscreen
from rich.console import Console

# ── Local Imports ──────────────────────────────────────────────────────────
from ..utils import discovery
from ..core.sync import Config, logger
from ..db import SpectraDB
from ..utils.channel_utils import populate_account_channel_access
from ..forwarding import AttachmentForwarder
from ..forms import VPSConfigForm # Import the new form
from ..utils.user_operations import get_server_users
from ..services.group_mirror import GroupMirrorManager

# ── Global Config ──────────────────────────────────────────────────────────
TZ = timezone.utc
console = Console()
TITLE = """
╔═══════════════════════════════════════════════════════════════════════════╗
║                          ███████╗██████╗ ███████╗ ██████╗████████╗██████╗  ║
║                          ██╔════╝██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗ ║
║                          ███████╗██████╔╝█████╗  ██║        ██║   ██████╔╗ ║
║                          ╚════██║██╔═══╝ ██╔══╝  ██║        ██║   ██╔══██║ ║
║                          ███████║██║     ███████╗╚██████╗   ██║   ██║  ██║ ║
║                          ╚══════╝╚═╝     ╚══════╝ ╚═════╝   ╚═╝   ╚═╝  ╚═╝ ║
╚═══════════════════════════════════════════════════════════════════════════╝
               Telegram Network Discovery & Archiving System v3.0
"""


# ── Async Helper ───────────────────────────────────────────────────────────
class AsyncRunner:
    """Helper class to run async functions from npyscreen"""
    
    @staticmethod
    def run_async(coroutine):
        """Run an async function and wait for the result"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coroutine)

    @staticmethod
    def run_in_thread(coroutine, callback=None):
        """Run an async function in a separate thread"""
        def _worker():
            result = AsyncRunner.run_async(coroutine)
            if callback:
                callback(result)
        
        thread = threading.Thread(target=_worker)
        thread.daemon = True
        thread.start()
        return thread


# ── Status Messages Widget ───────────────────────────────────────────────────
class StatusMessages(npyscreen.BoxTitle):
    """Widget for displaying status messages in a scrollable box"""
    
    _contained_widget = npyscreen.MultiLine
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages = []
        self.entry_order = []
        self.max_messages = 1000
        
    def add_message(self, message, level="INFO"):
        """Add a new message to the log with timestamp"""
        timestamp = datetime.now(TZ).strftime("%H:%M:%S")
        entry = f"[{timestamp}] {level}: {message}"
        
        # Add to the beginning for reverse chronological order
        self.messages.insert(0, entry)
        self.entry_order.insert(0, entry)
        
        # Limit the number of messages
        if len(self.messages) > self.max_messages:
            self.messages.pop()
            self.entry_order.pop()
            
        self.update_display()
        
    def update_display(self):
        """Update the display with current messages"""
        self.values = self.messages
        self.display()


# ── Graph Explorer Form ──────────────────────────────────────────────────────
class GraphExplorerForm(npyscreen.Form):
    """Form for visualizing and exploring the network graph"""
    
    def create(self):
        self.name = "SPECTRA Network Explorer"
        self.manager = self.parentApp.manager
        
        # Instructions
        self.add(npyscreen.FixedText, value=TITLE)
        self.add(npyscreen.FixedText, value="Network Graph Explorer - Analyze Telegram Group Relationships")
        self.add(npyscreen.FixedText, value="")
        
        # Network loading options
        self.add(npyscreen.TitleText, name="Crawler Directory:", value=str(Path.cwd() / "telegram-groups-crawler"))
        
        # Buttons for actions
        self.add(npyscreen.ButtonPress, name="Load Network Data", when_pressed_function=self.load_network)
        self.add(npyscreen.ButtonPress, name="Generate Network Visualization", when_pressed_function=self.visualize_network)
        self.add(npyscreen.FixedText, value="")
        
        # Metrics selection for targeting
        self.add(npyscreen.TitleSelectOne, name="Importance Metric:",
                max_height=5, value=[4],
                values=["Degree Centrality", "In-Degree Centrality", "Betweenness Centrality", 
                       "PageRank", "Combined Score"])
        
        self.top_n = self.add(npyscreen.TitleSlider, name="Top Groups:", 
                            out_of=50, step=5, value=10)
        
        # Results area
        self.add(npyscreen.FixedText, value="")
        self.add(npyscreen.FixedText, value="Priority Targets (Select number of groups above):")
        self.targets_box = self.add(npyscreen.Pager, name="Priority Targets", height=10)
        
        # Status and navigation
        self.status = self.add(StatusMessages, name="Status Messages", max_height=8)
        self.add(npyscreen.ButtonPress, name="Archive Selected Targets", when_pressed_function=self.archive_targets)
        self.add(npyscreen.ButtonPress, name="Export Target List", when_pressed_function=self.export_targets)
        self.add(npyscreen.ButtonPress, name="Back to Main Menu", when_pressed_function=self.back_to_main)
        
        # Initialize
        self.targets = []
        self.status.add_message("Graph Explorer ready. Load network data to begin.")
        
    def load_network(self):
        """Load network data from crawler"""
        self.status.add_message("Loading network data...")
        
        crawler_dir = Path(self.get_widget(1).value)
        
        def load_callback(targets):
            if targets:
                self.targets = targets
                self.update_targets_display()
                self.status.add_message(f"Loaded network with {len(self.manager.network.graph.nodes())} nodes and " 
                                      f"{len(self.manager.network.graph.edges())} edges")
            else:
                self.status.add_message("Failed to load network data", "ERROR")
        
        AsyncRunner.run_in_thread(
            self.manager.load_and_analyze_network(crawler_dir),
            callback=load_callback
        )
    
    def update_targets_display(self):
        """Update the display of priority targets"""
        if not self.targets:
            self.targets_box.values = ["No targets available. Load network data first."]
            return
            
        # Limit to top_n
        top_n = self.top_n.value
        display_targets = self.targets[:top_n]
        
        # Format for display
        lines = []
        for i, target in enumerate(display_targets):
            lines.append(f"{i+1}. {target['id']} (Score: {target['score']:.4f})")
            
        self.targets_box.values = lines
        self.targets_box.display()
    
    def visualize_network(self):
        """Generate network visualization"""
        if not self.manager.network.graph.nodes():
            self.status.add_message("No network data loaded", "ERROR")
            return
            
        metrics = ["degree", "in_degree", "betweenness", "pagerank", "combined"]
        selected_idx = self.get_widget(6).value[0]
        selected_metric = metrics[selected_idx]
            
        self.status.add_message(f"Generating network visualization using {selected_metric} metric...")
        
        def viz_callback(output_file):
            if output_file:
                self.status.add_message(f"Network visualization saved to {output_file}")
                
                # Show file path in a popup
                npyscreen.notify_confirm(
                    f"Network graph visualization saved to:\n\n{output_file}\n\nUse a graphical file viewer to open.",
                    title="Visualization Complete"
                )
            else:
                self.status.add_message("Failed to generate visualization", "ERROR")
        
        AsyncRunner.run_in_thread(
            self.manager.network.plot_network(metric=selected_metric),
            callback=viz_callback
        )
    
    def archive_targets(self):
        """Archive the priority targets"""
        if not self.targets:
            self.status.add_message("No targets available to archive", "ERROR")
            return
            
        top_n = self.top_n.value
        
        if npyscreen.notify_yes_no(
            f"Archive top {top_n} priority targets?\n\nThis will join groups and archive content.",
            title="Confirm Batch Archive"
        ):
            self.status.add_message(f"Starting batch archive of {top_n} targets...")
            
            def archive_callback(results):
                success_count = sum(1 for success in results.values() if success)
                self.status.add_message(f"Batch archive complete: {success_count}/{len(results)} successful")
            
            AsyncRunner.run_in_thread(
                self.manager.archive_priority_targets(top_n=top_n),
                callback=archive_callback
            )
    
    def export_targets(self):
        """Export the priority targets to a file"""
        if not self.targets:
            self.status.add_message("No targets available to export", "ERROR")
            return
            
        top_n = self.top_n.value
        
        # Filename with timestamp
        timestamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
        filename = f"priority_targets_{timestamp}.json"
        file_path = self.manager.data_dir / filename
        
        # Export
        try:
            with open(file_path, 'w') as f:
                json.dump(self.targets[:top_n], f, indent=2)
            
            self.status.add_message(f"Exported {top_n} targets to {file_path}")
            
            # Show file path in a popup
            npyscreen.notify_confirm(
                f"Target list exported to:\n\n{file_path}",
                title="Export Complete"
            )
        except Exception as e:
            self.status.add_message(f"Failed to export targets: {e}", "ERROR")
    
    def back_to_main(self):
        """Return to the main menu"""
        self.parentApp.switchForm("MAIN")


# ── Discovery Form ──────────────────────────────────────────────────────────
class DiscoveryForm(npyscreen.Form):
    """Form for discovering Telegram groups from seeds"""
    
    def create(self):
        self.name = "SPECTRA Group Discovery"
        self.manager = self.parentApp.manager
        
        # Instructions
        self.add(npyscreen.FixedText, value=TITLE)
        self.add(npyscreen.FixedText, value="Group Discovery - Find Telegram Groups from Seeds")
        self.add(npyscreen.FixedText, value="")
        
        # Input fields
        self.seed_input = self.add(npyscreen.TitleText, name="Seed Entity (e.g. @channel):")
        self.depth = self.add(npyscreen.TitleSlider, name="Discovery Depth:", 
                            out_of=3, value=1,
                            comment="Higher depth = exponential search")
        self.msg_limit = self.add(npyscreen.TitleSlider, name="Messages to Scan:", 
                               out_of=2000, step=100, value=500)
        
        # Options for loading existing data
        self.add(npyscreen.FixedText, value="")
        self.add(npyscreen.FixedText, value="Additional Data Sources:")
        self.crawler_path = self.add(npyscreen.TitleText, name="Crawler Directory:", 
                                  value=str(Path.cwd() / "telegram-groups-crawler"))
        
        # Action buttons
        self.add(npyscreen.ButtonPress, name="Start Discovery from Seed", when_pressed_function=self.start_discovery)
        self.add(npyscreen.ButtonPress, name="Load Data from Crawler", when_pressed_function=self.load_crawler_data)
        self.add(npyscreen.ButtonPress, name="Export Discovered Groups", when_pressed_function=self.export_groups)
        
        # Results area
        self.add(npyscreen.FixedText, value="")
        self.add(npyscreen.TitleText, name="Discovered Groups Count:", value="0", editable=False)
        self.groups_box = self.add(npyscreen.Pager, name="Discovered Groups (Sample)", height=8)
        
        # Status and navigation
        self.status = self.add(StatusMessages, name="Status Messages", max_height=8)
        self.add(npyscreen.ButtonPress, name="Archive Selected Groups", when_pressed_function=self.archive_groups)
        self.add(npyscreen.ButtonPress, name="Back to Main Menu", when_pressed_function=self.back_to_main)
        
        # Initialize
        self.status.add_message("Group Discovery ready. Enter a seed entity to begin.")
    
    def update_groups_display(self):
        """Update the display of discovered groups"""
        if not self.manager.discovery or not self.manager.discovery.discovered_groups:
            self.groups_box.values = ["No groups discovered yet."]
            return
            
        # Update count
        count_widget = self.get_widget(13)
        count_widget.value = str(len(self.manager.discovery.discovered_groups))
        count_widget.display()
        
        # Show sample in box (limit to avoid excessive display)
        sample = list(self.manager.discovery.discovered_groups)[:50]
        self.groups_box.values = sample
        self.groups_box.display()
    
    def start_discovery(self):
        """Start group discovery from seed entity"""
        seed = self.seed_input.value.strip()
        
        if not seed:
            self.status.add_message("Please enter a seed entity", "ERROR")
            return
            
        # Configure discovery
        depth = self.depth.value
        msg_limit = self.msg_limit.value
        
        self.status.add_message(f"Starting discovery from {seed} with depth {depth}...")
        
        def discovery_callback(discovered):
            self.status.add_message(f"Discovery complete. Found {len(discovered)} groups.")
            self.update_groups_display()
        
        AsyncRunner.run_in_thread(
            self.manager.discover_from_seed(seed, depth=depth, max_messages=msg_limit),
            callback=discovery_callback
        )
    
    def load_crawler_data(self):
        """Load group data from crawler"""
        crawler_path = Path(self.crawler_path.value)
        
        if not crawler_path.exists():
            self.status.add_message(f"Directory not found: {crawler_path}", "ERROR")
            return
            
        self.status.add_message(f"Loading groups from crawler data in {crawler_path}...")
        
        def load_callback(groups):
            self.status.add_message(f"Loaded {len(groups)} groups from crawler data.")
            self.update_groups_display()
        
        # Make sure discovery is initialized
        if not self.manager.discovery:
            AsyncRunner.run_async(self.manager.initialize())
            
        AsyncRunner.run_in_thread(
            self.manager.discovery.load_crawler_data(crawler_path),
            callback=load_callback
        )
    
    def export_groups(self):
        """Export discovered groups to a file"""
        if not self.manager.discovery or not self.manager.discovery.discovered_groups:
            self.status.add_message("No groups to export", "ERROR")
            return
            
        # Filename with timestamp
        timestamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
        filename = f"discovered_groups_{timestamp}.txt"
        
        output_path = self.manager.discovery.export_groups_to_file(str(self.manager.data_dir / filename))
        
        if output_path:
            self.status.add_message(f"Exported {len(self.manager.discovery.discovered_groups)} groups to {output_path}")
            
            # Show file path in a popup
            npyscreen.notify_confirm(
                f"Group list exported to:\n\n{output_path}",
                title="Export Complete"
            )
        else:
            self.status.add_message("Failed to export groups", "ERROR")
    
    def archive_groups(self):
        """Archive discovered groups"""
        if not self.manager.discovery or not self.manager.discovery.discovered_groups:
            self.status.add_message("No groups to archive", "ERROR")
            return
            
        # Ask how many to archive
        groups_count = len(self.manager.discovery.discovered_groups)
        
        F = npyscreen.Form(name="Archive Options")
        F.add(npyscreen.TitleText, name="Total Groups:", value=str(groups_count), editable=False)
        F.add(npyscreen.TitleSlider, name="Number to Archive:", out_of=min(groups_count, 50), value=5)
        F.add(npyscreen.TitleSlider, name="Delay Between Groups (seconds):", out_of=120, value=60, step=10)
        F.edit()
        
        to_archive = F.get_widget(1).value
        delay = F.get_widget(2).value
        
        if to_archive > 0:
            if npyscreen.notify_yes_no(
                f"Archive {to_archive} groups with {delay}s delay between each?\n\nThis will join groups and archive content.",
                title="Confirm Batch Archive"
            ):
                # Get list of groups to archive
                groups_list = list(self.manager.discovery.discovered_groups)[:to_archive]
                
                self.status.add_message(f"Starting batch archive of {to_archive} groups...")
                
                def archive_callback(results):
                    success_count = sum(1 for success in results.values() if success)
                    self.status.add_message(f"Batch archive complete: {success_count}/{len(results)} successful")
                
                AsyncRunner.run_in_thread(
                    self.manager.group_manager.batch_join_archive(groups_list, delay=delay),
                    callback=archive_callback
                )
    
    def back_to_main(self):
        """Return to the main menu"""
        self.parentApp.switchForm("MAIN")


# ── Archive Form ───────────────────────────────────────────────────────────
class ArchiveForm(npyscreen.Form):
    """Form for standard archiving operations"""
    
    def create(self):
        self.name = "SPECTRA Archiver"
        self.manager = self.parentApp.manager
        self.config = self.manager.config
        
        # Instructions
        self.add(npyscreen.FixedText, value=TITLE)
        self.add(npyscreen.FixedText, value="Channel/Group Archiver - Archive Telegram Content")
        self.add(npyscreen.FixedText, value="")
        
        # Account selection
        self.add(npyscreen.TitleSelectOne, name="Account:", max_height=6,
               values=self.get_account_names(), scroll_exit=True)
        
        # Channel input
        self.entity = self.add(npyscreen.TitleText, name="Channel/Group:", value=self.config["entity"])
        
        # Archive options
        self.add(npyscreen.FixedText, value="")
        self.add(npyscreen.FixedText, value="Archive Options:")
        self.dl_media = self.add(npyscreen.Checkbox, name="Download Media", value=self.config["download_media"])
        self.dl_avatars = self.add(npyscreen.Checkbox, name="Download Avatars", value=self.config["download_avatars"])
        self.sidecar = self.add(npyscreen.Checkbox, name="Write Sidecar Metadata", value=self.config["sidecar_metadata"])
        self.archive_topics = self.add(npyscreen.Checkbox, name="Archive Topics/Threads", value=self.config["archive_topics"])
        
        # Proxy options
        self.add(npyscreen.FixedText, value="")
        self.add(npyscreen.FixedText, value="Proxy Configuration:")
        self.use_proxy = self.add(npyscreen.Checkbox, name="Use Rotating Proxy", 
                               value=bool(self.config.proxy_conf.get("host")))
        
        # File paths
        self.add(npyscreen.FixedText, value="")
        self.add(npyscreen.TitleText, name="Media Directory:", value=self.config["media_dir"])
        self.add(npyscreen.TitleText, name="Database File:", value=self.config["db_path"])
        
        # Actions
        self.add(npyscreen.ButtonPress, name="Start Archive", when_pressed_function=self.start_archive)
        self.add(npyscreen.ButtonPress, name="Join Entity", when_pressed_function=self.join_entity)
        self.add(npyscreen.ButtonPress, name="Save Configuration", when_pressed_function=self.save_config)
        
        # Status and navigation
        self.status = self.add(StatusMessages, name="Status Messages", max_height=8)
        self.add(npyscreen.ButtonPress, name="Back to Main Menu", when_pressed_function=self.back_to_main)
        
        # Initialize
        self.status.add_message("Archive tool ready. Configure settings and start archiving.")
    
    def get_account_names(self):
        """Get list of account names for selection"""
        accounts = self.config.active_accounts
        if not accounts:
            return ["No accounts available"]
        return [acc.get("session_name", f"Account {i}") for i, acc in enumerate(accounts)]
    
    def save_config(self):
        """Save current configuration"""
        # Update config with form values
        self.config.data["entity"] = self.entity.value
        self.config.data["download_media"] = self.dl_media.value
        self.config.data["download_avatars"] = self.dl_avatars.value
        self.config.data["sidecar_metadata"] = self.sidecar.value
        self.config.data["archive_topics"] = self.archive_topics.value
        self.config.data["media_dir"] = self.get_widget(16).value
        self.config.data["db_path"] = self.get_widget(17).value
        
        # Save to file
        self.config.save()
        self.status.add_message("Configuration saved.")
    
    def start_archive(self):
        """Start the archiving process"""
        # Get selected account
        account_idx = self.get_widget(3).value[0] if self.get_widget(3).value else 0
        if account_idx >= len(self.config.active_accounts):
            self.status.add_message("No valid account selected", "ERROR")
            return
            
        selected_account = self.config.active_accounts[account_idx]
        
        # Update entity
        entity = self.entity.value.strip()
        if not entity:
            self.status.add_message("Please enter a channel/group to archive", "ERROR")
            return
            
        self.config.data["entity"] = entity
        
        # Update other options
        self.save_config()
        
        # Confirm
        if npyscreen.notify_yes_no(
            f"Start archiving {entity}?\n\nThis may take a while depending on the size of the channel/group.",
            title="Confirm Archive"
        ):
            self.status.add_message(f"Starting archive of {entity}...")
            
            def archive_callback(_):
                self.status.add_message(f"Archive of {entity} complete.")
            
            AsyncRunner.run_in_thread(
                self.manager.config.runner(self.config, selected_account),
                callback=archive_callback
            )
    
    def join_entity(self):
        """Join the specified entity"""
        entity = self.entity.value.strip()
        if not entity:
            self.status.add_message("Please enter a channel/group to join", "ERROR")
            return
            
        self.status.add_message(f"Joining {entity}...")
        
        def join_callback(entity_id):
            if entity_id:
                self.status.add_message(f"Successfully joined {entity} (ID: {entity_id})")
            else:
                self.status.add_message(f"Failed to join {entity}", "ERROR")
        
        AsyncRunner.run_in_thread(
            self.manager.group_manager.join_group(entity),
            callback=join_callback
        )
    
    def back_to_main(self):
        """Return to the main menu"""
        self.parentApp.switchForm("MAIN")


# ── Forwarding Menu Form ───────────────────────────────────────────────────
class ForwardingMenuForm(npyscreen.Form):
    """Form for SPECTRA Forwarding Utilities"""

    def create(self):
        self.name = "SPECTRA Forwarding Utilities"
        # self.manager = self.parentApp.manager # Assuming access to a manager if needed later

        # Title
        self.add(npyscreen.FixedText, value="SPECTRA Forwarding Utilities", editable=False)
        self.add(npyscreen.FixedText, value="-" * 40, editable=False) # Separator
        self.add(npyscreen.FixedText, value="", editable=False)

        # Primary Action: Channel Recovery (Banned Owner Scenario)
        self.add(npyscreen.FixedText, value="🔴 RECOVERY MODE (Owner Banned)", editable=False)
        self.add(npyscreen.ButtonPress, name="► Channel Recovery Wizard", when_pressed_function=self.channel_recovery_wizard)
        self.add(npyscreen.FixedText, value="  Recover all content when owner is banned", editable=False)
        self.add(npyscreen.FixedText, value="", editable=False)

        # Configuration Options
        self.add(npyscreen.FixedText, value="⚙️  CONFIGURATION", editable=False)
        self.add(npyscreen.ButtonPress, name="Configure Default Forwarding Destination", when_pressed_function=self.configure_default_destination)
        self.add(npyscreen.ButtonPress, name="View Default Forwarding Destination", when_pressed_function=self.view_default_destination)
        self.add(npyscreen.ButtonPress, name="Update Channel Access Database", when_pressed_function=self.update_channel_access_db)
        self.add(npyscreen.FixedText, value="", editable=False)

        # Advanced Forwarding Options
        self.add(npyscreen.FixedText, value="📤 ADVANCED FORWARDING", editable=False)
        self.add(npyscreen.ButtonPress, name="Selective Attachment Forwarding", when_pressed_function=self.selective_forwarding_form)
        self.add(npyscreen.ButtonPress, name="Total Forward Mode (Manual)", when_pressed_function=self.total_forwarding_form)
        self.add(npyscreen.ButtonPress, name="Re-post Messages in Channel", when_pressed_function=self.repost_form)

        self.add(npyscreen.FixedText, value="", editable=False) # Spacer

        # Status Messages
        self.status_widget = self.add(StatusMessages, name="Status", max_height=5, editable=False)
        self.status_widget.add_message("Forwarding utilities ready.")

        self.add(npyscreen.FixedText, value="", editable=False) # Spacer

        # Navigation
        self.add(npyscreen.ButtonPress, name="Back to Main Menu", when_pressed_function=self.back_to_main_menu)

    def back_to_main_menu(self):
        """Returns to the main application menu."""
        self.parentApp.switchForm("MAIN")

    def channel_recovery_wizard(self):
        """Switches to the Channel Recovery Wizard for banned owner scenarios."""
        self.parentApp.switchForm("CHANNEL_RECOVERY")

    def configure_default_destination(self):
        """Switches to the form to set the default forwarding destination."""
        self.parentApp.switchForm("SET_FORWARD_DEST")

    def view_default_destination(self):
        """Views the currently set default forwarding destination."""
        try:
            config = self.parentApp.manager.config
            destination_id = config.default_forwarding_destination_id

            if destination_id:
                message = f"Default Forwarding Destination ID: {destination_id}"
                self.status_widget.add_message(f"Current default forwarding destination: {destination_id}", "INFO")
            else:
                message = "Default Forwarding Destination ID is not set."
                self.status_widget.add_message("Default forwarding destination is not set.", "INFO")
            
            npyscreen.notify_confirm(message, title="Default Destination")
        except AttributeError as e:
            # This might happen if self.parentApp.manager.config is None or default_forwarding_destination_id is missing
            error_msg = f"Could not retrieve config or destination ID: {e}"
            npyscreen.notify_confirm(error_msg, title="Error")
            self.status_widget.add_message(error_msg, "ERROR")
        except Exception as e:
            error_msg = f"An unexpected error occurred: {e}"
            npyscreen.notify_confirm(error_msg, title="Error")
            self.status_widget.add_message(error_msg, "ERROR")

    def _update_finished_callback(self, db_instance, result=None):
        """Callback for when populate_account_channel_access finishes."""
        # result might contain information about success/failure or data processed
        # For now, we assume success if no exception was propagated by AsyncRunner
        self.status_widget.add_message("Channel access database update process finished.", "INFO")
        if db_instance and db_instance.conn:
            try:
                db_instance.conn.close()
                self.status_widget.add_message("Database connection closed.", "INFO")
            except Exception as e:
                self.status_widget.add_message(f"Error closing database: {e}", "ERROR")

    def update_channel_access_db(self):
        """Updates the channel access database by running populate_account_channel_access."""
        self.status_widget.add_message("Preparing to update channel access database...", "INFO")
        db_instance = None # To hold the SpectraDB instance for closing in callback
        try:
            config = self.parentApp.manager.config
            db_path = Path(config.db_path) # Ensure db_path is a Path object

            self.status_widget.add_message(f"Initializing database at {db_path}...", "INFO")
            db_instance = SpectraDB(db_path)
            # The SpectraDB class likely establishes the connection on __init__ or needs an explicit open.
            # If it's a context manager primarily, direct instantiation might not open it.
            # However, populate_account_channel_access expects an active db instance.
            # For now, assume SpectraDB constructor gets it ready or populate_account_channel_access handles it.

            self.status_widget.add_message("Starting channel access database update... This may take a while.", "INFO")
            
            # Pass the db_instance to the callback so it can close it
            callback_with_db = lambda result: self._update_finished_callback(db_instance, result)
            
            AsyncRunner.run_in_thread(
                populate_account_channel_access(db_instance, config),
                callback=callback_with_db
            )
        except Exception as e:
            self.status_widget.add_message(f"Failed to start database update: {e}", "ERROR")
            if db_instance and db_instance.conn: # Attempt to close if opened before error
                 try:
                     db_instance.conn.close()
                 except Exception as db_e:
                     self.status_widget.add_message(f"Error closing database during error handling: {db_e}", "ERROR")

    def selective_forwarding_form(self):
        """Switches to the Selective Attachment Forwarding form."""
        self.parentApp.switchForm("SELECTIVE_FORWARD")

    def total_forwarding_form(self):
        """Switches to the Total Forward Mode form."""
        self.parentApp.switchForm("TOTAL_FORWARD")

    def repost_form(self):
        """Switches to the Re-post form."""
        self.parentApp.switchForm("REPOST")


# ── Channel Recovery Wizard Form ──────────────────────────────────
class ChannelRecoveryWizardForm(npyscreen.Form):
    """Guided wizard for recovering a channel when the owner has been banned."""
    def create(self):
        self.name = "Channel Recovery Wizard"
        self.current_forwarder = None
        self.db_instance = None
        self.step = 1  # Track wizard step

        # Header
        self.add(npyscreen.FixedText, value="🔴 CHANNEL RECOVERY WIZARD", editable=False)
        self.add(npyscreen.FixedText, value="=" * 50, editable=False)
        self.add(npyscreen.FixedText, value="", editable=False)

        # Step 1: Welcome & Information
        self.add(npyscreen.FixedText, value="STEP 1: Recovery Information", editable=False)
        self.add(npyscreen.FixedText, value="-" * 50, editable=False)
        self.add(npyscreen.FixedText, value="This wizard will help you recover all messages from channels", editable=False)
        self.add(npyscreen.FixedText, value="when the channel owner has been banned. The process will:", editable=False)
        self.add(npyscreen.FixedText, value="", editable=False)
        self.add(npyscreen.FixedText, value="  • Forward all accessible channel messages to a destination", editable=False)
        self.add(npyscreen.FixedText, value="  • Handle channels with forwarding restrictions", editable=False)
        self.add(npyscreen.FixedText, value="  • Detect and skip duplicate messages", editable=False)
        self.add(npyscreen.FixedText, value="  • Use all available accounts to maximize coverage", editable=False)
        self.add(npyscreen.FixedText, value="", editable=False)

        # Step 2: Database Setup
        self.add(npyscreen.FixedText, value="STEP 2: Database Configuration", editable=False)
        self.add(npyscreen.FixedText, value="-" * 50, editable=False)
        self.add(npyscreen.FixedText, value="Before starting recovery, ensure your channel access database", editable=False)
        self.add(npyscreen.FixedText, value="is up to date. This identifies all channels accessible to your accounts.", editable=False)
        self.add(npyscreen.FixedText, value="", editable=False)
        self.db_check_button = self.add(npyscreen.ButtonPress, name="✓ Check & Update Channel Access Database",
                                        when_pressed_function=self.check_channel_database)
        self.add(npyscreen.FixedText, value="", editable=False)

        # Step 3: Recovery Configuration
        self.add(npyscreen.FixedText, value="STEP 3: Recovery Configuration", editable=False)
        self.add(npyscreen.FixedText, value="-" * 50, editable=False)

        self.destination_id_widget = self.add(npyscreen.TitleText, name="Recovery Destination:",
                                              footer="Channel ID, username, or invite link for recovery channel")
        self.add(npyscreen.FixedText, value="", editable=False)

        self.add(npyscreen.FixedText, value="Recovery Options:", editable=False)
        self.enable_dedup_widget = self.add(npyscreen.Checkbox, name="Enable Deduplication (recommended)",
                                            value=True,
                                            footer="Prevent duplicate messages during recovery")
        self.prepend_origin_widget = self.add(npyscreen.Checkbox, name="Prepend Origin Info to messages",
                                              value=True,
                                              footer="Add source channel info for tracking")
        self.forward_to_saved_widget = self.add(npyscreen.Checkbox, name="Also backup to Saved Messages",
                                                value=False,
                                                footer="Create backup in all accounts' Saved Messages")
        self.add(npyscreen.FixedText, value="", editable=False)

        # Recovery Account Selection
        self.account_id_widget = self.add(npyscreen.TitleText, name="Orchestration Account (Optional):",
                                          footer="Leave blank for automatic selection")
        self.add(npyscreen.FixedText, value="", editable=False)

        # Step 4: Start Recovery
        self.add(npyscreen.FixedText, value="STEP 4: Start Recovery", editable=False)
        self.add(npyscreen.FixedText, value="-" * 50, editable=False)
        self.add(npyscreen.ButtonPress, name="🚀 START RECOVERY", when_pressed_function=self.start_recovery)
        self.add(npyscreen.FixedText, value="", editable=False)

        # Status and Progress
        self.status_widget = self.add(StatusMessages, name="Recovery Status", max_height=6, rely=-10)
        self.status_widget.add_message("Channel recovery wizard ready. Update database first.", "INFO")

        # Navigation
        self.add(npyscreen.ButtonPress, name="Back to Forwarding Menu", when_pressed_function=self.back_to_forwarding_menu)

    def on_enter(self):
        """Called when the form is activated."""
        try:
            config = self.parentApp.manager.config
            default_dest = config.default_forwarding_destination_id
            if default_dest:
                self.destination_id_widget.value = default_dest
                self.destination_id_widget.display()
                self.status_widget.add_message(f"Loaded default destination: {default_dest}", "INFO")
        except Exception as e:
            self.status_widget.add_message(f"Error loading config: {e}", "WARNING")

    def check_channel_database(self):
        """Check and update the channel access database."""
        if self.current_forwarder or self.db_instance:
            self.status_widget.add_message("A task is already in progress. Please wait.", "WARNING")
            return

        self.status_widget.add_message("Checking channel access database...", "INFO")
        try:
            config = self.parentApp.manager.config
            db_path = Path(config.db_path)
            self.db_instance = SpectraDB(db_path)
            self.status_widget.add_message("Database connected. Starting update process...", "INFO")
            self.status_widget.add_message("(This may take a while - check terminal for progress)", "INFO")

            AsyncRunner.run_in_thread(
                populate_account_channel_access(self.db_instance, config),
                callback=self._db_update_finished_callback
            )
        except Exception as e:
            self.status_widget.add_message(f"Error updating database: {e}", "ERROR")
            self.db_instance = None

    def _db_update_finished_callback(self, result=None):
        """Callback when database update completes."""
        self.status_widget.add_message("✓ Channel database update completed successfully!", "INFO")
        self.status_widget.add_message("You can now proceed with channel recovery.", "INFO")
        if self.db_instance:
            try:
                self.db_instance.conn.close()
            except:
                pass
            self.db_instance = None

    def _recovery_finished_callback(self, result=None):
        """Callback when recovery process completes."""
        self.status_widget.add_message("=" * 50, "INFO")
        self.status_widget.add_message("✓ RECOVERY PROCESS COMPLETED", "INFO")
        self.status_widget.add_message("Check the recovery destination for recovered messages.", "INFO")

        if self.current_forwarder:
            try:
                AsyncRunner.run_async(self.current_forwarder.close())
            except:
                pass

        if self.db_instance and self.db_instance.conn:
            try:
                self.db_instance.conn.close()
            except:
                pass

        self.current_forwarder = None
        self.db_instance = None

    def start_recovery(self):
        """Start the channel recovery process."""
        if self.current_forwarder or self.db_instance:
            self.status_widget.add_message("A recovery task is already in progress. Please wait.", "WARNING")
            return

        destination_id = self.destination_id_widget.value
        if not destination_id:
            self.status_widget.add_message("Recovery destination is required!", "ERROR")
            npyscreen.notify_confirm("Please enter a recovery destination channel.", title="Missing Configuration")
            return

        account_identifier = self.account_id_widget.value or None
        enable_dedup = self.enable_dedup_widget.value
        prepend_origin = self.prepend_origin_widget.value
        forward_to_saved = self.forward_to_saved_widget.value

        try:
            config = self.parentApp.manager.config
            db_path = Path(config.db_path)

            self.status_widget.add_message("=" * 50, "INFO")
            self.status_widget.add_message("🚀 STARTING CHANNEL RECOVERY", "INFO")
            self.status_widget.add_message(f"Destination: {destination_id}", "INFO")
            self.status_widget.add_message(f"Deduplication: {'ENABLED' if enable_dedup else 'DISABLED'}", "INFO")
            self.status_widget.add_message(f"Origin Info: {'ENABLED' if prepend_origin else 'DISABLED'}", "INFO")
            self.status_widget.add_message("", "INFO")

            self.db_instance = SpectraDB(db_path)
            self.current_forwarder = AttachmentForwarder(
                config=config,
                db=self.db_instance,
                forward_to_all_saved_messages=forward_to_saved,
                prepend_origin_info=prepend_origin,
                enable_deduplication=enable_dedup
            )

            self.status_widget.add_message("Initializing recovery process...", "INFO")
            AsyncRunner.run_in_thread(
                self.current_forwarder.forward_all_accessible_channels(
                    destination_id=destination_id,
                    orchestration_account_identifier=account_identifier
                ),
                callback=self._recovery_finished_callback
            )

        except Exception as e:
            self.status_widget.add_message(f"Failed to start recovery: {e}", "ERROR")
            if self.current_forwarder:
                try:
                    AsyncRunner.run_async(self.current_forwarder.close())
                except:
                    pass
            if self.db_instance and self.db_instance.conn:
                try:
                    self.db_instance.conn.close()
                except:
                    pass
            self.current_forwarder = None
            self.db_instance = None

    def back_to_forwarding_menu(self):
        """Returns to the Forwarding Menu."""
        if self.current_forwarder or self.db_instance:
            npyscreen.notify_confirm(
                "A recovery task is in progress. Are you sure you want to go back?\n"
                "The task will continue, but you won't see live updates here.",
                title="Task in Progress"
            )
        self.parentApp.switchForm("FORWARDING")


# ── Re-post Form ──────────────────────────────────────────────────
class RepostForm(npyscreen.Form):
    """Form for re-posting messages in a channel."""
    def create(self):
        self.name = "Re-post Messages in Channel"
        self.current_forwarder = None

        self.add(npyscreen.FixedText, value="Re-post Messages in Channel", editable=False)
        self.add(npyscreen.FixedText, value="-" * 40, editable=False)
        self.add(npyscreen.FixedText, value="This will re-post all messages in a channel and delete the originals.", editable=False)
        self.add(npyscreen.FixedText, value="This is a destructive operation. Use with caution.", editable=False)
        self.add(npyscreen.FixedText, value="", editable=False)

        self.channel_id_widget = self.add(npyscreen.TitleText, name="Channel ID/Username:")
        self.account_id_widget = self.add(npyscreen.TitleText, name="Account (Optional):",
                                          footer="Leave blank for default/any.")

        self.add(npyscreen.FixedText, value="", editable=False)

        self.add(npyscreen.ButtonPress, name="Start Re-posting", when_pressed_function=self.start_reposting)

        self.status_widget = self.add(StatusMessages, name="Re-posting Status", max_height=6, rely=-10)

        self.add(npyscreen.ButtonPress, name="Back to Forwarding Menu", when_pressed_function=self.back_to_forwarding_menu)

    def _reposting_finished_callback(self, forwarder_instance, result=None):
        """Callback for when the re-posting process completes."""
        self.status_widget.add_message("Re-posting process finished.", "INFO")
        if forwarder_instance:
            self.status_widget.add_message("Closing client session...", "INFO")
            try:
                AsyncRunner.run_async(forwarder_instance.close())
                self.status_widget.add_message("Client session closed.", "INFO")
            except Exception as e:
                self.status_widget.add_message(f"Error closing session: {e}", "ERROR")
        self.current_forwarder = None

    def start_reposting(self):
        """Initiates the re-posting process."""
        if self.current_forwarder:
            self.status_widget.add_message("A task is already in progress. Please wait.", "WARNING")
            return

        channel_id = self.channel_id_widget.value
        account_identifier = self.account_id_widget.value or None

        if not channel_id:
            self.status_widget.add_message("Channel ID/Username is required.", "ERROR")
            return

        if not npyscreen.notify_yes_no(
            f"Are you sure you want to re-post all messages in {channel_id} and delete the originals?\n\nTHIS CANNOT BE UNDONE.",
            title="Confirm Destructive Operation"
        ):
            self.status_widget.add_message("Re-posting cancelled.", "INFO")
            return

        try:
            config = self.parentApp.manager.config

            self.current_forwarder = AttachmentForwarder(config=config, db=None)

            self.status_widget.add_message(f"Starting re-posting in channel: {channel_id}...", "INFO")

            AsyncRunner.run_in_thread(
                self.current_forwarder.repost_messages_in_channel(
                    channel_id=channel_id,
                    account_identifier=account_identifier
                ),
                callback=lambda res: self._reposting_finished_callback(self.current_forwarder, res)
            )
        except Exception as e:
            self.status_widget.add_message(f"Failed to start re-posting: {e}", "ERROR")
            if self.current_forwarder:
                try: AsyncRunner.run_async(self.current_forwarder.close())
                except: pass
            self.current_forwarder = None

    def back_to_forwarding_menu(self):
        """Returns to the Forwarding Menu."""
        if self.current_forwarder:
            npyscreen.notify_confirm(
                "A re-posting task is in progress. Are you sure you want to go back?",
                title="Task in Progress"
            )
        self.parentApp.switchForm("FORWARDING")


# ── Set Forward Destination Form ───────────────────────────────────────────
class SetForwardDestForm(npyscreen.ActionFormMinimal):
    """Form for setting the default forwarding destination ID."""
    def create(self):
        self.name = "Set Default Forwarding Destination"
        self.destination_id_widget = self.add(npyscreen.TitleText, name="Destination ID:")

    def on_ok(self):
        destination_id = self.destination_id_widget.value
        forwarding_form = self.parentApp.getForm("FORWARDING")

        if not destination_id:
            if forwarding_form:
                forwarding_form.status_widget.add_message("Destination ID cannot be empty.", "ERROR")
            self.parentApp.switchForm("FORWARDING")
            return

        try:
            config = self.parentApp.manager.config
            config.default_forwarding_destination_id = destination_id # Use the property setter
            config.save()
            if forwarding_form:
                forwarding_form.status_widget.add_message(f"Default forwarding destination set to: {destination_id}", "INFO")
        except Exception as e:
            if forwarding_form:
                forwarding_form.status_widget.add_message(f"Error saving destination: {e}", "ERROR")
        
        self.parentApp.switchForm("FORWARDING")

    def on_cancel(self):
        forwarding_form = self.parentApp.getForm("FORWARDING")
        if forwarding_form:
            forwarding_form.status_widget.add_message("Configuration of default destination cancelled.", "INFO")
        self.parentApp.switchForm("FORWARDING")


# ── Total Forwarding Form ──────────────────────────────────────────────────
class TotalForwardForm(npyscreen.Form):
    """Form for total forwarding of all accessible channel messages."""
    def create(self):
        self.name = "Total Forward Mode"
        self.current_forwarder = None
        self.db_instance = None # To store the SpectraDB instance

        self.add(npyscreen.FixedText, value="Total Forward Mode", editable=False)
        self.add(npyscreen.FixedText, value="-" * 40, editable=False)

        self.destination_id_widget = self.add(npyscreen.TitleText, name="Dest. ID/Username:")
        self.account_id_widget = self.add(npyscreen.TitleText, name="Orchestration Account (Optional):",
                                          footer="Leave blank for default/any.")
        
        self.add(npyscreen.FixedText, value="", editable=False) # Spacer
        self.to_all_saved_widget = self.add(npyscreen.Checkbox, name="Forward to all Saved Messages accounts", value=False)
        self.prepend_info_widget = self.add(npyscreen.Checkbox, name="Prepend Origin Info to messages", value=True)
        self.add(npyscreen.FixedText, value="", editable=False) # Spacer

        self.add(npyscreen.ButtonPress, name="Start Total Forwarding", when_pressed_function=self.start_total_forwarding)
        
        self.status_widget = self.add(StatusMessages, name="Forwarding Status", max_height=6, rely=-10)
        
        self.add(npyscreen.ButtonPress, name="Back to Forwarding Menu", when_pressed_function=self.back_to_forwarding_menu)

    def on_enter(self):
        """Called when the form is activated."""
        try:
            config = self.parentApp.manager.config
            default_dest = config.default_forwarding_destination_id
            if default_dest:
                self.destination_id_widget.value = default_dest
                self.destination_id_widget.display()
        except Exception as e:
            self.status_widget.add_message(f"Error loading default destination: {e}", "ERROR")
        self.status_widget.add_message("Total forwarding form ready. Ensure DB is updated.", "INFO")

    def _total_forwarding_finished_callback(self, forwarder_instance, db_instance, result=None):
        """Callback for when the total forwarding process completes."""
        self.status_widget.add_message("Total forwarding process finished.", "INFO")
        if forwarder_instance:
            self.status_widget.add_message("Closing forwarding client session...", "INFO")
            try:
                AsyncRunner.run_async(forwarder_instance.close())
                self.status_widget.add_message("Forwarding client session closed.", "INFO")
            except Exception as e:
                self.status_widget.add_message(f"Error closing forwarder session: {e}", "ERROR")
        
        if db_instance and db_instance.conn:
            self.status_widget.add_message("Closing database connection...", "INFO")
            try:
                db_instance.conn.close()
                self.status_widget.add_message("Database connection closed.", "INFO")
            except Exception as e:
                self.status_widget.add_message(f"Error closing database: {e}", "ERROR")
        
        self.current_forwarder = None
        self.db_instance = None

    def start_total_forwarding(self):
        """Initiates the total forwarding process."""
        if self.current_forwarder or self.db_instance:
            self.status_widget.add_message("A forwarding or DB task is already in progress. Please wait.", "WARNING")
            return

        destination_id = self.destination_id_widget.value
        account_identifier = self.account_id_widget.value or None
        to_all_saved = self.to_all_saved_widget.value
        prepend_info = self.prepend_info_widget.value

        if not destination_id and not to_all_saved:
            self.status_widget.add_message("Destination ID/Username is required if not forwarding to all Saved Messages.", "ERROR")
            return
        
        if to_all_saved:
            self.status_widget.add_message("Forwarding to all Saved Messages accounts.", "INFO")
            destination_id = None # Forwarder should handle this

        try:
            config = self.parentApp.manager.config
            db_path = Path(config.db_path)

            self.status_widget.add_message(f"Initializing database at {db_path}...", "INFO")
            self.db_instance = SpectraDB(db_path)
            # Assuming SpectraDB connects on init or populate_account_channel_access handles it.

            self.current_forwarder = AttachmentForwarder(
                config=config,
                db=self.db_instance, # Pass the initialized SpectraDB instance
                forward_to_all_saved_messages=to_all_saved,
                prepend_origin_info=prepend_info
            )
            
            display_dest = "all Saved Messages" if to_all_saved else destination_id
            self.status_widget.add_message(f"Starting total forwarding to {display_dest} from all accessible channels...", "INFO")

            AsyncRunner.run_in_thread(
                self.current_forwarder.forward_all_accessible_channels(
                    destination_id=destination_id,
                    orchestration_account_identifier=account_identifier
                ),
                callback=lambda res: self._total_forwarding_finished_callback(self.current_forwarder, self.db_instance, res)
            )
        except Exception as e:
            self.status_widget.add_message(f"Failed to start total forwarding: {e}", "ERROR")
            if self.current_forwarder:
                try: AsyncRunner.run_async(self.current_forwarder.close())
                except: pass # best effort
            if self.db_instance and self.db_instance.conn:
                try: self.db_instance.conn.close()
                except: pass # best effort
            self.current_forwarder = None
            self.db_instance = None

    def back_to_forwarding_menu(self):
        """Returns to the Forwarding Menu."""
        if self.current_forwarder or self.db_instance:
            npyscreen.notify_confirm(
                "A forwarding or DB task is in progress. Are you sure you want to go back?\n"
                "The task will continue, but you won't see live updates here and resources might not be cleaned up properly if the main app exits.",
                title="Task in Progress"
            )
        self.parentApp.switchForm("FORWARDING")


# ── Selective Forwarding Form ──────────────────────────────────────────────
class SelectiveForwardForm(npyscreen.Form):
    """Form for selective message forwarding with attachments."""
    def create(self):
        self.name = "Selective Message Forwarding"
        self.current_forwarder = None # To store the active forwarder instance

        self.add(npyscreen.FixedText, value="Selective Message Forwarding", editable=False)
        self.add(npyscreen.FixedText, value="-" * 40, editable=False)

        self.origin_id_widget = self.add(npyscreen.TitleText, name="Origin ID/Username:")
        self.destination_id_widget = self.add(npyscreen.TitleText, name="Dest. ID/Username:")
        self.account_id_widget = self.add(npyscreen.TitleText, name="Account (Optional):", 
                                          footer="Leave blank for default/any.")
        
        self.add(npyscreen.FixedText, value="", editable=False) # Spacer
        self.to_all_saved_widget = self.add(npyscreen.Checkbox, name="Forward to all Saved Messages accounts", value=False)
        self.prepend_info_widget = self.add(npyscreen.Checkbox, name="Prepend Origin Info to messages", value=True)
        self.add(npyscreen.FixedText, value="", editable=False) # Spacer

        self.add(npyscreen.ButtonPress, name="Start Selective Forwarding", when_pressed_function=self.start_forwarding)
        
        # Adjusted rely based on typical form layouts to appear above the final "Back" button.
        # This might need further tweaking depending on actual widget heights.
        self.status_widget = self.add(StatusMessages, name="Forwarding Status", max_height=6, rely=-10) 
        
        self.add(npyscreen.ButtonPress, name="Back to Forwarding Menu", when_pressed_function=self.back_to_forwarding_menu)

    def on_enter(self):
        """Called when the form is activated."""
        try:
            config = self.parentApp.manager.config
            default_dest = config.default_forwarding_destination_id
            if default_dest:
                self.destination_id_widget.value = default_dest
                self.destination_id_widget.display()
        except Exception as e:
            self.status_widget.add_message(f"Error loading default destination: {e}", "ERROR")
        self.status_widget.add_message("Selective forwarding form ready.", "INFO")

    def _forwarding_finished_callback(self, forwarder_instance, result=None):
        """Callback for when the forwarding process completes."""
        self.status_widget.add_message("Selective forwarding process finished.", "INFO")
        if forwarder_instance:
            self.status_widget.add_message("Closing forwarding client session...", "INFO")
            try:
                AsyncRunner.run_async(forwarder_instance.close())
                self.status_widget.add_message("Forwarding client session closed.", "INFO")
            except Exception as e:
                self.status_widget.add_message(f"Error closing forwarder session: {e}", "ERROR")
        self.current_forwarder = None # Clear the stored forwarder

    def start_forwarding(self):
        """Initiates the selective forwarding process."""
        if self.current_forwarder:
            self.status_widget.add_message("A forwarding task is already in progress. Please wait.", "WARNING")
            return

        origin_id = self.origin_id_widget.value
        destination_id = self.destination_id_widget.value
        account_identifier = self.account_id_widget.value or None # Ensure None if empty
        to_all_saved = self.to_all_saved_widget.value
        prepend_info = self.prepend_info_widget.value

        if not origin_id:
            self.status_widget.add_message("Origin ID/Username is required.", "ERROR")
            return
        if not destination_id and not to_all_saved:
            self.status_widget.add_message("Destination ID/Username is required if not forwarding to all Saved Messages.", "ERROR")
            return
        if to_all_saved: # If to_all_saved is true, destination_id might be ignored by forwarder logic
            self.status_widget.add_message("Forwarding to all Saved Messages accounts.", "INFO")
            destination_id = None # Explicitly set to None or a special value if your forwarder expects one

        try:
            config = self.parentApp.manager.config
            
            # Initialize AttachmentForwarder, db is None as per plan
            self.current_forwarder = AttachmentForwarder(
                config=config, 
                db=None,  # Passing db=None
                forward_to_all_saved_messages=to_all_saved,
                prepend_origin_info=prepend_info
            )

            display_dest = "all Saved Messages" if to_all_saved else destination_id
            self.status_widget.add_message(f"Starting selective forwarding: {origin_id} -> {display_dest}...", "INFO")

            AsyncRunner.run_in_thread(
                self.current_forwarder.forward_messages(
                    origin_entity=origin_id, 
                    destination_entity=destination_id, 
                    account_identifier=account_identifier
                ),
                callback=lambda res: self._forwarding_finished_callback(self.current_forwarder, res)
            )
        except Exception as e:
            self.status_widget.add_message(f"Failed to start forwarding: {e}", "ERROR")
            if self.current_forwarder: # Attempt cleanup if forwarder was initialized
                try:
                    AsyncRunner.run_async(self.current_forwarder.close())
                except Exception as ce:
                    self.status_widget.add_message(f"Error during forwarder cleanup: {ce}", "ERROR")
                self.current_forwarder = None


    def back_to_forwarding_menu(self):
        """Returns to the Forwarding Menu."""
        if self.current_forwarder:
            npyscreen.notify_confirm(
                "A forwarding task is in progress. Are you sure you want to go back?\n"
                "The task will continue in the background, but you won't see live updates here.",
                title="Task in Progress"
            )
        self.parentApp.switchForm("FORWARDING")


# ── Download Users Form ────────────────────────────────────────────────────
class DownloadUsersForm(npyscreen.Form):
    """Form for downloading users from a server"""

    def create(self):
        self.name = "SPECTRA User Downloader"
        self.manager = self.parentApp.manager
        self.config = self.manager.config

        self.add(npyscreen.FixedText, value=TITLE)
        self.add(npyscreen.FixedText, value="Download All Users from a Server")
        self.add(npyscreen.FixedText, value="")

        self.server_id = self.add(npyscreen.TitleText, name="Server ID:")
        self.output_file = self.add(npyscreen.TitleText, name="Output File:", value="users.csv")
        self.output_format = self.add(npyscreen.TitleSelectOne, name="Output Format:", values=["csv", "json", "sqlite"], max_height=3, value=[0])
        self.rotate_ip = self.add(npyscreen.Checkbox, name="Rotate IP on Flood Wait", value=False)
        self.rate_limit_delay = self.add(npyscreen.TitleSlider, out_of=10, name="Rate Limit Delay (s)", value=1)

        self.add(npyscreen.ButtonPress, name="Start Download", when_pressed_function=self.start_download)
        self.status = self.add(StatusMessages, name="Status Messages", max_height=8)
        self.add(npyscreen.ButtonPress, name="Back to Main Menu", when_pressed_function=self.back_to_main)

        self.status.add_message("User Downloader ready. Enter a server ID to begin.")

    def start_download(self):
        """Start the user download process"""
        server_id = self.server_id.value.strip()
        output_file = self.output_file.value.strip()
        output_format = self.output_format.values[self.output_format.value[0]]
        rotate_ip = self.rotate_ip.value
        rate_limit_delay = self.rate_limit_delay.value

        if not server_id:
            self.status.add_message("Please enter a server ID", "ERROR")
            return

        if not output_file:
            self.status.add_message("Please enter an output file path", "ERROR")
            return

        if npyscreen.notify_yes_no(
            f"Start downloading users from server {server_id} to {output_file} in {output_format} format?",
            title="Confirm Download"
        ):
            self.status.add_message(f"Starting user download from server {server_id}...")

            def download_callback(_):
                self.status.add_message(f"User download from server {server_id} complete.")

            from telethon import TelegramClient
            account = self.config.auto_select_account()
            if not account:
                self.status.add_message("No account available for this operation.", "ERROR")
                return

            client = TelegramClient(account['session_name'], account['api_id'], account['api_hash'])

            async def downloader():
                await client.connect()
                await get_server_users(client, int(server_id), output_file, output_format, rotate_ip, rate_limit_delay)
                await client.disconnect()

            AsyncRunner.run_in_thread(
                downloader(),
                callback=download_callback
            )

    def back_to_main(self):
        """Return to the main menu"""
        self.parentApp.switchForm("MAIN")


# ── Group Mirror Form ──────────────────────────────────────────────────────
class GroupMirrorForm(npyscreen.Form):
    """Form for mirroring a group to another group."""

    def create(self):
        self.name = "SPECTRA Group Mirroring"
        self.manager = self.parentApp.manager
        self.config = self.manager.config
        self.db = self.parentApp.db_instance

        self.add(npyscreen.FixedText, value=TITLE)
        self.add(npyscreen.FixedText, value="Mirror a Group to Another Group")
        self.add(npyscreen.FixedText, value="Uses two separate accounts for source and destination.")
        self.add(npyscreen.FixedText, value="")

        self.source_group = self.add(npyscreen.TitleText, name="Source Group ID/Username:")
        self.dest_group = self.add(npyscreen.TitleText, name="Destination Group ID/Username:")
        self.source_account = self.add(npyscreen.TitleText, name="Source Account Session/Phone:")
        self.dest_account = self.add(npyscreen.TitleText, name="Destination Account Session/Phone:")

        self.add(npyscreen.ButtonPress, name="Start Mirroring", when_pressed_function=self.start_mirroring)
        self.status = self.add(StatusMessages, name="Status Messages", max_height=8)
        self.add(npyscreen.ButtonPress, name="Back to Main Menu", when_pressed_function=self.back_to_main)

        self.status.add_message("Group Mirroring ready. Enter details to begin.")

    def start_mirroring(self):
        source = self.source_group.value.strip()
        dest = self.dest_group.value.strip()
        source_acc = self.source_account.value.strip()
        dest_acc = self.dest_account.value.strip()

        if not all([source, dest, source_acc, dest_acc]):
            self.status.add_message("All fields are required.", "ERROR")
            return

        if source_acc == dest_acc:
            self.status.add_message("Source and Destination accounts must be different.", "ERROR")
            return

        if npyscreen.notify_yes_no(
            f"Start mirroring from '{source}' to '{dest}'?\n\nThis will copy all topics and messages.",
            title="Confirm Group Mirror"
        ):
            self.status.add_message("Initializing mirror process...")

            async def mirror_task():
                mirror_manager = GroupMirrorManager(
                    config=self.config,
                    db=self.db,
                    source_account_id=source_acc,
                    dest_account_id=dest_acc
                )
                try:
                    await mirror_manager.mirror_group(source, dest)
                finally:
                    await mirror_manager.close()

            def mirror_callback(_):
                self.status.add_message("Mirroring process completed.")

            AsyncRunner.run_in_thread(mirror_task(), callback=mirror_callback)

    def back_to_main(self):
        self.parentApp.switchForm("MAIN")


# ── OSINT Menu Form ────────────────────────────────────────────────────────
class OSINTMenuForm(npyscreen.Form):
    """Form for OSINT operations"""
    def create(self):
        self.name = "SPECTRA OSINT Utilities"
        self.add(npyscreen.FixedText, value="OSINT Utilities - Track Users and Analyze Networks")
        self.add(npyscreen.FixedText, value="-" * 40)

        self.add(npyscreen.ButtonPress, name="Add Target", when_pressed_function=self.add_target_form)
        self.add(npyscreen.ButtonPress, name="List/Remove Targets", when_pressed_function=self.list_targets_form)
        self.add(npyscreen.ButtonPress, name="Scan Channel for Interactions", when_pressed_function=self.scan_channel_form)
        self.add(npyscreen.ButtonPress, name="Show Interaction Network", when_pressed_function=self.show_network_form)

        self.add(npyscreen.FixedText, value="")
        self.status_widget = self.add(StatusMessages, name="Status", max_height=5, editable=False)
        self.status_widget.add_message("OSINT utilities ready.")
        self.add(npyscreen.FixedText, value="")
        self.add(npyscreen.ButtonPress, name="Back to Main Menu", when_pressed_function=self.back_to_main_menu)

    def add_target_form(self):
        self.parentApp.switchForm("OSINT_ADD_TARGET")

    def list_targets_form(self):
        self.parentApp.switchForm("OSINT_LIST_TARGETS")

    def scan_channel_form(self):
        self.parentApp.switchForm("OSINT_SCAN_CHANNEL")

    def show_network_form(self):
        self.parentApp.switchForm("OSINT_SHOW_NETWORK")

    def back_to_main_menu(self):
        self.parentApp.switchForm("MAIN")

# ── OSINT Sub-Forms ────────────────────────────────────────────────────────
class OSINTAddTargetForm(npyscreen.ActionFormV2):
    def create(self):
        self.name = "Add OSINT Target"
        self.username = self.add(npyscreen.TitleText, name="Username:")
        self.notes = self.add(npyscreen.TitleText, name="Notes:")

    def on_ok(self):
        username = self.username.value
        if not username:
            npyscreen.notify_confirm("Username cannot be empty.", "Error")
            return

        async def add_target_task():
            collector = self.parentApp.get_intelligence_collector()
            await collector.add_target(username, self.notes.value)

        AsyncRunner.run_in_thread(add_target_task())
        npyscreen.notify_confirm(f"Task to add '{username}' has been started.", "Info")
        self.parentApp.switchForm("OSINT_MENU")

    def on_cancel(self):
        self.parentApp.switchForm("OSINT_MENU")

class OSINTListTargetsForm(npyscreen.Form):
    def create(self):
        self.name = "OSINT Targets"
        self.target_list = self.add(npyscreen.TitleMultiSelect, name="Targets", max_height=-5)
        self.add(npyscreen.ButtonPress, name="Remove Selected", when_pressed_function=self.remove_target)
        self.add(npyscreen.ButtonPress, name="Back", when_pressed_function=self.back_to_menu)

    def beforeEditing(self):
        self.update_list()

    def update_list(self):
        async def list_targets_task():
            collector = self.parentApp.get_intelligence_collector()
            return await collector.list_targets()

        targets = AsyncRunner.run_async(list_targets_task())
        self.target_list.values = [f"{t['username']} (ID: {t['user_id']})" for t in targets]

    def remove_target(self):
        selected = self.target_list.get_selected_objects()
        if not selected:
            npyscreen.notify_confirm("No target selected.", "Warning")
            return

        username = selected[0].split(" ")[0]
        if npyscreen.notify_yes_no(f"Are you sure you want to remove {username}?", "Confirm"):
            async def remove_target_task():
                collector = self.parentApp.get_intelligence_collector()
                await collector.remove_target(username)

            AsyncRunner.run_in_thread(remove_target_task(), callback=lambda r: self.update_list())
            npyscreen.notify_confirm(f"Task to remove '{username}' has been started.", "Info")


    def back_to_menu(self):
        self.parentApp.switchForm("OSINT_MENU")

class OSINTScanChannelForm(npyscreen.ActionFormV2):
    def create(self):
        self.name = "Scan Channel for Interactions"
        self.channel = self.add(npyscreen.TitleText, name="Channel ID/Username:")
        self.username = self.add(npyscreen.TitleText, name="Target Username:")

    def on_ok(self):
        channel = self.channel.value
        username = self.username.value
        if not channel or not username:
            npyscreen.notify_confirm("Channel and Username are required.", "Error")
            return

        async def scan_task():
            collector = self.parentApp.get_intelligence_collector()
            await collector.scan_channel(channel, username)

        AsyncRunner.run_in_thread(scan_task())
        npyscreen.notify_confirm(f"Scan for '{username}' in '{channel}' started.", "Info")
        self.parentApp.switchForm("OSINT_MENU")

    def on_cancel(self):
        self.parentApp.switchForm("OSINT_MENU")

class OSINTShowNetworkForm(npyscreen.Form):
    def create(self):
        self.name = "Interaction Network"
        self.username = self.add(npyscreen.TitleText, name="Target Username:")
        self.add(npyscreen.ButtonPress, name="Show Network", when_pressed_function=self.show_network)
        self.network_display = self.add(npyscreen.Pager, name="Network")
        self.add(npyscreen.ButtonPress, name="Back", when_pressed_function=self.back_to_menu)

    def show_network(self):
        username = self.username.value
        if not username:
            npyscreen.notify_confirm("Username is required.", "Error")
            return

        async def get_network_task():
            collector = self.parentApp.get_intelligence_collector()
            return await collector.get_network(username)

        def update_display(network):
            if network:
                lines = [f"{i['source_user_id']} -> {i['target_user_id']} ({i['interaction_type']})" for i in network]
                self.network_display.values = lines
            else:
                self.network_display.values = ["No network found."]
            self.network_display.display()

        AsyncRunner.run_in_thread(get_network_task(), callback=update_display)

    def back_to_menu(self):
        self.parentApp.switchForm("OSINT_MENU")


# ── Forwarding & Deduplication Settings Form ────────────────────────────────
class ForwardingSettingsForm(npyscreen.ActionFormV2):
    """Form for configuring forwarding and deduplication settings."""

    def create(self):
        self.name = "Forwarding & Deduplication Settings"
        self.config = self.parentApp.manager.config

        self.add(npyscreen.FixedText, value="Forwarding Settings", editable=False)
        self.always_prepend_info = self.add(npyscreen.Checkbox, name="Always Prepend Origin Info", value=self.config.data.get("forwarding", {}).get("always_prepend_origin_info", False))

        self.add(npyscreen.FixedText, value="", editable=False)
        self.add(npyscreen.FixedText, value="Deduplication Settings", editable=False)
        self.enable_near_duplicates = self.add(npyscreen.Checkbox, name="Enable Near-Duplicate Detection", value=self.config.data.get("deduplication", {}).get("enable_near_duplicates", False))

        self.fuzzy_threshold = self.add(npyscreen.TitleSlider, name="Fuzzy Hash Similarity Threshold:", out_of=100, step=1, value=self.config.data.get("deduplication", {}).get("fuzzy_hash_similarity_threshold", 90))
        self.phash_threshold = self.add(npyscreen.TitleSlider, name="Perceptual Hash Distance Threshold:", out_of=20, step=1, value=self.config.data.get("deduplication", {}).get("perceptual_hash_distance_threshold", 5))

    def on_ok(self):
        # Save settings to config
        self.config.data["forwarding"]["always_prepend_origin_info"] = self.always_prepend_info.value
        self.config.data["deduplication"]["enable_near_duplicates"] = self.enable_near_duplicates.value
        self.config.data["deduplication"]["fuzzy_hash_similarity_threshold"] = self.fuzzy_threshold.value
        self.config.data["deduplication"]["perceptual_hash_distance_threshold"] = self.phash_threshold.value
        self.config.save()
        npyscreen.notify_confirm("Settings saved.", title="Success")
        self.parentApp.switchForm("MAIN")

    def on_cancel(self):
        self.parentApp.switchForm("MAIN")


# ── Main Menu Form ─────────────────────────────────────────────────────────
class MainMenuForm(npyscreen.Form):
    """Main menu form for the application"""
    
    def create(self):
        self.name = "SPECTRA - Telegram Network Discovery & Archiving"
        
        # Title and description
        self.add(npyscreen.FixedText, value=TITLE)
        self.add(npyscreen.FixedText, value="Integrated Telegram Intelligence Platform")
        self.add(npyscreen.FixedText, value="")
        
        # Options - merged from both versions, best features combined
        self.add(npyscreen.ButtonPress, name="1. Archive Channel/Group", when_pressed_function=self.archive_form)
        self.add(npyscreen.ButtonPress, name="2. Discover Groups", when_pressed_function=self.discovery_form)
        self.add(npyscreen.ButtonPress, name="3. Network Analysis", when_pressed_function=self.graph_form)
        self.add(npyscreen.ButtonPress, name="4. Forwarding Utilities", when_pressed_function=self.forwarding_form)
        self.add(npyscreen.ButtonPress, name="5. OSINT Utilities", when_pressed_function=self.osint_form)
        self.add(npyscreen.ButtonPress, name="6. Group Mirroring", when_pressed_function=self.mirror_form)
        self.add(npyscreen.ButtonPress, name="7. Account Management", when_pressed_function=self.account_form)
        self.add(npyscreen.ButtonPress, name="8. Settings (VPS Config)", when_pressed_function=self.vps_config_form)
        self.add(npyscreen.ButtonPress, name="9. Forwarding & Deduplication Settings", when_pressed_function=self.forwarding_settings_form)
        self.add(npyscreen.ButtonPress, name="10. Download Users", when_pressed_function=self.download_users_form)
        self.add(npyscreen.ButtonPress, name="11. Help & About", when_pressed_function=self.help_form)
        self.add(npyscreen.ButtonPress, name="12. Exit", when_pressed_function=self.exit_app)
        
        # Status
        self.add(npyscreen.FixedText, value="")
        self.status = self.add(npyscreen.TitleFixedText, name="Status:", 
                            value="Initializing components...")
        
        # Initialize the manager
        self.parentApp.setup_manager()
        self.status.value = f"Ready. {len(self.parentApp.manager.config.active_accounts)} accounts available."
        self.status.display()
    
    def osint_form(self):
        """Switch to OSINT form"""
        self.parentApp.switchForm("OSINT_MENU")

    def archive_form(self):
        """Switch to archive form"""
        self.parentApp.switchForm("ARCHIVE")
    
    def discovery_form(self):
        """Switch to discovery form"""
        self.parentApp.switchForm("DISCOVERY")

    def forwarding_form(self):
        """Switch to forwarding utilities form"""
        self.parentApp.switchForm("FORWARDING")
    
    def mirror_form(self):
        """Switch to group mirror form"""
        self.parentApp.switchForm("GROUP_MIRROR")

    def graph_form(self):
        """Switch to graph explorer form"""
        self.parentApp.switchForm("GRAPH")
    
    def account_form(self):
        """Switch to account management form (not implemented yet)"""
        npyscreen.notify_confirm(
            "Account Management not yet implemented in this version.",
            title="Coming Soon"
        )
    
    def settings_form(self):
        """Switch to settings form (not implemented yet)"""
        npyscreen.notify_confirm(
            "Settings Management not yet implemented in this version.",
            title="Coming Soon"
        )

    def vps_config_form(self):
        """Switch to VPS Configuration form"""
        self.parentApp.switchForm("VPS_CONFIG")

    def download_users_form(self):
        """Switch to download users form"""
        self.parentApp.switchForm("DOWNLOAD_USERS")

    def forwarding_settings_form(self):
        """Switch to forwarding settings form"""
        self.parentApp.switchForm("FORWARDING_SETTINGS")
    
    def help_form(self):
        """Show help and about information"""
        about_text = """
SPECTRA Telegram Intelligence Platform v3.0
------------------------------------------

An integrated solution for:
- Archiving Telegram channels and groups
- Discovering new groups from seeds
- Analyzing network relationships
- Batch operations with multi-account support

Features:
• Multi-account support with rotation
• Proxy rotation for OPSEC
• Full message, media, and metadata archiving
• Network analysis and visualization
• Recursive group discovery
• SQLite database for forensic analysis
• Sidecar metadata for media files

© 2023-2025 SWORD-EPI (SPECTRA Team)
"""
        npyscreen.notify_confirm(about_text, title="About SPECTRA")
    
    def exit_app(self):
        """Exit the application"""
        if npyscreen.notify_yes_no(
            "Are you sure you want to exit?",
            title="Confirm Exit"
        ):
            # Clean up
            AsyncRunner.run_async(self.parentApp.manager.close())
            
            # Exit
            self.parentApp.switchForm(None)


# ── Main Application ─────────────────────────────────────────────────────────
class SpectraApp(npyscreen.NPSAppManaged):
    """Main application class"""
    
    def onStart(self):
        """Initialize application forms"""
        self.manager = None  # Will be initialized in setup_manager
        self.db_instance = None # Add a db_instance to the app
        
        # Register forms
        self.addForm("MAIN", MainMenuForm, name="SPECTRA Main Menu")
        self.addForm("ARCHIVE", ArchiveForm, name="SPECTRA Archiver")
        self.addForm("FORWARDING", ForwardingMenuForm, name="SPECTRA Forwarding")
        self.addForm("CHANNEL_RECOVERY", ChannelRecoveryWizardForm, name="Channel Recovery Wizard")
        self.addForm("SET_FORWARD_DEST", SetForwardDestForm, name="Set Default Forwarding Destination")
        self.addForm("SELECTIVE_FORWARD", SelectiveForwardForm, name="Selective Message Forwarding")
        self.addForm("TOTAL_FORWARD", TotalForwardForm, name="Total Forward Mode")
        self.addForm("REPOST", RepostForm, name="Re-post Messages")
        self.addForm("FORWARDING_SETTINGS", ForwardingSettingsForm, name="Forwarding & Deduplication Settings")
        self.addForm("DISCOVERY", DiscoveryForm, name="SPECTRA Group Discovery")
        self.addForm("GRAPH", GraphExplorerForm, name="SPECTRA Network Explorer")
        self.addForm("VPS_CONFIG", VPSConfigForm, name="VPS Configuration")
        self.addForm("DOWNLOAD_USERS", DownloadUsersForm, name="SPECTRA User Downloader")
        self.addForm("GROUP_MIRROR", GroupMirrorForm, name="SPECTRA Group Mirroring")
        self.addForm("OSINT_MENU", OSINTMenuForm, name="OSINT Utilities")
        self.addForm("OSINT_ADD_TARGET", OSINTAddTargetForm, name="Add OSINT Target")
        self.addForm("OSINT_LIST_TARGETS", OSINTListTargetsForm, name="List OSINT Targets")
        self.addForm("OSINT_SCAN_CHANNEL", OSINTScanChannelForm, name="Scan Channel for Interactions")
        self.addForm("OSINT_SHOW_NETWORK", OSINTShowNetworkForm, name="Show Interaction Network")
    
    def setup_manager(self):
        """Initialize the integrated manager"""
        if self.manager is None:
            # Load config
            config = Config()
            
            # Create integrated manager
            self.manager = discovery.SpectraCrawlerManager(config)
            self.db_instance = SpectraDB(config.db_path)
            
            # Initialize in background
            AsyncRunner.run_in_thread(self.manager.initialize())

    def get_intelligence_collector(self) -> "IntelligenceCollector":
        """Get an instance of the IntelligenceCollector"""
        from .osint.intelligence import IntelligenceCollector
        from telethon import TelegramClient

        if not hasattr(self, '_intelligence_collector'):
            account = self.manager.config.auto_select_account()
            if not account:
                raise Exception("No account available for OSINT operations.")

            client = TelegramClient(account['session_name'], account['api_id'], account['api_hash'])
            # The client needs to be connected, which is handled by the collector methods
            self._intelligence_collector = IntelligenceCollector(self.manager.config, self.db_instance, client)

        return self._intelligence_collector


# ── Entry point ────────────────────────────────────────────────────────────
def main():
    """Application entry point"""
    try:
        app = SpectraApp()
        app.run()
    except KeyboardInterrupt:
        print("\nApplication terminated by user.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Make sure we clean up
        if hasattr(app, 'manager') and app.manager:
            AsyncRunner.run_async(app.manager.close())


if __name__ == "__main__":
    main()
