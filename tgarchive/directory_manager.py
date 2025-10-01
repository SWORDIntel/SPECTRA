"""
Directory Manager for SPECTRA
=============================

This module contains the DirectoryManager class for creating directories and moving files.
"""

import os
import shutil
import logging

logger = logging.getLogger(__name__)

class DirectoryManager:
    """
    Manages the creation of directories and the moving of files.
    """
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def move_file(self, file_path: str, category: str):
        """
        Moves a file to a category-based directory.
        """
        if not category or category == "unknown":
            dest_dir = os.path.join(self.output_dir, "unknown")
        else:
            dest_dir = os.path.join(self.output_dir, category)

        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)

        dest_path = os.path.join(dest_dir, os.path.basename(file_path))

        try:
            shutil.move(file_path, dest_path)
            logger.info(f"Moved file {file_path} to {dest_path}")
        except Exception as e:
            logger.error(f"Error moving file {file_path} to {dest_path}: {e}")
            raise
