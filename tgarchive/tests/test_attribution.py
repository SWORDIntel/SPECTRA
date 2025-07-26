import unittest
import os
from unittest.mock import MagicMock
from tgarchive.attribution import AttributionFormatter
from tgarchive.db import SpectraDB

class TestAttribution(unittest.TestCase):
    def setUp(self):
        self.config = {
            "attribution": {
                "template": "{sender_name}",
                "timestamp_format": "%Y-%m-%d",
                "preserve_message_id": True,
                "style": "text",
                "disable_attribution_for_groups": [123]
            }
        }
        self.formatter = AttributionFormatter(self.config)
        self.db_path = "test.db"
        self.db = SpectraDB(self.db_path)

    def tearDown(self):
        os.remove(self.db_path)

    def test_format_attribution(self):
        message = MagicMock(id=456)
        attribution = self.formatter.format_attribution(
            message, "source_name", 789, "sender_name", 101, MagicMock(strftime=lambda fmt: "2025-01-01")
        )
        self.assertEqual(attribution, "sender_name")

    def test_attribution_stats(self):
        self.db.update_attribution_stats(123)
        stats = self.db.cur.execute("SELECT attributions_count FROM attribution_stats WHERE source_channel_id = 123").fetchone()
        self.assertEqual(stats[0], 1)
        self.db.update_attribution_stats(123)
        stats = self.db.cur.execute("SELECT attributions_count FROM attribution_stats WHERE source_channel_id = 123").fetchone()
        self.assertEqual(stats[0], 2)

if __name__ == '__main__':
    unittest.main()
