import unittest
import os
from tgarchive.db import SpectraDB
from tgarchive.group_manager import GroupManager

class TestSortingGroups(unittest.TestCase):
    def setUp(self):
        self.db_path = "test.db"
        self.db = SpectraDB(self.db_path)
        self.config = {
            "file_sorter": {
                "default_sorting_groups": {
                    "text_files": "SPECTRA-Text-Files"
                }
            }
        }
        self.group_manager = GroupManager(self.config, self.db, None)

    def tearDown(self):
        os.remove(self.db_path)

    def test_initialize_default_sorting_groups(self):
        self.group_manager.initialize_default_sorting_groups()
        template = self.db.get_sorting_group_template("text_files")
        self.assertEqual(template, "SPECTRA-Text-Files")

if __name__ == '__main__':
    unittest.main()
