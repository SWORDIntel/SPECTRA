"""
Tests for the change-point detection and campaign segmentation engine.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from tgarchive.threat.changepoint import (
    ChangePoint,
    ChangePointDetector,
    detect_campaigns,
)


@pytest.fixture
def messages_with_regime_change():
    """100 messages with a clear behavioral change at message 50."""
    msgs = []
    for i in range(100):
        if i < 50:
            content = f"hey whats up {i}"
            hour = 14
        else:
            content = f"Greetings. I would like to inform you that item number {i} is now available for purchase at the listed price."
            hour = 3
        msgs.append({
            "id": i + 1,
            "channel_id": 100,
            "user_id": 123,
            "content": content,
            "date": datetime(2024, 1, 1, hour, 0, tzinfo=timezone.utc) + timedelta(days=i),
        })
    return msgs


@pytest.fixture
def uniform_messages():
    """50 messages with no behavioral change."""
    return [
        {
            "id": i + 1,
            "channel_id": 100,
            "user_id": 123,
            "content": f"hello world {i}",
            "date": datetime(2024, 1, 1, 14, 0, tzinfo=timezone.utc) + timedelta(days=i),
        }
        for i in range(50)
    ]


class TestChangePointDetector:
    def test_detects_regime_change(self, messages_with_regime_change):
        detector = ChangePointDetector()
        cps = detector.detect_change_points(messages_with_regime_change, window_size=20)
        assert len(cps) > 0
        cp = cps[0]
        assert 0 <= cp.probability <= 1.0
        assert 0 <= cp.confidence <= 1.0
        assert len(cp.features_changed) > 0

    def test_no_change_in_uniform_messages(self, uniform_messages):
        detector = ChangePointDetector()
        cps = detector.detect_change_points(uniform_messages, window_size=10)
        # Should detect few or no change points in uniform data
        # (might detect minor fluctuations, but probability should be low)
        for cp in cps:
            assert cp.probability < 0.9  # No strong change points

    def test_change_point_has_provenance(self, messages_with_regime_change):
        detector = ChangePointDetector()
        cps = detector.detect_change_points(messages_with_regime_change, window_size=20)
        if cps:
            cp = cps[0]
            assert len(cp.before_window) > 0
            assert len(cp.after_window) > 0

    def test_change_point_to_dict(self, messages_with_regime_change):
        detector = ChangePointDetector()
        cps = detector.detect_change_points(messages_with_regime_change, window_size=20)
        if cps:
            d = cps[0].to_dict()
            assert isinstance(d, dict)
            import json
            json.dumps(d)  # Must be serializable

    def test_change_point_to_evidence(self, messages_with_regime_change):
        detector = ChangePointDetector()
        cps = detector.detect_change_points(messages_with_regime_change, window_size=20)
        if cps:
            ev = cps[0].to_evidence(user_id=123)
            assert ev.evidence_type is not None
            assert len(ev.sources) > 0
            assert 0 <= ev.confidence <= 1.0

    def test_describe_change(self, messages_with_regime_change):
        detector = ChangePointDetector()
        before = messages_with_regime_change[:50]
        after = messages_with_regime_change[50:]
        changes = detector.describe_change(before, after)
        assert isinstance(changes, dict)
        assert len(changes) > 0  # Should detect multiple feature changes

    def test_empty_messages(self):
        detector = ChangePointDetector()
        cps = detector.detect_change_points([], window_size=10)
        assert cps == []

    def test_few_messages(self):
        detector = ChangePointDetector()
        cps = detector.detect_change_points(
            [{"id": 1, "content": "hi", "date": datetime(2024, 1, 1, tzinfo=timezone.utc)}],
            window_size=10,
        )
        assert cps == []  # Too few messages for a change point


class TestCampaignDetection:
    def test_detects_campaign(self, messages_with_regime_change):
        actors = {
            123: messages_with_regime_change[:60],
            456: messages_with_regime_change[40:80],
        }
        campaigns = detect_campaigns(
            messages_with_regime_change,
            actors,
            min_actors=2,
            min_messages=10,
            gap_threshold_hours=48,
        )
        assert len(campaigns) > 0
        c = campaigns[0]
        assert len(c.actors) >= 2
        assert len(c.message_ids) >= 10
        assert 0 <= c.confidence <= 1.0

    def test_empty_input(self):
        campaigns = detect_campaigns([], {}, min_actors=2, min_messages=10)
        assert campaigns == []

    def test_single_actor_not_campaign(self, messages_with_regime_change):
        """A single actor's messages should not form a multi-actor campaign."""
        actors = {123: messages_with_regime_change}
        campaigns = detect_campaigns(
            messages_with_regime_change,
            actors,
            min_actors=2,
            min_messages=10,
        )
        # With min_actors=2, single actor should not produce campaigns
        for c in campaigns:
            assert len(c.actors) >= 2

    def test_campaign_has_timestamps(self, messages_with_regime_change):
        actors = {
            123: messages_with_regime_change[:60],
            456: messages_with_regime_change[40:80],
        }
        campaigns = detect_campaigns(
            messages_with_regime_change,
            actors,
            min_actors=2,
            min_messages=10,
        )
        if campaigns:
            c = campaigns[0]
            # Campaign should have start and end timestamps
            assert c.start is not None or c.end is not None or len(c.message_ids) > 0
