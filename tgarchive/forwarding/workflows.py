"""
High-level forwarding workflows.
"""
from __future__ import annotations

import logging
from typing import Optional

from tgarchive.config_models import Config
from tgarchive.db import SpectraDB

from .forwarder import AttachmentForwarder


class Workflows:
    """
    High-level forwarding workflows.
    """

    def __init__(self, config: Config, db: SpectraDB):
        self.config = config
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def forward_all_accessible_channels(
        self,
        destination_id: int | str,
        orchestration_account_identifier: Optional[str] = None,
    ):
        if not self.db:
            self.logger.error("Database instance (self.db) not available. Cannot proceed with total forward mode.")
            return
        self.logger.info(f"Starting 'Total Forward Mode'. Destination: {destination_id}")
        try:
            unique_channels_with_accounts = self.db.get_all_unique_channels()
        except Exception as e_db:
            self.logger.error(f"Failed to retrieve channels from database: {e_db}", exc_info=True)
            return
        if not unique_channels_with_accounts:
            self.logger.warning("No channels found in account_channel_access table to process for total forward mode.")
            return
        self.logger.info(f"Found {len(unique_channels_with_accounts)} unique channels to process.")
        for channel_id, accessing_account_phone in unique_channels_with_accounts:
            self.logger.info(f"--- Processing channel ID: {channel_id} using account: {accessing_account_phone} ---")
            try:
                forwarder = AttachmentForwarder(self.config, self.db)
                await forwarder.forward_messages(
                    origin_id=channel_id,
                    destination_id=destination_id,
                    account_identifier=accessing_account_phone,
                )
                self.logger.info(f"--- Finished processing channel ID: {channel_id} ---")
            except Exception as e_fwd_all:
                self.logger.error(f"Failed to forward messages for channel ID {channel_id} using account {accessing_account_phone}: {e_fwd_all}", exc_info=True)
                self.logger.info(f"Continuing to the next channel after error with channel ID: {channel_id}.")
                continue
        self.logger.info("'Total Forward Mode' completed.")
