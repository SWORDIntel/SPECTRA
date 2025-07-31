"""
User Operations for SPECTRA
===========================

This module contains functions for user-related operations.
"""

import logging
import json
import aiofiles
import aiosqlite
from telethon import TelegramClient
from tqdm.asyncio import tqdm

logger = logging.getLogger(__name__)

async def get_server_users(client: TelegramClient, server_id: int, output_file: str, output_format: str = 'csv'):
    """
    Downloads the full user list, profile, and ID for all users of a specific server.
    """
    try:
        users = []
        pbar = tqdm(desc="Downloading users")
        async for user in client.iter_participants(server_id):
            users.append({
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone": user.phone
            })
            pbar.update(1)
        pbar.close()

        if output_format == 'csv':
            async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                await f.write("user_id,username,first_name,last_name,phone\n")
                for user in users:
                    await f.write(f"{user['user_id']},{user['username']},{user['first_name']},{user['last_name']},{user['phone']}\n")
        elif output_format == 'json':
            async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(users, indent=4))
        elif output_format == 'sqlite':
            async with aiosqlite.connect(output_file) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        phone TEXT
                    )
                """)
                await db.executemany("INSERT OR REPLACE INTO users VALUES (:user_id, :username, :first_name, :last_name, :phone)", users)
                await db.commit()

        logger.info(f"User list for server {server_id} has been saved to {output_file} in {output_format} format.")
    except ValueError:
        logger.error(f"Invalid server ID: {server_id}. Please provide a valid integer.")
    except Exception as e:
        logger.error(f"Error downloading user list for server {server_id}: {e}")
