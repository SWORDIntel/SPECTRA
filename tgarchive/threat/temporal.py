"""
Temporal Analysis for Threat Actor Tracking

Analyzes time-based patterns in threat actor behavior:
- Activity timeline analysis
- Burst detection (coordinated attacks)
- Sleep pattern analysis (timezone inference)
- Campaign periodicity detection
- Predictive activity forecasting

Author: SPECTRA Intelligence System
"""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import statistics

logger = logging.getLogger(__name__)

# Optional: numpy and scipy for advanced analysis
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


class TemporalAnalyzer:
    """
    Analyze temporal patterns in threat actor behavior.

    Provides insights into:
    - When actors are active
    - Coordinated campaigns
    - Timezone/location inference
    - Future activity prediction
    """

    def __init__(self):
        self.timezone_map = self._build_timezone_map()

    def _build_timezone_map(self) -> Dict[Tuple[int, int], str]:
        """
        Build mapping from peak hours to likely timezones.

        Maps (start_hour, end_hour) tuples to timezone names.
        """
        return {
            (9, 17): "UTC+0 (GMT, London)",
            (8, 16): "UTC-1 (Azores)",
            (7, 15): "UTC-2 (Brazil)",
            (10, 18): "UTC+1 (CET, Berlin)",
            (11, 19): "UTC+2 (EET, Cairo)",
            (12, 20): "UTC+3 (MSK, Moscow)",
            (13, 21): "UTC+4 (Dubai)",
            (14, 22): "UTC+5 (Pakistan)",
            (15, 23): "UTC+6 (Bangladesh)",
            (16, 0): "UTC+7 (Bangkok)",
            (17, 1): "UTC+8 (Beijing, Singapore)",
            (18, 2): "UTC+9 (Tokyo, Seoul)",
            (19, 3): "UTC+10 (Sydney)",
            (0, 8): "UTC-8 (PST, Los Angeles)",
            (1, 9): "UTC-7 (MST, Denver)",
            (2, 10): "UTC-6 (CST, Chicago)",
            (3, 11): "UTC-5 (EST, New York)"
        }

    def analyze_activity_patterns(
        self,
        messages: List[Dict]
    ) -> Dict[str, any]:
        """
        Analyze when an actor is active.

        Args:
            messages: List of message dicts with 'date' field (datetime objects)

        Returns:
            {
                "peak_hours": List[int],  # Hours of day (0-23)
                "peak_days": List[str],   # Days of week
                "inferred_timezone": str,
                "burst_periods": List[dict],
                "regularity_score": float,  # 0-10
                "total_messages": int,
                "first_seen": datetime,
                "last_seen": datetime,
                "active_days": int
            }
        """
        if not messages:
            return self._empty_analysis()

        # Extract dates
        dates = [msg['date'] for msg in messages if 'date' in msg]
        if not dates:
            return self._empty_analysis()

        # Hour distribution
        hour_counts = Counter(d.hour for d in dates)
        peak_hours = self._detect_peaks(hour_counts)

        # Day of week distribution
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_counts = Counter(day_names[d.weekday()] for d in dates)
        peak_days = [day for day, count in day_counts.most_common(3)]

        # Timezone inference
        inferred_tz = self._infer_timezone(peak_hours)

        # Burst detection
        bursts = self._detect_bursts(dates)

        # Regularity score
        regularity = self._calculate_regularity(dates)

        # Activity span
        first_seen = min(dates)
        last_seen = max(dates)
        active_days = len(set(d.date() for d in dates))

        return {
            "peak_hours": peak_hours,
            "peak_days": peak_days,
            "inferred_timezone": inferred_tz,
            "burst_periods": bursts,
            "regularity_score": regularity,
            "total_messages": len(messages),
            "first_seen": first_seen,
            "last_seen": last_seen,
            "active_days": active_days,
            "hour_distribution": dict(hour_counts),
            "day_distribution": dict(day_counts)
        }

    def _empty_analysis(self) -> Dict:
        """Return empty analysis structure."""
        return {
            "peak_hours": [],
            "peak_days": [],
            "inferred_timezone": "Unknown",
            "burst_periods": [],
            "regularity_score": 0.0,
            "total_messages": 0,
            "first_seen": None,
            "last_seen": None,
            "active_days": 0
        }

    def _detect_peaks(self, hour_counts: Counter, threshold: float = 0.7) -> List[int]:
        """
        Detect peak activity hours.

        Args:
            hour_counts: Counter of hours
            threshold: Fraction of max count to consider as peak

        Returns:
            List of peak hours
        """
        if not hour_counts:
            return []

        max_count = max(hour_counts.values())
        threshold_count = max_count * threshold

        peaks = [hour for hour, count in hour_counts.items() if count >= threshold_count]
        return sorted(peaks)

    def _infer_timezone(self, peak_hours: List[int]) -> str:
        """
        Infer timezone from peak activity hours.

        Assumes peak hours represent typical work hours (9-17) in local time.
        """
        if not peak_hours or len(peak_hours) < 2:
            return "Unknown (insufficient data)"

        # Find closest match to work hours
        start_hour = min(peak_hours)
        end_hour = max(peak_hours)

        # Look for approximate match
        for (tz_start, tz_end), tz_name in self.timezone_map.items():
            if abs(start_hour - tz_start) <= 2 and abs(end_hour - tz_end) <= 2:
                return tz_name

        return f"Unknown (peaks: {start_hour:02d}00-{end_hour:02d}00 UTC)"

    def _detect_bursts(
        self,
        dates: List[datetime],
        window_minutes: int = 60,
        burst_threshold: int = 10
    ) -> List[Dict]:
        """
        Detect burst activity periods.

        A burst is a period with unusually high message rate.

        Args:
            dates: List of message timestamps
            window_minutes: Time window to analyze
            burst_threshold: Min messages in window to consider as burst

        Returns:
            List of burst periods with metadata
        """
        if not dates:
            return []

        sorted_dates = sorted(dates)
        bursts = []
        i = 0

        while i < len(sorted_dates):
            window_start = sorted_dates[i]
            window_end = window_start + timedelta(minutes=window_minutes)

            # Count messages in window
            messages_in_window = 0
            j = i
            while j < len(sorted_dates) and sorted_dates[j] <= window_end:
                messages_in_window += 1
                j += 1

            # Check if burst
            if messages_in_window >= burst_threshold:
                intensity = messages_in_window / burst_threshold
                bursts.append({
                    "start": window_start,
                    "end": sorted_dates[j-1] if j > 0 else window_end,
                    "message_count": messages_in_window,
                    "intensity": round(intensity, 2),
                    "duration_minutes": (sorted_dates[j-1] - window_start).total_seconds() / 60
                })

                # Skip past this burst
                i = j
            else:
                i += 1

        return bursts

    def _calculate_regularity(self, dates: List[datetime]) -> float:
        """
        Calculate regularity score (0-10).

        Higher score = more regular/predictable activity patterns.

        Measures:
        - Consistency in activity times
        - Regularity of intervals between messages
        """
        if len(dates) < 3:
            return 0.0

        sorted_dates = sorted(dates)

        # Measure 1: Hour distribution entropy
        hour_counts = Counter(d.hour for d in sorted_dates)
        hour_entropy = self._calculate_entropy(list(hour_counts.values()))
        max_entropy = 4.58  # log2(24) for uniform distribution
        hour_consistency = 1.0 - (hour_entropy / max_entropy)

        # Measure 2: Interval regularity
        intervals = [(sorted_dates[i+1] - sorted_dates[i]).total_seconds()
                     for i in range(len(sorted_dates) - 1)]

        if intervals:
            mean_interval = statistics.mean(intervals)
            if mean_interval > 0:
                interval_cv = statistics.stdev(intervals) / mean_interval  # Coefficient of variation
                interval_regularity = max(0, 1.0 - min(interval_cv, 1.0))
            else:
                interval_regularity = 0.0
        else:
            interval_regularity = 0.0

        # Combined score (0-10 scale)
        regularity = (hour_consistency * 0.6 + interval_regularity * 0.4) * 10.0

        return round(regularity, 2)

    def _calculate_entropy(self, values: List[int]) -> float:
        """Calculate Shannon entropy."""
        if not values:
            return 0.0

        total = sum(values)
        if total == 0:
            return 0.0

        import math
        entropy = 0.0
        for v in values:
            if v > 0:
                p = v / total
                entropy -= p * math.log2(p)

        return entropy

    def detect_coordinated_campaigns(
        self,
        actor_messages: Dict[int, List[Dict]],
        time_window_minutes: int = 30,
        min_actors: int = 3
    ) -> List[Dict]:
        """
        Detect coordinated activity among multiple actors.

        Identifies time windows where multiple actors are simultaneously active.

        Args:
            actor_messages: Dict mapping user_id to list of their messages
            time_window_minutes: Time window for coordination
            min_actors: Minimum actors needed to consider as coordinated

        Returns:
            List of coordinated campaign periods
        """
        # Collect all messages with actor IDs
        all_messages = []
        for user_id, messages in actor_messages.items():
            for msg in messages:
                all_messages.append({
                    "user_id": user_id,
                    "date": msg['date']
                })

        all_messages.sort(key=lambda x: x['date'])

        campaigns = []
        i = 0

        while i < len(all_messages):
            window_start = all_messages[i]['date']
            window_end = window_start + timedelta(minutes=time_window_minutes)

            # Find all messages in window
            messages_in_window = []
            j = i
            while j < len(all_messages) and all_messages[j]['date'] <= window_end:
                messages_in_window.append(all_messages[j])
                j += 1

            # Count unique actors
            unique_actors = set(m['user_id'] for m in messages_in_window)

            # Check if coordinated
            if len(unique_actors) >= min_actors:
                campaigns.append({
                    "start": window_start,
                    "end": messages_in_window[-1]['date'],
                    "actor_count": len(unique_actors),
                    "message_count": len(messages_in_window),
                    "actors": list(unique_actors),
                    "coordination_score": len(unique_actors) / len(messages_in_window) if messages_in_window else 0
                })

                i = j
            else:
                i += 1

        return campaigns

    def predict_next_activity(
        self,
        messages: List[Dict],
        forecast_hours: int = 24
    ) -> Dict:
        """
        Predict when actor will be active next.

        Uses historical patterns to forecast future activity windows.

        Args:
            messages: Historical messages
            forecast_hours: Hours to forecast into future

        Returns:
            {
                "likely_active_hours": List[int],  # Hours with high probability
                "probability_by_hour": Dict[int, float],
                "confidence": float  # 0-1
            }
        """
        if not messages:
            return {
                "likely_active_hours": [],
                "probability_by_hour": {},
                "confidence": 0.0
            }

        # Analyze historical hour distribution
        dates = [msg['date'] for msg in messages if 'date' in msg]
        hour_counts = Counter(d.hour for d in dates)

        # Calculate probabilities
        total = sum(hour_counts.values())
        probability_by_hour = {
            hour: count / total
            for hour, count in hour_counts.items()
        }

        # Identify likely hours (prob > average)
        avg_prob = 1.0 / 24  # Uniform distribution baseline
        likely_hours = [
            hour for hour, prob in probability_by_hour.items()
            if prob > avg_prob * 1.5  # 50% above baseline
        ]

        # Confidence based on sample size and regularity
        confidence = min(1.0, len(messages) / 100) * 0.7  # Sample size factor
        patterns = self.analyze_activity_patterns(messages)
        confidence += (patterns['regularity_score'] / 10) * 0.3  # Regularity factor

        return {
            "likely_active_hours": sorted(likely_hours),
            "probability_by_hour": probability_by_hour,
            "confidence": round(confidence, 3)
        }

    def generate_timeline_gantt(
        self,
        actor_messages: Dict[int, List[Dict]],
        actor_names: Optional[Dict[int, str]] = None
    ) -> str:
        """
        Generate Mermaid Gantt chart of actor activity timelines.

        Args:
            actor_messages: Dict mapping user_id to messages
            actor_names: Optional dict mapping user_id to display name

        Returns:
            Mermaid Gantt diagram
        """
        lines = [
            "gantt",
            "    title Threat Actor Activity Timeline",
            "    dateFormat YYYY-MM-DD",
            "    section Actors"
        ]

        for user_id, messages in sorted(actor_messages.items()):
            if not messages:
                continue

            dates = [msg['date'] for msg in messages if 'date' in msg]
            if not dates:
                continue

            first = min(dates)
            last = max(dates)
            duration = (last - first).days + 1

            name = actor_names.get(user_id, f"Actor_{user_id}") if actor_names else f"Actor_{user_id}"

            # Determine criticality class based on message count
            if len(messages) > 100:
                crit_class = "crit"
            elif len(messages) > 50:
                crit_class = "active"
            else:
                crit_class = ""

            task_id = f"a{user_id}"
            lines.append(
                f"    {name} ({len(messages)} msgs) :{crit_class}, {task_id}, "
                f"{first.strftime('%Y-%m-%d')}, {duration}d"
            )

        return "\n".join(lines)


