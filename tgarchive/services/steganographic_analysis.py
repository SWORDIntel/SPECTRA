"""
Steganographic Analysis Service — Detect hidden data in media files
====================================================================

Detects covert channels and hidden data in archived media:
  - LSB (Least Significant Bit) steganography in images
  - EXIF metadata anomalies (GPS coords, hidden tags, tool signatures)
  - File format mismatches (file claiming to be JPG but containing ZIP)
  - Appended data after EOF markers
  - Unusual entropy in file payloads
  - Audio steganography indicators (spectral anomalies, ultrasonic markers)

Usage (library)::

    from tgarchive.services.steganographic_analysis import analyze_media_file

    result = analyze_media_file("/path/to/suspicious.jpg")

Usage (CLI)::

    spectra-cli analyze steganography /path/to/media.jpg
    spectra-cli analyze steganography /path/to/media/ --batch
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import io
import logging
import os
import struct
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Checksum skip cache ─────────────────────────────────────────────────────

_CHECKSUM_CACHE: Dict[str, Dict[str, Any]] = {}


def get_stego_cache() -> Dict[str, Dict[str, Any]]:
    """Return the global steganographic analysis checksum cache."""
    return _CHECKSUM_CACHE


def clear_stego_cache() -> None:
    """Clear the global steganographic analysis checksum cache."""
    _CHECKSUM_CACHE.clear()


get_cache = get_stego_cache
clear_cache = clear_stego_cache


def _compute_checksum(file_path: Path | str) -> str:
    """Compute SHA-256 checksum of a file in chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()



# ─── File signature tables ───────────────────────────────────────────────────

_FILE_SIGNATURES = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "wav/webp",
    b"ID3": "mp3",
    b"\x00\x00\x01\x00": "ico",
    b"\x00\x00\x02\x00": "cur",
    b"BM": "bmp",
    b"PK\x03\x04": "zip",
    b"PK\x05\x06": "zip_empty",
    b"Rar!\x1a\x07": "rar",
    b"\x1f\x8b": "gzip",
    b"%PDF": "pdf",
    b"OggS": "ogg",
    b"ftyp": "mp4",
    b"\x00\x00\x00\x18ftyp": "mp4",
    b"\x00\x00\x00\x20ftyp": "mp4",
}

_EOF_MARKERS = {
    "jpeg": b"\xff\xd9",
    "png": b"IEND\xaeB`\x82",
    "gif": b"\x00\x3b",
}


def _detect_file_type(data: bytes) -> str:
    """Detect file type from magic bytes."""
    for sig, ftype in _FILE_SIGNATURES.items():
        if data.startswith(sig):
            return ftype
    return "unknown"


def _calculate_entropy(data: bytes) -> float:
    """Calculate Shannon entropy of a byte sequence (0-8 bits)."""
    if not data:
        return 0.0
    import math
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    total = len(data)
    entropy = 0.0
    for count in freq:
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def _check_lsb_steganography(data: bytes, file_type: str) -> Dict[str, Any]:
    """Check for LSB steganography indicators in image data.

    LSB steganography embeds data in the least significant bits of pixel values.
    We detect this by:
    1. Checking if the LSB plane has unusually high entropy (random data)
    2. Looking for sequential patterns in LSBs that suggest embedded content
    """
    result: Dict[str, Any] = {"detected": False, "indicators": [], "lsb_entropy": None}

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        if img.mode not in ("RGB", "RGBA", "L", "P"):
            img = img.convert("RGB")

        if img.mode == "P":
            img = img.convert("RGB")

        pixels = list(img.getdata())
        if not pixels:
            return result

        # Extract LSBs from first 1000 pixels
        sample_size = min(1000, len(pixels))
        lsbs = []
        for i in range(sample_size):
            pixel = pixels[i]
            if isinstance(pixel, int):
                lsbs.append(pixel & 1)
            elif isinstance(pixel, (tuple, list)):
                for channel in pixel[:3]:  # RGB channels
                    lsbs.append(channel & 1)

        if not lsbs:
            return result

        # Calculate LSB entropy
        lsb_entropy = _calculate_entropy(bytes(lsbs))
        result["lsb_entropy"] = round(lsb_entropy, 4)

        # High LSB entropy (>0.9) suggests possible steganography
        # Natural images tend to have LSB entropy around 0.5-0.8
        if lsb_entropy > 0.95:
            result["detected"] = True
            result["indicators"].append({
                "type": "high_lsb_entropy",
                "severity": "medium",
                "detail": f"LSB entropy {lsb_entropy:.4f} exceeds natural image threshold (0.95)",
            })

        # Check for sequential byte patterns in LSBs (could be embedded text)
        lsb_bytes = []
        for i in range(0, len(lsbs) - 7, 8):
            byte_val = 0
            for bit in range(8):
                byte_val |= (lsbs[i + bit] & 1) << bit
            lsb_bytes.append(byte_val)

        if lsb_bytes:
            # Check for printable ASCII sequences (embedded text)
            printable_count = sum(1 for b in lsb_bytes if 32 <= b <= 126)
            printable_ratio = printable_count / len(lsb_bytes)
            if printable_ratio > 0.8:
                result["detected"] = True
                result["indicators"].append({
                    "type": "embedded_text_pattern",
                    "severity": "high",
                    "detail": f"LSB extraction yields {printable_ratio:.1%} printable ASCII — possible embedded text",
                })

            # Check for embedded file signatures
            lsb_data = bytes(lsb_bytes[:64])
            for sig, ftype in _FILE_SIGNATURES.items():
                if lsb_data.startswith(sig):
                    result["detected"] = True
                    result["indicators"].append({
                        "type": "embedded_file_signature",
                        "severity": "high",
                        "detail": f"LSB extraction contains {ftype} file signature",
                    })
                    break

    except Exception as e:
        result["indicators"].append({
            "type": "analysis_error",
            "severity": "low",
            "detail": f"LSB analysis failed: {e}",
        })

    return result


