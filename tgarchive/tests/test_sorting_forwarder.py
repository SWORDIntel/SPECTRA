import unittest
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock
from tgarchive.sorting_forwarder import SortingForwarder
from tgarchive.file_sorter import FileTypeSorter
from tgarchive.group_manager import GroupManager
from tgarchive.db import SpectraDB
from tgarchive.config_models import Config

class TestSortingForwarder(unittest.TestCase):
    def setUp(self):
        self.config = Config(data={
            "file_sorter": {
                "extension_mapping": {
                    "text": [".txt"]
                }
            }
        })
        self.db_path = "test.db"
        self.db = SpectraDB(self.db_path)
        self.client = AsyncMock()
        self.sorter = FileTypeSorter(self.config.data)
        self.group_manager = GroupManager(self.config.data, self.db, self.client)
        self.forwarder = SortingForwarder(self.config, self.db, self.client, self.sorter, self.group_manager)

    def tearDown(self):
        os.remove(self.db_path)

    def test_sort_and_forward(self):
        async def run_test():
            schedule_id = self.db.add_file_forward_schedule("source", "dest", "* * * * *", None, None, None, 0)
            message = MagicMock()
            message.file.name = "test.txt"
            message.file.id = "file_id"
            message.file.size = 1234
            message.id = 123

            async def mock_iter_messages(*args, **kwargs):
                yield message

            self.client.iter_messages = mock_iter_messages
            self.group_manager.check_or_create_group = AsyncMock(return_value=456)

            await self.forwarder.sort_and_forward("source")

            queue = self.db.get_file_forward_queue()
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0][4], 456)
        asyncio.run(run_test())

if __name__ == '__main__':
    unittest.main()
