import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from tgarchive.group_mirror import GroupMirrorManager
from tgarchive.config_models import Config
from telethon.tl.types import User, Channel, UpdateNewChannelMessage, MessageActionTopicCreate

# Mock objects for Telethon types
class MockSender(User):
    def __init__(self, id, first_name, last_name=None, access_hash=0, username=None):
        super().__init__(id=id, first_name=first_name, last_name=last_name, access_hash=access_hash, username=username)

class MockMessage:
    def __init__(self, id, text, sender, media=None, reply_to=None, is_topic_message=False):
        self.id = id
        self.text = text
        self._sender = sender
        self.media = media
        self.reply_to = reply_to
        self.is_topic_message = is_topic_message
        self.is_reply = reply_to is not None

    async def get_sender(self):
        return self._sender

class MockTopic:
    def __init__(self, id, title):
        self.id = id
        self.title = title

class MockUpdates:
    def __init__(self, new_topic_id):
        class MockUpdate(UpdateNewChannelMessage):
            def __init__(self, topic_id):
                self.message = MockMessage(id=topic_id, text="", sender=None)
                self.message.action = MessageActionTopicCreate(title="dummy")
                self.pts = 1
                self.pts_count = 1
        self.updates = [MockUpdate(new_topic_id)]
        self.users = []
        self.chats = []
        self.date = 0

# Helper for mocking async iterators
class MockAsyncIterator:
    def __init__(self, items):
        self._items = items
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index < len(self._items):
            item = self._items[self._index]
            self._index += 1
            return item
        else:
            raise StopAsyncIteration


