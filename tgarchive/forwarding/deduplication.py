"""
Handles deduplication of forwarded attachments.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import tempfile
from typing import List, Set

from telethon import TelegramClient
from telethon.tl.types import Message as TLMessage

from tgarchive.db import SpectraDB


def get_sha256_hash(file_path, chunk_size=8192):
    """
    Generates a SHA-256 hash for a file in a memory-efficient way.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


class Deduplicator:
    """
    Handles deduplication of forwarded attachments.
    """

    def __init__(self, db: SpectraDB, enable_deduplication: bool):
        self.db = db
        self.enable_deduplication = enable_deduplication
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.message_hashes: Set[str] = set()
        if self.enable_deduplication:
            if self.db:
                self._load_existing_hashes()
            else:
                self.logger.warning("Deduplication is enabled, but no database is configured. Deduplication will be in-memory only for this session.")

    def _load_existing_hashes(self):
        """Load existing SHA256 hashes from the file_hashes table."""
        if not self.db:
            self.logger.warning("Database not available, cannot load hashes.")
            return
        try:
            cursor = self.db.conn.execute("SELECT sha256_hash FROM file_hashes WHERE sha256_hash IS NOT NULL")
            count = 0
            for row in cursor:
                self.message_hashes.add(row[0])
                count += 1
            self.logger.info(f"Loaded {count} existing file content hashes (SHA256) into memory.")
        except sqlite3.OperationalError as e:
            self.logger.warning(f"Could not load existing hashes from 'file_hashes' table. It might not exist if this is the first run. Error: {e}")
        except Exception as e:
            self.logger.error(f"Error loading existing file hashes: {e}", exc_info=True)

    async def is_duplicate(self, message_group: List[TLMessage], client: TelegramClient) -> bool:
        """
        Check if any file in a message group is a duplicate based on its content hash.
        """
        if not self.enable_deduplication or not message_group:
            return False

        with tempfile.TemporaryDirectory() as tmpdir:
            for message in message_group:
                if not message.file:
                    continue

                file_path = os.path.join(tmpdir, str(message.file.id))

                try:
                    self.logger.debug(f"Downloading file from Msg ID {message.id} for hash computation.")
                    await client.download_media(message.media, file=file_path)
                except Exception as e:
                    self.logger.error(f"Failed to download file for hashing (Msg ID: {message.id}): {e}", exc_info=True)
                    continue

                if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                    self.logger.warning(f"File for hashing (Msg ID: {message.id}) was not downloaded correctly or is empty. Skipping duplicate check for this file.")
                    continue

                sha256_hash = get_sha256_hash(file_path)
                self.logger.debug(f"Computed SHA256 hash for file in Msg ID {message.id}: {sha256_hash[:10]}...")

                if sha256_hash in self.message_hashes:
                    self.logger.info(f"Duplicate file found (Msg ID {message.id}, SHA256: {sha256_hash[:10]}...) via in-memory cache.")
                    return True

                if self.db:
                    try:
                        result = self.db.conn.execute(
                            "SELECT 1 FROM file_hashes WHERE sha256_hash = ?",
                            (sha256_hash,)
                        ).fetchone()

                        if result:
                            self.logger.info(f"Duplicate file found (Msg ID {message.id}, SHA256: {sha256_hash[:10]}...) via database.")
                            self.message_hashes.add(sha256_hash)
                            return True
                    except sqlite3.OperationalError as e:
                        self.logger.warning(f"Could not check for duplicates in 'file_hashes' table, it might not exist yet. Error: {e}")
                    except Exception as e:
                        self.logger.error(f"Error checking for duplicate file in DB (hash {sha256_hash[:10]}...): {e}", exc_info=True)

        return False

    async def record_forwarded(self, message_group: List[TLMessage], origin_id: int, dest_id: str, client: TelegramClient):
        """
        Record that files in a message group were forwarded by storing their content hashes.
        """
        if not self.enable_deduplication or not self.db or not message_group:
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            for message in message_group:
                if not message.file:
                    continue

                file_path = os.path.join(tmpdir, str(message.file.id))
                try:
                    await client.download_media(message.media, file=file_path)
                except Exception as e:
                    self.logger.error(f"Failed to download file for recording hash (Msg ID: {message.id}): {e}", exc_info=True)
                    continue

                if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                    self.logger.warning(f"File for recording hash (Msg ID: {message.id}) not downloaded correctly or empty. Skipping.")
                    continue

                sha256_hash = get_sha256_hash(file_path)
                self.message_hashes.add(sha256_hash)

                try:
                    self.db.add_file_hash(
                        file_id=message.file.id,
                        sha256_hash=sha256_hash,
                        perceptual_hash=None,
                        fuzzy_hash=None
                    )
                    self.db.add_channel_file_inventory(
                        channel_id=origin_id,
                        file_id=message.file.id,
                        message_id=message.id,
                        topic_id=getattr(message, 'reply_to_top_id', None)
                    )
                    self.logger.info(f"Recorded forwarded file (Msg ID {message.id}, SHA256: {sha256_hash[:10]}...) to database.")
                except Exception as e:
                    self.logger.error(f"Failed to record forwarded file hash for Msg ID {message.id} to DB: {e}", exc_info=True)
