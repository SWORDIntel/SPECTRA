"""
Group Manager for SPECTRA
=========================

This module contains the GroupManager class for managing dynamic group creation.
"""

import time
import asyncio
import logging
from telethon.tl.functions.channels import CreateChannelRequest

logger = logging.getLogger(__name__)

class GroupManager:
    """
    A class for managing dynamic group creation.
    """
    def __init__(self, config, db, client):
        self.config = config
        self.db = db
        self.client = client
        self.last_group_creation_time = 0
        self.group_metadata_cache = {}

    async def create_category_group(self, category):
        """
        Creates a new group for a category.
        """
        rate_limit = self.config.get("file_sorter", {}).get("group_creation_rate_limit_seconds", 60)
        time_since_last_creation = time.time() - self.last_group_creation_time
        if time_since_last_creation < rate_limit:
            await asyncio.sleep(rate_limit - time_since_last_creation)

        group_name_template = self.config.get("file_sorter", {}).get("group_naming_template", "SPECTRA-{category}")
        group_name = group_name_template.format(category=category)
        group_description_template = self.config.get("file_sorter", {}).get("group_description_template", "A group for {category} files.")
        group_description = group_description_template.format(category=category)

        created_channel = await self.client(CreateChannelRequest(
            title=group_name,
            about=group_description,
            megagroup=True
        ))

        self.last_group_creation_time = time.time()

        try:
            group_id = created_channel.chats[0].id
            self.db.add_category_to_group_mapping(category, group_id)
            return group_id
        except Exception as e:
            self.logger.error(f"Error creating group for category {category}: {e}")
            return None

    async def check_or_create_group(self, category):
        """
        Checks if a group for a category already exists, and creates it if it doesn't.
        """
        if category in self.group_metadata_cache:
            return self.group_metadata_cache[category]

        group_id = self.db.get_group_id_for_category(category)
        if group_id:
            self.group_metadata_cache[category] = group_id
            return group_id

        if not self.config.get("file_sorter", {}).get("group_creation_enabled", True):
            return None

        group_id = await self.create_category_group(category)
        self.group_metadata_cache[category] = group_id
        return group_id

    def initialize_default_sorting_groups(self):
        """
        Initializes the default sorting groups from the configuration.
        """
        default_groups = self.config.get("file_sorter", {}).get("default_sorting_groups", {})
        for group_name, template in default_groups.items():
            self.db.add_sorting_group(group_name, template)

    async def add_user_to_group(self, group_id, user_id):
        """
        Adds a user to a group.
        """
        from telethon.tl.functions.channels import InviteToChannelRequest
        await self.client(InviteToChannelRequest(group_id, [user_id]))

    async def remove_user_from_group(self, group_id, user_id):
        """
        Removes a user from a group.
        """
        from telethon.tl.functions.channels import EditBannedRequest
        from telethon.tl.types import ChatBannedRights
        await self.client(EditBannedRequest(group_id, user_id, ChatBannedRights(
            until_date=None,
            view_messages=True
        )))
