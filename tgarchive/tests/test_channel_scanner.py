import unittest
from unittest.mock import Mock, AsyncMock, patch
import asyncio

from tgarchive.deduplication import ChannelScanner

class TestChannelScanner(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.client = Mock()
        self.scanner = ChannelScanner(self.db, self.client)

    @patch("tgarchive.deduplication.get_sha256_hash")
    @patch("tgarchive.deduplication.is_exact_match")
    @patch("tgarchive.deduplication.get_perceptual_hash")
    @patch("tgarchive.deduplication.get_fuzzy_hash")
    def test_scan_channel_batching(
        self,
        mock_get_fuzzy_hash,
        mock_get_perceptual_hash,
        mock_is_exact_match,
        mock_get_sha256_hash,
    ):
        channel = "test_channel"
        messages = [Mock(), Mock()]
        for i, msg in enumerate(messages):
            msg.file.name = f"test_file_{i}.txt"
            msg.file.id = f"file{i}"

        async def mock_iter_messages(*args, **kwargs):
            for msg in messages:
                yield msg

        self.client.iter_messages = mock_iter_messages
        self.client.download_media = AsyncMock()

        mock_get_sha256_hash.return_value = "sha256_hash"
        mock_is_exact_match.return_value = False
        mock_get_perceptual_hash.return_value = "perceptual_hash"
        mock_get_fuzzy_hash.return_value = "fuzzy_hash"

        async def run_test():
            await self.scanner.scan_channel(channel, batch_size=2, rate_limit_seconds=0)

        asyncio.run(run_test())

        self.assertEqual(self.client.download_media.call_count, 2)
        self.assertEqual(mock_get_sha256_hash.call_count, 2)
        self.assertEqual(mock_is_exact_match.call_count, 2)
        self.assertEqual(mock_get_perceptual_hash.call_count, 2)
        self.assertEqual(mock_get_fuzzy_hash.call_count, 2)
        self.assertEqual(self.db.add_file_hash.call_count, 2)

if __name__ == "__main__":
    unittest.main()
