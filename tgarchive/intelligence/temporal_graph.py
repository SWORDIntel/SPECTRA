"""
SPECTRA Temporal Behavior Graph
===============================

Tracks temporal activity patterns for entities and derives behavioral
signals: activity patterns, timezone inference, and change-point detection.

This module integrates with the entity resolution v2 pipeline by providing
the *temporal behavior* evidence source (source 6) with richer data than
the simple hour-of-day comparison in :mod:`entity_resolver_v2`.

Key capabilities:

* **Activity patterns** — hour-of-day and day-of-week distributions.
* **Timezone inference** — estimates the UTC offset of an entity based on
  the hour-of-day distribution of its activity.
* **Behavioral change detection** — simple statistical change-point detection
  on activity rate over time.
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"

# Valid event types in the temporal graph.
EVENT_TYPES = frozenset(
    {
        "message",
        "join",
        "leave",
        "name_change",
        "username_change",
    }
)


# ─── Data model ──────────────────────────────────────────────────────────────


@dataclass
class TemporalEvent:
    """A single temporal event for an entity.

    Attributes:
        entity_id: Canonical ID of the entity (e.g. ``telegram:user:123``).
        event_type: One of ``EVENT_TYPES``.
        timestamp: When the event occurred (timezone-aware).
        channel_id: Optional channel/context where the event occurred.
        metadata: Extra structured context.
    """

    entity_id: str
    event_type: str
    timestamp: datetime
    channel_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(
                f"invalid event_type {self.event_type!r}; "
                f"expected one of {sorted(EVENT_TYPES)}"
            )
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)


@dataclass
class ActivityPattern:
    """Aggregated activity pattern for an entity.

    Attributes:
        entity_id: Canonical ID of the entity.
        total_events: Total number of events recorded.
        hour_histogram: 24-element list — count of events per hour-of-day (UTC).
        day_histogram: 7-element list — count of events per day-of-week (0=Mon).
        peak_hours: Hours with the highest activity (sorted by count desc).
        peak_days: Days with the highest activity (sorted by count desc).
        first_seen: Timestamp of the earliest event.
        last_seen: Timestamp of the latest event.
        channels: Set of channel IDs where the entity was active.
        estimated_timezone: Estimated UTC offset in hours, if inferable.
    """

    entity_id: str
    total_events: int = 0
    hour_histogram: List[int] = field(default_factory=lambda: [0] * 24)
    day_histogram: List[int] = field(default_factory=lambda: [0] * 7)
    peak_hours: List[int] = field(default_factory=list)
    peak_days: List[int] = field(default_factory=list)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    channels: List[int] = field(default_factory=list)
    estimated_timezone: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "total_events": self.total_events,
            "hour_histogram": self.hour_histogram,
            "day_histogram": self.day_histogram,
            "peak_hours": self.peak_hours,
            "peak_days": self.peak_days,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "channels": self.channels,
            "estimated_timezone": self.estimated_timezone,
        }


@dataclass
class ChangePoint:
    """A detected behavioral change point.

    Attributes:
        entity_id: Canonical ID of the entity.
        timestamp: Estimated time of the change.
        metric: Name of the metric that changed (e.g. ``activity_rate``).
        before_value: Mean value of the metric before the change.
        after_value: Mean value of the metric after the change.
        magnitude: Absolute difference ``after_value - before_value``.
        significance: Relative magnitude of the change (0-1 scale).
    """

    entity_id: str
    timestamp: datetime
    metric: str
    before_value: float
    after_value: float
    magnitude: float
    significance: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "timestamp": self.timestamp.isoformat(),
            "metric": self.metric,
            "before_value": self.before_value,
            "after_value": self.after_value,
            "magnitude": self.magnitude,
            "significance": self.significance,
        }


# ─── TemporalGraph ───────────────────────────────────────────────────────────


class TemporalGraph:
    """Temporal behavior graph for entities.

    Stores temporal events and derives activity patterns, timezone estimates,
    and behavioral change points.

    Usage::

        graph = TemporalGraph()
        graph.add_event(TemporalEvent(
            entity_id="telegram:user:123",
            event_type="message",
            timestamp=datetime(2024, 3, 15, 14, 30, tzinfo=timezone.utc),
            channel_id=100,
        ))
        pattern = graph.get_activity_pattern("telegram:user:123")
        tz = graph.infer_timezone("telegram:user:123")
        changes = graph.detect_behavioral_change("telegram:user:123")
    """

    def __init__(self) -> None:
        self._events: Dict[str, List[TemporalEvent]] = {}

    # ── public API ───────────────────────────────────────────────────────────

    def add_event(self, event: TemporalEvent) -> None:
        """Add a temporal event to the graph."""
        self._events.setdefault(event.entity_id, []).append(event)

    def get_events(self, entity_id: str) -> List[TemporalEvent]:
        """Return all events for an entity, sorted chronologically."""
        events = self._events.get(entity_id, [])
        return sorted(events, key=lambda e: e.timestamp)

    def get_activity_pattern(self, entity_id: str) -> ActivityPattern:
        """Compute the activity pattern for an entity.

        Aggregates all events into hour-of-day and day-of-week histograms,
        identifies peak activity periods, and estimates the timezone.
        """
        events = self.get_events(entity_id)
        pattern = ActivityPattern(entity_id=entity_id)
        pattern.total_events = len(events)
        if not events:
            return pattern

        channels: set[int] = set()
        for ev in events:
            hour = ev.timestamp.hour
            dow = ev.timestamp.weekday()
            pattern.hour_histogram[hour] += 1
            pattern.day_histogram[dow] += 1
            if ev.channel_id is not None:
                channels.add(ev.channel_id)

        pattern.channels = sorted(channels)
        pattern.first_seen = events[0].timestamp
        pattern.last_seen = events[-1].timestamp

        # Peak hours: top 3 hours by count (or fewer if ties).
        pattern.peak_hours = self._top_indices(pattern.hour_histogram, 3)
        pattern.peak_days = self._top_indices(pattern.day_histogram, 3)

        # Timezone estimate.
        pattern.estimated_timezone = self.infer_timezone(entity_id)
        return pattern

    def infer_timezone(self, entity_id: str) -> Optional[float]:
        """Estimate the timezone offset (in hours from UTC) for an entity.

        Uses the hour-of-day distribution to find the most likely UTC offset.
        The intuition: a person's local "active hours" are typically 09:00–22:00.
        We find the offset that, when applied, maximizes the fraction of
        activity falling within typical waking hours.

        Args:
            entity_id: Canonical ID of the entity.

        Returns:
            Estimated UTC offset in hours (e.g. ``-5.0`` for EST, ``+3.0``
            for Moscow), or ``None`` if there is insufficient data.
        """
        events = self.get_events(entity_id)
        if len(events) < 5:
            return None

        hour_hist = [0] * 24
        for ev in events:
            hour_hist[ev.timestamp.hour] += 1

        total = sum(hour_hist)
        if total == 0:
            return None

        # Typical waking hours: 09:00 to 22:00 local (13 hours).
        waking_hours = set(range(9, 22))

        best_offset = 0.0
        best_score = -1.0
        for offset in range(-12, 13):
            score = 0.0
            for hour in range(24):
                local_hour = (hour + offset) % 24
                if local_hour in waking_hours:
                    score += hour_hist[hour]
            score /= total
            if score > best_score:
                best_score = score
                best_offset = float(offset)

        # Only return if the best offset captures a meaningful majority.
        if best_score < 0.5:
            return None
        return best_offset

    def detect_behavioral_change(
        self,
        entity_id: str,
        window_days: int = 30,
    ) -> List[ChangePoint]:
        """Detect behavioral change points for an entity.

        Uses a simple statistical change-point detection on the daily activity
        rate.  The algorithm slides a window across the timeline and flags
        points where the mean activity rate before and after differs
        significantly (beyond a threshold based on the standard deviation).

        Args:
            entity_id: Canonical ID of the entity.
            window_days: Size of the sliding window in days.

        Returns:
            A list of ``ChangePoint`` objects, sorted chronologically.
        """
        events = self.get_events(entity_id)
        if len(events) < 10:
            return []

        # Build a daily activity count series.
        daily_counts: Dict[str, int] = {}
        dates: List[datetime] = []
        for ev in events:
            day_key = ev.timestamp.strftime("%Y-%m-%d")
            if day_key not in daily_counts:
                daily_counts[day_key] = 0
                dates.append(
                    datetime(
                        ev.timestamp.year,
                        ev.timestamp.month,
                        ev.timestamp.day,
                        tzinfo=timezone.utc,
                    )
                )
            daily_counts[day_key] += 1

        dates.sort()
        series = [daily_counts[d.strftime("%Y-%m-%d")] for d in dates]
        if len(series) < max(window_days * 2, 4):
            return []

        # Slide a window and detect points where the mean changes significantly.
        change_points: List[ChangePoint] = []
        half = max(window_days, 1)

        for i in range(half, len(series) - half):
            before = series[i - half : i]
            after = series[i : i + half]
            before_mean = statistics.mean(before)
            after_mean = statistics.mean(after)
            before_std = statistics.stdev(before) if len(before) > 1 else 0.0
            after_std = statistics.stdev(after) if len(after) > 1 else 0.0

            magnitude = after_mean - before_mean
            pooled_std = math.sqrt(
                (before_std ** 2 + after_std ** 2) / 2.0
            ) if (before_std + after_std) > 0 else 1.0

            # Significance: normalized magnitude (Cohen's d-like).
            significance = min(1.0, abs(magnitude) / (pooled_std + 1e-6))

            # Only flag significant changes (effect size > 0.5).
            if significance > 0.5 and abs(magnitude) >= 1.0:
                change_points.append(
                    ChangePoint(
                        entity_id=entity_id,
                        timestamp=dates[i],
                        metric="activity_rate",
                        before_value=before_mean,
                        after_value=after_mean,
                        magnitude=magnitude,
                        significance=significance,
                    )
                )

        # Deduplicate: remove change points within the same window that
        # point to the same direction.
        deduped: List[ChangePoint] = []
        for cp in change_points:
            if deduped:
                last = deduped[-1]
                delta = (cp.timestamp - last.timestamp).days
                same_dir = (cp.magnitude > 0) == (last.magnitude > 0)
                if delta < half and same_dir:
                    # Keep the more significant one.
                    if cp.significance > last.significance:
                        deduped[-1] = cp
                    continue
            deduped.append(cp)

        return deduped

    @property
    def entity_count(self) -> int:
        """Number of entities with recorded events."""
        return len(self._events)

    @property
    def event_count(self) -> int:
        """Total number of events across all entities."""
        return sum(len(v) for v in self._events.values())

    # ── internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _top_indices(histogram: List[int], top_n: int) -> List[int]:
        """Return the indices of the top-N values in a histogram."""
        indexed = sorted(
            enumerate(histogram), key=lambda x: x[1], reverse=True
        )
        return [idx for idx, val in indexed[:top_n] if val > 0]


__all__ = [
    "TemporalEvent",
    "ActivityPattern",
    "ChangePoint",
    "TemporalGraph",
    "EVENT_TYPES",
    "SCHEMA_VERSION",
]