class TestGroupMirrorManager(unittest.TestCase):
    def setUp(self):
        self.config = Config(data={'accounts': [
            {'session_name': 'source_acc', 'api_id': 1, 'api_hash': 'a'},
            {'session_name': 'dest_acc', 'api_id': 2, 'api_hash': 'b'}
        ]})
        self.db = MagicMock()
        self.manager = GroupMirrorManager(
            config=self.config,
            db=self.db,
            source_account_id='source_acc',
            dest_account_id='dest_acc'
        )

    @patch('tgarchive.group_mirror.GroupMirrorManager._get_client_for_account', new_callable=AsyncMock)
    def test_connect(self, mock_get_client):
        async def run_test():
            await self.manager.connect()
            self.assertEqual(mock_get_client.call_count, 2)
            mock_get_client.assert_any_call('source_acc')
            mock_get_client.assert_any_call('dest_acc')
            self.assertIsNotNone(self.manager.source_client)
            self.assertIsNotNone(self.manager.dest_client)
        asyncio.run(run_test())

    def test_get_sender_name(self):
        sender_user = MockSender(id=1, first_name="John", last_name="Doe")
        self.assertEqual(self.manager._get_sender_name(sender_user), "John Doe")

        sender_channel = MagicMock(spec=Channel)
        sender_channel.title = "Test Channel"
        self.assertEqual(self.manager._get_sender_name(sender_channel), "Test Channel")

    def test_mirror_group_logic(self):
        async def run_test():
            # Setup mocks
            self.manager.source_client = AsyncMock()
            self.manager.dest_client = AsyncMock()

            # Mock entities
            mock_source_channel = MagicMock(spec=Channel)
            mock_source_channel.id = 123
            mock_source_channel.forum = True
            mock_dest_channel = MagicMock(spec=Channel)
            mock_dest_channel.id = 456
            mock_dest_channel.forum = True

            self.manager.source_client.get_entity.return_value = mock_source_channel
            self.manager.dest_client.get_entity.return_value = mock_dest_channel

            # Mock DB
            self.db.get_mirror_progress.return_value = None # Test the creation path

            # Mock topics
            mock_source_topics_response = MagicMock()
            mock_source_topics_response.topics = [MockTopic(10, 'Topic 1')]

            mock_dest_topics_response = MagicMock()
            mock_dest_topics_response.topics = []

            async def client_side_effect(request):
                from telethon.tl.functions.channels import GetForumTopicsRequest, CreateForumTopicRequest
                if isinstance(request, GetForumTopicsRequest):
                    # This mock is simplistic. A real scenario might need to differentiate client calls.
                    if 'channel' in request.to_dict() and request.channel == mock_source_channel:
                         return mock_source_topics_response
                    else:
                         return mock_dest_topics_response
                elif isinstance(request, CreateForumTopicRequest):
                    return MockUpdates(20) # 20 is the new topic ID
                return MagicMock()

            self.manager.source_client.side_effect = client_side_effect
            self.manager.dest_client.side_effect = client_side_effect

            # Mock messages
            sender = MockSender(id=999, first_name="Test", last_name="User")
            messages = [
                MockMessage(1, "Hello", sender),
                MockMessage(2, "World", sender, media=b'some_data')
            ]
            # Replace the mock attribute with a standard MagicMock to avoid the async-for-coroutine issue
            self.manager.source_client.iter_messages = MagicMock(return_value=MockAsyncIterator(messages))
            self.manager.source_client.download_media = AsyncMock(return_value=b'some_data')

            # Run mirror
            await self.manager.mirror_group('source_group', 'dest_group')

            # Assertions
            self.db.get_mirror_progress.assert_called_once_with('123', '456')
            self.db.add_mirror_progress.assert_called_once_with('123', '456', 'in_progress')

            # Check send_file calls
            self.assertEqual(self.manager.dest_client.send_file.call_count, 2)

            # First call
            self.manager.dest_client.send_file.assert_any_call(
                mock_dest_channel,
                file=None,
                caption="**Test User**: Hello",
                reply_to=None
            )
            # Second call
            self.manager.dest_client.send_file.assert_any_call(
                mock_dest_channel,
                file=b'some_data',
                caption="**Test User**: World",
                reply_to=None
            )

            # Check DB updates
            self.db.update_mirror_progress.assert_any_call('123', '456', 1)
            self.db.update_mirror_progress.assert_any_call('123', '456', 2)

        asyncio.run(run_test())

    def test_mirror_group_resume_logic(self):
        async def run_test():
            # Setup mocks
            self.manager.source_client = AsyncMock()
            self.manager.dest_client = AsyncMock()

            # Mock entities
            mock_source_channel = MagicMock(spec=Channel)
            mock_source_channel.id = 123
            mock_source_channel.forum = True
            mock_dest_channel = MagicMock(spec=Channel)
            mock_dest_channel.id = 456
            mock_dest_channel.forum = True

            self.manager.source_client.get_entity.return_value = mock_source_channel
            self.manager.dest_client.get_entity.return_value = mock_dest_channel

            # Mock DB to return existing progress
            self.db.get_mirror_progress.return_value = 1

            # Mock topics (simplified as we're not testing topic creation here)
            self.manager._mirror_topics = AsyncMock(return_value={})

            # Mock messages
            sender = MockSender(id=999, first_name="Test", last_name="User")
            messages = [
                MockMessage(2, "World", sender, media=b'some_data')
            ]
            self.manager.source_client.iter_messages = MagicMock(return_value=MockAsyncIterator(messages))
            self.manager.source_client.download_media = AsyncMock(return_value=b'some_data')

            # Run mirror
            await self.manager.mirror_group('source_group', 'dest_group')

            # Assertions
            self.db.get_mirror_progress.assert_called_once_with('123', '456')
            self.db.add_mirror_progress.assert_not_called() # Should not be called when resuming
            self.manager.source_client.iter_messages.assert_called_once_with(mock_source_channel, min_id=1, reverse=True)

            # Check send_file calls
            self.assertEqual(self.manager.dest_client.send_file.call_count, 1)

            # Check that only the second message was sent
            self.manager.dest_client.send_file.assert_called_once_with(
                mock_dest_channel,
                file=b'some_data',
                caption="**Test User**: World",
                reply_to=None
            )

            # Check DB updates
            self.db.update_mirror_progress.assert_called_once_with('123', '456', 2)

        asyncio.run(run_test())

    def test_mirror_group_not_a_forum(self):
        async def run_test():
            # Setup mocks
            self.manager.source_client = AsyncMock()
            self.manager.dest_client = AsyncMock()

            # Mock entities where one is not a forum
            mock_source_channel = MagicMock(spec=Channel)
            mock_source_channel.id = 123
            mock_source_channel.forum = False # Not a forum
            mock_dest_channel = MagicMock(spec=Channel)
            mock_dest_channel.id = 456
            mock_dest_channel.forum = True

            self.manager.source_client.get_entity.return_value = mock_source_channel
            self.manager.dest_client.get_entity.return_value = mock_dest_channel

            # Run mirror
            await self.manager.mirror_group('source_group', 'dest_group')

            # Assertions
            self.manager.source_client.iter_messages.assert_not_called()
            self.manager.dest_client.send_file.assert_not_called()

        asyncio.run(run_test())

    def test_mirror_group_account_not_found(self):
        async def run_test():
            with self.assertRaises(ValueError):
                await self.manager._get_client_for_account('non_existent_account')

        asyncio.run(run_test())

    def test_mirror_topics_existing_topic(self):
        async def run_test():
            # Setup mocks
            self.manager.source_client = AsyncMock()
            self.manager.dest_client = AsyncMock()

            # Mock entities
            mock_source_channel = MagicMock(spec=Channel)
            mock_source_channel.id = 123
            mock_dest_channel = MagicMock(spec=Channel)
            mock_dest_channel.id = 456

            # Mock topics
            mock_source_topics_response = MagicMock()
            mock_source_topics_response.topics = [MockTopic(10, 'Existing Topic')]

            mock_dest_topics_response = MagicMock()
            mock_dest_topics_response.topics = [MockTopic(20, 'Existing Topic')] # Same name

            async def client_side_effect(request):
                from telethon.tl.functions.channels import GetForumTopicsRequest, CreateForumTopicRequest
                if isinstance(request, GetForumTopicsRequest):
                    if 'channel' in request.to_dict() and request.channel == mock_source_channel:
                         return mock_source_topics_response
                    else:
                         return mock_dest_topics_response
                return MagicMock()

            self.manager.source_client.side_effect = client_side_effect
            self.manager.dest_client.side_effect = client_side_effect

            # Run mirror_topics
            topic_map = await self.manager._mirror_topics(mock_source_channel, mock_dest_channel)

            # Assertions
            self.manager.dest_client.assert_any_call(unittest.mock.ANY) # Should be called for GetForumTopicsRequest
            # Should not be called for CreateForumTopicRequest
            self.assertEqual(sum(1 for call in self.manager.dest_client.call_args_list if "CreateForumTopicRequest" in str(call)), 0)
            self.assertEqual(topic_map, {10: 20})

        asyncio.run(run_test())


if __name__ == '__main__':
    unittest.main()