# Example usage
if __name__ == "__main__":
    print("=== Temporal Analysis Demo ===\n")

    # Create sample data
    from datetime import datetime

    messages = [
        {"date": datetime(2024, 6, 15, 9, 30), "text": "msg1"},
        {"date": datetime(2024, 6, 15, 10, 15), "text": "msg2"},
        {"date": datetime(2024, 6, 15, 14, 45), "text": "msg3"},
        {"date": datetime(2024, 6, 16, 9, 20), "text": "msg4"},
        {"date": datetime(2024, 6, 16, 10, 30), "text": "msg5"},
        {"date": datetime(2024, 6, 17, 11, 0), "text": "msg6"},
    ]

    analyzer = TemporalAnalyzer()

    # Analyze patterns
    patterns = analyzer.analyze_activity_patterns(messages)

    print("Activity Patterns:")
    print(f"  Peak hours: {patterns['peak_hours']}")
    print(f"  Peak days: {patterns['peak_days']}")
    print(f"  Inferred timezone: {patterns['inferred_timezone']}")
    print(f"  Regularity score: {patterns['regularity_score']}/10")
    print(f"  Active days: {patterns['active_days']}")
    print()

    # Predict next activity
    prediction = analyzer.predict_next_activity(messages)
    print("Activity Prediction:")
    print(f"  Likely active hours: {prediction['likely_active_hours']}")
    print(f"  Confidence: {prediction['confidence']:.1%}")
    print()

    print("=== Temporal analysis demo complete! ===")
