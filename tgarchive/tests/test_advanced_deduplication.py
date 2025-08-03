import unittest
import asyncio
import os
import tempfile
from unittest.mock import MagicMock, AsyncMock
from PIL import Image

from tgarchive.forwarding import AttachmentForwarder
from tgarchive.config_models import Config
from tgarchive.tests.test_forwarding_grouping import MockMessage
import imagehash

class TestAdvancedDeduplication(unittest.TestCase):

    def setUp(self):
        # Basic config
        mock_config_data = {
            "accounts": [{"api_id": 123, "api_hash": "abc", "session_name": "test"}],
            "db_path": "test_adv_dedup.sqlite3",
            "deduplication": {
                "enable_near_duplicates": True,
                "fuzzy_hash_similarity_threshold": 90,
                "perceptual_hash_distance_threshold": 5,
            }
        }

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = '{}'
        self.config = Config(path=mock_path)
        self.config.data.update(mock_config_data)

        # Mock DB
        self.db = MagicMock()

        # Forwarder instance
        self.forwarder = AttachmentForwarder(config=self.config, db=self.db)

        # Mock Client
        self.client = AsyncMock()

    def create_dummy_image(self, path, text="A"):
        img = Image.new('RGB', (100, 30), color = 'red')
        from PIL import ImageDraw
        d = ImageDraw.Draw(img)
        d.text((10,10), text, fill=(255,255,0))
        img.save(path)

    async def _test_near_duplicate_images(self):
        # --- Test Data ---
        message1 = MockMessage(id=1, date="2024-01-01", sender_id=1, filename="image1.png")
        message2 = MockMessage(id=2, date="2024-01-01", sender_id=1, filename="image2.png")

        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = os.path.join(tmpdir, "image1.png")
            path2 = os.path.join(tmpdir, "image2.png")
            self.create_dummy_image(path1, "Slightly different")
            self.create_dummy_image(path2, "Slightly differemt") # Typo to make it different but similar

            phash1 = imagehash.phash(Image.open(path1))

            # --- Mock DB to return the first image's hash ---
            self.db.get_all_perceptual_hashes.return_value = [(1, str(phash1))]
            self.db.conn.execute.return_value.fetchone.return_value = None # No exact match

            # --- Mock download for the second image ---
            async def mock_download(media, file):
                with open(file, "wb") as f:
                    with open(path2, "rb") as f2:
                        f.write(f2.read())
                fut = asyncio.Future()
                fut.set_result(None)
                return fut
            self.client.download_media = mock_download

            # --- Check if the second image is a near-duplicate ---
            is_dup = await self.forwarder._is_duplicate([message2], self.client)
            self.assertTrue(is_dup, "Similar images should be detected as near-duplicates.")

    def test_near_duplicate_images(self):
        asyncio.run(self._test_near_duplicate_images())

    async def _test_near_duplicate_docs(self):
        # --- Test Data ---
        message1 = MockMessage(id=3, date="2024-01-01", sender_id=1, filename="doc1.txt")
        message2 = MockMessage(id=4, date="2024-01-01", sender_id=1, filename="doc2.txt")

        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = os.path.join(tmpdir, "doc1.txt")
            path2 = os.path.join(tmpdir, "doc2.txt")
            with open(path1, "w") as f:
                f.write("This is a test document with a lot of content to make the fuzzy hash meaningful. " * 10)
            with open(path2, "w") as f:
                f.write("This is a test document with a lot of content to make the fuzzy hash meaningful. " * 9 + "Slightly different content.")

            from tgarchive.deduplication import get_fuzzy_hash
            fhash1 = get_fuzzy_hash(path1)

            # --- Mock DB to return the first doc's hash ---
            self.db.get_all_fuzzy_hashes.return_value = [(3, fhash1)]
            self.db.get_all_perceptual_hashes.return_value = [] # No perceptual hashes
            self.db.conn.execute.return_value.fetchone.return_value = None # No exact match

            # --- Mock download for the second doc ---
            async def mock_download(media, file):
                with open(file, "wb") as f:
                    with open(path2, "rb") as f2:
                        f.write(f2.read())
                fut = asyncio.Future()
                fut.set_result(None)
                return fut
            self.client.download_media = mock_download

            # --- Check if the second doc is a near-duplicate ---
            is_dup = await self.forwarder._is_duplicate([message2], self.client)
            self.assertTrue(is_dup, "Similar documents should be detected as near-duplicates.")

    def test_near_duplicate_docs(self):
        asyncio.run(self._test_near_duplicate_docs())

if __name__ == '__main__':
    unittest.main()
