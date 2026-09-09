"""
Tests for the immutable analyst label store.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from tgarchive.intelligence.labels import (
    AnalystLabel,
    AnalystLabelStore,
    AnalystLabelType,
    AnalystVerdict,
)


@pytest.fixture
def store():
    """Fresh in-memory label store."""
    conn = sqlite3.connect(":memory:")
    return AnalystLabelStore(conn)


@pytest.fixture
def confirm_label():
    return AnalystLabel(
        label_type=AnalystLabelType.SAME_ACTOR,
        verdict=AnalystVerdict.CONFIRM,
        subject_a="telegram:user:123",
        subject_b="telegram:user:456",
        analyst_id="analyst-1",
        notes="Confirmed via external OSINT",
        confidence=0.95,
    )


@pytest.fixture
def reject_label():
    return AnalystLabel(
        label_type=AnalystLabelType.SAME_ACTOR,
        verdict=AnalystVerdict.REJECT,
        subject_a="telegram:user:123",
        subject_b="telegram:user:456",
        analyst_id="analyst-2",
        notes="Different writing styles, different timezones",
        confidence=0.85,
    )


@pytest.fixture
def unsure_label():
    return AnalystLabel(
        label_type=AnalystLabelType.SAME_ACTOR,
        verdict=AnalystVerdict.UNSURE,
        subject_a="telegram:user:123",
        subject_b="telegram:user:456",
        analyst_id="analyst-3",
        notes="Insufficient evidence to determine",
        confidence=0.3,
    )


class TestAnalystLabel:
    def test_label_id_deterministic(self, confirm_label):
        label2 = AnalystLabel(
            label_type=AnalystLabelType.SAME_ACTOR,
            verdict=AnalystVerdict.CONFIRM,
            subject_a="telegram:user:123",
            subject_b="telegram:user:456",
            analyst_id="analyst-1",
        )
        assert confirm_label.label_id == label2.label_id

    def test_label_hash_computed(self, confirm_label):
        assert confirm_label.label_hash != ""
        assert len(confirm_label.label_hash) == 64  # SHA256 hex

    def test_to_dict_round_trip(self, confirm_label):
        d = confirm_label.to_dict()
        assert d["label_type"] == "same_actor"
        assert d["verdict"] == "confirm"
        label2 = AnalystLabel.from_dict(d)
        assert label2.label_type == AnalystLabelType.SAME_ACTOR
        assert label2.verdict == AnalystVerdict.CONFIRM
        assert label2.subject_a == confirm_label.subject_a

    def test_to_sql_row(self, confirm_label):
        row = confirm_label.to_sql_row()
        assert isinstance(row, tuple)
        assert row[0] == confirm_label.label_id
        assert row[1] == "same_actor"
        assert row[2] == "confirm"

    def test_json_serializable(self, confirm_label):
        import json
        json.dumps(confirm_label.to_dict())


class TestAnalystLabelStore:
    def test_add_and_retrieve_label(self, store, confirm_label):
        label_id = store.add_label(confirm_label)
        assert label_id == confirm_label.label_id
        labels = store.get_labels("telegram:user:123", "telegram:user:456")
        assert len(labels) == 1
        assert labels[0].verdict == AnalystVerdict.CONFIRM

    def test_append_only(self, store, confirm_label, reject_label):
        """Adding a second label for the same pair should not overwrite."""
        store.add_label(confirm_label)
        store.add_label(reject_label)
        labels = store.get_labels("telegram:user:123", "telegram:user:456")
        assert len(labels) == 2  # Both labels preserved

    def test_latest_label_supersedes(self, store, confirm_label, reject_label):
        """get_latest_label should return the most recent verdict."""
        store.add_label(confirm_label)
        store.add_label(reject_label)
        latest = store.get_latest_label(
            "telegram:user:123", "telegram:user:456", AnalystLabelType.SAME_ACTOR
        )
        assert latest.verdict == AnalystVerdict.REJECT

    def test_chain_integrity(self, store, confirm_label, reject_label):
        """Each label's prev_hash should match the previous label's hash."""
        store.add_label(confirm_label)
        store.add_label(reject_label)
        labels = store.get_all_labels()
        assert len(labels) == 2
        # First label has empty prev_hash
        assert labels[0].prev_hash == ""
        # Second label's prev_hash matches first label's hash
        assert labels[1].prev_hash == labels[0].label_hash

    def test_verify_chain(self, store, confirm_label, reject_label):
        """Chain verification should pass for untampered labels."""
        store.add_label(confirm_label)
        store.add_label(reject_label)
        assert store.verify_chain() is True

    def test_get_training_labels(self, store, confirm_label, reject_label, unsure_label):
        """Training labels should only include the latest per pair."""
        store.add_label(confirm_label)
        store.add_label(reject_label)  # Supersedes confirm
        store.add_label(unsure_label)  # Supersedes reject

        training = store.get_training_labels(AnalystLabelType.SAME_ACTOR)
        assert len(training) == 1  # Only latest
        label, gt = training[0]
        assert gt == "abstain"  # UNSURE is the latest

    def test_training_labels_positive_negative(self, store):
        """Test positive/negative/abstain classification."""
        # Different pairs
        store.add_label(AnalystLabel(
            label_type=AnalystLabelType.SAME_ACTOR,
            verdict=AnalystVerdict.CONFIRM,
            subject_a="telegram:user:1",
            subject_b="telegram:user:2",
            analyst_id="a1",
        ))
        store.add_label(AnalystLabel(
            label_type=AnalystLabelType.SAME_ACTOR,
            verdict=AnalystVerdict.REJECT,
            subject_a="telegram:user:3",
            subject_b="telegram:user:4",
            analyst_id="a1",
        ))
        store.add_label(AnalystLabel(
            label_type=AnalystLabelType.SAME_ACTOR,
            verdict=AnalystVerdict.UNSURE,
            subject_a="telegram:user:5",
            subject_b="telegram:user:6",
            analyst_id="a1",
        ))

        training = store.get_training_labels()
        gts = {gt for _, gt in training}
        assert "positive" in gts
        assert "negative" in gts
        assert "abstain" in gts

    def test_empty_store(self, store):
        assert store.get_all_labels() == []
        assert store.get_training_labels() == []
        assert store.verify_chain() is True

    def test_stats(self, store, confirm_label, reject_label):
        store.add_label(confirm_label)
        store.add_label(reject_label)
        stats = store.get_stats()
        assert stats["total_labels"] == 2
        assert stats["by_verdict"].get("confirm") == 1
        assert stats["by_verdict"].get("reject") == 1

    def test_filter_by_label_type(self, store, confirm_label):
        store.add_label(confirm_label)
        # Add a different type
        store.add_label(AnalystLabel(
            label_type=AnalystLabelType.BOT_DETECTION,
            verdict=AnalystVerdict.CONFIRM,
            subject_a="telegram:user:123",
            subject_b=None,
            analyst_id="a1",
        ))
        same_actor_labels = store.get_labels(
            "telegram:user:123", "telegram:user:456", AnalystLabelType.SAME_ACTOR
        )
        assert len(same_actor_labels) == 1
        assert same_actor_labels[0].label_type == AnalystLabelType.SAME_ACTOR

    def test_label_with_evidence_ids(self, store):
        """Labels should preserve evidence IDs for provenance."""
        label = AnalystLabel(
            label_type=AnalystLabelType.SAME_ACTOR,
            verdict=AnalystVerdict.CONFIRM,
            subject_a="telegram:user:1",
            subject_b="telegram:user:2",
            analyst_id="a1",
            evidence_ids=["ev1", "ev2", "ev3"],
        )
        store.add_label(label)
        retrieved = store.get_labels("telegram:user:1", "telegram:user:2")
        assert retrieved[0].evidence_ids == ["ev1", "ev2", "ev3"]
