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

import logging

from ..sqlite_runtime import connect_sqlite
from .index_outbox import IndexOutbox
from .native_store_lock import NativeStoreLock, NativeStoreLockTimeout

logger = logging.getLogger(__name__)


KEYSTONE_PROJECTION = "keystone.ids.v1"
MEDIA_MANIFEST_PROJECTION = "keystone.media_manifest.v1"
CHECKPOINT_PROJECTION = "keystone.checkpoints.v1"
EVENT_PROJECTION = "keystone.events.v1"
EXPORT_RECORD_PROJECTION = "keystone.export_records.v1"
ARCHIVE_MEMBER_PROJECTION = "keystone.archive_members.v1"
QIHSE_PROJECTION = "qihse.content.v1"
FTS_PROJECTION = "fts.messages.v1"
GRAPH_PROJECTION = "qihse.graph.v1"
ERROR_PROJECTION = "qihse.errors.v1"
INTELLIGENCE_PROJECTION = "qihse.intelligence.v1"
SEMANTIC_PROJECTION = "qihse.semantic.v1"
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
    ERROR_PROJECTION,
    INTELLIGENCE_PROJECTION,
    SEMANTIC_PROJECTION,
)
VECTOR_DIMENSIONS = 64
_INTELLIGENCE_SOURCE_TABLES = frozenset({
    "intelligence_evidence",
    "intelligence_hypotheses",
    "intelligence_inferences",
    "intelligence_campaigns",
    "intelligence_conclusions",
    "intelligence_patterns",
})
_PERSONA_SOURCE_TABLES = frozenset({
    "persona_targets",
    "persona_examples",
    "persona_knowledge_observations",
    "persona_profile_snapshots",
})
_TOKEN_RE = re.compile(r"[A-Za-z0-9_@.+-]+")
_SENSITIVE_KEYS = {"api_hash", "password", "token", "secret", "otp", "session_secret", "private_key"}
# Memoized token → (bucket, sign) cache for _text_vector. Token vocabulary is
# small and massively repetitive across events, so caching avoids redundant
# blake2b calls. Capped at 1M entries (~100 MB worst case; realistically <10 MB).
_TOKEN_HASH_CACHE: dict[tuple[str, int], tuple[int, float]] = {}
_TOKEN_HASH_CACHE_MAX = 1_000_000
_KEYSTONE_START_TIMEOUT_SECONDS = 10.0
_KEYSTONE_LOOKUP_TIMEOUT_SECONDS = 30.0

# Source-table to relevant projections mapping.  Avoids iterating over all 11
# projections for every event when most don't apply.
_MESSAGE_TABLES = frozenset({"messages", "channel_messages"})
_GRAPH_SOURCE_TABLES = frozenset({
    "messages", "channel_messages",
    "support_network_edges", "support_network_nodes",
    "intelligence_hypotheses", "intelligence_campaigns",
})
_ERROR_SOURCE_TABLES = frozenset({"errors"})
_EVENT_SOURCE_TABLES = frozenset({"task_events", "operation_events", "operation_audit_log"})
_CHECKPOINT_SOURCE_TABLES = frozenset({"checkpoints"})
_ARCHIVE_MEMBER_SOURCE_TABLES = frozenset({"archive_members"})
_EXPORT_SOURCE_TABLES = frozenset({"channel_messages"})
_MEDIA_SOURCE_TABLES = frozenset({"media"})


def _projections_for_source_table(source_table: str) -> tuple[str, ...]:
    """Return the subset of PROJECTIONS that may apply to this source_table.

    This is a fast pre-filter. _event_in_projection() still runs inside
    _upsert_event() for payload-dependent checks.  But this avoids the
    Python function call overhead for projections that can never match.

    Env vars to skip slow projections for bulk drain speed:
      SPECTRA_SKIP_SEMANTIC=1  — skip qihse.semantic.v1 (vector upsert)
      SPECTRA_SKIP_GRAPH=1     — skip qihse.graph.v1
      SPECTRA_SKIP_NATIVE=1    — skip qihse.content.v1 (deferred native sync)
      SPECTRA_SKIP_FTS=1       — skip fts.messages.v1 (FTS5 tokenization)
      SPECTRA_SKIP_STATE_REFRESH=1 — skip SHA-256 state checksums
    """
    _skip_semantic = os.environ.get("SPECTRA_SKIP_SEMANTIC", "").strip() == "1"
    _skip_graph = os.environ.get("SPECTRA_SKIP_GRAPH", "").strip() == "1"
    _skip_native = os.environ.get("SPECTRA_SKIP_NATIVE", "").strip() == "1"
    _skip_fts = os.environ.get("SPECTRA_SKIP_FTS", "").strip() == "1"
    result: list[str] = []
    if not _skip_native:
        result.append(QIHSE_PROJECTION)
    if source_table not in _ERROR_SOURCE_TABLES:
        result.append(KEYSTONE_PROJECTION)
    if source_table in _MESSAGE_TABLES:
        if not _skip_fts:
            result.append(FTS_PROJECTION)
        if not _skip_semantic:
            result.append(SEMANTIC_PROJECTION)
    if source_table in _GRAPH_SOURCE_TABLES and not _skip_graph:
        result.append(GRAPH_PROJECTION)
    if source_table in _ERROR_SOURCE_TABLES:
        result.append(ERROR_PROJECTION)
    if source_table in _INTELLIGENCE_SOURCE_TABLES:
        result.append(INTELLIGENCE_PROJECTION)
    if source_table in _EVENT_SOURCE_TABLES:
        result.append(EVENT_PROJECTION)
    if source_table in _CHECKPOINT_SOURCE_TABLES:
        result.append(CHECKPOINT_PROJECTION)
    if source_table in _ARCHIVE_MEMBER_SOURCE_TABLES:
        result.append(ARCHIVE_MEMBER_PROJECTION)
    if source_table in _EXPORT_SOURCE_TABLES:
        result.append(EXPORT_RECORD_PROJECTION)
    if source_table in _MEDIA_SOURCE_TABLES:
        result.append(MEDIA_MANIFEST_PROJECTION)
    return tuple(result)

_NATIVE_SYNC_MIN_TIMEOUT_SECONDS = 60.0
_NATIVE_SYNC_MAX_TIMEOUT_SECONDS = 900.0
_NATIVE_SYNC_SECONDS_PER_ROW = 0.25
_NATIVE_STORE_LOCK_TIMEOUT_SECONDS = 30.0
_PROJECTOR_LOCK_TIMEOUT_SECONDS = 300.0
# Events per transaction chunk in _process_locked. The fast path uses a single
# BEGIN/COMMIT per chunk (no per-event SAVEPOINT). On failure, the chunk is
# replayed event-by-event with savepoints for failure isolation.
_TXN_CHUNK = 500
# Module-level skip flags — read once at import for _upsert_event fast path.
# When SPECTRA_SKIP_NATIVE=1, _upsert_event skips the 64-dim vector computation
# and json.dumps for QIHSE_PROJECTION records (the per-event CPU cost in fast mode).
_SKIP_NATIVE_VECTOR = os.environ.get("SPECTRA_SKIP_NATIVE", "").strip() == "1"


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


