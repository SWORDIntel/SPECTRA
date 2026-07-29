from __future__ import annotations

import io
import json
import os
import sqlite3
import struct
import tarfile
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from tgarchive.cli.app import cli
from tgarchive.db.index_projector import IndexProjector
from tgarchive.services import archive_member_scanner
from tgarchive.services.archive_member_scanner import (
    MAX_RECORD_LIMIT,
    ArchiveScanError,
    EncryptedArchiveError,
    UnsafeArchiveError,
    UnsupportedArchiveError,
    scan_archive_members,
)


def _events(database: Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            "SELECT * FROM index_outbox ORDER BY sequence_id"
        ).fetchall()
    finally:
        connection.close()


def _write_zip(path: Path, names: tuple[str, ...] = ("alpha.txt", "nested/beta.bin")) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for index, name in enumerate(names):
            archive.writestr(
                name,
                f"payload-{index}".encode(),
                compress_type=zipfile.ZIP_DEFLATED,
            )


def _write_tar(path: Path, names: tuple[str, ...] = ("alpha.txt", "nested/beta.bin")) -> None:
    with tarfile.open(path, "w") as archive:
        for index, name in enumerate(names):
            data = f"payload-{index}".encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


def _mark_zip_encrypted(path: Path) -> None:
    raw = bytearray(path.read_bytes())
    local = raw.index(b"PK\x03\x04")
    central = raw.index(b"PK\x01\x02")
    local_flags = struct.unpack_from("<H", raw, local + 6)[0] | 1
    central_flags = struct.unpack_from("<H", raw, central + 8)[0] | 1
    struct.pack_into("<H", raw, local + 6, local_flags)
    struct.pack_into("<H", raw, central + 8, central_flags)
    path.write_bytes(raw)


def _set_zip_compression(path: Path, method: int) -> None:
    raw = bytearray(path.read_bytes())
    local = raw.index(b"PK\x03\x04")
    central = raw.index(b"PK\x01\x02")
    struct.pack_into("<H", raw, local + 8, method)
    struct.pack_into("<H", raw, central + 10, method)
    path.write_bytes(raw)


def _change_zip_local_name(path: Path) -> None:
    raw = bytearray(path.read_bytes())
    local = raw.index(b"PK\x03\x04")
    name_length = struct.unpack_from("<H", raw, local + 26)[0]
    assert name_length > 0
    raw[local + 30] ^= 1
    path.write_bytes(raw)


def _add_zip64_count_records(path: Path, entry_count: int) -> None:
    raw = bytearray(path.read_bytes())
    eocd = raw.rfind(b"PK\x05\x06")
    assert eocd >= 0
    central_size, central_offset = struct.unpack_from("<LL", raw, eocd + 12)
    assert central_offset + central_size == eocd
    struct.pack_into("<HH", raw, eocd + 8, 0xFFFF, 0xFFFF)
    zip64_record = struct.pack(
        "<4sQ2H2L4Q",
        b"PK\x06\x06",
        44,
        45,
        45,
        0,
        0,
        entry_count,
        entry_count,
        central_size,
        central_offset,
    )
    zip64_locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, eocd, 1)
    raw[eocd:eocd] = zip64_record + zip64_locator
    path.write_bytes(raw)


def test_zip_scan_records_offsets_sizes_crc_and_is_idempotent(tmp_path: Path) -> None:
    archive = tmp_path / "sample.zip"
    database = tmp_path / "index.db"
    _write_zip(archive)

    first = scan_archive_members(archive, database)
    second = scan_archive_members(archive, database)

    assert first["archive_format"] == "zip"
    assert first["records_scanned"] == 2
    assert first["inserted"] == 2
    assert first["already_present"] == 0
    assert first["truncated"] is False
    assert second["inserted"] == 0
    assert second["already_present"] == 2

    events = _events(database)
    assert len(events) == 2
    assert {row["source_table"] for row in events} == {"archive_members"}
    assert {row["event_type"] for row in events} == {"index"}
    records = [json.loads(row["payload_json"])["archive_member"] for row in events]
    assert len({record["member_id"] for record in records}) == 2
    assert all(record["header_offset"] >= 0 for record in records)
    assert all(record["data_offset"] > record["header_offset"] for record in records)
    assert all(record["compressed_size"] > 0 for record in records)
    assert all(record["uncompressed_size"] == 9 for record in records)
    assert all(len(record["crc32"]) == 8 for record in records)
    assert all(record["header_checksum"] is None for record in records)
    assert all(record["archive_size"] == archive.stat().st_size for record in records)
    assert all(record["archive_mtime_ns"] == archive.stat().st_mtime_ns for record in records)
    assert all(len(record["archive_sha256"]) == 64 for record in records)


