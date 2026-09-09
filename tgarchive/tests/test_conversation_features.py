"""Tests for conversation mechanics feature extraction."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from tgarchive.intelligence.features.conversation import (
    DEFAULT_CONVERSATION_FEATURES,
    extract_conversation_features,
)


def _msg(content, date=None, user_id=None, reply_to=None, msg_id=None):
    m = {"content": content}
    if date is not None:
        m["date"] = date
    if user_id is not None:
        m["user_id"] = user_id
    if reply_to is not None:
        m["reply_to_message_id"] = reply_to
    if msg_id is not None:
        m["id"] = msg_id
    return m


class TestConversationFeatures:
    def test_empty_input(self):
        result = extract_conversation_features([])
        assert result == DEFAULT_CONVERSATION_FEATURES

    def test_empty_messages_list(self):
        result = extract_conversation_features([])
        assert isinstance(result, dict)
        assert "reply_probability" in result
        assert result["reply_probability"] == 0.0

    def test_json_serializable(self):
        msgs = [
            _msg("hello", date="2026-01-01T10:00:00Z", user_id=1, msg_id=1),
            _msg("hi back", date="2026-01-01T10:01:00Z", user_id=2, reply_to=1, msg_id=2),
        ]
        result = extract_conversation_features(msgs)
        json.dumps(result)  # should not raise

    def test_reply_probability(self):
        msgs = [
            _msg("hello", date="2026-01-01T10:00:00Z", user_id=1, msg_id=1),
            _msg("hi", date="2026-01-01T10:01:00Z", user_id=2, reply_to=1, msg_id=2),
            _msg("how are you", date="2026-01-01T10:02:00Z", user_id=1, reply_to=2, msg_id=3),
            _msg("good", date="2026-01-01T10:03:00Z", user_id=2, msg_id=4),
        ]
        result = extract_conversation_features(msgs)
        # 2 out of 4 have reply_to
        assert result["reply_probability"] == 0.5
        assert result["reply_to_message_rate"] == 0.5

    def test_reply_latency(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("hello", date=base.isoformat(), user_id=1, msg_id=1),
            _msg("hi", date=(base + timedelta(seconds=30)).isoformat(),
                 user_id=2, reply_to=1, msg_id=2),
        ]
        result = extract_conversation_features(msgs)
        assert result["reply_latency_median"] == 30.0
        assert "median" in result["reply_latency_distribution"]
        assert result["reply_latency_distribution"]["median"] == 30.0

    def test_double_message_rate(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("a", date=base.isoformat(), user_id=1, msg_id=1),
            _msg("b", date=(base + timedelta(seconds=10)).isoformat(),
                 user_id=1, msg_id=2),
            _msg("c", date=(base + timedelta(seconds=20)).isoformat(),
                 user_id=1, msg_id=3),
            _msg("d", date=(base + timedelta(seconds=120)).isoformat(),
                 user_id=2, msg_id=4),
        ]
        result = extract_conversation_features(msgs)
        # 3 consecutive messages by user 1 within 60s = 1 double (and 1 triple)
        assert result["double_message_rate"] > 0
        assert result["triple_message_rate"] > 0

    def test_no_timestamps_graceful(self):
        msgs = [
            _msg("hello", user_id=1),
            _msg("hi", user_id=2, reply_to=1),
        ]
        result = extract_conversation_features(msgs)
        # Should not crash, reply_probability still computed
        assert result["reply_probability"] == 0.5
        assert result["reply_latency_median"] == 0.0

    def test_burst_detection(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("a", date=base.isoformat(), user_id=1, msg_id=1),
            _msg("b", date=(base + timedelta(seconds=30)).isoformat(),
                 user_id=1, msg_id=2),
            _msg("c", date=(base + timedelta(seconds=60)).isoformat(),
                 user_id=1, msg_id=3),
            _msg("d", date=(base + timedelta(seconds=400)).isoformat(),
                 user_id=1, msg_id=4),
        ]
        result = extract_conversation_features(msgs)
        # First 3 messages form a burst (gaps < 300s), 4th is separate
        assert result["messages_per_burst"] > 0

    def test_quote_usage(self):
        msgs = [
            _msg("> quoted text\nreply"),
            _msg("normal message"),
        ]
        result = extract_conversation_features(msgs)
        assert result["quote_usage_rate"] == 0.5

    def test_response_length_correlation(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("short", date=base.isoformat(), user_id=1, msg_id=1),
            _msg("a reply", date=(base + timedelta(seconds=10)).isoformat(),
                 user_id=2, reply_to=1, msg_id=2),
            _msg("a much longer message here", date=(base + timedelta(seconds=20)).isoformat(),
                 user_id=1, msg_id=3),
            _msg("another reply that is also longer", date=(base + timedelta(seconds=30)).isoformat(),
                 user_id=2, reply_to=3, msg_id=4),
        ]
        result = extract_conversation_features(msgs)
        # Correlation should be computable
        assert isinstance(result["response_length_given_prompt_length"], (int, float))

    def test_scalars_in_range(self):
        base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("hello", date=base.isoformat(), user_id=1, msg_id=1),
            _msg("hi", date=(base + timedelta(seconds=30)).isoformat(),
                 user_id=2, reply_to=1, msg_id=2),
        ]
        result = extract_conversation_features(msgs)
        for key in ("reply_probability", "double_message_rate", "triple_message_rate",
                    "followup_message_probability", "quote_usage_rate",
                    "conversation_initiation_rate", "conversation_termination_rate"):
            assert 0.0 <= result[key] <= 1.0, f"{key} out of range: {result[key]}"
