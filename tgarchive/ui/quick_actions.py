"""
Quick Actions and Aliases System for SPECTRA TUI
=================================================

Provides quick action commands (qa, qd, qf) and customizable aliases
for common operations.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Callable

logger = logging.getLogger(__name__)

try:
    import npyscreen
    HAS_NPYSCREEN = True
except ImportError:
    HAS_NPYSCREEN = False


class QuickActions:
    """
    Quick actions and aliases manager.
    
    Provides:
    - Quick action commands (qa=archive, qd=dashboard, qf=forwarding)
    - Customizable aliases
    - Command execution shortcuts
    """
    
    # Default quick actions
    DEFAULT_ACTIONS = {
        "qa": {"action": "switch_form", "target": "ARCHIVE", "description": "Quick Archive"},
        "qd": {"action": "switch_form", "target": "DASHBOARD", "description": "Quick Dashboard"},
        "qf": {"action": "switch_form", "target": "FORWARDING", "description": "Quick Forwarding"},
        "qs": {"action": "switch_form", "target": "DISCOVERY", "description": "Quick Search/Discovery"},
        "qg": {"action": "switch_form", "target": "GRAPH", "description": "Quick Graph"},
        "qm": {"action": "switch_form", "target": "MAIN", "description": "Quick Main Menu"},
    }
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize quick actions system.
        
        Args:
            config_path: Path to aliases config file (default: data/config/aliases.json)
        """
        if config_path is None:
            config_path = Path("data/config/aliases.json")
        
        self.config_path = config_path
        self.actions = self.DEFAULT_ACTIONS.copy()
        self._load_aliases()
    
    def _load_aliases(self):
        """Load custom aliases from config file"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    user_aliases = json.load(f)
                    self.actions.update(user_aliases)
                    logger.debug(f"Loaded aliases from {self.config_path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load aliases: {e}, using defaults")
        else:
            self._save_aliases()
    
    def _save_aliases(self):
        """Save aliases to config file"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.actions, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved aliases to {self.config_path}")
        except IOError as e:
            logger.warning(f"Failed to save aliases: {e}")
    
    def execute(self, alias: str, app: Any) -> bool:
        """
        Execute a quick action or alias.
        
        Args:
            alias: Alias or quick action name
            app: SpectraApp instance
            
        Returns:
            True if action was executed, False otherwise
        """
        action_config = self.actions.get(alias.lower())
        if not action_config:
            return False
        
        action = action_config.get("action")
        if action == "switch_form":
            target = action_config.get("target")
            if target:
                app.switchForm(target)
                return True
        elif action == "execute_function":
            func_name = action_config.get("function")
            if func_name and hasattr(app, func_name):
                getattr(app, func_name)()
                return True
        
        return False
    
    def add_alias(self, alias: str, action: str, target: Optional[str] = None, description: str = ""):
        """
        Add or update an alias.
        
        Args:
            alias: Alias name
            action: Action type ("switch_form", "execute_function")
            target: Target form name or function name
            description: Optional description
        """
        self.actions[alias.lower()] = {
            "action": action,
            "target": target,
            "description": description,
        }
        self._save_aliases()
    
    def get_aliases(self) -> Dict[str, Dict[str, Any]]:
        """Get all aliases and quick actions"""
        return self.actions.copy()


def create_quick_actions(config_path: Optional[Path] = None) -> QuickActions:
    """Create and initialize quick actions system"""
    return QuickActions(config_path)
