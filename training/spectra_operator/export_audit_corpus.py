#!/usr/bin/env python3
"""Export privacy-reviewed SPECTRA operation audit records as JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


SOURCE_TABLE = "operation_audit"
SCHEMA_VERSION = "spectra-operator-audit-corpus-v1"
REDACTION_VERSION = "spectra-operator-redaction-v1"
ALLOWED_COLUMNS = (
    "audit_id",
    "source",
    "request_text",
    "operation_id",
    "status",
    "started_at",
    "finished_at",
    "envelope_json",
    "planned_command_json",
    "actual_argv_json",
    "result_json",
    "error_json",
)

_SENSITIVE_KEYS = {
    "account",
    "api_hash",
    "api_id",
    "api_key",
    "authorization",
    "bootstrap_secret",
    "code",
    "credential",
    "jwt_secret",
    "otp",
    "passwd",
    "password",
    "phone",
    "phone_number",
    "private_key",
    "refresh_token",
    "session",
    "session_name",
    "session_secret",
    "secret",
    "token",
}
_SENSITIVE_FLAGS = {
    "--account",
    "--api-hash",
    "--api-id",
    "--api-key",
    "--authorization",
    "--code",
    "--otp",
    "--password",
    "--password-env",
    "--phone",
    "--private-key",
    "--session",
    "--session-name",
    "--secret",
    "--token",
}
_LABELED_SECRET_RE = re.compile(
    r"(?i)\b("
    r"account|api[\s_-]?(?:hash|id|key)|authorization|credential|"
    r"jwt[\s_-]?secret|otp|2fa(?:[\s_-]?code)?|pass(?:word|wd)|"
    r"phone(?:[\s_-]?number)?|private[\s_-]?key|refresh[\s_-]?token|"
    r"session(?:[\s_-]?(?:name|secret))?|secret|token"
    r")\b(\s*(?:=|:)\s*|\s+)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
    re.DOTALL,
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
_KNOWN_TOKEN_RE = re.compile(
    r"\b(?:gh[opsu]_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"\d{6,12}:[A-Za-z0-9_-]{20,})\b"
)
_URL_CREDENTIAL_RE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@/\s]+@", re.I)
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE_RE = re.compile(r"(?<!\w)\+\d[\d ()-]{7,}\d(?!\w)")


class CorpusExportError(RuntimeError):
    """Raised when an audit corpus cannot be exported safely."""


@dataclass(frozen=True)
class ExportSummary:
    database: str
    output: str
    rows_read: int
    rows_exported: int
    duplicates_skipped: int
    redaction_version: str = REDACTION_VERSION
    schema_version: str = SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "database": self.database,
            "output": self.output,
            "rows_read": self.rows_read,
            "rows_exported": self.rows_exported,
            "duplicates_skipped": self.duplicates_skipped,
            "redaction_version": self.redaction_version,
            "schema_version": self.schema_version,
        }


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    padded = f"_{normalized}_"
    return any(f"_{sensitive}_" in padded for sensitive in _SENSITIVE_KEYS)


def _is_sensitive_flag(flag: str) -> bool:
    return flag.startswith("-") and (
        flag.lower() in _SENSITIVE_FLAGS or _is_sensitive_key(flag.lstrip("-"))
    )


def _redact_text(value: str) -> str:
    text = _PRIVATE_KEY_RE.sub("[redacted-private-key]", value)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    text = _JWT_RE.sub("[redacted-token]", text)
    text = _KNOWN_TOKEN_RE.sub("[redacted-token]", text)
    text = _URL_CREDENTIAL_RE.sub(r"\g<scheme>[redacted]@", text)
    text = _LABELED_SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text)
    text = _EMAIL_RE.sub("[redacted-email]", text)
    return _PHONE_RE.sub("[redacted-phone]", text)


def _redact(value: Any, key: str | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return "[redacted]" if value not in (None, "") else value
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value))


def _redact_argv(value: Any) -> Any:
    if not isinstance(value, list):
        return _redact(value)
    redacted: list[Any] = []
    hide_next = False
    for item in value:
        if hide_next:
            redacted.append("[redacted]")
            hide_next = False
            continue
        if not isinstance(item, str):
            redacted.append(_redact(item))
            continue
        flag, separator, inline_value = item.partition("=")
        if _is_sensitive_flag(flag):
            if separator:
                redacted.append(f"{flag}=[redacted]")
            else:
                redacted.append(flag)
                hide_next = True
            continue
        redacted.append(_redact_text(item))
    return redacted


def _parse_json(raw: Any, *, argv: bool = False) -> Any:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return {"malformed": True}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"malformed": True}
    return _redact_argv(value) if argv else _redact(value)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise CorpusExportError(f"Unable to serialize privacy-reviewed corpus record: {exc}") from exc


def _error_category(error: Any) -> str | None:
    if not isinstance(error, dict):
        return None
    category = error.get("category")
    if not isinstance(category, str) or not category.strip():
        return None
    return _redact_text(category.strip())


def _build_record(row: sqlite3.Row) -> dict[str, Any]:
    error = _parse_json(row["error_json"])
    core = {
        "request": _redact(row["request_text"]),
        "operation": {
            "operation_id": _redact(row["operation_id"]),
            "envelope": _parse_json(row["envelope_json"]),
            "planned_command": _parse_json(row["planned_command_json"], argv=True),
            "actual_argv": _parse_json(row["actual_argv_json"], argv=True),
        },
        "execution": {
            "status": _redact(row["status"]),
            "result": _parse_json(row["result_json"]),
            "error_category": _error_category(error),
        },
    }
    dedup_hash = hashlib.sha256(_canonical_json(core).encode("utf-8")).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "redaction_version": REDACTION_VERSION,
        **core,
        "dedup_hash": dedup_hash,
        "provenance": {
            "source_table": SOURCE_TABLE,
            "audit_id": _redact(row["audit_id"]),
            "source": _redact(row["source"]),
            "started_at": _redact(row["started_at"]),
            "finished_at": _redact(row["finished_at"]),
        },
    }


def _connect_read_only(database: Path) -> sqlite3.Connection:
    resolved = database.expanduser().resolve()
    if not resolved.is_file():
        raise CorpusExportError(f"Audit database does not exist or is not a file: {resolved}")
    try:
        connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise CorpusExportError(f"Unable to open audit database read-only: {exc}") from exc
    connection.row_factory = sqlite3.Row
    return connection


def _validate_schema(connection: sqlite3.Connection) -> None:
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (SOURCE_TABLE,),
        ).fetchone()
        if table is None:
            raise CorpusExportError(f"Required table is missing: {SOURCE_TABLE}")
        available = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({SOURCE_TABLE})").fetchall()
        }
    except sqlite3.Error as exc:
        raise CorpusExportError(f"Unable to inspect audit schema: {exc}") from exc
    missing = sorted(set(ALLOWED_COLUMNS) - available)
    if missing:
        raise CorpusExportError(f"Audit table is missing required columns: {', '.join(missing)}")


def _iter_rows(
    connection: sqlite3.Connection,
    *,
    statuses: Sequence[str],
    limit: int | None,
) -> Iterable[sqlite3.Row]:
    columns = ", ".join(ALLOWED_COLUMNS)
    query = f"SELECT {columns} FROM {SOURCE_TABLE}"
    parameters: list[Any] = []
    if statuses:
        query += f" WHERE status IN ({', '.join('?' for _ in statuses)})"
        parameters.extend(statuses)
    query += " ORDER BY started_at ASC, audit_id ASC"
    if limit is not None:
        query += " LIMIT ?"
        parameters.append(limit)
    try:
        cursor = connection.execute(query, parameters)
        yield from cursor
    except sqlite3.Error as exc:
        raise CorpusExportError(f"Unable to read operation audit rows: {exc}") from exc


def export_operation_audit(
    database: Path,
    output: Path,
    *,
    statuses: Sequence[str] = (),
    limit: int | None = None,
    deduplicate: bool = True,
) -> ExportSummary:
    """Export allowlisted operation audit data to an atomic JSONL file."""
    if not isinstance(database, Path) or not isinstance(output, Path):
        raise TypeError("database and output must be pathlib.Path instances")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        raise ValueError("limit must be a positive integer")
    if not isinstance(statuses, Sequence) or isinstance(statuses, (str, bytes)):
        raise TypeError("statuses must be a sequence of strings")
    clean_statuses = tuple(status.strip() for status in statuses if isinstance(status, str) and status.strip())
    if len(clean_statuses) != len(statuses):
        raise ValueError("statuses must contain only non-empty strings")

    resolved_database = database.expanduser().resolve()
    resolved_output = output.expanduser().resolve()
    if resolved_output == resolved_database:
        raise CorpusExportError("Output path must not overwrite the input audit database")
    try:
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CorpusExportError(f"Unable to create output directory: {exc}") from exc
    rows_read = 0
    rows_exported = 0
    duplicates_skipped = 0
    seen_hashes: set[str] = set()
    temporary_path: Path | None = None

    try:
        with _connect_read_only(database) as connection:
            _validate_schema(connection)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=resolved_output.parent,
                prefix=f".{resolved_output.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                for row in _iter_rows(connection, statuses=clean_statuses, limit=limit):
                    rows_read += 1
                    record = _build_record(row)
                    dedup_hash = record["dedup_hash"]
                    if deduplicate and dedup_hash in seen_hashes:
                        duplicates_skipped += 1
                        continue
                    seen_hashes.add(dedup_hash)
                    handle.write(_canonical_json(record))
                    handle.write("\n")
                    rows_exported += 1
                handle.flush()
                os.fsync(handle.fileno())
        if temporary_path is None:
            raise CorpusExportError("Exporter did not create an output file")
        os.replace(temporary_path, resolved_output)
    except (OSError, sqlite3.Error) as exc:
        raise CorpusExportError(f"Unable to write corpus JSONL: {exc}") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError as exc:
                raise CorpusExportError(f"Unable to remove temporary corpus file: {exc}") from exc

    return ExportSummary(
        database=str(database.expanduser().resolve()),
        output=str(resolved_output),
        rows_read=rows_read,
        rows_exported=rows_exported,
        duplicates_skipped=duplicates_skipped,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export privacy-reviewed operation_audit records as training JSONL"
    )
    parser.add_argument("--database", type=Path, required=True, help="SQLite database containing operation_audit")
    parser.add_argument("--output", type=Path, required=True, help="Destination JSONL path")
    parser.add_argument(
        "--status",
        action="append",
        default=[],
        help="Include only this status; repeat to include multiple statuses",
    )
    parser.add_argument("--limit", type=int, help="Maximum source rows to inspect")
    parser.add_argument(
        "--keep-duplicates",
        action="store_true",
        help="Retain records with identical privacy-reviewed training content",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = export_operation_audit(
            args.database,
            args.output,
            statuses=args.status,
            limit=args.limit,
            deduplicate=not args.keep_duplicates,
        )
    except (CorpusExportError, TypeError, ValueError) as exc:
        print(f"export_audit_corpus: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
