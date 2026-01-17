"""Remote-friendly features: SSH optimizations and low-bandwidth mode"""

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class RemoteFriendly:
    """Remote-friendly features for SSH and low-bandwidth environments"""
    
    def __init__(self, preferences=None):
        self.preferences = preferences
        self.low_bandwidth_mode = False
        self.ssh_detected = self._detect_ssh()
        self._apply_optimizations()
    
    def _detect_ssh(self) -> bool:
        """Detect if running in SSH session"""
        return bool(os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_CLIENT'))
    
    def _apply_optimizations(self):
        """Apply optimizations based on environment"""
        if self.ssh_detected:
            logger.info("SSH session detected - applying optimizations")
            # Disable graphics, reduce refresh rates, etc.
            if self.preferences:
                self.preferences.set("performance", "refresh_interval_seconds", 10)  # Slower refresh
                self.preferences.set("ui", "compact_mode", True)
    
    def enable_low_bandwidth_mode(self):
        """Enable low-bandwidth optimizations"""
        self.low_bandwidth_mode = True
        if self.preferences:
            self.preferences.set("performance", "refresh_interval_seconds", 15)
            self.preferences.set("ui", "compact_mode", True)
            self.preferences.set("ui", "show_hints", False)
        logger.info("Low-bandwidth mode enabled")
    
    def disable_low_bandwidth_mode(self):
        """Disable low-bandwidth optimizations"""
        self.low_bandwidth_mode = False
        if self.preferences:
            self.preferences.set("performance", "refresh_interval_seconds", 5)
            self.preferences.set("ui", "compact_mode", False)
            self.preferences.set("ui", "show_hints", True)
        logger.info("Low-bandwidth mode disabled")
    
    def get_optimizations(self) -> Dict[str, Any]:
        """Get current optimization settings"""
        return {
            "ssh_detected": self.ssh_detected,
            "low_bandwidth_mode": self.low_bandwidth_mode,
            "refresh_interval": self.preferences.get("performance", "refresh_interval_seconds", 5) if self.preferences else 5,
            "compact_mode": self.preferences.get("ui", "compact_mode", False) if self.preferences else False,
        }
