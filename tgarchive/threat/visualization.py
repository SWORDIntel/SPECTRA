"""
SPECTRA Threat Visualization Generator
=======================================
Generates Mermaid diagrams and other visualizations for threat networks.

Features:
- Mermaid network graphs
- Threat score-based styling
- Community/cluster visualization
- Timeline diagrams
- Threat intelligence reports
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from .network import ActorRelationship, ThreatNetworkTracker
from .scoring import ThreatActorProfile, ThreatClassification

logger = logging.getLogger(__name__)


class MermaidGenerator:
    """
    Generates Mermaid diagram code for threat networks.
    """

    # Color schemes for threat levels
    THREAT_COLORS = {
        ThreatClassification.CRITICAL_RISK: {
            "fill": "#ff6b6b",
            "stroke": "#c92a2a",
            "stroke_width": "3px",
            "color": "#fff",
        },
        ThreatClassification.HIGH_RISK: {
            "fill": "#ff922b",
            "stroke": "#d9480f",
            "stroke_width": "2px",
            "color": "#fff",
        },
        ThreatClassification.MEDIUM_RISK: {
            "fill": "#ffd43b",
            "stroke": "#fab005",
            "stroke_width": "2px",
            "color": "#000",
        },
        ThreatClassification.LOW_RISK: {
            "fill": "#51cf66",
            "stroke": "#2f9e44",
            "stroke_width": "1px",
            "color": "#000",
        },
        ThreatClassification.HARMLESS: {
            "fill": "#a9e34b",
            "stroke": "#5c940d",
            "stroke_width": "1px",
            "color": "#000",
        },
    }

    @classmethod
    def generate_network_graph(
        cls,
        profiles: List[ThreatActorProfile],
        network_tracker: ThreatNetworkTracker,
        max_nodes: int = 50,
        min_interactions: int = 3,
        title: str = "Threat Actor Network",
    ) -> str:
        """
        Generate Mermaid network graph diagram.

        Args:
            profiles: List of threat actor profiles
            network_tracker: Network tracker with relationships
            max_nodes: Maximum number of nodes to include
            min_interactions: Minimum interactions for edge
            title: Diagram title

        Returns:
            Mermaid diagram code as string
        """
        # Sort profiles by threat score (top threats first)
        sorted_profiles = sorted(profiles, key=lambda p: p.threat_score, reverse=True)
        top_profiles = sorted_profiles[:max_nodes]

        # Create node ID mapping
        profile_map = {p.user_id: p for p in top_profiles}
        user_ids = set(profile_map.keys())

        # Start Mermaid graph
        mermaid_lines = [
            "```mermaid",
            "graph TD",
        ]

        # Add title as comment
        mermaid_lines.append(f"    %% {title}")
        mermaid_lines.append("")

        # Add nodes with labels
        for profile in top_profiles:
            node_id = f"U{profile.user_id}"
            username = cls._escape_label(profile.username or f"User_{profile.user_id}")
            score = f"{profile.threat_score:.1f}"
            classification = profile.classification.value

            # Multi-line label
            label = f"{username}<br/>Score: {score}<br/>{classification}"

            # Get class name for styling
            class_name = cls._get_class_name(profile.classification)

            mermaid_lines.append(f'    {node_id}["{label}"]:::{class_name}')

        mermaid_lines.append("")

        # Add edges (relationships)
        edge_count = 0
        for (source_id, target_id), rel in network_tracker.relationships.items():
            if source_id in user_ids and target_id in user_ids:
                if rel.interaction_count >= min_interactions:
                    source_node = f"U{source_id}"
                    target_node = f"U{target_id}"
                    count = rel.interaction_count

                    # Edge label with interaction count
                    edge_label = f"{count} interactions"

                    mermaid_lines.append(f'    {source_node} -->|{edge_label}| {target_node}')
                    edge_count += 1

        if edge_count == 0:
            mermaid_lines.append("    %% No relationships meet minimum interaction threshold")

        mermaid_lines.append("")

        # Add class definitions for styling
        mermaid_lines.extend(cls._generate_class_defs())

        mermaid_lines.append("```")

        return "\n".join(mermaid_lines)

    @classmethod
    def generate_community_graph(
        cls,
        profiles: List[ThreatActorProfile],
        network_tracker: ThreatNetworkTracker,
        communities: Dict[int, int],
        title: str = "Threat Actor Communities",
    ) -> str:
        """
        Generate Mermaid diagram showing community structure.

        Args:
            profiles: List of threat actor profiles
            network_tracker: Network tracker
            communities: Dict mapping user_id -> community_id
            title: Diagram title

        Returns:
            Mermaid diagram code
        """
        # Group profiles by community
        community_groups: Dict[int, List[ThreatActorProfile]] = {}

        for profile in profiles:
            if profile.user_id in communities:
                comm_id = communities[profile.user_id]
                if comm_id not in community_groups:
                    community_groups[comm_id] = []
                community_groups[comm_id].append(profile)

        # Start Mermaid graph
        mermaid_lines = [
            "```mermaid",
            "graph LR",
            f"    %% {title}",
            "",
        ]

        # Add each community as a subgraph
        for comm_id, comm_profiles in community_groups.items():
            # Calculate average threat score for community
            avg_score = sum(p.threat_score for p in comm_profiles) / len(comm_profiles)

            # Determine community threat level
            if avg_score >= 9.0:
                comm_label = f"APT Group (Critical)"
            elif avg_score >= 7.0:
                comm_label = f"Cybercrime Network (High)"
            elif avg_score >= 5.0:
                comm_label = f"Medium Risk Group"
            else:
                comm_label = f"Low Risk Group"

            mermaid_lines.append(f'    subgraph Cluster_{comm_id}["{comm_label}"]')

            # Add actors in community
            for profile in comm_profiles[:10]:  # Limit to 10 per community
                node_id = f"U{profile.user_id}"
                username = cls._escape_label(profile.username or f"User_{profile.user_id}")
                score = f"{profile.threat_score:.1f}"

                mermaid_lines.append(f'        {node_id}["{username}<br/>{score}"]')

            mermaid_lines.append("    end")
            mermaid_lines.append("")

        # Add inter-community edges
        for (source_id, target_id), rel in network_tracker.relationships.items():
            if source_id in communities and target_id in communities:
                source_comm = communities[source_id]
                target_comm = communities[target_id]

                if source_comm != target_comm and rel.interaction_count >= 5:
                    source_node = f"U{source_id}"
                    target_node = f"U{target_id}"

                    mermaid_lines.append(f'    {source_node} -->|{rel.interaction_count}| {target_node}')

        mermaid_lines.append("```")

        return "\n".join(mermaid_lines)

    @classmethod
    def generate_timeline(
        cls,
        profiles: List[ThreatActorProfile],
        title: str = "Threat Actor Activity Timeline",
    ) -> str:
        """
        Generate Gantt chart showing actor activity timelines.

        Args:
            profiles: List of threat actor profiles
            title: Diagram title

        Returns:
            Mermaid Gantt chart code
        """
        # Sort by threat score
        sorted_profiles = sorted(profiles, key=lambda p: p.threat_score, reverse=True)
        top_profiles = sorted_profiles[:15]  # Top 15 actors

        mermaid_lines = [
            "```mermaid",
            "gantt",
            f"    title {title}",
            "    dateFormat YYYY-MM-DD",
            "",
        ]

        # Add sections per actor
        for profile in top_profiles:
            if not profile.first_seen or not profile.last_seen:
                continue

            username = cls._escape_label(profile.username or f"User_{profile.user_id}")
            score = f"{profile.threat_score:.1f}"
            section_name = f"{username} ({score})"

            mermaid_lines.append(f"    section {section_name}")

            # Format dates
            start_date = profile.first_seen.strftime("%Y-%m-%d")
            end_date = profile.last_seen.strftime("%Y-%m-%d")

            # Calculate duration
            duration = (profile.last_seen - profile.first_seen).days

            # Determine if critical (for styling)
            task_style = "crit, " if profile.threat_score >= 8.0 else ""

            task_name = f"Activity Period"
            task_id = f"a{profile.user_id}"

            mermaid_lines.append(f"    {task_name} :{task_style}{task_id}, {start_date}, {duration}d")
            mermaid_lines.append("")

        mermaid_lines.append("```")

        return "\n".join(mermaid_lines)

    @staticmethod
    def _escape_label(text: str) -> str:
        """Escape special characters in labels for Mermaid."""
        # Replace characters that break Mermaid syntax
        text = text.replace('"', "'")
        text = text.replace('\n', ' ')
        text = text.replace('[', '(')
        text = text.replace(']', ')')
        return text[:50]  # Limit length

    @staticmethod
    def _get_class_name(classification: ThreatClassification) -> str:
        """Get CSS class name for threat classification."""
        class_map = {
            ThreatClassification.CRITICAL_RISK: "critical",
            ThreatClassification.HIGH_RISK: "high",
            ThreatClassification.MEDIUM_RISK: "medium",
            ThreatClassification.LOW_RISK: "low",
            ThreatClassification.HARMLESS: "harmless",
        }
        return class_map.get(classification, "default")

    @classmethod
    def _generate_class_defs(cls) -> List[str]:
        """Generate Mermaid class definitions for styling."""
        lines = []

        for classification, colors in cls.THREAT_COLORS.items():
            class_name = cls._get_class_name(classification)

            style = (
                f"fill:{colors['fill']},"
                f"stroke:{colors['stroke']},"
                f"stroke-width:{colors['stroke_width']},"
                f"color:{colors['color']}"
            )

            lines.append(f"    classDef {class_name} {style}")

        return lines


class ThreatReportGenerator:
    """
    Generates threat intelligence reports in markdown format.
    """

    @staticmethod
    def generate_executive_report(
        profiles: List[ThreatActorProfile],
        network_tracker: ThreatNetworkTracker,
        communities: Optional[Dict[int, int]] = None,
    ) -> str:
        """
        Generate executive summary report.

        Args:
            profiles: List of threat actor profiles
            network_tracker: Network tracker
            communities: Optional community detection results

        Returns:
            Markdown report
        """
        # Statistics
        total_actors = len(profiles)
        critical_actors = [p for p in profiles if p.threat_score >= 9.0]
        high_actors = [p for p in profiles if 7.0 <= p.threat_score < 9.0]
        network_stats = network_tracker.get_stats()

        # Generate report
        lines = [
            "# THREAT INTELLIGENCE REPORT",
            f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
            f"**Report ID:** TIR-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            "",
            "## Executive Summary",
            "",
            f"- **Total Actors Monitored:** {total_actors:,}",
            f"- **Critical Threat Actors (9-10):** {len(critical_actors)} ({len(critical_actors)/max(total_actors,1)*100:.1f}%)",
            f"- **High Threat Actors (7-8):** {len(high_actors)} ({len(high_actors)/max(total_actors,1)*100:.1f}%)",
            f"- **Total Interactions Tracked:** {network_stats.get('total_interactions', 0):,}",
        ]

        if communities:
            lines.append(f"- **Active Threat Networks:** {max(communities.values())+1} identified clusters")

        lines.extend([
            "",
            "## Top Threat Actors",
            "",
        ])

        # Sort by threat score
        sorted_profiles = sorted(profiles, key=lambda p: p.threat_score, reverse=True)

        # Add top 10 actors
        for i, profile in enumerate(sorted_profiles[:10], 1):
            lines.extend(ThreatReportGenerator._format_actor_section(i, profile, network_tracker))

        return "\n".join(lines)

    @staticmethod
    def _format_actor_section(
        rank: int,
        profile: ThreatActorProfile,
        network_tracker: ThreatNetworkTracker,
    ) -> List[str]:
        """Format an actor section in the report."""
        lines = [
            f"### {rank}. {profile.username or f'User_{profile.user_id}'} (Score: {profile.threat_score:.1f}, Confidence: {profile.confidence*100:.0f}%)",
            f"**Classification:** {profile.classification.value}",
            "",
            "**Indicators:**",
        ]

        # Indicators summary
        if profile.keyword_indicators:
            top_keywords = sorted(profile.keyword_indicators, key=lambda x: x.severity, reverse=True)[:3]
            keywords_str = ", ".join(k.value for k in top_keywords)
            lines.append(f"- {len(profile.keyword_indicators)} keyword matches: {keywords_str}")

        if profile.pattern_indicators:
            pattern_types = set(p.metadata.get("pattern_type", "unknown") for p in profile.pattern_indicators)
            lines.append(f"- {len(profile.pattern_indicators)} pattern matches: {', '.join(pattern_types)}")

        if profile.behavioral_flags:
            behavior_types = [f.flag_type for f in profile.behavioral_flags]
            lines.append(f"- {len(profile.behavioral_flags)} behavioral flags: {', '.join(behavior_types)}")

        # Network info
        associates = network_tracker.get_actor_associates(profile.user_id)
        lines.extend([
            "",
            "**Network:**",
            f"- Direct connections: {len(associates)}",
            f"- Network threat score: {profile.network_threat_score:.1f}",
        ])

        # Activity
        lines.extend([
            "",
            "**Activity:**",
            f"- First seen: {profile.first_seen.strftime('%Y-%m-%d') if profile.first_seen else 'Unknown'}",
            f"- Last seen: {profile.last_seen.strftime('%Y-%m-%d') if profile.last_seen else 'Unknown'}",
            f"- Message count: {profile.message_count}",
            f"- Active channels: {len(profile.channels)}",
        ])

        # Tags
        if profile.tags:
            lines.append(f"- Tags: {', '.join(profile.tags)}")

        # Recommended action
        if profile.threat_score >= 9.0:
            action = "🚨 CRITICAL - Immediate analyst review required"
        elif profile.threat_score >= 7.0:
            action = "⚠️ HIGH - Priority intelligence target"
        elif profile.threat_score >= 5.0:
            action = "📊 MEDIUM - Continued monitoring"
        else:
            action = "ℹ️ LOW - Background tracking"

        lines.extend([
            "",
            f"**Recommended Action:** {action}",
            "",
            "---",
            "",
        ])

        return lines


__all__ = [
    "MermaidGenerator",
    "ThreatReportGenerator",
]
