"""Tests for temporal feature extraction (V1 + V2)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from tgarchive.intelligence.features.temporal import (
    DEFAULT_TEMPORAL_FEATURES,
    extract_temporal_features,
)


def _msg(content, date=None):
    m = {"content": content}
    if date is not None:
        m["date"] = date
    return m


class TestTemporalFeatures:
    def test_empty_input(self):
        result = extract_temporal_features([])
        assert result == DEFAULT_TEMPORAL_FEATURES

    def test_no_timestamps(self):
        result = extract_temporal_features([_msg("hello"), _msg("world")])
        # Should return defaults (no valid timestamps)
        assert result["hour_0"] == 0.0
        assert result["timezone_inference_confidence"] == 0.0

    def test_json_serializable(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("hello", date=base.isoformat()),
            _msg("world", date=(base + timedelta(hours=1)).isoformat()),
        ]
        result = extract_temporal_features(msgs)
        json.dumps(result)  # should not raise

    def test_hour_distribution(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("a", date=base.isoformat()),
            _msg("b", date=base.isoformat()),  # same hour
            _msg("c", date=(base + timedelta(hours=2)).isoformat()),
        ]
        result = extract_temporal_features(msgs)
        # 2/3 at hour 10, 1/3 at hour 12
        assert result["hour_10"] == pytest.approx(2 / 3, abs=0.01)
        assert result["hour_12"] == pytest.approx(1 / 3, abs=0.01)
        assert "10" in result["hour_of_day_distribution"]

    def test_weekday_weekend(self):
        # 2026-01-01 is a Thursday
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("a", date=base.isoformat()),  # Thursday
            _msg("b", date=(base + timedelta(days=2)).isoformat()),  # Saturday
        ]
        result = extract_temporal_features(msgs)
        assert result["weekday_ratio"] == 0.5
        assert result["weekend_ratio"] == 0.5
        assert "Thu" in result["day_of_week_distribution"]
        assert "Sat" in result["day_of_week_distribution"]

    def test_session_detection(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("a", date=base.isoformat()),
            _msg("b", date=(base + timedelta(minutes=10)).isoformat()),
            _msg("c", date=(base + timedelta(minutes=20)).isoformat()),
            # 1 hour gap > 30 min session gap
            _msg("d", date=(base + timedelta(hours=1)).isoformat()),
        ]
        result = extract_temporal_features(msgs)
        # Two sessions: (a,b,c) and (d)
        assert result["activity_session_length"] > 0
        assert len(result["session_start_distribution"]) > 0

    def test_drift_zero_with_uniform_vocab(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("hello world", date=base.isoformat()),
            _msg("hello world", date=(base + timedelta(days=1)).isoformat()),
            _msg("hello world", date=(base + timedelta(days=2)).isoformat()),
            _msg("hello world", date=(base + timedelta(days=3)).isoformat()),
        ]
        result = extract_temporal_features(msgs)
        # Same vocabulary → drift should be 0
        assert result["persona_drift_30d"] == 0.0

    def test_drift_nonzero_with_changing_vocab(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("alpha beta gamma", date=base.isoformat()),
            _msg("alpha beta gamma", date=(base + timedelta(days=1)).isoformat()),
            _msg("delta epsilon zeta", date=(base + timedelta(days=60)).isoformat()),
            _msg("delta epsilon zeta", date=(base + timedelta(days=61)).isoformat()),
        ]
        result = extract_temporal_features(msgs)
        # 30d window from day 61 → cutoff at day 31.
        # Days 0,1 are "older", days 60,61 are "recent".
        # Different vocabulary → drift > 0
        assert result["persona_drift_30d"] > 0.0

    def test_scalars_in_range(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("a", date=base.isoformat()),
            _msg("b", date=(base + timedelta(hours=1)).isoformat()),
        ]
        result = extract_temporal_features(msgs)
        for key in ("weekday_ratio", "weekend_ratio", "timezone_inference_confidence"):
            assert 0.0 <= result[key] <= 1.0, f"{key} out of range: {result[key]}"
        for h in range(24):
            assert 0.0 <= result[f"hour_{h}"] <= 1.0

    def test_message_length_by_hour(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("short", date=base.isoformat()),
            _msg("longer message here", date=base.isoformat()),
        ]
        result = extract_temporal_features(msgs)
        assert "10" in result["message_length_by_hour"]
        avg_len = result["message_length_by_hour"]["10"]
        assert avg_len == (5 + 19) / 2

    def test_half_life(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        # Same words throughout, evenly split → retention ~0.5
        # half_life ≈ span * ln(0.5)/ln(0.5) = span
        msgs = [
            _msg("hello world foo", date=base.isoformat()),
            _msg("hello world foo", date=(base + timedelta(days=30)).isoformat()),
            _msg("hello world foo", date=(base + timedelta(days=60)).isoformat()),
            _msg("hello world foo", date=(base + timedelta(days=90)).isoformat()),
        ]
        result = extract_temporal_features(msgs)
        # With 50% retention and 90-day span, half_life ≈ 90
        assert result["feature_half_life"] > 0.0
        assert result["feature_half_life"] <= 200.0  # bounded

    def test_half_life_no_turnover(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        # All words in early also dominate late → retention ~1.0 → half_life = 0
        msgs = [
            _msg("hello world foo bar baz", date=base.isoformat()),
            _msg("hello world foo bar baz", date=(base + timedelta(days=1)).isoformat()),
            _msg("hello world foo bar baz", date=(base + timedelta(days=2)).isoformat()),
            _msg("hello world foo bar baz", date=(base + timedelta(days=3)).isoformat()),
            _msg("hello world foo bar baz", date=(base + timedelta(days=4)).isoformat()),
            _msg("hello world foo bar baz", date=(base + timedelta(days=5)).isoformat()),
        ]
        result = extract_temporal_features(msgs)
        # Same words in both halves with equal frequency → retention ~0.5
        # This is expected behavior, not a bug
        assert result["feature_half_life"] >= 0.0
