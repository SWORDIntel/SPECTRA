#!/usr/bin/env python3
"""Download sticker set using a SPECTRA session."""
import asyncio
import json
import os
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.functions.messages import GetStickerSetRequest
from telethon.tl.types import (
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    InputStickerSetShortName,
)

SESSIONS_DIR = Path("/home/john/SPECTRA/sessions")
SESSION_STEM = "spectra_tdata_8011484242_1"
META_PATH = SESSIONS_DIR / f"{SESSION_STEM}.json"
OUTPUT_DIR = Path("/home/john/Pictures/atklib")

async def download_stickerset(short_name: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(META_PATH, "r") as f:
        meta = json.load(f)

    client = TelegramClient(
        str(SESSIONS_DIR / SESSION_STEM),
        meta["api_id"],
        meta["api_hash"],
    )

    await client.connect()
    if not await client.is_user_authorized():
        print("Error: Client is not authorized!")
        return

    me = await client.get_me()
    print(f"Connected as: {me.first_name} (@{me.username or 'no_username'}) [ID: {me.id}]")

    print(f"Fetching sticker set '{short_name}'...")
    try:
        sticker_set = await client(GetStickerSetRequest(
            stickerset=InputStickerSetShortName(short_name=short_name),
            hash=0
        ))
    except Exception as e:
        print(f"Failed to fetch sticker set '{short_name}': {e}")
        await client.disconnect()
        return

    set_title = sticker_set.set.title
    total_docs = len(sticker_set.documents)
    print(f"Found sticker set: '{set_title}' ({sticker_set.set.short_name}) with {total_docs} stickers.")

    downloaded = 0
    for idx, doc in enumerate(sticker_set.documents, start=1):
        # Determine emoji and extension
        alt_emoji = ""
        ext = ".webp"
        if doc.mime_type == "application/x-tgsticker":
            ext = ".tgs"
        elif doc.mime_type == "video/webm":
            ext = ".webm"

        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeSticker):
                alt_emoji = attr.alt or ""
            elif isinstance(attr, DocumentAttributeFilename):
                if attr.file_name:
                    _, ext_fn = os.path.splitext(attr.file_name)
                    if ext_fn:
                        ext = ext_fn

        filename = f"{idx:03d}_{doc.id}{ext}"
        target_path = OUTPUT_DIR / filename

        print(f"[{idx}/{total_docs}] Downloading sticker {doc.id} {alt_emoji} -> {filename}...")
        await client.download_media(doc, file=str(target_path))
        downloaded += 1

    print(f"\nSuccessfully downloaded {downloaded}/{total_docs} stickers to {OUTPUT_DIR}")
    await client.disconnect()

if __name__ == "__main__":
    sticker_name = sys.argv[1] if len(sys.argv) > 1 else "atklib"
    asyncio.run(download_stickerset(sticker_name))
