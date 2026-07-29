"""Modern SPECTRA CLI foundation.

This module intentionally imports heavyweight Telegram and analytics code only
inside the command that needs it. Help, version, and configuration inspection
remain usable in a minimal installation.
"""

from __future__ import annotations

import asyncio
import base64
import csv
import getpass
import importlib.util
import json
import os
import platform
import re
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import click

from ..db.index_outbox import IndexOutbox
from ..sqlite_runtime import connect_sqlite


DEFAULT_TASK_WATCH_INTERVAL = 1.0
DEFAULT_TASK_CANCEL_WAIT = 10.0
INDEX_WATCH_FAILURE_SAMPLE_LIMIT = 5
DEFAULT_TABLE_LIMIT = 50
MAX_TABLE_LIMIT = 1000
CORE_DB_TABLES = (
    "users",
    "media",
    "messages",
    "checkpoints",
    "account_channel_access",
    "osint_targets",
    "osint_interactions",
    "channel_forward_schedule",
    "file_forward_schedule",
)

SENSITIVE_KEYS = {
    "api_hash", "password", "token", "secret", "jwt_secret", "session_secret",
    "bootstrap_secret", "private_key", "refresh_token",
}
ENV_MIGRATION_KEYS = ("api_hash", "password", "token", "secret", "private_key", "refresh_token")
SUPPORTED_COMPLETION_SHELLS = ("bash", "zsh", "fish")
EXIT_USAGE = 2
EXIT_CONFIG_AUTH = 3
EXIT_NOT_FOUND = 4
EXIT_CONFLICT = 5
EXIT_NETWORK = 6
EXIT_PARTIAL = 7
EXIT_UNAVAILABLE = 8
EXIT_INTERRUPTED = 130
_OPERATION_REGISTRY_CACHE: Any | None = None


def _detect_output(argv: list[str]) -> str:
    for index, token in enumerate(argv):
        if token == "--output" and index + 1 < len(argv):
            return argv[index + 1].lower()
        if token.startswith("--output="):
            return token.split("=", 1)[1].lower()
    return "table"


def _error_code_and_category(message: str, default_code: int) -> tuple[int, str]:
    lowered = message.lower()
    if default_code == EXIT_USAGE:
        return EXIT_USAGE, "usage"
    if "not found" in lowered or "does not exist" in lowered:
        return EXIT_NOT_FOUND, "not_found"
    if "already exists" in lowered or "refusing to" in lowered or "overwrite" in lowered:
        return EXIT_CONFLICT, "conflict"
    if "config" in lowered or "account" in lowered or "auth" in lowered or "login" in lowered or "credential" in lowered:
        return EXIT_CONFIG_AUTH, "config_auth"
    if "telethon" in lowered or "telegram" in lowered or "network" in lowered or "flood" in lowered or "timeout" in lowered:
        return EXIT_NETWORK, "network"
    if "unavailable" in lowered or "unsupported" in lowered or "required" in lowered:
        return EXIT_UNAVAILABLE, "unavailable"
    return default_code, "error"


def _emit_error(message: str, *, code: int, category: str, output: str) -> None:
    if output == "json":
        click.echo(json.dumps({"error": {"code": code, "category": category, "message": message}}))
        return
    click.echo(f"spectra: {message}", err=True)


def run(argv: list[str] | None = None, *, prog_name: str = "spectra") -> int:
    """Run the Click CLI with reserved exit codes and machine-readable errors."""
    args = list(sys.argv[1:] if argv is None else argv)
    output = _detect_output(args)
    try:
        result = cli.main(args=args, prog_name=prog_name, standalone_mode=False)
        if isinstance(result, int):
            return result
        return 0
    except click.exceptions.Exit as exc:
        return int(exc.exit_code or 0)
    except click.UsageError as exc:
        _emit_error(exc.format_message(), code=EXIT_USAGE, category="usage", output=output)
        return EXIT_USAGE
    except click.ClickException as exc:
        code, category = _error_code_and_category(exc.format_message(), exc.exit_code or 1)
        _emit_error(exc.format_message(), code=code, category=category, output=output)
        return code
    except KeyboardInterrupt:
        _emit_error("Interrupted", code=EXIT_INTERRUPTED, category="interrupted", output=output)
        return EXIT_INTERRUPTED


@dataclass(frozen=True)
class CliContext:
    config_path: Path
    db_path: Path
    output: str
    quiet: bool
    verbose: bool
    no_color: bool
    non_interactive: bool
    yes: bool
    dry_run: bool
    timeout: float | None
    detach: bool


def _redact(value: Any, key: str | None = None) -> Any:
    if key and any(part in key.lower() for part in SENSITIVE_KEYS):
        return "[redacted]" if value else value
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _emit(value: Any, output: str) -> None:
    if output == "json":
        click.echo(json.dumps(value, indent=2, default=str))
        return
    if output == "jsonl":
        if isinstance(value, list):
            for item in value:
                click.echo(json.dumps(item, default=str))
        else:
            click.echo(json.dumps(value, default=str))
        return
    if output == "csv":
        click.echo(_to_csv(value))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            click.echo(f"{key}: {item}")
        return
    if isinstance(value, list):
        for item in value:
            click.echo(str(item))
        return
    click.echo(str(value))


def _to_csv(value: Any) -> str:
    rows = value if isinstance(value, list) else [value]
    normalized_rows = [row if isinstance(row, dict) else {"value": row} for row in rows]
    fieldnames: list[str] = []
    for row in normalized_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in normalized_rows:
        writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
    return buffer.getvalue().rstrip()


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return value


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Unable to read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise click.ClickException(f"{path} does not contain a JSON object")
    return payload


