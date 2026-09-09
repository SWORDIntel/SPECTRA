"""
Unit and integration tests for tgarchive.evaluation (calibration.py and datasets.py).
"""
from __future__ import annotations

import sqlite3
import unittest
import numpy as np

from tgarchive.db.schema import SCHEMA_SQL
from tgarchive.evaluation.calibration import (
    brier_score,
    expected_calibration_error,
    reliability_data,
    calibration_map,
)
from tgarchive.evaluation.datasets import (
    Dataset,
    SAME_ACTOR,
    DIFFERENT_ACTOR,
    build_same_actor_dataset,
    build_different_actor_dataset,
    build_style_change_dataset,
    build_cross_channel_dataset,
    build_forwarded_control_dataset,
    build_short_message_dataset,
    build_long_message_dataset,
    build_bot_dataset,
)


class TestCalibrationMetrics(unittest.TestCase):
    """Test suite for calibration metrics and isotonic recalibration."""

    def test_brier_score_empty(self):
        self.assertEqual(brier_score([], []), 0.0)

    def test_brier_score_perfect(self):
        y_true = [0, 0, 1, 1]
        y_prob = [0.0, 0.0, 1.0, 1.0]
        self.assertAlmostEqual(brier_score(y_true, y_prob), 0.0)

    def test_brier_score_worst(self):
        y_true = [0, 0, 1, 1]
        y_prob = [1.0, 1.0, 0.0, 0.0]
        self.assertAlmostEqual(brier_score(y_true, y_prob), 1.0)

    def test_brier_score_values(self):
        y_true = [0, 1]
        y_prob = [0.2, 0.8]
        # (0.2 - 0)^2 + (0.8 - 1)^2 = 0.04 + 0.04 = 0.08 / 2 = 0.04
        self.assertAlmostEqual(brier_score(y_true, y_prob), 0.04)

    def test_brier_score_mismatch_raises(self):
        with self.assertRaises(ValueError):
            brier_score([0, 1], [0.5])

    def test_reliability_data_empty(self):
        rel = reliability_data([], [], n_bins=10)
        self.assertEqual(len(rel), 10)
        for low, high, conf, acc, count in rel:
            self.assertEqual(count, 0)
            self.assertEqual(conf, 0.0)
            self.assertEqual(acc, 0.0)

    def test_reliability_data_bins(self):
        y_true = [0, 0, 1, 1]
        y_prob = [0.05, 0.15, 0.85, 0.95]
        rel = reliability_data(y_true, y_prob, n_bins=5)
        self.assertEqual(len(rel), 5)
        # First bin [0.0, 0.2) should contain 0.05 and 0.15
        self.assertEqual(rel[0][4], 2)
        self.assertAlmostEqual(rel[0][2], 0.10)
        self.assertAlmostEqual(rel[0][3], 0.0)
        # Last bin [0.8, 1.0] should contain 0.85 and 0.95
        self.assertEqual(rel[4][4], 2)
        self.assertAlmostEqual(rel[4][2], 0.90)
        self.assertAlmostEqual(rel[4][3], 1.0)

    def test_expected_calibration_error_empty(self):
        self.assertEqual(expected_calibration_error([], [], n_bins=10), 0.0)

    def test_expected_calibration_error_perfect(self):
        y_true = [0, 1]
        y_prob = [0.0, 1.0]
        self.assertAlmostEqual(expected_calibration_error(y_true, y_prob, n_bins=10), 0.0)

    def test_expected_calibration_error_calculation(self):
        y_true = [0, 0, 1, 1]
        y_prob = [0.1, 0.1, 0.9, 0.9]
        # Bins: [0.0, 0.5): 2 samples, conf=0.1, acc=0.0 -> diff=0.1
        #       [0.5, 1.0]: 2 samples, conf=0.9, acc=1.0 -> diff=0.1
        # ECE = 0.5 * 0.1 + 0.5 * 0.1 = 0.1
        ece = expected_calibration_error(y_true, y_prob, n_bins=2)
        self.assertAlmostEqual(ece, 0.1)

    def test_calibration_map_empty(self):
        fn = calibration_map([], [])
        self.assertEqual(fn(0.5), 0.5)
        self.assertEqual(fn(1.5), 1.0)
        self.assertEqual(fn(-0.5), 0.0)

    def test_calibration_map_isotonic(self):
        y_true = [0, 0, 1, 1]
        y_prob = [0.1, 0.2, 0.8, 0.9]
        fn = calibration_map(y_true, y_prob)
        self.assertAlmostEqual(fn(0.1), 0.0)
        self.assertAlmostEqual(fn(0.9), 1.0)
        self.assertAlmostEqual(fn(0.5), 0.5)

        # Monotonicity test
        probs = [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]
        calibrated = fn(probs)
        for i in range(len(calibrated) - 1):
            self.assertTrue(calibrated[i] <= calibrated[i + 1] + 1e-9)

    def test_calibration_map_noisy(self):
        # Non-monotonic input that requires PAV merging
        y_true = [0, 1, 0, 1]
        y_prob = [0.2, 0.4, 0.6, 0.8]
        fn = calibration_map(y_true, y_prob)
        res = fn([0.1, 0.5, 0.9])
        self.assertTrue(res[0] <= res[1] <= res[2])


