import asyncio
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from tgarchive.core.config_models import Config
from tgarchive.forwarding.forwarder import AttachmentForwarder


class MockFile:
    def __init__(self, name: str, size: int = 0):
        self.name = name
        self.size = size


class MockMessage:
    def __init__(
        self,
        message_id: int,
        *,
        text: str = "",
        has_media: bool = False,
        reply_to_top_id=None,
        size: int = 0,
    ):
        self.id = message_id
        self.text = text
        self.message = text
        self.date = datetime.now(timezone.utc)
        self.sender_id = 1
        self.reply_to_top_id = reply_to_top_id
        self.media = MagicMock(name=f"media-{message_id}") if has_media else None
        self.file = MockFile(f"file-{message_id}.bin", size=size) if has_media else None


class TestForwardingTopics(unittest.TestCase):
    def setUp(self):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        self.config = Config(path=mock_path)
        self.config.data["accounts"] = [{"api_id": 1, "api_hash": "hash", "session_name": "test"}]
        self.config.data.setdefault("forwarding", {})
        self.config.data["forwarding"]["forward_with_attribution"] = False

    def test_topic_forwarding_filters_source_topic_and_targets_destination_topic(self):
        asyncio.run(self._test_topic_forwarding_filters_source_topic_and_targets_destination_topic())

    async def _test_topic_forwarding_filters_source_topic_and_targets_destination_topic(self):
        forwarder = AttachmentForwarder(
            config=self.config,
            db=None,
            enable_deduplication=False,
            source_topic_id=101,
            destination_topic_id=202,
        )

        client = MagicMock()
        client.is_connected.return_value = True
        client.get_entity = AsyncMock(side_effect=[MagicMock(id=10), MagicMock(id=20)])
        client.forward_messages = AsyncMock()
        client.send_message = AsyncMock()

        messages = [
            MockMessage(1, text="topic text", reply_to_top_id=101),
            MockMessage(2, text="topic media", has_media=True, reply_to_top_id=101, size=4096),
            MockMessage(3, text="other topic", has_media=True, reply_to_top_id=303, size=128),
        ]

        async def iter_messages(*args, **kwargs):
            for message in messages:
                yield message

        client.iter_messages = iter_messages
        forwarder.client_manager.get_client = AsyncMock(return_value=client)
        forwarder.client_manager.close = AsyncMock()

        last_message_id, stats = await forwarder.forward_messages(
            origin_id="@origin",
            destination_id="@destination",
        )

        self.assertEqual(last_message_id, 1)
        self.assertEqual(stats["messages_forwarded"], 2)
        self.assertEqual(stats["files_forwarded"], 1)
        self.assertEqual(stats["bytes_forwarded"], 4096)
        self.assertEqual(client.forward_messages.await_count, 2)
        client.send_message.assert_not_called()
        for call in client.forward_messages.await_args_list:
            self.assertEqual(call.kwargs["reply_to"], 202)

    def test_copy_mode_posts_without_forward_header(self):
        asyncio.run(self._test_copy_mode_posts_without_forward_header())

    async def _test_copy_mode_posts_without_forward_header(self):
        forwarder = AttachmentForwarder(
            config=self.config,
            db=None,
            enable_deduplication=False,
            destination_topic_id=707,
            copy_messages_into_destination=True,
            include_text_messages=True,
        )

        client = MagicMock()
        client.is_connected.return_value = True
        client.get_entity = AsyncMock(side_effect=[MagicMock(id=11), MagicMock(id=22)])
        client.forward_messages = AsyncMock()
        client.send_message = AsyncMock()

        message = MockMessage(55, text="copy me", has_media=False)

        async def iter_messages(*args, **kwargs):
            yield message

        client.iter_messages = iter_messages
        forwarder.client_manager.get_client = AsyncMock(return_value=client)
        forwarder.client_manager.close = AsyncMock()

        await forwarder.forward_messages(origin_id="@origin", destination_id="@destination")

        client.forward_messages.assert_not_called()
        client.send_message.assert_awaited_once()
        send_call = client.send_message.await_args
        self.assertEqual(send_call.kwargs["message"], "copy me")
        self.assertEqual(send_call.kwargs["reply_to"], 707)


if __name__ == "__main__":
    unittest.main()