def _read_config_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_json_file(path)


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_name(f"{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_path, path)
    except OSError as exc:
        raise click.ClickException(f"Unable to write {path}: {exc}") from exc
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


def _connect_existing_sqlite(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise click.ClickException(f"Database not found: {path}")
    try:
        connection = connect_sqlite(path, read_only=True)
        connection.row_factory = sqlite3.Row
        return connection
    except sqlite3.Error as exc:
        raise click.ClickException(f"Unable to open database {path}: {exc}") from exc


def _quote_identifier(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum() or not identifier:
        raise click.ClickException(f"Invalid SQLite identifier: {identifier}")
    return '"' + identifier.replace('"', '""') + '"'


def _table_names(connection: sqlite3.Connection) -> list[str]:
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    except sqlite3.Error as exc:
        raise click.ClickException(f"Unable to list database tables: {exc}") from exc
    return [str(row["name"]) for row in rows]


def _require_table(connection: sqlite3.Connection, table: str) -> None:
    if table not in _table_names(connection):
        raise click.ClickException(f"Table not found: {table}")


def _count_table_rows(connection: sqlite3.Connection, table: str) -> int:
    _require_table(connection, table)
    try:
        row = connection.execute(f"SELECT COUNT(*) AS count FROM {_quote_identifier(table)}").fetchone()
    except sqlite3.Error as exc:
        raise click.ClickException(f"Unable to count table {table}: {exc}") from exc
    return int(row["count"]) if row else 0


def _fetch_table_rows(connection: sqlite3.Connection, table: str, *, limit: int, offset: int) -> list[dict[str, Any]]:
    _require_table(connection, table)
    try:
        rows = connection.execute(
            f"SELECT * FROM {_quote_identifier(table)} LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        raise click.ClickException(f"Unable to read table {table}: {exc}") from exc
    return [dict(row) for row in rows]


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    _require_table(connection, table)
    try:
        rows = connection.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
    except sqlite3.Error as exc:
        raise click.ClickException(f"Unable to inspect table {table}: {exc}") from exc
    return [str(row["name"]) for row in rows]


def _message_search_rows(
    context: CliContext,
    query: str,
    *,
    limit: int,
    offset: int,
    channel_id: int | None = None,
) -> list[dict[str, Any]]:
    if not context.db_path.exists():
        return []
    normalized_query = query.strip().lower()
    if not normalized_query:
        raise click.ClickException("Search query cannot be empty")
    with _connect_existing_sqlite(context.db_path) as connection:
        if "messages" not in set(_table_names(connection)):
            return []
        columns = _table_columns(connection, "messages")
        text_columns = [column for column in ("content", "message", "raw_text", "text", "caption") if column in columns]
        if not text_columns:
            return []
        selected = [column for column in ("id", "channel_id", "user_id", "sender_id", "date", "type", "content", "message", "raw_text", "text", "caption") if column in columns]
        text_expr = " || ' ' || ".join(f"COALESCE({_quote_identifier(column)}, '')" for column in text_columns)
        clauses = [f"LOWER({text_expr}) LIKE ?"]
        params: list[Any] = [f"%{normalized_query}%"]
        if channel_id is not None:
            if "channel_id" not in columns:
                raise click.ClickException("messages table does not contain channel_id")
            clauses.append("channel_id = ?")
            params.append(channel_id)
        order_column = "date" if "date" in columns else "id"
        try:
            rows = connection.execute(
                f"""
                SELECT {', '.join(_quote_identifier(column) for column in selected)}
                FROM messages
                WHERE {' AND '.join(clauses)}
                ORDER BY {_quote_identifier(order_column)} DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
        except sqlite3.Error as exc:
            raise click.ClickException(f"Unable to search messages: {exc}") from exc
    return [dict(row) for row in rows]


def _search_stats(context: CliContext) -> dict[str, Any]:
    if not context.db_path.exists():
        return {
            "database": str(context.db_path),
            "database_exists": False,
            "messages": 0,
            "searchable_columns": [],
            "saved_searches": 0,
        }
    with _connect_existing_sqlite(context.db_path) as connection:
        tables = set(_table_names(connection))
        columns = _table_columns(connection, "messages") if "messages" in tables else []
        searchable_columns = [column for column in ("content", "message", "raw_text", "text", "caption") if column in columns]
        saved_searches = _count_table_rows(connection, "saved_searches") if "saved_searches" in tables else 0
        messages = _count_table_rows(connection, "messages") if "messages" in tables else 0
    return {
        "database": str(context.db_path),
        "database_exists": True,
        "messages": messages,
        "searchable_columns": searchable_columns,
        "saved_searches": saved_searches,
        "semantic_available": _module_available("tgarchive.search.qihse_bindings"),
        "keystone_available": _module_available("tgarchive.search.keystone_bindings"),
    }


def _capability_status() -> dict[str, Any]:
    return {
        "telegram": _module_available("telethon"),
        "server": _module_available("flask"),
        "websocket": _module_available("flask_socketio"),
        "analysis": _module_available("networkx"),
        "dataframes": _module_available("pandas"),
        "crypto": _module_available("tgarchive.crypto.pqc"),
        "graphql": _module_available("tgarchive.api.graphql"),
        "qihse": _module_available("tgarchive.search.qihse_bindings"),
        "keystone": _module_available("tgarchive.search.keystone_bindings"),
    }


def _admin_health(context: CliContext) -> dict[str, Any]:
    task_records = _latest_task_records(context)
    running_tasks = sum(1 for record in task_records if _pid_running(record.get("pid")))
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "config": {"path": str(context.config_path), "exists": context.config_path.exists()},
        "database": {"path": str(context.db_path), "exists": context.db_path.exists()},
        "task_registry": {"path": str(_task_registry_path(context)), "tasks": len(task_records), "running": running_tasks},
        "capabilities": _capability_status(),
    }


def _server_health(context: CliContext) -> dict[str, Any]:
    config = _read_config_document(context.config_path)
    jwt_secret = os.environ.get("SPECTRA_JWT_SECRET") or config.get("SPECTRA_JWT_SECRET") or config.get("JWT_SECRET")
    unsafe_secret = jwt_secret in {None, "", "dev-secret-key", "change-me-in-production"}
    return {
        "server_available": _module_available("flask"),
        "cors_available": _module_available("flask_cors"),
        "socketio_available": _module_available("flask_socketio"),
        "graphql_available": _graphql_available(),
        "jwt_secret_configured": not unsafe_secret,
        "auth_required": False,
        "security_posture": "workstation_trust",
        "cors_origins": config.get("CORS_ORIGINS") or os.environ.get("SPECTRA_CORS_ORIGINS"),
        "config": str(context.config_path),
    }


def _doctor_checks(context: CliContext, *, capabilities: bool) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "python": {"ok": sys.version_info >= (3, 10), "version": platform.python_version()},
        "config": {"ok": context.config_path.exists(), "path": str(context.config_path)},
        "database_parent": {"ok": context.db_path.parent.exists(), "path": str(context.db_path)},
    }
    if capabilities:
        checks["capabilities"] = {
            name: {"available": _module_available(name)}
            for name in ("telethon", "flask", "flask_socketio", "pandas", "networkx", "fido2")
        }
    return checks


def _read_file_base64(path: Path) -> str:
    try:
        return base64.b64encode(path.read_bytes()).decode("utf-8")
    except OSError as exc:
        raise click.ClickException(f"Unable to read {path}: {exc}") from exc


def _write_bytes_file(path: Path, data: bytes, *, force: bool) -> None:
    if path.exists() and not force:
        raise click.ClickException(f"Output file already exists: {path}. Use --force to overwrite.")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        raise click.ClickException(f"Unable to write {path}: {exc}") from exc


def _crypto_result_or_unavailable(payload: dict[str, Any]) -> dict[str, Any]:
    error = payload.get("error")
    if error:
        raise click.ClickException(f"Unavailable capability: {error}")
    return _redact(payload)


def _operator_permissions(values: tuple[str, ...]) -> dict[str, bool]:
    permissions: dict[str, bool] = {}
    for value in values:
        key = value.strip()
        if not key:
            raise click.ClickException("Operator permission cannot be empty")
        if not key.replace("_", "").replace("-", "").isalnum():
            raise click.ClickException(f"Invalid operator permission: {key}")
        permissions[key] = True
    return permissions


def _operator_password(password_env: str | None, *, non_interactive: bool) -> str:
    if password_env:
        password = os.environ.get(password_env)
        if password is None:
            raise click.ClickException(f"Operator password environment variable is not set: {password_env}")
    else:
        if non_interactive:
            raise click.ClickException("Operator password requires --password-env in non-interactive mode")
        password = click.prompt("Operator password", hide_input=True, confirmation_prompt=True)
    from ..operator_security import validate_operator_password_strength

    problems = validate_operator_password_strength(password)
    if problems:
        raise click.ClickException("Operator password must include " + ", ".join(problems))
    return password


def _operator_record(username: str, password: str, roles: tuple[str, ...], permissions: tuple[str, ...]) -> dict[str, Any]:
    from ..operator_security import hash_password

    normalized_roles = [role.strip() for role in roles if role.strip()] or ["admin"]
    return {
        "user_id": username,
        "username": username,
        "password_hash": hash_password(password),
        "roles": normalized_roles,
        "permissions": _operator_permissions(permissions),
    }


def _write_rows(path: Path, rows: list[dict[str, Any]], output_format: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if output_format == "json":
            path.write_text(json.dumps(rows, indent=2, default=str) + "\n", encoding="utf-8")
            return
        if output_format == "jsonl":
            with path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, default=str) + "\n")
            return
        if output_format == "csv":
            fieldnames: list[str] = []
            for row in rows:
                for key in row:
                    if key not in fieldnames:
                        fieldnames.append(str(key))
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
            return
    except OSError as exc:
        raise click.ClickException(f"Unable to write export {path}: {exc}") from exc
    raise click.ClickException(f"Unsupported export format: {output_format}")


def _completion_script(shell: str, prog_name: str) -> str:
    from click.shell_completion import get_completion_class

    complete_cls = get_completion_class(shell)
    if complete_cls is None:
        raise click.ClickException(f"Unsupported shell: {shell}")
    return complete_cls(cli, {}, prog_name, f"_{prog_name.upper().replace('-', '_')}_COMPLETE").source()


def _default_completion_path(shell: str, prog_name: str) -> Path:
    home = Path.home()
    if shell == "bash":
        return home / ".local" / "share" / "bash-completion" / "completions" / prog_name
    if shell == "zsh":
        return home / ".zfunc" / f"_{prog_name}"
    if shell == "fish":
        return home / ".config" / "fish" / "completions" / f"{prog_name}.fish"
    raise click.ClickException(f"Unsupported shell: {shell}")


def _snapshot_profile_data(data: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(data)
    snapshot.pop("profiles", None)
    snapshot.pop("active_profile", None)
    return snapshot


def _env_name_for_path(prefix: str, parts: list[str]) -> str:
    safe_parts = ["".join(char if char.isalnum() else "_" for char in part).upper() for part in parts]
    return "_".join([prefix.upper(), *safe_parts])


def _migrate_env_refs(value: Any, prefix: str, parts: list[str], env_rows: list[str]) -> Any:
    if isinstance(value, dict):
        return {str(key): _migrate_env_refs(item, prefix, [*parts, str(key)], env_rows) for key, item in value.items()}
    if isinstance(value, list):
        return [_migrate_env_refs(item, prefix, [*parts, str(index)], env_rows) for index, item in enumerate(value)]
    key = parts[-1].lower() if parts else ""
    if isinstance(value, str) and value and any(secret_key in key for secret_key in ENV_MIGRATION_KEYS):
        env_name = _env_name_for_path(prefix, parts)
        env_rows.append(f"{env_name}={value}")
        return f"env:{env_name}"
    return value


def _scheduler_state_path(context: CliContext) -> Path:
    data = _read_config_document(context.config_path)
    configured = data.get("scheduler", {}).get("state_file") if isinstance(data.get("scheduler"), dict) else None
    return Path(str(configured or "scheduler_state.json"))


def _read_scheduler_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"jobs": []}
    return _read_json_file(path)


def _scheduler_db_schedules(context: CliContext) -> dict[str, list[dict[str, Any]]]:
    if not context.db_path.exists():
        return {"channel_forward": [], "file_forward": []}
    with _connect_existing_sqlite(context.db_path) as connection:
        tables = set(_table_names(connection))
        channel_rows = (
            _fetch_table_rows(connection, "channel_forward_schedule", limit=MAX_TABLE_LIMIT, offset=0)
            if "channel_forward_schedule" in tables else []
        )
        file_rows = (
            _fetch_table_rows(connection, "file_forward_schedule", limit=MAX_TABLE_LIMIT, offset=0)
            if "file_forward_schedule" in tables else []
        )
    return {"channel_forward": channel_rows, "file_forward": file_rows}


def _forwarding_status(context: CliContext) -> dict[str, Any]:
    if not context.db_path.exists():
        return {
            "database": str(context.db_path),
            "database_exists": False,
            "channel_forward_schedules": [],
            "file_forward_schedules": [],
            "channel_forward_stats": [],
            "file_forward_stats": [],
            "file_forward_queue_status": [],
        }
    with _connect_existing_sqlite(context.db_path) as connection:
        tables = set(_table_names(connection))
        schedules = _scheduler_db_schedules(context)
        channel_stats = (
            _fetch_table_rows(connection, "channel_forward_stats", limit=DEFAULT_TABLE_LIMIT, offset=0)
            if "channel_forward_stats" in tables else []
        )
        file_stats = (
            _fetch_table_rows(connection, "file_forward_stats", limit=DEFAULT_TABLE_LIMIT, offset=0)
            if "file_forward_stats" in tables else []
        )
        queue_status = [
            dict(row)
            for row in connection.execute(
                """
                SELECT COALESCE(status, 'unknown') AS status, COUNT(*) AS items
                FROM file_forward_queue
                GROUP BY COALESCE(status, 'unknown')
                ORDER BY items DESC, status
                """
            ).fetchall()
        ] if "file_forward_queue" in tables else []
    return {
        "database": str(context.db_path),
        "database_exists": True,
        "channel_forward_schedules": schedules["channel_forward"],
        "file_forward_schedules": schedules["file_forward"],
        "channel_forward_stats": channel_stats,
        "file_forward_stats": file_stats,
        "file_forward_queue_status": queue_status,
    }


def _discovery_status(context: CliContext) -> dict[str, Any]:
    if not context.db_path.exists():
        return {
            "database": str(context.db_path),
            "database_exists": False,
            "groups": 0,
            "sources": 0,
            "relationships": 0,
            "latest_discovery": None,
            "status_counts": [],
            "source_counts": [],
        }
    with _connect_existing_sqlite(context.db_path) as connection:
        tables = set(_table_names(connection))
        groups = _count_table_rows(connection, "discovered_groups") if "discovered_groups" in tables else 0
        sources = _count_table_rows(connection, "discovery_sources") if "discovery_sources" in tables else 0
        relationships = _count_table_rows(connection, "group_relationships") if "group_relationships" in tables else 0
        latest = None
        status_counts: list[dict[str, Any]] = []
        source_counts: list[dict[str, Any]] = []
        if "discovered_groups" in tables:
            latest_row = connection.execute(
                "SELECT MAX(date_discovered) AS latest_discovery FROM discovered_groups"
            ).fetchone()
            latest = latest_row["latest_discovery"] if latest_row else None
            status_counts = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT COALESCE(status, 'unknown') AS status, COUNT(*) AS groups
                    FROM discovered_groups
                    GROUP BY COALESCE(status, 'unknown')
                    ORDER BY groups DESC, status
                    """
                ).fetchall()
            ]
            source_counts = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT COALESCE(source, 'unknown') AS source, COUNT(*) AS groups
                    FROM discovered_groups
                    GROUP BY COALESCE(source, 'unknown')
                    ORDER BY groups DESC, source
                    LIMIT ?
                    """,
                    (DEFAULT_TABLE_LIMIT,),
                ).fetchall()
            ]
    return {
        "database": str(context.db_path),
        "database_exists": True,
        "groups": groups,
        "sources": sources,
        "relationships": relationships,
        "latest_discovery": latest,
        "status_counts": status_counts,
        "source_counts": source_counts,
    }


def _discovery_results(context: CliContext, *, limit: int, offset: int, status: str | None, source: str | None, min_priority: float) -> list[dict[str, Any]]:
    if not context.db_path.exists():
        return []
    with _connect_existing_sqlite(context.db_path) as connection:
        if "discovered_groups" not in set(_table_names(connection)):
            return []
        clauses = ["COALESCE(priority, 0) >= ?"]
        params: list[Any] = [min_priority]
        if status:
            clauses.append("status = ?")
            params.append(status)
        if source:
            clauses.append("source = ?")
            params.append(source)
        rows = connection.execute(
            f"""
            SELECT
                group_link,
                group_type,
                date_discovered,
                source,
                priority,
                status,
                last_checked,
                member_count,
                title,
                description
            FROM discovered_groups
            WHERE {' AND '.join(clauses)}
            ORDER BY COALESCE(priority, 0) DESC, date_discovered DESC, group_link
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    return [dict(row) for row in rows]


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError as exc:
        raise click.ClickException(f"Unable to read {path}: {exc}") from exc


def _directory_file_stats(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"files": 0, "bytes": 0}
    files = 0
    total_bytes = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                files += 1
                total_bytes += child.stat().st_size
    except OSError as exc:
        raise click.ClickException(f"Unable to inspect {path}: {exc}") from exc
    return {"files": files, "bytes": total_bytes}


def _tail_lines(path: Path, limit: int) -> list[str]:
    if not path.exists() or limit <= 0:
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError as exc:
        raise click.ClickException(f"Unable to read {path}: {exc}") from exc
    return [line.rstrip("\n") for line in lines[-limit:]]


def _download_log_path(export_dir: Path, state: dict[str, Any], manifest: dict[str, Any]) -> Path:
    """Resolve the freshest persisted log for a channel export."""
    candidates = [
        export_dir / "download.log",
        Path(str(state["log_path"])) if state.get("log_path") else None,
        Path(str(manifest["log_path"])) if manifest.get("log_path") else None,
    ]
    existing = [path for path in candidates if path is not None and path.is_file()]
    return max(existing, key=lambda path: path.stat().st_mtime_ns) if existing else export_dir / "download.log"


def _get_config_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if not part:
            raise click.ClickException("Config path contains an empty segment")
        if isinstance(current, dict):
            if part not in current:
                raise click.ClickException(f"Config path not found: {path}")
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise click.ClickException(f"Config path segment is not a list index: {part}") from exc
            try:
                current = current[index]
            except IndexError as exc:
                raise click.ClickException(f"Config list index out of range: {part}") from exc
            continue
        raise click.ClickException(f"Config path cannot descend into scalar segment: {part}")
    return current


def _parse_config_value(value: str, raw: bool) -> Any:
    if raw:
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Config value must be valid JSON unless --raw is used: {exc}") from exc


def _set_config_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    if not parts or any(not part for part in parts):
        raise click.ClickException("Config path contains an empty segment")
    current: Any = data
    for part in parts[:-1]:
        if isinstance(current, dict):
            child = current.setdefault(part, {})
            if not isinstance(child, (dict, list)):
                raise click.ClickException(f"Config path cannot descend into scalar segment: {part}")
            current = child
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise click.ClickException(f"Config path segment is not a list index: {part}") from exc
            try:
                current = current[index]
            except IndexError as exc:
                raise click.ClickException(f"Config list index out of range: {part}") from exc
            continue
        raise click.ClickException(f"Config path cannot descend into scalar segment: {part}")
    final = parts[-1]
    if isinstance(current, dict):
        current[final] = value
        return
    if isinstance(current, list):
        try:
            index = int(final)
        except ValueError as exc:
            raise click.ClickException(f"Config path segment is not a list index: {final}") from exc
        if index < 0 or index >= len(current):
            raise click.ClickException(f"Config list index out of range: {final}")
        current[index] = value
        return
    raise click.ClickException(f"Config path cannot assign into scalar segment: {final}")


def _unset_config_path(data: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    if not parts or any(not part for part in parts):
        raise click.ClickException("Config path contains an empty segment")
    current: Any = data
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                raise click.ClickException(f"Config path not found: {path}")
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except ValueError as exc:
                raise click.ClickException(f"Config path segment is not a list index: {part}") from exc
            except IndexError as exc:
                raise click.ClickException(f"Config list index out of range: {part}") from exc
            continue
        raise click.ClickException(f"Config path cannot descend into scalar segment: {part}")
    final = parts[-1]
    if isinstance(current, dict):
        if final not in current:
            raise click.ClickException(f"Config path not found: {path}")
        return current.pop(final)
    if isinstance(current, list):
        try:
            index = int(final)
        except ValueError as exc:
            raise click.ClickException(f"Config path segment is not a list index: {final}") from exc
        try:
            return current.pop(index)
        except IndexError as exc:
            raise click.ClickException(f"Config list index out of range: {final}") from exc
    raise click.ClickException(f"Config path cannot unset scalar segment: {final}")


def _session_name_from_phone(phone: str) -> str:
    digits = "".join(char for char in phone if char.isdigit())
    if not digits:
        raise click.ClickException("Phone number is required to derive a session name")
    return f"spectra_{digits}"


def _find_account_config(data: dict[str, Any], account: str | None) -> dict[str, Any] | None:
    accounts = data.get("accounts", [])
    if not isinstance(accounts, list):
        raise click.ClickException("Config accounts must be a list")
    if account is None:
        return accounts[0] if len(accounts) == 1 and isinstance(accounts[0], dict) else None
    for item in accounts:
        if not isinstance(item, dict):
            continue
        candidates = {
            str(item.get("session_name", "")),
            str(item.get("phone_number", "")),
            str(item.get("phone", "")),
        }
        if account in candidates:
            return item
    return None


def _upsert_account_config(data: dict[str, Any], account: dict[str, Any]) -> None:
    accounts = data.setdefault("accounts", [])
    if not isinstance(accounts, list):
        raise click.ClickException("Config accounts must be a list")
    session_name = account.get("session_name")
    for index, item in enumerate(accounts):
        if isinstance(item, dict) and item.get("session_name") == session_name:
            merged = dict(item)
            merged.update(account)
            accounts[index] = merged
            return
    accounts.append(account)


def _account_session_paths(session_name: str) -> list[Path]:
    return [Path(f"{session_name}.session"), Path(f"{session_name}.session-journal")]


def _account_has_session(session_name: Any) -> bool:
    if not session_name:
        return False
    return _account_session_paths(str(session_name))[0].exists()


def _remove_account_session_files(session_name: str) -> list[str]:
    removed: list[str] = []
    for path in _account_session_paths(session_name):
        if not path.exists():
            continue
        try:
            path.unlink()
        except OSError as exc:
            raise click.ClickException(f"Unable to remove session file {path}: {exc}") from exc
        removed.append(str(path))
    return removed


def _account_identifier_matches(account: dict[str, Any], identifier: str) -> bool:
    candidates = {
        str(account.get("session_name", "")),
        str(account.get("phone_number", "")),
        str(account.get("phone", "")),
    }
    return identifier in candidates


async def _login_account_async(account: dict[str, Any], *, code: str | None, password: str | None, force: bool, non_interactive: bool) -> dict[str, Any]:
    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
    except ImportError as exc:
        raise click.ClickException("Telethon is required for account login") from exc
    session_name = str(account.get("session_name") or "")
    phone = str(account.get("phone_number") or account.get("phone") or "")
    api_id = account.get("api_id")
    api_hash = account.get("api_hash")
    if not session_name or not phone or not api_id or not api_hash:
        raise click.ClickException("Account login requires session_name, phone_number, api_id, and api_hash")
    try:
        numeric_api_id = int(api_id)
    except (TypeError, ValueError) as exc:
        raise click.ClickException("Account api_id must be an integer") from exc
    async with TelegramClient(session_name, numeric_api_id, str(api_hash)) as client:
        if await client.is_user_authorized() and not force:
            return {"authorized": True, "already_authorized": True, "session_name": session_name, "phone_number": phone}
        await client.send_code_request(phone)
        login_code = code
        if not login_code:
            if non_interactive:
                raise click.ClickException("Telegram login code is required in non-interactive mode")
            login_code = click.prompt("Telegram code", hide_input=False).strip()
        try:
            await client.sign_in(phone=phone, code=login_code)
        except SessionPasswordNeededError:
            login_password = password
            if not login_password:
                if non_interactive:
                    raise click.ClickException("Telegram 2FA password is required in non-interactive mode")
                login_password = click.prompt("Telegram 2FA password", hide_input=True).strip()
            await client.sign_in(password=login_password)
        authorized = await client.is_user_authorized()
    if not authorized:
        raise click.ClickException("Telegram account was not authorized after login")
    return {"authorized": True, "already_authorized": False, "session_name": session_name, "phone_number": phone}


def _add_option(command: list[str], flag: str, value: Any) -> None:
    if value is None:
        return
    command.extend([flag, str(value)])


def _add_bool(command: list[str], flag: str, enabled: bool) -> None:
    if enabled:
        command.append(flag)


def _detached_log_path(output_dir: Path, entity: str) -> Path:
    safe_entity = "".join(char if char.isalnum() or char in "._-" else "_" for char in entity).strip("._-") or "channel"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return output_dir / f"spectra-channel-download-{safe_entity}-{timestamp}.log"


def _detached_channel_command(
    context: CliContext,
    *,
    entity: str,
    output_dir: Path,
    account: str | None,
    auto: bool,
    no_proxy: bool,
    no_media: bool,
    media_only: bool,
    max_connections: int,
    max_retries: int,
    retry_delay: float,
    fail_fast: bool,
    no_retry_flood_waits: bool,
    progress_interval: float,
    stall_timeout: float,
    limit: int | None,
    min_id: int | None,
    max_id: int | None,
    restart: bool,
    resume: bool,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "tgarchive",
        "--config",
        str(context.config_path),
        "--db",
        str(context.db_path),
        "channel",
        "download",
    ]
    _add_option(command, "--output-dir", output_dir)
    _add_option(command, "--account", account)
    _add_bool(command, "--auto", auto)
    _add_bool(command, "--no-proxy", no_proxy)
    _add_bool(command, "--no-media", no_media)
    _add_bool(command, "--media-only", media_only)
    _add_option(command, "--max-connections", max_connections)
    _add_option(command, "--max-retries", max_retries)
    _add_option(command, "--retry-delay", retry_delay)
    _add_bool(command, "--fail-fast", fail_fast)
    _add_bool(command, "--no-retry-flood-waits", no_retry_flood_waits)
    _add_option(command, "--progress-interval", progress_interval)
    _add_option(command, "--stall-timeout", stall_timeout)
    _add_option(command, "--limit", limit)
    _add_option(command, "--min-id", min_id)
    _add_option(command, "--max-id", max_id)
    _add_bool(command, "--restart", restart)
    command.append("--resume" if resume else "--no-resume")
    command.extend(["--", entity])
    return command


def _redact_argv(command: list[str]) -> list[str]:
    redacted = list(command)
    for index, token in enumerate(redacted[:-1]):
        if token == "--account":
            redacted[index + 1] = "[redacted]"
    return redacted


def _redact_audit_text(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(
        r"(?i)(api[_ -]?hash|api[_ -]?id|password|otp|secret|token)\s*(?:=|:)??\s+[^\s,]+",
        r"\1=[redacted]",
        value,
    )


def _redact_index_watch_value(value: Any, key: str | None = None) -> Any:
    redacted = _redact(value, key)
    if isinstance(redacted, dict):
        return {
            str(item_key): _redact_index_watch_value(item_value, str(item_key))
            for item_key, item_value in redacted.items()
        }
    if isinstance(redacted, list):
        return [_redact_index_watch_value(item) for item in redacted]
    if isinstance(redacted, str):
        redacted = _redact_audit_text(redacted)
        return re.sub(
            r"""(?ix)
            (?P<prefix>
                ["']?\b
                (?:api[_ -]?hash|api[_ -]?id|password|otp|secret|token)
                \b["']?\s*(?:=|:)\s*
            )
            (?:"[^"]*"|'[^']*'|[^\s,;}\]]+)
            """,
            r"\g<prefix>[redacted]",
            redacted,
        )
    return redacted


def _emit_index_watch_diagnostic(event: str, *, level: str, **details: Any) -> None:
    payload = _redact_index_watch_value({
        "event": event,
        "level": level,
        **details,
    })
    click.echo(json.dumps(payload, sort_keys=True, default=str), err=True)


def _audit_json(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(_redact(value), default=str, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise click.ClickException(f"Unable to serialize operation audit payload: {exc}") from exc


def _task_registry_path(context: CliContext) -> Path:
    return context.db_path.with_suffix(".tasks.sqlite3")


def _legacy_task_registry_path(context: CliContext) -> Path:
    return context.db_path.with_suffix(".tasks.jsonl")


def _connect_task_registry(context: CliContext) -> sqlite3.Connection:
    registry_path = _task_registry_path(context)
    try:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        connection = connect_sqlite(registry_path)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS task_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                kind TEXT,
                status TEXT,
                pid INTEGER,
                event_at TEXT NOT NULL,
                log_path TEXT,
                output_dir TEXT,
                argv_json TEXT,
                payload_json TEXT NOT NULL,
                source TEXT,
                source_line INTEGER,
                UNIQUE(source, source_line)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS operation_audit (
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
                error_json TEXT
            )
            """
        )
        IndexOutbox.ensure_schema(connection)
        connection.commit()
    except sqlite3.Error as exc:
        raise click.ClickException(f"Unable to open task registry {registry_path}: {exc}") from exc
    return connection


def _create_operation_audit(
    context: CliContext,
    *,
    source: str,
    request_text: str | None,
    operation_id: str | None,
    status: str,
    started_at: str,
    envelope: Any = None,
    planned_command: list[str] | None = None,
    actual_argv: list[str] | None = None,
    result: Any = None,
    error: Any = None,
) -> str:
    audit_id = f"audit-{uuid.uuid4().hex}"
    try:
        with _connect_task_registry(context) as connection:
            connection.execute(
                """
                INSERT INTO operation_audit
                (audit_id, source, actor, request_text, operation_id, status, started_at,
                 finished_at, envelope_json, planned_command_json, actual_argv_json,
                 result_json, error_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    source,
                    getpass.getuser() or "unknown",
                    _redact_audit_text(request_text) if request_text else None,
                    operation_id,
                    status,
                    started_at,
                    datetime.now(timezone.utc).isoformat() if status in {"completed", "failed", "planned", "unavailable"} else None,
                    _audit_json(envelope),
                    _audit_json(_redact_argv(planned_command)) if planned_command else None,
                    _audit_json(_redact_argv(actual_argv)) if actual_argv else None,
                    _audit_json(result),
                    _audit_json(error),
                ),
            )
            IndexOutbox.append_to(
                connection,
                source_table="operation_audit",
                source_key=audit_id,
                event_type=status,
                payload={
                    "audit_id": audit_id,
                    "source": source,
                    "operation_id": operation_id,
                    "status": status,
                    "started_at": started_at,
                    "result": result,
                    "error": error,
                },
                source_revision=started_at,
            )
            connection.commit()
    except sqlite3.Error as exc:
        raise click.ClickException(f"Unable to write operation audit record: {exc}") from exc
    return audit_id


def _finish_operation_audit(context: CliContext, audit_id: str, *, status: str, result: Any = None, error: Any = None) -> None:
    try:
        with _connect_task_registry(context) as connection:
            finished_at = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "UPDATE operation_audit SET status = ?, finished_at = ?, result_json = ?, error_json = ? WHERE audit_id = ?",
                (
                    status,
                    finished_at,
                    _audit_json(result),
                    _audit_json(error),
                    audit_id,
                ),
            )
            IndexOutbox.append_to(
                connection,
                source_table="operation_audit",
                source_key=audit_id,
                event_type=status,
                payload={"audit_id": audit_id, "status": status, "result": result, "error": error, "finished_at": finished_at},
                source_revision=finished_at,
            )
            connection.commit()
    except sqlite3.Error as exc:
        raise click.ClickException(f"Unable to update operation audit record {audit_id}: {exc}") from exc


def _operation_canonical_argv(context: CliContext, operation_id: str, arguments: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tgarchive",
        "--config",
        str(context.config_path),
        "--db",
        str(context.db_path),
        "operations",
        "run",
        operation_id,
        "--arguments",
        json.dumps(_redact(arguments), sort_keys=True, separators=(",", ":")),
    ]


def _operation_audit_rows(context: CliContext, *, limit: int, audit_id: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM operation_audit"
    params: tuple[Any, ...] = ()
    if audit_id:
        query += " WHERE audit_id = ?"
        params = (audit_id,)
    query += " ORDER BY started_at DESC LIMIT ?"
    params += (limit,)
    try:
        with _connect_task_registry(context) as connection:
            rows = connection.execute(query, params).fetchall()
    except sqlite3.Error as exc:
        raise click.ClickException(f"Unable to read operation audit: {exc}") from exc
    records: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        for key in ("envelope_json", "planned_command_json", "actual_argv_json", "result_json", "error_json"):
            raw = record.get(key)
            if raw is not None:
                try:
                    record[key] = json.loads(raw)
                except json.JSONDecodeError:
                    record[key] = {"malformed": True}
        records.append(_redact(record))
    return records


def _insert_task_record(connection: sqlite3.Connection, record: dict[str, Any], *, source: str | None = None, source_line: int | None = None) -> None:
    task_id = record.get("id")
    if not isinstance(task_id, str) or not task_id:
        raise click.ClickException("Task record does not contain a valid id")
    event_at = (
        record.get("cancel_requested_at")
        or record.get("started_at")
        or record.get("event_at")
        or datetime.now(timezone.utc).isoformat()
    )
    argv = record.get("argv")
    try:
        payload_json = json.dumps(record, default=str)
        argv_json = json.dumps(argv, default=str) if argv is not None else None
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO task_events
            (task_id, kind, status, pid, event_at, log_path, output_dir, argv_json, payload_json, source, source_line)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                record.get("kind"),
                record.get("status"),
                record.get("pid"),
                str(event_at),
                record.get("log_path"),
                record.get("output_dir"),
                argv_json,
                payload_json,
                source,
                source_line,
            ),
        )
        if cursor.rowcount:
            IndexOutbox.append_to(
                connection,
                source_table="task_events",
                source_key=str(cursor.lastrowid),
                event_type=str(record.get("status") or "event"),
                payload={
                    **record,
                    "event_id": int(cursor.lastrowid),
                    "task_id": task_id,
                    "event_at": str(event_at),
                },
                source_revision=str(event_at),
            )
    except (TypeError, sqlite3.Error) as exc:
        raise click.ClickException(f"Unable to write task registry record: {exc}") from exc


def _migrate_legacy_task_registry(context: CliContext, connection: sqlite3.Connection) -> None:
    legacy_path = _legacy_task_registry_path(context)
    if not legacy_path.exists():
        return
    try:
        with legacy_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise click.ClickException(f"Malformed legacy task registry line {line_number}: {exc}") from exc
                if isinstance(payload, dict):
                    _insert_task_record(connection, payload, source=str(legacy_path), source_line=line_number)
        connection.commit()
    except OSError as exc:
        raise click.ClickException(f"Unable to read legacy task registry {legacy_path}: {exc}") from exc


def _append_task_record(context: CliContext, record: dict[str, Any]) -> None:
    with _connect_task_registry(context) as connection:
        _migrate_legacy_task_registry(context, connection)
        _insert_task_record(connection, record)
        connection.commit()


def _load_task_records(context: CliContext) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with _connect_task_registry(context) as connection:
        _migrate_legacy_task_registry(context, connection)
        try:
            rows = connection.execute("SELECT payload_json FROM task_events ORDER BY event_id").fetchall()
        except sqlite3.Error as exc:
            raise click.ClickException(f"Unable to read task registry {_task_registry_path(context)}: {exc}") from exc
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise click.ClickException(f"Malformed task registry payload: {exc}") from exc
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _latest_task_records(context: CliContext) -> list[dict[str, Any]]:
    records_by_id: dict[str, dict[str, Any]] = {}
    for record in _load_task_records(context):
        task_id = record.get("id")
        if isinstance(task_id, str) and task_id:
            records_by_id[task_id] = record
    return list(records_by_id.values())


def _find_task_record(context: CliContext, task_id: str) -> dict[str, Any]:
    for record in reversed(_load_task_records(context)):
        if record.get("id") == task_id:
            return record
    raise click.ClickException(f"Task not found: {task_id}")


def _read_task_channel_status(record: dict[str, Any], tail: int) -> dict[str, Any] | None:
    output_dir = record.get("output_dir")
    if not output_dir:
        return None
    export_dir = Path(str(output_dir))
    if not export_dir.exists() or not export_dir.is_dir():
        return None
    state = _read_json_file(export_dir / "state.json")
    manifest = _read_json_file(export_dir / "manifest.json")
    summary = _read_json_file(export_dir / "summary.json")
    media_stats = _directory_file_stats(export_dir / "media")
    log_path = _download_log_path(export_dir, state, manifest)
    return {
        "complete": bool(state.get("complete") or summary.get("complete")),
        "last_message_id": state.get("last_message_id") or summary.get("last_message_id"),
        "state_updated_at": state.get("updated_at"),
        "media_downloaded_this_run": state.get("media_downloaded_this_run"),
        "media_skipped_this_run": state.get("media_skipped_this_run"),
        "media_failed_this_run": state.get("media_failed_this_run"),
        "failed_media_ids": state.get("failed_media_ids", []),
        "media_files": media_stats["files"],
        "media_bytes": media_stats["bytes"],
        "manifest_records": _count_jsonl(export_dir / "media_manifest.jsonl"),
        "has_summary": bool(summary),
        "log_path": str(log_path),
        "log_tail": _tail_lines(log_path, tail),
    }


def _enrich_task_record(record: dict[str, Any], *, tail: int = 0) -> dict[str, Any]:
    enriched = dict(record)
    running = _pid_running(enriched.get("pid"))
    enriched["running"] = running
    log_path = enriched.get("log_path")
    if log_path and tail > 0:
        enriched["log_tail"] = _tail_lines(Path(str(log_path)), tail)
    channel_status_payload = _read_task_channel_status(enriched, tail)
    if channel_status_payload is not None:
        enriched["channel_status"] = channel_status_payload
        if enriched.get("status") == "running" and channel_status_payload.get("complete"):
            enriched["status"] = "completed"
    if enriched.get("status") == "running" and not running:
        enriched["status"] = "exited"
    return _redact(enriched)


def _recovery_status(record: dict[str, Any]) -> str | None:
    if record.get("status") != "running":
        return None
    channel_status_payload = _read_task_channel_status(record, 0)
    if channel_status_payload and channel_status_payload.get("complete"):
        return "completed"
    if not _pid_running(record.get("pid")):
        return "exited"
    return None


def _pid_running(pid: Any) -> bool:
    try:
        numeric_pid = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        os.kill(numeric_pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _interrupt_process_group(pid: Any) -> None:
    try:
        numeric_pid = int(pid)
    except (TypeError, ValueError) as exc:
        raise click.ClickException("Task record does not contain a valid pid") from exc
    try:
        os.killpg(numeric_pid, signal.SIGINT)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise click.ClickException(f"Permission denied while cancelling pid {numeric_pid}") from exc


def _load_config(path: Path):
    from ..core.config_models import Config

    return Config(path)


def _run_legacy(handler_name: str, **values: Any) -> None:
    """Invoke an existing production handler through the modern command tree."""
    from .. import __main__ as legacy

    getattr(legacy, '_load_legacy_dependencies', lambda: None)()
    context = _context()
    defaults = {
        "config": str(context.config_path),
        "db": str(context.db_path),
        "data_dir": "spectra_data",
        "import_accounts": False,
        "parallel": False,
        "max_workers": None,
    }
    defaults.update(values)
    result = asyncio.run(getattr(legacy, handler_name)(SimpleNamespace(**defaults)))
    if result:
        raise click.exceptions.Exit(result)


def _forwarding_options(function):
    options = [
        click.option("--channels-file", type=click.Path(path_type=Path), help="File of seed channel URLs for traversal/download mode."),
        click.option("--output-dir", type=click.Path(path_type=Path), help="Output directory for traversal/download mode."),
        click.option("--max-depth", type=click.IntRange(min=1), default=2, show_default=True, help="Maximum traversal depth."),
        click.option("--min-files-gateway", type=click.IntRange(min=1), default=100, show_default=True, help="Minimum files for gateway classification."),
        click.option("--origin", help="Origin channel/chat for direct forwarding."),
        click.option("--destination", help="Destination channel/chat. Uses config default if omitted."),
        click.option("--account", help="Specific account phone or session name."),
        click.option("--total-mode", is_flag=True, help="Forward from all accessible database channels."),
        click.option("--all-dialogs", is_flag=True, help="Sweep and forward every accessible dialog."),
        click.option("--forward-to-all-saved", is_flag=True, help="Also copy into Saved Messages for configured accounts."),
        click.option("--prepend-origin-info", is_flag=True, help="Prepend origin metadata to forwarded message text."),
        click.option("--copy-into-destination", "--copy-mode", "copy_into_destination", flag_value=True, default=False, help="Copy messages as native destination posts."),
        click.option("--preserve-forward-header", "--forward-mode", "copy_into_destination", flag_value=False, help="Use Telegram native forwarding headers."),
        click.option("--source-topic-id", "--source-room-id", type=click.IntRange(min=1), help="Restrict single-origin forwarding to one source topic."),
        click.option("--destination-topic-id", "--destination-room-id", type=click.IntRange(min=1), help="Post into one destination topic."),
        click.option("--include-text-messages", is_flag=True, help="Include text-only messages as well as media."),
        click.option("--quote-copied-messages", is_flag=True, help="Quote original text when copy mode is active."),
        click.option("--secondary-unique-destination", help="Secondary destination for unique messages only."),
        click.option("--source-accounts", multiple=True, help="Restrict total mode to these source account identifiers."),
        click.option("--include-saved-messages", is_flag=True, help="Include Saved Messages in dialog sweeps."),
        click.option("--include-private-chats/--exclude-private-chats", default=True, show_default=True, help="Include private chats in dialog sweeps."),
        click.option("--enable-deduplication/--disable-deduplication", default=None, help="Override forwarding deduplication config."),
        click.option("--enable-auto-invites/--disable-auto-invites", "auto_invite_accounts", default=None, help="Override auto-invite behavior."),
    ]
    for option in reversed(options):
        function = option(function)
    return function


def _run_forward_legacy(**values: Any) -> None:
    context = _context()
    defaults = {
        "config": str(context.config_path),
        "db": str(context.db_path),
        "channels_file": None,
        "output_dir": None,
        "max_depth": 2,
        "min_files_gateway": 100,
        "origin": None,
        "destination": None,
        "account": None,
        "total_mode": False,
        "all_dialogs": False,
        "forward_to_all_saved": False,
        "prepend_origin_info": False,
        "copy_into_destination": False,
        "source_topic_id": None,
        "destination_topic_id": None,
        "include_text_messages": False,
        "quote_copied_messages": False,
        "secondary_unique_destination": None,
        "source_accounts": None,
        "include_saved_messages": False,
        "include_private_chats": True,
        "enable_deduplication": None,
        "auto_invite_accounts": None,
        "import_accounts": False,
    }
    defaults.update(values)
    if isinstance(defaults.get("source_accounts"), tuple):
        defaults["source_accounts"] = list(defaults["source_accounts"]) or None
    if context.dry_run:
        _emit(_redact({
            "dry_run": True,
            "handler": "handle_cloud_forwarding" if defaults.get("channels_file") and defaults.get("output_dir") else "handle_attachment_forwarding",
            "options": defaults,
        }), context.output)
        return
    from .. import __main__ as legacy

    getattr(legacy, '_load_legacy_dependencies', lambda: None)()
    args = SimpleNamespace(**defaults)
    if args.channels_file and args.output_dir:
        result = asyncio.run(legacy.handle_cloud_forwarding(args))
    else:
        result = asyncio.run(legacy.handle_attachment_forwarding(args))
    if result:
        raise click.exceptions.Exit(result)


def _context() -> CliContext:
    ctx = click.get_current_context().find_root().obj
    if not isinstance(ctx, CliContext):
        raise click.ClickException("CLI context was not initialized")
    return ctx


def _operation_registry():
    global _OPERATION_REGISTRY_CACHE
    if _OPERATION_REGISTRY_CACHE is not None:
        return _OPERATION_REGISTRY_CACHE
    try:
        from ..operations import create_builtin_registry
    except ImportError as exc:
        raise click.ClickException("Unavailable capability: operation registry requires pydantic v2") from exc
    registry = create_builtin_registry()
    registry.attach_handler("version", _operation_version)
    registry.attach_handler("doctor", _operation_doctor)
    registry.attach_handler("config.get", _operation_config_get)
    registry.attach_handler("task.show", _operation_task_show)
    registry.attach_handler("channel.status", _operation_channel_status)
    registry.attach_handler("index.status", _operation_index_status)
    registry.attach_handler("index.process", _operation_index_process)
    registry.attach_handler("index.drain", _operation_index_drain)
    registry.attach_handler("index.rebuild", _operation_index_rebuild)
    registry.attach_handler("index.verify", _operation_index_verify)
    registry.attach_handler("index.lookup", _operation_index_lookup)
    registry.attach_handler("index.lookup-record", _operation_index_record_lookup)
    registry.attach_handler("index.graph", _operation_index_graph)
    registry.attach_handler("index.backfill-export", _operation_index_backfill_export)
    registry.attach_handler("index.backfill-database", _operation_index_backfill_database)
    registry.attach_handler("index.scan-archive", _operation_index_scan_archive)
    registry.attach_handler("index.benchmark", _operation_index_benchmark)
    _OPERATION_REGISTRY_CACHE = registry
    return registry


def _operation_result(operation_id: str, arguments: dict[str, Any], context: CliContext):
    try:
        from ..operations.models import OperationEnvelope
        from ..operations.registry import OperationUnavailable
    except ImportError as exc:
        raise click.ClickException("Unavailable capability: operation registry requires pydantic v2") from exc
    try:
        result = _operation_registry().execute(
            OperationEnvelope(operation_id=operation_id, arguments=arguments, dry_run=context.dry_run),
            context,
        )
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    except OperationUnavailable as exc:
        raise click.ClickException(f"Unavailable capability: {exc}") from exc
    if result.error is not None:
        raise click.ClickException(result.error.message)
    return result.result


def _operation_version(arguments: Any, context: CliContext) -> dict[str, Any]:
    from .. import __version__

    return {"spectra": __version__, "python": platform.python_version()}


def _operation_doctor(arguments: Any, context: CliContext) -> dict[str, Any]:
    return {"checks": _doctor_checks(context, capabilities=bool(arguments.capabilities))}


def _operation_config_get(arguments: Any, context: CliContext) -> dict[str, Any]:
    cfg = _load_config(context.config_path)
    value = _get_config_path(cfg.data, arguments.path)
    return {"path": arguments.path, "value": _redact(value, arguments.path)}


def _operation_task_show(arguments: Any, context: CliContext) -> dict[str, Any]:
    return {"record": _enrich_task_record(_find_task_record(context, arguments.task_id), tail=arguments.tail)}


def _channel_status_payload(export_dir: Path, tail: int) -> dict[str, Any]:
    if not export_dir.exists():
        raise click.ClickException(f"Export directory not found: {export_dir}")
    if not export_dir.is_dir():
        raise click.ClickException(f"Export path is not a directory: {export_dir}")

    state = _read_json_file(export_dir / "state.json")
    manifest = _read_json_file(export_dir / "manifest.json")
    summary = _read_json_file(export_dir / "summary.json")
    media_stats = _directory_file_stats(export_dir / "media")
    log_path = _download_log_path(export_dir, state, manifest)
    return {
        "export_dir": str(export_dir),
        "title": manifest.get("title") or summary.get("title"),
        "entity": manifest.get("entity") or summary.get("entity"),
        "entity_id": manifest.get("entity_id") or summary.get("entity_id"),
        "complete": bool(state.get("complete") or summary.get("complete")),
        "last_message_id": state.get("last_message_id") or summary.get("last_message_id"),
        "state_updated_at": state.get("updated_at"),
        "messages_written_this_run": state.get("messages_written_this_run"),
        "media_downloaded_this_run": state.get("media_downloaded_this_run"),
        "media_skipped_this_run": state.get("media_skipped_this_run"),
        "media_failed_this_run": state.get("media_failed_this_run"),
        "failed_media_ids": state.get("failed_media_ids", []),
        "media_files": media_stats["files"],
        "media_bytes": media_stats["bytes"],
        "manifest_records": _count_jsonl(export_dir / "media_manifest.jsonl"),
        "has_summary": bool(summary),
        "log_path": str(log_path),
        "log_tail": _tail_lines(log_path, tail),
    }


def _operation_channel_status(arguments: Any, context: CliContext) -> dict[str, Any]:
    return {"status": _redact(_channel_status_payload(arguments.export_dir, arguments.tail))}


def _operation_index_status(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..db.index_outbox import IndexOutbox

    return IndexOutbox(context.db_path).status()


def _operation_index_process(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..db.index_projector import IndexProjector

    if context.dry_run:
        return {"details": {"dry_run": True, "batch_size": arguments.batch_size, "lease_seconds": arguments.lease_seconds}}
    return {"details": IndexProjector(context.db_path).process(
        batch_size=arguments.batch_size,
        lease_seconds=arguments.lease_seconds,
    )}


def _operation_index_rebuild(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..db.index_projector import IndexProjector

    if context.dry_run:
        return {"details": {"dry_run": True, "projection": arguments.projection}}
    return {"details": IndexProjector(context.db_path).rebuild(projection=arguments.projection)}


def _operation_index_drain(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..db.index_projector import IndexProjector

    if context.dry_run:
        return {"details": {
            "dry_run": True,
            "batch_size": arguments.batch_size,
            "lease_seconds": arguments.lease_seconds,
            "max_batches": arguments.max_batches,
        }}
    return {"details": IndexProjector(context.db_path).drain(
        batch_size=arguments.batch_size,
        lease_seconds=arguments.lease_seconds,
        max_batches=arguments.max_batches,
    )}


def _operation_index_verify(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..db.index_projector import IndexProjector

    return {"details": IndexProjector(context.db_path).verify(
        projection=arguments.projection,
        native=arguments.native,
        sample_size=arguments.sample_size,
    )}


def _operation_index_lookup(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..db.index_projector import IndexProjector

    with IndexProjector(context.db_path) as projector:
        details = projector.lookup(
            channel_id=arguments.channel_id,
            message_id=arguments.message_id,
        )
    return {"details": details}


def _operation_index_record_lookup(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..db.index_projector import IndexProjector

    with IndexProjector(context.db_path) as projector:
        details = projector.lookup_record(
            projection=arguments.projection,
            namespace=arguments.namespace,
            external_id=arguments.external_id,
        )
    return {"details": details}


def _operation_index_graph(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..db.index_projector import IndexProjector

    return {"details": IndexProjector(context.db_path).graph_neighbors(
        node_type=arguments.node_type,
        external_id=arguments.external_id,
        edge_type=arguments.edge_type,
        direction=arguments.direction,
        limit=arguments.limit,
    )}


def _operation_index_backfill_export(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..services.index_backfill import backfill_channel_export

    if context.dry_run:
        return {"details": {
            "dry_run": True,
            "database": str(context.db_path),
            "export_dir": str(arguments.export_dir),
            "limit": arguments.limit,
        }}
    return {"details": backfill_channel_export(
        arguments.export_dir,
        context.db_path,
        limit=arguments.limit,
    )}


def _operation_index_backfill_database(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..services.index_database_backfill import backfill_database_records

    if context.dry_run:
        return {"details": {
            "dry_run": True,
            "database": str(context.db_path),
            "limit": arguments.limit,
        }}
    return {"details": backfill_database_records(
        context.db_path,
        limit=arguments.limit,
    )}


def _operation_index_scan_archive(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..services.archive_member_scanner import scan_archive_members

    if context.dry_run:
        return {"details": {
            "dry_run": True,
            "database": str(context.db_path),
            "archive_path": str(arguments.archive_path),
            "limit": arguments.limit,
        }}
    return {"details": scan_archive_members(
        arguments.archive_path,
        context.db_path,
        limit=arguments.limit,
    )}


def _operation_index_benchmark(arguments: Any, context: CliContext) -> dict[str, Any]:
    from ..services.index_benchmark import benchmark_indexing

    if context.dry_run:
        return {"details": {
            "dry_run": True,
            "database": str(arguments.database) if arguments.database else None,
            "events": arguments.events,
            "writers": arguments.writers,
            "lookups": arguments.lookups,
            "batch_size": arguments.batch_size,
        }}
    return {"details": benchmark_indexing(
        database=arguments.database,
        events=arguments.events,
        writers=arguments.writers,
        lookups=arguments.lookups,
        batch_size=arguments.batch_size,
    )}


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--config", "config_path", type=click.Path(path_type=Path), default="spectra_config.json", show_default=True)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default="spectra.db", show_default=True)
@click.option("--output", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), default="table", show_default=True)
@click.option("--quiet", is_flag=True, help="Suppress non-result status output.")
@click.option("--verbose", is_flag=True, help="Emit additional diagnostics where supported.")
@click.option("--no-color", is_flag=True, help="Disable terminal colour output.")
@click.option("--non-interactive", is_flag=True, help="Never prompt for missing input.")
@click.option("--yes", is_flag=True, help="Confirm destructive operations.")
@click.option("--dry-run", is_flag=True, help="Validate work without making changes where supported.")
@click.option("--timeout", type=click.FloatRange(min=0), help="Operation timeout in seconds where supported.")
@click.option("--detach", is_flag=True, help="Start long-running operations in the background where supported.")
@click.version_option(package_name="spectra-archive", prog_name="spectra")
@click.pass_context
def cli(ctx: click.Context, config_path: Path, db_path: Path, output: str, quiet: bool, verbose: bool, no_color: bool, non_interactive: bool, yes: bool, dry_run: bool, timeout: float | None, detach: bool) -> None:
    """SPECTRA: Telegram collection, analysis, and operations."""
    ctx.obj = CliContext(config_path, db_path, output.lower(), quiet, verbose, no_color, non_interactive, yes, dry_run, timeout, detach)


@cli.command()
def version() -> None:
    """Print SPECTRA and Python runtime versions."""
    context = _context()
    _emit(_operation_result("version", {}, context), context.output)


@cli.command()
@click.argument("shell", type=click.Choice(SUPPORTED_COMPLETION_SHELLS, case_sensitive=False))
@click.option("--prog-name", default="spectra", show_default=True, help="Executable name used by the completion script.")
@click.option("--install", is_flag=True, help="Install the completion script into the standard user completion directory.")
@click.option("--path", "install_path", type=click.Path(path_type=Path), help="Install path or output path when used with --install.")
@click.option("--force", is_flag=True, help="Overwrite an existing completion file when installing.")
def completion(shell: str, prog_name: str, install: bool, install_path: Path | None, force: bool) -> None:
    """Generate or install shell completion."""
    context = _context()
    normalized_shell = shell.lower()
    script = _completion_script(normalized_shell, prog_name)
    target = install_path or _default_completion_path(normalized_shell, prog_name)
    if not install:
        click.echo(script.rstrip())
        return
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to install completion in non-interactive mode without --yes")
    if target.exists() and not force:
        raise click.ClickException(f"Completion file already exists: {target}. Use --force to overwrite.")
    if not context.dry_run:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(script, encoding="utf-8")
        except OSError as exc:
            raise click.ClickException(f"Unable to write completion file {target}: {exc}") from exc
    _emit({
        "shell": normalized_shell,
        "prog_name": prog_name,
        "path": str(target),
        "installed": not context.dry_run,
        "dry_run": context.dry_run,
    }, context.output)


HELP_TOPICS: dict[str, str] = {
    "channel-download": (
        "Download channel media:\n"
        "  spectra channel download --output-dir /fast/ULPs --account session_name --media-only --no-proxy -- -1001234567890\n"
        "\n"
        "Status:\n"
        "  spectra channel status /fast/ULPs/Channel_123 --output json\n"
        "\n"
        "Recovery:\n"
        "  Re-run the same command without --restart. Existing complete files are skipped, partial .part files are cleaned up, and failed media IDs stay visible in state.json."
    ),
    "errors": (
        "Common exit codes:\n"
        "  0 success\n"
        "  2 usage error\n"
        "  3 configuration or authentication error\n"
        "  6 network or Telegram failure\n"
        "  7 partial completion\n"
        "  8 unavailable capability\n"
        "  130 interrupted"
    ),
    "auth": (
        "Telegram account authorization:\n"
        "  spectra account login spectra_447353481399\n"
        "  spectra --non-interactive account login spectra_447353481399 --code 12345\n"
        "\n"
        "New account:\n"
        "  spectra account login --phone +10000000000 --api-id 123456 --api-hash \"your-api-hash\"\n"
        "\n"
        "2FA:\n"
        "  export SPECTRA_TELEGRAM_2FA_PASSWORD=\"your-password\"\n"
        "  spectra account login spectra_447353481399 --password-env SPECTRA_TELEGRAM_2FA_PASSWORD\n"
        "\n"
        "Secrets are redacted from account list, account show, config show, config get, and task output."
    ),
    "discovery": (
        "Discovery and network analysis:\n"
        "  spectra discover run --seed @target_channel --depth 2 --messages 1000 --export discovered.json\n"
        "  spectra discover run --seeds-file seeds.txt --depth 2 --parallel --max-workers 4\n"
        "  spectra network analyze --crawler-dir ./telegram-groups-crawler --top 50 --export priority_targets.json\n"
        "  spectra network analyze --from-db --metric combined --top 50\n"
        "\n"
        "Use --output json on status-oriented commands. Discovery commands may contact Telegram and should be run with authorized accounts."
    ),
    "forwarding": (
        "Forwarding workflows:\n"
        "  spectra forward --origin @source --destination @dest --dry-run\n"
        "  spectra forward --origin @source --destination @dest --total-mode --source-accounts spectra_1 spectra_2\n"
        "  spectra config set-forward-dest -1001234567890\n"
        "  spectra config view-forward-dest --output json\n"
        "\n"
        "Use --dry-run before bulk forwarding. Source account restrictions use session names or phone numbers."
    ),
    "exports": (
        "Export and local artifact inspection:\n"
        "  spectra channel status channel_downloads/Example_123 --output json --tail 20\n"
        "  spectra task show task-20260728T205258Z --output json\n"
        "  spectra task events task-20260728T205258Z --output json\n"
        "\n"
        "Whole-channel downloads write manifest.json, state.json, media_manifest.jsonl, download.log, and final summary.json."
    ),
    "recovery": (
        "Recovery workflows:\n"
        "  spectra channel status channel_downloads/Example_123 --output json --tail 50\n"
        "  spectra task recover --output json\n"
        "  spectra task watch task-20260728T205258Z --tail 30\n"
        "  spectra channel download @target --output-dir channel_downloads --media-only\n"
        "\n"
        "Resume channel downloads by rerunning the same command without --restart. Existing complete files are skipped, .part files are cleaned up, and failed media IDs remain visible in state.json."
    ),
    "completion": (
        "Shell completion:\n"
        "  spectra completion bash > ~/.local/share/bash-completion/completions/spectra\n"
        "  spectra completion zsh > ~/.zfunc/_spectra\n"
        "  spectra completion fish > ~/.config/fish/completions/spectra.fish\n"
        "\n"
        "Install directly:\n"
        "  spectra --yes completion bash --install\n"
        "  spectra --yes completion zsh --install --path ~/.zfunc/_spectra\n"
        "\n"
        "Restart the shell after installing, or source the generated file where the shell supports it."
    ),
}


@cli.command("help")
@click.argument("topic", required=False)
def help_topic(topic: str | None) -> None:
    """Print offline help for an operational topic."""
    if topic is None:
        _emit({"topics": sorted(HELP_TOPICS)}, _context().output)
        return
    key = topic.strip().lower()
    if key not in HELP_TOPICS:
        raise click.ClickException(f"Unknown help topic: {topic}")
    click.echo(HELP_TOPICS[key])


def _parse_operation_arguments(arguments: str) -> dict[str, Any]:
    if arguments.startswith("@"):
        return _read_json_file(Path(arguments[1:]))
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Operation arguments must be a JSON object or @file: {exc}") from exc
    if not isinstance(parsed, dict):
        raise click.ClickException("Operation arguments must be a JSON object")
    return parsed


@cli.group("operations")
def operations_group() -> None:
    """Inspect and execute typed SPECTRA operations."""


@operations_group.command("list")
@click.option("--group", "group_name", help="Filter by operation group.")
@click.option("--executable/--all", "executable", default=None, help="Filter to locally executable operations.")
@click.option("--schema", "include_schema", is_flag=True, help="Include request and result JSON schemas.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def operations_list(group_name: str | None, executable: bool | None, include_schema: bool, output_override: str | None) -> None:
    """List registered operation definitions."""
    registry = _operation_registry()
    rows = [definition.metadata(include_schema=include_schema) for definition in registry.list(group=group_name, executable=executable)]
    output = output_override.lower() if output_override else _context().output
    _emit(_redact(rows), output)


@operations_group.command("show")
@click.argument("operation_id")
@click.option("--schema", "include_schema", is_flag=True, help="Include request and result JSON schemas.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def operations_show(operation_id: str, include_schema: bool, output_override: str | None) -> None:
    """Show one operation definition."""
    try:
        payload = _operation_registry().get(operation_id).metadata(include_schema=include_schema)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    output = output_override.lower() if output_override else _context().output
    _emit(_redact(payload), output)


@operations_group.command("schema")
@click.argument("operation_id")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def operations_schema(operation_id: str, output_override: str | None) -> None:
    """Print JSON schemas for one operation."""
    try:
        payload = _operation_registry().schema(operation_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    output = output_override.lower() if output_override else _context().output
    _emit(_redact(payload), output)


@operations_group.command("run")
@click.argument("operation_id")
@click.option("--arguments", "arguments_json", default="{}", show_default=True, help="JSON object or @file containing operation arguments.")
@click.option("--idempotency-key", help="Caller-provided operation idempotency key.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def operations_run(operation_id: str, arguments_json: str, idempotency_key: str | None, output_override: str | None) -> None:
    """Validate and run one locally executable operation."""
    try:
        from ..operations.models import OperationEnvelope
        from ..operations.registry import OperationUnavailable
    except ImportError as exc:
        raise click.ClickException("Unavailable capability: operation registry requires pydantic v2") from exc
    context = _context()
    arguments = _parse_operation_arguments(arguments_json)
    envelope = OperationEnvelope(
        operation_id=operation_id,
        arguments=arguments,
        dry_run=context.dry_run,
        idempotency_key=idempotency_key,
    )
    started_at = datetime.now(timezone.utc).isoformat()
    audit_id = _create_operation_audit(
        context,
        source="operations.run",
        request_text=None,
        operation_id=operation_id,
        status="running",
        started_at=started_at,
        envelope=envelope.model_dump(mode="json"),
        planned_command=_operation_canonical_argv(context, operation_id, arguments),
        actual_argv=_operation_canonical_argv(context, operation_id, arguments),
    )
    try:
        result = _operation_registry().execute(envelope, context)
    except KeyError as exc:
        _finish_operation_audit(context, audit_id, status="failed", error={"category": "unknown_operation", "message": str(exc)})
        raise click.ClickException(str(exc)) from exc
    except OperationUnavailable as exc:
        _finish_operation_audit(context, audit_id, status="unavailable", error={"category": "unavailable", "message": str(exc)})
        raise click.ClickException(f"Unavailable capability: {exc}") from exc
    except click.ClickException as exc:
        _finish_operation_audit(context, audit_id, status="failed", error={"category": "execution", "message": exc.format_message()})
        raise
    except Exception as exc:
        _finish_operation_audit(context, audit_id, status="failed", error={"category": "execution", "message": str(exc)})
        raise click.ClickException(f"Operation failed: {exc}") from exc
    output = output_override.lower() if output_override else context.output
    payload = result.model_dump(mode="json")
    _finish_operation_audit(
        context,
        audit_id,
        status=result.status,
        result=payload.get("result"),
        error=payload.get("error"),
    )
    _emit(_redact(payload), output)
    if result.error is not None:
        raise click.exceptions.Exit(result.error.code)


@cli.group("agent")
def agent_group() -> None:
    """Plan typed SPECTRA operations from concise operator requests."""


@agent_group.command("plan")
@click.argument("request", required=False)
@click.option("--file", "request_file", type=click.Path(path_type=Path), help="Read the request text from a UTF-8 file.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def agent_plan(request: str | None, request_file: Path | None, output_override: str | None) -> None:
    """Plan a validated operation without executing it or contacting Telegram."""
    if request and request_file:
        raise click.UsageError("Provide REQUEST or --file, not both.")
    if request_file:
        try:
            request = request_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise click.ClickException(f"Unable to read request file {request_file}: {exc}") from exc
    if request is None:
        if click.get_text_stream("stdin").isatty():
            raise click.UsageError("Provide REQUEST or --file.")
        request = click.get_text_stream("stdin").read()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        from ..operations.planner import OperationPlanner, PlanningError
        plan = OperationPlanner(_operation_registry()).plan(request)
    except PlanningError as exc:
        _create_operation_audit(
            _context(),
            source="agent.plan",
            request_text=request,
            operation_id=None,
            status="failed",
            started_at=started_at,
            error={"category": "planning", "message": str(exc)},
        )
        raise click.ClickException(str(exc)) from exc
    context = _context()
    audit_id = _create_operation_audit(
        context,
        source="agent.plan",
        request_text=request,
        operation_id=plan.request.operation_id,
        status="planned",
        started_at=started_at,
        envelope=plan.request.model_dump(mode="json"),
        planned_command=_operation_canonical_argv(context, plan.request.operation_id, plan.request.arguments),
    )
    output = output_override.lower() if output_override else _context().output
    payload = plan.as_dict(request.strip())
    payload["audit_id"] = audit_id
    _emit(_redact(payload), output)


@agent_group.command("run")
@click.argument("request", required=False)
@click.option("--file", "request_file", type=click.Path(path_type=Path), help="Read the request text from a UTF-8 file.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def agent_run(request: str | None, request_file: Path | None, output_override: str | None) -> None:
    """Plan and execute one allowlisted local operation, recording the audit trail."""
    if request and request_file:
        raise click.UsageError("Provide REQUEST or --file, not both.")
    if request_file:
        try:
            request = request_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise click.ClickException(f"Unable to read request file {request_file}: {exc}") from exc
    if request is None:
        if click.get_text_stream("stdin").isatty():
            raise click.UsageError("Provide REQUEST or --file.")
        request = click.get_text_stream("stdin").read()
    context = _context()
    started_at = datetime.now(timezone.utc).isoformat()
    
    from ..db.spectra_db import SpectraDB
    import getpass
    db = SpectraDB(context.db_path)
    actor = getpass.getuser() or "unknown"

    try:
        from ..operations.planner import OperationPlanner, PlanningError
        plan = OperationPlanner(_operation_registry()).plan(request)
    except PlanningError as exc:
        _create_operation_audit(context, source="agent.run", request_text=request, operation_id=None, status="failed", started_at=started_at, error={"category": "planning", "message": str(exc)})
        raise click.ClickException(str(exc)) from exc
    definition = _operation_registry().get(plan.request.operation_id)
    envelope = plan.request.model_copy(update={"dry_run": context.dry_run})
    audit_id = _create_operation_audit(
        context,
        source="agent.run",
        request_text=request,
        operation_id=plan.request.operation_id,
        status="running",
        started_at=started_at,
        envelope=envelope.model_dump(mode="json"),
        planned_command=_operation_canonical_argv(context, plan.request.operation_id, plan.request.arguments),
        actual_argv=_operation_canonical_argv(context, plan.request.operation_id, plan.request.arguments),
    )
    
    # Save audit log to main DB
    from ..operations.models import OperationResult
    db.save_operation(envelope, OperationResult(operation_id=envelope.operation_id, status="running"))
    db.save_audit_log(operation_id=envelope.operation_id, action="execute_planned", user=actor, details={"request": request})

    if definition.handler is None:
        _finish_operation_audit(context, audit_id, status="unavailable", error={"category": "unavailable", "message": f"Operation has no local executor: {plan.request.operation_id}"})
        raise click.ClickException(f"Unavailable capability: Operation has no local executor: {plan.request.operation_id}")
    if definition.destructive and not context.dry_run and not context.yes:
        _finish_operation_audit(context, audit_id, status="failed", error={"category": "confirmation", "message": "Destructive operation requires --yes."})
        raise click.ClickException("Destructive operation requires --yes.")
    try:
        result = _operation_registry().execute(envelope, context)
        db.save_operation(envelope, result)
    except click.ClickException as exc:
        _finish_operation_audit(context, audit_id, status="failed", error={"category": "execution", "message": exc.format_message()})
        raise
    except Exception as exc:
        _finish_operation_audit(context, audit_id, status="failed", error={"category": "execution", "message": str(exc)})
        raise click.ClickException(f"Operation failed: {exc}") from exc
    payload = result.model_dump(mode="json")
    _finish_operation_audit(context, audit_id, status=result.status, result=payload.get("result"), error=payload.get("error"))
    output = output_override.lower() if output_override else context.output
    payload["audit_id"] = audit_id
    _emit(_redact(payload), output)
    if result.error is not None:
        raise click.exceptions.Exit(result.error.code)


@agent_group.group("audit")
def agent_audit_group() -> None:
    """Inspect redacted agent and operation audit records."""


@agent_audit_group.command("list")
@click.option("--limit", type=click.IntRange(min=1, max=1000), default=50, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def agent_audit_list(limit: int, output_override: str | None) -> None:
    """List recent redacted agent and operation audit records."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_operation_audit_rows(context, limit=limit), output)


@agent_audit_group.command("show")
@click.argument("audit_id")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def agent_audit_show(audit_id: str, output_override: str | None) -> None:
    """Show one redacted audit record."""
    context = _context()
    records = _operation_audit_rows(context, limit=1, audit_id=audit_id)
    if not records:
        raise click.ClickException(f"Audit record not found: {audit_id}")
    output = output_override.lower() if output_override else context.output
    _emit(records[0], output)


@cli.command()
@click.option("--capabilities", is_flag=True, help="Check optional runtime capabilities.")
def doctor(capabilities: bool) -> None:
    """Check configuration, runtime, and optional capabilities."""
    context = _context()
    checks = _operation_result("doctor", {"capabilities": capabilities}, context)["checks"]
    _emit(_redact(checks), context.output)
    if not all(item.get("ok", True) for item in checks.values() if isinstance(item, dict)):
        raise click.exceptions.Exit(8)


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _graphql_available() -> bool:
    return _module_available("tgarchive.api.graphql") and _module_available("graphene") and _module_available("flask_graphql")


@cli.group()
def config() -> None:
    """Inspect and validate SPECTRA configuration."""


@config.command("path")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_path(output_override: str | None) -> None:
    """Print the active configuration path."""
    output = output_override.lower() if output_override else _context().output
    _emit({"path": str(_context().config_path)}, output)


@config.command("show")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_show(output_override: str | None) -> None:
    """Print the active configuration with secrets redacted."""
    context = _context()
    cfg = _load_config(context.config_path)
    output = output_override.lower() if output_override else context.output
    _emit(_redact(cfg.data), output)


@config.command("get")
@click.argument("path")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_get(path: str, output_override: str | None) -> None:
    """Print one dotted configuration value with secrets redacted."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_operation_result("config.get", {"path": path}, context), output)


@config.command("set")
@click.argument("path")
@click.argument("value")
@click.option("--raw", is_flag=True, help="Store VALUE as a string instead of parsing it as JSON.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_set(path: str, value: str, raw: bool, output_override: str | None) -> None:
    """Set one dotted configuration value."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to modify config in non-interactive mode without --yes")
    data = _read_config_document(context.config_path)
    parsed_value = _parse_config_value(value, raw)
    old_value: Any = None
    existed = True
    try:
        old_value = _get_config_path(data, path)
    except click.ClickException:
        existed = False
    _set_config_path(data, path, parsed_value)
    if not context.dry_run:
        _write_json_file(context.config_path, data)
    output = output_override.lower() if output_override else context.output
    _emit(_redact({
        "path": path,
        "changed": not context.dry_run,
        "dry_run": context.dry_run,
        "existed": existed,
        "old_value": _redact(old_value, path),
        "value": _redact(parsed_value, path),
        "config": str(context.config_path),
    }), output)


@config.command("unset")
@click.argument("path")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_unset(path: str, output_override: str | None) -> None:
    """Remove one dotted configuration value."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to modify config in non-interactive mode without --yes")
    data = _read_config_document(context.config_path)
    removed_value = _unset_config_path(data, path)
    if not context.dry_run:
        _write_json_file(context.config_path, data)
    output = output_override.lower() if output_override else context.output
    _emit(_redact({
        "path": path,
        "changed": not context.dry_run,
        "dry_run": context.dry_run,
        "removed_value": _redact(removed_value, path),
        "config": str(context.config_path),
    }), output)


@config.group("profile")
def config_profile_group() -> None:
    """Manage named local configuration profiles."""


@config_profile_group.command("list")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_profile_list(output_override: str | None) -> None:
    """List stored configuration profiles."""
    context = _context()
    data = _read_config_document(context.config_path)
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        raise click.ClickException("Config profiles must be an object")
    rows = [{"name": name, "active": data.get("active_profile") == name} for name in sorted(profiles)]
    output = output_override.lower() if output_override else context.output
    _emit(rows, output)


@config_profile_group.command("show")
@click.argument("name")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_profile_show(name: str, output_override: str | None) -> None:
    """Show one stored configuration profile with secrets redacted."""
    context = _context()
    data = _read_config_document(context.config_path)
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict) or name not in profiles:
        raise click.ClickException(f"Profile not found: {name}")
    output = output_override.lower() if output_override else context.output
    _emit(_redact({"name": name, "profile": profiles[name]}), output)


@config_profile_group.command("add")
@click.argument("name")
@click.option("--from-file", "from_file", type=click.Path(path_type=Path), help="Load profile data from a JSON file instead of the active config.")
@click.option("--replace", is_flag=True, help="Replace an existing profile.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_profile_add(name: str, from_file: Path | None, replace: bool, output_override: str | None) -> None:
    """Store a named configuration profile."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to modify config profiles in non-interactive mode without --yes")
    data = _read_config_document(context.config_path)
    profiles = data.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        raise click.ClickException("Config profiles must be an object")
    existed = name in profiles
    if existed and not replace:
        raise click.ClickException(f"Profile already exists: {name}")
    profile_data = _read_json_file(from_file) if from_file else _snapshot_profile_data(data)
    if not context.dry_run:
        profiles[name] = profile_data
        _write_json_file(context.config_path, data)
    output = output_override.lower() if output_override else context.output
    _emit(_redact({"name": name, "changed": not context.dry_run, "dry_run": context.dry_run, "replaced": existed}), output)


@config_profile_group.command("use")
@click.argument("name")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_profile_use(name: str, output_override: str | None) -> None:
    """Apply a named profile to the active configuration."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to switch config profiles in non-interactive mode without --yes")
    data = _read_config_document(context.config_path)
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict) or name not in profiles:
        raise click.ClickException(f"Profile not found: {name}")
    profile_data = profiles[name]
    if not isinstance(profile_data, dict):
        raise click.ClickException(f"Profile is not a JSON object: {name}")
    if not context.dry_run:
        preserved_profiles = data.get("profiles", {})
        data.clear()
        data.update(profile_data)
        data["profiles"] = preserved_profiles
        data["active_profile"] = name
        _write_json_file(context.config_path, data)
    output = output_override.lower() if output_override else context.output
    _emit({"name": name, "changed": not context.dry_run, "dry_run": context.dry_run, "config": str(context.config_path)}, output)


@config_profile_group.command("remove")
@click.argument("name")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_profile_remove(name: str, output_override: str | None) -> None:
    """Remove a stored configuration profile."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to remove config profiles in non-interactive mode without --yes")
    data = _read_config_document(context.config_path)
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict) or name not in profiles:
        raise click.ClickException(f"Profile not found: {name}")
    if not context.dry_run:
        profiles.pop(name)
        if data.get("active_profile") == name:
            data.pop("active_profile", None)
        _write_json_file(context.config_path, data)
    output = output_override.lower() if output_override else context.output
    _emit({"name": name, "changed": not context.dry_run, "dry_run": context.dry_run, "config": str(context.config_path)}, output)


@config.command("migrate-env")
@click.option("--prefix", default="SPECTRA", show_default=True, help="Environment variable prefix.")
@click.option("--env-file", type=click.Path(path_type=Path), help="Write extracted environment assignments to this file.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_migrate_env(prefix: str, env_file: Path | None, output_override: str | None) -> None:
    """Replace inline sensitive values with env:NAME references."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to migrate config secrets in non-interactive mode without --yes")
    data = _read_config_document(context.config_path)
    env_rows: list[str] = []
    migrated = _migrate_env_refs(data, prefix, [], env_rows)
    if not isinstance(migrated, dict):
        raise click.ClickException("Migrated config is not a JSON object")
    if not context.dry_run:
        _write_json_file(context.config_path, migrated)
        if env_file:
            try:
                env_file.parent.mkdir(parents=True, exist_ok=True)
                env_file.write_text("\n".join(env_rows) + ("\n" if env_rows else ""), encoding="utf-8")
            except OSError as exc:
                raise click.ClickException(f"Unable to write env file {env_file}: {exc}") from exc
    output = output_override.lower() if output_override else context.output
    _emit({
        "changed": not context.dry_run,
        "dry_run": context.dry_run,
        "config": str(context.config_path),
        "env_file": str(env_file) if env_file else None,
        "migrated_values": len(env_rows),
        "env_vars": [row.split("=", 1)[0] for row in env_rows],
    }, output)


@config.command("validate")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_validate(output_override: str | None) -> None:
    """Validate the active configuration without modifying it."""
    context = _context()
    cfg = _load_config(context.config_path)
    accounts = cfg.data.get("accounts", [])
    valid = isinstance(accounts, list) and all(
        isinstance(account, dict)
        and account.get("api_id")
        and account.get("api_hash")
        and account.get("session_name")
        for account in accounts
    )
    result = {"valid": valid, "path": str(context.config_path), "accounts": len(accounts) if isinstance(accounts, list) else 0}
    output = output_override.lower() if output_override else context.output
    _emit(result, output)
    if not valid:
        raise click.exceptions.Exit(3)


@config.command("set-forward-dest")
@click.argument("destination_id")
def config_set_forward_dest(destination_id: str) -> None:
    """Set the default forwarding destination ID."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to modify config in non-interactive mode without --yes")
    cfg = _load_config(context.config_path)
    cfg.default_forwarding_destination_id = destination_id
    cfg.save()
    _emit({"default_forwarding_destination_id": destination_id}, context.output)


@config.command("view-forward-dest")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def config_view_forward_dest(output_override: str | None) -> None:
    """View the default forwarding destination ID."""
    context = _context()
    cfg = _load_config(context.config_path)
    output = output_override.lower() if output_override else context.output
    _emit({"default_forwarding_destination_id": cfg.default_forwarding_destination_id}, output)


@cli.group("account")
def account_group() -> None:
    """Manage Telegram accounts without exposing credentials."""


@account_group.command("list")
def account_list() -> None:
    """List configured accounts and safe metadata."""
    context = _context()
    cfg = _load_config(context.config_path)
    accounts = []
    for account in cfg.data.get("accounts", []):
        accounts.append({
            "session_name": account.get("session_name"),
            "phone_number": account.get("phone_number") or account.get("phone"),
            "api_id": account.get("api_id"),
            "authorized_session": _account_has_session(account.get("session_name")),
        })
    _emit(accounts, context.output)


@account_group.command("show")
@click.argument("account")
def account_show(account: str) -> None:
    """Show one configured account with sensitive values redacted."""
    context = _context()
    cfg = _load_config(context.config_path)
    for item in cfg.data.get("accounts", []):
        candidates = {
            str(item.get("session_name", "")),
            str(item.get("phone_number", "")),
            str(item.get("phone", "")),
        }
        if account in candidates:
            payload = dict(item)
            payload["authorized_session"] = _account_has_session(item.get("session_name"))
            _emit(_redact(payload), context.output)
            return
    raise click.ClickException(f"Account not found: {account}")


@account_group.command("add")
@click.option("--phone", required=True, help="Telegram account phone number.")
@click.option("--api-id", type=click.IntRange(min=1), required=True, help="Telegram application API ID.")
@click.option("--api-hash", required=True, help="Telegram application API hash.")
@click.option("--session-name", help="Session name to store. Defaults to spectra_<digits-from-phone>.")
@click.option("--inactive", is_flag=True, help="Add the account with active=false.")
@click.option("--replace", is_flag=True, help="Replace an existing account with the same session name.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def account_add(phone: str, api_id: int, api_hash: str, session_name: str | None, inactive: bool, replace: bool, output_override: str | None) -> None:
    """Add or replace a Telegram account configuration."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to modify config in non-interactive mode without --yes")
    data = _read_config_document(context.config_path)
    new_account = {
        "api_id": api_id,
        "api_hash": api_hash,
        "session_name": session_name or _session_name_from_phone(phone),
        "phone_number": phone,
        "active": not inactive,
    }
    accounts = data.setdefault("accounts", [])
    if not isinstance(accounts, list):
        raise click.ClickException("Config accounts must be a list")
    existing = _find_account_config(data, str(new_account["session_name"]))
    if existing is not None and not replace:
        raise click.ClickException(f"Account already exists: {new_account['session_name']}")
    if not context.dry_run:
        _upsert_account_config(data, new_account)
        _write_json_file(context.config_path, data)
    output = output_override.lower() if output_override else context.output
    _emit(_redact({
        "changed": not context.dry_run,
        "dry_run": context.dry_run,
        "replaced": existing is not None,
        "account": new_account,
        "config": str(context.config_path),
    }), output)


@account_group.command("login")
@click.argument("account", required=False)
@click.option("--phone", help="Phone number for a new or existing account.")
@click.option("--api-id", type=click.IntRange(min=1), help="Telegram application API ID.")
@click.option("--api-hash", help="Telegram application API hash.")
@click.option("--session-name", help="Session name to create or update when ACCOUNT is not already configured.")
@click.option("--code", help="Telegram login code for non-interactive completion.")
@click.option("--password-env", help="Environment variable containing the Telegram 2FA password.")
@click.option("--force", is_flag=True, help="Send a new code even if the current session is already authorized.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def account_login(account: str | None, phone: str | None, api_id: int | None, api_hash: str | None, session_name: str | None, code: str | None, password_env: str | None, force: bool, output_override: str | None) -> None:
    """Authorize a Telegram account with phone, code, and optional 2FA."""
    context = _context()
    data = _read_config_document(context.config_path)
    selected = _find_account_config(data, account)
    if selected is None:
        login_phone = phone
        login_session_name = session_name or (_session_name_from_phone(login_phone) if login_phone else None)
        selected = {
            "session_name": login_session_name,
            "phone_number": login_phone,
            "api_id": api_id,
            "api_hash": api_hash,
        }
    else:
        selected = dict(selected)
        if phone:
            selected["phone_number"] = phone
        if api_id:
            selected["api_id"] = api_id
        if api_hash:
            selected["api_hash"] = api_hash
        if session_name:
            selected["session_name"] = session_name
    if not selected.get("phone_number") and selected.get("phone"):
        selected["phone_number"] = selected.get("phone")
    if not selected.get("session_name") and selected.get("phone_number"):
        selected["session_name"] = _session_name_from_phone(str(selected["phone_number"]))
    missing = [key for key in ("session_name", "phone_number", "api_id", "api_hash") if not selected.get(key)]
    if missing:
        raise click.ClickException(f"Missing account login fields: {', '.join(missing)}")
    password = None
    if password_env:
        password = os.environ.get(password_env)
        if password is None:
            raise click.ClickException(f"2FA password environment variable is not set: {password_env}")
    if context.dry_run:
        result = {
            "authorized": False,
            "dry_run": True,
            "session_name": selected.get("session_name"),
            "phone_number": selected.get("phone_number"),
            "config": str(context.config_path),
        }
    else:
        result = asyncio.run(
            _login_account_async(
                selected,
                code=code,
                password=password,
                force=force,
                non_interactive=context.non_interactive,
            )
        )
        _upsert_account_config(data, selected)
        _write_json_file(context.config_path, data)
        result["dry_run"] = False
        result["config"] = str(context.config_path)
    output = output_override.lower() if output_override else context.output
    _emit(_redact(result), output)


@account_group.command("logout")
@click.argument("account")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def account_logout(account: str, output_override: str | None) -> None:
    """Remove local Telegram session files for an account."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to remove session files in non-interactive mode without --yes")
    data = _read_config_document(context.config_path)
    selected = _find_account_config(data, account)
    if selected is None:
        raise click.ClickException(f"Account not found: {account}")
    session_name = str(selected.get("session_name") or "")
    if not session_name:
        raise click.ClickException(f"Account does not have a session name: {account}")
    removed = [] if context.dry_run else _remove_account_session_files(session_name)
    output = output_override.lower() if output_override else context.output
    _emit({
        "account": session_name,
        "changed": bool(removed) and not context.dry_run,
        "dry_run": context.dry_run,
        "removed_session_files": removed,
        "authorized_session": _account_has_session(session_name),
    }, output)


@account_group.command("remove")
@click.argument("account")
@click.option("--delete-session", is_flag=True, help="Also remove local .session and .session-journal files.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def account_remove(account: str, delete_session: bool, output_override: str | None) -> None:
    """Remove an account from the active configuration."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to modify config in non-interactive mode without --yes")
    data = _read_config_document(context.config_path)
    accounts = data.get("accounts", [])
    if not isinstance(accounts, list):
        raise click.ClickException("Config accounts must be a list")
    kept = []
    removed_account: dict[str, Any] | None = None
    for item in accounts:
        if isinstance(item, dict) and removed_account is None and _account_identifier_matches(item, account):
            removed_account = item
            continue
        kept.append(item)
    if removed_account is None:
        raise click.ClickException(f"Account not found: {account}")
    removed_files: list[str] = []
    if delete_session and not context.dry_run:
        session_name = str(removed_account.get("session_name") or "")
        if session_name:
            removed_files = _remove_account_session_files(session_name)
    if not context.dry_run:
        data["accounts"] = kept
        _write_json_file(context.config_path, data)
    output = output_override.lower() if output_override else context.output
    _emit(_redact({
        "changed": not context.dry_run,
        "dry_run": context.dry_run,
        "removed_account": {
            "session_name": removed_account.get("session_name"),
            "phone_number": removed_account.get("phone_number") or removed_account.get("phone"),
            "api_id": removed_account.get("api_id"),
        },
        "removed_session_files": removed_files,
        "config": str(context.config_path),
    }), output)


@account_group.command("stats")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def account_stats(output_override: str | None) -> None:
    """Summarize configured account and local session state."""
    context = _context()
    data = _read_config_document(context.config_path)
    accounts = data.get("accounts", [])
    if not isinstance(accounts, list):
        raise click.ClickException("Config accounts must be a list")
    total = 0
    active = 0
    inactive = 0
    authorized = 0
    missing_credentials = 0
    for item in accounts:
        if not isinstance(item, dict):
            continue
        total += 1
        if item.get("active", True):
            active += 1
        else:
            inactive += 1
        if _account_has_session(item.get("session_name")):
            authorized += 1
        if not all(item.get(key) for key in ("api_id", "api_hash", "session_name")):
            missing_credentials += 1
    output = output_override.lower() if output_override else context.output
    _emit({
        "total": total,
        "active": active,
        "inactive": inactive,
        "authorized_sessions": authorized,
        "missing_credentials": missing_credentials,
        "config": str(context.config_path),
    }, output)


@account_group.command("health")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def account_health(output_override: str | None) -> None:
    """Check local account configuration and session-file health."""
    context = _context()
    data = _read_config_document(context.config_path)
    accounts = data.get("accounts", [])
    if not isinstance(accounts, list):
        raise click.ClickException("Config accounts must be a list")
    rows = []
    for item in accounts:
        if not isinstance(item, dict):
            continue
        session_name = item.get("session_name")
        missing = [key for key in ("api_id", "api_hash", "session_name") if not item.get(key)]
        rows.append({
            "session_name": session_name,
            "phone_number": item.get("phone_number") or item.get("phone"),
            "active": item.get("active", True),
            "authorized_session": _account_has_session(session_name),
            "missing_fields": missing,
            "healthy": not missing and _account_has_session(session_name),
        })
    output = output_override.lower() if output_override else context.output
    _emit(_redact(rows), output)


@account_group.command("test")
def account_test() -> None:
    """Test configured Telegram accounts for connectivity."""
    _run_legacy("handle_accounts", list=False, reset=False, test=True, import_accs=False)


@account_group.command("reset-usage")
def account_reset_usage() -> None:
    """Reset account usage counters."""
    if _context().non_interactive and not _context().yes:
        raise click.ClickException("Refusing to reset usage counters in non-interactive mode without --yes")
    _run_legacy("handle_accounts", list=False, reset=True, test=False, import_accs=False)


@account_group.command("import")
def account_import() -> None:
    """Import accounts from gen_config.py into the active config."""
    if _context().non_interactive and not _context().yes:
        raise click.ClickException("Refusing to modify config in non-interactive mode without --yes")
    _run_legacy("handle_accounts", list=False, reset=False, test=False, import_accs=True)


@cli.group("channel")
def channel_group() -> None:
    """Inspect and download Telegram channels."""


@cli.group("task")
def task_group() -> None:
    """Inspect locally detached SPECTRA tasks."""


@task_group.command("list")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def task_list(output_override: str | None) -> None:
    """List locally recorded detached tasks."""
    context = _context()
    records = [_enrich_task_record(record) for record in _latest_task_records(context)]
    output = output_override.lower() if output_override else context.output
    _emit(records, output)


@task_group.command("show")
@click.argument("task_id")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def task_show(task_id: str, output_override: str | None) -> None:
    """Show one locally recorded detached task."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_operation_result("task.show", {"task_id": task_id, "tail": 10}, context)["record"], output)


@task_group.command("events")
@click.argument("task_id")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def task_events(task_id: str, output_override: str | None) -> None:
    """List persisted events for one detached task."""
    context = _context()
    events = [record for record in _load_task_records(context) if record.get("id") == task_id]
    if not events:
        raise click.ClickException(f"Task not found: {task_id}")
    output = output_override.lower() if output_override else context.output
    _emit([_redact(event) for event in events], output)


@task_group.command("watch")
@click.argument("task_id")
@click.option("--tail", type=click.IntRange(min=0), default=20, show_default=True, help="Include the last N log lines in each status snapshot.")
@click.option("--interval", type=click.FloatRange(min=0.25), default=DEFAULT_TASK_WATCH_INTERVAL, show_default=True, help="Seconds between live status snapshots.")
@click.option("--once", is_flag=True, help="Print one status snapshot and exit.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def task_watch(task_id: str, tail: int, interval: float, once: bool, output_override: str | None) -> None:
    """Follow a detached task log and status."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    while True:
        snapshot = _enrich_task_record(_find_task_record(context, task_id), tail=tail)
        if output == "jsonl" and not once:
            click.echo(json.dumps(snapshot, default=str))
        else:
            _emit(snapshot, output)
        if once or not snapshot.get("running"):
            return
        time.sleep(interval)


@task_group.command("cancel")
@click.argument("task_id")
@click.option("--wait", "wait_seconds", type=click.FloatRange(min=0), default=DEFAULT_TASK_CANCEL_WAIT, show_default=True, help="Seconds to wait for the process to exit after SIGINT.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def task_cancel(task_id: str, wait_seconds: float, output_override: str | None) -> None:
    """Cancel a recorded detached task with SIGINT."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to cancel a task in non-interactive mode without --yes")
    record = _find_task_record(context, task_id)
    was_running = _pid_running(record.get("pid"))
    if was_running and not context.dry_run:
        _interrupt_process_group(record.get("pid"))
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline and _pid_running(record.get("pid")):
            time.sleep(min(DEFAULT_TASK_WATCH_INTERVAL, max(deadline - time.monotonic(), 0.0)))
    running = _pid_running(record.get("pid"))
    status = "running" if running else "cancelled"
    event = {
        "id": task_id,
        "kind": record.get("kind"),
        "status": "cancel-requested" if context.dry_run else status,
        "pid": record.get("pid"),
        "cancel_requested_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": context.dry_run,
        "log_path": record.get("log_path"),
        "output_dir": record.get("output_dir"),
        "argv": record.get("argv"),
    }
    if not context.dry_run:
        _append_task_record(context, event)
    output = output_override.lower() if output_override else context.output
    _emit(_redact({
        "id": task_id,
        "pid": record.get("pid"),
        "was_running": was_running,
        "running": running,
        "status": event["status"],
        "dry_run": context.dry_run,
        "task_registry": str(_task_registry_path(context)),
    }), output)


@task_group.command("recover")
@click.argument("task_id", required=False)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def task_recover(task_id: str | None, output_override: str | None) -> None:
    """Persist recovered task statuses after process exits or restarts."""
    context = _context()
    records = _latest_task_records(context)
    if task_id:
        records = [record for record in records if record.get("id") == task_id]
        if not records:
            raise click.ClickException(f"Task not found: {task_id}")
    recovered: list[dict[str, Any]] = []
    for record in records:
        status = _recovery_status(record)
        if not status:
            continue
        event = {
            "id": record.get("id"),
            "kind": record.get("kind"),
            "status": status,
            "pid": record.get("pid"),
            "recovered_at": datetime.now(timezone.utc).isoformat(),
            "log_path": record.get("log_path"),
            "output_dir": record.get("output_dir"),
            "argv": record.get("argv"),
        }
        if not context.dry_run:
            _append_task_record(context, event)
        recovered.append(_redact(event))
    output = output_override.lower() if output_override else context.output
    _emit({
        "dry_run": context.dry_run,
        "recovered": recovered,
        "count": len(recovered),
        "task_registry": str(_task_registry_path(context)),
    }, output)


@cli.group("archive")
def archive_group() -> None:
    """Archive Telegram channels and groups."""


@archive_group.command("channel")
@click.argument("entity")
@click.option("--auto", is_flag=True, help="Select an available account automatically.")
@click.option("--no-media", is_flag=True)
@click.option("--no-avatars", is_flag=True)
@click.option("--no-topics", is_flag=True)
def archive_channel(entity: str, auto: bool, no_media: bool, no_avatars: bool, no_topics: bool) -> None:
    """Archive ENTITY into the configured database."""
    _run_legacy(
        "handle_archive",
        entity=entity,
        auto=auto,
        no_media=no_media,
        no_avatars=no_avatars,
        no_topics=no_topics,
    )


@cli.group("forward", invoke_without_command=True)
@click.pass_context
@_forwarding_options
def forward_group(ctx: click.Context, **options: Any) -> None:
    """Forward messages or traverse channels through legacy production services."""
    if ctx.invoked_subcommand is not None:
        return
    _run_forward_legacy(**options)


@forward_group.command("messages")
@_forwarding_options
def forward_messages(**options: Any) -> None:
    """Forward messages between Telegram chats or run recovery sweeps."""
    _run_forward_legacy(**options)


@forward_group.command("dialogs")
@_forwarding_options
def forward_dialogs(**options: Any) -> None:
    """Forward media from all accessible dialogs."""
    options["all_dialogs"] = True
    _run_forward_legacy(**options)


@forward_group.command("recover")
@_forwarding_options
def forward_recover(**options: Any) -> None:
    """Recover content from all locally known accessible channels."""
    options["total_mode"] = True
    _run_forward_legacy(**options)


@forward_group.command("traverse")
@_forwarding_options
def forward_traverse(**options: Any) -> None:
    """Traverse channels from a seed file and download discovered files."""
    if not options.get("channels_file") or not options.get("output_dir"):
        raise click.ClickException("forward traverse requires --channels-file and --output-dir")
    _run_forward_legacy(**options)


@forward_group.command("schedule")
@click.option("--channel-id", type=click.IntRange(min=1), required=True)
@click.option("--destination", required=True)
@click.option("--schedule", "schedule_expr", required=True, help="Cron-style schedule.")
def forward_schedule(channel_id: int, destination: str, schedule_expr: str) -> None:
    """Add a channel forwarding schedule."""
    if _context().dry_run:
        _emit({
            "dry_run": True,
            "schedule_command": "add-channel-forward",
            "channel_id": channel_id,
            "destination": destination,
            "schedule": schedule_expr,
        }, _context().output)
        return
    _run_legacy(
        "handle_schedule",
        schedule_command="add-channel-forward",
        channel_id=channel_id,
        destination=destination,
        schedule=schedule_expr,
    )


@forward_group.command("status")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def forward_status(output_override: str | None) -> None:
    """Inspect local forwarding schedules, queues, and recent stats."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_forwarding_status(context)), output)


@cli.group("scheduler")
def scheduler_group() -> None:
    """Manage scheduled SPECTRA jobs."""


@scheduler_group.command("add")
@click.option("--name", required=True, help="Name of the scheduled job.")
@click.option("--schedule", "schedule_expr", required=True, help="Cron-style schedule expression.")
@click.option("--command", "job_command", required=True, help="Command to execute.")
def scheduler_add(name: str, schedule_expr: str, job_command: str) -> None:
    """Add a scheduled command job."""
    _run_legacy("handle_schedule", schedule_command="add", name=name, schedule=schedule_expr, command=job_command)


@scheduler_group.command("list")
def scheduler_list() -> None:
    """List scheduled jobs."""
    _run_legacy("handle_schedule", schedule_command="list")


@scheduler_group.command("status")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def scheduler_status(output_override: str | None) -> None:
    """Inspect persisted scheduler state without starting the daemon."""
    context = _context()
    state_path = _scheduler_state_path(context)
    state = _read_scheduler_state(state_path)
    schedules = _scheduler_db_schedules(context)
    payload = {
        "state_file": str(state_path),
        "state_file_exists": state_path.exists(),
        "jobs": state.get("jobs", []) if isinstance(state.get("jobs", []), list) else [],
        "channel_forward_schedules": schedules["channel_forward"],
        "file_forward_schedules": schedules["file_forward"],
    }
    output = output_override.lower() if output_override else context.output
    _emit(_redact(payload), output)


@scheduler_group.command("show")
@click.argument("name")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def scheduler_show(name: str, output_override: str | None) -> None:
    """Show one persisted generic scheduler job by name."""
    context = _context()
    state_path = _scheduler_state_path(context)
    state = _read_scheduler_state(state_path)
    jobs = state.get("jobs", [])
    if not isinstance(jobs, list):
        raise click.ClickException(f"Scheduler state jobs must be a list: {state_path}")
    for job in jobs:
        if isinstance(job, dict) and job.get("name") == name:
            output = output_override.lower() if output_override else context.output
            _emit(_redact({"state_file": str(state_path), "job": job}), output)
            return
    raise click.ClickException(f"Scheduler job not found: {name}")


@scheduler_group.command("remove")
@click.option("--name", required=True, help="Name of the scheduled job to remove.")
def scheduler_remove(name: str) -> None:
    """Remove a scheduled job."""
    if _context().non_interactive and not _context().yes:
        raise click.ClickException("Refusing to remove scheduler job in non-interactive mode without --yes")
    _run_legacy("handle_schedule", schedule_command="remove", name=name)


@scheduler_group.command("daemon")
def scheduler_daemon() -> None:
    """Run the scheduler daemon in the foreground."""
    _run_legacy("handle_schedule", schedule_command="run")


@scheduler_group.command("add-channel-forward")
@click.option("--channel-id", type=click.IntRange(min=1), required=True)
@click.option("--destination", required=True)
@click.option("--schedule", "schedule_expr", required=True)
def scheduler_add_channel_forward(channel_id: int, destination: str, schedule_expr: str) -> None:
    """Add a channel forwarding schedule."""
    _run_legacy("handle_schedule", schedule_command="add-channel-forward", channel_id=channel_id, destination=destination, schedule=schedule_expr)


@scheduler_group.command("add-file-forward")
@click.option("--source", required=True)
@click.option("--destination", required=True)
@click.option("--schedule", "schedule_expr", required=True)
@click.option("--file-types")
@click.option("--min-file-size", type=click.IntRange(min=0))
@click.option("--max-file-size", type=click.IntRange(min=0))
@click.option("--priority", type=click.IntRange(min=0), default=0, show_default=True)
def scheduler_add_file_forward(source: str, destination: str, schedule_expr: str, file_types: str | None, min_file_size: int | None, max_file_size: int | None, priority: int) -> None:
    """Add a file forwarding schedule."""
    _run_legacy(
        "handle_schedule",
        schedule_command="add-file-forward",
        source=source,
        destination=destination,
        schedule=schedule_expr,
        file_types=file_types,
        min_file_size=min_file_size,
        max_file_size=max_file_size,
        priority=priority,
    )


@scheduler_group.command("report")
@click.option("--schedule-id", type=click.IntRange(min=1), required=True)
def scheduler_report(schedule_id: int) -> None:
    """Report file forwarding queue status for a schedule."""
    _run_legacy("handle_schedule", schedule_command="report", schedule_id=schedule_id)


@cli.group("schedule", invoke_without_command=True, hidden=True)
@click.pass_context
def schedule_alias(ctx: click.Context) -> None:
    """Compatibility alias for scheduler commands."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


for _command in scheduler_group.commands.values():
    schedule_alias.add_command(_command)


@cli.group("files")
def files_group() -> None:
    """Sort and watch local files."""


@files_group.command("sort")
@click.option("--directory", type=click.Path(path_type=Path), required=True, help="Directory to watch for new files.")
@click.option("--output-directory", type=click.Path(path_type=Path), required=True, help="Directory where sorted files are moved.")
def files_sort(directory: Path, output_directory: Path) -> None:
    """Watch a directory and sort new files by type."""
    _run_legacy("handle_sort", directory=str(directory), output_directory=str(output_directory))


@files_group.command("watch")
@click.option("--directory", type=click.Path(path_type=Path), required=True, help="Directory to watch for new files.")
@click.option("--output-directory", type=click.Path(path_type=Path), required=True, help="Directory where sorted files are moved.")
def files_watch(directory: Path, output_directory: Path) -> None:
    """Watch a directory and sort new files by type."""
    _run_legacy("handle_sort", directory=str(directory), output_directory=str(output_directory))


@cli.command("sort", hidden=True)
@click.option("--directory", type=click.Path(path_type=Path), required=True)
@click.option("--output-directory", type=click.Path(path_type=Path), required=True)
def sort_alias(directory: Path, output_directory: Path) -> None:
    """Compatibility alias for files sort."""
    files_sort.callback(directory, output_directory)


@cli.group("db")
def db_group() -> None:
    """Inspect the local SPECTRA SQLite database."""


@db_group.command("stats")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def db_stats(output_override: str | None) -> None:
    """Show row counts for core database tables."""
    context = _context()
    with _connect_existing_sqlite(context.db_path) as connection:
        tables = set(_table_names(connection))
        counts = {table: _count_table_rows(connection, table) for table in CORE_DB_TABLES if table in tables}
    output = output_override.lower() if output_override else context.output
    _emit({"database": str(context.db_path), "tables": counts, "total_tables": len(counts)}, output)


@cli.group("index")
def index_group() -> None:
    """Inspect durable index projection work."""


@index_group.command("status")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_status(output_override: str | None) -> None:
    """Show pending index events and projection checkpoints."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.status", {}, context)), output)


@index_group.command("process")
@click.option("--batch-size", type=click.IntRange(min=1, max=10_000), default=100, show_default=True)
@click.option("--lease-seconds", type=click.IntRange(min=1, max=86_400), default=300, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_process(batch_size: int, lease_seconds: int, output_override: str | None) -> None:
    """Consume one bounded batch of durable index events."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.process", {
        "batch_size": batch_size,
        "lease_seconds": lease_seconds,
    }, context)), output)


@index_group.command("drain")
@click.option("--batch-size", type=click.IntRange(min=1, max=10_000), default=1000, show_default=True)
@click.option("--lease-seconds", type=click.IntRange(min=1, max=86_400), default=300, show_default=True)
@click.option("--max-batches", type=click.IntRange(min=0, max=100_000), default=0, show_default=True, help="Zero drains until empty.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_drain(batch_size: int, lease_seconds: int, max_batches: int, output_override: str | None) -> None:
    """Consume outbox batches until empty."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.drain", {
        "batch_size": batch_size,
        "lease_seconds": lease_seconds,
        "max_batches": max_batches,
    }, context)), output)


@index_group.command("watch")
@click.option("--batch-size", type=click.IntRange(min=1, max=10_000), default=1000, show_default=True)
@click.option("--lease-seconds", type=click.IntRange(min=1, max=86_400), default=300, show_default=True)
@click.option("--poll-interval", type=click.FloatRange(min=0.1, max=3600), default=0.1, show_default=True)
@click.option("--max-backoff", type=click.FloatRange(min=1, max=3600), default=60.0, show_default=True)
@click.option("--idle-exit", type=click.FloatRange(min=0), default=0.0, show_default=True, help="Exit after this many idle seconds; zero watches indefinitely.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the final summary format.")
def index_watch(batch_size: int, lease_seconds: int, poll_interval: float, max_backoff: float, idle_exit: float, output_override: str | None) -> None:
    """Continuously drain index events with bounded idle polling."""
    from ..db.index_projector import IndexProjector

    context = _context()
    projector = IndexProjector(context.db_path)
    started = time.monotonic()
    idle_since: float | None = None
    base_backoff = min(poll_interval, max_backoff)
    backoff = base_backoff
    totals = {"batches": 0, "claimed": 0, "processed": 0, "failed": 0, "worker_errors": 0}
    try:
        while True:
            try:
                result = projector.process(batch_size=batch_size, lease_seconds=lease_seconds)
            except Exception as exc:
                totals["worker_errors"] += 1
                _emit_index_watch_diagnostic(
                    "index_watch_worker_exception",
                    level="error",
                    exception_type=type(exc).__name__,
                    error=str(exc),
                    retry_seconds=backoff,
                    worker_errors=totals["worker_errors"],
                )
                time.sleep(backoff)
                backoff = min(max_backoff, max(base_backoff, backoff * 2))
                continue
            totals["batches"] += 1
            for key in ("claimed", "processed", "failed"):
                totals[key] += int(result[key])
            if result["failed"]:
                idle_since = None
                _emit_index_watch_diagnostic(
                    "index_watch_batch_failed",
                    level="error",
                    claimed=int(result["claimed"]),
                    processed=int(result["processed"]),
                    failed=int(result["failed"]),
                    failure_samples=list(result.get("failures") or [])[
                        :INDEX_WATCH_FAILURE_SAMPLE_LIMIT
                    ],
                    retry_seconds=backoff,
                )
                time.sleep(backoff)
                backoff = min(max_backoff, max(base_backoff, backoff * 2))
                continue
            backoff = base_backoff
            if result["claimed"]:
                idle_since = None
                continue
            idle_since = idle_since or time.monotonic()
            if idle_exit and time.monotonic() - idle_since >= idle_exit:
                break
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        totals["interrupted"] = True
    totals["elapsed_seconds"] = round(time.monotonic() - started, 3)
    output = output_override.lower() if output_override else context.output
    _emit(totals, output)


@index_group.command("rebuild")
@click.option("--projection", type=click.Choice(["all", "keystone", "media", "checkpoints", "events", "exports", "archive-members", "qihse", "fts", "graph"], case_sensitive=False), default="all", show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_rebuild(projection: str, output_override: str | None) -> None:
    """Rebuild derived projection records from committed outbox events."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.rebuild", {"projection": projection.lower()}, context)), output)


@index_group.command("verify")
@click.option("--projection", type=click.Choice(["all", "keystone", "media", "checkpoints", "events", "exports", "archive-members", "qihse", "fts", "graph"], case_sensitive=False), default="all", show_default=True)
@click.option("--native/--no-native", default=True, show_default=True, help="Run sampled native QIHSE/KEYSTONE lookups.")
@click.option("--sample-size", type=click.IntRange(min=1, max=10_000), default=16, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_verify(projection: str, native: bool, sample_size: int, output_override: str | None) -> None:
    """Verify projection counts, checksums, and sampled native lookups."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    result = _redact(_operation_result("index.verify", {
        "projection": projection.lower(),
        "native": native,
        "sample_size": sample_size,
    }, context))
    _emit(result, output)
    if not result.get("details", {}).get("ok", False):
        raise click.exceptions.Exit(EXIT_PARTIAL)


@index_group.command("lookup")
@click.option("--channel-id", type=click.IntRange(), required=True)
@click.option("--message-id", type=click.IntRange(), required=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_lookup(channel_id: int, message_id: int, output_override: str | None) -> None:
    """Look up a channel-scoped message through KEYSTONE."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.lookup", {
        "channel_id": channel_id,
        "message_id": message_id,
    }, context)), output)


@index_group.command("lookup-record")
@click.argument("projection", type=click.Choice(["checkpoints", "events", "exports", "archive-members"], case_sensitive=False))
@click.argument("namespace")
@click.argument("external_id")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_lookup_record(
    projection: str,
    namespace: str,
    external_id: str,
    output_override: str | None,
) -> None:
    """Resolve a typed non-message record through KEYSTONE."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.lookup-record", {
        "projection": projection.lower(),
        "namespace": namespace,
        "external_id": external_id,
    }, context)), output)


def _emit_typed_record_lookup(
    projection: str,
    namespace: str,
    external_id: str,
    output_override: str | None,
) -> None:
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.lookup-record", {
        "projection": projection,
        "namespace": namespace,
        "external_id": external_id,
    }, context)), output)


@index_group.command("checkpoint")
@click.argument("checkpoint_id", type=click.IntRange(min=1))
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_checkpoint(checkpoint_id: int, output_override: str | None) -> None:
    """Resolve one durable database checkpoint by ID."""
    _emit_typed_record_lookup(
        "checkpoints",
        "checkpoints",
        str(checkpoint_id),
        output_override,
    )


@index_group.command("event")
@click.argument("kind", type=click.Choice(["task", "operation", "audit"], case_sensitive=False))
@click.argument("event_id", type=click.IntRange(min=1))
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_event(kind: str, event_id: int, output_override: str | None) -> None:
    """Resolve one immutable task, operation, or audit event by ID."""
    namespaces = {
        "task": "task_events",
        "operation": "operation_events",
        "audit": "operation_audit_log",
    }
    _emit_typed_record_lookup(
        "events",
        namespaces[kind.lower()],
        str(event_id),
        output_override,
    )


@index_group.command("export-record")
@click.argument("export_id")
@click.argument("record_ordinal", type=click.IntRange(min=0))
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_export_record(
    export_id: str,
    record_ordinal: int,
    output_override: str | None,
) -> None:
    """Resolve one byte-addressable export record by persistent ordinal."""
    _emit_typed_record_lookup(
        "exports",
        export_id,
        str(record_ordinal),
        output_override,
    )


@index_group.command("archive-member")
@click.argument("archive_id")
@click.argument("member_index", type=click.IntRange(min=0))
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_archive_member(
    archive_id: str,
    member_index: int,
    output_override: str | None,
) -> None:
    """Resolve one indexed ZIP/TAR member by archive-local index."""
    _emit_typed_record_lookup(
        "archive-members",
        archive_id,
        str(member_index),
        output_override,
    )


@index_group.command("graph")
@click.option("--node-type", required=True, help="Node namespace, such as message, channel, user, or channel_ref.")
@click.option("--external-id", required=True, help="Namespace-local node identity.")
@click.option("--edge-type", help="Optional typed-edge filter.")
@click.option("--direction", type=click.Choice(["outgoing", "incoming", "both"]), default="both", show_default=True)
@click.option("--limit", type=click.IntRange(min=1, max=10_000), default=100, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_graph(node_type: str, external_id: str, edge_type: str | None, direction: str, limit: int, output_override: str | None) -> None:
    """Query persistent QIHSE relationship edges for one stable node."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.graph", {
        "node_type": node_type,
        "external_id": external_id,
        "edge_type": edge_type,
        "direction": direction,
        "limit": limit,
    }, context)), output)


@index_group.command("backfill-export")
@click.argument("export_dir", type=click.Path(path_type=Path))
@click.option("--limit", type=click.IntRange(min=1), help="Read at most this many manifest records.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_backfill_export(export_dir: Path, limit: int | None, output_override: str | None) -> None:
    """Import a channel export snapshot into the durable index outbox."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.backfill-export", {
        "export_dir": export_dir,
        "limit": limit,
    }, context)), output)


@index_group.command("backfill-database")
@click.option("--limit", type=click.IntRange(min=1), help="Read at most this many source rows.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_backfill_database(limit: int | None, output_override: str | None) -> None:
    """Import safe historical checkpoint and event identities."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.backfill-database", {
        "limit": limit,
    }, context)), output)


@index_group.command("scan-archive")
@click.argument("archive_path", type=click.Path(path_type=Path))
@click.option("--limit", type=click.IntRange(min=1, max=100_000), default=10_000, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_scan_archive(
    archive_path: Path,
    limit: int,
    output_override: str | None,
) -> None:
    """Index bounded ZIP/TAR member metadata without extracting contents."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.scan-archive", {
        "archive_path": archive_path,
        "limit": limit,
    }, context)), output)


@index_group.command("benchmark")
@click.option("--database", type=click.Path(path_type=Path), help="Keep benchmark artifacts in this database; default uses a temporary database.")
@click.option("--events", type=click.IntRange(min=10, max=1_000_000), default=1000, show_default=True)
@click.option("--writers", type=click.IntRange(min=1, max=256), default=16, show_default=True)
@click.option("--lookups", type=click.IntRange(min=1, max=10_000), default=10, show_default=True)
@click.option("--batch-size", type=click.IntRange(min=1, max=100_000), default=1000, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def index_benchmark(database: Path | None, events: int, writers: int, lookups: int, batch_size: int, output_override: str | None) -> None:
    """Benchmark writes, projections, lookups, replay, and crash recovery."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_operation_result("index.benchmark", {
        "database": database,
        "events": events,
        "writers": writers,
        "lookups": lookups,
        "batch_size": batch_size,
    }, context)), output)


@db_group.command("tables")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def db_tables(output_override: str | None) -> None:
    """List database tables and row counts."""
    context = _context()
    with _connect_existing_sqlite(context.db_path) as connection:
        rows = [{"table": table, "rows": _count_table_rows(connection, table)} for table in _table_names(connection)]
    output = output_override.lower() if output_override else context.output
    _emit(rows, output)


@db_group.command("table")
@click.argument("table")
@click.option("--limit", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT), default=DEFAULT_TABLE_LIMIT, show_default=True)
@click.option("--offset", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def db_table(table: str, limit: int, offset: int, output_override: str | None) -> None:
    """Read rows from one database table."""
    context = _context()
    with _connect_existing_sqlite(context.db_path) as connection:
        rows = _fetch_table_rows(connection, table, limit=limit, offset=offset)
    output = output_override.lower() if output_override else context.output
    _emit(_redact(rows), output)


@cli.group("database", hidden=True)
def database_alias() -> None:
    """Compatibility alias for db commands."""


for _command in db_group.commands.values():
    database_alias.add_command(_command)


@cli.group("export")
def export_group() -> None:
    """Export local SPECTRA data."""


@export_group.command("table")
@click.argument("table")
@click.option("--output-file", type=click.Path(path_type=Path), required=True, help="Destination export file.")
@click.option("--format", "export_format", type=click.Choice(["csv", "json", "jsonl"], case_sensitive=False), default="csv", show_default=True)
@click.option("--limit", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT))
@click.option("--offset", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the command result output format.")
def export_table(table: str, output_file: Path, export_format: str, limit: int | None, offset: int, output_override: str | None) -> None:
    """Export one database table to CSV, JSON, or JSONL."""
    context = _context()
    export_format = export_format.lower()
    with _connect_existing_sqlite(context.db_path) as connection:
        row_limit = limit if limit is not None else _count_table_rows(connection, table)
        rows = _fetch_table_rows(connection, table, limit=row_limit, offset=offset)
    if not context.dry_run:
        _write_rows(output_file, rows, export_format)
    output = output_override.lower() if output_override else context.output
    _emit({
        "database": str(context.db_path),
        "table": table,
        "output_file": str(output_file),
        "format": export_format,
        "rows": len(rows),
        "dry_run": context.dry_run,
        "written": not context.dry_run,
    }, output)


@cli.group("discover")
def discover_group() -> None:
    """Discover groups and channels from Telegram seeds or crawler data."""


@discover_group.command("run")
@click.option("--seed")
@click.option("--seeds-file", type=click.Path(path_type=Path))
@click.option("--crawler-dir", type=click.Path(path_type=Path))
@click.option("--depth", type=click.IntRange(min=1, max=3), default=1, show_default=True)
@click.option("--messages", type=click.IntRange(min=1), default=1000, show_default=True)
@click.option("--export", type=click.Path(path_type=Path))
@click.option("--parallel", is_flag=True)
@click.option("--max-workers", type=click.IntRange(min=1))
def discover_run(seed: str | None, seeds_file: Path | None, crawler_dir: Path | None, depth: int, messages: int, export: Path | None, parallel: bool, max_workers: int | None) -> None:
    """Discover related groups from a seed, file, or crawler export."""
    _run_legacy(
        "handle_discover",
        seed=seed,
        seeds_file=str(seeds_file) if seeds_file else None,
        crawler_dir=str(crawler_dir) if crawler_dir else None,
        depth=depth,
        messages=messages,
        export=str(export) if export else None,
        parallel=parallel,
        max_workers=max_workers,
    )


@discover_group.command("status")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def discover_status(output_override: str | None) -> None:
    """Inspect persisted discovery summary data without Telegram."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_discovery_status(context), output)


@discover_group.command("results")
@click.option("--limit", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT), default=DEFAULT_TABLE_LIMIT, show_default=True)
@click.option("--offset", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--status", "status_filter", help="Filter by discovered group status.")
@click.option("--source", help="Filter by discovery source.")
@click.option("--min-priority", type=click.FloatRange(min=0), default=0.0, show_default=True)
@click.option("--export", "export_file", type=click.Path(path_type=Path), help="Write results to a file.")
@click.option("--format", "export_format", type=click.Choice(["json", "jsonl", "csv"], case_sensitive=False), default="json", show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def discover_results(limit: int, offset: int, status_filter: str | None, source: str | None, min_priority: float, export_file: Path | None, export_format: str, output_override: str | None) -> None:
    """List persisted discovered groups without Telegram."""
    context = _context()
    rows = _discovery_results(
        context,
        limit=limit,
        offset=offset,
        status=status_filter,
        source=source,
        min_priority=min_priority,
    )
    if export_file and not context.dry_run:
        _write_rows(export_file, rows, export_format.lower())
    output = output_override.lower() if output_override else context.output
    if export_file:
        _emit({
            "database": str(context.db_path),
            "output_file": str(export_file),
            "format": export_format.lower(),
            "rows": len(rows),
            "dry_run": context.dry_run,
            "written": not context.dry_run,
        }, output)
        return
    _emit(rows, output)


@cli.group("network")
def network_group() -> None:
    """Analyze discovered Telegram relationships."""


@network_group.command("analyze")
@click.option("--crawler-dir", type=click.Path(path_type=Path))
@click.option("--from-db", is_flag=True)
@click.option("--plot", is_flag=True)
@click.option("--metric", default="combined", show_default=True)
@click.option("--export", type=click.Path(path_type=Path))
@click.option("--top", type=click.IntRange(min=1), default=20, show_default=True)
def network_analyze(crawler_dir: Path | None, from_db: bool, plot: bool, metric: str, export: Path | None, top: int) -> None:
    """Analyze crawler or database relationship data."""
    _run_legacy(
        "handle_network",
        crawler_dir=str(crawler_dir) if crawler_dir else None,
        from_db=from_db,
        plot=plot,
        metric=metric,
        export=str(export) if export else None,
        top=top,
    )


@network_group.command("status")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def network_status(output_override: str | None) -> None:
    """Inspect persisted discovery network summary data without Telegram."""
    context = _context()
    payload = _discovery_status(context)
    output = output_override.lower() if output_override else context.output
    _emit(payload, output)


@network_group.command("export")
@click.option("--output-file", type=click.Path(path_type=Path), required=True, help="Destination file for priority target export.")
@click.option("--format", "export_format", type=click.Choice(["json", "jsonl", "csv"], case_sensitive=False), default="json", show_default=True)
@click.option("--top", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT), default=DEFAULT_TABLE_LIMIT, show_default=True)
@click.option("--min-priority", type=click.FloatRange(min=0), default=0.0, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def network_export(output_file: Path, export_format: str, top: int, min_priority: float, output_override: str | None) -> None:
    """Export persisted priority targets without rerunning network analysis."""
    context = _context()
    rows = _discovery_results(
        context,
        limit=top,
        offset=0,
        status=None,
        source=None,
        min_priority=min_priority,
    )
    if not context.dry_run:
        _write_rows(output_file, rows, export_format.lower())
    output = output_override.lower() if output_override else context.output
    _emit({
        "database": str(context.db_path),
        "output_file": str(output_file),
        "format": export_format.lower(),
        "rows": len(rows),
        "dry_run": context.dry_run,
        "written": not context.dry_run,
    }, output)


@cli.group("search")
def search_group() -> None:
    """Search locally archived SPECTRA data."""


@search_group.command("fulltext")
@click.argument("query")
@click.option("--limit", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT), default=DEFAULT_TABLE_LIMIT, show_default=True)
@click.option("--offset", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--channel-id", type=click.IntRange())
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def search_fulltext(query: str, limit: int, offset: int, channel_id: int | None, output_override: str | None) -> None:
    """Run a case-insensitive local keyword search over archived messages."""
    from ..db.index_projector import IndexProjector

    context = _context()
    try:
        rows = IndexProjector(context.db_path).fulltext_search(
            query,
            limit=limit,
            offset=offset,
            channel_id=channel_id,
        )
    except ValueError as exc:
        raise click.ClickException(f"Full-text search failed: {exc}") from exc
    if not rows:
        rows = _message_search_rows(context, query, limit=limit, offset=offset, channel_id=channel_id)
    output = output_override.lower() if output_override else context.output
    _emit(rows, output)


@search_group.command("stats")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def search_stats(output_override: str | None) -> None:
    """Show local search index and message-table status."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_search_stats(context), output)


@search_group.command("semantic")
@click.argument("query")
@click.option("--limit", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT), default=DEFAULT_TABLE_LIMIT, show_default=True)
@click.option("--channel-id", type=click.IntRange())
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def search_semantic(query: str, limit: int, channel_id: int | None, output_override: str | None) -> None:
    """Search the persistent QIHSE content projection."""
    from ..db.index_projector import IndexProjector

    context = _context()
    try:
        rows = IndexProjector(context.db_path).search(query, limit=limit, channel_id=channel_id)
    except (RuntimeError, ValueError) as exc:
        raise click.ClickException(f"Semantic search unavailable: {exc}. Run `spectra index process` first.") from exc
    output = output_override.lower() if output_override else context.output
    _emit(_redact(rows), output)


@search_group.command("hybrid")
@click.argument("query")
@click.option("--limit", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT), default=DEFAULT_TABLE_LIMIT, show_default=True)
@click.option("--channel-id", type=click.IntRange())
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def search_hybrid(query: str, limit: int, channel_id: int | None, output_override: str | None) -> None:
    """Return local keyword and QIHSE semantic results together."""
    from ..db.index_projector import IndexProjector

    context = _context()
    try:
        keyword_rows = IndexProjector(context.db_path).fulltext_search(
            query,
            limit=limit,
            channel_id=channel_id,
        )
    except ValueError as exc:
        raise click.ClickException(f"Hybrid search unavailable: {exc}") from exc
    if not keyword_rows:
        keyword_rows = _message_search_rows(context, query, limit=limit, offset=0, channel_id=channel_id)
    try:
        semantic_rows = IndexProjector(context.db_path).search(query, limit=limit, channel_id=channel_id)
    except (RuntimeError, ValueError) as exc:
        raise click.ClickException(f"Hybrid search unavailable: {exc}. Run `spectra index process` first.") from exc
    output = output_override.lower() if output_override else context.output
    _emit(_redact({"query": query, "keyword": keyword_rows, "semantic": semantic_rows}), output)


@search_group.command("saved")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def search_saved(output_override: str | None) -> None:
    """List saved searches when the saved-search table exists."""
    context = _context()
    rows: list[dict[str, Any]] = []
    if context.db_path.exists():
        with _connect_existing_sqlite(context.db_path) as connection:
            if "saved_searches" in set(_table_names(connection)):
                rows = _fetch_table_rows(connection, "saved_searches", limit=MAX_TABLE_LIMIT, offset=0)
    output = output_override.lower() if output_override else context.output
    _emit(_redact(rows), output)


@cli.group("analyze")
def analyze_group() -> None:
    """Run local analysis over archived data."""


@analyze_group.command("indicators")
@click.argument("query", required=False)
@click.option("--limit", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT), default=DEFAULT_TABLE_LIMIT, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def analyze_indicators(query: str | None, limit: int, output_override: str | None) -> None:
    """Detect threat indicators in matching local message text."""
    context = _context()
    try:
        from ..threat.indicators import ThreatIndicatorDetector
    except ImportError as exc:
        raise click.ClickException("Unavailable capability: threat indicator detector is not importable") from exc
    if query:
        rows = _message_search_rows(context, query, limit=limit, offset=0)
    elif context.db_path.exists():
        with _connect_existing_sqlite(context.db_path) as connection:
            if "messages" in set(_table_names(connection)):
                columns = _table_columns(connection, "messages")
                selected = [column for column in ("id", "channel_id", "user_id", "sender_id", "date", "type", "content", "message", "raw_text", "text", "caption") if column in columns]
                order_column = "date" if "date" in columns else "id"
                rows = [
                    dict(row)
                    for row in connection.execute(
                        f"SELECT {', '.join(_quote_identifier(column) for column in selected)} FROM messages ORDER BY {_quote_identifier(order_column)} DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                ]
            else:
                rows = []
    else:
        rows = []
    detector = ThreatIndicatorDetector()
    results = []
    for row in rows:
        text = str(row.get("content") or row.get("message") or row.get("raw_text") or row.get("text") or "")
        detected = detector.detect_indicators(text)
        if detected:
            results.append({"message_id": row.get("id"), "indicators": [item.__dict__ for item in detected]})
    output = output_override.lower() if output_override else context.output
    _emit(results, output)


@analyze_group.command("temporal")
@click.option("--limit", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT), default=MAX_TABLE_LIMIT, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def analyze_temporal(limit: int, output_override: str | None) -> None:
    """Analyze timestamp distribution for locally archived messages."""
    context = _context()
    if not context.db_path.exists():
        _emit({"database": str(context.db_path), "messages": 0, "hours": []}, output_override.lower() if output_override else context.output)
        return
    with _connect_existing_sqlite(context.db_path) as connection:
        if "messages" not in set(_table_names(connection)) or "date" not in _table_columns(connection, "messages"):
            rows = []
        else:
            rows = connection.execute("SELECT date FROM messages WHERE date IS NOT NULL ORDER BY date DESC LIMIT ?", (limit,)).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        hour = str(row["date"])[:13]
        if hour:
            counts[hour] = counts.get(hour, 0) + 1
    payload = {"database": str(context.db_path), "messages": len(rows), "hours": [{"hour": key, "messages": value} for key, value in sorted(counts.items())]}
    output = output_override.lower() if output_override else context.output
    _emit(payload, output)


def analyze_unavailable() -> None:
    """Report analysis capabilities that are not wired to the local CLI yet."""
    raise click.ClickException("Unavailable capability: this analysis backend is not configured for the local CLI")


for _name in ("attribution", "account-correlation", "network", "score", "forecast"):
    analyze_group.add_command(click.Command(_name, callback=analyze_unavailable, help=analyze_unavailable.__doc__))


@cli.group("ml")
def ml_group() -> None:
    """Inspect local ML and model state."""


@ml_group.command("patterns")
@click.option("--limit", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT), default=DEFAULT_TABLE_LIMIT, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def ml_patterns(limit: int, output_override: str | None) -> None:
    """List persisted pattern records when available."""
    context = _context()
    rows: list[dict[str, Any]] = []
    if context.db_path.exists():
        with _connect_existing_sqlite(context.db_path) as connection:
            for table in ("ml_patterns", "patterns", "caas_message_profile"):
                if table in set(_table_names(connection)):
                    rows = _fetch_table_rows(connection, table, limit=limit, offset=0)
                    break
    output = output_override.lower() if output_override else context.output
    _emit(rows, output)


@ml_group.group("model")
def ml_model_group() -> None:
    """Inspect local ML model capabilities."""


@ml_model_group.command("list")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def ml_model_list(output_override: str | None) -> None:
    """Show local ML backend availability."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit({
        "models": [],
        "pattern_detector_available": _module_available("tgarchive.ml.pattern_detector"),
        "continuous_learner_available": _module_available("tgarchive.ml.continuous_learner"),
        "semantic_store_available": _module_available("tgarchive.search.qihse_bindings"),
    }, output)


def ml_unavailable() -> None:
    """Report ML capabilities that require an initialized ML backend."""
    raise click.ClickException("Unavailable capability: ML backend is not configured for the local CLI")


for _name in ("correlate", "entities", "semantic-search"):
    ml_group.add_command(click.Command(_name, callback=ml_unavailable, help=ml_unavailable.__doc__))
ml_model_group.add_command(click.Command("train", callback=ml_unavailable, help=ml_unavailable.__doc__))


@cli.group("crypto")
def crypto_group() -> None:
    """Run CNSA 2.0 crypto operations."""


async def _crypto_call(method: str, *args: Any) -> dict[str, Any]:
    try:
        from ..api.services.crypto_service import CryptoService
    except ImportError as exc:
        raise click.ClickException("Unavailable capability: crypto service is not importable") from exc
    service = CryptoService()
    result = await getattr(service, method)(*args)
    if not isinstance(result, dict):
        raise click.ClickException("Crypto service returned an invalid result")
    return _crypto_result_or_unavailable(result)


@crypto_group.command("algorithms")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def crypto_algorithms(output_override: str | None) -> None:
    """Show configured CNSA 2.0 algorithms."""
    context = _context()
    payload = asyncio.run(_crypto_call("get_algorithm_info"))
    output = output_override.lower() if output_override else context.output
    _emit(payload, output)


@crypto_group.command("kem")
@click.option("--key-id")
@click.option("--output-file", type=click.Path(path_type=Path), help="Write generated keypair JSON to an owner-only file.")
@click.option("--force", is_flag=True, help="Overwrite an existing output file.")
def crypto_kem(key_id: str | None, output_file: Path | None, force: bool) -> None:
    """Generate an ML-KEM-1024 keypair."""
    context = _context()
    payload = asyncio.run(_crypto_call("generate_kem_keypair", key_id))
    if output_file:
        _write_bytes_file(output_file, json.dumps(payload, indent=2).encode("utf-8") + b"\n", force=force)
        _emit({"output_file": str(output_file), "written": True, "algorithm": payload.get("algorithm"), "key_id": payload.get("key_id")}, context.output)
        return
    _emit(payload, context.output)


@crypto_group.command("signature")
@click.option("--key-id")
@click.option("--output-file", type=click.Path(path_type=Path), help="Write generated keypair JSON to an owner-only file.")
@click.option("--force", is_flag=True, help="Overwrite an existing output file.")
def crypto_signature(key_id: str | None, output_file: Path | None, force: bool) -> None:
    """Generate an ML-DSA-87 signature keypair."""
    context = _context()
    payload = asyncio.run(_crypto_call("generate_signature_keypair", key_id))
    if output_file:
        _write_bytes_file(output_file, json.dumps(payload, indent=2).encode("utf-8") + b"\n", force=force)
        _emit({"output_file": str(output_file), "written": True, "algorithm": payload.get("algorithm"), "key_id": payload.get("key_id")}, context.output)
        return
    _emit(payload, context.output)


@crypto_group.command("encrypt")
@click.option("--input-file", type=click.Path(path_type=Path), required=True)
@click.option("--recipient-public-key", required=True, help="Base64 recipient public key.")
@click.option("--output-file", type=click.Path(path_type=Path), help="Write encrypted JSON package to an owner-only file.")
@click.option("--force", is_flag=True, help="Overwrite an existing output file.")
def crypto_encrypt(input_file: Path, recipient_public_key: str, output_file: Path | None, force: bool) -> None:
    """Encrypt a file with hybrid ML-KEM-1024 and AES-256-GCM."""
    context = _context()
    payload = asyncio.run(_crypto_call("encrypt_data", _read_file_base64(input_file), recipient_public_key))
    if output_file:
        _write_bytes_file(output_file, json.dumps(payload, indent=2).encode("utf-8") + b"\n", force=force)
        _emit({"output_file": str(output_file), "written": True, "algorithm": payload.get("algorithm")}, context.output)
        return
    _emit(payload, context.output)


@crypto_group.command("decrypt")
@click.option("--package-file", type=click.Path(path_type=Path), required=True)
@click.option("--recipient-secret-key", required=True, help="Base64 recipient secret key.")
@click.option("--output-file", type=click.Path(path_type=Path), required=True, help="Write plaintext to an owner-only file.")
@click.option("--force", is_flag=True, help="Overwrite an existing output file.")
def crypto_decrypt(package_file: Path, recipient_secret_key: str, output_file: Path, force: bool) -> None:
    """Decrypt a JSON encryption package to a file."""
    context = _context()
    package = _read_json_file(package_file)
    payload = asyncio.run(_crypto_call("decrypt_data", package, recipient_secret_key))
    plaintext_b64 = payload.get("plaintext")
    if not isinstance(plaintext_b64, str):
        raise click.ClickException("Crypto service did not return plaintext")
    try:
        plaintext = base64.b64decode(plaintext_b64)
    except ValueError as exc:
        raise click.ClickException(f"Crypto service returned invalid base64 plaintext: {exc}") from exc
    _write_bytes_file(output_file, plaintext, force=force)
    _emit({"output_file": str(output_file), "written": True}, context.output)


@cli.group("admin")
def admin_group() -> None:
    """Inspect local administration state."""


@admin_group.command("health")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def admin_health(output_override: str | None) -> None:
    """Show local system, config, task, and capability health."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit(_redact(_admin_health(context)), output)


@admin_group.command("config")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def admin_config(output_override: str | None) -> None:
    """Show redacted active configuration."""
    config_show.callback(output_override)


@admin_group.command("stats")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def admin_stats(output_override: str | None) -> None:
    """Show database and task totals."""
    context = _context()
    table_counts: dict[str, int] = {}
    if context.db_path.exists():
        with _connect_existing_sqlite(context.db_path) as connection:
            table_counts = {table: _count_table_rows(connection, table) for table in _table_names(connection)}
    payload = {"database": str(context.db_path), "tables": table_counts, "tasks": len(_latest_task_records(context))}
    output = output_override.lower() if output_override else context.output
    _emit(payload, output)


@admin_group.command("operations")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def admin_operations(output_override: str | None) -> None:
    """List locally recorded detached operations."""
    context = _context()
    output = output_override.lower() if output_override else context.output
    _emit([_enrich_task_record(record) for record in _latest_task_records(context)], output)


@admin_group.command("logs")
@click.option("--path", "log_path", type=click.Path(path_type=Path), help="Specific log file to read.")
@click.option("--tail", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT), default=50, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def admin_logs(log_path: Path | None, tail: int, output_override: str | None) -> None:
    """Tail a local SPECTRA log file."""
    target = log_path or Path("logs")
    if target.is_dir():
        candidates = sorted((path for path in target.glob("*.log") if path.is_file()), key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            rows: list[str] = []
            selected = None
        else:
            selected = candidates[0]
            rows = _tail_lines(selected, tail)
    else:
        selected = target
        rows = _tail_lines(target, tail)
    output = output_override.lower() if output_override else _context().output
    _emit({"path": str(selected) if selected else str(target), "lines": rows}, output)


@admin_group.group("operator")
def admin_operator_group() -> None:
    """Onboard hardened remote API operators."""


@admin_operator_group.command("hash-password")
@click.option("--username", required=True, help="Operator username.")
@click.option("--password-env", help="Environment variable containing the operator password.")
@click.option("--role", "roles", multiple=True, default=("admin",), help="Role to assign. Repeat for multiple roles.")
@click.option("--permission", "permissions", multiple=True, help="Permission flag to set true. Repeat for multiple permissions.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def admin_operator_hash_password(username: str, password_env: str | None, roles: tuple[str, ...], permissions: tuple[str, ...], output_override: str | None) -> None:
    """Generate a hardened remote operator record without saving it."""
    context = _context()
    password = _operator_password(password_env, non_interactive=context.non_interactive)
    record = _operator_record(username, password, roles, permissions)
    output = output_override.lower() if output_override else context.output
    _emit(record, output)


@admin_operator_group.command("add")
@click.option("--username", required=True, help="Operator username.")
@click.option("--password-env", help="Environment variable containing the operator password.")
@click.option("--role", "roles", multiple=True, default=("admin",), help="Role to assign. Repeat for multiple roles.")
@click.option("--permission", "permissions", multiple=True, help="Permission flag to set true. Repeat for multiple permissions.")
@click.option("--replace", is_flag=True, help="Replace an existing operator with the same username.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def admin_operator_add(username: str, password_env: str | None, roles: tuple[str, ...], permissions: tuple[str, ...], replace: bool, output_override: str | None) -> None:
    """Add a hardened remote operator record to the active config."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to modify operators in non-interactive mode without --yes")
    password = _operator_password(password_env, non_interactive=context.non_interactive)
    record = _operator_record(username, password, roles, permissions)
    data = _read_config_document(context.config_path)
    operators = data.setdefault("operators", [])
    if not isinstance(operators, list):
        raise click.ClickException("Config operators must be a list")
    existing_index = next(
        (index for index, operator in enumerate(operators) if isinstance(operator, dict) and operator.get("username") == username),
        None,
    )
    if existing_index is not None and not replace:
        raise click.ClickException(f"Operator already exists: {username}")
    if not context.dry_run:
        if existing_index is None:
            operators.append(record)
        else:
            operators[existing_index] = record
        _write_json_file(context.config_path, data)
    output = output_override.lower() if output_override else context.output
    _emit({
        "changed": not context.dry_run,
        "dry_run": context.dry_run,
        "username": username,
        "roles": record["roles"],
        "permissions": record["permissions"],
        "config": str(context.config_path),
        "replaced": existing_index is not None,
    }, output)


@cli.group("server")
def server_group() -> None:
    """Inspect or run the local SPECTRA API server."""


@server_group.command("health")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def server_health(output_override: str | None) -> None:
    """Check server capability and secret readiness."""
    context = _context()
    payload = _server_health(context)
    output = output_override.lower() if output_override else context.output
    _emit(payload, output)
    if not payload["server_available"]:
        raise click.exceptions.Exit(EXIT_UNAVAILABLE)


@server_group.command("run")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=click.IntRange(min=1, max=65535), default=5000, show_default=True)
@click.option("--debug", is_flag=True)
def server_run(host: str, port: int, debug: bool) -> None:
    """Run the SPECTRA Flask API server."""
    context = _context()
    health = _server_health(context)
    if not health["server_available"]:
        raise click.ClickException("Unavailable capability: Flask server dependencies are not installed")
    if context.dry_run:
        _emit({"dry_run": True, "host": host, "port": port, "debug": debug, "security_posture": health["security_posture"]}, context.output)
        return
    from ..api import create_app

    app = create_app(_read_config_document(context.config_path))
    app.run(host=host, port=port, debug=debug)


