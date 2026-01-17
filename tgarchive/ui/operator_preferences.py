"""Operator preferences system with UI customization and defaults"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class OperatorPreferences:
    """Manages operator preferences and UI customization"""
    
    DEFAULT_PREFS = {
        "ui": {
            "theme": "default",
            "color_scheme": "default",
            "show_hints": True,
            "compact_mode": False,
        },
        "defaults": {
            "default_account": None,
            "default_media_dir": "media",
            "auto_save_config": True,
            "confirm_destructive": True,
        },
        "performance": {
            "max_concurrent_operations": 3,
            "refresh_interval_seconds": 5,
            "history_size": 5000,
        },
        "shortcuts": {
            "enable_quick_actions": True,
            "enable_keyboard_shortcuts": True,
        },
    }
    
    def __init__(self, prefs_file: Optional[Path] = None):
        if prefs_file is None:
            prefs_file = Path("data/config/operator_preferences.json")
        self.prefs_file = prefs_file
        self.prefs_file.parent.mkdir(parents=True, exist_ok=True)
        self.prefs = self.DEFAULT_PREFS.copy()
        self._load_preferences()
    
    def _load_preferences(self):
        """Load preferences from file"""
        if self.prefs_file.exists():
            try:
                with open(self.prefs_file, 'r', encoding='utf-8') as f:
                    user_prefs = json.load(f)
                    # Deep merge
                    self._merge_prefs(user_prefs)
            except Exception as e:
                logger.warning(f"Failed to load preferences: {e}")
        else:
            self._save_preferences()
    
    def _merge_prefs(self, user_prefs: Dict[str, Any]):
        """Deep merge user preferences with defaults"""
        for key, value in user_prefs.items():
            if key in self.prefs and isinstance(self.prefs[key], dict) and isinstance(value, dict):
                self.prefs[key].update(value)
            else:
                self.prefs[key] = value
    
    def _save_preferences(self):
        """Save preferences to file"""
        try:
            with open(self.prefs_file, 'w', encoding='utf-8') as f:
                json.dump(self.prefs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save preferences: {e}")
    
    def get(self, category: str, key: str, default: Any = None) -> Any:
        """Get a preference value"""
        return self.prefs.get(category, {}).get(key, default)
    
    def set(self, category: str, key: str, value: Any):
        """Set a preference value"""
        if category not in self.prefs:
            self.prefs[category] = {}
        self.prefs[category][key] = value
        self._save_preferences()
    
    def get_all(self) -> Dict[str, Any]:
        """Get all preferences"""
        return self.prefs.copy()
    
    def update(self, category: str, values: Dict[str, Any]):
        """Update multiple preferences in a category"""
        if category not in self.prefs:
            self.prefs[category] = {}
        self.prefs[category].update(values)
        self._save_preferences()
    
    def reset_category(self, category: str):
        """Reset a category to defaults"""
        if category in self.DEFAULT_PREFS:
            self.prefs[category] = self.DEFAULT_PREFS[category].copy()
            self._save_preferences()