def test_tar_scan_records_physical_offsets_sizes_and_checksums(tmp_path: Path) -> None:
    archive = tmp_path / "sample.tar"
    database = tmp_path / "index.db"
    _write_tar(archive)

    result = scan_archive_members(archive, database)

    assert result["archive_format"] == "tar"
    records = [
        json.loads(row["payload_json"])["archive_member"]
        for row in _events(database)
    ]
    assert [record["member_name"] for record in records] == [
        "alpha.txt",
        "nested/beta.bin",
    ]
    assert all(record["offset_basis"] == "archive_bytes" for record in records)
    assert all(record["data_offset"] == record["header_offset"] + 512 for record in records)
    assert all(record["compressed_size"] == record["uncompressed_size"] for record in records)
    assert all(len(record["header_checksum"]) == 8 for record in records)
    assert all(record["crc32"] is None for record in records)


def test_compressed_tar_reports_unavailable_physical_offsets(tmp_path: Path) -> None:
    archive = tmp_path / "sample.tar.gz"
    database = tmp_path / "index.db"
    with tarfile.open(archive, "w:gz") as tar:
        data = b"compressed"
        member = tarfile.TarInfo("value.txt")
        member.size = len(data)
        tar.addfile(member, io.BytesIO(data))

    scan_archive_members(archive, database)

    record = json.loads(_events(database)[0]["payload_json"])["archive_member"]
    assert record["header_offset"] is None
    assert record["data_offset"] is None
    assert record["offset_basis"] is None
    assert record["compressed_size"] is None
    assert record["uncompressed_size"] == len(b"compressed")


def test_tar_record_limit_is_enforced_and_reported(tmp_path: Path) -> None:
    archive = tmp_path / "sample.tar"
    database = tmp_path / "index.db"
    names = ("one", "two", "three")
    _write_tar(archive, names)

    result = scan_archive_members(archive, database, limit=2)

    assert result["records_scanned"] == 2
    assert result["inserted"] == 2
    assert result["truncated"] is True
    assert len(_events(database)) == 2


def test_zip_limit_is_preflighted_before_zipfile_loads_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "oversized.zip"
    database = tmp_path / "index.db"
    _write_zip(archive, ("one", "two", "three"))

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ZipFile must not load an oversized central directory")

    monkeypatch.setattr(zipfile.ZipFile, "__init__", forbidden)
    with pytest.raises(ArchiveScanError, match="3 members, exceeding limit 2"):
        scan_archive_members(archive, database, limit=2)

    assert not database.exists()


def test_zip64_limit_is_preflighted_before_zipfile_loads_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "oversized-zip64.zip"
    database = tmp_path / "index.db"
    _write_zip(archive, ("one",))
    _add_zip64_count_records(archive, entry_count=3)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ZipFile must not load an oversized ZIP64 directory")

    monkeypatch.setattr(zipfile.ZipFile, "__init__", forbidden)
    with pytest.raises(ArchiveScanError, match="3 members, exceeding limit 2"):
        scan_archive_members(archive, database, limit=2)

    assert not database.exists()


def test_replacing_archive_at_same_path_creates_new_content_identity(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "replace.zip"
    database = tmp_path / "index.db"
    _write_zip(archive, ("first.txt",))
    first = scan_archive_members(archive, database)

    _write_zip(archive, ("second.txt",))
    second = scan_archive_members(archive, database)

    assert first["archive_id"] != second["archive_id"]
    records = [
        json.loads(row["payload_json"])["archive_member"]
        for row in _events(database)
    ]
    assert {record["archive_id"] for record in records} == {
        first["archive_id"],
        second["archive_id"],
    }


def test_content_mutation_with_preserved_stat_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "mutating.zip"
    database = tmp_path / "index.db"
    _write_zip(archive, ("value.txt",))
    original_scan = archive_member_scanner._scan_records

    def mutate_after_scan(*args: object, **kwargs: object) -> object:
        result = original_scan(*args, **kwargs)
        details = archive.stat()
        raw = bytearray(archive.read_bytes())
        raw[0] ^= 1
        archive.write_bytes(raw)
        os.utime(archive, ns=(details.st_atime_ns, details.st_mtime_ns))
        return result

    monkeypatch.setattr(archive_member_scanner, "_scan_records", mutate_after_scan)
    with pytest.raises(UnsafeArchiveError, match="changed while being scanned"):
        scan_archive_members(archive, database)

    assert not database.exists()


@pytest.mark.parametrize("limit", [0, -1, MAX_RECORD_LIMIT + 1, True, 1.5])
def test_invalid_record_limits_are_rejected(tmp_path: Path, limit: object) -> None:
    with pytest.raises((TypeError, ValueError), match="limit"):
        scan_archive_members(tmp_path / "unused.zip", tmp_path / "index.db", limit=limit)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "names",
    [
        ("../escape",),
        ("/absolute",),
        ("C:/windows",),
        ("ambiguous\\windows",),
        ("same", "same"),
        ("composed/\u00e9", "composed/e\u0301"),
    ],
)
def test_unsafe_or_ambiguous_zip_names_are_rejected_without_events(
    tmp_path: Path,
    names: tuple[str, ...],
) -> None:
    archive = tmp_path / "unsafe.zip"
    database = tmp_path / "index.db"
    _write_zip(archive, names)

    with pytest.raises(UnsafeArchiveError):
        scan_archive_members(archive, database)

    assert not database.exists()


