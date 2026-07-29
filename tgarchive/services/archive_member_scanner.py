"""Bounded, metadata-only ZIP and TAR member indexing."""

from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import stat
import struct
import tarfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from ..db.index_outbox import IndexOutbox
from ..sqlite_runtime import connect_sqlite

DEFAULT_RECORD_LIMIT = 10_000
MAX_RECORD_LIMIT = 100_000
ARCHIVE_MEMBER_SCHEMA_VERSION = 1

_ZIP_LOCAL_HEADER = struct.Struct("<4s5H3L2H")
_ZIP_LOCAL_SIGNATURE = b"PK\x03\x04"
_ZIP_EOCD = struct.Struct("<4s4H2LH")
_ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP64_EOCD = struct.Struct("<4sQ2H2L4Q")
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_ZIP64_LOCATOR = struct.Struct("<4sLQL")
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP_EOCD_MAX_SEARCH = _ZIP_EOCD.size + 0xFFFF
_ZIP_ENCRYPTION_FLAGS = 0x41
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_SUPPORTED_ZIP_COMPRESSION = {
    zipfile.ZIP_STORED: "stored",
    zipfile.ZIP_DEFLATED: "deflate",
    zipfile.ZIP_BZIP2: "bzip2",
    zipfile.ZIP_LZMA: "lzma",
}


class ArchiveScanError(ValueError):
    """Base error for archives that cannot be indexed unambiguously."""


class UnsupportedArchiveError(ArchiveScanError):
    """The selected file is not a supported ZIP or TAR archive."""


class UnsafeArchiveError(ArchiveScanError):
    """The archive contains ambiguous or unsafe member metadata."""


class EncryptedArchiveError(ArchiveScanError):
    """The archive contains encrypted member metadata."""


@dataclass(frozen=True)
class _ArchiveSnapshot:
    device: int
    inode: int
    size: int
    mtime_ns: int


def _snapshot(path: Path) -> _ArchiveSnapshot:
    try:
        details = path.stat()
    except OSError as exc:
        raise ArchiveScanError(f"unable to inspect archive {path}: {exc}") from exc
    if not stat.S_ISREG(details.st_mode):
        raise ArchiveScanError(f"archive is not a regular file: {path}")
    return _ArchiveSnapshot(
        device=details.st_dev,
        inode=details.st_ino,
        size=details.st_size,
        mtime_ns=details.st_mtime_ns,
    )


def _validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit < 1 or limit > MAX_RECORD_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_RECORD_LIMIT}")
    return limit


def _canonical_member_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise UnsafeArchiveError("archive member name must be a non-empty string")
    if "\x00" in name or "\\" in name or not name.isprintable():
        raise UnsafeArchiveError(f"unsafe archive member name: {name!r}")

    normalized = unicodedata.normalize("NFC", name)
    directory_trimmed = normalized[:-1] if normalized.endswith("/") else normalized
    if not directory_trimmed:
        raise UnsafeArchiveError(f"unsafe archive member name: {name!r}")
    path = PurePosixPath(directory_trimmed)
    if path.is_absolute() or _WINDOWS_DRIVE.match(directory_trimmed):
        raise UnsafeArchiveError(f"absolute archive member path: {name!r}")
    if any(part in {"", ".", ".."} for part in directory_trimmed.split("/")):
        raise UnsafeArchiveError(f"ambiguous archive member path: {name!r}")
    return path.as_posix()


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _content_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise ArchiveScanError(f"unable to hash archive {path}: {exc}") from exc
    return digest.hexdigest()


