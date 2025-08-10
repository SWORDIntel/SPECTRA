import unittest
import json
from tgarchive.config_models import Config
from pathlib import Path

class TestConfigManagement(unittest.TestCase):
    def setUp(self):
        self.config_path = Path("test_config.json")
        with open(self.config_path, "w") as f:
            json.dump({
                "forwarding_mode": {
                    "enabled": True
                },
                "scheduler": {
                    "enabled": True,
                    "timezone": "America/New_York",
                    "state_file": "test_state.json",
                    "bandwidth_limit_kbps": 1024,
                    "schedule_check_interval_seconds": 30,
                    "max_concurrent_forwards": 8,
                    "error_retry_attempts": 5
                },
                "file_sorter": {
                    "sorting_enabled": False,
                    "group_creation_enabled": False
                },
                "migration_mode": {
                    "use_parallel": True
                }
            }, f)
        self.config = Config(self.config_path)

    def tearDown(self):
        import os
        os.remove(self.config_path)

    def test_config_loading(self):
        self.assertEqual(self.config.data["forwarding_mode"]["enabled"], True)
        self.assertEqual(self.config.data["scheduler"]["timezone"], "America/New_York")
        self.assertEqual(self.config.data["file_sorter"]["sorting_enabled"], False)
        self.assertEqual(self.config.data["migration_mode"]["use_parallel"], True)

if __name__ == '__main__':
    unittest.main()
