import unittest
import os
from tgarchive.utils.file_sorter import FileTypeSorter
from tgarchive.db import SpectraDB

class TestFileTypeSorter(unittest.TestCase):
    def setUp(self):
        self.config = {
            "file_sorter": {
                "extension_mapping": {
                    "text": [".txt"],
                    "pdf": [".pdf"],
                    "archive": [".zip"],
                    "image": [".jpg"],
                    "video": [".mp4"],
                    "document": [".doc"],
                    "source_code": [".py"],
                }
            }
        }
        self.sorter = FileTypeSorter(self.config)
        self.db_path = "test.db"
        self.db = SpectraDB(self.db_path)
        with open("test.txt", "w") as f:
            f.write("test")
        with open("test.pdf", "w") as f:
            f.write("test")
        with open("test.zip", "w") as f:
            f.write("test")
        with open("test.jpg", "w") as f:
            f.write("test")
        with open("test.mp4", "w") as f:
            f.write("test")
        with open("test.doc", "w") as f:
            f.write("test")
        with open("test.py", "w") as f:
            f.write("test")
        with open("unknown.xyz", "w") as f:
            f.write("test")

    def tearDown(self):
        os.remove(self.db_path)
        os.remove("test.txt")
        os.remove("test.pdf")
        os.remove("test.zip")
        os.remove("test.jpg")
        os.remove("test.mp4")
        os.remove("test.doc")
        os.remove("test.py")
        os.remove("unknown.xyz")

    def test_file_type_classification(self):
        self.assertEqual(self.sorter.get_file_category("test.txt", self.db), "text")
        self.assertEqual(self.sorter.get_file_category("test.pdf", self.db), "pdf")
        self.assertEqual(self.sorter.get_file_category("test.zip", self.db), "archive")
        self.assertEqual(self.sorter.get_file_category("test.jpg", self.db), "image")
        self.assertEqual(self.sorter.get_file_category("test.mp4", self.db), "video")
        self.assertEqual(self.sorter.get_file_category("test.doc", self.db), "document")
        self.assertEqual(self.sorter.get_file_category("test.py", self.db), "source_code")
        self.assertEqual(self.sorter.get_file_category("unknown.xyz", self.db), "text")

if __name__ == '__main__':
    unittest.main()