def _find_zip_eocd(handle: BinaryIO, archive_size: int) -> tuple[int, tuple[Any, ...]]:
    read_size = min(archive_size, _ZIP_EOCD_MAX_SEARCH)
    try:
        handle.seek(archive_size - read_size)
        tail = handle.read(read_size)
    except OSError as exc:
        raise ArchiveScanError(f"unable to read ZIP end record: {exc}") from exc

    search_end = len(tail)
    while True:
        relative_offset = tail.rfind(_ZIP_EOCD_SIGNATURE, 0, search_end)
        if relative_offset < 0:
            raise UnsafeArchiveError("ZIP end-of-central-directory record is missing")
        if relative_offset + _ZIP_EOCD.size <= len(tail):
            fields = _ZIP_EOCD.unpack_from(tail, relative_offset)
            comment_length = fields[-1]
            if relative_offset + _ZIP_EOCD.size + comment_length == len(tail):
                return archive_size - read_size + relative_offset, fields
        search_end = relative_offset


def _zip64_entry_count(
    handle: BinaryIO,
    *,
    eocd_offset: int,
) -> int:
    locator_offset = eocd_offset - _ZIP64_LOCATOR.size
    if locator_offset < 0:
        raise UnsafeArchiveError("ZIP64 locator is missing")
    try:
        handle.seek(locator_offset)
        locator_raw = handle.read(_ZIP64_LOCATOR.size)
    except OSError as exc:
        raise ArchiveScanError(f"unable to read ZIP64 locator: {exc}") from exc
    if len(locator_raw) != _ZIP64_LOCATOR.size:
        raise UnsafeArchiveError("truncated ZIP64 locator")

    signature, disk_number, record_offset, disk_count = _ZIP64_LOCATOR.unpack(locator_raw)
    if signature != _ZIP64_LOCATOR_SIGNATURE:
        raise UnsafeArchiveError("ZIP64 locator is missing")
    if disk_number != 0 or disk_count != 1:
        raise UnsupportedArchiveError("multi-disk ZIP64 archives are unsupported")
    if record_offset < 0 or record_offset + _ZIP64_EOCD.size > locator_offset:
        raise UnsafeArchiveError("invalid ZIP64 end-record offset")

    try:
        handle.seek(record_offset)
        record_raw = handle.read(_ZIP64_EOCD.size)
    except OSError as exc:
        raise ArchiveScanError(f"unable to read ZIP64 end record: {exc}") from exc
    if len(record_raw) != _ZIP64_EOCD.size:
        raise UnsafeArchiveError("truncated ZIP64 end record")

    fields = _ZIP64_EOCD.unpack(record_raw)
    (
        signature,
        record_size,
        _version_made,
        _version_needed,
        disk_number,
        central_disk,
        entries_on_disk,
        total_entries,
        _central_size,
        _central_offset,
    ) = fields
    if signature != _ZIP64_EOCD_SIGNATURE or record_size < 44:
        raise UnsafeArchiveError("invalid ZIP64 end record")
    if record_offset + 12 + record_size > locator_offset:
        raise UnsafeArchiveError("ZIP64 end record overlaps its locator")
    if disk_number != 0 or central_disk != 0 or entries_on_disk != total_entries:
        raise UnsupportedArchiveError("multi-disk ZIP64 archives are unsupported")
    return total_entries


def _preflight_zip_entry_count(path: Path, *, archive_size: int, limit: int) -> int:
    try:
        with path.open("rb") as handle:
            eocd_offset, fields = _find_zip_eocd(handle, archive_size)
            (
                _signature,
                disk_number,
                central_disk,
                entries_on_disk,
                total_entries,
                _central_size,
                _central_offset,
                _comment_length,
            ) = fields
            if disk_number != 0 or central_disk != 0:
                raise UnsupportedArchiveError("multi-disk ZIP archives are unsupported")
            if entries_on_disk != total_entries:
                raise UnsupportedArchiveError("multi-disk ZIP archives are unsupported")
            if entries_on_disk == 0xFFFF or total_entries == 0xFFFF:
                total_entries = _zip64_entry_count(
                    handle,
                    eocd_offset=eocd_offset,
                )
    except OSError as exc:
        raise ArchiveScanError(f"unable to preflight ZIP archive {path}: {exc}") from exc

    if total_entries > limit:
        raise ArchiveScanError(
            f"ZIP contains {total_entries} members, exceeding limit {limit}"
        )
    return total_entries


