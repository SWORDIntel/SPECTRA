"""
File System Watcher for SPECTRA
===============================

This module contains the FileSystemWatcher for monitoring a directory for new files.
"""

import time
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from .file_sorting_manager import FileSortingManager

logger = logging.getLogger(__name__)

class FileSystemWatcher(FileSystemEventHandler):
    """
    Handles file system events and triggers the file sorting process.
    """
    def __init__(self, file_sorting_manager: FileSortingManager):
        self.file_sorting_manager = file_sorting_manager

    def on_created(self, event):
        """
        Called when a file or directory is created.
        """
        if not event.is_directory:
            logger.info(f"New file detected: {event.src_path}")
            self.file_sorting_manager.process_file(event.src_path)

def start_watching(path: str, file_sorting_manager: FileSortingManager):
    """
    Starts the file system watcher.
    """
    event_handler = FileSystemWatcher(file_sorting_manager)
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()
    logger.info(f"Started watching directory: {path}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
