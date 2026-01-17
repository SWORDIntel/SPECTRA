"""
Kitty Visualizations
====================

Visual components for SPECTRA using Kitty graphics.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from .kitty_graphics import KittyGraphics

logger = logging.getLogger(__name__)


class KittyVisualizations:
    """
    Visualization components using Kitty graphics.
    
    Features:
    - Charts and graphs
    - Network graphs
    - Activity timelines
    - Threat score heatmaps
    """
    
    def __init__(self):
        """Initialize visualizations"""
        self.graphics = KittyGraphics()
    
    def render_chart(
        self,
        data: List[float],
        labels: Optional[List[str]] = None,
        title: str = ""
    ) -> str:
        """
        Render ASCII chart.
        
        Args:
            data: Data points
            labels: Optional labels
            title: Chart title
        
        Returns:
            Rendered chart string
        """
        if not data:
            return ""
        
        max_val = max(data)
        min_val = min(data)
        range_val = max_val - min_val if max_val != min_val else 1
        
        # Simple ASCII bar chart
        chart_lines = [title] if title else []
        chart_lines.append("─" * 50)
        
        for i, value in enumerate(data):
            bar_length = int((value - min_val) / range_val * 40)
            bar = "█" * bar_length
            label = labels[i] if labels and i < len(labels) else str(i)
            chart_lines.append(f"{label:10} │{bar} {value:.2f}")
        
        return "\n".join(chart_lines)
    
    def render_network_graph(self, nodes: List[Dict], edges: List[Dict]) -> str:
        """
        Render network graph as ASCII visualization.
        
        Args:
            nodes: List of node dictionaries with id, label, etc.
            edges: List of edge dictionaries with source, target, weight, etc.
        
        Returns:
            ASCII representation of network graph
        """
        if not nodes:
            return "Network: No nodes"
        
        lines = [f"Network Graph: {len(nodes)} nodes, {len(edges)} edges"]
        lines.append("─" * 60)
        
        # Display node summary
        for i, node in enumerate(nodes[:10]):  # Limit display
            node_id = node.get('id', i)
            label = node.get('label', f'Node {node_id}')
            lines.append(f"  {node_id}: {label}")
        
        if len(nodes) > 10:
            lines.append(f"  ... and {len(nodes) - 10} more nodes")
        
        # Display edge summary
        if edges:
            lines.append("")
            lines.append("Connections:")
            for edge in edges[:5]:  # Limit display
                source = edge.get('source', '?')
                target = edge.get('target', '?')
                weight = edge.get('weight', 1.0)
                lines.append(f"  {source} → {target} (weight: {weight:.2f})")
            
            if len(edges) > 5:
                lines.append(f"  ... and {len(edges) - 5} more connections")
        
        return "\n".join(lines)
    
    def render_timeline(
        self,
        events: List[Dict[str, Any]],
        width: int = 80
    ) -> str:
        """Render activity timeline"""
        if not events:
            return ""
        
        timeline = ["Timeline:"]
        timeline.append("─" * width)
        
        for event in events[:20]:  # Limit display
            timestamp = event.get('timestamp', '')
            content = str(event.get('content', ''))[:50]
            timeline.append(f"{timestamp} │ {content}")
        
        return "\n".join(timeline)
    
    def render_heatmap(
        self,
        data: Dict[str, float],
        title: str = "Heatmap"
    ) -> str:
        """Render threat score heatmap"""
        if not data:
            return ""
        
        # Simple heatmap using color codes
        heatmap = [title]
        heatmap.append("─" * 50)
        
        sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)
        for key, value in sorted_items[:10]:
            # Color intensity based on value
            intensity = int(value * 10) if value <= 1.0 else 10
            bar = "█" * intensity
            heatmap.append(f"{key:30} │{bar} {value:.2f}")
        
        return "\n".join(heatmap)
