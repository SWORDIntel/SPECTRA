import unittest
import json
import os
from tgarchive.db import SpectraDB
from tgarchive.notifications import NotificationManager

class TestChannelForwardingScheduler(unittest.TestCase):
    def setUp(self):
        self.db_path = "test.db"
        self.db = SpectraDB(self.db_path)
        self.config = {
            "notifications": {
                "enabled": True,
                "provider": "placeholder"
            }
        }
        self.notification_manager = NotificationManager(self.config.get("notifications", {}))

    def tearDown(self):
        os.remove(self.db_path)

    def test_add_channel_forward_schedule(self):
        self.db.add_channel_forward_schedule(123, "dest", "* * * * *")
        schedules = self.db.get_channel_forward_schedules()
        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0][1], 123)

    def test_notification_manager(self):
        # This is a simple test to ensure the placeholder provider works.
        # A more comprehensive test would require mocking the notification providers.
        self.notification_manager.send("test message")

if __name__ == '__main__':
    unittest.main()
