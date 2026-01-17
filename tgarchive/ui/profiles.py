"""Configuration profiles system for SPECTRA"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ConfigProfile:
    """Configuration profile"""
    
    def __init__(self, name: str, config_data: Dict[str, Any]):
        self.name = name
        self.config_data = config_data
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {"name": self.name, "config": self.config_data}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConfigProfile':
        """Create from dictionary"""
        return cls(data["name"], data.get("config", {}))


class ProfileManager:
    """Manages configuration profiles"""
    
    def __init__(self, profiles_dir: Optional[Path] = None):
        if profiles_dir is None:
            profiles_dir = Path("data/profiles")
        self.profiles_dir = profiles_dir
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.profiles: Dict[str, ConfigProfile] = {}
        self.current_profile: Optional[str] = None
        self._load_profiles()
    
    def _load_profiles(self):
        """Load profiles from directory"""
        for profile_file in self.profiles_dir.glob("*.json"):
            try:
                with open(profile_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    profile = ConfigProfile.from_dict(data)
                    self.profiles[profile.name] = profile
            except Exception as e:
                logger.warning(f"Failed to load profile {profile_file}: {e}")
    
    def save_profile(self, profile: ConfigProfile):
        """Save a profile"""
        profile_file = self.profiles_dir / f"{profile.name}.json"
        try:
            with open(profile_file, 'w', encoding='utf-8') as f:
                json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
            self.profiles[profile.name] = profile
            logger.debug(f"Saved profile: {profile.name}")
        except Exception as e:
            logger.error(f"Failed to save profile {profile.name}: {e}")
    
    def get_profile(self, name: str) -> Optional[ConfigProfile]:
        """Get a profile by name"""
        return self.profiles.get(name)
    
    def list_profiles(self) -> List[str]:
        """List all profile names"""
        return list(self.profiles.keys())
    
    def set_current(self, name: str) -> bool:
        """Set current active profile"""
        if name in self.profiles:
            self.current_profile = name
            return True
        return False
    
    def get_current(self) -> Optional[ConfigProfile]:
        """Get current active profile"""
        if self.current_profile:
            return self.profiles.get(self.current_profile)
        return None
    
    def delete_profile(self, name: str) -> bool:
        """Delete a profile"""
        profile_file = self.profiles_dir / f"{name}.json"
        if profile_file.exists():
            profile_file.unlink()
            self.profiles.pop(name, None)
            if self.current_profile == name:
                self.current_profile = None
            return True
        return False
