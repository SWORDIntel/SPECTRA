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
        self.multipart_exts = {f".{i:03d}" for i in range(1, 1000)}
        self.multipart_exts.update({f".r{i:02d}" for i in range(1, 100)})
        self.multipart_exts.update({f".z{i:02d}" for i in range(1, 100)})

    def _get_true_extension(self, file_path: str) -> str:
        """
        Gets the 'true' file extension, handling multi-part archives and combined extensions.
        e.g., 'file.tar.gz' -> '.tar.gz', 'file.7z.001' -> '.7z'
        """
        name, ext = os.path.splitext(file_path)
        if ext in self.multipart_exts:
            # It's a multi-part archive part, get the extension before it
            name, ext = os.path.splitext(name)
            return ext

        # Handle common combined extensions
        if name.endswith('.tar'):
            return '.tar' + ext

        return ext

    @staticmethod
    def _looks_like_text(file_path: str) -> bool:
        try:
            with open(file_path, "rb") as fh:
                sample = fh.read(512)
            if not sample:
                return True
            text_bytes = sum(1 for b in sample if b in b"\n\r\t\f\b" or 32 <= b <= 126)
            return (text_bytes / len(sample)) >= 0.85
        except Exception:
            return False

    def get_file_category(self, file_path, db):
        """
        Gets the category of a file and updates statistics.
        """
        category = "unknown"
        ext = self._get_true_extension(file_path)
        text_extensions = {
            ".txt", ".md", ".rst", ".csv", ".json", ".yaml", ".yml",
            ".xml", ".html", ".htm", ".js", ".ts", ".css",
        }
        source_code_extensions = {
            ".py", ".sh", ".rb", ".go", ".java", ".c", ".cc", ".cpp",
        }

        if ext.lower() in source_code_extensions:
            category = "source_code"
        elif ext.lower() in text_extensions:
            category = "text"

        if category == "unknown":
            for cat, extensions in self.extension_mapping.items():
                if ext in extensions:
                    category = cat
                    break

        # If the category is still unknown, try to determine it using python-magic
        if category == "unknown":
            try:
                mime = magic.from_file(file_path, mime=True)
                category = mime.split('/')[0] if mime else "application"
            except Exception as e:
                logger.error(f"Error getting MIME type for {file_path}: {e}")
                category = "application" if os.path.exists(file_path) else "unknown"

        if category == "unknown":
            if os.path.exists(file_path):
                category = "text" if self._looks_like_text(file_path) else "application"
            else:
                category = "unknown"

        # Update statistics in the database
        if db:
            try:
                file_size = os.path.getsize(file_path)
                db.update_category_stats(category, file_size)
            except Exception as e:
                logger.error(f"Error updating category stats for {file_path}: {e}")

        return category
