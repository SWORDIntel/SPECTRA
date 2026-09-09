"""
Tests for the Actor Identity-Resolution Engine.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tgarchive.intelligence.resolver import ActorIdentityResolver
from tgarchive.intelligence.schema import HypothesisType


@pytest.fixture
def same_actor_messages_a():
    return [
        {"id": 1, "channel_id": 100, "user_id": 123, "content": "Selling malware samples, DM for price. BTC accepted.", "date": datetime(2024, 3, 15, 14, 30, tzinfo=timezone.utc)},
        {"id": 2, "channel_id": 100, "user_id": 123, "content": "New ransomware build available. $500 USD. escrow accepted.", "date": datetime(2024, 3, 15, 15, 0, tzinfo=timezone.utc)},
        {"id": 3, "channel_id": 100, "user_id": 123, "content": "Check out my shop at https://darkshop.onion", "date": datetime(2024, 3, 16, 14, 45, tzinfo=timezone.utc)},
        {"id": 4, "channel_id": 100, "user_id": 123, "content": "Bulk discount available. 10% off for orders over 5.", "date": datetime(2024, 3, 17, 14, 15, tzinfo=timezone.utc)},
        {"id": 5, "channel_id": 100, "user_id": 123, "content": "Verified vendor. Check my vouches. PM for details.", "date": datetime(2024, 3, 18, 14, 30, tzinfo=timezone.utc)},
        {"id": 6, "channel_id": 100, "user_id": 123, "content": "New stock just arrived. In stock and ready to ship.", "date": datetime(2024, 3, 19, 15, 0, tzinfo=timezone.utc)},
    ]


@pytest.fixture
def same_actor_messages_b():
    """Same content, different time period — same actor reappearing."""
    return [
        {"id": 10, "channel_id": 100, "user_id": 456, "content": "Selling malware samples, DM for price. BTC accepted.", "date": datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc)},
        {"id": 11, "channel_id": 100, "user_id": 456, "content": "New ransomware build available. $500 USD. escrow accepted.", "date": datetime(2024, 6, 15, 15, 0, tzinfo=timezone.utc)},
        {"id": 12, "channel_id": 100, "user_id": 456, "content": "Check out my shop at https://darkshop.onion", "date": datetime(2024, 6, 16, 14, 45, tzinfo=timezone.utc)},
        {"id": 13, "channel_id": 100, "user_id": 456, "content": "Bulk discount available. 10% off for orders over 5.", "date": datetime(2024, 6, 17, 14, 15, tzinfo=timezone.utc)},
        {"id": 14, "channel_id": 100, "user_id": 456, "content": "Verified vendor. Check my vouches. PM for details.", "date": datetime(2024, 6, 18, 14, 30, tzinfo=timezone.utc)},
        {"id": 15, "channel_id": 100, "user_id": 456, "content": "New stock just arrived. In stock and ready to ship.", "date": datetime(2024, 6, 19, 15, 0, tzinfo=timezone.utc)},
    ]


@pytest.fixture
def different_actor_messages():
    """Completely different actor — different style, timezone, topic."""
    return [
        {"id": 20, "channel_id": 200, "user_id": 789, "content": "Hey everyone, looking for recommendations for a good VPN service.", "date": datetime(2024, 3, 15, 3, 30, tzinfo=timezone.utc)},
        {"id": 21, "channel_id": 200, "user_id": 789, "content": "Anyone tried Mullvad? Heard good things about them.", "date": datetime(2024, 3, 15, 4, 0, tzinfo=timezone.utc)},
        {"id": 22, "channel_id": 200, "user_id": 789, "content": "Just want to browse safely, nothing fancy.", "date": datetime(2024, 3, 16, 3, 45, tzinfo=timezone.utc)},
        {"id": 23, "channel_id": 200, "user_id": 789, "content": "Thanks for the suggestions everyone!", "date": datetime(2024, 3, 17, 4, 15, tzinfo=timezone.utc)},
        {"id": 24, "channel_id": 200, "user_id": 789, "content": "Will check out ProtonVPN too.", "date": datetime(2024, 3, 18, 3, 30, tzinfo=timezone.utc)},
        {"id": 25, "channel_id": 200, "user_id": 789, "content": "Appreciate the help.", "date": datetime(2024, 3, 19, 4, 0, tzinfo=timezone.utc)},
    ]


class TestActorIdentityResolver:
    def test_same_actor_high_probability(self, same_actor_messages_a, same_actor_messages_b):
        resolver = ActorIdentityResolver(min_messages=3)
        hyp = resolver.resolve(
            actor_a_messages=same_actor_messages_a,
            actor_b_messages=same_actor_messages_b,
            actor_a_id=123,
            actor_b_id=456,
        )
        assert hyp.hypothesis_type == HypothesisType.SAME_ACTOR
        assert hyp.probability > 0.8
        assert hyp.confidence > 0.5
        assert len(hyp.supporting_evidence) > 0
        assert hyp.hypothesis_id != ""

    def test_different_actor_lower_probability(self, same_actor_messages_a, different_actor_messages):
        resolver = ActorIdentityResolver(min_messages=3)
        hyp = resolver.resolve(
            actor_a_messages=same_actor_messages_a,
            actor_b_messages=different_actor_messages,
            actor_a_id=123,
            actor_b_id=789,
        )
        assert hyp.probability < 0.9  # Should be lower than same-actor case
        assert len(hyp.contradicting_evidence) > 0  # Should have contradicting evidence

    def test_probability_in_range(self, same_actor_messages_a, same_actor_messages_b):
        resolver = ActorIdentityResolver()
        hyp = resolver.resolve(
            actor_a_messages=same_actor_messages_a,
            actor_b_messages=same_actor_messages_b,
            actor_a_id=123,
            actor_b_id=456,
        )
        assert 0.0 <= hyp.probability <= 1.0
        assert 0.0 <= hyp.confidence <= 1.0

    def test_hypothesis_has_provenance(self, same_actor_messages_a, same_actor_messages_b):
        resolver = ActorIdentityResolver()
        hyp = resolver.resolve(
            actor_a_messages=same_actor_messages_a,
            actor_b_messages=same_actor_messages_b,
            actor_a_id=123,
            actor_b_id=456,
        )
        # The hypothesis should have evidence IDs (provenance)
        total_evidence = len(hyp.supporting_evidence) + len(hyp.contradicting_evidence)
        assert total_evidence > 0

    def test_insufficient_evidence_tracked(self, same_actor_messages_a, same_actor_messages_b):
        resolver = ActorIdentityResolver()
        hyp = resolver.resolve(
            actor_a_messages=same_actor_messages_a,
            actor_b_messages=same_actor_messages_b,
            actor_a_id=123,
            actor_b_id=456,
        )
        # Media features should be insufficient (no media provided)
        assert "media" in hyp.insufficient_evidence_flags

    def test_empty_messages(self):
        resolver = ActorIdentityResolver()
        hyp = resolver.resolve(
            actor_a_messages=[],
            actor_b_messages=[],
            actor_a_id=1,
            actor_b_id=2,
        )
        assert hyp.probability == 0.5  # No evidence → uncertain
        assert hyp.confidence == 0.0   # No confidence

    def test_canonical_subject_ids(self, same_actor_messages_a, same_actor_messages_b):
        resolver = ActorIdentityResolver()
        hyp = resolver.resolve(
            actor_a_messages=same_actor_messages_a,
            actor_b_messages=same_actor_messages_b,
            actor_a_id=123,
            actor_b_id=456,
        )
        assert hyp.subject_a == "telegram:user:123"
        assert hyp.subject_b == "telegram:user:456"

    def test_to_dict_round_trip(self, same_actor_messages_a, same_actor_messages_b):
        resolver = ActorIdentityResolver()
        hyp = resolver.resolve(
            actor_a_messages=same_actor_messages_a,
            actor_b_messages=same_actor_messages_b,
            actor_a_id=123,
            actor_b_id=456,
        )
        d = hyp.to_dict()
        assert d["probability"] == hyp.probability
        assert d["hypothesis_type"] == "same_actor"
        # Can be serialized to JSON
        import json
        json.dumps(d)
