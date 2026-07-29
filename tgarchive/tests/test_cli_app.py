import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

import tgarchive.cli.app as cli_app
from tgarchive.core.config_models import Config
from tgarchive.cli.app import cli


def test_help_is_available_without_heavy_runtime_logging():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "SPECTRA: Telegram collection" in result.output
    assert "QIHSE" not in result.output


def test_version_supports_machine_output():
    result = CliRunner().invoke(cli, ["--output", "json", "version"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["spectra"]
    assert payload["python"]


def test_operations_list_and_schema_expose_typed_registry():
    list_result = CliRunner().invoke(cli, ["--output", "json", "operations", "list"])
    schema_result = CliRunner().invoke(cli, ["--output", "json", "operations", "schema", "channel.download"])

    assert list_result.exit_code == 0
    operations = {item["operation_id"]: item for item in json.loads(list_result.output)}
    assert operations["version"]["executable"] is True
    assert operations["channel.download"]["telegram_backed"] is True
    assert schema_result.exit_code == 0
    schema = json.loads(schema_result.output)
    assert schema["operation_id"] == "channel.download"
    assert schema["request_schema"]["properties"]["max_connections"]["default"] == 32


def test_index_status_exposes_outbox_and_projection_state(tmp_path: Path):
    result = CliRunner().invoke(
        cli,
        ["--db", str(tmp_path / "spectra.db"), "--output", "json", "index", "status"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["outbox"]["pending"] == 0
    assert payload["projections"] == []


def test_index_process_rebuild_and_verify_cli(tmp_path: Path):
    from tgarchive.db.index_outbox import IndexOutbox

    database = tmp_path / "spectra.db"
    IndexOutbox(database).append(
        source_table="messages",
        source_key="42",
        event_type="upsert",
        payload={"message_id": 42, "text": "projection test"},
        source_revision="v1",
    )

    runner = CliRunner()
    process_result = runner.invoke(
        cli,
        ["--db", str(database), "--output", "json", "index", "process"],
    )
    verify_result = runner.invoke(
        cli,
        ["--db", str(database), "--output", "json", "index", "verify", "--no-native"],
    )
    rebuild_result = runner.invoke(
        cli,
        ["--db", str(database), "--output", "json", "index", "rebuild", "--projection", "all"],
    )

    assert process_result.exit_code == 0, process_result.output
    assert json.loads(process_result.output)["details"]["processed"] == 1
    assert verify_result.exit_code == 0, verify_result.output
    assert json.loads(verify_result.output)["details"]["ok"] is True
    assert rebuild_result.exit_code == 0, rebuild_result.output
    assert json.loads(rebuild_result.output)["details"]["events"] == 1

    drain_result = runner.invoke(
        cli,
        ["--db", str(database), "--output", "json", "index", "drain"],
    )
    assert drain_result.exit_code == 0, drain_result.output
    assert json.loads(drain_result.output)["details"]["drained"] is True


def test_index_record_lookup_cli_resolves_typed_event(tmp_path: Path):
    from tgarchive.db.index_outbox import IndexOutbox
    from tgarchive.db.index_projector import IndexProjector

    database = tmp_path / "spectra.db"
    IndexOutbox(database).append(
        source_table="task_events",
        source_key="31",
        event_type="completed",
        payload={
            "event_id": 31,
            "task_id": "task-31",
            "status": "completed",
            "event_at": "2026-07-29T00:00:00+00:00",
        },
        source_revision="v1",
    )
    IndexProjector(database).process()

    result = CliRunner().invoke(
        cli,
        [
            "--db",
            str(database),
            "--output",
            "json",
            "index",
            "lookup-record",
            "events",
            "task_events",
            "31",
        ],
    )

    assert result.exit_code == 0, result.output
    details = json.loads(result.output)["details"]
    assert details["found"] is True
    assert details["native"]["found"] is True
    assert details["records"][0]["payload"]["task_id"] == "task-31"


def _invoke_index_convenience(monkeypatch, arguments: list[str]):
    calls = []

    def fake_operation_result(operation_id, operation_arguments, context):
        calls.append((operation_id, operation_arguments))
        return {"details": operation_arguments}

    monkeypatch.setattr(cli_app, "_operation_result", fake_operation_result)
    result = CliRunner().invoke(cli, ["--output", "json", "index", *arguments])
    return result, calls


def test_index_checkpoint_convenience_routes_typed_lookup(monkeypatch):
    result, calls = _invoke_index_convenience(monkeypatch, ["checkpoint", "17"])

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "index.lookup-record",
            {
                "projection": "checkpoints",
                "namespace": "checkpoints",
                "external_id": "17",
            },
        )
    ]


@pytest.mark.parametrize(
    ("kind", "namespace"),
    [
        ("task", "task_events"),
        ("operation", "operation_events"),
        ("audit", "operation_audit_log"),
    ],
)
def test_index_event_convenience_maps_kind(monkeypatch, kind: str, namespace: str):
    result, calls = _invoke_index_convenience(monkeypatch, ["event", kind, "23"])

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "index.lookup-record",
            {
                "projection": "events",
                "namespace": namespace,
                "external_id": "23",
            },
        )
    ]


def test_index_export_record_convenience_routes_typed_lookup(monkeypatch):
    result, calls = _invoke_index_convenience(
        monkeypatch,
        ["export-record", "export-abc", "0"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "index.lookup-record",
            {
                "projection": "exports",
                "namespace": "export-abc",
                "external_id": "0",
            },
        )
    ]


def test_index_archive_member_convenience_routes_typed_lookup(monkeypatch):
    result, calls = _invoke_index_convenience(
        monkeypatch,
        ["archive-member", "archive-abc", "4"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "index.lookup-record",
            {
                "projection": "archive-members",
                "namespace": "archive-abc",
                "external_id": "4",
            },
        )
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        ["checkpoint", "0"],
        ["event", "unknown", "1"],
        ["event", "task", "0"],
        ["export-record", "export-abc", "-1"],
        ["archive-member", "archive-abc", "-1"],
    ],
)
def test_index_convenience_rejects_invalid_kind_and_boundaries(arguments: list[str]):
    result = CliRunner().invoke(cli, ["index", *arguments])

    assert result.exit_code == cli_app.EXIT_USAGE


def test_index_watch_defaults_to_fast_polling():
    result = CliRunner().invoke(cli, ["index", "watch", "--help"])

    assert result.exit_code == 0
    assert "--poll-interval" in result.output
    assert "[default: 0.1;" in result.output


