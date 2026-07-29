import json
import sqlite3
from pathlib import Path

from training.spectra_operator.export_audit_corpus import (
    ALLOWED_COLUMNS,
    REDACTION_VERSION,
    SCHEMA_VERSION,
    export_operation_audit,
    main as export_main,
)
from training.spectra_operator.generate_data import build_rows, write_jsonl


def test_spectra_operator_generator_outputs_valid_chat_rows(tmp_path: Path):
    output_path = tmp_path / "train.jsonl"
    rows = build_rows(count_per_template=2, seed=7)
    write_jsonl(output_path, rows)

    assert rows
    operation_ids = set()
    for line in output_path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        messages = payload["messages"]
        assert [message["role"] for message in messages] == ["system", "user", "assistant"]
        assistant = json.loads(messages[-1]["content"])
        if set(assistant) == {"error"}:
            assert isinstance(assistant["error"], str)
            assert assistant["error"].startswith("Refusal:")
            continue
        assert set(assistant) == {"operation_id", "arguments", "dry_run"}
        assert isinstance(assistant["arguments"], dict)
        operation_ids.add(assistant["operation_id"])

    assert "channel.download" in operation_ids
    assert "config.get" in operation_ids


def _create_audit_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE operation_audit (
                audit_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                actor TEXT NOT NULL,
                request_text TEXT,
                operation_id TEXT,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                envelope_json TEXT,
                planned_command_json TEXT,
                actual_argv_json TEXT,
                result_json TEXT,
                error_json TEXT,
                unallowlisted_secret TEXT
            )
            """
        )


def _insert_audit_row(
    path: Path,
    *,
    audit_id: str,
    started_at: str,
    request_text: str = "download media using token: request-secret",
    result_json: str | None = None,
    error_json: str | None = None,
) -> None:
    envelope = {
        "operation_id": "channel.download",
        "arguments": {
            "entity": "-1002407846598",
            "api_hash": "envelope-secret",
            "notification_email": "operator@example.invalid",
        },
        "dry_run": False,
    }
    planned = [
        "spectra",
        "channel",
        "download",
        "--account",
        "+447700900123",
        "--api-hash=planned-secret",
        "-1002407846598",
    ]
    actual = [
        "spectra",
        "operations",
        "run",
        "--token",
        "actual-secret",
        "--client-secret",
        "generic-flag-secret",
        "https://operator:password@example.invalid/job",
    ]
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO operation_audit (
                audit_id, source, actor, request_text, operation_id, status,
                started_at, finished_at, envelope_json, planned_command_json,
                actual_argv_json, result_json, error_json, unallowlisted_secret
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                "agent.run",
                "private-actor",
                request_text,
                "channel.download",
                "failed" if error_json else "completed",
                started_at,
                "2026-07-29T12:01:00+00:00",
                json.dumps(envelope),
                json.dumps(planned),
                json.dumps(actual),
                result_json or json.dumps({"downloaded": 4, "session_secret": "result-secret"}),
                error_json,
                "must-never-export",
            ),
        )


def test_audit_corpus_export_is_allowlisted_redacted_and_deduplicated(tmp_path: Path):
    database = tmp_path / "tasks.sqlite3"
    output = tmp_path / "audit.jsonl"
    _create_audit_database(database)
    error = json.dumps(
        {
            "category": "network",
            "message": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturevalue",
            "private_key": "private-key-material",
        }
    )
    _insert_audit_row(
        database,
        audit_id="audit-1",
        started_at="2026-07-29T12:00:00+00:00",
        error_json=error,
    )
    _insert_audit_row(
        database,
        audit_id="audit-2",
        started_at="2026-07-29T12:00:30+00:00",
        error_json=error,
    )

    summary = export_operation_audit(database, output)

    assert summary.rows_read == 2
    assert summary.rows_exported == 1
    assert summary.duplicates_skipped == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema_version",
        "redaction_version",
        "request",
        "operation",
        "execution",
        "dedup_hash",
        "provenance",
    }
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["redaction_version"] == REDACTION_VERSION
    assert payload["execution"]["status"] == "failed"
    assert payload["execution"]["error_category"] == "network"
    assert payload["operation"]["envelope"]["arguments"]["api_hash"] == "[redacted]"
    assert payload["operation"]["planned_command"][4] == "[redacted]"
    assert payload["operation"]["actual_argv"][4] == "[redacted]"
    assert payload["provenance"]["source_table"] == "operation_audit"
    assert payload["provenance"]["audit_id"] == "audit-1"
    assert len(payload["dedup_hash"]) == 64
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "request-secret",
        "envelope-secret",
        "planned-secret",
        "actual-secret",
        "generic-flag-secret",
        "result-secret",
        "private-key-material",
        "private-actor",
        "must-never-export",
        "operator@example.invalid",
        "+447700900123",
        "password@example.invalid",
        "eyJhbGciOiJIUzI1NiJ9",
    ):
        assert forbidden not in serialized

    assert "actor" not in ALLOWED_COLUMNS
    assert "unallowlisted_secret" not in ALLOWED_COLUMNS


def test_audit_corpus_export_handles_malformed_json_and_cli_filters_status(tmp_path: Path, capsys):
    database = tmp_path / "tasks.sqlite3"
    output = tmp_path / "audit.jsonl"
    _create_audit_database(database)
    _insert_audit_row(
        database,
        audit_id="audit-completed",
        started_at="2026-07-29T12:00:00+00:00",
        result_json='{"token":"unterminated-secret"',
    )
    _insert_audit_row(
        database,
        audit_id="audit-failed",
        started_at="2026-07-29T12:01:00+00:00",
        error_json=json.dumps({"category": "execution", "message": "safe failure"}),
    )

    exit_code = export_main(
        [
            "--database",
            str(database),
            "--output",
            str(output),
            "--status",
            "completed",
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["rows_exported"] == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["execution"]["status"] == "completed"
    assert payload["execution"]["result"] == {"malformed": True}
    assert "unterminated-secret" not in output.read_text(encoding="utf-8")