def _zip_data_offset(
    handle: BinaryIO,
    info: zipfile.ZipInfo,
    *,
    archive_size: int,
) -> int:
    try:
        handle.seek(info.header_offset)
        raw_header = handle.read(_ZIP_LOCAL_HEADER.size)
    except OSError as exc:
        raise ArchiveScanError(
            f"unable to read ZIP local header for {info.filename!r}: {exc}"
        ) from exc
    if len(raw_header) != _ZIP_LOCAL_HEADER.size:
        raise UnsafeArchiveError(f"truncated ZIP local header for {info.filename!r}")

    fields = _ZIP_LOCAL_HEADER.unpack(raw_header)
    signature = fields[0]
    local_flags = fields[2]
    local_compression = fields[3]
    name_length = fields[-2]
    extra_length = fields[-1]
    if signature != _ZIP_LOCAL_SIGNATURE:
        raise UnsafeArchiveError(f"invalid ZIP local header for {info.filename!r}")
    if local_flags & _ZIP_ENCRYPTION_FLAGS:
        raise EncryptedArchiveError(
            f"encrypted ZIP member is unsupported: {info.filename!r}"
        )
    if local_flags != info.flag_bits or local_compression != info.compress_type:
        raise UnsafeArchiveError(
            f"conflicting ZIP headers for {info.filename!r}"
        )

    data_offset = info.header_offset + _ZIP_LOCAL_HEADER.size + name_length + extra_length
    data_end = data_offset + info.compress_size
    if data_offset < 0 or data_end > archive_size:
        raise UnsafeArchiveError(f"invalid ZIP data span for {info.filename!r}")
    try:
        raw_name = handle.read(name_length)
        handle.seek(extra_length, 1)
        encoding = "utf-8" if local_flags & 0x800 else "cp437"
        local_name = raw_name.decode(encoding)
    except (OSError, UnicodeDecodeError) as exc:
        raise UnsafeArchiveError(
            f"invalid ZIP local filename for {info.filename!r}"
        ) from exc
    if len(raw_name) != name_length or local_name != info.orig_filename:
        raise UnsafeArchiveError(
            f"conflicting ZIP member names for {info.filename!r}"
        )
    return data_offset


def _zip_members(
    path: Path,
    archive_id: str,
    *,
    limit: int,
    archive_size: int,
) -> tuple[list[dict[str, Any]], bool]:
    records: list[dict[str, Any]] = []
    canonical_names: set[str] = set()
    expected_entries = _preflight_zip_entry_count(
        path,
        archive_size=archive_size,
        limit=limit,
    )
    try:
        with zipfile.ZipFile(path, mode="r") as archive, path.open("rb") as raw:
            infos = archive.infolist()
            if len(infos) != expected_entries:
                raise UnsafeArchiveError(
                    "ZIP central-directory count changed after preflight"
                )
            for member_index, info in enumerate(infos):
                canonical_name = _canonical_member_name(info.orig_filename)
                if canonical_name in canonical_names:
                    raise UnsafeArchiveError(
                        f"duplicate canonical ZIP member name: {info.orig_filename!r}"
                    )
                canonical_names.add(canonical_name)
                if info.flag_bits & _ZIP_ENCRYPTION_FLAGS:
                    raise EncryptedArchiveError(
                        f"encrypted ZIP member is unsupported: {info.filename!r}"
                    )
                compression = _SUPPORTED_ZIP_COMPRESSION.get(info.compress_type)
                if compression is None:
                    raise UnsupportedArchiveError(
                        f"unsupported ZIP compression method {info.compress_type} "
                        f"for {info.filename!r}"
                    )
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if unix_mode and stat.S_ISLNK(unix_mode):
                    raise UnsafeArchiveError(
                        f"ZIP symbolic links are unsupported: {info.filename!r}"
                    )
                if info.file_size < 0 or info.compress_size < 0 or info.header_offset < 0:
                    raise UnsafeArchiveError(
                        f"invalid ZIP member sizes or offset: {info.filename!r}"
                    )

                data_offset = _zip_data_offset(
                    raw,
                    info,
                    archive_size=archive_size,
                )
                member_id = _stable_id(archive_id, "zip", canonical_name)
                records.append(
                    {
                        "schema_version": ARCHIVE_MEMBER_SCHEMA_VERSION,
                        "member_id": member_id,
                        "archive_id": archive_id,
                        "archive_path": str(path),
                        "archive_format": "zip",
                        "member_index": member_index,
                        "member_name": info.orig_filename,
                        "canonical_member_name": canonical_name,
                        "member_type": "directory" if info.is_dir() else "file",
                        "header_offset": info.header_offset,
                        "data_offset": data_offset,
                        "offset_basis": "archive_bytes",
                        "compressed_size": info.compress_size,
                        "uncompressed_size": info.file_size,
                        "compression": compression,
                        "crc32": f"{info.CRC:08x}",
                        "header_checksum": None,
                    }
                )
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ArchiveScanError(f"unable to scan ZIP archive {path}: {exc}") from exc
    return records, False


