"""
File Type Sorter for SPECTRA
============================

This module contains the FileTypeSorter class for sorting files by type.
"""

import magic
import os
import logging

logger = logging.getLogger(__name__)

class FileTypeSorter:
    """
    A class for sorting files by type.
    Custom categories can be added to the `extension_mapping` section of the `spectra_config.json` file.
    """
    def __init__(self, config):
        self.config = config
        self.extension_mapping = self.config.get("file_sorter", {}).get("extension_mapping", {})

    def get_file_category(self, file_path, db):
        """
        Gets the category of a file and updates statistics.
        """
        category = "unknown"
        _, ext = os.path.splitext(file_path)
        for cat, extensions in self.extension_mapping.items():
            if ext in extensions:
                category = cat
                break

        # If the category is still unknown, try to determine it using python-magic
        if category == "unknown":
            try:
                mime = magic.from_file(file_path, mime=True)
                category = mime.split('/')[0]
            except Exception as e:
                logger.error(f"Error getting MIME type for {file_path}: {e}")

        # Update statistics in the database
        if db:
            try:
                file_size = os.path.getsize(file_path)
                db.update_category_stats(category, file_size)
            except Exception as e:
                logger.error(f"Error updating category stats for {file_path}: {e}")

        return category
