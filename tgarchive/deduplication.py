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

def is_exact_match(db, sha256_hash):
    """
    Checks if an exact match for a file exists in the database.
    """
    db.cur.execute("SELECT file_id FROM file_hashes WHERE sha256_hash = ?", (sha256_hash,))
    return db.cur.fetchone() is not None

def find_near_duplicates(db, fuzzy_hash, threshold=85):
    """
    Finds near-duplicates for a file in the database.
    """
    db.cur.execute("SELECT file_id, fuzzy_hash FROM file_hashes WHERE fuzzy_hash IS NOT NULL")
    duplicates = []
    for file_id, other_fuzzy_hash in db.cur.fetchall():
        similarity = compare_fuzzy_hashes(fuzzy_hash, other_fuzzy_hash)
        if similarity >= threshold:
            duplicates.append((file_id, similarity))
    return duplicates
