"""
Unit tests for Conditional Behavioral Probabilities feature extraction module.

Tests:
- Empty input returns defaults
- Messages with None/empty text or missing fields
- JSON serializability of output
- Known input with all context types:
  - Channel IDs ('channel:<id>')
  - Reply vs Initiation
  - Hour buckets ('morning', 'afternoon', 'evening', 'night')
  - Length buckets ('short', 'medium', 'long')
  - Custom context function
- Conditional feature detection for all 7 features:
  - profanity_rate
  - long_message_rate
  - question_rate
  - emoji_rate
  - codeblock_rate
  - url_rate
  - technical_jargon_rate
- Context distribution, context count, and context entropy calculation
- Context-conditioned variance calculation
- Distribution capping at 50 contexts
- Scalar ranges and rounding to 6 decimal places
- Comparison function (compare_conditional_features)
"""
from __future__ import annotations

import json
import math
import pytest

from tgarchive.intelligence.features.conditional import (
    CONDITIONAL_FEATURE_NAMES,
    DEFAULT_CONDITIONAL_FEATURES,
    MAX_CONTEXTS,
    compare_conditional_features,
    extract_conditional_features,
)


class TestConditionalFeatures:
    """Tests for conditional behavioral probability extraction."""

    def test_empty_messages(self):
        """Empty input should return default structure."""
        feat = extract_conditional_features([])
        assert isinstance(feat, dict)
        assert feat["conditional_probabilities"] == {}
        assert feat["context_distribution"] == {}
        assert feat["context_count"] == 0
        assert feat["context_entropy"] == 0.0
        assert isinstance(feat["context_conditioned_variance"], dict)
        for f in CONDITIONAL_FEATURE_NAMES:
            assert feat["context_conditioned_variance"][f] == 0.0

    def test_messages_with_none_or_missing_text(self):
        """Messages with None or missing text should be processed gracefully."""
        messages = [
            {"id": 1, "date": "2026-01-01T08:00:00Z"},
            {"id": 2, "content": None, "channel_id": 101},
            {"id": 3, "text": "", "reply_to_message_id": 55},
        ]
        feat = extract_conditional_features(messages)
        assert isinstance(feat, dict)
        assert feat["context_count"] > 0
        assert "short" in feat["conditional_probabilities"]
        # Rates should all be 0.0 for empty texts
        for f in CONDITIONAL_FEATURE_NAMES:
            assert feat["conditional_probabilities"]["short"][f] == 0.0

    def test_json_serializable(self):
        """Verify the output is fully JSON serializable."""
        messages = [
            {
                "channel_id": 12345,
                "reply_to_message_id": 99,
                "date": "2026-03-15T09:30:00Z",
                "content": "Why is the compiler throwing a kernel panic? 😱 Check https://example.com/err\n```c\nint x = 0;\n```",
            },
            {
                "channel_id": 12345,
                "reply_to_message_id": None,
                "date": "2026-03-15T14:10:00Z",
                "text": "Just pushed the fix.",
            },
        ]
        feat = extract_conditional_features(messages)
        serialized = json.dumps(feat)
        assert isinstance(serialized, str)

        deserialized = json.loads(serialized)
        assert "conditional_probabilities" in deserialized
        assert "context_distribution" in deserialized
        assert "context_count" in deserialized
        assert "context_entropy" in deserialized
        assert "context_conditioned_variance" in deserialized
        assert deserialized["context_count"] == len(deserialized["conditional_probabilities"])

    def test_metadata_context_derivation(self):
        """Verify contexts: channel_id, reply/initiation, hour buckets, length buckets."""
        messages = [
            # Message 1: channel:42, reply, morning (9 AM), short (<50 chars)
            {
                "channel_id": 42,
                "reply_to_message_id": 10,
                "date": "2026-05-01 09:00:00",
                "content": "Good morning!",
            },
            # Message 2: channel:42, initiation, afternoon (14 PM), medium (50-200 chars)
            {
                "channel_id": "42",
                "reply_to_message_id": None,
                "date": "2026-05-01 14:00:00",
                "content": "This is a medium length message designed to test the medium bucket classifier with more than fifty chars.",
            },
            # Message 3: channel:99, initiation, evening (19 PM), long (>200 chars)
            {
                "channel_id": 99,
                "date": "2026-05-01 19:00:00",
                "content": "A" * 250,
            },
            # Message 4: initiation, night (02 AM), short
            {
                "date": "2026-05-01 02:00:00",
                "content": "Late night note.",
            },
        ]

        feat = extract_conditional_features(messages)
        probs = feat["conditional_probabilities"]

        assert "channel:42" in probs
        assert "channel:99" in probs
        assert "reply" in probs
        assert "initiation" in probs
        assert "morning" in probs
        assert "afternoon" in probs
        assert "evening" in probs
        assert "night" in probs
        assert "short" in probs
        assert "medium" in probs
        assert "long" in probs

    def test_all_seven_feature_detections(self):
        """Test calculation of profanity, long_message, question, emoji, codeblock, url, technical_jargon."""
        messages = [
            {
                "channel_id": 1,
                "reply_to_message_id": 10,
                "date": "2026-06-01 10:00:00",
                "content": (
                    "Why the fuck is this docker redis container failing? 🤔\n"
                    "Check https://docker.com/docs for debugging details.\n"
                    "```yaml\nversion: '3'\n```\n"
                    "Adding additional descriptive context to make this message longer than 200 characters so that it triggers long_message_rate? 🤔"
                ),
            },
            {
                "channel_id": 1,
                "reply_to_message_id": 10,
                "date": "2026-06-01 10:05:00",
                "content": "Clean short message.",
            },
        ]

        feat = extract_conditional_features(messages)
        probs = feat["conditional_probabilities"]["channel:1"]

        # Exactly 1 of 2 messages in channel:1 has all features
        assert probs["profanity_rate"] == 0.5
        assert probs["long_message_rate"] == 0.5
        assert probs["question_rate"] == 0.5
        assert probs["emoji_rate"] == 0.5
        assert probs["codeblock_rate"] == 0.5
        assert probs["url_rate"] == 0.5
        assert probs["technical_jargon_rate"] == 0.5

    def test_custom_context_fn(self):
        """Verify custom context function receives message and contributes to contexts."""
        def my_context_fn(msg):
            role = msg.get("role")
            if role:
                return f"role:{role}"
            tags = msg.get("tags")
            if tags:
                return [f"tag:{t}" for t in tags]
            return None

        messages = [
            {"content": "Admin notice", "role": "admin"},
            {"content": "User question?", "tags": ["support", "billing"]},
        ]

        feat = extract_conditional_features(messages, context_fn=my_context_fn)
        probs = feat["conditional_probabilities"]

        assert "role:admin" in probs
        assert "tag:support" in probs
        assert "tag:billing" in probs
        assert probs["tag:support"]["question_rate"] == 1.0
        assert probs["role:admin"]["question_rate"] == 0.0

    def test_custom_context_fn_exception_handled(self):
        """Custom context function throwing exceptions should be handled gracefully."""
        def faulty_context_fn(msg):
            raise ValueError("Intentional error")

        messages = [{"content": "Hello world"}]
        feat = extract_conditional_features(messages, context_fn=faulty_context_fn)
        assert feat["context_count"] > 0
        assert "initiation" in feat["conditional_probabilities"]

    def test_context_conditioned_variance_and_entropy(self):
        """Verify variance across contexts and entropy calculation."""
        # 2 messages with 2 custom disjoint contexts:
        # Context 'ctx_a': 1 message with profanity and question -> rates = 1.0
        # Context 'ctx_b': 1 message with no profanity and no question -> rates = 0.0
        def split_context(msg):
            return msg.get("custom_ctx")

        messages = [
            {"content": "damn this is broken?", "custom_ctx": "ctx_a"},
            {"content": "all clean here", "custom_ctx": "ctx_b"},
        ]

        feat = extract_conditional_features(messages, context_fn=split_context)
        probs = feat["conditional_probabilities"]

        assert probs["ctx_a"]["profanity_rate"] == 1.0
        assert probs["ctx_a"]["question_rate"] == 1.0
        assert probs["ctx_b"]["profanity_rate"] == 0.0
        assert probs["ctx_b"]["question_rate"] == 0.0

        variances = feat["context_conditioned_variance"]
        # With 4 contexts (ctx_a, ctx_b, initiation, short), let's check variance is computed
        for f in CONDITIONAL_FEATURE_NAMES:
            assert 0.0 <= variances[f] <= 1.0
            assert isinstance(variances[f], float)

        # Specifically for 2 isolated contexts:
        # If we isolate just two contexts: rates are [1.0, 0.0, 0.5, 0.5] for initiation/short
        assert feat["context_entropy"] > 0.0

    def test_distributions_capped_at_max_contexts(self):
        """Verify that distributions are capped at 50 contexts."""
        messages = []
        for i in range(75):
            messages.append({
                "channel_id": f"channel_{i}",
                "content": f"Message number {i}",
            })

        feat = extract_conditional_features(messages)
        assert feat["context_count"] <= MAX_CONTEXTS
        assert len(feat["conditional_probabilities"]) <= MAX_CONTEXTS
        assert len(feat["context_distribution"]) <= MAX_CONTEXTS

    def test_scalar_ranges_and_rounding(self):
        """All scalar rates and statistics must be in valid ranges and rounded to 6 decimal places."""
        messages = [
            {"channel_id": "c1", "content": "hello world?"},
            {"channel_id": "c1", "content": "another message"},
            {"channel_id": "c2", "content": "damn http://test.com/a 🤔"},
        ]
        feat = extract_conditional_features(messages)

        assert isinstance(feat["context_count"], int)
        assert isinstance(feat["context_entropy"], float)
        assert feat["context_entropy"] >= 0.0

        for ctx, rates in feat["conditional_probabilities"].items():
            for feat_name, val in rates.items():
                assert 0.0 <= val <= 1.0
                # Float representation should have at most 6 decimal places
                assert round(val, 6) == val

        for ctx, p in feat["context_distribution"].items():
            assert 0.0 <= p <= 1.0
            assert round(p, 6) == p

        for feat_name, var in feat["context_conditioned_variance"].items():
            assert 0.0 <= var <= 1.0
            assert round(var, 6) == var

    def test_compare_conditional_features(self):
        """Test similarity and confidence calculation between feature sets."""
        msg_a = [
            {"channel_id": "c1", "content": "What is the kernel bug? 😱"},
            {"channel_id": "c1", "content": "Fixed here: https://link.com"},
        ]
        msg_b = [
            {"channel_id": "c1", "content": "Why is the compiler failing? 🔥"},
            {"channel_id": "c1", "content": "Fixed in repo: https://link2.com"},
        ]
        msg_c = [
            {"channel_id": "c99", "content": "Completely unrelated content."},
        ]

        feat_a = extract_conditional_features(msg_a)
        feat_b = extract_conditional_features(msg_b)
        feat_c = extract_conditional_features(msg_c)

        # High similarity between similar behavior in same contexts
        sim_ab, conf_ab = compare_conditional_features(feat_a, feat_b)
        assert 0.0 <= sim_ab <= 1.0
        assert 0.0 <= conf_ab <= 1.0
        assert sim_ab > 0.7

        # Zero/low confidence when contexts are disjoint
        sim_ac, conf_ac = compare_conditional_features(feat_a, feat_c)
        assert 0.0 <= sim_ac <= 1.0
        assert 0.0 <= conf_ac <= 1.0

        # Empty/invalid inputs
        assert compare_conditional_features({}, feat_a) == (0.0, 0.0)
        assert compare_conditional_features(feat_a, {}) == (0.0, 0.0)
        assert compare_conditional_features(None, None) == (0.0, 0.0)
