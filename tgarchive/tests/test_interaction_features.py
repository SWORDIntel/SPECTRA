"""
Unit tests for Interaction-Conditioned Style feature extraction module (L11).

Tests:
- Empty messages and messages without text return defaults
- Graceful handling of missing or partial metadata
- JSON serializability of all outputs
- Grouping by context:
  - style_by_channel (per channel_id)
  - style_by_recipient_class (inferred 'dm' vs 'group')
  - style_by_time_period (morning, afternoon, evening, night)
  - style_by_message_type (initiation vs reply)
- Compact style vector computation (all 8 features):
  - avg_length
  - profanity_rate
  - emoji_rate
  - question_rate
  - formality_score (0-1 composite)
  - slang_rate
  - technical_jargon_rate
  - discourse_marker_rate
- Context distance calculations:
  - register_shift_score in [0.0, 1.0]
  - recipient_style_distance in [0.0, 1.0]
  - channel_style_distance in [0.0, 1.0]
  - context_style_consistency == round(1 - register_shift_score, 6)
- Scalar rounding to 6 decimal places
- Profile comparison function (compare_interaction_features)
"""
from __future__ import annotations

import json
import pytest

from tgarchive.intelligence.features.interaction import (
    DEFAULT_INTERACTION_FEATURES,
    DEFAULT_STYLE_VECTOR,
    STYLE_FEATURE_KEYS,
    compare_interaction_features,
    compute_style_vector,
    cosine_distance,
    extract_interaction_features,
)