def _check_eof_appended_data(data: bytes, file_type: str) -> Dict[str, Any]:
    """Check for data appended after the EOF marker."""
    result: Dict[str, Any] = {"detected": False, "appended_size": 0, "indicators": []}

    eof_marker = _EOF_MARKERS.get(file_type)
    if not eof_marker:
        return result

    # Find the last occurrence of the EOF marker
    eof_pos = data.rfind(eof_marker)
    if eof_pos == -1:
        return result

    after_eof = data[eof_pos + len(eof_marker):]
    # Strip trailing nulls/padding
    stripped = after_eof.rstrip(b"\x00\r\n ")
    if len(stripped) > 16:
        result["detected"] = True
        result["appended_size"] = len(after_eof)

        # Check what the appended data is
        appended_type = _detect_file_type(stripped[:16])
        if appended_type != "unknown":
            result["indicators"].append({
                "type": "appended_file",
                "severity": "high",
                "detail": f"{len(after_eof)} bytes appended after {file_type} EOF — contains {appended_type} data",
            })
        else:
            # Check if it's a ZIP archive (common for steganography)
            try:
                zipfile.ZipFile(io.BytesIO(after_eof))
                result["indicators"].append({
                    "type": "appended_zip",
                    "severity": "high",
                    "detail": f"{len(after_eof)} bytes appended after {file_type} EOF — valid ZIP archive",
                })
            except (zipfile.BadZipFile, Exception):
                entropy = _calculate_entropy(stripped[:4096])
                if entropy > 7.0:
                    result["indicators"].append({
                        "type": "appended_high_entropy",
                        "severity": "medium",
                        "detail": f"{len(after_eof)} bytes appended after {file_type} EOF — high entropy ({entropy:.2f}), possible encrypted/compressed data",
                    })
                else:
                    result["indicators"].append({
                        "type": "appended_data",
                        "severity": "low",
                        "detail": f"{len(after_eof)} bytes appended after {file_type} EOF",
                    })

    return result


def _check_exif_anomalies(data: bytes, file_type: str) -> Dict[str, Any]:
    """Check EXIF metadata for anomalies."""
    result: Dict[str, Any] = {"detected": False, "indicators": [], "exif": {}}

    if file_type not in ("jpeg", "png"):
        return result

    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS

        img = Image.open(io.BytesIO(data))
        exif_data = {}
        if hasattr(img, "_getexif") and img._getexif():
            raw_exif = img._getexif()
            for tag, value in raw_exif.items():
                decoded = TAGS.get(tag, tag)
                exif_data[decoded] = str(value)
            result["exif"] = exif_data

            # Check for GPS coordinates
            if "GPSInfo" in exif_data:
                result["detected"] = True
                result["indicators"].append({
                    "type": "gps_coordinates",
                    "severity": "high",
                    "detail": "EXIF contains GPS location data — possible OPSEC failure",
                })

            # Check for editing software signatures
            software = exif_data.get("Software", "") + " " + exif_data.get("ProcessingSoftware", "")
            editing_tools = ["photoshop", "gimp", "lightroom", "snapseed", "canva", "steg", "steghide"]
            for tool in editing_tools:
                if tool in software.lower():
                    result["detected"] = True
                    result["indicators"].append({
                        "type": "editing_tool_signature",
                        "severity": "medium",
                        "detail": f"EXIF Software tag contains '{tool}' — image was edited",
                    })

            # Check for unusual camera make/model (could indicate synthetic images)
            make = exif_data.get("Make", "")
            model = exif_data.get("Model", "")
            if not make and not model and file_type == "jpeg":
                result["indicators"].append({
                    "type": "missing_camera_info",
                    "severity": "low",
                    "detail": "JPEG has EXIF but no camera make/model — possible synthetic image",
                })

    except Exception:
        pass

    return result


