"""Rebuildable QIHSE and KEYSTONE projections driven by the SQLite outbox."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import select
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..sqlite_runtime import connect_sqlite
from .index_outbox import IndexOutbox
from .native_store_lock import NativeStoreLock, NativeStoreLockTimeout


KEYSTONE_PROJECTION = "keystone.ids.v1"
MEDIA_MANIFEST_PROJECTION = "keystone.media_manifest.v1"
CHECKPOINT_PROJECTION = "keystone.checkpoints.v1"
EVENT_PROJECTION = "keystone.events.v1"
EXPORT_RECORD_PROJECTION = "keystone.export_records.v1"
ARCHIVE_MEMBER_PROJECTION = "keystone.archive_members.v1"
QIHSE_PROJECTION = "qihse.content.v1"
FTS_PROJECTION = "fts.messages.v1"
GRAPH_PROJECTION = "qihse.graph.v1"
KEYSTONE_PROJECTIONS = (
    KEYSTONE_PROJECTION,
    MEDIA_MANIFEST_PROJECTION,
    CHECKPOINT_PROJECTION,
    EVENT_PROJECTION,
    EXPORT_RECORD_PROJECTION,
    ARCHIVE_MEMBER_PROJECTION,
)
PROJECTIONS = (
    *KEYSTONE_PROJECTIONS,
    QIHSE_PROJECTION,
    FTS_PROJECTION,
    GRAPH_PROJECTION,
)
VECTOR_DIMENSIONS = 64
_TOKEN_RE = re.compile(r"[A-Za-z0-9_@.+-]+")
_SENSITIVE_KEYS = {"api_hash", "password", "token", "secret", "otp", "session_secret", "private_key"}
_KEYSTONE_START_TIMEOUT_SECONDS = 10.0
_KEYSTONE_LOOKUP_TIMEOUT_SECONDS = 30.0
_NATIVE_SYNC_MIN_TIMEOUT_SECONDS = 60.0
_NATIVE_SYNC_MAX_TIMEOUT_SECONDS = 900.0
_NATIVE_SYNC_SECONDS_PER_ROW = 0.25
_NATIVE_STORE_LOCK_TIMEOUT_SECONDS = 30.0
_PROJECTOR_LOCK_TIMEOUT_SECONDS = 300.0


def _native_sync_timeout(
    row_count: int,
    *,
    timeout_limit: float | None = None,
) -> float:
    timeout = min(
        _NATIVE_SYNC_MAX_TIMEOUT_SECONDS,
        max(
            _NATIVE_SYNC_MIN_TIMEOUT_SECONDS,
            row_count * _NATIVE_SYNC_SECONDS_PER_ROW,
        ),
    )
    return min(timeout, timeout_limit) if timeout_limit is not None else timeout


def _read_native_payload(stream: Any, marker: str, timeout: float) -> str:
    """Read one newline-framed native response against a single wall-clock deadline."""
    deadline = time.monotonic() + timeout
    marker_bytes = marker.encode("ascii")
    buffered = bytearray()
    while True:
        newline = buffered.find(b"\n")
        if newline >= 0:
            line = bytes(buffered[:newline]).rstrip(b"\r")
            del buffered[:newline + 1]
            if line.startswith(marker_bytes):
                return line[len(marker_bytes):].decode("utf-8")
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"native worker did not respond within {timeout:g} seconds")
        readable, _, _ = select.select([stream.fileno()], [], [], remaining)
        if not readable:
            raise TimeoutError(f"native worker did not respond within {timeout:g} seconds")
        chunk = os.read(stream.fileno(), 65536)
        if not chunk:
            raise RuntimeError("native worker exited before returning a complete response")
        buffered.extend(chunk)


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def _run_native_command(
    command: list[str],
    *,
    store_path: Path,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    started = time.monotonic()
    lock_timeout = min(timeout, _NATIVE_STORE_LOCK_TIMEOUT_SECONDS)
    with NativeStoreLock(store_path, timeout=lock_timeout):
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise NativeStoreLockTimeout(
                f"native store operation timed out while waiting for {store_path}"
            )
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=remaining,
            check=False,
        )


def _projection_names(projection: str) -> tuple[str, ...]:
    normalized = projection.strip().lower()
    aliases = {
        "all": PROJECTIONS,
        "keystone": KEYSTONE_PROJECTIONS,
        KEYSTONE_PROJECTION: (KEYSTONE_PROJECTION,),
        "media": (MEDIA_MANIFEST_PROJECTION,),
        MEDIA_MANIFEST_PROJECTION: (MEDIA_MANIFEST_PROJECTION,),
        "checkpoints": (CHECKPOINT_PROJECTION,),
        CHECKPOINT_PROJECTION: (CHECKPOINT_PROJECTION,),
        "events": (EVENT_PROJECTION,),
        EVENT_PROJECTION: (EVENT_PROJECTION,),
        "exports": (EXPORT_RECORD_PROJECTION,),
        EXPORT_RECORD_PROJECTION: (EXPORT_RECORD_PROJECTION,),
        "archive-members": (ARCHIVE_MEMBER_PROJECTION,),
        ARCHIVE_MEMBER_PROJECTION: (ARCHIVE_MEMBER_PROJECTION,),
        "qihse": (QIHSE_PROJECTION,),
        QIHSE_PROJECTION: (QIHSE_PROJECTION,),
        "fts": (FTS_PROJECTION,),
        FTS_PROJECTION: (FTS_PROJECTION,),
        "graph": (GRAPH_PROJECTION,),
        GRAPH_PROJECTION: (GRAPH_PROJECTION,),
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(f"Unknown projection: {projection}") from exc


def _canonical_payload(event: dict[str, Any]) -> str:
    payload = event.get("payload", {})
    return json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))


def _content_hash(event: dict[str, Any]) -> str:
    source = "\0".join(
        (
            str(event["source_table"]),
            str(event["source_key"]),
            str(event["event_type"]),
            str(event.get("source_revision") or ""),
            _canonical_payload(event),
        )
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _numeric_key(event: dict[str, Any]) -> int | None:
    payload = event.get("payload", {})
    if isinstance(payload, dict):
        channel_id = payload.get("channel_id")
        message_id = payload.get("message_id")
        if isinstance(channel_id, int) and isinstance(message_id, int):
            return keystone_compound_key(channel_id, message_id)
    candidates = ("message_id", "channel_id", "file_id", "event_id", "sequence_id", "id")
    if isinstance(payload, dict):
        for candidate in candidates:
            value = payload.get(candidate)
            if isinstance(value, int) and -(2**63) <= value < 2**63:
                return value
            if isinstance(value, str):
                try:
                    parsed = int(value)
                except ValueError:
                    continue
                if -(2**63) <= parsed < 2**63:
                    return parsed
    try:
        parsed = int(str(event["source_key"]))
    except ValueError:
        return None
    return parsed if -(2**63) <= parsed < 2**63 else None


def keystone_record_key(
    projection_name: str,
    namespace: str,
    external_id: str,
) -> int:
    """Map one typed external record identity to a stable signed int64 key."""
    if projection_name not in KEYSTONE_PROJECTIONS:
        raise ValueError(f"{projection_name} is not a KEYSTONE projection")
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError("namespace must be a non-empty string")
    if not isinstance(external_id, str) or not external_id:
        raise ValueError("external_id must be a non-empty string")
    fields = (projection_name, namespace, external_id)
    encoded = b"".join(
        len(field.encode("utf-8")).to_bytes(4, "big") + field.encode("utf-8")
        for field in fields
    )
    digest = hashlib.blake2b(
        encoded,
        digest_size=8,
        person=b"SPECTRA-KEY-v1",
    ).digest()
    return int.from_bytes(digest, "big", signed=True)


def _projection_identity(
    projection_name: str,
    event: dict[str, Any],
) -> tuple[str, str] | None:
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        return None
    if projection_name in {KEYSTONE_PROJECTION, MEDIA_MANIFEST_PROJECTION}:
        channel_id = payload.get("channel_id")
        message_id = payload.get("message_id")
        if isinstance(channel_id, int) and isinstance(message_id, int):
            return "telegram-message", f"{channel_id}:{message_id}"
        return None
    if projection_name == EXPORT_RECORD_PROJECTION:
        export_id = payload.get("export_id")
        record_ordinal = payload.get("record_ordinal")
        if isinstance(export_id, str) and export_id and isinstance(record_ordinal, int):
            return export_id, str(record_ordinal)
        return None
    if projection_name == ARCHIVE_MEMBER_PROJECTION:
        archive_member = payload.get("archive_member")
        if isinstance(archive_member, dict):
            archive_id = archive_member.get("archive_id")
            member_index = archive_member.get("member_index")
            if isinstance(archive_id, str) and archive_id and isinstance(member_index, int):
                return archive_id, str(member_index)
        return None
    if projection_name in {CHECKPOINT_PROJECTION, EVENT_PROJECTION}:
        return str(event["source_table"]), str(event["source_key"])
    return None


def _projection_numeric_key(projection_name: str, event: dict[str, Any]) -> int | None:
    identity = _projection_identity(projection_name, event)
    if projection_name in {
        CHECKPOINT_PROJECTION,
        EVENT_PROJECTION,
        EXPORT_RECORD_PROJECTION,
        ARCHIVE_MEMBER_PROJECTION,
    } and identity is not None:
        return keystone_record_key(projection_name, *identity)
    return _numeric_key(event)


def _event_in_projection(projection_name: str, event: dict[str, Any]) -> bool:
    if projection_name == QIHSE_PROJECTION:
        return True
    if projection_name == FTS_PROJECTION:
        return str(event.get("source_table")) in {"messages", "channel_messages"}
    if projection_name == GRAPH_PROJECTION:
        _nodes, edges = _graph_records(event)
        return bool(edges)
    source_table = str(event.get("source_table") or "")
    if projection_name == CHECKPOINT_PROJECTION:
        payload = event.get("payload", {})
        try:
            source_id = int(str(event.get("source_key")))
        except ValueError:
            return False
        return (
            source_table == "checkpoints"
            and event.get("event_type") == "save"
            and isinstance(payload, dict)
            and payload.get("checkpoint_id") == source_id
            and isinstance(payload.get("last_message_id"), int)
            and payload["last_message_id"] >= 0
            and isinstance(payload.get("context"), str)
            and bool(payload["context"])
            and isinstance(payload.get("checkpoint_time"), str)
            and bool(payload["checkpoint_time"])
        )
    if projection_name == EVENT_PROJECTION:
        payload = event.get("payload", {})
        try:
            source_id = int(str(event.get("source_key")))
        except ValueError:
            return False
        if not isinstance(payload, dict) or payload.get("event_id") != source_id:
            return False
        if source_table == "task_events":
            return (
                isinstance(payload.get("task_id"), str)
                and bool(payload["task_id"])
                and isinstance(payload.get("event_at"), str)
                and bool(payload["event_at"])
            )
        if source_table == "operation_events":
            return (
                isinstance(payload.get("operation_id"), str)
                and bool(payload["operation_id"])
                and isinstance(payload.get("event"), str)
                and bool(payload["event"])
                and isinstance(payload.get("timestamp"), str)
                and bool(payload["timestamp"])
            )
        if source_table == "operation_audit_log":
            return (
                isinstance(payload.get("action"), str)
                and bool(payload["action"])
                and isinstance(payload.get("timestamp"), str)
                and bool(payload["timestamp"])
            )
        return False
    if projection_name == EXPORT_RECORD_PROJECTION:
        payload = event.get("payload", {})
        media_manifest = payload.get("media_manifest") if isinstance(payload, dict) else None
        return (
            source_table == "channel_messages"
            and isinstance(payload, dict)
            and isinstance(payload.get("export_id"), str)
            and bool(payload["export_id"])
            and isinstance(payload.get("record_ordinal"), int)
            and payload["record_ordinal"] >= 0
            and isinstance(media_manifest, dict)
            and isinstance(media_manifest.get("byte_offset"), int)
            and media_manifest["byte_offset"] >= 0
            and isinstance(media_manifest.get("byte_length"), int)
            and media_manifest["byte_length"] > 0
            and isinstance(media_manifest.get("record_sha256"), str)
            and len(media_manifest["record_sha256"]) == 64
        )
    if projection_name == ARCHIVE_MEMBER_PROJECTION:
        payload = event.get("payload", {})
        archive_member = payload.get("archive_member") if isinstance(payload, dict) else None
        return (
            source_table == "archive_members"
            and event.get("event_type") == "index"
            and isinstance(archive_member, dict)
            and archive_member.get("member_id") == event.get("source_key")
            and isinstance(archive_member.get("archive_id"), str)
            and bool(archive_member["archive_id"])
            and isinstance(archive_member.get("member_index"), int)
            and archive_member["member_index"] >= 0
            and isinstance(archive_member.get("canonical_member_name"), str)
            and bool(archive_member["canonical_member_name"])
        )
    if projection_name == MEDIA_MANIFEST_PROJECTION:
        payload = event.get("payload", {})
        return (
            _projection_identity(projection_name, event) is not None
            and isinstance(payload, dict)
            and isinstance(payload.get("media_manifest"), dict)
        )
    return (
        projection_name == KEYSTONE_PROJECTION
        and _projection_identity(projection_name, event) is not None
    )


def keystone_compound_key(channel_id: int, message_id: int) -> int:
    """Map a Telegram channel/message identity to a stable signed int64 key."""
    if not isinstance(channel_id, int) or not isinstance(message_id, int):
        raise TypeError("channel_id and message_id must be integers")
    digest = hashlib.blake2b(f"{channel_id}:{message_id}".encode("ascii"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def _graph_node_id(node_key: str) -> int:
    digest = hashlib.blake2b(node_key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1) or 1


def _graph_records(event: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        return [], []
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(node_type: str, external_id: Any) -> dict[str, Any]:
        node_key = f"{node_type}:{external_id}"
        node = {
            "node_id": _graph_node_id(node_key),
            "node_key": node_key,
            "node_type": node_type,
            "external_id": str(external_id),
        }
        nodes[node_key] = node
        return node

    def add_edge(source: dict[str, Any], target: dict[str, Any], edge_type: str) -> None:
        edges.append({
            "from_node_id": source["node_id"],
            "to_node_id": target["node_id"],
            "edge_type": edge_type,
            "metadata": {
                "sequence_id": int(event["sequence_id"]),
                "source_table": str(event["source_table"]),
                "source_key": str(event["source_key"]),
            },
        })

    channel_id = payload.get("channel_id")
    message_id = payload.get("message_id", payload.get("id"))
    if isinstance(channel_id, int) and isinstance(message_id, int):
        message = add_node("message", f"{channel_id}:{message_id}")
        channel = add_node("channel", channel_id)
        add_edge(message, channel, "IN_CHANNEL")
        sender_id = payload.get("sender_id", payload.get("user_id"))
        if isinstance(sender_id, int):
            add_edge(message, add_node("user", sender_id), "POSTED_BY")
        reply_id = payload.get("reply_to_msg_id", payload.get("reply_to"))
        if isinstance(reply_id, int):
            add_edge(message, add_node("message", f"{channel_id}:{reply_id}"), "REPLIES_TO")

    source_group = payload.get("source_group")
    target_group = payload.get("target_group")
    if source_group is not None and target_group is not None:
        add_edge(
            add_node("channel_ref", source_group),
            add_node("channel_ref", target_group),
            "DISCOVERED",
        )
    return list(nodes.values()), edges


def _text_values(value: Any, *, key: str | None = None) -> Iterable[str]:
    if key and key.lower() in _SENSITIVE_KEYS:
        return
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _text_values(child, key=str(child_key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _text_values(child)
    elif isinstance(value, str) and value.strip():
        yield value.strip()


def _text_content(event: dict[str, Any]) -> str:
    values = list(_text_values(event.get("payload", {})))
    values.extend((str(event["source_table"]), str(event["source_key"]), str(event["event_type"])))
    return "\n".join(values)


def _fts_text_content(event: dict[str, Any]) -> str:
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        return ""
    values = [
        str(payload[key]).strip()
        for key in ("content", "message", "raw_text", "text", "caption")
        if isinstance(payload.get(key), str) and str(payload[key]).strip()
    ]
    return "\n".join(values)


def _text_vector(text: str) -> list[float]:
    vector = [0.0] * VECTOR_DIMENSIONS
    for token in _TOKEN_RE.findall(text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
        position = int.from_bytes(digest[:8], "little") % VECTOR_DIMENSIONS
        vector[position] += 1.0 if digest[8] & 1 else -1.0
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude:
        return [value / magnitude for value in vector]
    return vector


class IndexProjector:
    """Consume outbox events into durable, native-searchable projections."""

    def __init__(self, database: Path | str) -> None:
        self.database = Path(database)
        self.qihse_path = self.database.with_suffix(self.database.suffix + ".qihse.qdb")
        self.graph_path = self.database.with_suffix(self.database.suffix + ".graph.qdb")
        canonical_database = self.database.expanduser().resolve()
        self.projector_lock_path = canonical_database.with_suffix(
            canonical_database.suffix + ".projector"
        )
        self.outbox = IndexOutbox(self.database)
        self._keystone_server: subprocess.Popen[bytes] | None = None
        self._keystone_server_lock = threading.Lock()
        self._keystone_request_id = 0
        self._ensure_schema()

    def close(self) -> None:
        with self._keystone_server_lock:
            self._stop_keystone_server_locked()

    def _stop_keystone_server_locked(self) -> None:
        server = self._keystone_server
        self._keystone_server = None
        if server is not None:
            _terminate_process(server)

    def __enter__(self) -> "IndexProjector":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _start_keystone_server(self) -> subprocess.Popen[bytes]:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tgarchive.db.index_native_probe",
                "--server",
                "--db",
                str(self.database),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        if server.stdout is None:
            _terminate_process(server)
            raise RuntimeError("KEYSTONE server stdout is unavailable")
        marker = "SPECTRA_NATIVE_SERVER="
        try:
            result = json.loads(_read_native_payload(
                server.stdout,
                marker,
                _KEYSTONE_START_TIMEOUT_SECONDS,
            ))
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise RuntimeError("KEYSTONE lookup server returned invalid readiness data")
            return server
        except (OSError, RuntimeError, TimeoutError, json.JSONDecodeError):
            _terminate_process(server)
            raise

    def _keystone_lookup(
        self,
        numeric_key: int,
        *,
        projection_name: str = KEYSTONE_PROJECTION,
    ) -> dict[str, Any]:
        if projection_name not in KEYSTONE_PROJECTIONS:
            raise ValueError(f"{projection_name} is not a KEYSTONE projection")
        marker = "SPECTRA_NATIVE_RESPONSE="
        with self._keystone_server_lock:
            for attempt in range(2):
                try:
                    server = self._keystone_server
                    if server is None or server.poll() is not None:
                        self._keystone_server = self._start_keystone_server()
                        server = self._keystone_server
                    if server.stdin is None or server.stdout is None:
                        raise RuntimeError("KEYSTONE lookup server pipes are unavailable")
                    self._keystone_request_id += 1
                    request_id = self._keystone_request_id
                    request = json.dumps({
                        "request_id": request_id,
                        "lookup_key": numeric_key,
                        "projection": projection_name,
                    }).encode("utf-8") + b"\n"
                    server.stdin.write(request)
                    server.stdin.flush()
                    result = json.loads(_read_native_payload(
                        server.stdout,
                        marker,
                        _KEYSTONE_LOOKUP_TIMEOUT_SECONDS,
                    ))
                    if not isinstance(result, dict):
                        raise RuntimeError("KEYSTONE lookup server returned a non-object response")
                    if result.get("request_id") != request_id:
                        raise RuntimeError("KEYSTONE lookup server returned a mismatched request ID")
                    if not result.get("ok"):
                        raise RuntimeError(str(result.get("error") or "KEYSTONE lookup failed"))
                    return result
                except (
                    BrokenPipeError,
                    OSError,
                    RuntimeError,
                    TimeoutError,
                    TypeError,
                    ValueError,
                    json.JSONDecodeError,
                ) as exc:
                    self._stop_keystone_server_locked()
                    if attempt:
                        raise RuntimeError("KEYSTONE lookup server failed after restart") from exc
            raise RuntimeError("KEYSTONE lookup failed")

    def _connection(self):
        connection = connect_sqlite(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self.outbox._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS index_projection_records (
                    projection_name TEXT NOT NULL,
                    sequence_id INTEGER NOT NULL,
                    source_table TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source_revision TEXT,
                    content_hash TEXT NOT NULL,
                    numeric_key INTEGER,
                    text_content TEXT,
                    vector_json TEXT,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (projection_name, sequence_id),
                    FOREIGN KEY (sequence_id) REFERENCES index_outbox(sequence_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_index_projection_numeric
                    ON index_projection_records(projection_name, numeric_key);
                CREATE INDEX IF NOT EXISTS idx_index_projection_source
                    ON index_projection_records(projection_name, source_table, source_key);
                CREATE TABLE IF NOT EXISTS index_projection_keys (
                    projection_name TEXT NOT NULL,
                    numeric_key INTEGER NOT NULL,
                    logical_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (projection_name, numeric_key),
                    UNIQUE (projection_name, logical_key)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS index_projection_fts USING fts5(
                    sequence_id UNINDEXED,
                    source_table UNINDEXED,
                    source_key UNINDEXED,
                    channel_id UNINDEXED,
                    text_content,
                    tokenize='unicode61'
                );
                CREATE TABLE IF NOT EXISTS index_graph_nodes (
                    node_id INTEGER PRIMARY KEY,
                    node_key TEXT NOT NULL UNIQUE,
                    node_type TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    first_sequence_id INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS index_graph_edges (
                    from_node_id INTEGER NOT NULL,
                    to_node_id INTEGER NOT NULL,
                    edge_type TEXT NOT NULL,
                    sequence_id INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (from_node_id, to_node_id, edge_type)
                );
                CREATE INDEX IF NOT EXISTS idx_index_graph_edges_sequence
                    ON index_graph_edges(sequence_id);
                """
            )

    def _upsert_event(self, connection, projection_name: str, event: dict[str, Any]) -> bool:
        numeric_key = _projection_numeric_key(projection_name, event)
        if not _event_in_projection(projection_name, event):
            return False
        if projection_name in KEYSTONE_PROJECTIONS and numeric_key is not None:
            identity = _projection_identity(projection_name, event)
            if identity is None:
                raise RuntimeError(f"Missing logical identity for {projection_name}")
            logical_key = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
            try:
                connection.execute(
                    """
                    INSERT INTO index_projection_keys(
                        projection_name, numeric_key, logical_key, created_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(projection_name, logical_key) DO NOTHING
                    """,
                    (
                        projection_name,
                        numeric_key,
                        logical_key,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise RuntimeError(
                    f"KEYSTONE key collision in {projection_name} for {logical_key}"
                ) from exc
        if projection_name == QIHSE_PROJECTION:
            text_content = _text_content(event)
        elif projection_name == FTS_PROJECTION:
            text_content = _fts_text_content(event)
        else:
            text_content = None
        vector_json = json.dumps(_text_vector(text_content), separators=(",", ":")) if text_content is not None else None
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO index_projection_records (
                projection_name, sequence_id, source_table, source_key, event_type,
                source_revision, content_hash, numeric_key, text_content, vector_json,
                payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(projection_name, sequence_id) DO UPDATE SET
                source_table=excluded.source_table,
                source_key=excluded.source_key,
                event_type=excluded.event_type,
                source_revision=excluded.source_revision,
                content_hash=excluded.content_hash,
                numeric_key=excluded.numeric_key,
                text_content=excluded.text_content,
                vector_json=excluded.vector_json,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                projection_name,
                int(event["sequence_id"]),
                event["source_table"],
                event["source_key"],
                event["event_type"],
                event.get("source_revision"),
                _content_hash(event),
                numeric_key,
                text_content,
                vector_json,
                _canonical_payload(event),
                now,
            ),
        )
        if projection_name == FTS_PROJECTION:
            sequence_id = int(event["sequence_id"])
            payload = event.get("payload", {})
            channel_id = payload.get("channel_id") if isinstance(payload, dict) else None
            connection.execute("DELETE FROM index_projection_fts WHERE rowid=?", (sequence_id,))
            connection.execute(
                """
                INSERT INTO index_projection_fts(
                    rowid, sequence_id, source_table, source_key, channel_id, text_content
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence_id,
                    sequence_id,
                    str(event["source_table"]),
                    str(event["source_key"]),
                    channel_id,
                    text_content,
                ),
            )
        elif projection_name == GRAPH_PROJECTION:
            nodes, edges = _graph_records(event)
            for node in nodes:
                existing = connection.execute(
                    "SELECT node_key FROM index_graph_nodes WHERE node_id=?",
                    (node["node_id"],),
                ).fetchone()
                if existing is not None and existing["node_key"] != node["node_key"]:
                    raise RuntimeError(f"graph node ID collision for {node['node_key']}")
                connection.execute(
                    """
                    INSERT INTO index_graph_nodes(
                        node_id, node_key, node_type, external_id, first_sequence_id
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(node_key) DO NOTHING
                    """,
                    (
                        node["node_id"],
                        node["node_key"],
                        node["node_type"],
                        node["external_id"],
                        int(event["sequence_id"]),
                    ),
                )
            for edge in edges:
                connection.execute(
                    """
                    INSERT INTO index_graph_edges(
                        from_node_id, to_node_id, edge_type, sequence_id, metadata_json
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(from_node_id, to_node_id, edge_type) DO UPDATE SET
                        sequence_id=excluded.sequence_id,
                        metadata_json=excluded.metadata_json
                    WHERE excluded.sequence_id >= index_graph_edges.sequence_id
                    """,
                    (
                        edge["from_node_id"],
                        edge["to_node_id"],
                        edge["edge_type"],
                        int(event["sequence_id"]),
                        json.dumps(edge["metadata"], sort_keys=True, separators=(",", ":")),
                    ),
                )
        return True

    def _refresh_state(self, connection, projection_name: str, *, error: str | None = None) -> dict[str, Any]:
        rows = connection.execute(
            """
            SELECT sequence_id, content_hash
            FROM index_projection_records
            WHERE projection_name=?
            ORDER BY sequence_id
            """,
            (projection_name,),
        ).fetchall()
        checksum = hashlib.sha256(
            "".join(str(row["sequence_id"]) + row["content_hash"] for row in rows).encode("ascii")
        ).hexdigest()
        last_sequence = int(rows[-1]["sequence_id"]) if rows else 0
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO index_projection_state (
                projection_name, projection_version, last_sequence_id, source_checksum,
                row_count, last_success_at, last_error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(projection_name) DO UPDATE SET
                projection_version=excluded.projection_version,
                last_sequence_id=excluded.last_sequence_id,
                source_checksum=excluded.source_checksum,
                row_count=excluded.row_count,
                last_success_at=excluded.last_success_at,
                last_error=excluded.last_error,
                updated_at=excluded.updated_at
            """,
            (
                projection_name,
                projection_name.rsplit(".", 1)[-1],
                last_sequence,
                checksum,
                len(rows),
                None if error else now,
                error,
                now,
            ),
        )
        return {"projection": projection_name, "rows": len(rows), "checksum": checksum, "last_sequence_id": last_sequence}

    def process(self, *, batch_size: int = 100, lease_seconds: int = 300) -> dict[str, Any]:
        if batch_size < 1 or lease_seconds < 1:
            raise ValueError("batch_size and lease_seconds must be positive")
        lock_timeout = max(_PROJECTOR_LOCK_TIMEOUT_SECONDS, float(lease_seconds))
        try:
            with NativeStoreLock(self.projector_lock_path, timeout=lock_timeout):
                return self._process_locked(
                    batch_size=batch_size,
                    lease_seconds=lease_seconds,
                )
        except NativeStoreLockTimeout as exc:
            return {
                "ok": False,
                "claimed": 0,
                "processed": 0,
                "failed": 0,
                "failures": [],
                "projections": [],
                "qihse_native": None,
                "graph_native": None,
                "error": f"projector ordering lock timed out: {exc}",
            }

    def _process_locked(
        self,
        *,
        batch_size: int,
        lease_seconds: int,
    ) -> dict[str, Any]:
        events = self.outbox.claim(batch_size=batch_size, lease_seconds=lease_seconds)
        failures: list[dict[str, Any]] = []
        touched: set[str] = set()
        projected_events: list[dict[str, Any]] = []
        states: list[dict[str, Any]] = []
        native: dict[str, Any] | None = None
        graph_native: dict[str, Any] | None = None
        with self._connection() as connection:
            for event in events:
                sequence_id = int(event["sequence_id"])
                savepoint = f"event_{sequence_id}"
                event_touched: set[str] = set()
                connection.execute(f"SAVEPOINT {savepoint}")
                try:
                    for projection_name in PROJECTIONS:
                        if self._upsert_event(connection, projection_name, event):
                            event_touched.add(projection_name)
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    touched.update(event_touched)
                    projected_events.append(event)
                except Exception as exc:
                    connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    message = f"{type(exc).__name__}: {exc}"[:1000]
                    failures.append({"sequence_id": sequence_id, "error": message})
            if touched:
                states = [self._refresh_state(connection, name) for name in sorted(touched)]
                if QIHSE_PROJECTION in touched:
                    rows = connection.execute(
                        """
                        SELECT * FROM index_projection_records
                        WHERE projection_name=? AND sequence_id IN ({})
                        ORDER BY sequence_id
                        """.format(",".join("?" for _ in projected_events)),
                        (QIHSE_PROJECTION, *(int(event["sequence_id"]) for event in projected_events)),
                    ).fetchall()
                if GRAPH_PROJECTION in touched:
                    graph_rows = connection.execute(
                        """
                        SELECT * FROM index_projection_records
                        WHERE projection_name=? AND sequence_id IN ({})
                        ORDER BY sequence_id
                        """.format(",".join("?" for _ in projected_events)),
                        (GRAPH_PROJECTION, *(int(event["sequence_id"]) for event in projected_events)),
                    ).fetchall()
            else:
                rows = []
                graph_rows = []
        native_phases = sum(
            projection_name in touched
            for projection_name in (QIHSE_PROJECTION, GRAPH_PROJECTION)
        )
        phase_timeout = (
            max(0.25, lease_seconds * 0.8 / native_phases)
            if native_phases
            else None
        )
        if QIHSE_PROJECTION in touched:
            native = self._sync_qihse(
                rows,
                rebuild=False,
                timeout_limit=phase_timeout,
            )
        if GRAPH_PROJECTION in touched:
            graph_native = self._sync_graph(
                graph_rows,
                rebuild=False,
                timeout_limit=phase_timeout,
            )
        native_ok = (
            (native is None or bool(native.get("ok")))
            and (graph_native is None or bool(graph_native.get("ok")))
        )
        if not native_ok:
            failed_native = native if native is not None and not native.get("ok") else graph_native
            message = str((failed_native or {}).get("error") or "QIHSE synchronization failed")[:1000]
            failed_projection_names = {
                projection_name
                for projection_name, result in (
                    (QIHSE_PROJECTION, native),
                    (GRAPH_PROJECTION, graph_native),
                )
                if result is not None and not result.get("ok")
            }
            with self._connection() as connection:
                failed_states: dict[str, dict[str, Any]] = {}
                for projection_name in failed_projection_names:
                    failed_states[projection_name] = self._refresh_state(
                        connection,
                        projection_name,
                        error=message,
                    )
            states = [
                failed_states.get(str(state["projection"]), state)
                for state in states
            ]
            failures.extend(
                {"sequence_id": int(event["sequence_id"]), "error": message}
                for event in projected_events
            )
        completion_results = {
            int(event["sequence_id"]): None if native_ok else message
            for event in projected_events
        }
        completion_results.update({
            int(failure["sequence_id"]): str(failure["error"])
            for failure in failures
        })
        self.outbox.complete_batch(
            completion_results,
            claim_tokens={
                int(event["sequence_id"]): str(event["claim_token"])
                for event in events
            },
        )
        processed = len(projected_events) if native_ok else 0
        return {
            "ok": not failures and native_ok,
            "claimed": len(events),
            "processed": processed,
            "failed": len(failures),
            "failures": failures,
            "projections": states,
            "qihse_native": native,
            "graph_native": graph_native,
        }

    def drain(
        self,
        *,
        batch_size: int = 1000,
        lease_seconds: int = 300,
        max_batches: int = 0,
    ) -> dict[str, Any]:
        if max_batches < 0:
            raise ValueError("max_batches must be non-negative")
        batches = 0
        claimed = 0
        processed = 0
        failed = 0
        ok = True
        last_result: dict[str, Any] | None = None
        last_productive_result: dict[str, Any] | None = None
        while max_batches == 0 or batches < max_batches:
            result = self.process(batch_size=batch_size, lease_seconds=lease_seconds)
            last_result = result
            batches += 1
            claimed += int(result["claimed"])
            processed += int(result["processed"])
            failed += int(result["failed"])
            ok = ok and bool(result.get("ok"))
            if result["claimed"]:
                last_productive_result = result
            if not result.get("ok") and result["claimed"] == 0:
                break
            if result["claimed"] == 0:
                break
        overall_ok = ok and failed == 0
        return {
            "ok": overall_ok,
            "batches": batches,
            "claimed": claimed,
            "processed": processed,
            "failed": failed,
            "drained": bool(
                overall_ok
                and last_result
                and last_result["claimed"] == 0
            ),
            "last_batch": last_productive_result or last_result,
        }

    def rebuild(self, *, projection: str = "all") -> dict[str, Any]:
        names = _projection_names(projection)
        try:
            with NativeStoreLock(
                self.projector_lock_path,
                timeout=_PROJECTOR_LOCK_TIMEOUT_SECONDS,
            ):
                events = self.outbox.events()
                with self._connection() as connection:
                    placeholders = ",".join("?" for _ in names)
                    connection.execute(
                        f"DELETE FROM index_projection_records WHERE projection_name IN ({placeholders})",
                        names,
                    )
                    connection.execute(
                        f"DELETE FROM index_projection_keys WHERE projection_name IN ({placeholders})",
                        names,
                    )
                    if FTS_PROJECTION in names:
                        connection.execute("DELETE FROM index_projection_fts")
                    if GRAPH_PROJECTION in names:
                        connection.execute("DELETE FROM index_graph_edges")
                        connection.execute("DELETE FROM index_graph_nodes")
                    for event in events:
                        for projection_name in names:
                            self._upsert_event(connection, projection_name, event)
                    states = [self._refresh_state(connection, name) for name in names]
                    qihse_rows = connection.execute(
                        "SELECT * FROM index_projection_records WHERE projection_name=? ORDER BY sequence_id",
                        (QIHSE_PROJECTION,),
                    ).fetchall() if QIHSE_PROJECTION in names else []
                    graph_rows = connection.execute(
                        "SELECT * FROM index_projection_records WHERE projection_name=? ORDER BY sequence_id",
                        (GRAPH_PROJECTION,),
                    ).fetchall() if GRAPH_PROJECTION in names else []
                native = (
                    self._sync_qihse(qihse_rows, rebuild=True)
                    if QIHSE_PROJECTION in names
                    else None
                )
                graph_native = (
                    self._sync_graph(graph_rows, rebuild=True)
                    if GRAPH_PROJECTION in names
                    else None
                )
                native_ok = (
                    (native is None or bool(native.get("ok")))
                    and (graph_native is None or bool(graph_native.get("ok")))
                )
                if not native_ok:
                    native_errors = {
                        QIHSE_PROJECTION: (
                            str(native.get("error") or "QIHSE synchronization failed")
                            if native is not None and not native.get("ok")
                            else None
                        ),
                        GRAPH_PROJECTION: (
                            str(graph_native.get("error") or "QIHSE graph synchronization failed")
                            if graph_native is not None and not graph_native.get("ok")
                            else None
                        ),
                    }
                    with self._connection() as connection:
                        states = [
                            self._refresh_state(
                                connection,
                                name,
                                error=native_errors.get(name),
                            )
                            for name in names
                        ]
                return {
                    "ok": native_ok,
                    "events": len(events),
                    "projections": states,
                    "qihse_native": native,
                    "graph_native": graph_native,
                }
        except NativeStoreLockTimeout as exc:
            return {
                "ok": False,
                "events": 0,
                "projections": [],
                "qihse_native": None,
                "graph_native": None,
                "error": f"projector ordering lock timed out: {exc}",
            }

    def _sync_qihse(
        self,
        rows: list[Any],
        *,
        rebuild: bool,
        timeout_limit: float | None = None,
    ) -> dict[str, Any]:
        timeout = _native_sync_timeout(len(rows), timeout_limit=timeout_limit)
        command = [
            sys.executable,
            "-m",
            "tgarchive.db.index_native_probe",
            "--action",
            "sync",
            "--db",
            str(self.database),
            "--projection",
            QIHSE_PROJECTION,
            "--sample-size",
            "1",
        ]
        if rows and not rebuild:
            command.extend((
                "--sequence-ids",
                json.dumps([int(row["sequence_id"]) for row in rows], separators=(",", ":")),
            ))
        if rebuild:
            command.append("--rebuild")
        try:
            completed = _run_native_command(
                command,
                store_path=self.qihse_path,
                timeout=timeout,
            )
        except (NativeStoreLockTimeout, OSError, subprocess.TimeoutExpired) as exc:
            return {
                "available": False,
                "ok": False,
                "path": str(self.qihse_path),
                "error": (
                    str(exc)
                    if isinstance(exc, (NativeStoreLockTimeout, OSError))
                    else f"QIHSE synchronization timed out after {timeout:g} seconds"
                ),
            }
        marker = "SPECTRA_NATIVE_PROBE="
        payload_line = next(
            (line[len(marker):] for line in reversed(completed.stdout.splitlines()) if line.startswith(marker)),
            None,
        )
        if completed.returncode != 0 or payload_line is None:
            detail = completed.stderr.strip().splitlines()
            return {
                "available": False,
                "ok": False,
                "path": str(self.qihse_path),
                "returncode": completed.returncode,
                "error": detail[-1] if detail else "QIHSE synchronization exited without a result",
            }
        try:
            result = json.loads(payload_line)
            if not isinstance(result, dict):
                raise ValueError("native result must be an object")
            return result
        except (ValueError, json.JSONDecodeError) as exc:
            return {
                "available": False,
                "ok": False,
                "path": str(self.qihse_path),
                "error": f"invalid QIHSE synchronization response: {exc}",
            }

    def _sync_graph(
        self,
        rows: list[Any],
        *,
        rebuild: bool,
        timeout_limit: float | None = None,
    ) -> dict[str, Any]:
        timeout = _native_sync_timeout(len(rows), timeout_limit=timeout_limit)
        command = [
            sys.executable,
            "-m",
            "tgarchive.db.index_native_probe",
            "--action",
            "graph-sync",
            "--db",
            str(self.database),
            "--projection",
            GRAPH_PROJECTION,
            "--sample-size",
            "1",
        ]
        if rows and not rebuild:
            command.extend((
                "--sequence-ids",
                json.dumps([int(row["sequence_id"]) for row in rows], separators=(",", ":")),
            ))
        if rebuild:
            command.append("--rebuild")
        try:
            completed = _run_native_command(
                command,
                store_path=self.graph_path,
                timeout=timeout,
            )
        except (NativeStoreLockTimeout, OSError, subprocess.TimeoutExpired) as exc:
            return {
                "available": False,
                "ok": False,
                "path": str(self.graph_path),
                "error": (
                    str(exc)
                    if isinstance(exc, (NativeStoreLockTimeout, OSError))
                    else f"QIHSE graph synchronization timed out after {timeout:g} seconds"
                ),
            }
        marker = "SPECTRA_NATIVE_PROBE="
        payload_line = next(
            (line[len(marker):] for line in reversed(completed.stdout.splitlines()) if line.startswith(marker)),
            None,
        )
        if completed.returncode != 0 or payload_line is None:
            detail = completed.stderr.strip().splitlines()
            return {
                "available": False,
                "ok": False,
                "path": str(self.graph_path),
                "returncode": completed.returncode,
                "error": detail[-1] if detail else "QIHSE graph synchronization exited without a result",
            }
        try:
            result = json.loads(payload_line)
            if not isinstance(result, dict):
                raise ValueError("native result must be an object")
            return result
        except (ValueError, json.JSONDecodeError) as exc:
            return {
                "available": False,
                "ok": False,
                "path": str(self.graph_path),
                "error": f"invalid QIHSE graph response: {exc}",
            }

    def verify(self, *, projection: str = "all", native: bool = True, sample_size: int = 16) -> dict[str, Any]:
        if sample_size < 1:
            raise ValueError("sample_size must be positive")
        names = _projection_names(projection)
        events = self.outbox.events()
        results = [self._verify_projection(name, events, native=native, sample_size=sample_size) for name in names]
        return {"ok": all(result["ok"] for result in results), "projections": results}

    def search(self, query: str, *, limit: int = 10, channel_id: int | None = None) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if limit < 1:
            raise ValueError("limit must be positive")
        command = [
            sys.executable,
            "-m",
            "tgarchive.db.index_native_probe",
            "--action",
            "search",
            "--db",
            str(self.database),
            "--projection",
            QIHSE_PROJECTION,
            "--sample-size",
            str(limit),
            "--query-vector",
            json.dumps(_text_vector(query), separators=(",", ":")),
        ]
        try:
            completed = _run_native_command(
                command,
                store_path=self.qihse_path,
                timeout=30,
            )
        except (NativeStoreLockTimeout, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"QIHSE semantic search timed out: {exc}") from exc
        marker = "SPECTRA_NATIVE_PROBE="
        payload_line = next(
            (line[len(marker):] for line in reversed(completed.stdout.splitlines()) if line.startswith(marker)),
            None,
        )
        if completed.returncode != 0 or payload_line is None:
            raise RuntimeError("QIHSE semantic search failed")
        matches = json.loads(payload_line).get("matches", [])
        sequence_ids = [int(match["id"]) for match in matches]
        if not sequence_ids:
            return []
        placeholders = ",".join("?" for _ in sequence_ids)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT sequence_id, source_table, source_key, payload_json
                FROM index_projection_records
                WHERE projection_name=? AND sequence_id IN ({placeholders})
                """,
                (QIHSE_PROJECTION, *sequence_ids),
            ).fetchall()
        by_id = {int(row["sequence_id"]): row for row in rows}
        results = []
        for match in matches:
            row = by_id.get(int(match["id"]))
            if row is None:
                continue
            payload = json.loads(row["payload_json"])
            if channel_id is not None and payload.get("channel_id") != channel_id:
                continue
            results.append({
                "sequence_id": int(row["sequence_id"]),
                "source_table": row["source_table"],
                "source_key": row["source_key"],
                "score": float(match["score"]),
                "payload": payload,
            })
        return results

    def fulltext_search(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        channel_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset must be non-negative")
        clauses = ["index_projection_fts MATCH ?"]
        parameters: list[Any] = [query.strip()]
        if channel_id is not None:
            clauses.append("f.channel_id = ?")
            parameters.append(channel_id)
        parameters.extend((limit, offset))
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    f"""
                    SELECT f.sequence_id, f.source_table, f.source_key,
                           bm25(index_projection_fts) AS rank, p.payload_json
                    FROM index_projection_fts AS f
                    JOIN index_projection_records AS p
                      ON p.projection_name=? AND p.sequence_id=f.sequence_id
                    WHERE {' AND '.join(clauses)}
                      AND LOWER(p.event_type) NOT IN ('delete', 'deleted', 'remove')
                      AND NOT EXISTS (
                          SELECT 1
                          FROM index_projection_records AS newer
                          WHERE newer.projection_name=p.projection_name
                            AND newer.source_table=p.source_table
                            AND newer.source_key=p.source_key
                            AND newer.sequence_id>p.sequence_id
                      )
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                    """,
                    (FTS_PROJECTION, *parameters),
                ).fetchall()
        except sqlite3.Error as exc:
            raise ValueError(f"invalid full-text query: {exc}") from exc
        return [
            {
                "sequence_id": int(row["sequence_id"]),
                "source_table": row["source_table"],
                "source_key": row["source_key"],
                "score": float(-row["rank"]),
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def graph_neighbors(
        self,
        *,
        node_type: str,
        external_id: str,
        edge_type: str | None = None,
        direction: str = "both",
        limit: int = 100,
    ) -> dict[str, Any]:
        if not node_type.strip() or not external_id.strip():
            raise ValueError("node_type and external_id must be non-empty")
        if direction not in {"outgoing", "incoming", "both"}:
            raise ValueError("direction must be outgoing, incoming, or both")
        node_key = f"{node_type}:{external_id}"
        with self._connection() as connection:
            node = connection.execute(
                "SELECT * FROM index_graph_nodes WHERE node_key=?",
                (node_key,),
            ).fetchone()
        if node is None:
            return {"found": False, "node_key": node_key, "records": []}
        command = [
            sys.executable,
            "-m",
            "tgarchive.db.index_native_probe",
            "--action",
            "graph-query",
            "--db",
            str(self.database),
            "--projection",
            GRAPH_PROJECTION,
            "--node-id",
            str(int(node["node_id"])),
            "--direction",
            direction,
            "--sample-size",
            str(limit),
        ]
        if edge_type:
            command.extend(("--edge-type", edge_type))
        try:
            completed = _run_native_command(
                command,
                store_path=self.graph_path,
                timeout=30,
            )
        except (NativeStoreLockTimeout, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"QIHSE graph query timed out: {exc}") from exc
        marker = "SPECTRA_NATIVE_PROBE="
        payload_line = next(
            (line[len(marker):] for line in reversed(completed.stdout.splitlines()) if line.startswith(marker)),
            None,
        )
        if completed.returncode != 0 or payload_line is None:
            detail = completed.stderr.strip().splitlines()
            raise RuntimeError(detail[-1] if detail else "QIHSE graph query failed")
        native = json.loads(payload_line)
        node_ids = {
            int(record[key])
            for record in native.get("records", [])
            for key in ("from_node_id", "to_node_id")
        }
        with self._connection() as connection:
            if node_ids:
                placeholders = ",".join("?" for _ in node_ids)
                nodes = connection.execute(
                    f"SELECT * FROM index_graph_nodes WHERE node_id IN ({placeholders})",
                    tuple(node_ids),
                ).fetchall()
            else:
                nodes = []
        by_id = {
            int(item["node_id"]): {
                "node_key": item["node_key"],
                "node_type": item["node_type"],
                "external_id": item["external_id"],
            }
            for item in nodes
        }
        records = [
            record | {
                "from_node": by_id.get(int(record["from_node_id"])),
                "to_node": by_id.get(int(record["to_node_id"])),
            }
            for record in native.get("records", [])
        ]
        return {
            "found": True,
            "node_key": node_key,
            "node_id": int(node["node_id"]),
            "records": records,
            "native": {key: value for key, value in native.items() if key != "records"},
        }

    def lookup(self, *, channel_id: int, message_id: int) -> dict[str, Any]:
        numeric_key = keystone_compound_key(channel_id, message_id)
        native = self._keystone_lookup(numeric_key)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT projection_name, sequence_id, source_table, source_key, payload_json
                FROM index_projection_records
                WHERE projection_name IN (?, ?) AND numeric_key=?
                ORDER BY projection_name, sequence_id
                """,
                (KEYSTONE_PROJECTION, MEDIA_MANIFEST_PROJECTION, numeric_key),
            ).fetchall()
        records = [
            {
                "sequence_id": int(row["sequence_id"]),
                "projection": row["projection_name"],
                "source_table": row["source_table"],
                "source_key": row["source_key"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
            if (
                json.loads(row["payload_json"]).get("channel_id") == channel_id
                and json.loads(row["payload_json"]).get("message_id") == message_id
            )
        ]
        return {
            "channel_id": channel_id,
            "message_id": message_id,
            "numeric_key": numeric_key,
            "found": bool(records),
            "native": native,
            "records": records,
        }

    def lookup_record(
        self,
        *,
        projection: str,
        namespace: str,
        external_id: str,
    ) -> dict[str, Any]:
        names = _projection_names(projection)
        supported = {
            CHECKPOINT_PROJECTION,
            EVENT_PROJECTION,
            EXPORT_RECORD_PROJECTION,
            ARCHIVE_MEMBER_PROJECTION,
        }
        if len(names) != 1 or names[0] not in supported:
            raise ValueError(
                "record lookup projection must be checkpoints, events, exports, or archive-members"
            )
        projection_name = names[0]
        numeric_key = keystone_record_key(
            projection_name,
            namespace,
            external_id,
        )
        native = self._keystone_lookup(
            numeric_key,
            projection_name=projection_name,
        )
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT projection_name, sequence_id, source_table, source_key, payload_json
                FROM index_projection_records
                WHERE projection_name=? AND numeric_key=?
                ORDER BY sequence_id
                """,
                (projection_name, numeric_key),
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            identity = _projection_identity(
                projection_name,
                {
                    "source_table": row["source_table"],
                    "source_key": row["source_key"],
                    "payload": payload,
                },
            )
            if identity != (namespace, external_id):
                continue
            records.append({
                "sequence_id": int(row["sequence_id"]),
                "projection": row["projection_name"],
                "source_table": row["source_table"],
                "source_key": row["source_key"],
                "payload": payload,
            })
        return {
            "projection": projection_name,
            "namespace": namespace,
            "external_id": external_id,
            "numeric_key": numeric_key,
            "found": bool(records),
            "native": native,
            "records": records,
        }

    def _verify_projection(
        self,
        projection_name: str,
        events: list[dict[str, Any]],
        *,
        native: bool,
        sample_size: int,
    ) -> dict[str, Any]:
        expected = [
            event
            for event in events
            if _event_in_projection(projection_name, event)
        ]
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM index_projection_records WHERE projection_name=? ORDER BY sequence_id",
                (projection_name,),
            ).fetchall()
            state = connection.execute(
                "SELECT * FROM index_projection_state WHERE projection_name=?",
                (projection_name,),
            ).fetchone()
            key_rows = connection.execute(
                "SELECT numeric_key, logical_key FROM index_projection_keys WHERE projection_name=?",
                (projection_name,),
            ).fetchall() if projection_name in KEYSTONE_PROJECTIONS else []
        expected_checksum = hashlib.sha256(
            "".join(str(event["sequence_id"]) + _content_hash(event) for event in expected).encode("ascii")
        ).hexdigest()
        actual_checksum = hashlib.sha256(
            "".join(str(row["sequence_id"]) + row["content_hash"] for row in rows).encode("ascii")
        ).hexdigest()
        if projection_name == FTS_PROJECTION:
            native_result = self._verify_fts(rows, sample_size)
        elif projection_name == GRAPH_PROJECTION:
            native_result = self._verify_graph(sample_size)
        elif native:
            native_result = self._verify_native(projection_name, sample_size)
        else:
            native_result = {
                "requested": False,
                "available": None,
                "ok": True,
                "samples": 0,
            }
        state_matches = (
            not rows and not expected and state is None
        ) or bool(
            state
            and int(state["row_count"]) == len(rows)
            and state["source_checksum"] == actual_checksum
        )
        key_map_matches = (
            projection_name not in KEYSTONE_PROJECTIONS
            or (
                len(key_rows) == len({int(row["numeric_key"]) for row in rows})
                and {int(row["numeric_key"]) for row in key_rows}
                == {int(row["numeric_key"]) for row in rows}
            )
        )
        ok = (
            len(expected) == len(rows)
            and expected_checksum == actual_checksum
            and state_matches
            and key_map_matches
            and native_result["ok"]
        )
        return {
            "projection": projection_name,
            "ok": ok,
            "expected_rows": len(expected),
            "actual_rows": len(rows),
            "expected_checksum": expected_checksum,
            "actual_checksum": actual_checksum,
            "state_matches": state_matches,
            "key_map_matches": key_map_matches,
            "native": native_result,
        }

    def _verify_fts(self, rows: list[Any], sample_size: int) -> dict[str, Any]:
        with self._connection() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM index_projection_fts").fetchone()[0])
            samples = rows[:sample_size]
            found = sum(
                int(connection.execute(
                    "SELECT COUNT(*) FROM index_projection_fts WHERE rowid=?",
                    (int(row["sequence_id"]),),
                ).fetchone()[0])
                for row in samples
            )
        return {
            "requested": True,
            "available": True,
            "ok": count == len(rows) and found == len(samples),
            "samples": len(samples),
        }

    def _verify_graph(self, sample_size: int) -> dict[str, Any]:
        with self._connection() as connection:
            edges = connection.execute(
                "SELECT * FROM index_graph_edges ORDER BY from_node_id, to_node_id, edge_type LIMIT ?",
                (sample_size,),
            ).fetchall()
            group_limits = {
                (int(edge["from_node_id"]), str(edge["edge_type"])): int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM index_graph_edges
                        WHERE from_node_id=? AND edge_type=?
                        """,
                        (int(edge["from_node_id"]), str(edge["edge_type"])),
                    ).fetchone()[0]
                )
                for edge in edges
            }
        groups: dict[tuple[int, str | None], list[Any]] = {}
        if edges:
            for edge in edges:
                key = (int(edge["from_node_id"]), str(edge["edge_type"]))
                groups.setdefault(key, []).append(edge)
        else:
            groups[(0, None)] = []

        checked = 0
        marker = "SPECTRA_NATIVE_PROBE="
        for (from_node_id, edge_type), expected_edges in groups.items():
            command = [
                sys.executable,
                "-m",
                "tgarchive.db.index_native_probe",
                "--action",
                "graph-query",
                "--db",
                str(self.database),
                "--projection",
                GRAPH_PROJECTION,
                "--node-id",
                str(from_node_id),
                "--direction",
                "outgoing",
                "--sample-size",
                str(group_limits.get((from_node_id, edge_type), 1)),
            ]
            if edge_type is not None:
                command.extend(("--edge-type", edge_type))
            try:
                completed = _run_native_command(
                    command,
                    store_path=self.graph_path,
                    timeout=30,
                )
            except (NativeStoreLockTimeout, OSError, subprocess.TimeoutExpired) as exc:
                return {
                    "requested": True,
                    "available": False,
                    "ok": False,
                    "samples": checked,
                    "error": str(exc),
                }
            payload_line = next(
                (
                    line[len(marker):]
                    for line in reversed(completed.stdout.splitlines())
                    if line.startswith(marker)
                ),
                None,
            )
            if completed.returncode != 0 or payload_line is None:
                detail = completed.stderr.strip().splitlines()
                return {
                    "requested": True,
                    "available": False,
                    "ok": False,
                    "samples": checked,
                    "returncode": completed.returncode,
                    "error": detail[-1] if detail else "QIHSE graph probe exited without a result",
                }
            try:
                native = json.loads(payload_line)
                if not isinstance(native, dict) or native.get("ok") is not True:
                    raise ValueError("QIHSE graph probe reported failure")
                records = native.get("records", [])
                if not isinstance(records, list):
                    raise ValueError("QIHSE graph probe records must be a list")
                native_by_identity = {
                    (
                        int(record["from_node_id"]),
                        int(record["to_node_id"]),
                        str(record["edge_type"]),
                    ): json.dumps(
                        record.get("metadata", {}),
                        default=str,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    for record in records
                    if isinstance(record, dict)
                }
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                return {
                    "requested": True,
                    "available": False,
                    "ok": False,
                    "samples": checked,
                    "error": f"invalid QIHSE graph response: {exc}",
                }
            for edge in expected_edges:
                identity = (
                    int(edge["from_node_id"]),
                    int(edge["to_node_id"]),
                    str(edge["edge_type"]),
                )
                try:
                    expected_metadata = json.dumps(
                        json.loads(str(edge["metadata_json"])),
                        default=str,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    return {
                        "requested": True,
                        "available": True,
                        "ok": False,
                        "samples": checked,
                        "error": f"invalid persisted graph metadata: {exc}",
                    }
                checked += 1
                if native_by_identity.get(identity) != expected_metadata:
                    return {
                        "requested": True,
                        "available": True,
                        "ok": False,
                        "samples": checked,
                        "error": "QIHSE graph edge identity or metadata mismatch",
                    }
        return {
            "requested": True,
            "available": True,
            "ok": True,
            "samples": checked,
        }

    def _verify_native(self, projection_name: str, sample_size: int) -> dict[str, Any]:
        command = [
            sys.executable,
            "-m",
            "tgarchive.db.index_native_probe",
            "--db",
            str(self.database),
            "--projection",
            projection_name,
            "--sample-size",
            str(sample_size),
        ]
        try:
            if projection_name == QIHSE_PROJECTION:
                completed = _run_native_command(
                    command,
                    store_path=self.qihse_path,
                    timeout=30,
                )
            else:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
        except (NativeStoreLockTimeout, OSError, subprocess.TimeoutExpired) as exc:
            return {
                "requested": True,
                "available": False,
                "ok": False,
                "samples": 0,
                "error": (
                    str(exc)
                    if isinstance(exc, (NativeStoreLockTimeout, OSError))
                    else "native verification timed out after 30 seconds"
                ),
            }
        marker = "SPECTRA_NATIVE_PROBE="
        payload_line = next(
            (line[len(marker):] for line in reversed(completed.stdout.splitlines()) if line.startswith(marker)),
            None,
        )
        if completed.returncode != 0 or payload_line is None:
            detail = completed.stderr.strip().splitlines()
            suffix = detail[-1] if detail else "native probe exited without a result"
            return {
                "requested": True,
                "available": False,
                "ok": False,
                "samples": 0,
                "returncode": completed.returncode,
                "error": suffix,
            }
        try:
            result = json.loads(payload_line)
            if not isinstance(result, dict) or "ok" not in result:
                raise ValueError("native verification result must contain ok")
            return result
        except (ValueError, json.JSONDecodeError) as exc:
            return {
                "requested": True,
                "available": False,
                "ok": False,
                "samples": 0,
                "error": f"invalid native probe response: {exc}",
            }

    @staticmethod
    def verify_native_in_process(
        projection_name: str,
        rows: list[Any],
        sample_size: int,
        *,
        qihse_path: Path | None = None,
    ) -> dict[str, Any]:
        try:
            if projection_name in KEYSTONE_PROJECTIONS:
                from ..search.keystone_bindings import KEYSTONE_WORKLOAD_IDS, KeystoneSearchEngine, keystone_available

                if not keystone_available():
                    return {"requested": True, "available": False, "ok": False, "samples": 0, "error": "KEYSTONE unavailable"}
                values = sorted({int(row["numeric_key"]) for row in rows if row["numeric_key"] is not None})
                samples = values[:sample_size]
                engine = KeystoneSearchEngine(KEYSTONE_WORKLOAD_IDS)
                positions = engine.search_batch(values, samples)
                ok = all(position is not None and values[position] == key for key, position in zip(samples, positions))
                return {"requested": True, "available": True, "ok": ok, "samples": len(samples), "stats": engine.get_stats()}

            from ..search.qihse_vector_backend import QihseVectorIndex

            vectors = [json.loads(row["vector_json"]) for row in rows]
            indexes = list(range(min(sample_size, len(rows))))
            rows_by_id = {int(row["sequence_id"]): row for row in rows}
            if len(rows_by_id) != len(rows):
                raise RuntimeError("QIHSE projection contains duplicate sequence IDs")
            vector_groups: dict[tuple[float, ...], int] = {}
            for vector in vectors:
                vector_key = tuple(float(value) for value in vector)
                vector_groups[vector_key] = vector_groups.get(vector_key, 0) + 1
            ok = True
            if qihse_path is None:
                raise RuntimeError("QIHSE probe did not receive its index path")
            with QihseVectorIndex(qihse_path) as engine:
                for index in indexes:
                    expected_row = rows[index]
                    expected_id = int(expected_row["sequence_id"])
                    expected_identity = (
                        str(expected_row["source_table"]),
                        str(expected_row["source_key"]),
                    )
                    duplicate_count = vector_groups[tuple(float(value) for value in vectors[index])]
                    matches = engine.search(vectors[index], limit=duplicate_count)
                    matched = next(
                        (match for match in matches if int(match["id"]) == expected_id),
                        None,
                    )
                    matched_id = int(matched["id"]) if matched is not None else None
                    persisted_row = rows_by_id.get(matched_id) if matched_id is not None else None
                    persisted_identity = (
                        str(persisted_row["source_table"]),
                        str(persisted_row["source_key"]),
                    ) if persisted_row is not None else None
                    if (
                        matched is None
                        or not matches
                        or persisted_identity != expected_identity
                        or not math.isclose(
                            float(matched["score"]),
                            float(matches[0]["score"]),
                            rel_tol=1e-6,
                            abs_tol=1e-6,
                        )
                    ):
                        ok = False
                        break
                return {
                    "requested": True,
                    "available": True,
                    "ok": ok,
                    "samples": len(indexes),
                    "library": str(engine.library_path),
                }
        except Exception as exc:
            return {
                "requested": True,
                "available": False,
                "ok": False,
                "samples": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
