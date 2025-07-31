"""
User Operations for SPECTRA
===========================

This module contains functions for user-related operations.
"""

import logging
from telethon import TelegramClient

logger = logging.getLogger(__name__)

async def get_server_users(client: TelegramClient, server_id: int, output_file: str):
    """
    Downloads the full user list, profile, and ID for all users of a specific server.
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("user_id,username,first_name,last_name,phone\n")
            async for user in client.iter_participants(server_id):
                f.write(f"{user.id},{user.username},{user.first_name},{user.last_name},{user.phone}\n")
        logger.info(f"User list for server {server_id} has been saved to {output_file}")
    except Exception as e:
        logger.error(f"Error downloading user list for server {server_id}: {e}")