def test_index_watch_backs_off_failures_and_keeps_summary_on_stdout(
    tmp_path: Path,
    monkeypatch,
):
    from tgarchive.db import index_projector

    results = iter([
        {
            "claimed": 1,
            "processed": 0,
            "failed": 1,
            "failures": [{
                "sequence_id": 7,
                "error": "token=worker-secret projection failed",
            }],
        },
        {
            "claimed": 1,
            "processed": 0,
            "failed": 1,
            "failures": [{
                "sequence_id": 7,
                "error": "password: second-secret projection failed",
            }],
        },
    ])
    sleeps = []

    class Projector:
        def __init__(self, database):
            assert database == tmp_path / "spectra.db"

        def process(self, *, batch_size, lease_seconds):
            assert (batch_size, lease_seconds) == (4, 9)
            try:
                return next(results)
            except StopIteration:
                raise KeyboardInterrupt

    monkeypatch.setattr(index_projector, "IndexProjector", Projector)
    monkeypatch.setattr(cli_app.time, "sleep", sleeps.append)
    result = CliRunner().invoke(
        cli,
        [
            "--db",
            str(tmp_path / "spectra.db"),
            "--output",
            "json",
            "index",
            "watch",
            "--batch-size",
            "4",
            "--lease-seconds",
            "9",
            "--poll-interval",
            "0.5",
            "--max-backoff",
            "8",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert sleeps == [0.5, 1.0]
    assert json.loads(result.stdout) == {
        "batches": 2,
        "claimed": 2,
        "elapsed_seconds": pytest.approx(0, abs=0.1),
        "failed": 2,
        "interrupted": True,
        "processed": 0,
        "worker_errors": 0,
    }
    diagnostics = [json.loads(line) for line in result.stderr.splitlines()]
    assert [item["event"] for item in diagnostics] == [
        "index_watch_batch_failed",
        "index_watch_batch_failed",
    ]
    assert [item["retry_seconds"] for item in diagnostics] == [0.5, 1.0]
    assert "worker-secret" not in result.stderr
    assert "second-secret" not in result.stderr
    assert all("[redacted]" in item["failure_samples"][0]["error"] for item in diagnostics)


def test_index_watch_exception_backoff_resets_after_success_and_idle(
    tmp_path: Path,
    monkeypatch,
):
    from tgarchive.db import index_projector

    outcomes = iter([
        RuntimeError("worker config {'api_hash': 'first-secret'} unavailable"),
        RuntimeError("otp: second-secret unavailable"),
        {"claimed": 1, "processed": 1, "failed": 0, "failures": []},
        RuntimeError("token=third-secret unavailable"),
        {"claimed": 0, "processed": 0, "failed": 0, "failures": []},
        RuntimeError("secret=fourth-secret unavailable"),
    ])
    sleeps = []

    class Projector:
        def __init__(self, database):
            assert database == tmp_path / "spectra.db"

        def process(self, *, batch_size, lease_seconds):
            try:
                outcome = next(outcomes)
            except StopIteration:
                raise KeyboardInterrupt
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(index_projector, "IndexProjector", Projector)
    monkeypatch.setattr(cli_app.time, "sleep", sleep)
    result = CliRunner().invoke(
        cli,
        [
            "--db",
            str(tmp_path / "spectra.db"),
            "--output",
            "json",
            "index",
            "watch",
            "--poll-interval",
            "0.25",
            "--max-backoff",
            "4",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert sleeps == [0.25, 0.5, 0.25, 0.25, 0.25]
    summary = json.loads(result.stdout)
    assert summary["batches"] == 2
    assert summary["claimed"] == 1
    assert summary["processed"] == 1
    assert summary["worker_errors"] == 4
    assert summary["interrupted"] is True
    diagnostics = [json.loads(line) for line in result.stderr.splitlines()]
    assert [item["retry_seconds"] for item in diagnostics] == [0.25, 0.5, 0.25, 0.25]
    assert all(item["event"] == "index_watch_worker_exception" for item in diagnostics)
    assert [item["exception_type"] for item in diagnostics] == [
        "RuntimeError",
        "RuntimeError",
        "RuntimeError",
        "RuntimeError",
    ]
    assert "first-secret" not in result.stderr
    assert "second-secret" not in result.stderr
    assert "third-secret" not in result.stderr
    assert "fourth-secret" not in result.stderr


def test_index_watch_retry_delay_respects_max_backoff(tmp_path: Path, monkeypatch):
    from tgarchive.db import index_projector

    calls = 0
    sleeps = []

    class Projector:
        def __init__(self, database):
            assert database == tmp_path / "spectra.db"

        def process(self, *, batch_size, lease_seconds):
            nonlocal calls
            calls += 1
            if calls <= 2:
                raise RuntimeError("projection unavailable")
            raise KeyboardInterrupt

    monkeypatch.setattr(index_projector, "IndexProjector", Projector)
    monkeypatch.setattr(cli_app.time, "sleep", sleeps.append)
    result = CliRunner().invoke(
        cli,
        [
            "--db",
            str(tmp_path / "spectra.db"),
            "--output",
            "json",
            "index",
            "watch",
            "--poll-interval",
            "2",
            "--max-backoff",
            "1",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert sleeps == [1.0, 1.0]
    diagnostics = [json.loads(line) for line in result.stderr.splitlines()]
    assert [item["retry_seconds"] for item in diagnostics] == [1.0, 1.0]
    assert json.loads(result.stdout)["worker_errors"] == 2


def test_index_verify_drift_exits_partial(tmp_path: Path):
    from tgarchive.db.index_outbox import IndexOutbox
    from tgarchive.db.index_projector import IndexProjector
    from tgarchive.sqlite_runtime import connect_sqlite

    database = tmp_path / "spectra.db"
    IndexOutbox(database).append(
        source_table="messages",
        source_key="42",
        event_type="upsert",
        payload={"message_id": 42, "text": "projection drift"},
        source_revision="v1",
    )
    IndexProjector(database).process()
    with connect_sqlite(database) as connection:
        connection.execute(
            "UPDATE index_projection_records SET content_hash='drift' "
            "WHERE projection_name='qihse.content.v1'"
        )

    result = CliRunner().invoke(
        cli,
        ["--db", str(database), "--output", "json", "index", "verify", "--no-native"],
    )

    assert result.exit_code == cli_app.EXIT_PARTIAL
    assert json.loads(result.output)["details"]["ok"] is False


def test_search_fulltext_uses_outbox_projection(tmp_path: Path):
    from tgarchive.db.index_outbox import IndexOutbox
    from tgarchive.db.index_projector import IndexProjector

    database = tmp_path / "spectra.db"
    IndexOutbox(database).append(
        source_table="channel_messages",
        source_key="10:42",
        event_type="download",
        payload={"channel_id": 10, "message_id": 42, "message": "indexed keyword phrase"},
        source_revision="v1",
    )
    IndexProjector(database).process()

    result = CliRunner().invoke(
        cli,
        ["--db", str(database), "--output", "json", "search", "fulltext", "keyword", "--channel-id", "10"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["payload"]["message_id"] == 42

    graph_result = CliRunner().invoke(
        cli,
        [
            "--db",
            str(database),
            "--output",
            "json",
            "index",
            "graph",
            "--node-type",
            "message",
            "--external-id",
            "10:42",
            "--edge-type",
            "IN_CHANNEL",
            "--direction",
            "outgoing",
        ],
    )
    assert graph_result.exit_code == 0, graph_result.output
    graph_payload = json.loads(graph_result.output)
    assert graph_payload["details"]["records"][0]["to_node"]["node_key"] == "channel:10"


def test_operations_run_executes_local_operation_envelope(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{"session_name": "test-account", "api_hash": "secret-hash"}],
    }))

    result = CliRunner().invoke(
        cli,
        [
            "--config",
            str(config_path),
            "--output",
            "json",
            "operations",
            "run",
            "config.get",
            "--arguments",
            '{"path":"accounts.0.api_hash"}',
        ],
    )

    assert result.exit_code == 0
    assert "secret-hash" not in result.output
    payload = json.loads(result.output)
    assert payload["operation_id"] == "config.get"
    assert payload["status"] == "completed"
    assert payload["result"]["value"] == "[redacted]"


def test_operations_run_reports_validation_errors():
    result = CliRunner().invoke(
        cli,
        ["--output", "json", "operations", "run", "config.get", "--arguments", '{"path":""}'],
    )

    assert result.exit_code == cli_app.EXIT_USAGE
    payload = json.loads(result.output)
    assert payload["operation_id"] == "config.get"
    assert payload["status"] == "failed"
    assert payload["error"]["category"] == "validation"


def test_agent_plan_emits_validated_channel_download_envelope():
    result = CliRunner().invoke(
        cli,
        [
            "--output",
            "json",
            "agent",
            "plan",
            "download all media from -1002407846598 to /fast/ULPs --no-proxy --max-connections 64 --max-retries 7",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "operation_plan"
    assert payload["request"]["operation_id"] == "channel.download"
    assert payload["request"]["dry_run"] is True
    assert payload["request"]["arguments"]["entity"] == "-1002407846598"
    assert payload["request"]["arguments"]["media_only"] is True
    assert payload["request"]["arguments"]["max_connections"] == 64
    assert payload["request"]["arguments"]["max_retries"] == 7


def test_agent_plan_supports_read_only_positional_requests():
    result = CliRunner().invoke(cli, ["--output", "json", "agent", "plan", "show task task-123 --tail 4"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["request"]["operation_id"] == "task.show"
    assert payload["request"]["arguments"] == {"task_id": "task-123", "tail": 4}


def test_agent_plan_rejects_credentials():
    result = CliRunner().invoke(cli, ["--output", "json", "agent", "plan", "login with api_hash abc"])

    assert result.exit_code != 0
    assert "credentials" in result.output
    assert "abc" not in result.output


def test_agent_run_and_audit_link_request_envelope_and_command(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    result = CliRunner().invoke(
        cli,
        [
            "--db",
            str(db_path),
            "--output",
            "json",
            "agent",
            "run",
            "show version",
        ],
    )

    assert result.exit_code == 0, result.output
    # Parse only the JSON part from output (might contain log messages)
    output_lines = result.output.strip().split("\n")
    start_idx = next(i for i, line in enumerate(output_lines) if line.startswith("{"))
    json_str = "\n".join(output_lines[start_idx:])
    run_payload = json.loads(json_str)
    assert run_payload["status"] == "completed"
    assert run_payload["audit_id"].startswith("audit-")

    audit_result = CliRunner().invoke(
        cli,
        ["--db", str(db_path), "--output", "json", "agent", "audit", "show", run_payload["audit_id"]],
    )

    assert audit_result.exit_code == 0, audit_result.output
    audit = json.loads(audit_result.output)
    assert audit["source"] == "agent.run"
    assert audit["operation_id"] == "version"
    assert audit["status"] == "completed"
    assert audit["envelope_json"]["operation_id"] == "version"
    assert audit["planned_command_json"] == audit["actual_argv_json"]
    assert "operations" in audit["actual_argv_json"]
    with sqlite3.connect(db_path.with_suffix(".tasks.sqlite3")) as connection:
        outbox_events = connection.execute(
            "SELECT event_type FROM index_outbox WHERE source_table='operation_audit' ORDER BY sequence_id"
        ).fetchall()
    assert [row[0] for row in outbox_events] == ["running", "completed"]


def test_agent_plan_audit_redacts_sensitive_request_text(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    result = CliRunner().invoke(
        cli,
        ["--db", str(db_path), "--output", "json", "agent", "plan", "login with password super-secret"],
    )

    assert result.exit_code != 0
    audit_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "agent", "audit", "list"])
    assert audit_result.exit_code == 0, audit_result.output
    records = json.loads(audit_result.output)
    assert records[0]["status"] == "failed"
    assert "super-secret" not in records[0]["request_text"]
    assert "[redacted]" in records[0]["request_text"]


def test_agent_plan_covers_discovery_network_search_archive_and_export(tmp_path: Path):
    requests = {
        "discovery.run": "crawl from @seed_channel depth 3 messages 250 parallel --max-workers 4",
        "network.analyze": "analyze network from db metric combined top 25",
        "search.fulltext": 'search for "needle phrase" --limit 20 --offset 5',
        "channel.archive": "archive channel @archive_target --no-media --no-topics",
        "export.table": "export table messages to exports/messages.csv --format csv --limit 100",
    }

    for operation_id, request in requests.items():
        result = CliRunner().invoke(cli, ["--db", str(tmp_path / "spectra.db"), "--output", "json", "agent", "plan", request])
        assert result.exit_code == 0, f"{operation_id}: {result.output}"
        assert json.loads(result.output)["request"]["operation_id"] == operation_id


def test_agent_plan_search_does_not_confuse_channel_word_with_channel_id():
    result = CliRunner().invoke(
        cli,
        ["--output", "json", "agent", "plan", 'search for "needle" in channel --channel-id 456'],
    )

    assert result.exit_code == 0, result.output
    arguments = json.loads(result.output)["request"]["arguments"]
    assert arguments["query"] == "needle"
    assert arguments["channel_id"] == 456


def test_config_show_redacts_account_secrets(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{
            "api_id": 123,
            "api_hash": "secret-hash",
            "session_name": "test-account",
            "password": "secret-password",
        }],
    }))

    result = CliRunner().invoke(cli, ["--config", str(config_path), "--output", "json", "config", "show"])

    assert result.exit_code == 0
    assert "secret-hash" not in result.output
    assert "secret-password" not in result.output
    assert "[redacted]" in result.output


def test_config_get_supports_nested_values_and_redaction(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{
            "api_id": 123,
            "api_hash": "secret-hash",
            "session_name": "test-account",
        }],
    }))

    session_result = CliRunner().invoke(cli, ["--config", str(config_path), "--output", "json", "config", "get", "accounts.0.session_name"])
    secret_result = CliRunner().invoke(cli, ["--config", str(config_path), "--output", "json", "config", "get", "accounts.0.api_hash"])

    assert session_result.exit_code == 0
    assert json.loads(session_result.output)["value"] == "test-account"
    assert secret_result.exit_code == 0
    assert "secret-hash" not in secret_result.output
    assert json.loads(secret_result.output)["value"] == "[redacted]"


def test_config_set_preserves_json_types_and_redacts_secret_output(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{"api_hash": "old-secret", "session_name": "test-account"}],
        "download_media": True,
    }))

    result = CliRunner().invoke(
        cli,
        [
            "--config",
            str(config_path),
            "--output",
            "json",
            "config",
            "set",
            "accounts.0.api_hash",
            '"new-secret"',
        ],
    )

    assert result.exit_code == 0
    assert "old-secret" not in result.output
    assert "new-secret" not in result.output
    payload = json.loads(result.output)
    assert payload["value"] == "[redacted]"
    saved = json.loads(config_path.read_text())
    assert saved["accounts"][0]["api_hash"] == "new-secret"


