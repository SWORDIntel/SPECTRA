import unittest
import asyncio
import os
import tempfile
from unittest.mock import MagicMock, AsyncMock

from tgarchive.forwarding.deduplication import Deduplicator
from tgarchive.config_models import Config
from tgarchive.tests.test_forwarding_grouping import MockMessage

class TestNewDeduplication(unittest.TestCase):

    def setUp(self):
        # Basic config
        mock_config_data = {
            "accounts": [{"api_id": 123, "api_hash": "abc", "session_name": "test"}],
            "db_path": "test_dedup.sqlite3"
        }

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = '{}'
        self.config = Config(path=mock_path)
        self.config.data.update(mock_config_data)

        # Mock DB
        self.db = MagicMock()

        # Deduplicator instance
        self.deduplicator = Deduplicator(db=self.db, enable_deduplication=True)

        # Mock Client
        self.client = AsyncMock()

    def test_is_duplicate_and_record_forwarded(self):
        """
        An integration test for the new deduplication logic.
        1. Records a file.
        2. Checks if the same file is now considered a duplicate.
        """
        asyncio.run(self._test_is_duplicate_and_record_forwarded())

    async def _test_is_duplicate_and_record_forwarded(self):
        # --- Test Data ---
        origin_id = 12345
        dest_id = "destination_channel"
        message = MockMessage(id=1, date="2024-01-01", sender_id=1, filename="test_file.zip")
        message_group = [message]

        # --- Mocking file download ---
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a dummy file to be "downloaded"
            dummy_file_content = b"This is a test file for deduplication."
            dummy_file_path = os.path.join(tmpdir, str(message.file.id))
            with open(dummy_file_path, "wb") as f:
                f.write(dummy_file_content)

            # Expected hash for the dummy content
            expected_hash = "54eb06f8cae6f65a20acfbd81127171c6a189bae309e8df214fefeeacd21737e"

            async def mock_download(media, file):
                # Simulate downloading by ensuring the file exists where it's expected
                with open(file, "wb") as f:
                    f.write(dummy_file_content)
                # Create a future and set its result
                fut = asyncio.Future()
                fut.set_result(None)
                return fut

            self.client.download_media = mock_download

            # --- 1. First Pass: Should NOT be a duplicate ---

            # Setup DB mock to return no results for the hash
            self.db.conn.execute.return_value.fetchone.return_value = None
            self.deduplicator.message_hashes = set() # Reset in-memory cache

            is_dup = await self.deduplicator.is_duplicate(message_group, self.client)
            self.assertFalse(is_dup, "File should not be a duplicate on the first check.")

            # --- 2. Record the forwarded file ---
            await self.deduplicator.record_forwarded(message_group, origin_id, dest_id, self.client)

            # Verify that the hash was added to the database
            self.db.add_file_hash.assert_called_once_with(
                file_id=message.file.id,
                sha256_hash=expected_hash,
                perceptual_hash=None,
                fuzzy_hash=None
            )
            # Verify that the inventory was updated
            self.db.add_channel_file_inventory.assert_called_once_with(
                channel_id=origin_id,
                file_id=message.file.id,
                message_id=message.id,
                topic_id=None
            )

            # --- 3. Second Pass: Should NOW be a duplicate ---

            # The hash should now be in the in-memory set
            self.assertIn(expected_hash, self.deduplicator.message_hashes)

            is_dup_after_record = await self.deduplicator.is_duplicate(message_group, self.client)
            self.assertTrue(is_dup_after_record, "File should be a duplicate after being recorded.")

            # --- 4. Test DB-based duplication ---

            # Reset in-memory cache to simulate a new session
            self.deduplicator.message_hashes = set()
            # Setup DB mock to return the hash
            self.db.conn.execute.return_value.fetchone.return_value = (1,) # Simulate finding a row

            is_dup_from_db = await self.deduplicator.is_duplicate(message_group, self.client)
            self.assertTrue(is_dup_from_db, "File should be a duplicate based on the database check.")


if __name__ == '__main__':
    unittest.main()
