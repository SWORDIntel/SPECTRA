"""
Kitty Graphics Integration
===========================

Kitty terminal graphics wrapper for SPECTRA TUI enhancements.
"""

import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Try to import EKI
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent / "libs" / "EKI"))
    from modules.kitty_remote_control import KittyRemoteControl, KittyState
    EKI_AVAILABLE = True
except ImportError:
    EKI_AVAILABLE = False
    logger.warning("EKI not available. Kitty graphics disabled.")


class KittyGraphics:
    """
    Kitty graphics wrapper for SPECTRA visualizations.
    
    Features:
    - Terminal detection
    - Graphics protocol support
    - Remote control integration
    """
    
    def __init__(self):
        """Initialize Kitty graphics"""
        self.remote_control = None
        self.is_kitty = self._detect_kitty()
        
        if self.is_kitty and EKI_AVAILABLE:
            try:
                self.remote_control = KittyRemoteControl()
            except Exception as e:
                logger.warning(f"Failed to initialize Kitty remote control: {e}")
                self.remote_control = None
    
    def _detect_kitty(self) -> bool:
        """Detect if running in Kitty terminal"""
        term = sys.environ.get('TERM', '')
        kitty_pid = sys.environ.get('KITTY_PID')
        return 'kitty' in term.lower() or kitty_pid is not None
    
    def is_available(self) -> bool:
        """Check if Kitty graphics are available"""
        return self.is_kitty and self.remote_control is not None
    
    def send_image(self, image_path: str, width: Optional[int] = None, height: Optional[int] = None):
        """Display inline image"""
        if not self.is_available():
            return False
        
        # Kitty graphics protocol for images
        # \033_Gf=100,r=1,a=T,f=24,s=100,v=300,t=d;base64_data\033\\
        try:
            import base64
            with open(image_path, 'rb') as f:
                img_data = base64.b64encode(f.read()).decode('ascii')
            
            width = width or 300
            height = height or 200
            
            # Send image via Kitty graphics protocol
            cmd = f"\033_Gf=100,r=1,a=T,f=24,s={width},v={height},t=d;{img_data}\033\\"
            sys.stdout.write(cmd)
            sys.stdout.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to send image: {e}")
            return False
    
    def get_state(self) -> Optional[KittyState]:
        """Get Kitty terminal state"""
        if not self.is_available():
            return None
        return self.remote_control.get_state()
