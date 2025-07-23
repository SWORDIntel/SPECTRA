import unittest
import json
import os
from datetime import datetime, timedelta
from tgarchive.scheduler_service import SchedulerDaemon
from croniter import croniter

class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.config_path = "test_config.json"
        self.state_path = "test_state.json"
        with open(self.config_path, 'w') as f:
            json.dump({
                "scheduler": {
                    "timezone": "UTC"
                }
            }, f)
        with open(self.state_path, 'w') as f:
            json.dump({"jobs": []}, f)
        self.scheduler = SchedulerDaemon(self.config_path, self.state_path)

    def tearDown(self):
        os.remove(self.config_path)
        os.remove(self.state_path)

    def test_load_jobs(self):
        with open(self.state_path, 'w') as f:
            json.dump({"jobs": [{"name": "test_job"}]}, f)
        jobs = self.scheduler.load_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['name'], "test_job")

    def test_save_jobs(self):
        self.scheduler.jobs = [{"name": "test_job"}]
        self.scheduler.save_jobs()
        with open(self.state_path, 'r') as f:
            state = json.load(f)
            self.assertEqual(len(state['jobs']), 1)
            self.assertEqual(state['jobs'][0]['name'], "test_job")

    def test_cron_matching(self):
        now = datetime.now(self.scheduler.timezone)
        schedule = f"{now.minute} {now.hour} * * *"
        self.assertTrue(croniter.match(schedule, now))

if __name__ == '__main__':
    unittest.main()
