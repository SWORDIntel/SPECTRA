import unittest
from unittest.mock import Mock, patch
import os

from tgarchive.utils.file_sorter import FileTypeSorter

class TestFileTypeSorter(unittest.TestCase):
    def setUp(self):
        self.config = {
            "file_sorter": {
                "extension_mapping": {
                    "documents": [".pdf", ".docx"],
                    "images": [".jpg", ".png"],
                }
            }
        }
        self.db = Mock()
        self.file_sorter = FileTypeSorter(self.config)

    def test_get_file_category_by_extension(self):
        category = self.file_sorter.get_file_category("test.pdf", self.db)
        self.assertEqual(category, "documents")

    @patch("magic.from_file")
    def test_get_file_category_by_mime_type(self, mock_from_file):
        mock_from_file.return_value = "image/jpeg"
        category = self.file_sorter.get_file_category("test.jpg", self.db)
        self.assertEqual(category, "images")

    @patch("magic.from_file")
    def test_get_file_category_unknown(self, mock_from_file):
        mock_from_file.side_effect = Exception("test error")
        category = self.file_sorter.get_file_category("test.unknown", self.db)
        self.assertEqual(category, "unknown")

    @patch("os.path.getsize")
    @patch("os.path.exists")
    def test_update_category_stats(self, mock_exists, mock_getsize):
        mock_exists.return_value = True
        mock_getsize.return_value = 1024
        self.file_sorter.get_file_category("test.pdf", self.db)
        self.db.update_category_stats.assert_called_once_with("documents", 1024)

if __name__ == "__main__":
    unittest.main()
