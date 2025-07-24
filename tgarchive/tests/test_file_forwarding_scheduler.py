import unittest
import os
from tgarchive.db import SpectraDB

class TestFileForwardingScheduler(unittest.TestCase):
    def setUp(self):
        self.db_path = "test.db"
        self.db = SpectraDB(self.db_path)

    def tearDown(self):
        os.remove(self.db_path)

    def test_add_file_forward_schedule(self):
        self.db.add_file_forward_schedule("source", "dest", "* * * * *", "image/jpeg", 1024, 2048, 1)
        schedules = self.db.get_file_forward_schedules()
        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0][1], "source")

    def test_add_to_file_forward_queue(self):
        self.db.add_file_forward_schedule("source", "dest", "* * * * *", None, None, None, 0)
        schedules = self.db.get_file_forward_schedules()
        schedule_id = schedules[0][0]
        self.db.add_to_file_forward_queue(schedule_id, 123, "file_id")
        queue = self.db.get_file_forward_queue()
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0][2], 123)

    def test_update_file_forward_queue_status(self):
        self.db.add_file_forward_schedule("source", "dest", "* * * * *", None, None, None, 0)
        schedules = self.db.get_file_forward_schedules()
        schedule_id = schedules[0][0]
        self.db.add_to_file_forward_queue(schedule_id, 123, "file_id")
        queue = self.db.get_file_forward_queue()
        queue_id = queue[0][0]
        self.db.update_file_forward_queue_status(queue_id, "success")
        queue = self.db.get_file_forward_queue()
        self.assertEqual(len(queue), 0)
        status = self.db.get_file_forward_queue_status_by_schedule_id(schedule_id)
        self.assertEqual(status[0][2], "success")

if __name__ == '__main__':
    unittest.main()
