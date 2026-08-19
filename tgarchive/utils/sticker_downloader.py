"""
SPECTRA Sticker Set Downloader
==============================
General utility for downloading Telegram sticker sets using converted Telethon sessions.
Supports static (.webp), animated (.tgs), and video (.webm) sticker sets with metadata sidecars.
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from telethon import TelegramClient
from telethon.tl.functions.messages import GetStickerSetRequest
from telethon.tl.types import (
    DocumentAttributeFilename,
    DocumentAttributeImageSize,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    InputStickerSetShortName,
    messages,
)

logger = logging.getLogger(__name__)

DEFAULT_API_ID = 2040
DEFAULT_API_HASH = "b18441a1ff607e10a989891a5462e627"


def normalize_stickerset_name(input_str: str) -> str:
    """
    Extract clean sticker set short_name from a URL, uri scheme, or raw identifier.
    
    Examples:
        https://t.me/addstickers/atklib -> atklib
        t.me/addstickers/atklib         -> atklib
        tg://addstickers?set=atklib     -> atklib
        @atklib                         -> atklib
        atklib                          -> atklib
    """
    s = input_str.strip()
    # Match https://t.me/addstickers/<name> or t.me/addstickers/<name>
    m = re.search(r"t\.me/addstickers/([a-zA-Z0-9_]+)", s)
    if m:
        return m.group(1)
    
    # Match tg://addstickers?set=<name>
    m = re.search(r"tg://addstickers\?set=([a-zA-Z0-9_]+)", s)
    if m:
        return m.group(1)
    
    # Strip @ and url slashes
    s = s.lstrip("@").split("/")[-1].split("?")[0]
    return s


def find_available_sessions(sessions_dir: Path | str = "sessions") -> List[Tuple[Path, dict]]:
    """Discover usable .session files and their corresponding .json sidecars."""
    sdir = Path(sessions_dir).expanduser().resolve()
    if not sdir.exists():
        return []
    
    found: List[Tuple[Path, dict]] = []
    for session_file in sorted(sdir.glob("*.session")):
        json_file = session_file.with_suffix(".json")
        meta = {
            "api_id": DEFAULT_API_ID,
            "api_hash": DEFAULT_API_HASH,
        }
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        meta.update(loaded)
            except Exception as e:
                logger.debug(f"Could not read session sidecar {json_file}: {e}")
        
        found.append((session_file, meta))
    
    return found


class StickerDownloader:
    """Downloads and archives Telegram sticker sets with full metadata preservation."""

    def __init__(
        self,
        sessions_dir: Path | str = "sessions",
        explicit_session: Optional[str] = None,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
    ) -> None:
        self.sessions_dir = Path(sessions_dir).expanduser().resolve()
        self.explicit_session = explicit_session
        self.api_id = api_id
        self.api_hash = api_hash

    def _resolve_session(self) -> Tuple[Path, int, str]:
        """Resolve which session and API credentials to use."""
        if self.explicit_session:
            cand = Path(self.explicit_session).expanduser().resolve()
            if not cand.suffix:
                cand = cand.with_suffix(".session")
            if not cand.exists() and not cand.is_absolute():
                cand = self.sessions_dir / cand.name
            if not cand.exists():
                raise FileNotFoundError(f"Specified session not found: {self.explicit_session}")
            
            api_id = self.api_id or DEFAULT_API_ID
            api_hash = self.api_hash or DEFAULT_API_HASH
            json_file = cand.with_suffix(".json")
            if json_file.exists():
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        api_id = self.api_id or meta.get("api_id") or api_id
                        api_hash = self.api_hash or meta.get("api_hash") or api_hash
                except Exception:
                    pass
            return cand, int(api_id), str(api_hash)

        available = find_available_sessions(self.sessions_dir)
        if not available:
            raise RuntimeError(
                f"No Telegram sessions found in {self.sessions_dir}. "
                "Use 'spectra tdata2session' or specify a session with --session."
            )

        session_path, meta = available[0]
        api_id = self.api_id or meta.get("api_id") or DEFAULT_API_ID
        api_hash = self.api_hash or meta.get("api_hash") or DEFAULT_API_HASH
        return session_path, int(api_id), str(api_hash)

    async def get_stickerset_info(self, stickerset_input: str) -> Dict[str, Any]:
        """Fetch sticker set metadata without downloading files."""
        short_name = normalize_stickerset_name(stickerset_input)
        session_path, api_id, api_hash = self._resolve_session()

        client = TelegramClient(str(session_path.with_suffix("")), api_id, api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise PermissionError(f"Session {session_path.name} is not authorized.")

            res: messages.StickerSet = await client(
                GetStickerSetRequest(
                    stickerset=InputStickerSetShortName(short_name=short_name),
                    hash=0,
                )
            )
            return self._parse_set_metadata(res)
        finally:
            await client.disconnect()

    def _parse_set_metadata(self, res: messages.StickerSet) -> Dict[str, Any]:
        s = res.set
        stickers_meta = []
        for idx, doc in enumerate(res.documents, start=1):
            alt_emoji = ""
            ext = ".webp"
            width, height = 512, 512

            if doc.mime_type == "application/x-tgsticker":
                ext = ".tgs"
            elif doc.mime_type == "video/webm":
                ext = ".webm"

            for attr in doc.attributes:
                if isinstance(attr, DocumentAttributeSticker):
                    alt_emoji = attr.alt or ""
                elif isinstance(attr, DocumentAttributeImageSize):
                    width, height = attr.w, attr.h
                elif isinstance(attr, DocumentAttributeVideo):
                    width, height = attr.w, attr.h
                elif isinstance(attr, DocumentAttributeFilename):
                    if attr.file_name:
                        _, ext_fn = os.path.splitext(attr.file_name)
                        if ext_fn:
                            ext = ext_fn

            stickers_meta.append({
                "index": idx,
                "document_id": doc.id,
                "access_hash": doc.access_hash,
                "emoji": alt_emoji,
                "mime_type": doc.mime_type,
                "size_bytes": doc.size,
                "extension": ext,
                "width": width,
                "height": height,
                "filename": f"{idx:03d}_{doc.id}{ext}",
            })

        return {
            "title": s.title,
            "short_name": s.short_name,
            "id": s.id,
            "access_hash": s.access_hash,
            "count": len(res.documents),
            "is_animated": getattr(s, "animated", False),
            "is_video": getattr(s, "video", False),
            "is_emojis": getattr(s, "emojis", False),
            "stickers": stickers_meta,
        }

    async def download(
        self,
        stickerset_input: str,
        output_dir: Optional[Path | str] = None,
        overwrite: bool = False,
        convert_to_png: bool = False,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """Download all stickers in the set to the output directory."""
        short_name = normalize_stickerset_name(stickerset_input)
        session_path, api_id, api_hash = self._resolve_session()

        if output_dir:
            out_path = Path(output_dir).expanduser().resolve()
        else:
            out_path = Path(f"data/stickers/{short_name}").expanduser().resolve()

        out_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Connecting via session: {session_path.name}")
        client = TelegramClient(str(session_path.with_suffix("")), api_id, api_hash)
        await client.connect()

        try:
            if not await client.is_user_authorized():
                raise PermissionError(f"Session {session_path.name} is not authorized.")

            logger.info(f"Fetching sticker set '{short_name}'...")
            res: messages.StickerSet = await client(
                GetStickerSetRequest(
                    stickerset=InputStickerSetShortName(short_name=short_name),
                    hash=0,
                )
            )

            meta = self._parse_set_metadata(res)
            total = len(res.documents)
            downloaded = 0
            skipped = 0
            converted_png_count = 0

            logger.info(f"Downloading {total} stickers for '{meta['title']}' into {out_path}")

            for doc_info, doc in zip(meta["stickers"], res.documents):
                filename = doc_info["filename"]
                target_file = out_path / filename

                already_exists = target_file.exists() and not overwrite and target_file.stat().st_size > 0
                if already_exists:
                    skipped += 1
                else:
                    await client.download_media(doc, file=str(target_file))
                    downloaded += 1

                # Convert to PNG if requested
                if convert_to_png and target_file.exists():
                    png_target = target_file.with_suffix(".png")
                    if not png_target.exists() or overwrite or not already_exists:
                        try:
                            from PIL import Image
                            with Image.open(target_file) as im:
                                im.convert("RGBA").save(png_target, "PNG")
                            converted_png_count += 1
                        except Exception as exc:
                            logger.debug(f"Could not convert {target_file.name} to PNG: {exc}")

                if progress_callback:
                    progress_callback(doc_info["index"], total, filename, already_exists)

            # Write metadata sidecar
            meta_file = out_path / "metadata.json"
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            return {
                "success": True,
                "title": meta["title"],
                "short_name": meta["short_name"],
                "total": total,
                "downloaded": downloaded,
                "skipped": skipped,
                "converted_png": converted_png_count,
                "output_dir": str(out_path),
                "metadata_file": str(meta_file),
            }

        finally:
            await client.disconnect()