# Keep a reference to the original function so we can detect monkeypatching
# (tests replace _run_native_command to simulate native failures)
_ORIGINAL_RUN_NATIVE_COMMAND = _run_native_command


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
        "errors": (ERROR_PROJECTION,),
        ERROR_PROJECTION: (ERROR_PROJECTION,),
        "intelligence": (INTELLIGENCE_PROJECTION,),
        INTELLIGENCE_PROJECTION: (INTELLIGENCE_PROJECTION,),
        "semantic": (SEMANTIC_PROJECTION,),
        SEMANTIC_PROJECTION: (SEMANTIC_PROJECTION,),
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
        # Messages without channel_id still get a KEYSTONE anchor on
        # message_id alone, enabling O(1) cross-index lookups by ID.
        if isinstance(message_id, int) and projection_name == KEYSTONE_PROJECTION:
            return "message", str(message_id)
        # Users get KEYSTONE anchors on user_id for cross-indexing.
        user_id = payload.get("user_id")
        if isinstance(user_id, int) and projection_name == KEYSTONE_PROJECTION:
            return "user", str(user_id)
        # Media get KEYSTONE anchors on media_id for cross-indexing.
        media_id = payload.get("media_id")
        if isinstance(media_id, int) and projection_name == KEYSTONE_PROJECTION:
            return "media", str(media_id)
        # Intelligence objects get KEYSTONE anchors on their deterministic IDs
        # for O(1) cross-index lookups (evidence → content → graph).
        source_table = str(event.get("source_table") or "")
        if projection_name == KEYSTONE_PROJECTION and source_table in _INTELLIGENCE_SOURCE_TABLES:
            source_key = str(event.get("source_key") or "")
            if source_key:
                namespace = source_table.replace("intelligence_", "intel-")
                return namespace, source_key
        # Persona training-data objects get KEYSTONE anchors for O(1) lookup.
        if projection_name == KEYSTONE_PROJECTION and source_table in _PERSONA_SOURCE_TABLES:
            source_key = str(event.get("source_key") or "")
            if source_key:
                namespace = source_table.replace("persona_", "persona-").replace("_", "-")
                return namespace, source_key
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
    # Intelligence objects use deterministic hash IDs (not numeric), so
    # they need keystone_record_key to get a stable int64 KEYSTONE key.
    if (
        projection_name == KEYSTONE_PROJECTION
        and str(event.get("source_table") or "") in _INTELLIGENCE_SOURCE_TABLES
        and identity is not None
    ):
        return keystone_record_key(projection_name, *identity)
    # Persona training-data objects also use deterministic hash IDs.
    if (
        projection_name == KEYSTONE_PROJECTION
        and str(event.get("source_table") or "") in _PERSONA_SOURCE_TABLES
        and identity is not None
    ):
        return keystone_record_key(projection_name, *identity)
    return _numeric_key(event)


def _event_in_projection(projection_name: str, event: dict[str, Any]) -> bool:
    if projection_name == QIHSE_PROJECTION:
        return True
    if projection_name == FTS_PROJECTION:
        return str(event.get("source_table")) in {"messages", "channel_messages"}
    if projection_name == SEMANTIC_PROJECTION:
        return str(event.get("source_table")) in {"messages", "channel_messages"}
    if projection_name == GRAPH_PROJECTION:
        _nodes, edges = _graph_records(event)
        return bool(edges)
    if projection_name == ERROR_PROJECTION:
        payload = event.get("payload", {})
        return (
            str(event.get("source_table")) == "errors"
            and isinstance(payload, dict)
            and bool(payload.get("error_code"))
            and bool(payload.get("error_message"))
        )
    if projection_name == INTELLIGENCE_PROJECTION:
        source_table = str(event.get("source_table") or "")
        payload = event.get("payload", {})
        return (
            source_table in _INTELLIGENCE_SOURCE_TABLES
            and isinstance(payload, dict)
            and bool(event.get("source_key"))
        )
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

    # ── Intelligence hypotheses → graph edges ───────────────────────────
    # ActorHypothesis and RelationshipHypothesis create edges between
    # their subject entities.  Canonical entity IDs (e.g. "telegram:user:123")
    # are parsed into node_type + external_id for the graph.
    source_table = str(event.get("source_table") or "")
    if source_table == "intelligence_hypotheses":
        htype = str(payload.get("hypothesis_type") or "")
        prob = payload.get("probability")
        htype_upper = htype.upper().replace("-", "_")
        subject_a = payload.get("subject_a") or payload.get("subject")
        subject_b = payload.get("subject_b") or payload.get("object")
        if subject_a and subject_b:
            node_a = _add_canonical_node(add_node, subject_a)
            node_b = _add_canonical_node(add_node, subject_b)
            edge_meta = {
                "hypothesis_id": str(event.get("source_key") or ""),
                "probability": float(prob) if isinstance(prob, (int, float)) else None,
                "model": str(payload.get("model") or ""),
            }
            edges.append({
                "from_node_id": node_a["node_id"],
                "to_node_id": node_b["node_id"],
                "edge_type": htype_upper,
                "metadata": {
                    "sequence_id": int(event["sequence_id"]),
                    "source_table": source_table,
                    "source_key": str(event["source_key"]),
                    **edge_meta,
                },
            })

    # ── Campaign → graph edges linking actors to the campaign ───────────
    if source_table == "intelligence_campaigns":
        campaign_key = str(event.get("source_key") or "")
        campaign_node = add_node("campaign", campaign_key)
        for actor_id in payload.get("actors", []) or []:
            actor_node = _add_canonical_node(add_node, actor_id)
            edges.append({
                "from_node_id": actor_node["node_id"],
                "to_node_id": campaign_node["node_id"],
                "edge_type": "PART_OF_CAMPAIGN",
                "metadata": {
                    "sequence_id": int(event["sequence_id"]),
                    "source_table": source_table,
                    "source_key": campaign_key,
                },
            })
        for channel_id in payload.get("channels", []) or []:
            channel_node = _add_canonical_node(add_node, channel_id)
            edges.append({
                "from_node_id": channel_node["node_id"],
                "to_node_id": campaign_node["node_id"],
                "edge_type": "CAMPAIGN_CHANNEL",
                "metadata": {
                    "sequence_id": int(event["sequence_id"]),
                    "source_table": source_table,
                    "source_key": campaign_key,
                },
            })

    # ── Persona examples → graph edges linking example to persona target ─
    if source_table == "persona_examples":
        target_id = payload.get("target_id")
        example_id = str(event.get("source_key") or "")
        label = str(payload.get("label") or "")
        if target_id and example_id:
            target_node = add_node("persona_target", str(target_id))
            example_node = add_node("persona_example", example_id)
            edges.append({
                "from_node_id": example_node["node_id"],
                "to_node_id": target_node["node_id"],
                "edge_type": f"PERSONA_{label.upper()}",
                "metadata": {
                    "sequence_id": int(event["sequence_id"]),
                    "source_table": source_table,
                    "source_key": example_id,
                    "label": label,
                },
            })

    # ── Persona snapshots → graph edge linking snapshot to target ────────
    if source_table == "persona_profile_snapshots":
        target_id = payload.get("target_id")
        snapshot_id = str(event.get("source_key") or "")
        if target_id and snapshot_id:
            target_node = add_node("persona_target", str(target_id))
            snapshot_node = add_node("persona_snapshot", snapshot_id)
            edges.append({
                "from_node_id": snapshot_node["node_id"],
                "to_node_id": target_node["node_id"],
                "edge_type": "PERSONA_SNAPSHOT",
                "metadata": {
                    "sequence_id": int(event["sequence_id"]),
                    "source_table": source_table,
                    "source_key": snapshot_id,
                    "as_of": payload.get("as_of"),
                },
            })

    return list(nodes.values()), edges


