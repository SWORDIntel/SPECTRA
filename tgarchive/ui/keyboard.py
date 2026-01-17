"""
Keyboard Shortcuts Handler for SPECTRA TUI
==========================================

Provides global keyboard shortcuts and hotkeys for improved operator efficiency.
Integrates with npyscreen to intercept and handle keypresses.

Shortcuts:
- Global: Ctrl+D (Dashboard), Ctrl+A (Archive), Ctrl+F (Forwarding), Ctrl+S (Search), Ctrl+Q (Quit)
- Navigation: Esc (Back), Tab/Shift+Tab (Field navigation)
- Quick actions: Ctrl+Enter (Execute), Ctrl+R (Refresh), Ctrl+H (Help)
- Number keys 1-9: Jump to main menu items
"""

import curses
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

try:
    import npyscreen
    HAS_NPYSCREEN = True
except ImportError:
    HAS_NPYSCREEN = False

logger = logging.getLogger(__name__)


class KeyboardShortcutHandler:
    """
    Handles keyboard shortcuts for SPECTRA TUI.
    
    Intercepts keypresses and maps them to actions based on configuration.
    Shortcuts can be customized via data/config/keyboard_shortcuts.json
    """
    
    # Default shortcuts mapping
    DEFAULT_SHORTCUTS = {
        # Global shortcuts
        'ctrl_d': {'action': 'switch_form', 'target': 'DASHBOARD', 'description': 'Go to Dashboard'},
        'ctrl_a': {'action': 'switch_form', 'target': 'ARCHIVE', 'description': 'Go to Archive'},
        'ctrl_f': {'action': 'switch_form', 'target': 'FORWARDING', 'description': 'Go to Forwarding'},
        'ctrl_s': {'action': 'show_search', 'description': 'Show Search'},
        'ctrl_q': {'action': 'quit', 'description': 'Quit Application'},
        'ctrl_k': {'action': 'command_palette', 'description': 'Command Palette'},
        'ctrl_p': {'action': 'switch_profile', 'description': 'Switch Profile'},
        'ctrl_h': {'action': 'show_help', 'description': 'Show Help'},
        'ctrl_r': {'action': 'refresh', 'description': 'Refresh'},
        'ctrl_enter': {'action': 'execute', 'description': 'Execute Selected'},
        'ctrl_question': {'action': 'quick_reference', 'description': 'Quick Reference'},
        
        # Navigation
        'esc': {'action': 'go_back', 'description': 'Go Back'},
        'tab': {'action': 'next_field', 'description': 'Next Field'},
        'shift_tab': {'action': 'prev_field', 'description': 'Previous Field'},
        
        # Number keys for main menu
        '1': {'action': 'switch_form', 'target': 'DASHBOARD', 'description': 'Dashboard'},
        '2': {'action': 'switch_form', 'target': 'ARCHIVE', 'description': 'Archive'},
        '3': {'action': 'switch_form', 'target': 'DISCOVERY', 'description': 'Discover'},
        '4': {'action': 'switch_form', 'target': 'GRAPH', 'description': 'Network Analysis'},
        '5': {'action': 'switch_form', 'target': 'FORWARDING', 'description': 'Forwarding'},
        '6': {'action': 'switch_form', 'target': 'OSINT_MENU', 'description': 'OSINT'},
        '7': {'action': 'switch_form', 'target': 'GROUP_MIRROR', 'description': 'Group Mirror'},
        '8': {'action': 'switch_form', 'target': 'MAIN', 'description': 'Account Management'},
        '9': {'action': 'switch_form', 'target': 'VPS_CONFIG', 'description': 'Settings'},
    }
    
    def __init__(self, app: Any, config_path: Optional[Path] = None):
        """
        Initialize keyboard shortcut handler.
        
        Args:
            app: SpectraApp instance
            config_path: Optional path to keyboard shortcuts config file
        """
        self.app = app
        self.config_path = config_path or Path("data/config/keyboard_shortcuts.json")
        self.shortcuts = self._load_shortcuts()
        self._key_map = self._build_key_map()
        
    def _load_shortcuts(self) -> Dict[str, Dict[str, Any]]:
        """
        Load shortcuts from config file or use defaults.
        
        Returns:
            Dictionary of shortcut configurations
        """
        shortcuts = self.DEFAULT_SHORTCUTS.copy()
        
        # Try to load from config file
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    user_shortcuts = json.load(f)
                    # Merge user shortcuts with defaults
                    shortcuts.update(user_shortcuts)
                    logger.debug(f"Loaded keyboard shortcuts from {self.config_path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load keyboard shortcuts: {e}, using defaults")
        else:
            # Create default config file
            self._save_shortcuts(shortcuts)
        
        return shortcuts
    
    def _save_shortcuts(self, shortcuts: Dict[str, Dict[str, Any]]):
        """Save shortcuts to config file."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(shortcuts, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved keyboard shortcuts to {self.config_path}")
        except IOError as e:
            logger.warning(f"Failed to save keyboard shortcuts: {e}")
    
    def _build_key_map(self) -> Dict[int, str]:
        """
        Build mapping from curses key codes to shortcut names.
        
        Returns:
            Dictionary mapping key codes to shortcut names
        """
        key_map = {}
        
        # Map number keys (ASCII '1' through '9')
        for i in range(1, 10):
            key_map[ord(str(i))] = str(i)
        
        # Map ESC - npyscreen uses curses.KEY_BACKSPACE or 27 for ESC
        key_map[27] = 'esc'  # ESC key
        key_map[curses.KEY_BACKSPACE] = 'esc'  # Backspace as back
        
        # Map Tab
        key_map[ord('\t')] = 'tab'
        key_map[curses.KEY_BTAB] = 'shift_tab'  # Shift+Tab
        
        # Map Ctrl+key combinations
        # In curses/npyscreen, Ctrl+key is key & 0x1F or curses.KEY_CTRL_*
        # Standard ASCII control codes:
        # Ctrl+D = 4, Ctrl+A = 1, Ctrl+F = 6, Ctrl+S = 19, Ctrl+Q = 17
        # Ctrl+H = 8, Ctrl+R = 18, Ctrl+K = 11, Ctrl+P = 16
        # Ctrl+Enter = 10 (Ctrl+J, newline)
        key_map[4] = 'ctrl_d'      # Ctrl+D
        key_map[1] = 'ctrl_a'      # Ctrl+A
        key_map[6] = 'ctrl_f'      # Ctrl+F
        key_map[19] = 'ctrl_s'     # Ctrl+S
        key_map[17] = 'ctrl_q'     # Ctrl+Q
        key_map[8] = 'ctrl_h'      # Ctrl+H
        key_map[18] = 'ctrl_r'     # Ctrl+R
        key_map[11] = 'ctrl_k'     # Ctrl+K
        key_map[16] = 'ctrl_p'     # Ctrl+P
        key_map[10] = 'ctrl_enter' # Ctrl+Enter (Ctrl+J)
        key_map[ord('\n')] = 'ctrl_enter'  # Also handle Enter as execute in some contexts
        
        # Also check for curses KEY_CTRL_* constants if available
        try:
            if hasattr(curses, 'KEY_CTRL_D'):
                key_map[getattr(curses, 'KEY_CTRL_D')] = 'ctrl_d'
        except AttributeError:
            pass
        
        return key_map
    
    def handle_keypress(self, key: int, current_form: Optional[str] = None) -> bool:
        """
        Handle a keypress event.
        
        Args:
            key: Key code from curses/npyscreen
            current_form: Current form name (optional)
            
        Returns:
            True if key was handled, False otherwise
        """
        # Check if key is in our map
        shortcut_name = self._key_map.get(key)
        if not shortcut_name:
            # Try direct lookup for number keys
            if 48 <= key <= 57:  # '0'-'9'
                shortcut_name = chr(key)
            else:
                return False
        
        # Get shortcut config
        shortcut_config = self.shortcuts.get(shortcut_name)
        if not shortcut_config:
            return False
        
        # Execute action
        action = shortcut_config.get('action')
        if not action:
            return False
        
        try:
            return self._execute_action(action, shortcut_config, current_form)
        except Exception as e:
            logger.error(f"Error executing shortcut {shortcut_name}: {e}")
            return False
    
    def _execute_action(
        self,
        action: str,
        config: Dict[str, Any],
        current_form: Optional[str]
    ) -> bool:
        """
        Execute a shortcut action.
        
        Args:
            action: Action name
            config: Shortcut configuration
            current_form: Current form name
            
        Returns:
            True if action was executed
        """
        if action == 'switch_form':
            target = config.get('target')
            if target:
                self.app.switchForm(target)
                return True
        
        elif action == 'go_back':
            # Go back to main menu
            self.app.switchForm("MAIN")
            return True
        
        elif action == 'quit':
            # Exit application
            if hasattr(self.app, 'getForm'):
                main_form = self.app.getForm("MAIN")
                if main_form and hasattr(main_form, 'exit_app'):
                    main_form.exit_app()
                    return True
            return False
        
        elif action == 'show_help':
            # Show help
            if hasattr(self.app, 'getForm'):
                main_form = self.app.getForm("MAIN")
                if main_form and hasattr(main_form, 'help_form'):
                    main_form.help_form()
                    return True
            return False
        
        elif action == 'refresh':
            # Refresh current form
            current = self.app.getForm(current_form) if current_form else None
            if current and hasattr(current, 'refresh_stats'):
                current.refresh_stats()
                return True
            elif current and hasattr(current, 'display'):
                current.display()
                return True
            return False
        
        elif action == 'command_palette':
            # Command palette - show quick access menu
            if hasattr(self.app, 'show_command_palette'):
                self.app.show_command_palette()
                return True
            logger.debug("Command palette not available")
            return False
        
        elif action == 'switch_profile':
            # Switch profile (to be implemented)
            logger.debug("Profile switching not yet implemented")
            return False
        
        elif action == 'show_search':
            # Show search (to be implemented)
            logger.debug("Search dialog not yet implemented")
            return False
        
        elif action == 'execute':
            # Execute selected (context-dependent)
            logger.debug("Execute action - context dependent")
            return False
        
        elif action == 'quick_reference':
            # Show quick reference (to be implemented)
            logger.debug("Quick reference not yet implemented")
            return False
        
        elif action == 'next_field':
            # Next field (handled by npyscreen by default)
            return False
        
        elif action == 'prev_field':
            # Previous field (handled by npyscreen by default)
            return False
        
        return False
    
    def get_shortcut_help(self) -> str:
        """
        Get help text for all shortcuts.
        
        Returns:
            Formatted help text
        """
        lines = ["Keyboard Shortcuts:", ""]
        
        # Group by category
        global_shortcuts = []
        nav_shortcuts = []
        menu_shortcuts = []
        
        for name, config in sorted(self.shortcuts.items()):
            desc = config.get('description', '')
            if name.startswith('ctrl_') or name in ['esc', 'tab', 'shift_tab']:
                if name in ['esc', 'tab', 'shift_tab']:
                    nav_shortcuts.append(f"  {name.upper():20} - {desc}")
                else:
                    global_shortcuts.append(f"  {name.upper():20} - {desc}")
            elif name.isdigit():
                menu_shortcuts.append(f"  {name:20} - {desc}")
        
        if global_shortcuts:
            lines.append("Global Shortcuts:")
            lines.extend(global_shortcuts)
            lines.append("")
        
        if nav_shortcuts:
            lines.append("Navigation:")
            lines.extend(nav_shortcuts)
            lines.append("")
        
        if menu_shortcuts:
            lines.append("Main Menu (from Main Menu only):")
            lines.extend(menu_shortcuts)
        
        return "\n".join(lines)


def create_keyboard_handler(app: Any, config_path: Optional[Path] = None) -> KeyboardShortcutHandler:
    """
    Create and initialize keyboard shortcut handler.
    
    Args:
        app: SpectraApp instance
        config_path: Optional path to config file
        
    Returns:
        Initialized KeyboardShortcutHandler
    """
    return KeyboardShortcutHandler(app, config_path)


if HAS_NPYSCREEN:
    class ShortcutWidget(npyscreen.Widget):
        """
        Invisible widget that intercepts keyboard shortcuts.
        
        This widget can be added to forms to handle global shortcuts.
        It's invisible and doesn't take focus, but intercepts keypresses.
        """
        
        def __init__(self, *args, **keywords):
            super().__init__(*args, **keywords)
            self.handled = False
            self.editable = False  # Don't take focus
        
        def set_up_handlers(self):
            """Set up keyboard handlers"""
            super().set_up_handlers()
            # Add handlers for Ctrl+key combinations
            for key_code in [4, 1, 6, 19, 17, 8, 18, 11, 16, 10]:  # Ctrl+D, A, F, S, Q, H, R, K, P, Enter
                self.handlers[key_code] = self.handle_shortcut
        
        def handle_shortcut(self, key):
            """Handle a keyboard shortcut"""
            if hasattr(self.parent, 'parentApp') and hasattr(self.parentApp, 'keyboard_handler'):
                current_form = self.parent.name if hasattr(self.parent, 'name') else None
                if self.parentApp.keyboard_handler.handle_keypress(key, current_form):
                    self.handled = True
                    return True
            return False
        
        def when_cursor_moved(self):
            """Called when cursor moves - not used"""
            pass
        
        def update(self, clear=False):
            """Update display - widget is invisible"""
            pass
else:
    # Dummy class if npyscreen not available
    class ShortcutWidget:
        pass
