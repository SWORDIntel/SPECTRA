import unittest
import asyncio
import os
import tempfile
from unittest.mock import MagicMock, AsyncMock

from tgarchive.forwarding import AttachmentForwarder
from tgarchive.forwarding.deduplication import Deduplicator
from tgarchive.core.config_models import Config
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
        
        # Forwarder instance with deduplicator integration
        self.forwarder = AttachmentForwarder(config=self.config, db=self.db, deduplicator=self.deduplicator)
        
        # Mock Client
        self.client = AsyncMock()

    def test_is_duplicate_and_record_forwarded(self):
        """
        Integration test for deduplication logic using extracted Deduplicator class.
        Tests:
        1. Initial file is not duplicate
        2. Recording forwarded file updates database and cache
        3. Same file becomes duplicate after recording
        4. Database-based duplicate detection works across sessions
        """
        asyncio.run(self._test_is_duplicate_and_record_forwarded())

    async def _test_is_duplicate_and_record_forwarded(self):
        # --- Test Data ---
        origin_id = 12345
        dest_id = "destination_channel"
        message = MockMessage(id=1, date="2024-01-01", sender_id=1, filename="test_file.zip")
        message_group = [message]

        # --- Mock file download setup ---
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create dummy file for testing
            dummy_file_content = b"This is a test file for deduplication."
            dummy_file_path = os.path.join(tmpdir, str(message.file.id))
            with open(dummy_file_path, "wb") as f:
                f.write(dummy_file_content)

            # Expected SHA256 hash for verification
            expected_hash = "54eb06f8cae6f65a20acfbd81127171c6a189bae309e8df214fefeeacd21737e"

            async def mock_download(media, file):
                """Mock download function that writes test content to specified path"""
                with open(file, "wb") as f:
                    f.write(dummy_file_content)
                fut = asyncio.Future()
                fut.set_result(None)
                return fut

            self.client.download_media = mock_download

            # --- Phase 1: Initial duplicate check (should be False) ---
            
            # Configure DB mock: no existing hash found
            self.db.conn.execute.return_value.fetchone.return_value = None
            # Reset in-memory cache
            self.deduplicator.message_hashes = set()

            is_dup_initial = await self.deduplicator.is_duplicate(message_group, self.client)
            self.assertFalse(is_dup_initial, "File should not be duplicate on first check")

            # --- Phase 2: Record forwarded file ---
            
            await self.deduplicator.record_forwarded(message_group, origin_id, dest_id, self.client)

            # Verify database operations
            self.db.add_file_hash.assert_called_once_with(
                file_id=message.file.id,
                sha256_hash=expected_hash,
                perceptual_hash=None,
                fuzzy_hash=None
            )
            self.db.add_channel_file_inventory.assert_called_once_with(
                channel_id=origin_id,
                file_id=message.file.id,
                message_id=message.id,
                topic_id=None
            )

            # --- Phase 3: Memory-based duplicate check (should be True) ---
            
            # Verify hash in memory cache
            self.assertIn(expected_hash, self.deduplicator.message_hashes)

            is_dup_memory = await self.deduplicator.is_duplicate(message_group, self.client)
            self.assertTrue(is_dup_memory, "File should be duplicate after recording (memory cache)")

            # --- Phase 4: Database-based duplicate check (should be True) ---
            
            # Reset memory cache to simulate new session
            self.deduplicator.message_hashes = set()
            # Configure DB mock: hash found in database
            self.db.conn.execute.return_value.fetchone.return_value = (1,)

            is_dup_database = await self.deduplicator.is_duplicate(message_group, self.client)
            self.assertTrue(is_dup_database, "File should be duplicate based on database check")


if __name__ == '__main__':
    unittest.main()
