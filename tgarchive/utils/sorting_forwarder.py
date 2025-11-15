"""
Sorting Forwarder for SPECTRA
=============================

This module contains the SortingForwarder class for forwarding files with sorting.
"""

from .forwarding import AttachmentForwarder
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class SortingForwarder(AttachmentForwarder):
    """
    A class for forwarding files with sorting.
    """
    def __init__(self, config, db, client, sorter, group_manager):
        super().__init__(
            config=config,
            db=db,
            prepend_origin_info=config.data.get("forwarding", {}).get("always_prepend_origin_info", False)
        )
        self.client = client
        self.sorter = sorter
        self.group_manager = group_manager
        self.sorting_cache = {}

    async def sort_and_forward(self, source, preview=False):
        """
        Sorts files and adds them to the forwarding queue.
        """
        started_at = datetime.now().isoformat()
        files_sorted = 0
        bytes_sorted = 0

        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                async for message in self.client.iter_messages(source):
                    if not message.file:
                        continue

                    files_sorted += 1
                    bytes_sorted += message.file.size

                    file_path = os.path.join(tmpdir, message.file.name)

                    try:
                        await self.client.download_media(message.media, file=file_path)
                    except Exception as e:
                        logger.error(f"Failed to download {message.file.name}: {e}")
                        continue

                    if file_path in self.sorting_cache:
                        category = self.sorting_cache[file_path]
                    else:
                        category = self.sorter.get_file_category(file_path, self.db)
                        self.sorting_cache[file_path] = category

                    group_id = await self.group_manager.check_or_create_group(category)

                    if preview:
                        print(f"DRY RUN: Would queue file {message.file.name} for group {group_id}")
                        continue

                    self.db.add_to_file_forward_queue(
                        schedule_id=None,
                        message_id=message.id,
                        file_id=message.file.id,
                        destination=group_id
                    )
                    self.db.add_sorting_audit_log(str(source), message.id, message.file.id, category, group_id)

            except Exception as e:
                logger.error(f"Error sorting files from {source}: {e}")
            finally:
                finished_at = datetime.now().isoformat()
                self.db.add_sorting_stats(str(source), files_sorted, bytes_sorted, started_at, finished_at)
