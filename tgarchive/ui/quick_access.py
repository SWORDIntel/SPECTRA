"""Quick access menu (Ctrl+K) with command palette and favorites"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import npyscreen
    HAS_NPYSCREEN = True
except ImportError:
    HAS_NPYSCREEN = False


class QuickAccessMenu:
    """Quick access menu with command palette"""
    
    def __init__(self, app: Any):
        self.app = app
        self.favorites: List[Dict[str, Any]] = []
        self._load_favorites()
    
    def _load_favorites(self):
        """Load favorites from preferences"""
        if hasattr(self.app, 'preferences'):
            favorites_data = self.app.preferences.get("quick_access", "favorites", [])
            self.favorites = favorites_data if isinstance(favorites_data, list) else []
    
    def _save_favorites(self):
        """Save favorites to preferences"""
        if hasattr(self.app, 'preferences'):
            self.app.preferences.set("quick_access", "favorites", self.favorites)
    
    def show_command_palette(self):
        """Show command palette dialog"""
        if not HAS_NPYSCREEN:
            return
        
        # Build command list
        commands = []
        
        # Forms
        commands.append(("Dashboard", "DASHBOARD"))
        commands.append(("Archive", "ARCHIVE"))
        commands.append(("Forwarding", "FORWARDING"))
        commands.append(("Discovery", "DISCOVERY"))
        commands.append(("Network Analysis", "GRAPH"))
        commands.append(("OSINT", "OSINT_MENU"))
        
        # Quick actions if available
        if hasattr(self.app, 'quick_actions'):
            for alias, action in self.app.quick_actions.get_aliases().items():
                if action.get("action") == "switch_form":
                    commands.append((f"Quick: {alias} ({action.get('description', '')})", action.get("target")))
        
        # Favorites
        for fav in self.favorites:
            commands.append((f"★ {fav.get('name', 'Favorite')}", fav.get("target")))
        
        # Show selection dialog
        if commands:
            F = npyscreen.Form(name="Command Palette (Ctrl+K)")
            F.add(npyscreen.FixedText, value="Select a command:", editable=False)
            command_list = F.add(npyscreen.TitleSelectOne, name="Commands:", values=[c[0] for c in commands], scroll_exit=True)
            F.edit()
            
            if command_list.value:
                selected_idx = command_list.value[0]
                if 0 <= selected_idx < len(commands):
                    target = commands[selected_idx][1]
                    self.app.switchForm(target)
    
    def add_favorite(self, name: str, target: str, description: str = ""):
        """Add a favorite"""
        self.favorites.append({
            "name": name,
            "target": target,
            "description": description,
        })
        self._save_favorites()
    
    def remove_favorite(self, name: str) -> bool:
        """Remove a favorite"""
        for i, fav in enumerate(self.favorites):
            if fav.get("name") == name:
                del self.favorites[i]
                self._save_favorites()
                return True
        return False
    
    def get_favorites(self) -> List[Dict[str, Any]]:
        """Get all favorites"""
        return self.favorites.copy()