class TestEvaluationDatasets(unittest.TestCase):
    """Test suite for benchmark dataset builders."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(SCHEMA_SQL)

    def tearDown(self):
        self.conn.close()

    def test_dataset_dataclass_methods(self):
        ds = Dataset(
            name="test_bench",
            description="Test dataset",
            pairs=[
                {"subject_a": "a", "subject_b": "b", "label": 1, "messages_a": [], "messages_b": []},
                {"subject_a": "c", "subject_b": "d", "label": 0, "messages_a": [], "messages_b": []},
            ],
            metadata={"source": "test"},
        )
        self.assertEqual(len(ds), 2)
        self.assertEqual(ds[0]["subject_a"], "a")

        d_dict = ds.to_dict()
        self.assertEqual(d_dict["name"], "test_bench")

        ds_restored = Dataset.from_dict(d_dict)
        self.assertEqual(len(ds_restored), 2)

        summary = ds.summary()
        self.assertEqual(summary["total_pairs"], 2)
        self.assertEqual(summary["positive_pairs"], 1)
        self.assertEqual(summary["negative_pairs"], 1)
        self.assertEqual(summary["unique_subjects"], 4)

    def test_empty_db_builders(self):
        empty_conn = sqlite3.connect(":memory:")
        self.assertEqual(len(build_same_actor_dataset(empty_conn)), 0)
        self.assertEqual(len(build_different_actor_dataset(empty_conn)), 0)
        self.assertEqual(len(build_style_change_dataset(empty_conn)), 0)
        self.assertEqual(len(build_cross_channel_dataset(empty_conn)), 0)
        self.assertEqual(len(build_forwarded_control_dataset(empty_conn)), 0)
        self.assertEqual(len(build_short_message_dataset(empty_conn)), 0)
        self.assertEqual(len(build_long_message_dataset(empty_conn)), 0)
        self.assertEqual(len(build_bot_dataset(empty_conn)), 0)

    def test_populated_db_builders(self):
        # Insert test users
        self.conn.execute("INSERT INTO users (id, username, first_name, last_name, tags) VALUES (1, 'u1', 'John', 'Doe', 'same:grp1')")
        self.conn.execute("INSERT INTO users (id, username, first_name, last_name, tags) VALUES (2, 'u2', 'John', 'Doe', 'same:grp1')")
        self.conn.execute("INSERT INTO users (id, username, first_name, last_name, tags) VALUES (3, 'u3', 'Jane', 'Smith', 'actor')")

        # Insert messages
        short_msg = "hello there short test"
        long_msg = " ".join(["forensic stylometry text sample analysis"] * 25)

        for i in range(4):
            self.conn.execute(
                "INSERT INTO messages (id, type, date, content, user_id) VALUES (?, 'text', ?, ?, 1)",
                (100 + i, f"2026-01-0{i+1}T10:00:00", f"{short_msg} {i} {long_msg}"),
            )

        for i in range(4):
            self.conn.execute(
                "INSERT INTO messages (id, type, date, content, user_id) VALUES (?, 'text', ?, ?, 2)",
                (200 + i, f"2026-01-0{i+1}T10:00:00", f"{short_msg} {i} {long_msg}"),
            )

        for i in range(2):
            self.conn.execute(
                "INSERT INTO messages (id, type, date, content, user_id) VALUES (?, 'text', ?, ?, 3)",
                (300 + i, f"2026-01-0{i+1}T10:00:00", "brief note"),
            )

        # 1. Same actor
        ds_same = build_same_actor_dataset(self.conn)
        self.assertGreaterEqual(len(ds_same), 1)
        self.assertEqual(ds_same[0]["label"], SAME_ACTOR)

        # 2. Different actor
        ds_diff = build_different_actor_dataset(self.conn)
        self.assertGreaterEqual(len(ds_diff), 1)
        self.assertEqual(ds_diff[0]["label"], DIFFERENT_ACTOR)

        # 3. Style change
        ds_style = build_style_change_dataset(self.conn, min_messages=2)
        self.assertGreaterEqual(len(ds_style), 1)
        self.assertEqual(ds_style[0]["label"], SAME_ACTOR)

        # 4. Short message
        ds_short = build_short_message_dataset(self.conn, max_words=20)
        self.assertGreaterEqual(len(ds_short), 1)

        # 5. Long message
        ds_long = build_long_message_dataset(self.conn, min_words=50)
        self.assertGreaterEqual(len(ds_long), 1)


if __name__ == "__main__":
    unittest.main()
