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
    def test_scan_channel(
        self,
        mock_get_fuzzy_hash,
        mock_get_perceptual_hash,
        mock_is_exact_match,
        mock_get_sha256_hash,
    ):
        channel = "test_channel"
        message = Mock()
        message.file.name = "test_file.txt"
        message.file.id = "file123"

        async def mock_iter_messages(*args, **kwargs):
            yield message

        self.client.iter_messages = mock_iter_messages
        self.client.download_media = AsyncMock()

        mock_get_sha256_hash.return_value = "sha256_hash"
        mock_is_exact_match.return_value = False
        mock_get_perceptual_hash.return_value = "perceptual_hash"
        mock_get_fuzzy_hash.return_value = "fuzzy_hash"

        async def run_test():
            await self.scanner.scan_channel(channel, rate_limit_seconds=0)

        asyncio.run(run_test())

        self.client.download_media.assert_called_once()
        mock_get_sha256_hash.assert_called_once()
        mock_is_exact_match.assert_called_once_with(self.db, "sha256_hash")
        mock_get_perceptual_hash.assert_called_once()
        mock_get_fuzzy_hash.assert_called_once()
        self.db.add_file_hash.assert_called_once_with(
            file_id="file123",
            sha256_hash="sha256_hash",
            perceptual_hash="perceptual_hash",
            fuzzy_hash="fuzzy_hash",
        )

if __name__ == "__main__":
    unittest.main()
