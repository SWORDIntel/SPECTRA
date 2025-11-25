"""
Handles queue-based file forwarding.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from tgarchive.core.config_models import Config
from tgarchive.db import SpectraDB

from .client import ClientManager
from .deduplication import Deduplicator


class QueueManager:
    """
    Manages the queue-based file forwarding.
    """

    def __init__(self, config: Config, db: SpectraDB):
        self.config = config
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.client_manager = ClientManager(config)
        self.deduplicator = Deduplicator(db, enable_deduplication=True)

    async def forward_files(
        self,
        schedule_id: int,
        source_id: int | str,
        destination_id: int | str,
        file_types: Optional[str],
        min_file_size: Optional[int],
        max_file_size: Optional[int],
        account_identifier: Optional[str] = None,
    ):
        client = None
        try:
            client = await self.client_manager.get_client(account_identifier)
            source_entity = await client.get_entity(source_id)

            if not source_entity:
                raise ValueError("Could not resolve the source Telegram entity.")

            async for message in client.iter_messages(source_entity):
                if not message.media or not message.file:
                    continue

                if file_types:
                    if message.file.mime_type not in file_types.split(","):
                        continue

                if min_file_size is not None and message.file.size < min_file_size:
                    continue

                if max_file_size is not None and message.file.size > max_file_size:
                    continue

                if await self.deduplicator.is_duplicate([message], client):
                    continue

                self.db.add_to_file_forward_queue(schedule_id, message.id, message.file.id, destination_id)

        except Exception as e:
            self.logger.error(f"Error queueing files from {source_id}: {e}")
            raise
        finally:
            if client:
                await self.client_manager.close()

    async def process_file_forward_queue(self, account_identifier: Optional[str] = None):
        client = None
        try:
            client = await self.client_manager.get_client(account_identifier)
            queue = self.db.get_file_forward_queue()
            for queue_id, schedule_id, message_id, file_id, destination in queue:
                try:
                    if destination:
                        destination_entity = await client.get_entity(destination)
                    else:
                        schedule = self.db.get_file_forward_schedule_by_id(schedule_id)
                        if not schedule:
                            self.db.update_file_forward_queue_status(queue_id, "error: schedule not found")
                            continue
                        destination_entity = await client.get_entity(schedule.destination)

                    source_entity = await client.get_entity(schedule.source)

                    await client.forward_messages(
                        entity=destination_entity,
                        messages=[message_id],
                        from_peer=source_entity,
                    )
                    await self.deduplicator.record_forwarded(
                        [await client.get_messages(source_entity, ids=message_id)],
                        str(source_entity.id),
                        str(destination_entity.id),
                        client,
                    )
                    self.db.update_file_forward_queue_status(queue_id, "success")

                    bandwidth_limit_kbps = self.config.data.get("scheduler", {}).get("bandwidth_limit_kbps", 0)
                    if bandwidth_limit_kbps > 0:
                        message = await client.get_messages(source_entity, ids=message_id)
                        if message and message.file:
                            delay = message.file.size / (bandwidth_limit_kbps * 1024)
                            await asyncio.sleep(delay)

                except Exception as e:
                    self.db.update_file_forward_queue_status(queue_id, f"error: {e}")
                    self.logger.error(f"Error processing queue item {queue_id}: {e}")
        except Exception as e:
            self.logger.error(f"Error processing file forward queue: {e}")
            raise
        finally:
            if client:
                await self.client_manager.close()