def _add_canonical_node(add_node, canonical_id: str) -> dict[str, Any]:
    """Add a graph node from a canonical entity ID like ``telegram:user:123``.

    Falls back to a generic ``entity`` node type if the ID format is
    unrecognized.
    """
    parts = str(canonical_id).split(":")
    if len(parts) >= 3:
        node_type = parts[1]  # e.g. "user", "channel", "msg"
        external_id = ":".join(parts[2:])
    else:
        node_type = "entity"
        external_id = str(canonical_id)
    return add_node(node_type, external_id)


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


def _token_hash_bow(token: str, dimensions: int) -> tuple[int, float]:
    """Memoized token → (bucket, sign) for hash-bow vectors.

    Identical math to the inline version: blake2b(digest_size=16),
    position from first 8 bytes, sign from byte 8 bit 0.
    """
    key = (token, dimensions)
    entry = _TOKEN_HASH_CACHE.get(key)
    if entry is None:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
        entry = (
            int.from_bytes(digest[:8], "little") % dimensions,
            1.0 if digest[8] & 1 else -1.0,
        )
        if len(_TOKEN_HASH_CACHE) < _TOKEN_HASH_CACHE_MAX:
            _TOKEN_HASH_CACHE[key] = entry
    return entry


def _text_vector(text: str) -> list[float]:
    vector = [0.0] * VECTOR_DIMENSIONS
    for token in _TOKEN_RE.findall(text.lower()):
        position, sign = _token_hash_bow(token, VECTOR_DIMENSIONS)
        vector[position] += sign
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
        # Persistent native index handles — kept open for the drain loop to
        # avoid O(total_vectors) open/close/flush per batch. Flushed periodically.
        self._persistent_qihse_index: Any = None
        self._persistent_graph_index: Any = None
        self._persistent_semantic_projection: Any = None
        self._batch_timestamp: str = datetime.now(timezone.utc).isoformat()
        # In-process KEYSTONE engine cache: projection_name -> (engine, values, generation)
        # Avoids subprocess IPC for lookups; rebuilt when projection state changes.
        self._keystone_engines: dict[str, tuple[Any, list[int], str]] = {}
        self._keystone_engines_lock = threading.Lock()
        # Persistent read-only connection for data_version tracking.  A new
        # connection always reports data_version=1; only a persistent one
        # increments when another connection commits changes.
        self._keystone_watch_connection: sqlite3.Connection | None = None
        self._persistent_index_lock = threading.Lock()
        self._batches_since_flush = 0
        self._last_flush_time = time.monotonic()
        # Incremental checksum state — avoids O(total_records) full table scan
        # per batch in _refresh_state. The SHA-256 hasher is kept alive across
        # batches and fed only newly-appended rows, producing a bit-identical
        # digest to the original full-scan implementation.
        self._state_hashers: dict[str, Any] = {}
        self._state_high_water: dict[str, int] = {}
        self._state_row_counts: dict[str, int] = {}
        # Deferred native sync buffer — accumulate QIHSE content rows across
        # batches and sync to native DB only at flush time (every N batches).
        # This avoids per-batch native upsert overhead for the 64-dim hash-bow
        # vectors when the semantic projection (384-dim VPU) already covers search.
        self._deferred_qihse_rows: list[Any] = []
        self._deferred_graph_rows: list[Any] = []
        self._ensure_schema()
        self._cleanup_stale_qdb()

    def _cleanup_stale_qdb(self) -> None:
        """Remove stale .qdb files that don't match the current projection state.

        If the SQLite DB has no projection records but .qdb sidecar files
        exist (from a previous run, migration, or DB recreation), the old
        .qdb files are stale and must be deleted so QIHSE starts fresh.
        Also handles the case where multiple .qdb files exist in the same
        directory (e.g. from a rename) — keeps the newest, deletes the rest.
        """
        db_dir = self.database.parent
        db_stem = self.database.stem

        # Always check for duplicate .qdb files — keep newest, delete rest.
        for pattern in ("*.qihse.qdb", "*.graph.qdb"):
            qdbs = sorted(
                db_dir.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old_qdb in qdbs[1:]:
                try:
                    old_qdb.unlink()
                    logger.info("Removed old QIHSE store (keeping newer): %s", old_qdb)
                except OSError as exc:
                    logger.warning("Could not remove old %s: %s", old_qdb, exc)

        # If DB is fresh (no projection records), delete all matching .qdb
        # sidecars so QIHSE starts clean.
        has_records = False
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM index_projection_records"
                ).fetchone()
                has_records = row is not None and int(row[0]) > 0
        except Exception:
            pass

        if not has_records:
            for qdb in db_dir.glob(f"{db_stem}*.qdb"):
                try:
                    qdb.unlink()
                    logger.info("Removed stale QIHSE store: %s", qdb)
                except OSError as exc:
                    logger.warning("Could not remove stale %s: %s", qdb, exc)

    def close(self) -> None:
        self._close_persistent_indices()
        with self._keystone_server_lock:
            self._stop_keystone_server_locked()

    def _close_persistent_indices(self) -> None:
        """Flush and close persistent QIHSE/graph/semantic indices if open."""
        with self._persistent_index_lock:
            if self._persistent_qihse_index is not None:
                try:
                    self._persistent_qihse_index.flush()
                except Exception as exc:
                    logger.warning("persistent QIHSE flush on close failed: %s", exc)
                try:
                    self._persistent_qihse_index.close()
                except Exception as exc:
                    logger.warning("persistent QIHSE close failed: %s", exc)
                self._persistent_qihse_index = None
            if hasattr(self, "_persistent_keystone_content_index") and \
               self._persistent_keystone_content_index is not None:
                try:
                    self._persistent_keystone_content_index.close()
                except Exception:
                    pass
                self._persistent_keystone_content_index = None
            if self._persistent_graph_index is not None:
                try:
                    self._persistent_graph_index.flush()
                except Exception as exc:
                    logger.warning("persistent graph flush on close failed: %s", exc)
                try:
                    self._persistent_graph_index.close()
                except Exception as exc:
                    logger.warning("persistent graph close failed: %s", exc)
                self._persistent_graph_index = None
            if self._persistent_semantic_projection is not None:
                try:
                    self._persistent_semantic_projection.close()
                except Exception as exc:
                    logger.warning("persistent semantic projection close failed: %s", exc)
                self._persistent_semantic_projection = None
            # Close the KEYSTONE watch connection and clear engine cache.
            if self._keystone_watch_connection is not None:
                try:
                    self._keystone_watch_connection.close()
                except Exception:
                    pass
                self._keystone_watch_connection = None
            self._keystone_engines.clear()
            self._batches_since_flush = 0
            # Clear incremental checksum state — a new drain will cold-rebuild.
            self._state_hashers.clear()
            self._state_high_water.clear()
            self._state_row_counts.clear()

    def _get_persistent_qihse_index(self) -> Any:
        """Lazy-init and return the persistent QIHSE vector index."""
        with self._persistent_index_lock:
            if self._persistent_qihse_index is None:
                from ..search.qihse_vector_backend import QihseVectorIndex
                self._persistent_qihse_index = QihseVectorIndex(self.qihse_path)
            return self._persistent_qihse_index

    def _get_persistent_graph_index(self) -> Any:
        """Lazy-init and return the persistent QIHSE graph index."""
        with self._persistent_index_lock:
            if self._persistent_graph_index is None:
                from ..search.qihse_graph_backend import QihseGraphIndex
                self._persistent_graph_index = QihseGraphIndex(self.graph_path)
            return self._persistent_graph_index

    def _get_persistent_semantic_projection(self) -> Any:
        """Lazy-init and return the persistent SemanticProjection."""
        with self._persistent_index_lock:
            if self._persistent_semantic_projection is None:
                import os

                from ..search.semantic_projection import (
                    EmbeddingGenerator,
                    SemanticProjection,
                )

                device = os.environ.get("SPECTRA_EMBEDDING_DEVICE", "cpu").strip()
                st_batch_size = int(
                    os.environ.get("SPECTRA_EMBEDDING_BATCH_SIZE", "32")
                )
                gen = EmbeddingGenerator(device=device, st_batch_size=st_batch_size)
                self._persistent_semantic_projection = SemanticProjection(
                    db_path=self.database,
                    embedding_generator=gen,
                )
            return self._persistent_semantic_projection

    def _flush_persistent_indices(self) -> None:
        """Flush all persistent native indices — O(total_vectors) but infrequent."""
        with self._persistent_index_lock:
            # Sync any deferred native rows before flushing
            if self._deferred_qihse_rows:
                try:
                    self._sync_qihse(self._deferred_qihse_rows, rebuild=False)
                except Exception as exc:
                    logger.warning("deferred QIHSE sync on flush failed: %s", exc)
                self._deferred_qihse_rows.clear()
            if self._deferred_graph_rows:
                try:
                    self._sync_graph(self._deferred_graph_rows, rebuild=False)
                except Exception as exc:
                    logger.warning("deferred graph sync on flush failed: %s", exc)
                self._deferred_graph_rows.clear()
            if self._persistent_qihse_index is not None:
                self._persistent_qihse_index.flush()
            if hasattr(self, "_persistent_keystone_content_index") and \
               self._persistent_keystone_content_index is not None:
                try:
                    self._persistent_keystone_content_index.flush()
                except Exception as exc:
                    logger.warning("persistent KEYSTONE content flush failed: %s", exc)
            if self._persistent_graph_index is not None:
                self._persistent_graph_index.flush()
            if self._persistent_semantic_projection is not None:
                try:
                    self._persistent_semantic_projection.flush()
                except Exception as exc:
                    logger.warning("persistent semantic flush failed: %s", exc)
            self._batches_since_flush = 0
            self._last_flush_time = time.monotonic()

    def _should_flush(self, *, flush_every_batches: int, flush_interval_seconds: float) -> bool:
        if self._batches_since_flush >= flush_every_batches:
            return True
        if time.monotonic() - self._last_flush_time >= flush_interval_seconds:
            return True
        return False

    def _null_projection_payloads(self, sequence_ids: list[int]) -> None:
        """Shrink payload_json and null vector_json for synced projection records.

        After native QIHSE/graph sync completes, the full payload JSON and
        64-dim vector JSON are dead weight in ``index_projection_records``.
        Setting payload_json to '{}' (NOT NULL constraint) and vector_json
        to NULL reclaims ~4GB on a 3.9M-event database.

        Controlled by SPECTRA_SKIP_PAYLOAD_NULL=1 to disable.
        """
        if not sequence_ids:
            return
        _skip = os.environ.get("SPECTRA_SKIP_PAYLOAD_NULL", "").strip() == "1"
        if _skip:
            return
        # Batch the UPDATE in chunks to avoid SQLite variable limits
        _CHUNK = 500
        try:
            with self._connection() as connection:
                for i in range(0, len(sequence_ids), _CHUNK):
                    chunk = sequence_ids[i:i + _CHUNK]
                    placeholders = ",".join("?" for _ in chunk)
                    connection.execute(
                        f"""
                        UPDATE index_projection_records
                        SET payload_json = '{{}}', vector_json = NULL
                        WHERE sequence_id IN ({placeholders})
                        """,
                        chunk,
                    )
                connection.commit()
        except Exception as exc:
            logger.debug("payload nulling failed (non-fatal): %s", exc)

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

    def _keystone_lookup_in_process(
        self,
        numeric_key: int,
        projection_name: str,
    ) -> dict[str, Any] | None:
        """In-process KEYSTONE lookup via ctypes — avoids subprocess IPC.

        Caches a KeystoneSearchEngine per projection, rebuilding when the
        projection's SQLite state changes (data_version + state token).
        Returns None to signal the caller to fall back to subprocess.
        """
        try:
            from ..search.keystone_bindings import (
                KEYSTONE_WORKLOAD_IDS,
                KeystoneSearchEngine,
                keystone_available,
            )
        except (ImportError, OSError):
            return None
        if not keystone_available():
            return None
        try:
            with self._keystone_engines_lock:
                entry = self._keystone_engines.get(projection_name)
                if entry is not None:
                    engine, values, generation = entry
                else:
                    engine = values = generation = None
            # Check if the cached engine is still valid by comparing state.
            # Use a persistent read-only connection so PRAGMA data_version
            # increments when other connections commit changes.
            if self._keystone_watch_connection is None:
                self._keystone_watch_connection = connect_sqlite(
                    self.database, read_only=True
                )
                self._keystone_watch_connection.row_factory = sqlite3.Row
            conn = self._keystone_watch_connection
            conn.execute("BEGIN")
            try:
                data_version = int(conn.execute("PRAGMA data_version").fetchone()[0])
                state = conn.execute(
                    """
                    SELECT projection_version, last_sequence_id, source_checksum,
                           row_count, updated_at
                    FROM index_projection_state
                    WHERE projection_name=?
                    """,
                    (projection_name,),
                ).fetchone()
                state_token = [
                    state[c] for c in (
                        "projection_version", "last_sequence_id",
                        "source_checksum", "row_count", "updated_at",
                    )
                ] if state is not None else []
                observed_state = json.dumps(
                    [data_version, state_token],
                    ensure_ascii=True,
                    separators=(",", ":"),
                )
                if observed_state != generation:
                    # Rebuild engine from current projection records.
                    values = [
                        int(row[0]) for row in conn.execute(
                            """
                            SELECT DISTINCT numeric_key
                            FROM index_projection_records
                            WHERE projection_name=? AND numeric_key IS NOT NULL
                            ORDER BY numeric_key
                            """,
                            (projection_name,),
                        )
                    ]
                    engine = KeystoneSearchEngine(KEYSTONE_WORKLOAD_IDS)
                    if values:
                        engine.seed_anchors(values)
                    generation = observed_state
                    with self._keystone_engines_lock:
                        self._keystone_engines[projection_name] = (engine, values, generation)
            finally:
                conn.execute("ROLLBACK")
            if engine is None or not values:
                return {
                    "available": True,
                    "ok": True,
                    "projection": projection_name,
                    "found": False,
                    "position": None,
                    "numeric_key": numeric_key,
                    "generation": generation,
                }
            position = engine.search(values, numeric_key)
            found = position is not None and values[position] == numeric_key
            return {
                "available": True,
                "ok": True,
                "projection": projection_name,
                "found": found,
                "position": position if found else None,
                "numeric_key": numeric_key,
                "generation": generation,
            }
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            logger.debug("in-process KEYSTONE lookup failed, falling back to subprocess: %s", exc)
            return None

    def _keystone_lookup(
        self,
        numeric_key: int,
        *,
        projection_name: str = KEYSTONE_PROJECTION,
    ) -> dict[str, Any]:
        if projection_name not in KEYSTONE_PROJECTIONS:
            raise ValueError(f"{projection_name} is not a KEYSTONE projection")
        # Try in-process KEYSTONE first (avoids subprocess IPC overhead).
        inproc = self._keystone_lookup_in_process(numeric_key, projection_name)
        if inproc is not None:
            return inproc
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
        # Additional performance PRAGMAs for drain throughput.
        # connect_sqlite already sets WAL + synchronous=NORMAL; these add
        # a large page cache (512 MB), memory temp store, 4 GB mmap, and a
        # higher WAL checkpoint threshold to reduce periodic stalls.
        # With 88GB RAM and a 20GB DB, a large cache eliminates most disk reads.
        try:
            connection.execute("PRAGMA cache_size=-524288")  # 512 MB page cache
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA mmap_size=4294967296")  # 4 GB mmap
            connection.execute("PRAGMA wal_autocheckpoint=8000")  # ~32 MB
        except sqlite3.Error:
            pass  # non-fatal — defaults are still correct
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
                        self._batch_timestamp,
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
        # Skip the 64-dim hash-bow vector + json.dumps when SPECTRA_SKIP_NATIVE=1
        # (fast drain mode). The QIHSE native sync is skipped anyway, so the
        # vector_json column is not consumed. Saves per-event CPU in fast mode.
        compute_vector = not (projection_name == QIHSE_PROJECTION and _SKIP_NATIVE_VECTOR)
        vector_json = (
            json.dumps(_text_vector(text_content), separators=(",", ":"))
            if text_content is not None and compute_vector
            else None
        )
        # Skip content_hash computation in fast mode (SPECTRA_SKIP_STATE_REFRESH=1).
        # The hash is only used by _refresh_state for change detection between
        # drain runs. In fast mode we skip state refresh, so a dummy hash is fine.
        _skip_hash = os.environ.get("SPECTRA_SKIP_STATE_REFRESH", "").strip() == "1"
        if _skip_hash:
            content_hash = f"fast_{int(event['sequence_id'])}"
        else:
            content_hash = _content_hash(event)
        now = self._batch_timestamp
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
                content_hash,
                numeric_key,
                text_content,
                vector_json,
                _canonical_payload(event) if not _skip_hash else "{}",
                now,
            ),
        )
        if projection_name == FTS_PROJECTION:
            sequence_id = int(event["sequence_id"])
            payload = event.get("payload", {})
            channel_id = payload.get("channel_id") if isinstance(payload, dict) else None
            # Use INSERT OR REPLACE to atomically upsert in one statement
            # instead of DELETE + INSERT (saves one statement per event).
            connection.execute(
                """
                INSERT OR REPLACE INTO index_projection_fts(
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
            # Batch node upsert: deduplicate within the event, then do a single
            # SELECT for existence check + executemany for inserts. This reduces
            # 2N statements (per-node SELECT + INSERT) to 2 statements per event.
            seen_nodes: dict[int, dict[str, Any]] = {}
            for node in nodes:
                seen_nodes.setdefault(node["node_id"], node)
            unique_nodes = list(seen_nodes.values())
            if unique_nodes:
                # Check for node_id collisions in one query (chunked for SQLite
                # parameter limit of 999).
                node_ids = [node["node_id"] for node in unique_nodes]
                for ci in range(0, len(node_ids), 900):
                    chunk_ids = node_ids[ci:ci + 900]
                    placeholders = ",".join("?" for _ in chunk_ids)
                    existing_rows = connection.execute(
                        f"SELECT node_id, node_key FROM index_graph_nodes WHERE node_id IN ({placeholders})",
                        chunk_ids,
                    ).fetchall()
                    existing_map = {row["node_id"]: row["node_key"] for row in existing_rows}
                    new_node_rows = []
                    for node in unique_nodes[ci:ci + 900]:
                        if node["node_id"] in existing_map:
                            if existing_map[node["node_id"]] != node["node_key"]:
                                raise RuntimeError(f"graph node ID collision for {node['node_key']}")
                        else:
                            new_node_rows.append((
                                node["node_id"],
                                node["node_key"],
                                node["node_type"],
                                node["external_id"],
                                int(event["sequence_id"]),
                            ))
                    if new_node_rows:
                        connection.executemany(
                            """
                            INSERT INTO index_graph_nodes(
                                node_id, node_key, node_type, external_id, first_sequence_id
                            ) VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(node_key) DO NOTHING
                            """,
                            new_node_rows,
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
        elif projection_name == SEMANTIC_PROJECTION:
            # Semantic projection is handled in batch after the event loop
            # to avoid per-event QIHSE container open/close overhead.
            # The projection record above still serves as a checksum-tracked
            # marker so ``_refresh_state`` stays consistent.
            text = _text_content(event)
            if not text or not text.strip():
                return False
            return True
        return True

    def _refresh_state(self, connection, projection_name: str, *, error: str | None = None) -> dict[str, Any]:
        # Incremental checksum: keep a SHA-256 hasher alive across batches and
        # feed it only newly-appended rows. This avoids an O(total_records) full
        # table scan per batch — the dominant bottleneck at 2M+ records.
        # The digest is bit-identical to the original full-scan implementation
        # because SHA-256 is a streaming hash and the byte stream is the same.
        hasher = self._state_hashers.get(projection_name)
        high_water = self._state_high_water.get(projection_name, -1)
        expected_count = self._state_row_counts.get(projection_name, 0)

        if hasher is not None:
            # Fast path: only rows appended since last refresh.
            rows = connection.execute(
                """
                SELECT sequence_id, content_hash
                FROM index_projection_records
                WHERE projection_name=? AND sequence_id>?
                ORDER BY sequence_id
                """,
                (projection_name, high_water),
            ).fetchall()
            # Guard against out-of-order writes or deletions by other paths.
            actual_count = connection.execute(
                "SELECT COUNT(*) FROM index_projection_records WHERE projection_name=?",
                (projection_name,),
            ).fetchone()[0]
            if rows and (int(rows[0]["sequence_id"]) <= high_water or actual_count != expected_count + len(rows)):
                hasher = None  # force cold rebuild below
            else:
                for row in rows:
                    hasher.update((str(row["sequence_id"]) + row["content_hash"]).encode("ascii"))
                self._state_high_water[projection_name] = int(rows[-1]["sequence_id"]) if rows else high_water
                self._state_row_counts[projection_name] = actual_count
                checksum = hasher.copy().hexdigest()
                last_sequence = self._state_high_water[projection_name]

        if hasher is None:
            # Cold path: full scan once (startup, or after detected divergence).
            rows = connection.execute(
                """
                SELECT sequence_id, content_hash
                FROM index_projection_records
                WHERE projection_name=?
                ORDER BY sequence_id
                """,
                (projection_name,),
            ).fetchall()
            hasher = hashlib.sha256()
            last = -1
            for row in rows:
                hasher.update((str(row["sequence_id"]) + row["content_hash"]).encode("ascii"))
                last = int(row["sequence_id"])
            self._state_hashers[projection_name] = hasher
            self._state_high_water[projection_name] = last
            self._state_row_counts[projection_name] = len(rows)
            checksum = hasher.copy().hexdigest()
            last_sequence = last
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
            # Use shared lock — allows multiple projector workers to project
            # to SQLite simultaneously (WAL handles concurrent writes).
            # The native QIHSE sync inside _process_locked takes its own
            # exclusive lock via _run_native_command / NativeStoreLock.
            with NativeStoreLock(self.projector_lock_path, timeout=lock_timeout, shared=True):
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
        # Cache timestamp per batch — avoids per-event datetime.now() calls
        self._batch_timestamp = datetime.now(timezone.utc).isoformat()
        failures: list[dict[str, Any]] = []
        touched: set[str] = set()
        projected_events: list[dict[str, Any]] = []
        states: list[dict[str, Any]] = []
        native: dict[str, Any] | None = None
        graph_native: dict[str, Any] | None = None
        with self._connection() as connection:
            # Chunked transactions: process events in chunks of _TXN_CHUNK with
            # a single BEGIN/COMMIT per chunk instead of per-event SAVEPOINT.
            # The fast path (99.9%+ of events) pays zero savepoint overhead.
            # On failure, the chunk is rolled back and replayed event-by-event
            # with savepoints so one poisoned event cannot discard good ones.
            for chunk_start in range(0, len(events), _TXN_CHUNK):
                chunk = events[chunk_start:chunk_start + _TXN_CHUNK]
                connection.execute("BEGIN")
                chunk_failed = False
                try:
                    for event in chunk:
                        source_table = str(event.get("source_table") or "")
                        relevant_projections = _projections_for_source_table(source_table)
                        for projection_name in relevant_projections:
                            if self._upsert_event(connection, projection_name, event):
                                touched.add(projection_name)
                        projected_events.append(event)
                    connection.execute("COMMIT")
                except Exception:
                    # Slow path: replay chunk with per-event savepoints.
                    connection.execute("ROLLBACK")
                    chunk_failed = True
                    connection.execute("BEGIN")
                    for event in chunk:
                        sequence_id = int(event["sequence_id"])
                        savepoint = f"event_{sequence_id}"
                        connection.execute(f"SAVEPOINT {savepoint}")
                        try:
                            source_table = str(event.get("source_table") or "")
                            relevant_projections = _projections_for_source_table(source_table)
                            for projection_name in relevant_projections:
                                if self._upsert_event(connection, projection_name, event):
                                    touched.add(projection_name)
                            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                            projected_events.append(event)
                        except Exception as exc:
                            connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                            message = f"{type(exc).__name__}: {exc}"[:1000]
                            failures.append({"sequence_id": sequence_id, "error": message})
                    connection.execute("COMMIT")
            if touched:
                _skip_state = os.environ.get("SPECTRA_SKIP_STATE_REFRESH", "").strip() == "1"
                if _skip_state:
                    # Fast mode: skip the expensive SHA-256 checksum computation.
                    # Just record a minimal state with the last sequence_id.
                    states = []
                    for name in sorted(touched):
                        last_seq = connection.execute(
                            "SELECT MAX(sequence_id) FROM index_projection_records WHERE projection_name=?",
                            (name,),
                        ).fetchone()[0] or 0
                        states.append({"projection_name": name, "last_sequence_id": last_seq, "skipped": True})
                else:
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
        # ── Parallel post-SQLite projections ──
        # After the SQLite event loop, run the independent native/semantic
        # projections in parallel threads to overlap CPU-bound embedding
        # with I/O-bound native syncs.
        import concurrent.futures

        semantic_events: list[dict[str, Any]] = []
        semantic_texts: list[str] = []
        if SEMANTIC_PROJECTION in touched:
            # Cache _text_content per event — the original called it twice per
            # event (once for the truthiness check, once for .strip()). Compute
            # once and pass the cached text to project_batch.
            for ev in projected_events:
                text = _text_content(ev)
                if text and text.strip():
                    semantic_events.append(ev)
                    semantic_texts.append(text)
        intel_evidence_events = [
            ev for ev in projected_events
            if str(ev.get("source_table") or "") == "intelligence_evidence"
        ]
        native_phases = sum(
            projection_name in touched
            for projection_name in (QIHSE_PROJECTION, GRAPH_PROJECTION)
        )
        phase_timeout = (
            max(0.25, lease_seconds * 0.8 / native_phases)
            if native_phases
            else None
        )

        def _run_semantic() -> None:
            if not semantic_events:
                return
            try:
                projection = self._get_persistent_semantic_projection()
                # Use cached texts from the filter above (avoids redundant
                # _text_content calls — 3x fewer dict-walks per event).
                source_table = str(semantic_events[0].get("source_table", ""))
                source_ids = [str(ev.get("source_key", "")) for ev in semantic_events]
                projection.project_batch(
                    texts=semantic_texts,
                    source_table=source_table,
                    source_ids=source_ids,
                )
            except Exception as exc:
                logger.warning(
                    "Batch semantic projection failed for %d events: %s",
                    len(semantic_events),
                    exc,
                )

        def _run_intel_vectors() -> dict[str, Any] | None:
            if not intel_evidence_events:
                return None
            return self._sync_intelligence_vectors(intel_evidence_events)

        # Run semantic + intelligence vectors in parallel (they use separate
        # QIHSE databases).  The QIHSE and graph native syncs are kept serial
        # because they acquire exclusive NativeStoreLocks and the QIHSE C
        # library may not be thread-safe for concurrent opens of the same file.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fut_semantic = pool.submit(_run_semantic)
            fut_intel = pool.submit(_run_intel_vectors)
            concurrent.futures.wait([fut_semantic, fut_intel])
            intel_vector_result = fut_intel.result()
        # Native syncs are deferred to flush time — accumulate rows across
        # batches and sync in bulk every N batches. This eliminates per-batch
        # native upsert overhead (JSON parse + C-level QIHSE upsert) for the
        # 64-dim hash-bow content vectors.
        if QIHSE_PROJECTION in touched:
            self._deferred_qihse_rows.extend(rows)
        if GRAPH_PROJECTION in touched:
            self._deferred_graph_rows.extend(graph_rows)

        # Only sync to native DB at flush time or when buffer gets large
        native = None
        graph_native = None
        _deferred_threshold = int(os.environ.get("SPECTRA_DEFERRED_NATIVE_THRESHOLD", "4000"))
        if len(self._deferred_qihse_rows) >= _deferred_threshold or self._should_flush(
            flush_every_batches=getattr(self, '_drain_flush_every', 20),
            flush_interval_seconds=getattr(self, '_drain_flush_interval', 120),
        ):
            if self._deferred_qihse_rows:
                native = self._sync_qihse(
                    self._deferred_qihse_rows,
                    rebuild=False,
                    timeout_limit=phase_timeout,
                )
                # Null out payload_json + vector_json for synced rows to
                # reclaim disk space. The data is now in the native store;
                # the projection record only needs text_content + metadata.
                if native and native.get("ok") and not os.environ.get("SPECTRA_SKIP_NATIVE", "").strip() == "1":
                    _synced_ids = [int(r["sequence_id"]) for r in self._deferred_qihse_rows]
                    self._null_projection_payloads(_synced_ids)
                self._deferred_qihse_rows.clear()
            if self._deferred_graph_rows:
                graph_native = self._sync_graph(
                    self._deferred_graph_rows,
                    rebuild=False,
                    timeout_limit=phase_timeout,
                )
                if graph_native and graph_native.get("ok"):
                    _synced_graph_ids = [int(r["sequence_id"]) for r in self._deferred_graph_rows]
                    self._null_projection_payloads(_synced_graph_ids)
                self._deferred_graph_rows.clear()
        else:
            # Mark as ok — native sync deferred, not failed
            native = {"available": True, "ok": True, "deferred": True}
            graph_native = {"available": True, "ok": True, "deferred": True}
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
            "intel_vectors": intel_vector_result,
        }

    def drain(
        self,
        *,
        batch_size: int = 5000,
        lease_seconds: int = 300,
        max_batches: int = 0,
        flush_every_batches: int = 20,
        flush_interval_seconds: float = 30.0,
    ) -> dict[str, Any]:
        if max_batches < 0:
            raise ValueError("max_batches must be non-negative")
        # Store flush params for deferred native sync check in _process_locked
        self._drain_flush_every = flush_every_batches
        self._drain_flush_interval = flush_interval_seconds
        batches = 0
        claimed = 0
        processed = 0
        failed = 0
        ok = True
        last_result: dict[str, Any] | None = None
        last_productive_result: dict[str, Any] | None = None
        try:
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
                    self._batches_since_flush += 1
                # Periodic flush of persistent native indices
                if result["claimed"] and self._should_flush(
                    flush_every_batches=flush_every_batches,
                    flush_interval_seconds=flush_interval_seconds,
                ):
                    try:
                        self._flush_persistent_indices()
                    except Exception as exc:
                        logger.warning("periodic native index flush failed: %s", exc)
                if not result.get("ok") and result["claimed"] == 0:
                    break
                if result["claimed"] == 0:
                    break
            # Final flush before returning
            try:
                self._flush_persistent_indices()
            except Exception as exc:
                logger.warning("final native index flush failed: %s", exc)
        finally:
            # Keep persistent indices open — close() will clean them up.
            # But if this is a one-shot drain (not a long-running loop),
            # close them now to release the QIHSE file lock.
            pass
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

    def _sync_qihse_in_process(
        self,
        rows: list[Any],
        *,
        rebuild: bool,
    ) -> dict[str, Any] | None:
        """In-process QIHSE vector sync — avoids subprocess startup overhead.

        Uses the persistent index handle if available (no flush per batch).
        Returns None to signal the caller to fall back to subprocess.
        """
        # Skip in-process for rebuild with no rows — that's a full rebuild
        # that needs the subprocess path for proper locking
        if rebuild and not rows:
            return None
        try:
            from ..search.qihse_vector_backend import QihseVectorIndex
        except (ImportError, OSError):
            return None
        ids = [int(row["sequence_id"]) for row in rows]
        vectors = [json.loads(row["vector_json"]) for row in rows if row["vector_json"]]
        if len(ids) != len(vectors):
            return None
        try:
            if rebuild:
                # Rebuild needs a fresh handle with truncate
                with QihseVectorIndex(self.qihse_path, rebuild=rebuild) as index:
                    changes = index.upsert(ids, vectors)
                    return {
                        "available": True,
                        "ok": True,
                        "path": str(self.qihse_path),
                        "library": str(index.library_path),
                        "rows": len(rows),
                        **changes,
                    }
            # Non-rebuild: use persistent index with deferred flush
            index = self._get_persistent_qihse_index()
            changes = index.upsert_no_flush(ids, vectors)
            return {
                "available": True,
                "ok": True,
                "path": str(self.qihse_path),
                "library": str(index.library_path),
                "rows": len(rows),
                **changes,
            }
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug("in-process QIHSE sync failed, trying KEYSTONE vector engine: %s", exc)
            # Fallback: KEYSTONE vector engine for 64-dim hash-bow content vectors
            try:
                from ..search.keystone_vector_backend import KeystoneVectorIndex
                ks_path = self.database.parent / f"{self.database.name}.keystone_content.bin"
                if rebuild:
                    with KeystoneVectorIndex(ks_path, dim=64, rebuild=rebuild) as index:
                        index.upsert(ids, vectors)
                        return {
                            "available": True, "ok": True, "backend": "keystone",
                            "path": str(ks_path), "rows": len(rows),
                            "inserted": len(ids), "updated": 0,
                        }
                # Persistent handle
                with self._persistent_index_lock:
                    if not hasattr(self, "_persistent_keystone_content_index") or \
                       self._persistent_keystone_content_index is None:
                        self._persistent_keystone_content_index = KeystoneVectorIndex(
                            ks_path, dim=64,
                        )
                    index = self._persistent_keystone_content_index
                index.upsert_no_flush(ids, vectors)
                return {
                    "available": True, "ok": True, "backend": "keystone",
                    "path": str(ks_path), "rows": len(rows),
                    "inserted": len(ids), "updated": 0,
                }
            except Exception as exc2:
                logger.debug("KEYSTONE vector fallback also failed: %s", exc2)
                return None

    def _sync_graph_in_process(
        self,
        rows: list[Any],
        *,
        rebuild: bool,
    ) -> dict[str, Any] | None:
        """In-process graph sync — avoids subprocess startup overhead.

        Uses the persistent index handle if available (no flush per batch).
        Returns None to signal the caller to fall back to subprocess.
        """
        # Skip in-process for rebuild with no rows — full rebuild needs
        # the subprocess path for proper locking
        if rebuild and not rows:
            return None
        try:
            from ..search.qihse_graph_backend import QihseGraphIndex
        except (ImportError, OSError):
            return None
        # Gather graph nodes/edges from the projection connection
        sequence_ids = [int(row["sequence_id"]) for row in rows]
        try:
            with self._connection() as conn:
                if rebuild or not sequence_ids:
                    graph_nodes = conn.execute(
                        "SELECT * FROM index_graph_nodes ORDER BY node_id"
                    ).fetchall()
                    graph_edges = conn.execute(
                        "SELECT * FROM index_graph_edges ORDER BY from_node_id, to_node_id, edge_type"
                    ).fetchall()
                else:
                    ph = ",".join("?" for _ in sequence_ids)
                    graph_nodes = conn.execute(
                        f"SELECT * FROM index_graph_nodes WHERE first_sequence_id IN ({ph}) ORDER BY node_id",
                        sequence_ids,
                    ).fetchall()
                    graph_edges = conn.execute(
                        f"SELECT * FROM index_graph_edges WHERE sequence_id IN ({ph}) "
                        "ORDER BY from_node_id, to_node_id, edge_type",
                        sequence_ids,
                    ).fetchall()
        except sqlite3.OperationalError:
            return None
        try:
            if rebuild:
                with QihseGraphIndex(self.graph_path, rebuild=rebuild) as index:
                    changes = index.sync(
                        [int(row["node_id"]) for row in graph_nodes],
                        [
                            {
                                "from_node_id": int(row["from_node_id"]),
                                "to_node_id": int(row["to_node_id"]),
                                "edge_type": row["edge_type"],
                                "metadata": json.loads(row["metadata_json"]),
                            }
                            for row in graph_edges
                        ],
                    )
                    return {
                        "available": True,
                        "ok": True,
                        "path": str(self.graph_path),
                        "library": str(index.library_path),
                        "nodes": len(graph_nodes),
                        "edges": len(graph_edges),
                        **changes,
                    }
            # Non-rebuild: use persistent index with deferred flush
            index = self._get_persistent_graph_index()
            changes = index.sync_no_flush(
                [int(row["node_id"]) for row in graph_nodes],
                [
                    {
                        "from_node_id": int(row["from_node_id"]),
                        "to_node_id": int(row["to_node_id"]),
                        "edge_type": row["edge_type"],
                        "metadata": json.loads(row["metadata_json"]),
                    }
                    for row in graph_edges
                ],
            )
            return {
                "available": True,
                "ok": True,
                "path": str(self.graph_path),
                "library": str(index.library_path),
                "nodes": len(graph_nodes),
                "edges": len(graph_edges),
                **changes,
            }
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug("in-process graph sync failed, falling back to subprocess: %s", exc)
            return None

    def project_intelligence_bulk(
        self,
        hypotheses: list[dict[str, Any]],
        campaigns: list[dict[str, Any]],
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Bulk-project intelligence data into the QIHSE property graph store.

        Uses the new GraphStore ctypes bindings (qihse_graph_bindings.py) to
        create actors, hypotheses, campaigns, and evidence as property-graph
        vertices with typed edges between them.  External IDs are registered
        in the graph ingest ID map so subsequent CSV/JSONL ingestion can
        resolve references.

        Falls back to returning a skip result if the graph bindings are
        unavailable — callers should continue with the existing per-event
        graph projection in that case.
        """
        try:
            from ..search.qihse_graph_bindings import GraphStore, graph_available
        except (ImportError, OSError):
            return {"available": False, "ok": False, "error": "graph bindings unavailable"}
        if not graph_available():
            return {"available": False, "ok": False, "error": "libqihse.so not loadable"}

        graph_store_path = self.database.with_suffix(
            self.database.suffix + ".intel_graph.qdb"
        )
        store = GraphStore(str(graph_store_path))
        try:
            vertices_created = 0
            edges_created = 0
            errors = 0

            # ── Hypothesis vertices and relationship edges ────────────
            for hyp in hypotheses:
                hyp_id = str(hyp.get("hypothesis_id") or hyp.get("id") or "")
                if not hyp_id:
                    errors += 1
                    continue
                props = {
                    k: v for k, v in hyp.items()
                    if k not in ("hypothesis_id", "id") and v is not None
                }
                labels = ["Hypothesis"]
                htype = str(hyp.get("hypothesis_type") or "")
                if htype:
                    labels.append(htype.replace("-", "_").upper())
                vid = store.add_vertex(labels, props)
                if vid > 0:
                    store.register_id(hyp_id, vid)
                    vertices_created += 1
                else:
                    errors += 1
                    continue

                # Edge between subject entities
                subject_a = hyp.get("subject_a") or hyp.get("subject")
                subject_b = hyp.get("subject_b") or hyp.get("object")
                if subject_a and subject_b:
                    for sid in (subject_a, subject_b):
                        existing = store.lookup_id(str(sid))
                        if existing == 0:
                            ev = store.add_vertex(["Entity"], {"canonical_id": str(sid)})
                            if ev > 0:
                                store.register_id(str(sid), ev)
                                vertices_created += 1
                    va = store.lookup_id(str(subject_a))
                    vb = store.lookup_id(str(subject_b))
                    if va and vb:
                        edge_type = htype.upper().replace("-", "_") or "RELATED_TO"
                        if store.add_edge(edge_type, va, vb, {
                            "hypothesis_id": hyp_id,
                            "probability": hyp.get("probability"),
                        }) > 0:
                            edges_created += 1

            # ── Campaign vertices and actor/channel edges ─────────────
            for camp in campaigns:
                camp_id = str(camp.get("campaign_id") or camp.get("id") or "")
                if not camp_id:
                    errors += 1
                    continue
                props = {
                    k: v for k, v in camp.items()
                    if k not in ("campaign_id", "id", "actors", "channels") and v is not None
                }
                vid = store.add_vertex(["Campaign"], props)
                if vid > 0:
                    store.register_id(camp_id, vid)
                    vertices_created += 1
                else:
                    errors += 1
                    continue

                for actor_id in camp.get("actors", []) or []:
                    aid = str(actor_id)
                    existing = store.lookup_id(aid)
                    if existing == 0:
                        ev = store.add_vertex(["Actor"], {"canonical_id": aid})
                        if ev > 0:
                            store.register_id(aid, ev)
                            vertices_created += 1
                            existing = ev
                    if existing:
                        if store.add_edge("PART_OF_CAMPAIGN", existing, vid, {}) > 0:
                            edges_created += 1

                for channel_id in camp.get("channels", []) or []:
                    cid = str(channel_id)
                    existing = store.lookup_id(cid)
                    if existing == 0:
                        ev = store.add_vertex(["Channel"], {"canonical_id": cid})
                        if ev > 0:
                            store.register_id(cid, ev)
                            vertices_created += 1
                            existing = ev
                    if existing:
                        if store.add_edge("CAMPAIGN_CHANNEL", existing, vid, {}) > 0:
                            edges_created += 1

            # ── Evidence vertices linked to hypotheses ────────────────
            if evidence:
                for ev_item in evidence:
                    ev_id = str(ev_item.get("evidence_id") or ev_item.get("id") or "")
                    if not ev_id:
                        errors += 1
                        continue
                    props = {
                        k: v for k, v in ev_item.items()
                        if k not in ("evidence_id", "id", "hypothesis_id") and v is not None
                    }
                    vid = store.add_vertex(["Evidence"], props)
                    if vid > 0:
                        store.register_id(ev_id, vid)
                        vertices_created += 1
                        hyp_id = str(ev_item.get("hypothesis_id") or "")
                        if hyp_id:
                            hyp_vid = store.lookup_id(hyp_id)
                            if hyp_vid:
                                store.add_edge("SUPPORTS", vid, hyp_vid, {})
                                edges_created += 1
                    else:
                        errors += 1

            return {
                "available": True,
                "ok": errors == 0,
                "path": str(graph_store_path),
                "vertices": vertices_created,
                "edges": edges_created,
                "errors": errors,
                "total_vertices": store.vertex_count(),
                "total_edges": store.edge_count(),
            }
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("intelligence bulk graph projection failed: %s", exc)
            return {"available": True, "ok": False, "error": str(exc)}
        finally:
            try:
                store.close()
            except Exception:
                pass

    def _sync_qihse(
        self,
        rows: list[Any],
        *,
        rebuild: bool,
        timeout_limit: float | None = None,
    ) -> dict[str, Any]:
        # Try in-process sync first (avoids subprocess startup overhead)
        # Skip when tests monkeypatch _run_native_command (detect by checking
        # if the module-level function has been replaced)
        if _run_native_command is _ORIGINAL_RUN_NATIVE_COMMAND:
            inproc = self._sync_qihse_in_process(rows, rebuild=rebuild)
            if inproc is not None:
                return inproc
        # Fall back to subprocess
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
        # Try in-process sync first (avoids subprocess startup overhead)
        # Skip when tests monkeypatch _run_native_command
        if _run_native_command is _ORIGINAL_RUN_NATIVE_COMMAND:
            inproc = self._sync_graph_in_process(rows, rebuild=rebuild)
            if inproc is not None:
                return inproc
        # Fall back to subprocess
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

    def _sync_intelligence_vectors(
        self,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Upsert intelligence evidence feature vectors into the QIHSE vector index.

        For each evidence event, converts the payload into an ``AnalysisEvidence``
        and upserts a 64-dim feature vector into ``<db>.intelligence.qdb``.
        Non-evidence events are skipped.  Failures are logged but do not block
        the projection pipeline.
        """
        if not events:
            return {"ok": True, "upserted": 0, "skipped": 0}
        try:
            from ..intelligence.vectors import IntelligenceVectorIndex
            from ..intelligence.schema import AnalysisEvidence
        except (ImportError, OSError) as exc:
            logger.debug("intelligence vector index unavailable: %s", exc)
            return {"ok": False, "error": str(exc), "upserted": 0, "skipped": len(events)}
        upserted = 0
        skipped = 0
        errors: list[str] = []
        try:
            index = IntelligenceVectorIndex(self.database)
        except Exception as exc:
            logger.debug("intelligence vector index open failed: %s", exc)
            return {"ok": False, "error": str(exc), "upserted": 0, "skipped": len(events)}
        try:
            for event in events:
                payload = event.get("payload", {})
                if not isinstance(payload, dict):
                    skipped += 1
                    continue
                try:
                    evidence = AnalysisEvidence.from_dict(payload)
                    seq_id = int(event["sequence_id"])
                    index.upsert_evidence(evidence, seq_id)
                    upserted += 1
                except Exception as exc:
                    skipped += 1
                    errors.append(f"seq={event.get('sequence_id')}: {exc}")
        finally:
            index.close()
        return {
            "ok": True,
            "upserted": upserted,
            "skipped": skipped,
            "errors": errors,
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