@cli.group("api")
def api_group() -> None:
    """Inspect API capabilities."""


@api_group.command("graphql")
@click.option("--schema", "show_schema", is_flag=True, help="Report GraphQL route availability.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def api_graphql(show_schema: bool, output_override: str | None) -> None:
    """Inspect GraphQL availability."""
    context = _context()
    available = _graphql_available()
    payload = {
        "available": available,
        "schema_requested": show_schema,
        "endpoint": "/graphql" if available else None,
    }
    output = output_override.lower() if output_override else context.output
    _emit(payload, output)
    if not available:
        raise click.exceptions.Exit(EXIT_UNAVAILABLE)


@cli.group("osint")
def osint_group() -> None:
    """Track OSINT targets and run Telegram-backed scans."""


@osint_group.group("target")
def osint_target_group() -> None:
    """Manage OSINT tracked targets."""


@osint_target_group.command("add")
@click.option("--user", required=True, help="Username to track.")
@click.option("--user-id", type=click.IntRange(min=1), help="Known Telegram user ID for local add without network lookup.")
@click.option("--notes", default="", help="Operator notes for the target.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def osint_target_add(user: str, user_id: int | None, notes: str, output_override: str | None) -> None:
    """Add an OSINT target locally or through Telegram lookup."""
    context = _context()
    if user_id is None:
        _run_legacy("handle_osint", osint_command="add-target", user=user, notes=notes)
        return
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to modify OSINT targets in non-interactive mode without --yes")
    now = datetime.now(timezone.utc).isoformat()
    if not context.dry_run:
        with _connect_existing_sqlite(context.db_path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO users (id, username, last_updated) VALUES (?, ?, ?)",
                (user_id, user, now),
            )
            connection.execute(
                "INSERT OR REPLACE INTO osint_targets (user_id, username, notes, created_at) VALUES (?, ?, ?, ?)",
                (user_id, user, notes, now),
            )
            connection.commit()
    output = output_override.lower() if output_override else context.output
    _emit({
        "changed": not context.dry_run,
        "dry_run": context.dry_run,
        "target": {"user_id": user_id, "username": user, "notes": notes},
        "database": str(context.db_path),
    }, output)


@osint_target_group.command("remove")
@click.option("--user", required=True, help="Username to stop tracking.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def osint_target_remove(user: str, output_override: str | None) -> None:
    """Remove an OSINT target from the local database."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to modify OSINT targets in non-interactive mode without --yes")
    removed = 0
    if not context.dry_run:
        with _connect_existing_sqlite(context.db_path) as connection:
            cursor = connection.execute("DELETE FROM osint_targets WHERE username = ?", (user,))
            connection.commit()
            removed = cursor.rowcount
    output = output_override.lower() if output_override else context.output
    _emit({"changed": bool(removed) and not context.dry_run, "dry_run": context.dry_run, "username": user, "removed": removed}, output)


@osint_target_group.command("list")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def osint_target_list(output_override: str | None) -> None:
    """List OSINT targets from the local database."""
    context = _context()
    with _connect_existing_sqlite(context.db_path) as connection:
        _require_table(connection, "osint_targets")
        rows = connection.execute(
            "SELECT user_id, username, notes, created_at FROM osint_targets ORDER BY created_at DESC, username"
        ).fetchall()
    output = output_override.lower() if output_override else context.output
    _emit([dict(row) for row in rows], output)


@osint_group.command("scan")
@click.option("--channel", required=True, help="Channel ID or username to scan.")
@click.option("--user", required=True, help="Target username to scan for.")
def osint_scan(channel: str, user: str) -> None:
    """Scan a Telegram channel for target interactions."""
    _run_legacy("handle_osint", osint_command="scan", channel=channel, user=user)


@osint_group.command("network")
@click.option("--user", required=True, help="Target username.")
def osint_network(user: str) -> None:
    """Show a target interaction network."""
    _run_legacy("handle_osint", osint_command="show-network", user=user)


@cli.group("migration")
def migration_group() -> None:
    """Run and inspect channel migrations."""


@migration_group.command("run")
@click.option("--source", required=True)
@click.option("--destination", required=True)
@click.option("--dry-run", is_flag=True)
@click.option("--parallel", is_flag=True)
def migration_run(source: str, destination: str, dry_run: bool, parallel: bool) -> None:
    """Migrate media and messages from SOURCE to DESTINATION."""
    _run_legacy("handle_migrate", source=source, destination=destination, dry_run=dry_run, parallel=parallel)


@migration_group.command("report")
@click.option("--migration-id", type=click.IntRange(min=1), required=True)
def migration_report(migration_id: int) -> None:
    """Show the persisted report for a migration."""
    _run_legacy("handle_migrate_report", migration_id=migration_id)


@migration_group.command("status")
@click.option("--migration-id", type=click.IntRange(min=1), help="Show one migration by ID.")
@click.option("--source", help="Filter by source.")
@click.option("--destination", help="Filter by destination.")
@click.option("--limit", type=click.IntRange(min=1, max=MAX_TABLE_LIMIT), default=DEFAULT_TABLE_LIMIT, show_default=True)
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def migration_status(migration_id: int | None, source: str | None, destination: str | None, limit: int, output_override: str | None) -> None:
    """Inspect local migration progress records."""
    context = _context()
    clauses: list[str] = []
    params: list[Any] = []
    if migration_id is not None:
        clauses.append("id = ?")
        params.append(migration_id)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if destination:
        clauses.append("destination = ?")
        params.append(destination)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect_existing_sqlite(context.db_path) as connection:
        _require_table(connection, "migration_progress")
        try:
            rows = connection.execute(
                f"""
                SELECT id, source, destination, last_message_id, status, created_at, updated_at
                FROM migration_progress
                {where}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise click.ClickException(f"Unable to read migration status: {exc}") from exc
    output = output_override.lower() if output_override else context.output
    _emit([dict(row) for row in rows], output)


@migration_group.command("rollback")
@click.option("--migration-id", type=click.IntRange(min=1), required=True)
def migration_rollback(migration_id: int) -> None:
    """Roll back a completed migration."""
    _run_legacy("handle_rollback", migration_id=migration_id)


@cli.group("mirror", invoke_without_command=True)
@click.option("--source")
@click.option("--destination")
@click.option("--source-account")
@click.option("--destination-account")
@click.pass_context
def mirror_group(ctx: click.Context, source: str | None, destination: str | None, source_account: str | None, destination_account: str | None) -> None:
    """Mirror Telegram groups using separate source and destination accounts."""
    if ctx.invoked_subcommand is not None:
        return
    missing = [
        name
        for name, value in {
            "--source": source,
            "--destination": destination,
            "--source-account": source_account,
            "--destination-account": destination_account,
        }.items()
        if not value
    ]
    if missing:
        raise click.ClickException(f"Missing required option(s): {', '.join(missing)}")
    _run_legacy(
        "handle_mirror",
        source=source,
        destination=destination,
        source_account=source_account,
        destination_account=destination_account,
    )


@mirror_group.command("run")
@click.option("--source", required=True)
@click.option("--destination", required=True)
@click.option("--source-account", required=True)
@click.option("--destination-account", required=True)
def mirror_run(source: str, destination: str, source_account: str, destination_account: str) -> None:
    """Run a group mirror operation."""
    _run_legacy(
        "handle_mirror",
        source=source,
        destination=destination,
        source_account=source_account,
        destination_account=destination_account,
    )


@mirror_group.command("status")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def mirror_status(output_override: str | None) -> None:
    """Summarize mirror-related migration records."""
    context = _context()
    with _connect_existing_sqlite(context.db_path) as connection:
        if "migration_progress" not in set(_table_names(connection)):
            rows: list[dict[str, Any]] = []
        else:
            fetched = connection.execute(
                """
                SELECT id, source, destination, last_message_id, status, created_at, updated_at
                FROM migration_progress
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (DEFAULT_TABLE_LIMIT,),
            ).fetchall()
            rows = [dict(row) for row in fetched]
    output = output_override.lower() if output_override else context.output
    _emit({"database": str(context.db_path), "recent_migrations": rows}, output)


def _channel_access_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    _require_table(connection, "account_channel_access")
    rows = connection.execute(
        """
        SELECT
            channel_id,
            COALESCE(MAX(channel_name), '') AS channel_name,
            COUNT(DISTINCT account_phone_number) AS accounts,
            MAX(last_seen) AS last_seen,
            SUM(CASE WHEN access_hash IS NOT NULL THEN 1 ELSE 0 END) AS access_hashes
        FROM account_channel_access
        GROUP BY channel_id
        ORDER BY last_seen DESC, channel_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _channel_detail(connection: sqlite3.Connection, channel_id: int) -> dict[str, Any]:
    _require_table(connection, "account_channel_access")
    access_rows = connection.execute(
        """
        SELECT account_phone_number, channel_name, access_hash, last_seen
        FROM account_channel_access
        WHERE channel_id = ?
        ORDER BY last_seen DESC, account_phone_number
        """,
        (channel_id,),
    ).fetchall()
    if not access_rows:
        raise click.ClickException(f"Channel not found: {channel_id}")
    payload: dict[str, Any] = {
        "channel_id": channel_id,
        "channel_name": next((row["channel_name"] for row in access_rows if row["channel_name"]), None),
        "accounts": [dict(row) for row in access_rows],
    }
    tables = set(_table_names(connection))
    if "channel_file_inventory" in tables:
        inventory = connection.execute(
            """
            SELECT COUNT(*) AS files, COUNT(DISTINCT message_id) AS messages, COUNT(DISTINCT topic_id) AS topics
            FROM channel_file_inventory
            WHERE channel_id = ?
            """,
            (channel_id,),
        ).fetchone()
        payload["inventory"] = dict(inventory) if inventory else {"files": 0, "messages": 0, "topics": 0}
    return payload


def _ensure_channel_access_table(connection: sqlite3.Connection) -> None:
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS account_channel_access (
                account_phone_number TEXT NOT NULL,
                channel_id BIGINT NOT NULL,
                channel_name TEXT,
                access_hash BIGINT,
                last_seen TEXT,
                PRIMARY KEY (account_phone_number, channel_id)
            )
            """
        )
        connection.commit()
    except sqlite3.Error as exc:
        raise click.ClickException(f"Unable to prepare channel catalog table: {exc}") from exc


@channel_group.command("archive")
@click.argument("entity")
@click.option("--no-media", is_flag=True, help="Do not download media.")
@click.option("--no-avatars", is_flag=True, help="Do not download avatars.")
@click.option("--no-topics", is_flag=True, help="Do not archive topics/threads.")
@click.option("--auto", is_flag=True, help="Use auto-selected account.")
def channel_archive(entity: str, no_media: bool, no_avatars: bool, no_topics: bool, auto: bool) -> None:
    """Archive ENTITY through the existing Telegram archive workflow."""
    _run_legacy(
        "handle_archive",
        entity=entity,
        no_media=no_media,
        no_avatars=no_avatars,
        no_topics=no_topics,
        auto=auto,
    )


@channel_group.command("members")
@click.argument("server_id", type=click.IntRange())
@click.option("--output-file", type=click.Path(path_type=Path), required=True, help="Destination file for member export.")
@click.option("--format", "output_format", type=click.Choice(["csv", "json", "sqlite"], case_sensitive=False), default="csv", show_default=True)
@click.option("--rotate-ip", is_flag=True, help="Enable IP rotation on flood-wait errors.")
@click.option("--rate-limit-delay", type=click.IntRange(min=0), default=1, show_default=True, help="Delay between member requests.")
def channel_members(server_id: int, output_file: Path, output_format: str, rotate_ip: bool, rate_limit_delay: int) -> None:
    """Download channel/server member metadata."""
    _run_legacy(
        "handle_download_users",
        server_id=server_id,
        output_file=str(output_file),
        output_format=output_format.lower(),
        rotate_ip=rotate_ip,
        rate_limit_delay=rate_limit_delay,
    )


@channel_group.command("add")
@click.argument("channel_id", type=click.IntRange())
@click.option("--account", required=True, help="Account phone/session that can access the channel.")
@click.option("--name", "channel_name", help="Display name to store.")
@click.option("--access-hash", type=click.IntRange(), help="Telegram access hash when known.")
@click.option("--last-seen", help="ISO timestamp. Defaults to now.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def channel_add(channel_id: int, account: str, channel_name: str | None, access_hash: int | None, last_seen: str | None, output_override: str | None) -> None:
    """Add or update one local channel catalog entry."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to modify channel catalog in non-interactive mode without --yes")
    seen_at = last_seen or datetime.now(timezone.utc).isoformat()
    if not context.dry_run:
        with sqlite3.connect(context.db_path) as connection:
            _ensure_channel_access_table(connection)
            try:
                connection.execute(
                    """
                    INSERT INTO account_channel_access(account_phone_number, channel_id, channel_name, access_hash, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(account_phone_number, channel_id) DO UPDATE SET
                        channel_name=excluded.channel_name,
                        access_hash=excluded.access_hash,
                        last_seen=excluded.last_seen
                    """,
                    (account, channel_id, channel_name, access_hash, seen_at),
                )
                connection.commit()
            except sqlite3.Error as exc:
                raise click.ClickException(f"Unable to update channel catalog: {exc}") from exc
    output = output_override.lower() if output_override else context.output
    _emit({
        "changed": not context.dry_run,
        "dry_run": context.dry_run,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "account": account,
        "last_seen": seen_at,
        "database": str(context.db_path),
    }, output)


@channel_group.command("remove")
@click.argument("channel_id", type=click.IntRange())
@click.option("--account", help="Remove only this account/channel link.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def channel_remove(channel_id: int, account: str | None, output_override: str | None) -> None:
    """Remove local channel catalog metadata."""
    context = _context()
    if context.non_interactive and not context.yes:
        raise click.ClickException("Refusing to modify channel catalog in non-interactive mode without --yes")
    removed = 0
    if not context.dry_run:
        with sqlite3.connect(context.db_path) as connection:
            _ensure_channel_access_table(connection)
            try:
                if account:
                    cursor = connection.execute(
                        "DELETE FROM account_channel_access WHERE channel_id = ? AND account_phone_number = ?",
                        (channel_id, account),
                    )
                else:
                    cursor = connection.execute(
                        "DELETE FROM account_channel_access WHERE channel_id = ?",
                        (channel_id,),
                    )
                connection.commit()
                removed = int(cursor.rowcount)
            except sqlite3.Error as exc:
                raise click.ClickException(f"Unable to remove channel catalog entry: {exc}") from exc
    output = output_override.lower() if output_override else context.output
    _emit({
        "changed": bool(removed) and not context.dry_run,
        "dry_run": context.dry_run,
        "channel_id": channel_id,
        "account": account,
        "removed": removed,
        "database": str(context.db_path),
    }, output)


@channel_group.command("list")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def channel_list(output_override: str | None) -> None:
    """List channels known from account access metadata."""
    context = _context()
    with _connect_existing_sqlite(context.db_path) as connection:
        rows = _channel_access_rows(connection)
    output = output_override.lower() if output_override else context.output
    _emit(rows, output)


@channel_group.command("show")
@click.argument("channel_id", type=click.IntRange())
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def channel_show(channel_id: int, output_override: str | None) -> None:
    """Show local metadata for one known channel."""
    context = _context()
    with _connect_existing_sqlite(context.db_path) as connection:
        payload = _channel_detail(connection, channel_id)
    output = output_override.lower() if output_override else context.output
    _emit(_redact(payload), output)


@channel_group.command("stats")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def channel_stats(output_override: str | None) -> None:
    """Summarize local channel access and inventory metadata."""
    context = _context()
    with _connect_existing_sqlite(context.db_path) as connection:
        tables = set(_table_names(connection))
        rows = _channel_access_rows(connection) if "account_channel_access" in tables else []
        inventory_files = _count_table_rows(connection, "channel_file_inventory") if "channel_file_inventory" in tables else 0
    payload = {
        "database": str(context.db_path),
        "channels": len(rows),
        "account_channel_links": sum(int(row.get("accounts") or 0) for row in rows),
        "channels_with_access_hash": sum(1 for row in rows if int(row.get("access_hashes") or 0) > 0),
        "inventory_files": inventory_files,
    }
    output = output_override.lower() if output_override else context.output
    _emit(payload, output)


@channel_group.command("inspect")
@click.argument("channel_id", type=click.IntRange())
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format.")
def channel_inspect(channel_id: int, output_override: str | None) -> None:
    """Inspect local channel access and file inventory metadata."""
    channel_show.callback(channel_id, output_override)


@channel_group.command("access-refresh")
def channel_access_refresh() -> None:
    """Refresh account-to-channel access metadata through Telegram."""
    _run_legacy("handle_update_channel_access")


@cli.group("channels", hidden=True)
def channels_alias() -> None:
    """Compatibility alias for channel metadata commands."""


channels_alias.add_command(channel_access_refresh, "update-access")
channels_alias.add_command(channel_access_refresh, "access-refresh")
channels_alias.add_command(channel_list, "list")
channels_alias.add_command(channel_show, "show")
channels_alias.add_command(channel_stats, "stats")
channels_alias.add_command(channel_inspect, "inspect")
channels_alias.add_command(channel_add, "add")
channels_alias.add_command(channel_remove, "remove")


@channel_group.command("download")
@click.argument("entity")
@click.option("--output-dir", type=click.Path(path_type=Path), default="channel_downloads", show_default=True)
@click.option("--account")
@click.option("--auto", is_flag=True, help="Select an available account automatically.")
@click.option("--no-proxy", is_flag=True, help="Connect directly without the configured proxy.")
@click.option("--no-media", is_flag=True)
@click.option("--media-only", is_flag=True, help="Download media without writing message JSONL metadata.")
@click.option("--max-connections", "--concurrency", "max_connections", type=click.IntRange(min=1), default=32, show_default=True, help="Maximum concurrent media transfers.")
@click.option("--max-retries", type=click.IntRange(min=0), default=5, show_default=True, help="Retry attempts per media file after transient failures.")
@click.option("--retry-delay", type=click.FloatRange(min=0), default=3.0, show_default=True, help="Delay between non-flood media retries in seconds.")
@click.option("--fail-fast", is_flag=True, help="Abort the download on the first media transfer failure.")
@click.option("--no-retry-flood-waits", is_flag=True, help="Do not wait and retry Telegram flood-wait errors.")
@click.option("--progress-interval", type=click.FloatRange(min=1), default=15.0, show_default=True, help="Seconds between aggregate progress summaries.")
@click.option("--stall-timeout", type=click.FloatRange(min=1), default=75.0, show_default=True, help="Seconds without per-file byte progress before retrying a media transfer.")
@click.option("--limit", type=click.IntRange(min=1))
@click.option("--min-id", type=click.IntRange(min=1))
@click.option("--max-id", type=click.IntRange(min=1))
@click.option("--restart", is_flag=True, help="Start over from the beginning, ignoring state.json.")
@click.option("--resume/--no-resume", default=True, help="Resume an interrupted download from state.json.")
def channel_download(entity: str, output_dir: Path, account: str | None, auto: bool, no_proxy: bool, no_media: bool, media_only: bool, max_connections: int, max_retries: int, retry_delay: float, fail_fast: bool, no_retry_flood_waits: bool, progress_interval: float, stall_timeout: float, limit: int | None, min_id: int | None, max_id: int | None, restart: bool, resume: bool) -> None:
    """Download all accessible messages and media from ENTITY."""
    context = _context()
    if context.detach or context.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        command = _detached_channel_command(
            context,
            entity=entity,
            output_dir=output_dir,
            account=account,
            auto=auto,
            no_proxy=no_proxy,
            no_media=no_media,
            media_only=media_only,
            max_connections=max_connections,
            max_retries=max_retries,
            retry_delay=retry_delay,
            fail_fast=fail_fast,
            no_retry_flood_waits=no_retry_flood_waits,
            progress_interval=progress_interval,
            stall_timeout=stall_timeout,
            limit=limit,
            min_id=min_id,
            max_id=max_id,
            restart=restart,
            resume=resume,
        )
        log_path = _detached_log_path(output_dir, entity)
        result: dict[str, Any] = {
            "detached": context.detach,
            "dry_run": context.dry_run,
            "log_path": str(log_path),
            "output_dir": str(output_dir),
        }
        if context.dry_run:
            result["argv"] = command
            _emit(_redact(result), context.output)
            return
        try:
            log_handle = log_path.open("ab")
        except OSError as exc:
            raise click.ClickException(f"Unable to open detached log {log_path}: {exc}") from exc
        try:
            child_environment = os.environ.copy()
            child_environment["SPECTRA_DOWNLOAD_LOG_PATH"] = str(log_path.resolve())
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=child_environment,
            )
        except OSError as exc:
            raise click.ClickException(f"Unable to start detached channel download: {exc}") from exc
        finally:
            log_handle.close()
        result["pid"] = process.pid
        task_id = datetime.now(timezone.utc).strftime("task-%Y%m%dT%H%M%SZ")
        task_record = {
            "id": task_id,
            "kind": "channel.download",
            "status": "running",
            "pid": process.pid,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "log_path": str(log_path),
            "output_dir": str(output_dir),
            "argv": _redact_argv(command),
        }
        _append_task_record(context, task_record)
        result["task_id"] = task_id
        result["task_registry"] = str(_task_registry_path(context))
        _emit(_redact(result), context.output)
        return

    from .. import __main__ as legacy

    getattr(legacy, '_load_legacy_dependencies', lambda: None)()

    args = type("DownloadArgs", (), {
        "config": str(context.config_path), "db": str(context.db_path), "entity": entity, "output_dir": str(output_dir),
        "account": account, "auto": auto, "no_proxy": no_proxy, "no_media": no_media, "media_only": media_only, "limit": limit,
        "min_id": min_id, "max_id": max_id, "restart": restart, "resume": resume, "max_connections": max_connections, "max_retries": max_retries,
        "retry_delay": retry_delay, "fail_fast": fail_fast, "no_retry_flood_waits": no_retry_flood_waits,
        "progress_interval": progress_interval, "stall_timeout": stall_timeout, "import_accounts": False,
    })()
    result = asyncio.run(legacy.handle_download_channel(args))
    if result:
        raise click.exceptions.Exit(result)



@channel_group.command("retry-failed")
@click.argument("entity")
@click.option("--output-dir", type=click.Path(path_type=Path), default="channel_downloads", show_default=True)
@click.option("--account")
@click.option("--no-proxy", is_flag=True, help="Connect directly without the configured proxy.")
@click.option("--max-connections", "--concurrency", "max_connections", type=click.IntRange(min=1), default=32, show_default=True, help="Maximum concurrent media transfers.")
@click.option("--max-retries", type=click.IntRange(min=0), default=5, show_default=True, help="Retry attempts per media file after transient failures.")
@click.option("--retry-delay", type=click.FloatRange(min=0), default=3.0, show_default=True, help="Delay between non-flood media retries in seconds.")
@click.option("--fail-fast", is_flag=True, help="Abort the download on the first media transfer failure.")
@click.option("--no-retry-flood-waits", is_flag=True, help="Do not wait and retry Telegram flood-wait errors.")
@click.option("--progress-interval", type=click.FloatRange(min=1), default=15.0, show_default=True, help="Seconds between aggregate progress summaries.")
@click.option("--stall-timeout", type=click.FloatRange(min=1), default=75.0, show_default=True, help="Seconds without per-file byte progress before retrying a media transfer.")
def channel_retry_failed(entity: str, output_dir: Path, account: str | None, no_proxy: bool, max_connections: int, max_retries: int, retry_delay: float, fail_fast: bool, no_retry_flood_waits: bool, progress_interval: float, stall_timeout: float) -> None:
    """Retry failed media downloads for ENTITY."""
    context = _context()
    from .. import __main__ as legacy
    getattr(legacy, '_load_legacy_dependencies', lambda: None)()

    args = type("RetryFailedArgs", (), {
        "config": str(context.config_path), "db": str(context.db_path), "entity": entity, "output_dir": str(output_dir),
        "account": account, "no_proxy": no_proxy, "max_connections": max_connections, "max_retries": max_retries,
        "retry_delay": retry_delay, "fail_fast": fail_fast, "no_retry_flood_waits": no_retry_flood_waits,
        "progress_interval": progress_interval, "stall_timeout": stall_timeout, "import_accounts": False,
    })()
    import asyncio
    result = asyncio.run(legacy.handle_retry_failed(args))
    if result:
        raise click.exceptions.Exit(result)


@channel_group.command("status")
@click.argument("export_dir", type=click.Path(path_type=Path))
@click.option("--tail", type=click.IntRange(min=0), default=10, show_default=True, help="Include the last N log lines.")
@click.option("--output", "output_override", type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False), help="Override the global output format for this status report.")
def channel_status(export_dir: Path, tail: int, output_override: str | None) -> None:
    """Inspect a channel download export directory."""
    context = _context()
    payload = _operation_result("channel.status", {"export_dir": export_dir, "tail": tail}, context)["status"]
    output = output_override.lower() if output_override else _context().output
    _emit(payload, output)


@channel_group.command("monitor")
@click.argument("base_dir", type=click.Path(path_type=Path), default=".", required=False)
@click.option("--refresh", type=float, default=1.0, help="Refresh interval in seconds")
def channel_monitor(base_dir: Path, refresh: float) -> None:
    """Monitor all active channel downloads in real-time."""
    import json
    import time
    try:
        from rich.live import Live
        from rich.table import Table
        from rich.panel import Panel
    except ImportError:
        raise click.ClickException("The 'rich' library is required for the monitor TUI.")

    def generate_dashboard():
        table = Table(title=f"Unified Download Monitor: {base_dir.absolute()}", expand=True)
        table.add_column("Channel", style="cyan", no_wrap=True)
        table.add_column("Status", style="bold")
        table.add_column("Messages", justify="right")
        table.add_column("Media (OK/Skip/Fail)", justify="right")
        table.add_column("Last Updated", style="dim")
        table.add_column("Last Log Line", style="dim italic", overflow="ellipsis")

        state_files = list(base_dir.glob("*/state.json"))
        if not state_files:
            return Panel(f"No download states found in {base_dir.absolute()}")

        for state_file in sorted(state_files):
            try:
                with open(state_file) as f:
                    state = json.load(f)
                
                channel_id = str(state_file.parent.name)
                
                msg_written = state.get("messages_written_this_run", 0)
                media_dl = state.get("media_downloaded_this_run", 0)
                media_skip = state.get("media_skipped_this_run", 0)
                media_fail = state.get("media_failed_this_run", 0)
                last_updated = state.get("updated_at", "").split(".")[0]
                
                status_text = "[green]Running"
                if state.get("complete"):
                    status_text = "[blue]Completed"
                
                media_text = f"{media_dl} / {media_skip} / " + (f"[red]{media_fail}[/red]" if media_fail > 0 else f"{media_fail}")
                
                log_line = ""
                log_path = state_file.parent / "download.log"
                if log_path.exists():
                    try:
                        with open(log_path, "rb") as f:
                            f.seek(0, 2)
                            size = f.tell()
                            if size > 0:
                                f.seek(max(size - 256, 0), 0)
                                lines = f.read().decode("utf-8", errors="ignore").splitlines()
                                if lines:
                                    log_line = lines[-1][-80:].strip()
                                    from rich.markup import escape
                                    log_line = escape(log_line)
                    except Exception:
                        pass

                table.add_row(
                    channel_id,
                    status_text,
                    str(msg_written),
                    media_text,
                    last_updated,
                    log_line
                )
            except Exception:
                continue
                
        return table

    with Live(generate_dashboard(), refresh_per_second=1/refresh) as live:
        try:
            while True:
                time.sleep(refresh)
                live.update(generate_dashboard())
        except KeyboardInterrupt:
            pass



@cli.command("download-channel", hidden=True)
@click.argument("entity")
@click.pass_context
def download_channel_alias(ctx: click.Context, entity: str) -> None:
    """Compatibility alias for `channel download`."""
    ctx.invoke(channel_download, entity=entity, output_dir=Path("channel_downloads"), account=None, auto=False, no_proxy=False, no_media=False, media_only=False, max_connections=32, max_retries=5, retry_delay=3.0, fail_fast=False, no_retry_flood_waits=False, progress_interval=15.0, stall_timeout=75.0, limit=None, min_id=None, max_id=None, restart=False)

if __name__ == "__main__":
    cli()
