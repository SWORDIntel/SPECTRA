"""
Contextual Help System for SPECTRA TUI
=======================================

Provides context-sensitive help, tooltips, and quick reference for operators.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import npyscreen
    HAS_NPYSCREEN = True
except ImportError:
    HAS_NPYSCREEN = False
    logger.warning("npyscreen not available - help system disabled")


class HelpSystem:
    """
    Contextual help system for SPECTRA TUI.
    
    Provides:
    - Context-sensitive help for forms and fields
    - Tooltips for widgets
    - Quick reference for keyboard shortcuts
    - Examples database
    """
    
    # Default help content
    DEFAULT_HELP = {
        "forms": {
            "MAIN": {
                "title": "SPECTRA Main Menu",
                "description": "Main navigation menu for all SPECTRA operations",
                "fields": {},
                "shortcuts": "Press number keys (1-9) to jump to menu items",
            },
            "DASHBOARD": {
                "title": "SPECTRA Dashboard",
                "description": "Real-time system status and activity monitoring",
                "fields": {
                    "accounts_status": "Shows active and total configured accounts",
                    "db_status": "Database connection status",
                    "total_channels": "Number of archived channels",
                    "total_messages": "Total messages archived",
                    "discovered_groups": "Number of groups discovered",
                },
                "shortcuts": "Ctrl+R to refresh stats",
            },
            "ARCHIVE": {
                "title": "Archive Channel/Group",
                "description": "Archive messages, media, and metadata from Telegram channels/groups",
                "fields": {
                    "entity": "Channel/group username, ID, or invite link (e.g., @channel, 123456789, https://t.me/joinchat/...)",
                    "download_media": "Download media files (images, videos, documents)",
                    "download_avatars": "Download user/group avatars",
                    "sidecar_metadata": "Create .json sidecar files with message metadata",
                    "archive_topics": "Archive all topics/threads in groups",
                },
                "examples": [
                    "Archive public channel: @channelname",
                    "Archive by ID: 123456789",
                    "Archive with invite link: https://t.me/joinchat/ABC123",
                ],
            },
            "DISCOVERY": {
                "title": "Discover Groups",
                "description": "Discover new groups from seed channels using network analysis",
                "fields": {
                    "seed": "Starting channel/group to discover from",
                    "depth": "Discovery depth (how many hops to traverse)",
                    "msg_limit": "Maximum messages to analyze per group",
                },
            },
            "FORWARDING": {
                "title": "Forwarding Utilities",
                "description": "Forward messages between channels with deduplication",
                "fields": {},
            },
        },
        "shortcuts": {
            "global": {
                "ctrl_d": "Go to Dashboard",
                "ctrl_a": "Go to Archive",
                "ctrl_f": "Go to Forwarding",
                "ctrl_s": "Show Search",
                "ctrl_q": "Quit Application",
                "ctrl_h": "Show Help",
                "ctrl_r": "Refresh",
                "ctrl_k": "Command Palette",
                "esc": "Go Back",
            },
            "navigation": {
                "tab": "Next Field",
                "shift_tab": "Previous Field",
                "1-9": "Jump to main menu item (from main menu only)",
            },
        },
    }
    
    def __init__(self, help_dir: Optional[Path] = None):
        """
        Initialize help system.
        
        Args:
            help_dir: Directory containing help content files (default: data/help/)
        """
        self.help_dir = help_dir or Path("data/help")
        self.help_dir.mkdir(parents=True, exist_ok=True)
        
        self.help_content = self.DEFAULT_HELP.copy()
        self._load_help_content()
    
    def _load_help_content(self):
        """Load help content from files"""
        help_file = self.help_dir / "help_content.json"
        if help_file.exists():
            try:
                with open(help_file, 'r', encoding='utf-8') as f:
                    user_help = json.load(f)
                    # Merge with defaults
                    self._merge_help_content(user_help)
                    logger.debug(f"Loaded help content from {help_file}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load help content: {e}, using defaults")
        else:
            # Save defaults
            self._save_help_content()
    
    def _merge_help_content(self, user_help: Dict[str, Any]):
        """Merge user help content with defaults"""
        # Merge forms
        if "forms" in user_help:
            for form_name, form_help in user_help["forms"].items():
                if form_name in self.help_content["forms"]:
                    self.help_content["forms"][form_name].update(form_help)
                else:
                    self.help_content["forms"][form_name] = form_help
        
        # Merge shortcuts
        if "shortcuts" in user_help:
            for category, shortcuts in user_help["shortcuts"].items():
                if category in self.help_content["shortcuts"]:
                    self.help_content["shortcuts"][category].update(shortcuts)
                else:
                    self.help_content["shortcuts"][category] = shortcuts
    
    def _save_help_content(self):
        """Save help content to file"""
        try:
            help_file = self.help_dir / "help_content.json"
            with open(help_file, 'w', encoding='utf-8') as f:
                json.dump(self.help_content, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved help content to {help_file}")
        except IOError as e:
            logger.warning(f"Failed to save help content: {e}")
    
    def get_form_help(self, form_name: str) -> Optional[Dict[str, Any]]:
        """
        Get help content for a form.
        
        Args:
            form_name: Form name (e.g., "ARCHIVE", "DASHBOARD")
            
        Returns:
            Help content dictionary or None
        """
        return self.help_content.get("forms", {}).get(form_name)
    
    def get_field_help(self, form_name: str, field_name: str) -> Optional[str]:
        """
        Get help text for a specific field.
        
        Args:
            form_name: Form name
            field_name: Field/widget name
            
        Returns:
            Help text or None
        """
        form_help = self.get_form_help(form_name)
        if form_help:
            fields = form_help.get("fields", {})
            return fields.get(field_name)
        return None
    
    def get_shortcuts_help(self) -> str:
        """
        Get formatted keyboard shortcuts help text.
        
        Returns:
            Formatted help text
        """
        lines = ["Keyboard Shortcuts:", ""]
        
        # Global shortcuts
        global_shortcuts = self.help_content.get("shortcuts", {}).get("global", {})
        if global_shortcuts:
            lines.append("Global Shortcuts:")
            for key, desc in sorted(global_shortcuts.items()):
                lines.append(f"  {key.upper():20} - {desc}")
            lines.append("")
        
        # Navigation shortcuts
        nav_shortcuts = self.help_content.get("shortcuts", {}).get("navigation", {})
        if nav_shortcuts:
            lines.append("Navigation:")
            for key, desc in sorted(nav_shortcuts.items()):
                lines.append(f"  {key.upper():20} - {desc}")
        
        return "\n".join(lines)
    
    def show_help(self, form_name: Optional[str] = None, field_name: Optional[str] = None) -> str:
        """
        Get help text for form or field.
        
        Args:
            form_name: Optional form name
            field_name: Optional field name
            
        Returns:
            Help text
        """
        if field_name and form_name:
            # Field-specific help
            help_text = self.get_field_help(form_name, field_name)
            if help_text:
                return f"Field Help: {field_name}\n\n{help_text}"
            return f"No help available for field: {field_name}"
        
        if form_name:
            # Form help
            form_help = self.get_form_help(form_name)
            if form_help:
                lines = [f"Help: {form_help.get('title', form_name)}", ""]
                desc = form_help.get("description")
                if desc:
                    lines.append(desc)
                    lines.append("")
                
                fields = form_help.get("fields", {})
                if fields:
                    lines.append("Fields:")
                    for field, field_help in fields.items():
                        lines.append(f"  {field}: {field_help}")
                    lines.append("")
                
                examples = form_help.get("examples", [])
                if examples:
                    lines.append("Examples:")
                    for example in examples:
                        lines.append(f"  • {example}")
                    lines.append("")
                
                shortcuts = form_help.get("shortcuts")
                if shortcuts:
                    lines.append(f"Shortcuts: {shortcuts}")
                
                return "\n".join(lines)
            return f"No help available for form: {form_name}"
        
        # General help
        return self.get_shortcuts_help()


def create_help_system(help_dir: Optional[Path] = None) -> HelpSystem:
    """
    Create and initialize help system.
    
    Args:
        help_dir: Optional help directory path
        
    Returns:
        Initialized HelpSystem
    """
    return HelpSystem(help_dir)
