import unittest
import os
import json
from tgarchive.file_sorter import FileTypeSorter
from tgarchive.db import SpectraDB

class TestFileSorter(unittest.TestCase):
    def setUp(self):
        self.config = {
            "file_sorter": {
                "extension_mapping": {
                    "text": [".txt"]
                }
            }
        }
        self.sorter = FileTypeSorter(self.config)
        self.db_path = "test.db"
        self.db = SpectraDB(self.db_path)
        with open("test.txt", "w") as f:
            f.write("test")

    def tearDown(self):
        os.remove(self.db_path)
        os.remove("test.txt")

    def test_get_file_category_by_extension(self):
        category = self.sorter.get_file_category("test.txt", self.db)
        self.assertEqual(category, "text")

    def test_get_file_category_by_mime(self):
        # Create a dummy file without an extension
        with open("test", "w") as f:
            f.write("test")
        category = self.sorter.get_file_category("test", self.db)
        self.assertEqual(category, "text")
        os.remove("test")

    def test_category_stats(self):
        self.sorter.get_file_category("test.txt", self.db)
        stats = self.db.cur.execute("SELECT files_count, bytes_count FROM category_stats WHERE category = 'text'").fetchone()
        self.assertEqual(stats[0], 1)
        self.assertEqual(stats[1], 4)

if __name__ == '__main__':
    unittest.main()
