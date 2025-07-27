import unittest
from unittest.mock import Mock, patch
import os
import hashlib

from tgarchive.deduplication import (
    get_sha256_hash,
    get_perceptual_hash,
    get_fuzzy_hash,
    compare_fuzzy_hashes,
    is_exact_match,
    find_near_duplicates,
    get_minhash,
)

class TestDeduplication(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.test_file = "test.txt"
        with open(self.test_file, "w") as f:
            f.write("this is a test file")

    def tearDown(self):
        os.remove(self.test_file)

    def test_get_sha256_hash(self):
        hash_val = get_sha256_hash(self.test_file)
        self.assertEqual(
            hash_val,
            "5881707e54b0112f901bc83a1ffbacac8fab74ea46a6f706a3efc5f7d4c1c625",
        )

    @patch("PIL.Image.open")
    @patch("imagehash.phash")
    def test_get_perceptual_hash(self, mock_phash, mock_open):
        mock_phash.return_value = "d879f8f8f8f8f879"
        hash_val = get_perceptual_hash(self.test_file)
        self.assertEqual(hash_val, "d879f8f8f8f8f879")

    @patch("ssdeep.hash_from_file")
    def test_get_fuzzy_hash(self, mock_hash_from_file):
        mock_hash_from_file.return_value = "3:abc:xyz"
        hash_val = get_fuzzy_hash(self.test_file)
        self.assertEqual(hash_val, "3:abc:xyz")

    def test_compare_fuzzy_hashes(self):
        self.assertEqual(compare_fuzzy_hashes("3:abc:xyz", "3:abc:xyz"), 100)
        self.assertEqual(compare_fuzzy_hashes("3:abc:xyz", "3:def:xyz"), 0)

    def test_is_exact_match(self):
        self.db.cur.fetchone.return_value = (1,)
        self.assertTrue(is_exact_match(self.db, "hash"))
        self.db.cur.fetchone.return_value = None
        self.assertFalse(is_exact_match(self.db, "hash"))

    def test_find_near_duplicates(self):
        self.db.cur.fetchall.return_value = [
            (1, "3:abc:xyz"),
            (2, "3:def:xyz"),
        ]
        duplicates = find_near_duplicates(self.db, "3:abc:xyz")
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0][0], 1)

    def test_get_minhash(self):
        from datasketch import MinHash
        m1 = get_minhash(self.test_file)
        self.assertIsInstance(m1, MinHash)

    def test_get_file_hashes_cache(self):
        from tgarchive.deduplication import get_file_hashes

        self.db.cur.fetchone.return_value = ("hash1", "hash2", "hash3")

        # Call the function twice
        get_file_hashes(self.db, 1)
        get_file_hashes(self.db, 1)

        # Check that the database was only called once
        self.db.cur.execute.assert_called_once()

    def test_get_ngrams(self):
        from tgarchive.deduplication import get_ngrams
        ngrams = get_ngrams("test", n=3)
        self.assertEqual(ngrams, ["tes", "est"])

    @patch("PIL.Image.open")
    def test_get_exif_data(self, mock_open):
        from tgarchive.deduplication import get_exif_data

        mock_image = Mock()
        mock_image._getexif.return_value = {271: "Make", 272: "Model"}
        mock_open.return_value.__enter__.return_value = mock_image

        exif_data = get_exif_data("test.jpg")
        self.assertEqual(exif_data, {"Make": "Make", "Model": "Model"})

if __name__ == "__main__":
    unittest.main()
