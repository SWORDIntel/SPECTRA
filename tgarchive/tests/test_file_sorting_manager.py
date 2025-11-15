import unittest
import os
import shutil
from pathlib import Path

from tgarchive.services.file_sorting_manager import FileSortingManager
from tgarchive.core.config_models import Config
from tgarchive.db.spectra_db import SpectraDB

class TestFileSortingManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_sorting_temp_dir")
        self.output_dir = self.test_dir / "output"
        os.makedirs(self.test_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        self.config_data = {
            "file_sorter": {
                "extension_mapping": {
                    "documents": [".pdf", ".docx"],
                    "archives": [".zip", ".tar.gz", ".7z"]
                }
            }
        }
        self.db = SpectraDB(":memory:")

        self.sorting_manager = FileSortingManager(
            config=self.config_data,
            output_dir=str(self.output_dir),
            db=self.db
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_file_sorting(self):
        # Create dummy files
        files_to_create = {
            "doc.pdf": "documents",
            "archive.tar.gz": "archives",
            "multi-part.7z.001": "archives",
            "unknown_file.xyz": "application", # python-magic identifies this as application/octet-stream
            "text.txt": "text" # Should be categorized by python-magic
        }

        for filename, category in files_to_create.items():
            file_path = self.test_dir / filename
            if filename == "unknown_file.xyz":
                with open(file_path, "wb") as f:
                    f.write(os.urandom(16))
            else:
                with open(file_path, "w") as f:
                    f.write("dummy content")

            self.sorting_manager.process_file(str(file_path))

            # Assert file was moved to the correct directory
            expected_dir = self.output_dir / category
            expected_path = expected_dir / filename

            self.assertTrue(os.path.exists(expected_path), f"File '{filename}' not found at '{expected_path}'")
            self.assertFalse(os.path.exists(file_path))

if __name__ == '__main__':
    unittest.main()