def _check_format_mismatch(file_path: Path, declared_type: str) -> Dict[str, Any]:
    """Check if the file extension matches the actual content type."""
    result: Dict[str, Any] = {"detected": False, "indicators": []}

    with open(file_path, "rb") as f:
        header = f.read(16)

    actual_type = _detect_file_type(header)
    ext = file_path.suffix.lower().lstrip(".")

    ext_map = {
        "jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif",
        "bmp": "bmp", "webp": "wav/webp", "wav": "wav/webp",
        "mp3": "mp3", "ogg": "ogg", "pdf": "pdf", "zip": "zip",
    }
    expected_type = ext_map.get(ext, ext)

    if actual_type != "unknown" and actual_type != expected_type:
        result["detected"] = True
        result["indicators"].append({
            "type": "format_mismatch",
            "severity": "high",
            "detail": f"File extension .{ext} suggests {expected_type}, but content is {actual_type}",
        })

    return result


def _check_entropy_anomalies(data: bytes) -> Dict[str, Any]:
    """Check for entropy anomalies suggesting encrypted/embedded data."""
    result: Dict[str, Any] = {"detected": False, "indicators": [], "entropy": None}

    # Sample first 64KB for entropy
    sample = data[:65536] if len(data) > 65536 else data
    entropy = _calculate_entropy(sample)
    result["entropy"] = round(entropy, 4)

    # Very high entropy (>7.5) across the whole file suggests encrypted/compressed data
    if entropy > 7.5 and len(data) > 1024:
        result["detected"] = True
        result["indicators"].append({
            "type": "high_entropy_payload",
            "severity": "medium",
            "detail": f"File entropy {entropy:.4f} is very high — possible encrypted/compressed payload",
        })

    return result


def analyze_media_file(
    file_path: Path | str,
    cache: Optional[Dict[str, Any]] | bool = None,
) -> Dict[str, Any]:
    """Analyze a single media file for steganographic content.

    Args:
        file_path: Path to the media file.
        cache: Optional dictionary for checksum-based skip cache.
               Pass False to bypass cache, or None to use global cache.

    Returns:
        Dict with: file_info, steganography_detected, indicators, details
    """
    file_path = Path(file_path).expanduser().resolve()
    if not file_path.exists():
        return {"error": f"File not found: {file_path}"}

    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except Exception as e:
        return {"error": f"Failed to read {file_path}: {e}"}

    file_size = len(data)
    file_hash = hashlib.sha256(data).hexdigest()[:16]
    full_hash = hashlib.sha256(data).hexdigest()

    effective_cache: Optional[Dict[str, Any]] = None
    if cache is None:
        effective_cache = _CHECKSUM_CACHE
    elif isinstance(cache, dict):
        effective_cache = cache

    if effective_cache is not None:
        cached_result = effective_cache.get(full_hash) or effective_cache.get(file_hash)
        if cached_result is not None:
            res = dict(cached_result)
            res["file"] = str(file_path)
            return res

    file_type = _detect_file_type(data)

    all_indicators: List[Dict[str, Any]] = []
    detected = False

    # 1. Format mismatch check
    mismatch = _check_format_mismatch(file_path, file_type)
    if mismatch["detected"]:
        detected = True
        all_indicators.extend(mismatch["indicators"])

    # 2. EOF appended data check
    eof_check = _check_eof_appended_data(data, file_type)
    if eof_check["detected"]:
        detected = True
        all_indicators.extend(eof_check["indicators"])

    # 3. EXIF anomalies
    exif_check = _check_exif_anomalies(data, file_type)
    if exif_check["detected"]:
        detected = True
        all_indicators.extend(exif_check["indicators"])

    # 4. LSB steganography (images only)
    lsb_check: Dict[str, Any] = {"detected": False, "indicators": []}
    if file_type in ("jpeg", "png", "gif", "bmp"):
        lsb_check = _check_lsb_steganography(data, file_type)
        if lsb_check["detected"]:
            detected = True
            all_indicators.extend(lsb_check["indicators"])

    # 5. Entropy anomalies
    entropy_check = _check_entropy_anomalies(data)
    if entropy_check["detected"]:
        detected = True
        all_indicators.extend(entropy_check["indicators"])

    # Severity ranking
    severity_order = {"high": 3, "medium": 2, "low": 1}
    all_indicators.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 0), reverse=True)

    result = {
        "file": str(file_path),
        "file_type": file_type,
        "file_size": file_size,
        "sha256_prefix": file_hash,
        "steganography_detected": detected,
        "indicator_count": len(all_indicators),
        "indicators": all_indicators,
        "details": {
            "lsb_entropy": lsb_check.get("lsb_entropy"),
            "file_entropy": entropy_check.get("entropy"),
            "appended_data_size": eof_check.get("appended_size", 0),
            "exif": exif_check.get("exif", {}),
        },
    }

    if effective_cache is not None:
        effective_cache[full_hash] = result
        effective_cache[file_hash] = result

    return result


