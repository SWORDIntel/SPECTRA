"""
Kitty Dashboard
===============

Enhanced dashboard with Kitty graphics for SPECTRA.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from .kitty_graphics import KittyGraphics
from .kitty_visualizations import KittyVisualizations

logger = logging.getLogger(__name__)


class KittyDashboard:
    """
    Enhanced dashboard with Kitty graphics.
    
    Features:
    - Real-time metrics visualization
    - Search result charts
    - Performance graphs
    - Activity timelines
    """
    
    def __init__(self):
        """Initialize dashboard"""
        self.graphics = KittyGraphics()
        self.visualizations = KittyVisualizations()
    
    def render_dashboard(
        self,
        metrics: Dict[str, Any],
        search_results: Optional[list] = None,
        performance_data: Optional[Dict[str, float]] = None
    ) -> str:
        """
        Render complete dashboard.
        
        Args:
            metrics: System metrics
            search_results: Recent search results
            performance_data: Performance statistics
        
        Returns:
            Rendered dashboard string
        """
        lines = []
        
        # Header
        lines.append("=" * 80)
        lines.append("SPECTRA Dashboard")
        lines.append("=" * 80)
        lines.append("")
        
        # Metrics
        if metrics:
            lines.append("System Metrics:")
            lines.append(self.visualizations.render_chart(
                list(metrics.values())[:10],
                list(metrics.keys())[:10],
                "Metrics"
            ))
            lines.append("")
        
        # Performance
        if performance_data:
            lines.append("Performance:")
            lines.append(self.visualizations.render_heatmap(performance_data, "Performance Heatmap"))
            lines.append("")
        
        # Search results summary
        if search_results:
            lines.append(f"Recent Search Results: {len(search_results)} items")
            lines.append("")
        
        return "\n".join(lines)
    
    def update_dashboard(self, data: Dict[str, Any]):
        """Update dashboard with new data"""
        if self.graphics.is_available():
            dashboard = self.render_dashboard(**data)
            # Clear screen and render
            print("\033[2J\033[H" + dashboard)
