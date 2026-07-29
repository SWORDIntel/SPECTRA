import hashlib
import json

from click.testing import CliRunner

from tgarchive.cli.app import cli
from tgarchive.db.index_outbox import IndexOutbox
from tgarchive.services.index_backfill import backfill_channel_export


def _export(tmp_path):
    export_dir = tmp_path / "Channel_123"
    export_dir.mkdir()
    (export_dir / "manifest.json").write_text(json.dumps({
        "entity": -100123,
        "entity_id": 123,
        "title": "Channel",
    }))
    valid = json.dumps({
        "message_id": 42,
        "path": "media/42.bin",
        "size": 4,
        "sha256": "abc123",
        "failed": False,
        "recorded_at": "2026-07-29T00:00:00+00:00",
    }, separators=(",", ":")).encode() + b"\n"
    malformed = b"{not-json}\n"
    partial = b'{"message_id":43'
    (export_dir / "media_manifest.jsonl").write_bytes(valid + malformed + partial)
    return export_dir, valid


def test_backfill_export_is_byte_exact_partial_safe_and_idempotent(tmp_path):
    export_dir, valid = _export(tmp_path)
    database = tmp_path / "spectra.db"

    first = backfill_channel_export(export_dir, database)
    second = backfill_channel_export(export_dir, database)

    assert first["channel_id"] == -100123
    assert first["records_read"] == 2
    assert first["inserted"] == 1
    assert first["invalid"] == 1
    assert first["incomplete_tail"] == 1
    assert first["export_id"]
    assert second["inserted"] == 0
    assert second["already_present"] == 1
    events = IndexOutbox(database).events()
    assert len(events) == 1
    media = events[0]["payload"]["media_manifest"]
    assert media["byte_offset"] == 0
    assert media["byte_length"] == len(valid)
    assert media["record_sha256"] == hashlib.sha256(valid).hexdigest()
    assert media["export_id"] == first["export_id"]
    assert media["record_ordinal"] == 0
    assert events[0]["payload"]["export_id"] == first["export_id"]
    assert events[0]["source_key"] == "-100123:42"
    assert json.loads((export_dir / "manifest.json").read_text())["export_id"] == first["export_id"]


def test_backfill_export_cli_uses_selected_database(tmp_path):
    export_dir, _valid = _export(tmp_path)
    database = tmp_path / "selected.db"

    result = CliRunner().invoke(cli, [
        "--db", str(database),
        "--output", "json",
        "index", "backfill-export", str(export_dir),
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["details"]["inserted"] == 1
    assert payload["details"]["database"] == str(database.resolve())
    assert IndexOutbox(database).status()["outbox"]["total"] == 1
