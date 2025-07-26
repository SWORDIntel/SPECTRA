import unittest
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock
from tgarchive.group_manager import GroupManager
from tgarchive.db import SpectraDB

class TestGroupManager(unittest.TestCase):
    def setUp(self):
        self.config = {
            "file_sorter": {
                "group_naming_template": "TEST-{category}",
                "group_description_template": "Test group for {category}",
                "group_creation_rate_limit_seconds": 0
            }
        }
        self.db_path = "test.db"
        self.db = SpectraDB(self.db_path)
        self.client = AsyncMock()
        self.group_manager = GroupManager(self.config, self.db, self.client)

    def tearDown(self):
        os.remove(self.db_path)

    def test_create_category_group(self):
        async def run_test():
            self.client.return_value = MagicMock(chats=[MagicMock(id=123)])
            group_id = await self.group_manager.create_category_group("test")
            self.assertEqual(group_id, 123)
            self.client.assert_called_once()
            self.assertEqual(self.db.get_group_id_for_category("test"), 123)
        asyncio.run(run_test())

    def test_check_or_create_group_existing(self):
        async def run_test():
            self.db.add_category_to_group_mapping("test", 456)
            group_id = await self.group_manager.check_or_create_group("test")
            self.assertEqual(group_id, 456)
            self.client.assert_not_called()
        asyncio.run(run_test())

    def test_check_or_create_group_new(self):
        async def run_test():
            self.client.return_value = MagicMock(chats=[MagicMock(id=789)])
            group_id = await self.group_manager.check_or_create_group("test")
            self.assertEqual(group_id, 789)
            self.client.assert_called_once()
        asyncio.run(run_test())

if __name__ == '__main__':
    unittest.main()
