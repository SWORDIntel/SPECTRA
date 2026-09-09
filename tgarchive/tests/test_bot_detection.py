"""Tests for Bot Detection Service with vectorized numpy and fallback modes."""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from tgarchive.services import bot_detection
from tgarchive.services.bot_detection import (
    NUMPY_AVAILABLE,
    _calculate_autocorrelation,
    _calculate_hour_histogram,
    _calculate_intervals,
    _calculate_message_interval_regularity,
    _calculate_vocabulary_diversity,
    _calculate_content_repetition,
    _calculate_activity_patterns,
    _calculate_response_time,
    _calculate_edit_behavior,
    detect_bot_behavior,
)


class TestBotDetection(unittest.TestCase):
    def setUp(self):
        self.base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_calculate_intervals(self):
        timestamps = [self.base_time + timedelta(seconds=i * 60) for i in range(5)]
        intervals = _calculate_intervals(timestamps)
        self.assertEqual(list(intervals), [60.0, 60.0, 60.0, 60.0])

        # Test empty or single element
        self.assertEqual(len(_calculate_intervals([])), 0)
        self.assertEqual(len(_calculate_intervals([self.base_time])), 0)

    def test_message_interval_regularity_exact_bot(self):
        # Precise 60 second intervals -> bot-like (CV = 0)
        timestamps = [self.base_time + timedelta(seconds=i * 60) for i in range(10)]
        result = _calculate_message_interval_regularity(timestamps)
        self.assertEqual(result["score"], 0.95)
        self.assertEqual(result["cv"], 0.0)
        self.assertEqual(result["mean_interval_seconds"], 60.0)
        self.assertEqual(result["std_dev_seconds"], 0.0)
        self.assertIn("Extremely regular timing", result["detail"])

    def test_message_interval_regularity_human(self):
        # Highly irregular intervals
        deltas = [0, 5, 200, 300, 1500, 1505, 5000, 12000]
        timestamps = [self.base_time + timedelta(seconds=d) for d in deltas]
        result = _calculate_message_interval_regularity(timestamps)
        self.assertLessEqual(result["score"], 0.2)
        self.assertGreater(result["cv"], 0.5)
        self.assertIn("human-like", result["detail"])

    def test_message_interval_regularity_insufficient_messages(self):
        timestamps = [self.base_time, self.base_time + timedelta(seconds=60)]
        result = _calculate_message_interval_regularity(timestamps)
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["detail"], "Insufficient messages for timing analysis")

    def test_message_interval_regularity_zero_mean(self):
        timestamps = [self.base_time, self.base_time, self.base_time]
        result = _calculate_message_interval_regularity(timestamps)
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["detail"], "All messages at same timestamp")

    def test_autocorrelation(self):
        # Periodic series
        series = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
        autocorr = _calculate_autocorrelation(series, max_lag=4)
        self.assertEqual(len(autocorr), 4)
        self.assertLess(autocorr[0], 0)  # lag 1 negative
        self.assertGreater(autocorr[1], 0)  # lag 2 positive

        # Short series
        self.assertEqual(_calculate_autocorrelation([1.0, 2.0]), [])

        # Constant series
        constant_autocorr = _calculate_autocorrelation([5.0] * 10, max_lag=3)
        self.assertEqual(constant_autocorr, [0.0, 0.0, 0.0])

    def test_hour_histogram(self):
        timestamps = [
            datetime(2026, 1, 1, h, 0, 0, tzinfo=timezone.utc)
            for h in [8, 8, 9, 10, 10, 10, 15]
        ]
        hist = _calculate_hour_histogram(timestamps)
        self.assertEqual(hist, {8: 2, 9: 1, 10: 3, 15: 1})
        self.assertEqual(_calculate_hour_histogram([]), {})

    def test_activity_patterns(self):
        # Continuous activity across all 24 hours without sleep gap
        timestamps_24h = [
            datetime(2026, 1, 1, h, 0, 0, tzinfo=timezone.utc) for h in range(24)
        ]
        result = _calculate_activity_patterns(timestamps_24h)
        self.assertEqual(result["active_hours"], 24)
        self.assertFalse(result["has_sleep_gap"])
        self.assertEqual(result["score"], 0.9)

        # Human with sleep gap
        timestamps_human = [
            datetime(2026, 1, 1, h, 0, 0, tzinfo=timezone.utc) for h in range(9, 19)
        ]
        result_human = _calculate_activity_patterns(timestamps_human)
        self.assertEqual(result_human["active_hours"], 10)
        self.assertTrue(result_human["has_sleep_gap"])
        self.assertEqual(result_human["score"], 0.1)

    def test_fallback_parity(self):
        # Ensure pure-python fallback produces exact same results as numpy
        timestamps = [
            self.base_time + timedelta(seconds=s)
            for s in [0, 60, 125, 185, 240, 310, 370, 430, 500, 560]
        ]
        with patch.object(bot_detection, "NUMPY_AVAILABLE", True):
            res_np = _calculate_message_interval_regularity(timestamps)
            hist_np = _calculate_hour_histogram(timestamps)
            act_np = _calculate_activity_patterns(timestamps)
            corr_np = _calculate_autocorrelation([10.0, 20.0, 15.0, 30.0, 25.0, 40.0])

        with patch.object(bot_detection, "NUMPY_AVAILABLE", False), patch.object(bot_detection, "np", None):
            res_py = _calculate_message_interval_regularity(timestamps)
            hist_py = _calculate_hour_histogram(timestamps)
            act_py = _calculate_activity_patterns(timestamps)
            corr_py = _calculate_autocorrelation([10.0, 20.0, 15.0, 30.0, 25.0, 40.0])

        self.assertEqual(res_np, res_py)
        self.assertEqual(hist_np, hist_py)
        self.assertEqual(act_np, act_py)
        self.assertEqual(corr_np, corr_py)

    def test_detect_bot_behavior_database(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        try:
            conn = sqlite3.connect(db_path)
            conn.executescript("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                type TEXT NOT NULL,
                date TEXT NOT NULL,
                edit_date TEXT,
                content TEXT,
                reply_to INTEGER,
                user_id INTEGER
            );
            """)
            # User 100: Automated bot (exact intervals, repetitive content, 24h)
            for i in range(25):
                dt_str = (self.base_time + timedelta(hours=i % 24, seconds=i * 60)).isoformat()
                conn.execute(
                    "INSERT INTO messages VALUES (?, 'text', ?, NULL, 'Automated status broadcast update', NULL, 100)",
                    (i + 1, dt_str),
                )

            # User 200: Human (< 5 messages, should be filtered by query)
            conn.execute(
                "INSERT INTO messages VALUES (101, 'text', '2026-01-01T10:00:00', NULL, 'Hi there!', NULL, 200)"
            )
            conn.commit()
            conn.close()

            # Scan all users
            result = detect_bot_behavior(db_path, scan_all=True)
            self.assertIn("results", result)
            self.assertIn("summary", result)
            self.assertEqual(result["summary"]["users_analyzed"], 1)
            bot_user = result["results"][0]
            self.assertEqual(bot_user["user_id"], 100)
            self.assertIn(bot_user["verdict"], ["bot_likely", "bot_possible"])

            # Single user query
            single_res = detect_bot_behavior(db_path, user_id=100)
            self.assertEqual(len(single_res["results"]), 1)
            self.assertEqual(single_res["results"][0]["user_id"], 100)

            # Single user with < 5 messages
            skip_res = detect_bot_behavior(db_path, user_id=200)
            self.assertEqual(len(skip_res["results"]), 0)
            self.assertEqual(skip_res["summary"]["users_analyzed"], 0)

        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


if __name__ == "__main__":
    unittest.main()