def test_config_set_raw_string_and_unset_value(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({"forwarding": {"enabled": True}}))

    set_result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "config", "set", "forwarding.mode", "media-only", "--raw", "--output", "json"],
    )
    unset_result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "config", "unset", "forwarding.enabled", "--output", "json"],
    )

    assert set_result.exit_code == 0
    assert unset_result.exit_code == 0
    saved = json.loads(config_path.read_text())
    assert saved["forwarding"]["mode"] == "media-only"
    assert "enabled" not in saved["forwarding"]


def test_config_set_requires_json_without_raw(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({}))

    result = CliRunner().invoke(cli, ["--config", str(config_path), "config", "set", "name", "not-json"])

    assert result.exit_code != 0
    assert "valid JSON" in result.output


def test_config_unset_requires_yes_in_non_interactive_mode(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({"download_media": True}))

    result = CliRunner().invoke(
        cli,
        ["--non-interactive", "--config", str(config_path), "config", "unset", "download_media"],
    )

    assert result.exit_code != 0
    assert "without --yes" in result.output


def test_config_profiles_add_use_remove(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({"download_media": True, "accounts": []}))

    add_result = CliRunner().invoke(
        cli,
        ["--yes", "--config", str(config_path), "--output", "json", "config", "profile", "add", "base"],
    )
    set_result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "config", "set", "download_media", "false", "--output", "json"],
    )
    use_result = CliRunner().invoke(
        cli,
        ["--yes", "--config", str(config_path), "--output", "json", "config", "profile", "use", "base"],
    )
    list_result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--output", "json", "config", "profile", "list"],
    )
    remove_result = CliRunner().invoke(
        cli,
        ["--yes", "--config", str(config_path), "--output", "json", "config", "profile", "remove", "base"],
    )

    assert add_result.exit_code == 0
    assert set_result.exit_code == 0
    assert use_result.exit_code == 0
    assert json.loads(config_path.read_text())["download_media"] is True
    assert json.loads(list_result.output)[0]["active"] is True
    assert remove_result.exit_code == 0
    assert "base" not in json.loads(config_path.read_text()).get("profiles", {})


def test_config_migrate_env_writes_refs_and_config_resolves_them(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "spectra_config.json"
    env_path = tmp_path / ".env.out"
    config_path.write_text(json.dumps({
        "accounts": [{"api_id": 123, "api_hash": "secret-hash", "session_name": "test-account"}],
    }))

    result = CliRunner().invoke(
        cli,
        [
            "--yes",
            "--config",
            str(config_path),
            "--output",
            "json",
            "config",
            "migrate-env",
            "--prefix",
            "SPEC",
            "--env-file",
            str(env_path),
        ],
    )

    assert result.exit_code == 0
    assert "secret-hash" not in result.output
    saved = json.loads(config_path.read_text())
    assert saved["accounts"][0]["api_hash"] == "env:SPEC_ACCOUNTS_0_API_HASH"
    assert env_path.read_text().strip() == "SPEC_ACCOUNTS_0_API_HASH=secret-hash"
    monkeypatch.setenv("SPEC_ACCOUNTS_0_API_HASH", "resolved-secret")
    assert Config(config_path).data["accounts"][0]["api_hash"] == "resolved-secret"


def test_account_list_exposes_only_safe_metadata(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{
            "api_id": 123,
            "api_hash": "secret-hash",
            "session_name": "test-account",
            "phone_number": "+10000000000",
        }],
    }))

    result = CliRunner().invoke(cli, ["--config", str(config_path), "--output", "json", "account", "list"])

    assert result.exit_code == 0
    assert "secret-hash" not in result.output
    assert "test-account" in result.output
    assert "+10000000000" in result.output


def test_account_show_redacts_secret_fields(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{
            "api_id": 123,
            "api_hash": "secret-hash",
            "session_name": "test-account",
            "phone_number": "+10000000000",
            "token": "secret-token",
        }],
    }))

    result = CliRunner().invoke(cli, ["--config", str(config_path), "--output", "json", "account", "show", "test-account"])

    assert result.exit_code == 0
    assert "secret-hash" not in result.output
    assert "secret-token" not in result.output
    payload = json.loads(result.output)
    assert payload["session_name"] == "test-account"
    assert payload["api_hash"] == "[redacted]"


def test_account_add_writes_redacted_config_entry(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    result = CliRunner().invoke(
        cli,
        [
            "--config",
            str(config_path),
            "--output",
            "json",
            "account",
            "add",
            "--phone",
            "+10000000000",
            "--api-id",
            "123",
            "--api-hash",
            "secret-hash",
        ],
    )

    assert result.exit_code == 0
    assert "secret-hash" not in result.output
    payload = json.loads(result.output)
    assert payload["account"]["api_hash"] == "[redacted]"
    saved = json.loads(config_path.read_text())
    assert saved["accounts"][0]["session_name"] == "spectra_10000000000"
    assert saved["accounts"][0]["api_hash"] == "secret-hash"


def test_account_add_rejects_duplicate_without_replace(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{
            "api_id": 123,
            "api_hash": "secret-hash",
            "session_name": "test-account",
            "phone_number": "+10000000000",
        }],
    }))

    result = CliRunner().invoke(
        cli,
        [
            "--config",
            str(config_path),
            "account",
            "add",
            "--phone",
            "+10000000000",
            "--api-id",
            "456",
            "--api-hash",
            "new-secret",
            "--session-name",
            "test-account",
        ],
    )

    assert result.exit_code != 0
    assert "already exists" in result.output


