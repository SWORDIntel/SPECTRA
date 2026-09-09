"""
SPECTRA Agent Tools — 5 clean functions for LLM agent consumption
=================================================================

Each tool is a thin wrapper around existing SPECTRA services.  Tools:

    search(query, limit, subsystems)     — unified search across subsystems
    expand(object_id, depth, ...)        — graph expansion from a known object
    timeline(entity_id, start, end, ...) — chronological activity for an entity
    resolve(query_or_id)                 — entity reference → identity clusters
    evidence(object_id)                  — full evidence/provenance chain

Design principles
-----------------
* Each tool is a **simple function** — no classes, no complex state.
* Each tool returns a **plain dict** (JSON-serializable).
* Tools **degrade gracefully**: if an underlying service is unavailable the
  tool returns an ``{"error": ...}`` dict rather than raising.
* Each result includes a human-readable ``"summary"`` or ``"explanation"``
  field for LLM consumption.
* Existing SPECTRA services are **wrapped, never modified**.

The database path defaults to ``./data/spectra.db`` (matching the CLI
``intel`` commands) and can be overridden via :func:`set_db_path` or the
``SPECTRA_DB_PATH`` environment variable.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..sqlite_runtime import connect_sqlite

logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────

_DEFAULT_DB = os.environ.get("SPECTRA_DB_PATH", "./data/spectra.db")
_db_path: str = _DEFAULT_DB


def set_db_path(path: str | Path) -> None:
    """Set the database path used by all agent tools."""
    global _db_path
    _db_path = str(path)


def get_db_path() -> str:
    """Return the currently configured database path."""
    return _db_path


# ─── Optional service imports (graceful degradation) ────────────────────────

# QueryPlanner may not exist yet (parallel task).  Fall back to file_search.
try:
    from ..search.query_planner import QueryPlanner  # type: ignore[import]
    _HAS_QUERY_PLANNER = True
except ImportError:
    QueryPlanner = None  # type: ignore[assignment,misc]
    _HAS_QUERY_PLANNER = False

# EntityResolverV2 may not exist yet (parallel task).  Fall back to resolver.
try:
    from ..intelligence.entity_resolver_v2 import EntityResolverV2  # type: ignore[import]
    _HAS_RESOLVER_V2 = True
except ImportError:
    EntityResolverV2 = None  # type: ignore[assignment,misc]
    _HAS_RESOLVER_V2 = False

# Existing services — always available.
from ..services.file_search import search_files as _search_files
from ..services.cross_index import (
    cross_index_intelligence as _cross_index_intelligence,
    cross_index as _cross_index,
)
from ..intelligence.conclusions import (
    draw_conclusions as _draw_conclusions,
    conclude_actor as _conclude_actor,
)
from ..intelligence.resolver import ActorIdentityResolver as _ActorIdentityResolver
from ..intelligence.schema import canonical_id as _canonical_id

# ChangePointDetector — used by timeline(); degrade if unavailable.
try:
    from ..threat.changepoint import ChangePointDetector as _ChangePointDetector
    _HAS_CHANGEPOINT = True
except ImportError:
    _ChangePointDetector = None  # type: ignore[assignment,misc]
    _HAS_CHANGEPOINT = False


# ─── Helpers ────────────────────────────────────────────────────────────────


def _error(message: str, **extra: Any) -> Dict[str, Any]:
    """Build a standard error dict."""
    result: Dict[str, Any] = {"error": message}
    result.update(extra)
    return result


def _parse_object_id(object_id: str) -> Tuple[str, str, Optional[int]]:
    """Parse an object ID into (entity_type, raw_id, numeric_id).

    Accepts forms:
        "media:123"            → ("media", "123", 123)
        "user:456"             → ("user", "456", 456)
        "message:789"          → ("message", "789", 789)
        "telegram:user:123"    → ("user", "123", 123)
        "123"                  → ("user", "123", 123)   # bare numeric → user

    Returns (entity_type, raw_id, numeric_id_or_None).
    """
    parts = object_id.split(":")
    if len(parts) == 1:
        # Bare numeric — assume user
        try:
            return "user", parts[0], int(parts[0])
        except ValueError:
            return "entity", parts[0], None
    if len(parts) == 2:
        etype, raw = parts[0].lower(), parts[1]
        try:
            num = int(raw)
        except ValueError:
            num = None
        return etype, raw, num
    # 3+ parts: platform:entity_type:id  (e.g. telegram:user:123)
    etype = parts[1].lower()
    raw = ":".join(parts[2:])
    try:
        num = int(parts[2])
    except ValueError:
        num = None
    return etype, raw, num


def _ensure_iso(value: Optional[str]) -> Optional[str]:
    """Normalise a date string to ISO format (best-effort)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _db_exists() -> bool:
    """Check whether the configured database file exists."""
    return Path(_db_path).expanduser().exists()