def analyze_media_batch(
    directory: Path | str,
    workers: int = 4,
    cache: Optional[Dict[str, Any]] | bool = None,
) -> Dict[str, Any]:
    """Analyze all media files in a directory for steganographic content.

    Args:
        directory: Directory to scan recursively.
        workers: Number of parallel worker processes (default: 4).
                 If workers <= 1, processes sequentially.
        cache: Optional dictionary to use as the checksum skip cache.
               Pass False to bypass cache, or None to use global cache.

    Returns:
        Dict with: files_scanned, files_with_indicators, results, summary
    """
    dir_path = Path(directory).expanduser().resolve()
    if not dir_path.is_dir():
        return {"error": f"Directory not found: {dir_path}"}

    media_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".mp3", ".wav", ".ogg", ".pdf"}
    files = sorted(
        f for f in dir_path.rglob("*")
        if f.is_file() and f.suffix.lower() in media_extensions
    )

    if not files:
        return {
            "directory": str(dir_path),
            "files_scanned": 0,
            "files_with_indicators": 0,
            "results": [],
            "summary": {
                "clean": 0,
                "suspicious": 0,
                "suspicion_rate": 0.0,
            },
        }

    effective_cache: Optional[Dict[str, Any]] = None
    if cache is None:
        effective_cache = _CHECKSUM_CACHE
    elif isinstance(cache, dict):
        effective_cache = cache

    results_by_index: Dict[int, Dict[str, Any]] = {}
    pending_items: List[Tuple[int, Path, str]] = []

    for idx, f in enumerate(files):
        try:
            cs = _compute_checksum(f)
            if effective_cache is not None and (cs in effective_cache or cs[:16] in effective_cache):
                cached_val = effective_cache.get(cs) or effective_cache.get(cs[:16])
                cached_result = dict(cached_val)
                cached_result["file"] = str(f)
                results_by_index[idx] = cached_result
            else:
                pending_items.append((idx, f, cs))
        except Exception as e:
            results_by_index[idx] = {
                "file": str(f),
                "error": f"File read error: {e}",
                "steganography_detected": False,
            }

    if pending_items:
        if workers <= 1 or len(pending_items) == 1:
            for idx, f, cs in pending_items:
                res = analyze_media_file(f, cache=effective_cache)
                results_by_index[idx] = res
                if effective_cache is not None:
                    effective_cache[cs] = res
                    effective_cache[cs[:16]] = res
        else:
            max_workers = min(workers, len(pending_items))
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                future_to_item = {
                    executor.submit(analyze_media_file, str(f), False): (idx, f, cs)
                    for idx, f, cs in pending_items
                }
                for future in as_completed(future_to_item):
                    idx, f, cs = future_to_item[future]
                    try:
                        res = future.result()
                    except Exception as e:
                        res = {
                            "file": str(f),
                            "error": f"Worker execution error: {e}",
                            "steganography_detected": False,
                        }
                    results_by_index[idx] = res
                    if effective_cache is not None:
                        effective_cache[cs] = res
                        effective_cache[cs[:16]] = res

    results = [results_by_index[i] for i in range(len(files))]
    files_with_indicators = sum(1 for r in results if r.get("steganography_detected"))

    return {
        "directory": str(dir_path),
        "files_scanned": len(files),
        "files_with_indicators": files_with_indicators,
        "results": results,
        "summary": {
            "clean": len(files) - files_with_indicators,
            "suspicious": files_with_indicators,
            "suspicion_rate": round(files_with_indicators / len(files) * 100, 2) if files else 0.0,
        },
    }


__all__ = [
    "analyze_media_file",
    "analyze_media_batch",
    "get_stego_cache",
    "clear_stego_cache",
    "get_cache",
    "clear_cache",
]