def test_account_login_dry_run_derives_session_without_saving_secret(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"

    result = CliRunner().invoke(
        cli,
        [
            "--dry-run",
            "--config",
            str(config_path),
            "--output",
            "json",
            "account",
            "login",
            "--phone",
            "+10000000000",
            "--api-id",
            "123",
            "--api-hash",
            "secret-hash",
        ],
    )

    assert result.exit_code == 0
    assert "secret-hash" not in result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["session_name"] == "spectra_10000000000"
    assert not config_path.exists()


def test_account_login_uses_configured_account_and_saves_result(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{
            "api_id": 123,
            "api_hash": "secret-hash",
            "session_name": "test-account",
            "phone_number": "+10000000000",
        }],
    }))
    calls = []

    async def fake_login(account, *, code, password, force, non_interactive):
        calls.append((account, code, password, force, non_interactive))
        return {
            "authorized": True,
            "already_authorized": False,
            "session_name": account["session_name"],
            "phone_number": account["phone_number"],
        }

    monkeypatch.setattr(cli_app, "_login_account_async", fake_login)

    result = CliRunner().invoke(
        cli,
        [
            "--non-interactive",
            "--config",
            str(config_path),
            "--output",
            "json",
            "account",
            "login",
            "test-account",
            "--code",
            "12345",
        ],
    )

    assert result.exit_code == 0
    assert "secret-hash" not in result.output
    payload = json.loads(result.output)
    assert payload["authorized"] is True
    assert calls[0][1] == "12345"
    assert calls[0][4] is True
    saved = json.loads(config_path.read_text())
    assert saved["accounts"][0]["session_name"] == "test-account"


def test_account_login_validates_password_env(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{
            "api_id": 123,
            "api_hash": "secret-hash",
            "session_name": "test-account",
            "phone_number": "+10000000000",
        }],
    }))

    result = CliRunner().invoke(
        cli,
        [
            "--config",
            str(config_path),
            "account",
            "login",
            "test-account",
            "--password-env",
            "SPECTRA_TEST_MISSING_PASSWORD",
        ],
    )

    assert result.exit_code != 0
    assert "environment variable is not set" in result.output


def test_account_remove_deletes_config_entry_and_session_when_requested(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{
            "api_id": 123,
            "api_hash": "secret-hash",
            "session_name": "test-account",
            "phone_number": "+10000000000",
        }],
    }))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test-account.session").write_text("session")
    (tmp_path / "test-account.session-journal").write_text("journal")

    result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--output", "json", "account", "remove", "test-account", "--delete-session"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["changed"] is True
    assert len(payload["removed_session_files"]) == 2
    assert json.loads(config_path.read_text())["accounts"] == []
    assert not (tmp_path / "test-account.session").exists()


def test_account_logout_removes_session_but_keeps_config(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{
            "api_id": 123,
            "api_hash": "secret-hash",
            "session_name": "test-account",
            "phone_number": "+10000000000",
        }],
    }))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test-account.session").write_text("session")

    result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--output", "json", "account", "logout", "test-account"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["changed"] is True
    assert payload["authorized_session"] is False
    assert len(json.loads(config_path.read_text())["accounts"]) == 1


