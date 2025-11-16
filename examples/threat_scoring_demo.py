#!/usr/bin/env python3
"""
SPECTRA Threat Scoring System Demonstration
============================================
Demonstrates the advanced threat scoring and network analysis capabilities.

Features demonstrated:
1. Threat indicator detection
2. Actor profiling and scoring (1-10 scale)
3. Network relationship tracking
4. Mermaid visualization generation
5. Threat intelligence reports
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tgarchive.threat.indicators import ThreatIndicatorDetector
from tgarchive.threat.scoring import ThreatProfiler
from tgarchive.threat.network import ThreatNetworkTracker, InteractionType
from tgarchive.threat.visualization import MermaidGenerator, ThreatReportGenerator


# ============================================================================
# EXAMPLE DATA - Simulated Threat Actors
# ============================================================================

# Example messages from various threat actors
EXAMPLE_MESSAGES = [
    # Critical Threat Actor (Nation-State)
    {
        "user_id": 1001,
        "username": "apt_actor_001",
        "messages": [
            {"id": 1, "content": "New APT29 zero-day targeting government infrastructure. CVE-2024-1234 confirmed working.", "date": "2024-12-01T10:00:00Z", "channel_id": 101},
            {"id": 2, "content": "Cozy Bear operation successful. Remote code execution achieved on multiple targets.", "date": "2024-12-05T14:30:00Z", "channel_id": 101},
            {"id": 3, "content": "State-sponsored campaign continues. New C2 infrastructure deployed at 45.67.89.123", "date": "2024-12-10T09:15:00Z", "channel_id": 101},
            {"id": 4, "content": "Weaponized exploit ready for deployment. PGP-encrypted payload available via tor hidden service.", "date": "2024-12-15T16:45:00Z", "channel_id": 102},
        ]
    },

    # High Threat Actor (Ransomware Operator)
    {
        "user_id": 1002,
        "username": "crypto_locker_pro",
        "messages": [
            {"id": 5, "content": "Latest ransomware variant ready. Bitcoin payment to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa for decryption key.", "date": "2024-12-02T11:00:00Z", "channel_id": 103},
            {"id": 6, "content": "Targeting healthcare sector. Backdoor installed. Encryption begins tonight.", "date": "2024-12-06T20:00:00Z", "channel_id": 103},
            {"id": 7, "content": "Payment received. Monero address: 4AdUndXHHZ6cfufTMvppY6JwXNouMBzSkbLYfpAV5Usx3skxNgYeYTRj5UzqtReoS44qo9mtmXCqY45DJ852K5Jv2684Rge", "date": "2024-12-08T15:30:00Z", "channel_id": 103},
            {"id": 8, "content": "Join our darknet market: ransomware-market.onion for tools and services.", "date": "2024-12-12T18:00:00Z", "channel_id": 104},
        ]
    },

    # Medium-High Threat (Advanced Hacker)
    {
        "user_id": 1003,
        "username": "grey_hat_researcher",
        "messages": [
            {"id": 9, "content": "Found SQL injection vulnerability in major e-commerce site. CVE-2024-5678.", "date": "2024-12-03T12:00:00Z", "channel_id": 105},
            {"id": 10, "content": "Using metasploit to test penetration. Buffer overflow confirmed in legacy system.", "date": "2024-12-07T14:00:00Z", "channel_id": 105},
            {"id": 11, "content": "XSS vulnerability allows credential theft. PoC code: <script>alert('pwned')</script>", "date": "2024-12-11T10:30:00Z", "channel_id": 105},
            {"id": 12, "content": "Nmap scan results show 15 open ports. VPN access via bulletproof hosting provider.", "date": "2024-12-14T16:00:00Z", "channel_id": 106},
        ]
    },

    # Medium Threat (Security Researcher)
    {
        "user_id": 1004,
        "username": "security_pro_2024",
        "messages": [
            {"id": 13, "content": "Participating in CTF challenge this weekend. Focus on reverse engineering and cryptography.", "date": "2024-12-04T09:00:00Z", "channel_id": 107},
            {"id": 14, "content": "Bug bounty submission: vulnerability research on web application firewall bypass.", "date": "2024-12-08T11:00:00Z", "channel_id": 107},
            {"id": 15, "content": "Red team exercise successful. Using Burp Suite for security audit.", "date": "2024-12-12T13:30:00Z", "channel_id": 107},
            {"id": 16, "content": "Responsible disclosure process initiated. Waiting for security patch from vendor.", "date": "2024-12-16T15:00:00Z", "channel_id": 107},
        ]
    },

    # Low Threat (IT Professional)
    {
        "user_id": 1005,
        "username": "it_admin_bob",
        "messages": [
            {"id": 17, "content": "Implementing new firewall rules for the office network. Cybersecurity best practices.", "date": "2024-12-05T08:00:00Z", "channel_id": 108},
            {"id": 18, "content": "Antivirus update deployed across all endpoints. Information security training next week.", "date": "2024-12-09T10:00:00Z", "channel_id": 108},
            {"id": 19, "content": "GDPR compliance audit completed. Security awareness campaign successful.", "date": "2024-12-13T14:00:00Z", "channel_id": 108},
        ]
    },

    # Harmless (General User)
    {
        "user_id": 1006,
        "username": "casual_user_123",
        "messages": [
            {"id": 20, "content": "Anyone know good tutorials for learning Python programming?", "date": "2024-12-06T12:00:00Z", "channel_id": 109},
            {"id": 21, "content": "Just finished setting up my home network. WiFi is finally working!", "date": "2024-12-10T15:00:00Z", "channel_id": 109},
            {"id": 22, "content": "Looking for recommendations on laptop security software.", "date": "2024-12-14T17:00:00Z", "channel_id": 109},
        ]
    },
]

# Example interactions (network relationships)
EXAMPLE_INTERACTIONS = [
    # APT actor coordinates with ransomware operator
    {"source": 1001, "target": 1002, "type": InteractionType.DIRECT_REPLY, "date": "2024-12-03T10:00:00Z", "channel": 101},
    {"source": 1001, "target": 1002, "type": InteractionType.MENTION, "date": "2024-12-05T11:00:00Z", "channel": 101},
    {"source": 1002, "target": 1001, "type": InteractionType.DIRECT_REPLY, "date": "2024-12-06T12:00:00Z", "channel": 103},
    {"source": 1001, "target": 1002, "type": InteractionType.FORWARDED, "date": "2024-12-08T13:00:00Z", "channel": 102},
    {"source": 1001, "target": 1002, "type": InteractionType.SAME_THREAD, "date": "2024-12-10T14:00:00Z", "channel": 101},

    # Ransomware operator interacts with grey hat
    {"source": 1002, "target": 1003, "type": InteractionType.MENTION, "date": "2024-12-04T09:00:00Z", "channel": 103},
    {"source": 1003, "target": 1002, "type": InteractionType.DIRECT_REPLY, "date": "2024-12-07T10:00:00Z", "channel": 105},
    {"source": 1002, "target": 1003, "type": InteractionType.SAME_THREAD, "date": "2024-12-09T11:00:00Z", "channel": 103},

    # Grey hat interacts with security researcher
    {"source": 1003, "target": 1004, "type": InteractionType.MENTION, "date": "2024-12-05T08:00:00Z", "channel": 105},
    {"source": 1004, "target": 1003, "type": InteractionType.DIRECT_REPLY, "date": "2024-12-08T09:00:00Z", "channel": 107},
    {"source": 1003, "target": 1004, "type": InteractionType.SAME_CHANNEL, "date": "2024-12-11T10:00:00Z", "channel": 105},

    # Security researcher interacts with IT admin
    {"source": 1004, "target": 1005, "type": InteractionType.SAME_CHANNEL, "date": "2024-12-06T14:00:00Z", "channel": 107},
    {"source": 1005, "target": 1004, "type": InteractionType.MENTION, "date": "2024-12-10T15:00:00Z", "channel": 108},

    # IT admin interacts with casual user
    {"source": 1005, "target": 1006, "type": InteractionType.DIRECT_REPLY, "date": "2024-12-07T16:00:00Z", "channel": 108},
    {"source": 1006, "target": 1005, "type": InteractionType.SAME_CHANNEL, "date": "2024-12-11T17:00:00Z", "channel": 109},
]


# ============================================================================
# DEMONSTRATION FUNCTIONS
# ============================================================================

def demo_threat_detection():
    """Demonstrate threat indicator detection."""
    print("\n" + "=" * 70)
    print("THREAT INDICATOR DETECTION DEMO")
    print("=" * 70)

    detector = ThreatIndicatorDetector()

    print("\n1. Analyzing messages for threat indicators...\n")

    for actor_data in EXAMPLE_MESSAGES[:3]:  # Show first 3 actors
        print(f"\n--- Actor: {actor_data['username']} (ID: {actor_data['user_id']}) ---")

        all_indicators = []
        for msg in actor_data['messages']:
            indicators = detector.detect_indicators(msg['content'])
            all_indicators.extend(indicators)

        # Get stats
        stats = detector.get_stats(all_indicators)

        print(f"Total indicators detected: {stats['total_indicators']}")
        print(f"By level: {stats['by_level']}")
        print(f"By type: {stats['by_type']}")
        print(f"Total severity: {stats['total_severity']:.1f}")

        # Show top indicators
        if all_indicators:
            print(f"\nTop indicators:")
            for i, indicator in enumerate(sorted(all_indicators, key=lambda x: x.severity, reverse=True)[:3], 1):
                print(f"  {i}. [{indicator.level.value.upper()}] {indicator.value} (severity: {indicator.severity})")


def demo_actor_profiling():
    """Demonstrate actor profiling and threat scoring."""
    print("\n" + "=" * 70)
    print("ACTOR PROFILING & THREAT SCORING DEMO")
    print("=" * 70)

    detector = ThreatIndicatorDetector()
    profiler = ThreatProfiler()

    print("\n2. Creating threat actor profiles with scores (1-10 scale)...\n")

    profiles = []

    for actor_data in EXAMPLE_MESSAGES:
        user_id = actor_data['user_id']
        username = actor_data['username']
        messages = actor_data['messages']

        # Detect all indicators
        keyword_indicators = []
        pattern_indicators = []

        for msg in messages:
            indicators = detector.detect_indicators(msg['content'])
            for ind in indicators:
                if ind.type.value == "keyword":
                    keyword_indicators.append(ind)
                elif ind.type.value == "pattern":
                    pattern_indicators.append(ind)

        # Create profile
        profile = profiler.create_profile(
            user_id=user_id,
            username=username,
            keyword_indicators=keyword_indicators,
            pattern_indicators=pattern_indicators,
            messages=messages,
        )

        profiles.append(profile)

        # Display profile
        print(f"Actor: {profile.username}")
        print(f"  Threat Score: {profile.threat_score:.1f}/10")
        print(f"  Confidence: {profile.confidence*100:.0f}%")
        print(f"  Classification: {profile.classification.value}")
        print(f"  Indicators: {len(profile.keyword_indicators)} keywords, {len(profile.pattern_indicators)} patterns, {len(profile.behavioral_flags)} behavioral")
        print(f"  Tags: {', '.join(profile.tags) if profile.tags else 'None'}")
        print()

    return profiles


def demo_network_tracking(profiles):
    """Demonstrate network relationship tracking."""
    print("\n" + "=" * 70)
    print("NETWORK RELATIONSHIP TRACKING DEMO")
    print("=" * 70)

    network_tracker = ThreatNetworkTracker()

    print("\n3. Building threat actor network from interactions...\n")

    # Add all interactions
    for interaction in EXAMPLE_INTERACTIONS:
        network_tracker.add_interaction(
            source_id=interaction["source"],
            target_id=interaction["target"],
            interaction_type=interaction["type"],
            timestamp=datetime.fromisoformat(interaction["date"]),
            channel_id=interaction["channel"],
        )

    # Get network statistics
    stats = network_tracker.get_stats()
    print(f"Network Statistics:")
    print(f"  Total interactions: {stats['total_interactions']}")
    print(f"  Total relationships: {stats['total_relationships']}")
    print(f"  Total actors: {stats['total_actors']}")

    # Calculate network threat scores
    actor_threat_scores = {p.user_id: p.threat_score for p in profiles}

    print(f"\n4. Calculating network-based threat scores (association analysis)...\n")

    for profile in profiles:
        network_score = network_tracker.calculate_network_threat_score(
            user_id=profile.user_id,
            actor_threat_scores=actor_threat_scores,
        )

        associates = network_tracker.get_actor_associates(profile.user_id)

        print(f"{profile.username}:")
        print(f"  Direct associates: {len(associates)}")
        print(f"  Network threat score: {network_score:.1f}/5.0")

        if associates:
            print(f"  Top associate: User {associates[0][0]} ({associates[0][1].interaction_count} interactions)")
        print()

        # Update profile with network score
        profile.network_threat_score = network_score
        profile.associate_count = len(associates)

    return network_tracker


def demo_visualization(profiles, network_tracker):
    """Demonstrate Mermaid visualization generation."""
    print("\n" + "=" * 70)
    print("MERMAID VISUALIZATION GENERATION DEMO")
    print("=" * 70)

    print("\n5. Generating Mermaid network diagram...\n")

    # Generate network graph
    mermaid_graph = MermaidGenerator.generate_network_graph(
        profiles=profiles,
        network_tracker=network_tracker,
        max_nodes=10,
        min_interactions=1,
        title="Threat Actor Network Map",
    )

    print("Network Graph (Mermaid):")
    print(mermaid_graph)
    print()

    # Generate timeline
    print("\n6. Generating activity timeline...\n")

    mermaid_timeline = MermaidGenerator.generate_timeline(
        profiles=profiles,
        title="Threat Actor Activity Timeline",
    )

    print("Activity Timeline (Mermaid):")
    print(mermaid_timeline)
    print()

    # Save visualizations
    output_dir = Path("./threat_analysis_output")
    output_dir.mkdir(exist_ok=True)

    graph_file = output_dir / "threat_network.md"
    graph_file.write_text(mermaid_graph)
    print(f"✓ Network graph saved to: {graph_file}")

    timeline_file = output_dir / "threat_timeline.md"
    timeline_file.write_text(mermaid_timeline)
    print(f"✓ Timeline saved to: {timeline_file}")


def demo_threat_report(profiles, network_tracker):
    """Demonstrate threat intelligence report generation."""
    print("\n" + "=" * 70)
    print("THREAT INTELLIGENCE REPORT GENERATION DEMO")
    print("=" * 70)

    print("\n7. Generating comprehensive threat intelligence report...\n")

    # Generate report
    report = ThreatReportGenerator.generate_executive_report(
        profiles=profiles,
        network_tracker=network_tracker,
    )

    print(report)

    # Save report
    output_dir = Path("./threat_analysis_output")
    output_dir.mkdir(exist_ok=True)

    report_file = output_dir / "threat_intelligence_report.md"
    report_file.write_text(report)
    print(f"\n✓ Full report saved to: {report_file}")


def main():
    """Run all demonstrations."""
    print("\n" + "=" * 70)
    print("SPECTRA ADVANCED THREAT SCORING SYSTEM - DEMONSTRATION")
    print("=" * 70)
    print("\nThis demo shows how the threat scoring system:")
    print("• Detects threat indicators (keywords, patterns, behaviors)")
    print("• Scores actors on a 1-10 scale (1=harmless, 10=nation-state)")
    print("• Tracks network relationships (who interacts with whom)")
    print("• Generates visualizations (Mermaid diagrams)")
    print("• Creates intelligence reports")

    # Run demonstrations
    demo_threat_detection()

    profiles = demo_actor_profiling()

    network_tracker = demo_network_tracking(profiles)

    demo_visualization(profiles, network_tracker)

    demo_threat_report(profiles, network_tracker)

    print("\n" + "=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70)
    print("\nOutput files created in ./threat_analysis_output/:")
    print("  • threat_network.md - Network diagram (open in Mermaid viewer)")
    print("  • threat_timeline.md - Activity timeline")
    print("  • threat_intelligence_report.md - Full intelligence report")
    print("\nTo view Mermaid diagrams:")
    print("  • GitHub/GitLab (native support)")
    print("  • VS Code (Markdown Preview Mermaid Support extension)")
    print("  • https://mermaid.live/ (online editor)")
    print("\nNext steps:")
    print("  • Integrate with your SPECTRA database")
    print("  • Set up automated scoring pipeline")
    print("  • Configure alerting for high-threat actors")
    print("  • Deploy to production monitoring")


if __name__ == "__main__":
    main()