class TestInteractionFeatures:
    """Tests for interaction-conditioned style feature extraction."""

    def test_empty_messages_returns_defaults(self):
        """Empty list of messages should return default dictionary."""
        feat = extract_interaction_features([])
        assert isinstance(feat, dict)
        assert feat["style_by_channel"] == {}
        assert feat["style_by_recipient_class"] == {}
        assert feat["style_by_time_period"] == {}
        assert feat["style_by_message_type"] == {}
        assert feat["register_shift_score"] == 0.0
        assert feat["recipient_style_distance"] == 0.0
        assert feat["channel_style_distance"] == 0.0
        assert feat["context_style_consistency"] == 1.0
        assert feat["context_count"] == 0

    def test_messages_without_text(self):
        """Messages with None or empty text should return defaults."""
        messages = [
            {"id": 1, "channel_id": 100},
            {"id": 2, "content": None, "date": "2026-08-23T10:00:00Z"},
            {"id": 3, "text": "", "reply_to_message_id": 12},
            {"id": 4, "content": "   ", "channel_id": -100500},
        ]
        feat = extract_interaction_features(messages)
        assert feat["style_by_channel"] == {}
        assert feat["style_by_recipient_class"] == {}
        assert feat["style_by_time_period"] == {}
        assert feat["style_by_message_type"] == {}
        assert feat["register_shift_score"] == 0.0
        assert feat["context_count"] == 0

    def test_missing_metadata_handled_gracefully(self):
        """Messages with missing channel_id, date, or reply_to_message_id should not crash."""
        messages = [
            {"content": "Just a plain message without extra metadata."},
            {"text": "Another plain message here."},
        ]
        feat = extract_interaction_features(messages)
        assert isinstance(feat, dict)
        assert feat["style_by_channel"] == {}
        assert feat["style_by_recipient_class"] == {}
        assert feat["style_by_time_period"] == {}
        # Should default to initiation
        assert "initiation" in feat["style_by_message_type"]
        assert feat["context_count"] == 1

    def test_json_serializable(self):
        """Verify the extracted dictionary is fully JSON-serializable."""
        messages = [
            {
                "channel_id": -100123456,
                "reply_to_message_id": None,
                "date": "2026-08-23T08:30:00Z",
                "content": "Good morning team, the compiler optimization pipeline is deployed.",
            },
            {
                "channel_id": 98765,
                "reply_to_message_id": 42,
                "date": "2026-08-23T22:15:00Z",
                "content": "yo bruh that bug was pure trash lmao 😂🔥",
            },
        ]
        feat = extract_interaction_features(messages)
        serialized = json.dumps(feat)
        assert isinstance(serialized, str)

        deserialized = json.loads(serialized)
        assert deserialized["context_count"] == feat["context_count"]
        assert "style_by_channel" in deserialized
        assert "style_by_recipient_class" in deserialized
        assert "style_by_time_period" in deserialized
        assert "style_by_message_type" in deserialized

    def test_channel_grouping(self):
        """Test that messages are correctly partitioned and styled per channel_id."""
        messages = [
            {"channel_id": 101, "content": "Message in channel 101."},
            {"channel_id": 101, "content": "Another message in channel 101."},
            {"channel_id": "chan_dev", "content": "Kernel panic debugging and profiling."},
            {"channel_id": "chan_dev", "content": "Async mutex synchronization."},
        ]
        feat = extract_interaction_features(messages)
        assert "101" in feat["style_by_channel"]
        assert "chan_dev" in feat["style_by_channel"]

        dev_style = feat["style_by_channel"]["chan_dev"]
        assert dev_style["technical_jargon_rate"] > 0.0
        assert feat["channel_style_distance"] >= 0.0

    def test_recipient_class_inference(self):
        """Test inference of 'dm' vs 'group' from channel_id, chat_type, and explicit flags."""
        messages = [
            # Inferred DM from positive channel_id
            {"channel_id": 555123, "content": "Hey bro what's up?"},
            # Inferred group from negative channel_id
            {"channel_id": -100999888, "content": "Meeting agenda for today."},
            # Explicit recipient_class
            {"recipient_class": "dm", "content": "Private message contents."},
            # chat_type supergroup
            {"chat_type": "supergroup", "content": "Public group discussion."},
            # is_group flag
            {"is_group": True, "content": "Another group message."},
        ]
        feat = extract_interaction_features(messages)
        assert "dm" in feat["style_by_recipient_class"]
        assert "group" in feat["style_by_recipient_class"]
        assert feat["recipient_style_distance"] >= 0.0
        assert feat["recipient_style_distance"] <= 1.0

    def test_time_period_grouping(self):
        """Test classification into morning(6-11), afternoon(12-17), evening(18-23), night(0-5)."""
        messages = [
            {"date": "2026-08-23T07:15:00Z", "content": "Morning message at 07:15."},
            {"date": "2026-08-23T14:30:00Z", "content": "Afternoon message at 14:30."},
            {"date": "2026-08-23T19:45:00Z", "content": "Evening message at 19:45."},
            {"date": "2026-08-23T02:10:00Z", "content": "Night message at 02:10."},
            # Unix timestamp format
            {"timestamp": 1755943200, "content": "Timestamp message."},
        ]
        feat = extract_interaction_features(messages)
        time_periods = feat["style_by_time_period"]
        assert "morning" in time_periods
        assert "afternoon" in time_periods
        assert "evening" in time_periods
        assert "night" in time_periods

    def test_message_type_grouping(self):
        """Test distinction between initiation and reply messages."""
        messages = [
            {"reply_to_message_id": None, "content": "Starting a new conversation topic."},
            {"reply_to_message_id": 1001, "content": "Replying to previous discussion."},
            {"reply_to_msg_id": 1002, "content": "Another reply message."},
            {"content": "Initiation without reply field."},
        ]
        feat = extract_interaction_features(messages)
        msg_types = feat["style_by_message_type"]
        assert "initiation" in msg_types
        assert "reply" in msg_types
        assert len(msg_types) == 2

    def test_style_vector_features_detection(self):
        """Verify all 8 features in the compact style vector are accurately extracted."""
        messages = [
            {
                "content": "Why is the compiler throwing this error? That damn shit is crazy bro! 😂 Check the kernel stack trace, however we must be careful.",
            }
        ]
        vec = compute_style_vector(messages)
        for k in STYLE_FEATURE_KEYS:
            assert k in vec
            assert isinstance(vec[k], float)
            assert vec[k] >= 0.0

        assert vec["avg_length"] > 0.0
        assert vec["profanity_rate"] > 0.0
        assert vec["emoji_rate"] > 0.0
        assert vec["question_rate"] == 1.0
        assert 0.0 <= vec["formality_score"] <= 1.0
        assert vec["slang_rate"] > 0.0
        assert vec["technical_jargon_rate"] > 0.0
        assert vec["discourse_marker_rate"] > 0.0

    def test_register_shift_across_contexts(self):
        """Test that differing styles between DM and Group produce high register shift."""
        casual_dm_messages = [
            {
                "channel_id": 12345,  # DM
                "content": "bruh that shit is hilarious lmao 😂 wtff",
            },
            {
                "channel_id": 12345,  # DM
                "content": "yo fam bet, gonna vibe later rn",
            },
        ]
        formal_group_messages = [
            {
                "channel_id": -100987654,  # Group
                "content": "The distributed database architecture requires consensus verification.",
            },
            {
                "channel_id": -100987654,  # Group
                "content": "Furthermore, the cryptographic handshake ensures session confidentiality.",
            },
        ]
        all_messages = casual_dm_messages + formal_group_messages
        feat = extract_interaction_features(all_messages)

        assert feat["register_shift_score"] > 0.1
        assert feat["recipient_style_distance"] > 0.1
        assert feat["context_style_consistency"] == round(1.0 - feat["register_shift_score"], 6)
        assert 0.0 <= feat["context_style_consistency"] <= 1.0

    def test_consistent_persona_across_contexts(self):
        """A persona with consistent style across contexts should have low register shift and high consistency."""
        messages = [
            {
                "channel_id": 111,
                "reply_to_message_id": None,
                "date": "2026-08-23T08:00:00Z",
                "content": "The algorithm computes the optimal pipeline scheduling.",
            },
            {
                "channel_id": -222,
                "reply_to_message_id": 5,
                "date": "2026-08-23T14:00:00Z",
                "content": "The algorithm evaluates the optimal pipeline scheduling.",
            },
        ]
        feat = extract_interaction_features(messages)
        assert feat["register_shift_score"] < 0.2
        assert feat["context_style_consistency"] > 0.8

    def test_cosine_distance_properties(self):
        """Verify mathematical properties of cosine distance between style vectors."""
        vec1 = {
            "avg_length": 50.0,
            "profanity_rate": 0.1,
            "emoji_rate": 0.05,
            "question_rate": 0.2,
            "formality_score": 0.5,
            "slang_rate": 0.1,
            "technical_jargon_rate": 0.15,
            "discourse_marker_rate": 0.1,
        }
        # Identical vector distance should be 0.0
        assert cosine_distance(vec1, vec1) == 0.0

        # Empty / zero vector handling
        assert cosine_distance({}, vec1) == 0.0
        assert cosine_distance(DEFAULT_STYLE_VECTOR, DEFAULT_STYLE_VECTOR) == 0.0

        # Very different vector
        vec2 = {
            "avg_length": 180.0,
            "profanity_rate": 0.0,
            "emoji_rate": 0.0,
            "question_rate": 0.0,
            "formality_score": 0.9,
            "slang_rate": 0.0,
            "technical_jargon_rate": 0.8,
            "discourse_marker_rate": 0.4,
        }
        dist = cosine_distance(vec1, vec2)
        assert 0.0 <= dist <= 1.0
        assert dist > 0.0

    def test_compare_interaction_features(self):
        """Test profile comparison function."""
        # Invalid / empty comparisons
        assert compare_interaction_features({}, {}) == (0.0, 0.0)
        assert compare_interaction_features(None, {}) == (0.0, 0.0)

        feat_a = {
            "register_shift_score": 0.3,
            "recipient_style_distance": 0.25,
            "channel_style_distance": 0.15,
            "context_style_consistency": 0.7,
        }
        # Identical profiles
        sim, conf = compare_interaction_features(feat_a, feat_a)
        assert sim == 1.0
        assert conf == 1.0

        # Slightly different profiles
        feat_b = {
            "register_shift_score": 0.35,
            "recipient_style_distance": 0.28,
            "channel_style_distance": 0.18,
            "context_style_consistency": 0.65,
        }
        sim_ab, conf_ab = compare_interaction_features(feat_a, feat_b)
        assert 0.9 <= sim_ab <= 1.0
        assert conf_ab == 1.0
