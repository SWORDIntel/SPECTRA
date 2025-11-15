import unittest
from unittest.mock import Mock, AsyncMock, patch
import asyncio

from tgarchive.utils.sorting_forwarder import SortingForwarder

class TestSortingForwarder(unittest.TestCase):
    def setUp(self):
        self.config = Mock()
        self.config.data = {}
        self.db = Mock()
        self.client = Mock()
        self.sorter = Mock()
        self.group_manager = Mock()
        self.sorting_forwarder = SortingForwarder(
            self.config, self.db, self.client, self.sorter, self.group_manager
        )

    def test_sort_and_forward(self):
        source = "test_source"
        message = Mock()
        message.file.name = "test_file.txt"
        message.file.size = 1024
        message.id = 123
        message.file.id = "file123"

        async def mock_iter_messages(*args, **kwargs):
            yield message

        self.client.iter_messages = mock_iter_messages
        self.client.download_media = AsyncMock()
        self.sorter.get_file_category.return_value = "text"
        self.group_manager.check_or_create_group = AsyncMock(return_value=456)

        async def run_test():
            await self.sorting_forwarder.sort_and_forward(source)

        asyncio.run(run_test())

        self.sorter.get_file_category.assert_called_once()
        self.group_manager.check_or_create_group.assert_called_once_with("text")
        self.db.add_to_file_forward_queue.assert_called_once_with(
            schedule_id=None,
            message_id=123,
            file_id="file123",
            destination=456,
        )
        self.db.add_sorting_audit_log.assert_called_once()
        self.db.add_sorting_stats.assert_called_once()

    def test_sort_and_forward_preview_mode(self):
        source = "test_source"
        message = Mock()
        message.file.name = "test_file.txt"
        message.file.size = 1024

        async def mock_iter_messages(*args, **kwargs):
            yield message

        self.client.iter_messages = mock_iter_messages
        self.client.download_media = AsyncMock()
        self.sorter.get_file_category.return_value = "text"
        self.group_manager.check_or_create_group = AsyncMock(return_value=456)

        async def run_test():
            await self.sorting_forwarder.sort_and_forward(source, preview=True)

        asyncio.run(run_test())

        self.db.add_to_file_forward_queue.assert_not_called()

if __name__ == "__main__":
    unittest.main()