# ─── Tool 1: search ─────────────────────────────────────────────────────────


def search(
    query: str,
    limit: int = 50,
    subsystems: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Search across file, semantic, graph, entity, and hash search.

    Args:
        query: Search query (filename, keyword, hash, or natural language).
        limit: Maximum number of candidates to return.
        subsystems: Optional list of subsystems to query
            (e.g. ``["file", "semantic", "graph"]``).  ``None`` queries all.

    Returns:
        A dict with ``candidates``, ``total_found``, ``subsystems_queried``,
        ``elapsed_ms``, and a human-readable ``summary``.
    """
    if not query or not query.strip():
        return _error("query must be a non-empty string")

    start = time.monotonic()
    candidates: List[Dict[str, Any]] = []
    queried: List[str] = []

    requested = subsystems if subsystems else ["file", "semantic", "graph", "entity", "hash"]
    requested_lower = {s.lower() for s in requested}

    # ── Path A: QueryPlanner (unified planner — may not exist yet) ──────────
    if _HAS_QUERY_PLANNER:
        try:
            planner = QueryPlanner(_db_path)
            bundle = planner.plan(query, limit=limit, subsystems=requested)
            if hasattr(bundle, "to_dict"):
                result = bundle.to_dict()
            elif isinstance(bundle, dict):
                result = bundle
            else:
                result = {"candidates": [], "raw": str(bundle)}
            elapsed = (time.monotonic() - start) * 1000.0
            result.setdefault("elapsed_ms", round(elapsed, 1))
            result.setdefault(
                "summary",
                f"QueryPlanner returned {len(result.get('candidates', []))} candidates "
                f"for '{query}' across {result.get('subsystems_queried', requested)}.",
            )
            return result
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            logger.warning("QueryPlanner failed (%s); falling back to file_search", exc)

    # ── Path B: Fallback — file_search + SQLite FTS ─────────────────────────
    if not _db_exists():
        return _error(
            f"database not found at {_db_path}",
            query=query,
            elapsed_ms=round((time.monotonic() - start) * 1000.0, 1),
        )

    # File / media search
    if "file" in requested_lower or "hash" in requested_lower or not subsystems:
        try:
            fs_result = _search_files(
                _db_path, query=query, limit=limit, scan_passwords=False,
            )
            queried.append("file")
            for r in fs_result.get("results", []):
                candidates.append({
                    "object_id": f"media:{r['media_id']}",
                    "object_type": "media",
                    "score": float(r.get("match_score", 0.0)),
                    "matched_by": [r.get("match_type", "filename_fuzzy")],
                    "summary": (
                        f"{r.get('filename', 'unknown')} — "
                        f"type={r.get('type', '?')}, "
                        f"posted_by={r.get('posted_by_username') or r.get('posted_by_user_id', '?')}"
                    ),
                    "context": r.get("message_refs", [])[:3],
                    "provenance": ["file_search.search_files"],
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("file_search failed: %s", exc)
            queried.append("file (error)")

    # Message / content search via SQLite FTS or LIKE fallback
    if "semantic" in requested_lower or "entity" in requested_lower or not subsystems:
        try:
            msg_hits = _search_messages(query, limit=limit)
            queried.append("semantic")
            for hit in msg_hits:
                candidates.append({
                    "object_id": f"message:{hit['message_id']}",
                    "object_type": "message",
                    "score": hit.get("score", 0.5),
                    "matched_by": [hit.get("match_type", "content")],
                    "summary": (
                        f"message {hit['message_id']} in channel {hit.get('channel_id', '?')} "
                        f"by user {hit.get('user_id', '?')}: "
                        f"{(hit.get('content_preview', '') or '')[:120]}"
                    ),
                    "context": [{"channel_id": hit.get("channel_id"),
                                 "user_id": hit.get("user_id"),
                                 "date": hit.get("date")}],
                    "provenance": ["hybrid_search (SQLite FTS/LIKE)"],
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("message search failed: %s", exc)
            queried.append("semantic (error)")

    # Sort by score descending and cap at limit
    candidates.sort(key=lambda c: c.get("score", 0.0), reverse=True)
    candidates = candidates[:limit]

    elapsed = (time.monotonic() - start) * 1000.0
    total = len(candidates)
    summary = (
        f"Found {total} candidate(s) for '{query}' across {queried}."
        if total
        else f"No results found for '{query}' across {queried}."
    )

    return {
        "candidates": candidates,
        "total_found": total,
        "subsystems_queried": queried,
        "elapsed_ms": round(elapsed, 1),
        "summary": summary,
    }


def _search_messages(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Search messages via FTS5 then LIKE fallback."""
    hits: List[Dict[str, Any]] = []
    with connect_sqlite(_db_path) as conn:
        conn.row_factory = sqlite3.Row
        # Try FTS5 first
        try:
            rows = conn.execute(
                """
                SELECT m.id, m.channel_id, m.user_id, m.content, m.date, m.type,
                       rank * -1 AS score
                FROM messages_fts
                JOIN messages m ON messages_fts.rowid = m.id
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
            for r in rows:
                hits.append({
                    "message_id": r["id"],
                    "channel_id": r["channel_id"],
                    "user_id": r["user_id"],
                    "content_preview": (r["content"] or "")[:200],
                    "date": r["date"],
                    "type": r["type"],
                    "score": min(1.0, float(r["score"] or 0.0) / 10.0),
                    "match_type": "fts5",
                })
        except sqlite3.OperationalError:
            pass  # FTS table missing — fall through to LIKE

        if not hits:
            # LIKE fallback
            tokens = [t.strip() for t in query.lower().split() if len(t.strip()) > 1]
            if not tokens:
                tokens = [query.strip().lower()]
            like_clauses = " OR ".join(["content LIKE ?" for _ in tokens])
            params = [f"%{t}%" for t in tokens] + [limit]
            try:
                rows = conn.execute(
                    f"SELECT id, channel_id, user_id, content, date, type "
                    f"FROM messages WHERE content IS NOT NULL AND ({like_clauses}) "
                    f"ORDER BY id DESC LIMIT ?",
                    params,
                ).fetchall()
                for r in rows:
                    hits.append({
                        "message_id": r["id"],
                        "channel_id": r["channel_id"],
                        "user_id": r["user_id"],
                        "content_preview": (r["content"] or "")[:200],
                        "date": r["date"],
                        "type": r["type"],
                        "score": 0.5,
                        "match_type": "like",
                    })
            except sqlite3.OperationalError:
                pass  # messages table missing
    return hits


# ─── Tool 2: expand ─────────────────────────────────────────────────────────


def expand(
    object_id: str,
    depth: int = 1,
    relationship_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Expand the network from a known object via graph traversal.

    Args:
        object_id: Object identifier (e.g. ``"media:123"``, ``"user:456"``,
            or canonical ``"telegram:user:123"``).
        depth: How many hops to traverse (1 = direct neighbours).
        relationship_types: Optional filter on edge types
            (e.g. ``["same_actor", "associated_with"]``).

    Returns:
        Dict with ``root``, ``neighbors``, ``edges``, ``depth_reached``,
        and a human-readable ``summary``.
    """
    if not object_id:
        return _error("object_id must be a non-empty string")
    if depth < 1:
        depth = 1
    if depth > 5:
        depth = 5  # safety cap

    etype, raw_id, num_id = _parse_object_id(object_id)
    if num_id is None:
        return _error(f"could not parse numeric ID from object_id '{object_id}'")

    if not _db_exists():
        return _error(f"database not found at {_db_path}")

    rel_filter = {r.lower() for r in relationship_types} if relationship_types else None

    try:
        # Use cross_index_intelligence for the graph neighbourhood.
        # Map entity types: cross_index_intelligence accepts user/channel/message/media.
        ci_type = etype if etype in ("user", "channel", "message", "media") else "user"
        intel = _cross_index_intelligence(
            _db_path, entity_id=num_id, entity_type=ci_type,
        )
        graph = intel.get("graph", {})
        all_edges = graph.get("edges", [])

        # Filter by relationship types if requested
        if rel_filter:
            all_edges = [
                e for e in all_edges
                if e.get("edge_type", "").lower() in rel_filter
            ]

        # Build neighbour list from edges
        neighbors: List[Dict[str, Any]] = []
        seen: set = set()
        for edge in all_edges:
            neighbor_key = edge.get("target") or edge.get("source")
            neighbor_type = edge.get("target_type") or edge.get("source_type")
            neighbor_id = edge.get("target_id") or edge.get("source_id")
            if neighbor_key and neighbor_key not in seen:
                seen.add(neighbor_key)
                confidence = 1.0
                meta = edge.get("metadata", {})
                if isinstance(meta, dict) and "confidence" in meta:
                    try:
                        confidence = float(meta["confidence"])
                    except (TypeError, ValueError):
                        pass
                neighbors.append({
                    "object_id": neighbor_key,
                    "object_type": neighbor_type,
                    "relationship": edge.get("edge_type", "related"),
                    "confidence": confidence,
                    "direction": edge.get("direction", "unknown"),
                })

        # For depth > 1, expand each neighbour one more hop (breadth-first).
        depth_reached = 1
        if depth > 1 and neighbors:
            frontier = list(neighbors)
            visited = {graph.get("node_key", f"{etype}:{raw_id}")}
            visited.update(seen)
            extra_edges: List[Dict[str, Any]] = []
            for hop in range(1, depth):
                next_frontier: List[Dict[str, Any]] = []
                for node in frontier:
                    n_etype, _, n_num = _parse_object_id(node["object_id"])
                    if n_num is None:
                        continue
                    n_ci_type = n_etype if n_etype in ("user", "channel", "message", "media") else "user"
                    try:
                        n_intel = _cross_index_intelligence(
                            _db_path, entity_id=n_num, entity_type=n_ci_type,
                        )
                        n_graph = n_intel.get("graph", {})
                        for e in n_graph.get("edges", []):
                            if rel_filter and e.get("edge_type", "").lower() not in rel_filter:
                                continue
                            extra_edges.append(e)
                            nk = e.get("target") or e.get("source")
                            if nk and nk not in visited:
                                visited.add(nk)
                                next_frontier.append({
                                    "object_id": nk,
                                    "object_type": e.get("target_type") or e.get("source_type"),
                                    "relationship": e.get("edge_type", "related"),
                                    "confidence": 1.0,
                                    "direction": e.get("direction", "unknown"),
                                })
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("expand hop %d for %s failed: %s", hop, node["object_id"], exc)
                if not next_frontier:
                    break
                neighbors.extend(next_frontier)
                frontier = next_frontier
                depth_reached = hop + 1

        all_edges_out = all_edges + extra_edges if depth > 1 else all_edges

        root = {
            "object_id": object_id,
            "object_type": etype,
            "canonical_id": intel.get("canonical_id", f"telegram:{etype}:{num_id}"),
        }
        summary = (
            f"Expanded from {object_id} to depth {depth_reached}: "
            f"{len(neighbors)} neighbour(s), {len(all_edges_out)} edge(s)."
        )

        return {
            "root": root,
            "neighbors": neighbors,
            "edges": all_edges_out,
            "depth_reached": depth_reached,
            "summary": summary,
        }
    except FileNotFoundError as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _error(f"expand failed: {exc}", object_id=object_id)


# ─── Tool 3: timeline ───────────────────────────────────────────────────────


def timeline(
    entity_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    event_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Get chronological activity for an entity.

    Args:
        entity_id: Entity identifier (e.g. ``"user:456"`` or ``"456"``).
        start: Optional ISO date lower bound (inclusive).
        end: Optional ISO date upper bound (inclusive).
        event_types: Optional filter on event types
            (e.g. ``["message", "media"]``).

    Returns:
        Dict with ``entity_id``, ``events``, ``activity_pattern``,
        ``change_points``, and a human-readable ``summary``.
    """
    if not entity_id:
        return _error("entity_id must be a non-empty string")

    etype, raw_id, num_id = _parse_object_id(entity_id)
    if num_id is None:
        return _error(f"could not parse numeric ID from entity_id '{entity_id}'")

    if not _db_exists():
        return _error(f"database not found at {_db_path}")

    type_filter = {t.lower() for t in event_types} if event_types else None
    start_iso = _ensure_iso(start)
    end_iso = _ensure_iso(end)

    try:
        events: List[Dict[str, Any]] = []
        hour_counts: Counter = Counter()
        raw_messages: List[Dict[str, Any]] = []

        with connect_sqlite(_db_path) as conn:
            conn.row_factory = sqlite3.Row

            conditions = ["user_id = ?"]
            params: List[Any] = [num_id]
            if start_iso:
                conditions.append("date >= ?")
                params.append(start_iso)
            if end_iso:
                conditions.append("date <= ?")
                params.append(end_iso)
            where = " AND ".join(conditions)

            try:
                rows = conn.execute(
                    f"SELECT id, channel_id, user_id, content, date, type, reply_to "
                    f"FROM messages WHERE {where} ORDER BY date ASC",
                    params,
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

            for r in rows:
                ev_type = r["type"] or "message"
                if type_filter and ev_type.lower() not in type_filter:
                    continue
                date_str = r["date"]
                events.append({
                    "timestamp": date_str,
                    "event_type": ev_type,
                    "channel_id": r["channel_id"],
                    "message_id": r["id"],
                    "reply_to": r["reply_to"],
                    "summary": (r["content"] or "")[:150],
                })
                # Track hour for activity pattern
                if date_str:
                    try:
                        dt = _parse_date(date_str)
                        if dt is not None:
                            hour_counts[dt.hour] += 1
                            raw_messages.append({
                                "id": r["id"],
                                "channel_id": r["channel_id"],
                                "user_id": r["user_id"],
                                "content": r["content"] or "",
                                "date": dt,
                            })
                    except (ValueError, TypeError):
                        pass

        # Activity pattern
        peak_hours: List[int] = []
        inferred_tz: Optional[str] = None
        if hour_counts:
            max_count = max(hour_counts.values())
            peak_hours = sorted(
                h for h, c in hour_counts.items() if c >= max_count * 0.6
            )
            # Rough timezone inference from peak hours
            if peak_hours:
                avg_peak = sum(peak_hours) / len(peak_hours)
                # Assume peaks are evening hours (17-22 local); estimate UTC offset
                if 0 <= avg_peak <= 23:
                    offset = int(round(((avg_peak - 19 + 12) % 24) - 12))
                    inferred_tz = f"UTC{'+' if offset >= 0 else ''}{offset}"

        # Change-point detection (graceful degradation)
        change_points: List[Dict[str, Any]] = []
        if _HAS_CHANGEPOINT and len(raw_messages) >= 10:
            try:
                detector = _ChangePointDetector()
                cps = detector.detect_change_points(raw_messages, window_size=min(50, len(raw_messages) // 2))
                change_points = [cp.to_dict() for cp in cps[:10]]
            except Exception as exc:  # noqa: BLE001
                logger.debug("changepoint detection failed: %s", exc)

        summary = (
            f"Entity {entity_id} has {len(events)} event(s)"
            + (f" between {start_iso} and {end_iso}" if start_iso or end_iso else "")
            + f". Peak activity hours: {peak_hours or 'n/a'}."
            + (f" {len(change_points)} change point(s) detected." if change_points else "")
        )

        return {
            "entity_id": entity_id,
            "entity_type": etype,
            "events": events,
            "activity_pattern": {
                "peak_hours": peak_hours,
                "inferred_timezone": inferred_tz,
                "total_events": len(events),
                "hour_histogram": dict(sorted(hour_counts.items())),
            },
            "change_points": change_points,
            "summary": summary,
        }
    except Exception as exc:  # noqa: BLE001
        return _error(f"timeline failed: {exc}", entity_id=entity_id)


def _parse_date(value: Any) -> Optional[datetime]:
    """Parse a date string or datetime into a timezone-aware datetime."""
    if isinstance(value, datetime):
        dt = value
    elif value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ─── Tool 4: resolve ────────────────────────────────────────────────────────


def resolve(query_or_id: str) -> Dict[str, Any]:
    """Resolve a mention/username/name/user_id to identity clusters.

    Args:
        query_or_id: A username (``"@alice"`` or ``"alice"``), display name,
            or numeric user ID (``"123"`` or ``"user:123"``).

    Returns:
        Dict with ``query``, ``clusters``, and a human-readable
        ``explanation``.
    """
    if not query_or_id or not query_or_id.strip():
        return _error("query_or_id must be a non-empty string")

    if not _db_exists():
        return _error(f"database not found at {_db_path}")

    query = query_or_id.strip()
    cleaned = query.lstrip("@")

    # ── Path A: EntityResolverV2 (may not exist yet) ────────────────────────
    if _HAS_RESOLVER_V2:
        try:
            resolver = EntityResolverV2(_db_path)
            result = resolver.resolve(query)
            if hasattr(result, "to_dict"):
                result = result.to_dict()
            if isinstance(result, dict):
                result.setdefault("query", query)
                result.setdefault(
                    "explanation",
                    f"EntityResolverV2 resolved '{query}' to "
                    f"{len(result.get('clusters', []))} cluster(s).",
                )
                return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("EntityResolverV2 failed (%s); falling back", exc)

    # ── Path B: Fallback — DB lookup + cross_index hypotheses ───────────────
    try:
        clusters: List[Dict[str, Any]] = []
        candidates: List[Dict[str, Any]] = []

        with connect_sqlite(_db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Try numeric user ID first
            num_id: Optional[int] = None
            try:
                num_id = int(cleaned.split(":")[-1])
            except ValueError:
                pass

            # Try username lookup
            user_row = None
            try:
                user_row = conn.execute(
                    "SELECT id, username, first_name, last_name, tags FROM users "
                    "WHERE username = ? OR username = ? LIMIT 1",
                    (cleaned, query),
                ).fetchone()
            except sqlite3.OperationalError:
                pass  # users table missing

            # Try numeric ID lookup
            if user_row is None and num_id is not None:
                try:
                    user_row = conn.execute(
                        "SELECT id, username, first_name, last_name, tags FROM users "
                        "WHERE id = ? LIMIT 1",
                        (num_id,),
                    ).fetchone()
                except sqlite3.OperationalError:
                    pass

            if user_row is not None:
                num_id = user_row["id"]
                candidates.append({
                    "type": "user_id",
                    "value": str(user_row["id"]),
                })
                if user_row["username"]:
                    candidates.append({"type": "username", "value": user_row["username"]})
                if user_row["first_name"]:
                    candidates.append({
                        "type": "name",
                        "value": " ".join(
                            filter(None, [user_row["first_name"], user_row["last_name"]])
                        ),
                    })

        # Cross-index for same_actor hypotheses
        evidence: List[Dict[str, Any]] = []
        contradicting: List[Dict[str, Any]] = []
        confidence = 0.5
        if num_id is not None:
            try:
                intel = _cross_index_intelligence(
                    _db_path, entity_id=num_id, entity_type="user",
                )
                for hyp in intel.get("hypotheses", []):
                    if hyp.get("hypothesis_type") == "same_actor":
                        confidence = max(confidence, float(hyp.get("probability", 0.5)))
                        evidence.extend(hyp.get("supporting_evidence", []))
                        contradicting.extend(hyp.get("contradicting_evidence", []))
                        # The other subject is a candidate
                        other = hyp.get("subject_b") if hyp.get("subject_a") == intel.get("canonical_id") else hyp.get("subject_a")
                        if other:
                            candidates.append({"type": "canonical_id", "value": other})
            except Exception as exc:  # noqa: BLE001
                logger.debug("cross_index for resolve failed: %s", exc)

        if candidates:
            # Deduplicate candidates
            seen_vals: set = set()
            unique_candidates = []
            for c in candidates:
                key = (c["type"], c["value"])
                if key not in seen_vals:
                    seen_vals.add(key)
                    unique_candidates.append(c)

            clusters.append({
                "cluster_id": f"cluster:{num_id or cleaned}",
                "confidence": round(confidence, 4),
                "candidates": unique_candidates,
                "evidence": evidence[:20],
                "contradicting_evidence": contradicting[:20],
            })

        explanation = (
            f"Resolved '{query}' to {len(clusters)} cluster(s) with "
            f"confidence {confidence:.2f}, derived from "
            f"{len(evidence)} supporting and {len(contradicting)} contradicting "
            f"observations."
            if clusters
            else f"No identity clusters found for '{query}'."
        )

        return {
            "query": query,
            "clusters": clusters,
            "explanation": explanation,
        }
    except Exception as exc:  # noqa: BLE001
        return _error(f"resolve failed: {exc}", query=query_or_id)


# ─── Tool 5: evidence ───────────────────────────────────────────────────────


def evidence(object_id: str) -> Dict[str, Any]:
    """Get full provenance and evidence chain for an object or conclusion.

    Args:
        object_id: An entity ID (``"user:123"``, ``"telegram:user:123"``),
            a conclusion ID (``"conclusion:789"``), or bare numeric ID.

    Returns:
        Dict with ``object_id``, ``object_type``, ``provenance_chain``,
        ``supporting_evidence``, ``contradicting_evidence``, and a
        human-readable ``explanation``.
    """
    if not object_id:
        return _error("object_id must be a non-empty string")

    if not _db_exists():
        return _error(f"database not found at {_db_path}")

    etype, raw_id, num_id = _parse_object_id(object_id)
    if num_id is None:
        return _error(f"could not parse numeric ID from object_id '{object_id}'")

    try:
        # Determine entity type for cross_index_intelligence
        ci_type = etype if etype in ("user", "channel", "message", "media") else "user"

        # Gather intelligence cross-index
        intel = _cross_index_intelligence(
            _db_path, entity_id=num_id, entity_type=ci_type,
        )
        canonical = intel.get("canonical_id", f"telegram:{etype}:{num_id}")

        # Draw conclusions (Bayesian fusion of all evidence)
        conclusions: List[Dict[str, Any]] = []
        try:
            conclusion_objs = _draw_conclusions(
                _db_path, entity_id=num_id, entity_type=ci_type,
            )
            conclusions = [c.to_dict() for c in conclusion_objs]
        except Exception as exc:  # noqa: BLE001
            logger.debug("draw_conclusions failed: %s", exc)

        # Build provenance chain from evidence + inferences
        provenance_chain: List[Dict[str, Any]] = []
        for ev in intel.get("evidence", []):
            provenance_chain.append({
                "node_id": ev.get("evidence_id", ""),
                "algorithm": ev.get("model", "unknown"),
                "version": ev.get("model_version", ""),
                "confidence": ev.get("confidence", 0.0),
                "evidence_type": ev.get("evidence_type", ""),
                "direction": ev.get("direction", "supports"),
            })
        for inf in intel.get("inferences", []):
            provenance_chain.append({
                "node_id": inf.get("inference_id", ""),
                "algorithm": inf.get("model", "unknown"),
                "version": inf.get("model_version", ""),
                "confidence": inf.get("confidence", 0.0),
                "inference_type": inf.get("inference_type", ""),
            })

        # Supporting / contradicting evidence
        all_evidence = intel.get("evidence", [])
        supporting = [
            {
                "evidence_id": e.get("evidence_id", ""),
                "evidence_type": e.get("evidence_type", ""),
                "score": e.get("score", 0.0),
                "confidence": e.get("confidence", 0.0),
                "model": e.get("model", ""),
            }
            for e in all_evidence
            if e.get("direction", "supports") == "supports"
        ]
        contradicting = [
            {
                "evidence_id": e.get("evidence_id", ""),
                "evidence_type": e.get("evidence_type", ""),
                "score": e.get("score", 0.0),
                "confidence": e.get("confidence", 0.0),
                "model": e.get("model", ""),
            }
            for e in all_evidence
            if e.get("direction", "supports") == "contradicts"
        ]

        # Determine object_type
        object_type = "conclusion" if etype == "conclusion" else ci_type

        # Build explanation
        ev_count = len(all_evidence)
        hyp_count = len(intel.get("hypotheses", []))
        conclusion_count = len(conclusions)
        top_conclusion = conclusions[0] if conclusions else None
        if top_conclusion:
            explanation = (
                f"This {object_type} ({canonical}) has {ev_count} evidence items "
                f"and {hyp_count} hypothesis(es), fused into {conclusion_count} "
                f"conclusion(s). Top conclusion: "
                f"{top_conclusion.get('conclusion_type', 'unknown')} with "
                f"P={top_conclusion.get('probability', 0):.2f} "
                f"(confidence={top_conclusion.get('confidence', 0):.2f}). "
                f"{len(supporting)} supporting, {len(contradicting)} contradicting."
            )
        else:
            explanation = (
                f"This {object_type} ({canonical}) has {ev_count} evidence items, "
                f"{hyp_count} hypothesis(es), and {len(provenance_chain)} "
                f"provenance node(s). No fused conclusions were derived. "
                f"{len(supporting)} supporting, {len(contradicting)} contradicting."
            )

        return {
            "object_id": object_id,
            "object_type": object_type,
            "canonical_id": canonical,
            "provenance_chain": provenance_chain,
            "supporting_evidence": supporting,
            "contradicting_evidence": contradicting,
            "conclusions": conclusions,
            "hypotheses": intel.get("hypotheses", []),
            "campaigns": intel.get("campaigns", []),
            "graph_neighbors": intel.get("graph", {}).get("neighbors", []),
            "explanation": explanation,
        }
    except FileNotFoundError as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _error(f"evidence failed: {exc}", object_id=object_id)


# ─── Registry ───────────────────────────────────────────────────────────────

#: Mapping of tool name → callable, for dynamic dispatch.
AGENT_TOOLS: Dict[str, Any] = {
    "search": search,
    "expand": expand,
    "timeline": timeline,
    "resolve": resolve,
    "evidence": evidence,
}


__all__ = [
    "search",
    "expand",
    "timeline",
    "resolve",
    "evidence",
    "set_db_path",
    "get_db_path",
    "AGENT_TOOLS",
]