def _tar_offsets_are_physical(archive: tarfile.TarFile) -> bool:
    return isinstance(archive.fileobj, io.BufferedReader)


def _tar_member_type(member: tarfile.TarInfo) -> str:
    if member.isfile():
        return "file"
    if member.isdir():
        return "directory"
    if member.issym() or member.islnk():
        raise UnsafeArchiveError(
            f"TAR links are unsupported: {member.name!r}"
        )
    raise UnsafeArchiveError(
        f"unsupported TAR member type for {member.name!r}"
    )


def _tar_members(
    path: Path,
    archive_id: str,
    *,
    limit: int,
    archive_size: int,
) -> tuple[list[dict[str, Any]], bool]:
    records: list[dict[str, Any]] = []
    canonical_names: set[str] = set()
    truncated = False
    try:
        with tarfile.open(path, mode="r:*", errorlevel=2) as archive:
            physical_offsets = _tar_offsets_are_physical(archive)
            for member_index, member in enumerate(archive):
                if member_index >= limit:
                    truncated = True
                    break
                canonical_name = _canonical_member_name(member.name)
                if canonical_name in canonical_names:
                    raise UnsafeArchiveError(
                        f"duplicate canonical TAR member name: {member.name!r}"
                    )
                canonical_names.add(canonical_name)
                if member.size < 0 or member.offset < 0 or member.offset_data < 0:
                    raise UnsafeArchiveError(
                        f"invalid TAR member sizes or offset: {member.name!r}"
                    )
                sparse_headers = any(
                    key.startswith("GNU.sparse.") for key in member.pax_headers
                )
                if member.sparse or sparse_headers:
                    raise UnsafeArchiveError(
                        f"sparse TAR members are unsupported: {member.name!r}"
                    )
                member_type = _tar_member_type(member)
                if physical_offsets and member.offset_data + member.size > archive_size:
                    raise UnsafeArchiveError(
                        f"invalid TAR data span for {member.name!r}"
                    )

                member_id = _stable_id(archive_id, "tar", canonical_name)
                records.append(
                    {
                        "schema_version": ARCHIVE_MEMBER_SCHEMA_VERSION,
                        "member_id": member_id,
                        "archive_id": archive_id,
                        "archive_path": str(path),
                        "archive_format": "tar",
                        "member_index": member_index,
                        "member_name": member.name,
                        "canonical_member_name": canonical_name,
                        "member_type": member_type,
                        "header_offset": member.offset if physical_offsets else None,
                        "data_offset": member.offset_data if physical_offsets else None,
                        "offset_basis": "archive_bytes" if physical_offsets else None,
                        "compressed_size": member.size if physical_offsets else None,
                        "uncompressed_size": member.size,
                        "compression": "stored" if physical_offsets else "archive_stream",
                        "crc32": None,
                        "header_checksum": f"{member.chksum:08x}",
                    }
                )
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise ArchiveScanError(f"unable to scan TAR archive {path}: {exc}") from exc
    return records, truncated