def test_encrypted_zip_is_rejected_without_events(tmp_path: Path) -> None:
    archive = tmp_path / "encrypted.zip"
    database = tmp_path / "index.db"
    _write_zip(archive, ("secret.txt",))
    _mark_zip_encrypted(archive)

    with pytest.raises(EncryptedArchiveError, match="encrypted"):
        scan_archive_members(archive, database)

    assert not database.exists()


def test_unsupported_zip_compression_is_rejected_without_events(tmp_path: Path) -> None:
    archive = tmp_path / "unsupported.zip"
    database = tmp_path / "index.db"
    _write_zip(archive, ("value.txt",))
    _set_zip_compression(archive, 99)

    with pytest.raises(UnsupportedArchiveError, match="compression method 99"):
        scan_archive_members(archive, database)

    assert not database.exists()


def test_conflicting_zip_local_name_is_rejected_without_events(tmp_path: Path) -> None:
    archive = tmp_path / "conflicting.zip"
    database = tmp_path / "index.db"
    _write_zip(archive, ("value.txt",))
    _change_zip_local_name(archive)

    with pytest.raises(UnsafeArchiveError, match="conflicting ZIP member names"):
        scan_archive_members(archive, database)

    assert not database.exists()


def test_tar_links_are_rejected_without_events(tmp_path: Path) -> None:
    archive = tmp_path / "links.tar"
    database = tmp_path / "index.db"
    with tarfile.open(archive, "w") as tar:
        member = tarfile.TarInfo("link")
        member.type = tarfile.SYMTYPE
        member.linkname = "../target"
        tar.addfile(member)

    with pytest.raises(UnsafeArchiveError, match="links"):
        scan_archive_members(archive, database)

    assert not database.exists()


def test_unsupported_input_is_rejected_without_database(tmp_path: Path) -> None:
    archive = tmp_path / "sample.rar"
    database = tmp_path / "index.db"
    archive.write_bytes(b"not an archive")

    with pytest.raises(UnsupportedArchiveError):
        scan_archive_members(archive, database)

    assert not database.exists()


def test_scanner_never_opens_or_extracts_member_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zip_path = tmp_path / "sample.zip"
    tar_path = tmp_path / "sample.tar"
    _write_zip(zip_path, ("value.txt",))
    _write_tar(tar_path, ("value.txt",))

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("member contents must not be opened or extracted")

    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden)
    monkeypatch.setattr(zipfile.ZipFile, "extract", forbidden)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", forbidden)
    monkeypatch.setattr(tarfile.TarFile, "extractfile", forbidden)
    monkeypatch.setattr(tarfile.TarFile, "extract", forbidden)
    monkeypatch.setattr(tarfile.TarFile, "extractall", forbidden)

    assert scan_archive_members(zip_path, tmp_path / "zip.db")["inserted"] == 1
    assert scan_archive_members(tar_path, tmp_path / "tar.db")["inserted"] == 1


def test_missing_archive_reports_clean_scan_error(tmp_path: Path) -> None:
    with pytest.raises(ArchiveScanError, match="unable to inspect"):
        scan_archive_members(tmp_path / "missing.zip", tmp_path / "index.db")


def test_archive_scan_cli_projects_and_resolves_member(tmp_path: Path) -> None:
    archive = tmp_path / "sample.zip"
    database = tmp_path / "index.db"
    _write_zip(archive, ("value.txt",))
    runner = CliRunner()

    scan_result = runner.invoke(
        cli,
        [
            "--db",
            str(database),
            "--output",
            "json",
            "index",
            "scan-archive",
            str(archive),
        ],
    )

    assert scan_result.exit_code == 0, scan_result.output
    scan = json.loads(scan_result.output)["details"]
    with IndexProjector(database) as projector:
        assert projector.drain()["processed"] == 1
        lookup = projector.lookup_record(
            projection="archive-members",
            namespace=scan["archive_id"],
            external_id="0",
        )
    assert lookup["found"] is True
    assert lookup["native"]["found"] is True
    assert lookup["records"][0]["payload"]["archive_member"]["member_name"] == "value.txt"
