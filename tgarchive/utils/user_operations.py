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

import asyncio
from telethon.errors.rpcerrorlist import FloodWaitError

logger = logging.getLogger(__name__)

async def get_server_users(client: TelegramClient, server_id: int, output_file: str, output_format: str = 'csv', rotate_ip: bool = False, rate_limit_delay: int = 1):
    """
    Downloads the full user list, profile, and ID for all users of a specific server.
    """
    while True:
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
                await asyncio.sleep(rate_limit_delay)
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
            break
        except ValueError:
            logger.error(f"Invalid server ID: {server_id}. Please provide a valid integer.")
            break
        except FloodWaitError as e:
            logger.warning(f"Flood wait error: {e}. Waiting for {e.seconds} seconds.")
            if rotate_ip:
                logger.info("Rotating IP address...")
                await rotate_ip_address()
            await asyncio.sleep(e.seconds)
        except Exception as e:
            logger.error(f"Error downloading user list for server {server_id}: {e}")
            break

async def rotate_ip_address(vpn_provider: str = "auto"):
    """
    Rotates the IP address using VPN provider CLI tools.
    
    Args:
        vpn_provider: VPN provider to use ("nordvpn", "mullvad", "auto" for auto-detect)
    
    Returns:
        bool: True if rotation was successful, False otherwise
    
    Note:
        Requires VPN provider CLI tools to be installed and configured.
        For NordVPN: Install nordvpn package and authenticate
        For Mullvad: Install mullvad CLI and authenticate
    """
    import subprocess
    import shutil
    
    # Auto-detect VPN provider
    if vpn_provider == "auto":
        if shutil.which("nordvpn"):
            vpn_provider = "nordvpn"
        elif shutil.which("mullvad"):
            vpn_provider = "mullvad"
        else:
            logger.warning("No VPN provider CLI found. Install NordVPN or Mullvad CLI tools.")
            return False
    
    try:
        if vpn_provider == "nordvpn":
            # Disconnect first
            subprocess.run(["nordvpn", "disconnect"], check=False, timeout=10)
            await asyncio.sleep(2)
            # Connect to random server
            result = subprocess.run(
                ["nordvpn", "connect"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                logger.info("IP rotated successfully using NordVPN")
                return True
            else:
                logger.error(f"Failed to rotate IP with NordVPN: {result.stderr}")
                return False
        
        elif vpn_provider == "mullvad":
            # Disconnect first
            subprocess.run(["mullvad", "disconnect"], check=False, timeout=10)
            await asyncio.sleep(2)
            # Connect to random server
            result = subprocess.run(
                ["mullvad", "connect"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                logger.info("IP rotated successfully using Mullvad")
                return True
            else:
                logger.error(f"Failed to rotate IP with Mullvad: {result.stderr}")
                return False
        
        else:
            logger.warning(f"Unsupported VPN provider: {vpn_provider}")
            return False
    
    except subprocess.TimeoutExpired:
        logger.error(f"VPN connection timeout for {vpn_provider}")
        return False
    except FileNotFoundError:
        logger.error(f"VPN CLI tool not found: {vpn_provider}. Please install and configure it.")
        return False
    except Exception as e:
        logger.error(f"Error rotating IP address: {e}")
        return False
