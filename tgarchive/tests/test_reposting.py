import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from telethon.errors.rpcerrorlist import MessageDeleteForbiddenError

from tgarchive.forwarding import AttachmentForwarder
from tgarchive.core.config_models import Config
from tgarchive.tests.test_forwarding_grouping import MockMessage

class TestReposting(unittest.TestCase):

    def setUp(self):
        mock_config_data = {
            "accounts": [{"api_id": 123, "api_hash": "abc", "session_name": "test"}],
        }
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = '{}'
        self.config = Config(path=mock_path)
        self.config.data.update(mock_config_data)
        self.forwarder = AttachmentForwarder(config=self.config, db=None)
        self.client = AsyncMock()

    @patch('tgarchive.forwarding.AttachmentForwarder._get_client')
    def test_repost_messages(self, mock_get_client):
        mock_get_client.return_value = self.client
        asyncio.run(self._test_repost_messages())

    async def _test_repost_messages(self):
        channel_id = 12345
        messages = [
            MockMessage(id=1, date="2024-01-01", sender_id=1, text="Message 1"),
            MockMessage(id=2, date="2024-01-02", sender_id=1, text="Message 2"),
        ]

        async def mock_iter_messages(entity):
            for msg in messages:
                yield msg

        self.client.iter_messages = mock_iter_messages
        self.client.get_entity.return_value = MagicMock(id=channel_id)
        self.client.send_message = AsyncMock()
        self.client.delete_messages = AsyncMock()

        await self.forwarder.repost_messages_in_channel(channel_id)

        self.assertEqual(self.client.send_message.call_count, 2)
        self.assertEqual(self.client.delete_messages.call_count, 2)

        # Check the first call
        self.client.send_message.assert_any_call(entity=self.client.get_entity.return_value, message="Message 1", file=None)
        self.client.delete_messages.assert_any_call(self.client.get_entity.return_value, [1])

        # Check the second call
        self.client.send_message.assert_any_call(entity=self.client.get_entity.return_value, message="Message 2", file=None)
        self.client.delete_messages.assert_any_call(self.client.get_entity.return_value, [2])

    @patch('tgarchive.forwarding.AttachmentForwarder._get_client')
    def test_repost_messages_delete_forbidden(self, mock_get_client):
        mock_get_client.return_value = self.client
        asyncio.run(self._test_repost_messages_delete_forbidden())

    async def _test_repost_messages_delete_forbidden(self):
        channel_id = 12345
        messages = [
            MockMessage(id=1, date="2024-01-01", sender_id=1, text="Message 1"),
            MockMessage(id=2, date="2024-01-02", sender_id=1, text="Message 2"),
        ]

        async def mock_iter_messages(entity):
            for msg in messages:
                yield msg

        self.client.iter_messages = mock_iter_messages
        self.client.get_entity.return_value = MagicMock(id=channel_id)
        self.client.send_message = AsyncMock()
        self.client.delete_messages.side_effect = MessageDeleteForbiddenError(request=None)

        await self.forwarder.repost_messages_in_channel(channel_id)

        self.assertEqual(self.client.send_message.call_count, 1)
        self.assertEqual(self.client.delete_messages.call_count, 1)

if __name__ == '__main__':
    unittest.main()
