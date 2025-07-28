"""
Deduplication for SPECTRA
=========================

This module contains functions for file deduplication.
"""

import hashlib
import imagehash
import ssdeep
from PIL import Image
from functools import lru_cache

@lru_cache(maxsize=1024)
def get_file_hashes(db, file_id):
    """
    Gets the hashes for a file from the database.
    """
    db.cur.execute("SELECT sha256_hash, perceptual_hash, fuzzy_hash FROM file_hashes WHERE file_id = ?", (file_id,))
    return db.cur.fetchone()

def get_sha256_hash(file_path, chunk_size=8192):
    """
    Generates a SHA-256 hash for a file in a memory-efficient way.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
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

def get_ngrams(text, n=3):
    """
    Generates n-grams for a text.
    """
    return [text[i:i+n] for i in range(len(text)-n+1)]

def get_exif_data(file_path):
    """
    Extracts EXIF data from an image file.
    """
    from PIL import Image
    from PIL.ExifTags import TAGS

    try:
        with Image.open(file_path) as img:
            exif_data = {}
            if hasattr(img, '_getexif'):
                exif = img._getexif()
                if exif:
                    for tag, value in exif.items():
                        decoded = TAGS.get(tag, tag)
                        exif_data[decoded] = value
            return exif_data
    except Exception:
        return None

class ChannelScanner:
    """
    Scans a channel for files and generates hashes for them.
    """
    def __init__(self, db, client):
        self.db = db
        self.client = client

    async def scan_channel(self, channel, batch_size=100, rate_limit_seconds=1):
        """
        Scans a channel for files, generates hashes, and stores them in the database.
        """
        import tempfile
        import os
        import asyncio

        batch = []
        async for message in self.client.iter_messages(channel):
            if not message.file:
                continue

            batch.append(message)

            if len(batch) >= batch_size:
                await self.process_batch(batch)
                batch = []
                await asyncio.sleep(rate_limit_seconds)

        if batch:
            await self.process_batch(batch)

    async def process_batch(self, batch):
        import tempfile
        import os
        import asyncio

        with tempfile.TemporaryDirectory() as tmpdir:
            tasks = []
            for message in batch:
                tasks.append(self.process_message(message, tmpdir))
            await asyncio.gather(*tasks)

    async def process_message(self, message, tmpdir):
        import os
        import asyncio

        file_path = os.path.join(tmpdir, message.file.name)
        try:
            await self.client.download_media(message.media, file=file_path)
        except Exception as e:
            print(f"Failed to download {message.file.name}: {e}")
            return

        sha256_hash = await asyncio.to_thread(get_sha256_hash, file_path)
        if await asyncio.to_thread(is_exact_match, self.db, sha256_hash):
            return

        perceptual_hash = await asyncio.to_thread(get_perceptual_hash, file_path)
        fuzzy_hash = await asyncio.to_thread(get_fuzzy_hash, file_path)

        await asyncio.to_thread(
            self.db.add_file_hash,
            file_id=message.file.id,
            sha256_hash=sha256_hash,
            perceptual_hash=perceptual_hash,
            fuzzy_hash=fuzzy_hash,
        )
