"""
File Sorting Manager for SPECTRA
================================

This module contains the FileSortingManager class for orchestrating the file sorting process.
"""

import logging
from .file_sorter import FileTypeSorter
from .directory_manager import DirectoryManager
from .db.spectra_db import SpectraDB

logger = logging.getLogger(__name__)

class FileSortingManager:
    """
    Orchestrates the file sorting process.
    """
    def __init__(self, config, output_dir: str, db: SpectraDB):
        self.config = config
        self.output_dir = output_dir
        self.db = db
        self.file_type_sorter = FileTypeSorter(self.config)
        self.directory_manager = DirectoryManager(self.output_dir)

    def process_file(self, file_path: str):
        """
        Processes a single file, categorizing it and moving it to the correct directory.
        """
        logger.info(f"Processing file: {file_path}")
        category = self.file_type_sorter.get_file_category(file_path, self.db)
        logger.info(f"Categorized '{file_path}' as '{category}'")
        self.directory_manager.move_file(file_path, category)
