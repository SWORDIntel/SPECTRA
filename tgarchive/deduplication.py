"""
Deduplication for SPECTRA
=========================

This module contains functions for file deduplication.
"""

import hashlib
import imagehash
import ssdeep
from PIL import Image

def get_sha256_hash(file_path):
    """
    Generates a SHA-256 hash for a file.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256.update(byte_block)
    return sha256.hexdigest()

def get_perceptual_hash(file_path):
    """
    Generates a perceptual hash for an image file.
    """
    try:
        with Image.open(file_path) as img:
            return str(imagehash.phash(img))
    except Exception:
        return None

def get_fuzzy_hash(file_path):
    """
    Generates a fuzzy hash for a file.
    """
    try:
        return ssdeep.hash_from_file(file_path)
    except Exception:
        return None

def compare_fuzzy_hashes(hash1, hash2):
    """
    Compares two fuzzy hashes and returns a similarity percentage.
    """
    return ssdeep.compare(hash1, hash2)

def is_exact_match(db, sha256_hash, channel_id=None):
    """
    Checks if an exact match for a file exists in the database.
    """
    if channel_id:
        sql = """
            SELECT f.file_id
            FROM file_hashes f
            JOIN channel_file_inventory c ON f.file_id = c.file_id
            WHERE f.sha256_hash = ? AND c.channel_id = ?
        """
        params = (sha256_hash, channel_id)
    else:
        sql = "SELECT file_id FROM file_hashes WHERE sha256_hash = ?"
        params = (sha256_hash,)
    db.cur.execute(sql, params)
    return db.cur.fetchone() is not None

def find_near_duplicates(db, fuzzy_hash, threshold=85, channel_id=None):
    """
    Finds near-duplicates for a file in the database.
    """
    if channel_id:
        sql = """
            SELECT f.file_id, f.fuzzy_hash
            FROM file_hashes f
            JOIN channel_file_inventory c ON f.file_id = c.file_id
            WHERE f.fuzzy_hash IS NOT NULL AND c.channel_id = ?
        """
        params = (channel_id,)
    else:
        sql = "SELECT file_id, fuzzy_hash FROM file_hashes WHERE fuzzy_hash IS NOT NULL"
        params = ()
    db.cur.execute(sql, params)
    duplicates = []
    for file_id, other_fuzzy_hash in db.cur.fetchall():
        similarity = compare_fuzzy_hashes(fuzzy_hash, other_fuzzy_hash)
        if similarity >= threshold:
            duplicates.append((file_id, similarity))
    return duplicates

def get_channel_id_for_file(db, file_id):
    """
    Gets the channel ID for a file.
    """
    db.cur.execute("SELECT channel_id FROM channel_file_inventory WHERE file_id = ?", (file_id,))
    row = db.cur.fetchone()
    return row[0] if row else None

def get_minhash(file_path, num_perm=128):
    """
    Generates a MinHash for a file.
    """
    from datasketch import MinHash

    with open(file_path, "r") as f:
        content = f.read()

    m = MinHash(num_perm=num_perm)
    for d in content.split():
        m.update(d.encode('utf8'))
    return m

class ChannelScanner:
    """
    Scans a channel for files and generates hashes for them.
    """
    def __init__(self, db, client):
        self.db = db
        self.client = client

    async def scan_channel(self, channel, rate_limit_seconds=1):
        """
        Scans a channel for files, generates hashes, and stores them in the database.
        """
        import tempfile
        import os
        import asyncio

        async for message in self.client.iter_messages(channel):
            if not message.file:
                continue

            with tempfile.TemporaryDirectory() as tmpdir:
                file_path = os.path.join(tmpdir, message.file.name)
                try:
                    await self.client.download_media(message.media, file=file_path)
                except Exception as e:
                    print(f"Failed to download {message.file.name}: {e}")
                    continue

                sha256_hash = get_sha256_hash(file_path)
                if is_exact_match(self.db, sha256_hash):
                    continue

                perceptual_hash = get_perceptual_hash(file_path)
                fuzzy_hash = get_fuzzy_hash(file_path)

                self.db.add_file_hash(
                    file_id=message.file.id,
                    sha256_hash=sha256_hash,
                    perceptual_hash=perceptual_hash,
                    fuzzy_hash=fuzzy_hash,
                )

            await asyncio.sleep(rate_limit_seconds)