def test_account_stats_counts_configured_sessions(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [
            {
                "api_id": 123,
                "api_hash": "secret-hash",
                "session_name": "active-account",
                "phone_number": "+10000000000",
            },
            {
                "api_id": 456,
                "api_hash": "other-secret",
                "session_name": "inactive-account",
                "phone_number": "+10000000001",
                "active": False,
            },
            {"session_name": "broken-account"},
        ],
    }))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "active-account.session").write_text("session")

    result = CliRunner().invoke(cli, ["--config", str(config_path), "--output", "json", "account", "stats"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total"] == 3
    assert payload["active"] == 2
    assert payload["inactive"] == 1
    assert payload["authorized_sessions"] == 1
    assert payload["missing_credentials"] == 1


def test_account_health_reports_missing_fields_and_sessions(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [
            {"api_id": 123, "api_hash": "secret-hash", "session_name": "healthy"},
            {"session_name": "broken"},
        ],
    }))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "healthy.session").write_text("session")

    result = CliRunner().invoke(cli, ["--config", str(config_path), "--output", "json", "account", "health"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["healthy"] is True
    assert payload[1]["healthy"] is False
    assert "api_id" in payload[1]["missing_fields"]


def test_account_remove_requires_yes_in_non_interactive_mode(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    config_path.write_text(json.dumps({
        "accounts": [{"session_name": "test-account"}],
    }))

    result = CliRunner().invoke(
        cli,
        ["--non-interactive", "--config", str(config_path), "account", "remove", "test-account"],
    )

    assert result.exit_code != 0
    assert "without --yes" in result.output


def test_account_reset_usage_requires_yes_in_non_interactive_mode():
    result = CliRunner().invoke(cli, ["--non-interactive", "account", "reset-usage"])

    assert result.exit_code != 0
    assert "without --yes" in result.output


def test_version_supports_csv_output():
    result = CliRunner().invoke(cli, ["--output", "csv", "version"])

    assert result.exit_code == 0
    assert "spectra,python" in result.output


def test_completion_generates_shell_script_without_installing():
    result = CliRunner().invoke(cli, ["completion", "bash"])

    assert result.exit_code == 0
    assert "_SPECTRA_COMPLETE=bash_complete" in result.output
    assert "_spectra_completion" in result.output


def test_completion_install_writes_standard_script(tmp_path: Path):
    target = tmp_path / "spectra-completion.bash"

    result = CliRunner().invoke(
        cli,
        [
            "--yes",
            "--output",
            "json",
            "completion",
            "bash",
            "--install",
            "--path",
            str(target),
        ],
    )
    second_result = CliRunner().invoke(
        cli,
        ["--yes", "completion", "bash", "--install", "--path", str(target)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["installed"] is True
    assert target.exists()
    assert "_SPECTRA_COMPLETE=bash_complete" in target.read_text()
    assert second_result.exit_code != 0
    assert "already exists" in second_result.output


def test_completion_install_requires_yes_in_non_interactive_mode(tmp_path: Path):
    result = CliRunner().invoke(
        cli,
        [
            "--non-interactive",
            "completion",
            "bash",
            "--install",
            "--path",
            str(tmp_path / "spectra-completion.bash"),
        ],
    )

    assert result.exit_code != 0
    assert "without --yes" in result.output


def test_run_emits_structured_json_error_for_machine_output(tmp_path: Path, capsys):
    code = cli_app.run(
        [
            "--output",
            "json",
            "channel",
            "status",
            str(tmp_path / "missing-export"),
        ]
    )

    captured = capsys.readouterr()
    assert code == cli_app.EXIT_NOT_FOUND
    payload = json.loads(captured.out)
    assert payload["error"]["category"] == "not_found"
    assert "not found" in payload["error"]["message"].lower()
    assert captured.err == ""


def test_run_maps_usage_errors_to_reserved_exit_code(capsys):
    code = cli_app.run(["--output", "json", "config", "get"])

    captured = capsys.readouterr()
    assert code == cli_app.EXIT_USAGE
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == cli_app.EXIT_USAGE
    assert payload["error"]["category"] == "usage"


def test_offline_help_topics_are_available_without_runtime_imports():
    result = CliRunner().invoke(cli, ["help", "channel-download"])
    auth_result = CliRunner().invoke(cli, ["help", "auth"])
    discovery_result = CliRunner().invoke(cli, ["help", "discovery"])
    forwarding_result = CliRunner().invoke(cli, ["help", "forwarding"])
    exports_result = CliRunner().invoke(cli, ["help", "exports"])
    recovery_result = CliRunner().invoke(cli, ["help", "recovery"])
    completion_result = CliRunner().invoke(cli, ["help", "completion"])

    assert result.exit_code == 0
    assert "spectra channel download" in result.output
    assert "QIHSE" not in result.output
    assert auth_result.exit_code == 0
    assert "spectra account login" in auth_result.output
    assert "QIHSE" not in auth_result.output
    assert discovery_result.exit_code == 0
    assert "spectra discover run" in discovery_result.output
    assert forwarding_result.exit_code == 0
    assert "spectra forward" in forwarding_result.output
    assert exports_result.exit_code == 0
    assert "media_manifest.jsonl" in exports_result.output
    assert recovery_result.exit_code == 0
    assert "spectra task recover" in recovery_result.output
    assert completion_result.exit_code == 0
    assert "spectra completion bash" in completion_result.output


def test_forward_messages_routes_legacy_options_without_runtime_imports(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_app, "_run_forward_legacy", lambda **values: calls.append(values))

    result = CliRunner().invoke(
        cli,
        [
            "forward",
            "messages",
            "--origin",
            "@source",
            "--destination",
            "@dest",
            "--account",
            "session-name",
            "--copy-mode",
            "--include-text-messages",
            "--source-accounts",
            "session-a",
            "--source-accounts",
            "session-b",
        ],
    )

    assert result.exit_code == 0
    assert calls
    assert calls[0]["origin"] == "@source"
    assert calls[0]["destination"] == "@dest"
    assert calls[0]["copy_into_destination"] is True
    assert calls[0]["include_text_messages"] is True
    assert calls[0]["source_accounts"] == ("session-a", "session-b")


def test_forward_root_supports_legacy_direct_form(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_app, "_run_forward_legacy", lambda **values: calls.append(values))

    result = CliRunner().invoke(cli, ["forward", "--origin", "@source", "--destination", "@dest"])

    assert result.exit_code == 0
    assert calls[0]["origin"] == "@source"
    assert calls[0]["destination"] == "@dest"


def test_forward_dry_run_emits_plan_without_runtime_imports():
    result = CliRunner().invoke(
        cli,
        ["--dry-run", "--output", "json", "forward", "messages", "--origin", "@source", "--destination", "@dest"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["handler"] == "handle_attachment_forwarding"
    assert payload["options"]["origin"] == "@source"


def test_forward_dialogs_recover_and_traverse_route_modes(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(cli_app, "_run_forward_legacy", lambda **values: calls.append(values))

    dialogs_result = CliRunner().invoke(cli, ["forward", "dialogs", "--destination", "@dest"])
    recover_result = CliRunner().invoke(cli, ["forward", "recover", "--destination", "@dest"])
    traverse_result = CliRunner().invoke(
        cli,
        [
            "forward",
            "traverse",
            "--channels-file",
            str(tmp_path / "seeds.txt"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert dialogs_result.exit_code == 0
    assert recover_result.exit_code == 0
    assert traverse_result.exit_code == 0
    assert calls[0]["all_dialogs"] is True
    assert calls[1]["total_mode"] is True
    assert calls[2]["channels_file"] == tmp_path / "seeds.txt"
    assert calls[2]["output_dir"] == tmp_path / "out"


def test_forward_schedule_dry_run_and_status_read_local_db(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE channel_forward_schedule (
                id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                destination TEXT,
                schedule TEXT,
                is_enabled BOOLEAN
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE file_forward_queue (
                id INTEGER PRIMARY KEY,
                schedule_id INTEGER,
                message_id INTEGER,
                file_id TEXT,
                status TEXT,
                destination TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO channel_forward_schedule (id, channel_id, destination, schedule, is_enabled) VALUES (1, 123, '@dest', '0 1 * * *', 1)"
        )
        connection.execute(
            "INSERT INTO file_forward_queue (id, schedule_id, message_id, file_id, status, destination) VALUES (1, 1, 42, 'file', 'pending', '@dest')"
        )

    schedule_result = CliRunner().invoke(
        cli,
        [
            "--dry-run",
            "--output",
            "json",
            "forward",
            "schedule",
            "--channel-id",
            "123",
            "--destination",
            "@dest",
            "--schedule",
            "0 1 * * *",
        ],
    )
    status_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "forward", "status"])

    assert schedule_result.exit_code == 0
    assert json.loads(schedule_result.output)["schedule_command"] == "add-channel-forward"
    assert status_result.exit_code == 0
    payload = json.loads(status_result.output)
    assert payload["channel_forward_schedules"][0]["channel_id"] == 123
    assert payload["file_forward_queue_status"][0]["status"] == "pending"


def test_forward_help_is_available_without_heavy_runtime_logging():
    result = CliRunner().invoke(cli, ["forward", "--help"])

    assert result.exit_code == 0
    assert "Forward messages" in result.output
    assert "QIHSE" not in result.output


def test_scheduler_add_routes_legacy_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_app, "_run_legacy", lambda handler_name, **values: calls.append((handler_name, values)))

    result = CliRunner().invoke(
        cli,
        ["scheduler", "add", "--name", "nightly", "--schedule", "0 1 * * *", "--command", "spectra account stats"],
    )

    assert result.exit_code == 0
    assert calls[0][0] == "handle_schedule"
    assert calls[0][1]["schedule_command"] == "add"
    assert calls[0][1]["name"] == "nightly"


def test_scheduler_remove_requires_yes_in_non_interactive_mode(monkeypatch):
    monkeypatch.setattr(cli_app, "_run_legacy", lambda handler_name, **values: None)

    result = CliRunner().invoke(cli, ["--non-interactive", "scheduler", "remove", "--name", "nightly"])

    assert result.exit_code != 0
    assert "without --yes" in result.output


def test_scheduler_status_and_show_read_state_and_db(tmp_path: Path):
    config_path = tmp_path / "spectra_config.json"
    state_path = tmp_path / "scheduler_state.json"
    db_path = tmp_path / "spectra.db"
    config_path.write_text(json.dumps({"scheduler": {"state_file": str(state_path)}}))
    state_path.write_text(json.dumps({"jobs": [{"name": "nightly", "schedule": "0 1 * * *", "command": "spectra account stats"}]}))
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE channel_forward_schedule (
                id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                destination TEXT,
                schedule TEXT,
                is_enabled BOOLEAN
            )
            """
        )
        connection.execute(
            "INSERT INTO channel_forward_schedule (id, channel_id, destination, schedule, is_enabled) VALUES (1, 123, '@dest', '0 1 * * *', 1)"
        )

    status_result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--db", str(db_path), "--output", "json", "scheduler", "status"],
    )
    show_result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--db", str(db_path), "--output", "json", "scheduler", "show", "nightly"],
    )

    assert status_result.exit_code == 0
    status_payload = json.loads(status_result.output)
    assert status_payload["jobs"][0]["name"] == "nightly"
    assert status_payload["channel_forward_schedules"][0]["channel_id"] == 123
    assert show_result.exit_code == 0
    assert json.loads(show_result.output)["job"]["command"] == "spectra account stats"


def test_files_sort_and_watch_route_legacy_handler(tmp_path: Path, monkeypatch):
    calls = []
    monkeypatch.setattr(cli_app, "_run_legacy", lambda handler_name, **values: calls.append((handler_name, values)))

    sort_result = CliRunner().invoke(
        cli,
        ["files", "sort", "--directory", str(tmp_path), "--output-directory", str(tmp_path / "sorted")],
    )
    watch_result = CliRunner().invoke(
        cli,
        ["files", "watch", "--directory", str(tmp_path), "--output-directory", str(tmp_path / "sorted")],
    )

    assert sort_result.exit_code == 0
    assert watch_result.exit_code == 0
    assert [call[0] for call in calls] == ["handle_sort", "handle_sort"]
    assert calls[0][1]["directory"] == str(tmp_path)


def test_scheduler_and_files_help_are_lazy():
    scheduler_result = CliRunner().invoke(cli, ["scheduler", "--help"])
    files_result = CliRunner().invoke(cli, ["files", "--help"])

    assert scheduler_result.exit_code == 0
    assert "Manage scheduled" in scheduler_result.output
    assert "QIHSE" not in scheduler_result.output
    assert files_result.exit_code == 0
    assert "Sort and watch" in files_result.output
    assert "QIHSE" not in files_result.output


def test_db_stats_tables_and_table_read_local_sqlite(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        connection.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, type TEXT, date TEXT)")
        connection.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
        connection.execute("INSERT INTO messages (id, type, date) VALUES (7, 'text', '2026-07-28T00:00:00+00:00')")

    stats_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "db", "stats"])
    tables_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "db", "tables"])
    table_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "db", "table", "users"])

    assert stats_result.exit_code == 0
    assert json.loads(stats_result.output)["tables"]["users"] == 1
    assert tables_result.exit_code == 0
    assert {"table": "messages", "rows": 1} in json.loads(tables_result.output)
    assert table_result.exit_code == 0
    assert json.loads(table_result.output)[0]["username"] == "alice"


def test_export_table_writes_jsonl_and_supports_dry_run(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    output_path = tmp_path / "users.jsonl"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        connection.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")

    result = CliRunner().invoke(
        cli,
        [
            "--db",
            str(db_path),
            "--output",
            "json",
            "export",
            "table",
            "users",
            "--output-file",
            str(output_path),
            "--format",
            "jsonl",
        ],
    )
    dry_result = CliRunner().invoke(
        cli,
        [
            "--dry-run",
            "--db",
            str(db_path),
            "--output",
            "json",
            "export",
            "table",
            "users",
            "--output-file",
            str(tmp_path / "dry.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["rows"] == 1
    assert json.loads(output_path.read_text())["username"] == "alice"
    assert dry_result.exit_code == 0
    assert not (tmp_path / "dry.json").exists()


def test_osint_target_local_add_list_remove(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, last_updated TEXT)")
        connection.execute("CREATE TABLE osint_targets (user_id INTEGER PRIMARY KEY, username TEXT, notes TEXT, created_at TEXT)")

    add_result = CliRunner().invoke(
        cli,
        [
            "--yes",
            "--db",
            str(db_path),
            "--output",
            "json",
            "osint",
            "target",
            "add",
            "--user",
            "alice",
            "--user-id",
            "123",
            "--notes",
            "watch",
        ],
    )
    list_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "osint", "target", "list"])
    remove_result = CliRunner().invoke(
        cli,
        ["--yes", "--db", str(db_path), "--output", "json", "osint", "target", "remove", "--user", "alice"],
    )

    assert add_result.exit_code == 0
    assert json.loads(add_result.output)["target"]["user_id"] == 123
    assert list_result.exit_code == 0
    assert json.loads(list_result.output)[0]["username"] == "alice"
    assert remove_result.exit_code == 0
    assert json.loads(remove_result.output)["removed"] == 1


def test_discover_status_results_and_network_export_read_local_db(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    output_path = tmp_path / "targets.jsonl"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE discovered_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_link TEXT UNIQUE,
                group_type TEXT,
                date_discovered TEXT,
                source TEXT,
                priority REAL DEFAULT 0.0,
                status TEXT DEFAULT 'new',
                last_checked TEXT,
                member_count INTEGER DEFAULT 0,
                title TEXT,
                description TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE discovery_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_entity TEXT,
                date_crawled TEXT,
                groups_found INTEGER,
                depth INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE group_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_group TEXT,
                target_group TEXT,
                relationship_type TEXT,
                weight REAL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO discovered_groups
            (group_link, group_type, date_discovered, source, priority, status, title)
            VALUES ('@high', 'username', '2026-07-29T00:00:00+00:00', 'seed', 9.5, 'new', 'High')
            """
        )
        connection.execute(
            """
            INSERT INTO discovered_groups
            (group_link, group_type, date_discovered, source, priority, status, title)
            VALUES ('@low', 'username', '2026-07-28T00:00:00+00:00', 'seed', 1.0, 'archived', 'Low')
            """
        )
        connection.execute("INSERT INTO discovery_sources (source_entity, date_crawled, groups_found, depth) VALUES ('@seed', 'now', 2, 1)")
        connection.execute("INSERT INTO group_relationships (source_group, target_group, relationship_type, weight) VALUES ('@seed', '@high', 'mention', 1.0)")

    status_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "discover", "status"])
    results_result = CliRunner().invoke(
        cli,
        ["--db", str(db_path), "--output", "json", "discover", "results", "--min-priority", "5"],
    )
    export_result = CliRunner().invoke(
        cli,
        [
            "--db",
            str(db_path),
            "--output",
            "json",
            "network",
            "export",
            "--output-file",
            str(output_path),
            "--format",
            "jsonl",
            "--top",
            "1",
        ],
    )

    assert status_result.exit_code == 0
    status_payload = json.loads(status_result.output)
    assert status_payload["groups"] == 2
    assert status_payload["sources"] == 1
    assert status_payload["relationships"] == 1
    assert results_result.exit_code == 0
    assert json.loads(results_result.output)[0]["group_link"] == "@high"
    assert export_result.exit_code == 0
    assert json.loads(export_result.output)["rows"] == 1
    assert json.loads(output_path.read_text())["group_link"] == "@high"


def test_discover_run_and_network_analyze_route_legacy_handlers(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(cli_app, "_run_legacy", lambda handler_name, **values: calls.append((handler_name, values)))

    discover_result = CliRunner().invoke(
        cli,
        ["discover", "run", "--seed", "@seed", "--depth", "2", "--messages", "50", "--export", str(tmp_path / "found.txt")],
    )
    network_result = CliRunner().invoke(
        cli,
        ["network", "analyze", "--from-db", "--top", "10", "--export", str(tmp_path / "targets.json")],
    )

    assert discover_result.exit_code == 0
    assert network_result.exit_code == 0
    assert calls[0][0] == "handle_discover"
    assert calls[0][1]["seed"] == "@seed"
    assert calls[0][1]["depth"] == 2
    assert calls[1][0] == "handle_network"
    assert calls[1][1]["from_db"] is True
    assert calls[1][1]["top"] == 10


def test_osint_scan_routes_legacy_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_app, "_run_legacy", lambda handler_name, **values: calls.append((handler_name, values)))

    result = CliRunner().invoke(cli, ["osint", "scan", "--channel", "@source", "--user", "alice"])

    assert result.exit_code == 0
    assert calls[0][0] == "handle_osint"
    assert calls[0][1]["osint_command"] == "scan"


def test_migration_status_reads_local_progress(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE migration_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                destination TEXT,
                last_message_id INTEGER,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO migration_progress (source, destination, last_message_id, status, created_at, updated_at) VALUES ('a', 'b', 42, 'running', 'c', 'u')"
        )

    result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "migration", "status"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["source"] == "a"
    assert payload[0]["last_message_id"] == 42


def test_mirror_run_and_root_route_legacy_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_app, "_run_legacy", lambda handler_name, **values: calls.append((handler_name, values)))

    run_result = CliRunner().invoke(
        cli,
        [
            "mirror",
            "run",
            "--source",
            "@source",
            "--destination",
            "@dest",
            "--source-account",
            "src",
            "--destination-account",
            "dst",
        ],
    )
    root_result = CliRunner().invoke(
        cli,
        [
            "mirror",
            "--source",
            "@source",
            "--destination",
            "@dest",
            "--source-account",
            "src",
            "--destination-account",
            "dst",
        ],
    )

    assert run_result.exit_code == 0
    assert root_result.exit_code == 0
    assert [call[0] for call in calls] == ["handle_mirror", "handle_mirror"]
    assert calls[0][1]["source_account"] == "src"


def test_db_export_osint_help_are_lazy():
    for args in (["db", "--help"], ["export", "--help"], ["osint", "--help"]):
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0
        assert "QIHSE" not in result.output



def test_channel_status_reads_export_files_without_secrets(tmp_path: Path):
    export_dir = tmp_path / "Channel_123"
    media_dir = export_dir / "media"
    media_dir.mkdir(parents=True)
    (media_dir / "1_payload.bin").write_bytes(b"data")
    (export_dir / "state.json").write_text(json.dumps({
        "last_message_id": 7,
        "messages_written_this_run": 2,
        "media_downloaded_this_run": 1,
        "media_skipped_this_run": 1,
        "media_failed_this_run": 0,
        "failed_media_ids": [],
        "updated_at": "2026-07-28T21:00:00+00:00",
        "complete": False,
    }))
    (export_dir / "manifest.json").write_text(json.dumps({
        "entity": "@target",
        "entity_id": 123,
        "title": "Target",
        "api_hash": "secret-hash",
    }))
    (export_dir / "media_manifest.jsonl").write_text(json.dumps({"message_id": 1}) + "\n")
    (export_dir / "download.log").write_text("line one\nline two\n")

    result = CliRunner().invoke(cli, ["--output", "json", "channel", "status", str(export_dir), "--tail", "1"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["title"] == "Target"
    assert payload["last_message_id"] == 7
    assert payload["media_files"] == 1
    assert payload["media_bytes"] == 4
    assert payload["manifest_records"] == 1
    assert payload["log_tail"] == ["line two"]
    assert "secret-hash" not in result.output


def test_channel_status_prefers_persisted_active_log(tmp_path: Path):
    export_dir = tmp_path / "Channel_123"
    export_dir.mkdir()
    active_log = tmp_path / "detached.log"
    active_log.write_text("current progress\n")
    stale_log = export_dir / "download.log"
    stale_log.write_text("stale progress\n")
    os.utime(stale_log, (1, 1))
    (export_dir / "state.json").write_text(json.dumps({
        "log_path": str(active_log),
        "complete": False,
    }))
    (export_dir / "manifest.json").write_text(json.dumps({"entity": "@target"}))

    result = CliRunner().invoke(cli, ["--output", "json", "channel", "status", str(export_dir), "--tail", "1"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["log_path"] == str(active_log)
    assert payload["log_tail"] == ["current progress"]


def test_channel_catalog_commands_read_local_access_tables(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE account_channel_access (
                account_phone_number TEXT,
                channel_id INTEGER,
                channel_name TEXT,
                access_hash INTEGER,
                last_seen TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE channel_file_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                file_id INTEGER,
                message_id INTEGER,
                topic_id INTEGER,
                created_at TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO account_channel_access VALUES ('+100', 123, 'Target', 999, '2026-07-28T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO account_channel_access VALUES ('+101', 123, 'Target', NULL, '2026-07-28T01:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO channel_file_inventory (channel_id, file_id, message_id, topic_id, created_at) VALUES (123, 7, 70, 5, 'now')"
        )

    list_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "channel", "list"])
    show_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "channel", "show", "123"])
    stats_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "channel", "stats"])
    inspect_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "channel", "inspect", "123"])

    assert list_result.exit_code == 0
    assert json.loads(list_result.output)[0]["channel_id"] == 123
    assert show_result.exit_code == 0
    show_payload = json.loads(show_result.output)
    assert show_payload["channel_name"] == "Target"
    assert show_payload["inventory"]["files"] == 1
    assert stats_result.exit_code == 0
    assert json.loads(stats_result.output)["channels"] == 1
    assert inspect_result.exit_code == 0
    assert json.loads(inspect_result.output)["channel_id"] == 123


def test_channel_catalog_add_and_remove_local_entries(tmp_path: Path):
    db_path = tmp_path / "spectra.db"

    add_result = CliRunner().invoke(
        cli,
        [
            "--yes",
            "--db",
            str(db_path),
            "--output",
            "json",
            "channel",
            "add",
            "123",
            "--account",
            "+100",
            "--name",
            "Target",
            "--access-hash",
            "999",
            "--last-seen",
            "2026-07-28T00:00:00+00:00",
        ],
    )
    show_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "channel", "show", "123"])
    remove_result = CliRunner().invoke(
        cli,
        ["--yes", "--db", str(db_path), "--output", "json", "channel", "remove", "123", "--account", "+100"],
    )

    assert add_result.exit_code == 0
    assert json.loads(add_result.output)["changed"] is True
    assert show_result.exit_code == 0
    assert json.loads(show_result.output)["channel_name"] == "Target"
    assert remove_result.exit_code == 0
    assert json.loads(remove_result.output)["removed"] == 1


def test_channel_catalog_remove_requires_yes_in_non_interactive_mode(tmp_path: Path):
    result = CliRunner().invoke(
        cli,
        ["--non-interactive", "--db", str(tmp_path / "spectra.db"), "channel", "remove", "123"],
    )

    assert result.exit_code != 0
    assert "without --yes" in result.output


def test_channel_archive_and_members_route_legacy_handlers(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(cli_app, "_run_legacy", lambda handler_name, **values: calls.append((handler_name, values)))

    archive_result = CliRunner().invoke(cli, ["channel", "archive", "@target", "--auto", "--no-media"])
    members_result = CliRunner().invoke(
        cli,
        [
            "channel",
            "members",
            "123",
            "--output-file",
            str(tmp_path / "members.json"),
            "--format",
            "json",
            "--rotate-ip",
        ],
    )

    assert archive_result.exit_code == 0
    assert members_result.exit_code == 0
    assert calls[0][0] == "handle_archive"
    assert calls[0][1]["entity"] == "@target"
    assert calls[0][1]["no_media"] is True
    assert calls[1][0] == "handle_download_users"
    assert calls[1][1]["server_id"] == 123
    assert calls[1][1]["output_format"] == "json"


def test_channels_update_access_alias_routes_legacy_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_app, "_run_legacy", lambda handler_name, **values: calls.append((handler_name, values)))

    result = CliRunner().invoke(cli, ["channels", "update-access"])

    assert result.exit_code == 0
    assert calls == [("handle_update_channel_access", {})]


def test_channel_catalog_help_is_lazy():
    result = CliRunner().invoke(cli, ["channel", "--help"])
    alias_result = CliRunner().invoke(cli, ["channels", "--help"])

    assert result.exit_code == 0
    assert "Inspect and download" in result.output
    assert "QIHSE" not in result.output
    assert alias_result.exit_code == 0
    assert "Compatibility alias" in alias_result.output
    assert "QIHSE" not in alias_result.output


def test_channel_download_detach_dry_run_reports_command(tmp_path: Path):
    result = CliRunner().invoke(
        cli,
        [
            "--detach",
            "--dry-run",
            "--output",
            "json",
            "channel",
            "download",
            "@target",
            "--output-dir",
            str(tmp_path),
            "--media-only",
            "--no-proxy",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["detached"] is True
    assert payload["dry_run"] is True
    assert "argv" in payload
    assert "--media-only" in payload["argv"]
    assert payload["argv"][payload["argv"].index("--max-connections") + 1] == "32"
    assert payload["argv"][payload["argv"].index("--max-retries") + 1] == "5"
    assert payload["argv"][payload["argv"].index("--retry-delay") + 1] == "3.0"
    assert payload["argv"][payload["argv"].index("--progress-interval") + 1] == "15.0"
    assert payload["argv"][payload["argv"].index("--stall-timeout") + 1] == "75.0"
    assert payload["argv"][-2:] == ["--", "@target"]
    assert payload["log_path"].startswith(str(tmp_path))


def test_channel_download_detach_dry_run_separates_negative_entity(tmp_path: Path):
    result = CliRunner().invoke(
        cli,
        [
            "--detach",
            "--dry-run",
            "--output",
            "json",
            "channel",
            "download",
            "--output-dir",
            str(tmp_path),
            "--min-id",
            "100",
            "--max-id",
            "200",
            "--",
            "-1002407846598",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["argv"][payload["argv"].index("--min-id") + 1] == "100"
    assert payload["argv"][payload["argv"].index("--max-id") + 1] == "200"
    assert payload["argv"][payload["argv"].index("--max-connections") + 1] == "32"
    assert payload["argv"][-2:] == ["--", "-1002407846598"]


def test_channel_download_forwards_selected_database_to_index_outbox(tmp_path: Path, monkeypatch):
    import tgarchive.__main__ as legacy

    captured = {}

    async def fake_download(args):
        captured["db"] = args.db
        captured["min_id"] = args.min_id
        captured["max_id"] = args.max_id
        return 0

    monkeypatch.setattr(legacy, "handle_download_channel", fake_download)
    database = tmp_path / "indexed.db"

    result = CliRunner().invoke(cli, [
        "--db", str(database),
        "channel", "download", "@target",
        "--min-id", "10",
        "--max-id", "20",
    ])

    assert result.exit_code == 0
    assert captured == {"db": str(database), "min_id": 10, "max_id": 20}


def test_index_benchmark_dry_run_is_typed_and_side_effect_free(tmp_path: Path):
    database = tmp_path / "benchmark.db"

    result = CliRunner().invoke(cli, [
        "--dry-run",
        "--output", "json",
        "index", "benchmark",
        "--database", str(database),
        "--events", "100",
        "--writers", "4",
        "--lookups", "2",
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["details"]["dry_run"] is True
    assert payload["details"]["events"] == 100
    assert not database.exists()


def test_channel_download_detach_starts_background_process(tmp_path: Path, monkeypatch):
    calls = []

    class FakeProcess:
        pid = 4242

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(cli_app.subprocess, "Popen", fake_popen)

    result = CliRunner().invoke(
        cli,
        [
            "--detach",
            "--output",
            "json",
            "--db",
            str(tmp_path / "spectra.db"),
            "channel",
            "download",
            "@target",
            "--output-dir",
            str(tmp_path),
            "--account",
            "session-name",
            "--media-only",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["pid"] == 4242
    assert payload["task_id"].startswith("task-")
    registry = Path(payload["task_registry"])
    assert registry.exists()
    with sqlite3.connect(registry) as connection:
        rows = connection.execute("SELECT payload_json FROM task_events").fetchall()
    records = [json.loads(row[0]) for row in rows]
    assert records[0]["pid"] == 4242
    assert records[0]["argv"][records[0]["argv"].index("--account") + 1] == "[redacted]"
    assert calls
    command, kwargs = calls[0]
    assert command[:3] == [sys.executable, "-m", "tgarchive"]
    assert "--account" in command
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] == cli_app.subprocess.DEVNULL


def test_task_list_and_show_read_detached_registry(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "spectra.db"
    registry_path = db_path.with_suffix(".tasks.jsonl")
    registry_path.write_text(json.dumps({
        "id": "task-1",
        "kind": "channel.download",
        "status": "running",
        "pid": 12345,
        "argv": ["python", "-m", "tgarchive", "--account", "[redacted]"],
    }) + "\n")
    monkeypatch.setattr(cli_app, "_pid_running", lambda pid: pid == 12345)

    list_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "task", "list"])
    show_result = CliRunner().invoke(cli, ["--db", str(db_path), "task", "show", "task-1", "--output", "json"])

    assert list_result.exit_code == 0
    list_payload = json.loads(list_result.output)
    assert list_payload[0]["id"] == "task-1"
    assert list_payload[0]["running"] is True
    assert show_result.exit_code == 0
    show_payload = json.loads(show_result.output)
    assert show_payload["argv"][-1] == "[redacted]"


def test_task_watch_once_includes_log_tail(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "spectra.db"
    log_path = tmp_path / "download.log"
    log_path.write_text("first\nsecond\n")
    registry_path = db_path.with_suffix(".tasks.jsonl")
    registry_path.write_text(json.dumps({
        "id": "task-watch",
        "kind": "channel.download",
        "status": "running",
        "pid": 12345,
        "log_path": str(log_path),
        "argv": ["python", "-m", "tgarchive", "--account", "[redacted]"],
    }) + "\n")
    monkeypatch.setattr(cli_app, "_pid_running", lambda pid: pid == 12345)

    result = CliRunner().invoke(
        cli,
        ["--db", str(db_path), "task", "watch", "task-watch", "--once", "--tail", "1", "--output", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["running"] is True
    assert payload["log_tail"] == ["second"]


def test_task_watch_default_interval_is_fast():
    assert cli_app.DEFAULT_TASK_WATCH_INTERVAL == 1.0


def test_task_cancel_sends_interrupt_and_records_event(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "spectra.db"
    legacy_registry_path = db_path.with_suffix(".tasks.jsonl")
    legacy_registry_path.write_text(json.dumps({
        "id": "task-cancel",
        "kind": "channel.download",
        "status": "running",
        "pid": 12345,
        "argv": ["python", "-m", "tgarchive", "--account", "[redacted]"],
    }) + "\n")
    states = iter([True, False])
    interrupted = []

    monkeypatch.setattr(cli_app, "_pid_running", lambda pid: next(states, False))
    monkeypatch.setattr(cli_app, "_interrupt_process_group", lambda pid: interrupted.append(pid))

    result = CliRunner().invoke(
        cli,
        ["--yes", "--db", str(db_path), "--output", "json", "task", "cancel", "task-cancel", "--wait", "0"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["was_running"] is True
    assert payload["running"] is False
    assert payload["status"] == "cancelled"
    assert interrupted == [12345]
    with sqlite3.connect(db_path.with_suffix(".tasks.sqlite3")) as connection:
        rows = connection.execute("SELECT payload_json FROM task_events ORDER BY event_id").fetchall()
    records = [json.loads(row[0]) for row in rows]
    assert records[-1]["status"] == "cancelled"


def test_task_cancel_requires_yes_in_non_interactive_mode(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    db_path.with_suffix(".tasks.jsonl").write_text(json.dumps({
        "id": "task-cancel",
        "kind": "channel.download",
        "status": "running",
        "pid": 12345,
    }) + "\n")

    result = CliRunner().invoke(
        cli,
        ["--non-interactive", "--db", str(db_path), "task", "cancel", "task-cancel"],
    )

    assert result.exit_code != 0
    assert "without --yes" in result.output


def test_task_events_lists_all_records_for_task(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    legacy_registry_path = db_path.with_suffix(".tasks.jsonl")
    legacy_registry_path.write_text(
        json.dumps({"id": "task-events", "status": "running", "pid": 12345}) + "\n"
        + json.dumps({"id": "task-events", "status": "cancelled", "pid": 12345}) + "\n"
    )

    result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "task", "events", "task-events"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [event["status"] for event in payload] == ["running", "cancelled"]


def test_task_recover_records_exited_running_task(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "spectra.db"
    db_path.with_suffix(".tasks.jsonl").write_text(json.dumps({
        "id": "task-recover",
        "kind": "channel.download",
        "status": "running",
        "pid": 12345,
    }) + "\n")
    monkeypatch.setattr(cli_app, "_pid_running", lambda pid: False)

    result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "task", "recover", "task-recover"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["count"] == 1
    assert payload["recovered"][0]["status"] == "exited"
    with sqlite3.connect(db_path.with_suffix(".tasks.sqlite3")) as connection:
        rows = connection.execute("SELECT payload_json FROM task_events ORDER BY event_id").fetchall()
    records = [json.loads(row[0]) for row in rows]
    assert records[-1]["status"] == "exited"


def test_task_show_marks_completed_export_as_completed(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "spectra.db"
    export_dir = tmp_path / "Export_123"
    (export_dir / "media").mkdir(parents=True)
    (export_dir / "state.json").write_text(json.dumps({"complete": True, "last_message_id": 99}))
    db_path.with_suffix(".tasks.jsonl").write_text(json.dumps({
        "id": "task-complete",
        "kind": "channel.download",
        "status": "running",
        "pid": 12345,
        "output_dir": str(export_dir),
    }) + "\n")
    monkeypatch.setattr(cli_app, "_pid_running", lambda pid: True)

    result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "task", "show", "task-complete"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "completed"
    assert payload["channel_status"]["complete"] is True


def test_search_fulltext_and_stats_read_message_text(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                user_id INTEGER,
                date TEXT,
                content TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO messages (id, channel_id, user_id, date, content) VALUES (1, 123, 7, '2026-07-28T10:00:00+00:00', 'alpha beta')"
        )
        connection.execute(
            "INSERT INTO messages (id, channel_id, user_id, date, content) VALUES (2, 456, 8, '2026-07-28T11:00:00+00:00', 'gamma')"
        )

    search_result = CliRunner().invoke(
        cli,
        ["--db", str(db_path), "--output", "json", "search", "fulltext", "beta", "--channel-id", "123"],
    )
    stats_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "search", "stats"])

    assert search_result.exit_code == 0
    assert json.loads(search_result.output)[0]["id"] == 1
    assert stats_result.exit_code == 0
    payload = json.loads(stats_result.output)
    assert payload["messages"] == 2
    assert payload["searchable_columns"] == ["content"]


def test_analyze_indicators_detects_local_message_patterns(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                date TEXT,
                content TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO messages (id, date, content) VALUES (1, '2026-07-28T10:00:00+00:00', 'BTC 1BoatSLRHtKNngkdXEeobR76b53LETtpyT')"
        )

    result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "analyze", "indicators"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["message_id"] == 1
    assert payload[0]["indicators"][0]["value"] == "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"


def test_ml_patterns_and_model_list_are_local(tmp_path: Path):
    db_path = tmp_path / "spectra.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE ml_patterns (id INTEGER PRIMARY KEY, label TEXT)")
        connection.execute("INSERT INTO ml_patterns (id, label) VALUES (1, 'burst')")

    patterns_result = CliRunner().invoke(cli, ["--db", str(db_path), "--output", "json", "ml", "patterns"])
    models_result = CliRunner().invoke(cli, ["--output", "json", "ml", "model", "list"])

    assert patterns_result.exit_code == 0
    assert json.loads(patterns_result.output)[0]["label"] == "burst"
    assert models_result.exit_code == 0
    assert "pattern_detector_available" in json.loads(models_result.output)


def test_crypto_key_generation_writes_owner_only_file(tmp_path: Path, monkeypatch):
    async def fake_crypto_call(method, *args):
        assert method == "generate_kem_keypair"
        return {
            "key_id": args[0],
            "algorithm": "ML-KEM-1024",
            "public_key": "public",
            "secret_key": "secret",
        }

    output_file = tmp_path / "kem.json"
    monkeypatch.setattr(cli_app, "_crypto_call", fake_crypto_call)

    result = CliRunner().invoke(
        cli,
        ["--output", "json", "crypto", "kem", "--key-id", "test-key", "--output-file", str(output_file)],
    )
    overwrite_result = CliRunner().invoke(
        cli,
        ["crypto", "kem", "--key-id", "test-key", "--output-file", str(output_file)],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["algorithm"] == "ML-KEM-1024"
    assert json.loads(output_file.read_text())["secret_key"] == "secret"
    assert oct(output_file.stat().st_mode & 0o777) == "0o600"
    assert overwrite_result.exit_code != 0
    assert "already exists" in overwrite_result.output


def test_admin_and_server_health_report_local_state(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "spectra_config.json"
    db_path = tmp_path / "spectra.db"
    config_path.write_text(json.dumps({"accounts": []}))
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO users (id) VALUES (1)")
    monkeypatch.setattr(cli_app, "_pid_running", lambda pid: False)

    admin_result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--db", str(db_path), "--output", "json", "admin", "health"],
    )
    server_result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--db", str(db_path), "--output", "json", "server", "health"],
    )

    assert admin_result.exit_code == 0
    assert json.loads(admin_result.output)["database"]["exists"] is True
    assert server_result.exit_code == 0
    server_payload = json.loads(server_result.output)
    assert server_payload["jwt_secret_configured"] is False
    assert server_payload["auth_required"] is False
    assert server_payload["security_posture"] == "workstation_trust"


def test_admin_operator_hash_and_add_enforce_strong_onboarding(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "spectra_config.json"
    monkeypatch.setenv("SPECTRA_TEST_OPERATOR_PASSWORD", "StrongPassw0rd!")
    monkeypatch.setenv("SPECTRA_TEST_WEAK_OPERATOR_PASSWORD", "weak")

    weak_result = CliRunner().invoke(
        cli,
        [
            "--non-interactive",
            "--config",
            str(config_path),
            "admin",
            "operator",
            "hash-password",
            "--username",
            "alice",
            "--password-env",
            "SPECTRA_TEST_WEAK_OPERATOR_PASSWORD",
        ],
    )
    hash_result = CliRunner().invoke(
        cli,
        [
            "--non-interactive",
            "--config",
            str(config_path),
            "--output",
            "json",
            "admin",
            "operator",
            "hash-password",
            "--username",
            "alice",
            "--password-env",
            "SPECTRA_TEST_OPERATOR_PASSWORD",
            "--permission",
            "manage_users",
        ],
    )
    add_result = CliRunner().invoke(
        cli,
        [
            "--non-interactive",
            "--yes",
            "--config",
            str(config_path),
            "--output",
            "json",
            "admin",
            "operator",
            "add",
            "--username",
            "alice",
            "--password-env",
            "SPECTRA_TEST_OPERATOR_PASSWORD",
            "--permission",
            "manage_users",
        ],
    )

    assert weak_result.exit_code != 0
    assert "Operator password must include" in weak_result.output
    assert hash_result.exit_code == 0
    hash_payload = json.loads(hash_result.output)
    assert hash_payload["username"] == "alice"
    assert hash_payload["password_hash"].startswith("pbkdf2-sha384$")
    assert add_result.exit_code == 0
    saved = json.loads(config_path.read_text())
    assert saved["operators"][0]["username"] == "alice"
    assert saved["operators"][0]["permissions"]["manage_users"] is True


def test_api_graphql_unavailable_uses_reserved_exit_code(capsys, monkeypatch):
    monkeypatch.setattr(cli_app, "_module_available", lambda name: False if name == "tgarchive.api.graphql" else True)

    code = cli_app.run(["--output", "json", "api", "graphql", "--schema"])

    captured = capsys.readouterr()
    assert code == cli_app.EXIT_UNAVAILABLE
    assert json.loads(captured.out)["available"] is False
