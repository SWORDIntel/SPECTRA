import unittest
from unittest.mock import Mock, AsyncMock, patch
import asyncio

from tgarchive.utils.group_manager import GroupManager

class TestGroupManager(unittest.TestCase):
    def setUp(self):
        self.config = {
            "file_sorter": {
                "group_creation_rate_limit_seconds": 0,
                "group_naming_template": "TEST-{category}",
                "group_description_template": "Test group for {category}",
            }
        }
        self.db = Mock()
        self.client = Mock()
        self.group_manager = GroupManager(self.config, self.db, self.client)

    def test_check_or_create_group_existing(self):
        category = "text"
        self.db.get_group_id_for_category.return_value = 123

        async def run_test():
            group_id = await self.group_manager.check_or_create_group(category)
            self.assertEqual(group_id, 123)

        asyncio.run(run_test())
        self.db.get_group_id_for_category.assert_called_once_with(category)

    @patch("telethon.tl.functions.channels.CreateChannelRequest")
    def test_check_or_create_group_new(self, mock_create_channel):
        category = "image"
        self.db.get_group_id_for_category.return_value = None

        mock_response = Mock()
        mock_response.chats = [Mock()]
        mock_response.chats[0].id = 456

        # Make the client an AsyncMock to mock the __call__ method
        self.client = AsyncMock(return_value=mock_response)
        self.group_manager.client = self.client


        async def run_test():
            group_id = await self.group_manager.check_or_create_group(category)
            self.assertEqual(group_id, 456)

        asyncio.run(run_test())

        self.db.get_group_id_for_category.assert_called_once_with(category)
        self.client.assert_called_once()
        self.db.add_category_to_group_mapping.assert_called_once_with(category, 456)


if __name__ == "__main__":
    unittest.main()