def _scan_records(
    path: Path,
    archive_id: str,
    *,
    limit: int,
    archive_size: int,
) -> tuple[list[dict[str, Any]], bool, str]:
    try:
        is_zip = zipfile.is_zipfile(path)
    except OSError as exc:
        raise ArchiveScanError(f"unable to inspect archive {path}: {exc}") from exc
    if is_zip:
        records, truncated = _zip_members(
            path,
            archive_id,
            limit=limit,
            archive_size=archive_size,
        )
        return records, truncated, "zip"

    try:
        is_tar = tarfile.is_tarfile(path)
    except OSError as exc:
        raise ArchiveScanError(f"unable to inspect archive {path}: {exc}") from exc
    if is_tar:
        records, truncated = _tar_members(
            path,
            archive_id,
            limit=limit,
            archive_size=archive_size,
        )
        return records, truncated, "tar"
    raise UnsupportedArchiveError(f"unsupported archive format: {path}")


def _source_revision(record: dict[str, Any]) -> str:
    serialized = json.dumps(
        record,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def scan_archive_members(
    archive_path: Path | str,
    database: Path | str,
    *,
    limit: int = DEFAULT_RECORD_LIMIT,
) -> dict[str, Any]:
    """Scan archive headers and append idempotent member metadata events."""
    validated_limit = _validate_limit(limit)
    path = Path(archive_path).expanduser().resolve()
    database_path = Path(database).expanduser().resolve()
    before = _snapshot(path)
    content_sha256 = _content_sha256(path)
    if _snapshot(path) != before:
        raise UnsafeArchiveError(f"archive changed while being identified: {path}")
    archive_id = _stable_id("archive-content-sha256", content_sha256)
    records, truncated, archive_format = _scan_records(
        path,
        archive_id,
        limit=validated_limit,
        archive_size=before.size,
    )
    after = _snapshot(path)
    final_content_sha256 = _content_sha256(path)
    if _snapshot(path) != after or after != before or final_content_sha256 != content_sha256:
        raise UnsafeArchiveError(f"archive changed while being scanned: {path}")
    for record in records:
        record["archive_size"] = before.size
        record["archive_mtime_ns"] = before.mtime_ns
        record["archive_sha256"] = content_sha256

    inserted = 0
    already_present = 0
    try:
        with connect_sqlite(database_path) as connection:
            IndexOutbox.ensure_schema(connection)
            for record in records:
                sequence_id = IndexOutbox.append_to(
                    connection,
                    source_table="archive_members",
                    source_key=record["member_id"],
                    event_type="index",
                    payload={"archive_member": record},
                    source_revision=_source_revision(record),
                )
                if sequence_id is None:
                    already_present += 1
                else:
                    inserted += 1
    except (OSError, sqlite3.Error) as exc:
        raise ArchiveScanError(
            f"unable to append archive metadata to {database_path}: {exc}"
        ) from exc

    return {
        "database": str(database_path),
        "archive_path": str(path),
        "archive_id": archive_id,
        "archive_format": archive_format,
        "record_limit": validated_limit,
        "records_scanned": len(records),
        "inserted": inserted,
        "already_present": already_present,
        "truncated": truncated,
    }


__all__ = [
    "ARCHIVE_MEMBER_SCHEMA_VERSION",
    "DEFAULT_RECORD_LIMIT",
    "MAX_RECORD_LIMIT",
    "ArchiveScanError",
    "EncryptedArchiveError",
    "UnsafeArchiveError",
    "UnsupportedArchiveError",
    "scan_archive_members",
]
