"""
Cross-Index Service — Traverse all QIHSE/KEYSTONE projections from a single ID
==============================================================================

Given a message_id, user_id, or media_id, resolve the full cross-index graph:
  - KEYSTONE anchor lookup (O(1) ID → projection record)
  - QIHSE content retrieval (full text + semantic vector)
  - FTS full-text search context
  - Graph relationships (reply chains, user interactions, media references)
  - Related records across all projections
  - Intelligence evidence, hypotheses, and campaigns involving the entity

Usage (library)::

    from tgarchive.services.cross_index import cross_index

    result = cross_index(db_path="spectra.db", entity_id=42, entity_type="message")

Usage (CLI)::

    spectra-cli cross-index 42 --type message
    spectra-cli cross-index 123 --type user
    spectra-cli cross-index 999 --type media
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..sqlite_runtime import connect_sqlite

logger = logging.getLogger(__name__)


def _query_projection_records(
    conn: sqlite3.Connection,
    *,
    source_table: str,
    source_key: str,
) -> List[Dict[str, Any]]:
    """Retrieve all projection records for a given source."""
    try:
        rows = conn.execute(
            """
            SELECT projection_name, sequence_id, source_table, source_key,
                   event_type, text_content, payload_json, updated_at
            FROM index_projection_records
            WHERE source_table = ? AND source_key = ?
            ORDER BY projection_name
            """,
            (source_table, source_key),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    results = []
    for row in rows:
        payload = {}
        if row["payload_json"]:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                pass
        results.append({
            "projection": row["projection_name"],
            "sequence_id": row["sequence_id"],
            "event_type": row["event_type"],
            "text_content": row["text_content"],
            "payload": payload,
            "updated_at": row["updated_at"],
        })
    return results


def _query_keystone_keys(
    conn: sqlite3.Connection,
    *,
    namespace: str,
    external_id: str,
) -> List[Dict[str, Any]]:
    """Retrieve KEYSTONE anchor keys for a given identity."""
    logical_key = json.dumps([namespace, external_id], ensure_ascii=False, separators=(",", ":"))
    try:
        rows = conn.execute(
            """
            SELECT projection_name, numeric_key, logical_key, created_at
            FROM index_projection_keys
            WHERE logical_key = ?
            """,
            (logical_key,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {
            "projection": row["projection_name"],
            "numeric_key": row["numeric_key"],
            "logical_key": row["logical_key"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _query_message_relations(
    conn: sqlite3.Connection,
    message_id: int,
) -> Dict[str, Any]:
    """Find related messages (replies, thread, same user)."""
    relations: Dict[str, Any] = {}

    # Replies to this message
    replies = conn.execute(
        "SELECT id, content, user_id, date FROM messages WHERE reply_to = ? ORDER BY id",
        (message_id,),
    ).fetchall()
    if replies:
        relations["replies"] = [
            {"message_id": r["id"], "content": r["content"], "user_id": r["user_id"], "date": r["date"]}
            for r in replies
        ]

    # This message's parent (if it's a reply)
    parent = conn.execute(
        "SELECT id, content, user_id, date FROM messages WHERE id = (SELECT reply_to FROM messages WHERE id = ?)",
        (message_id,),
    ).fetchone()
    if parent:
        relations["reply_to"] = {
            "message_id": parent["id"],
            "content": parent["content"],
            "user_id": parent["user_id"],
            "date": parent["date"],
        }

    # Other messages by the same user
    msg_row = conn.execute(
        "SELECT user_id FROM messages WHERE id = ?",
        (message_id,),
    ).fetchone()
    if msg_row and msg_row["user_id"]:
        user_msgs = conn.execute(
            "SELECT id, content, date FROM messages WHERE user_id = ? AND id != ? ORDER BY id DESC LIMIT 10",
            (msg_row["user_id"], message_id),
        ).fetchall()
        if user_msgs:
            relations["same_user_messages"] = [
                {"message_id": r["id"], "content": r["content"], "date": r["date"]}
                for r in user_msgs
            ]

    return relations


def _query_user_relations(
    conn: sqlite3.Connection,
    user_id: int,
) -> Dict[str, Any]:
    """Find messages, channels, and interactions for a user."""
    relations: Dict[str, Any] = {}

    # Message count and date range
    stats = conn.execute(
        "SELECT COUNT(*) as count, MIN(date) as first, MAX(date) as last FROM messages WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if stats and stats["count"]:
        relations["activity"] = {
            "message_count": stats["count"],
            "first_message": stats["first"],
            "last_message": stats["last"],
        }

    # Recent messages
    recent = conn.execute(
        "SELECT id, content, date, reply_to FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT 20",
        (user_id,),
    ).fetchall()
    if recent:
        relations["recent_messages"] = [
            {"message_id": r["id"], "content": r["content"], "date": r["date"], "reply_to": r["reply_to"]}
            for r in recent
        ]

    # User info
    user_row = conn.execute(
        "SELECT id, username, first_name, last_name, tags FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if user_row:
        relations["user_info"] = {
            "user_id": user_row["id"],
            "username": user_row["username"],
            "first_name": user_row["first_name"],
            "last_name": user_row["last_name"],
            "tags": user_row["tags"],
        }

    # Channels this user appears in (via channel_messages if available)
    try:
        channels = conn.execute(
            """
            SELECT DISTINCT channel_id, COUNT(*) as msg_count
            FROM channel_messages WHERE user_id = ?
            GROUP BY channel_id ORDER BY msg_count DESC
            """,
            (user_id,),
        ).fetchall()
        if channels:
            relations["channels"] = [
                {"channel_id": r["channel_id"], "message_count": r["msg_count"]}
                for r in channels
            ]
    except sqlite3.OperationalError:
        pass  # channel_messages table may not exist

    return relations


def _query_media_relations(
    conn: sqlite3.Connection,
    media_id: int,
) -> Dict[str, Any]:
    """Find messages referencing a media item."""
    relations: Dict[str, Any] = {}

    # Media info
    media_row = conn.execute(
        "SELECT id, type, url, title, description, checksum FROM media WHERE id = ?",
        (media_id,),
    ).fetchone()
    if media_row:
        relations["media_info"] = {
            "media_id": media_row["id"],
            "type": media_row["type"],
            "url": media_row["url"],
            "title": media_row["title"],
            "description": media_row["description"],
            "checksum": media_row["checksum"],
        }

    # Messages using this media
    msgs = conn.execute(
        "SELECT id, content, user_id, date FROM messages WHERE media_id = ? ORDER BY id",
        (media_id,),
    ).fetchall()
    if msgs:
        relations["messages"] = [
            {"message_id": r["id"], "content": r["content"], "user_id": r["user_id"], "date": r["date"]}
            for r in msgs
        ]

    return relations


# ─── Intelligence cross-index ──────────────────────────────────────────────


def _query_intelligence_evidence(
    conn: sqlite3.Connection,
    canonical_entity_id: str,
) -> List[Dict[str, Any]]:
    """Find all evidence where the entity is the subject or object."""
    try:
        rows = conn.execute(
            """
            SELECT evidence_id, evidence_type, subject, object, score,
                   confidence, direction, model, model_version, generated_at
            FROM intelligence_evidence
            WHERE subject = ? OR object = ?
            ORDER BY generated_at DESC
            """,
            (canonical_entity_id, canonical_entity_id),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {
            "evidence_id": r["evidence_id"],
            "evidence_type": r["evidence_type"],
            "subject": r["subject"],
            "object": r["object"],
            "score": r["score"],
            "confidence": r["confidence"],
            "direction": r["direction"],
            "model": r["model"],
            "model_version": r["model_version"],
            "generated_at": r["generated_at"],
            "role": "subject" if r["subject"] == canonical_entity_id else "object",
        }
        for r in rows
    ]


def _query_intelligence_hypotheses(
    conn: sqlite3.Connection,
    canonical_entity_id: str,
) -> List[Dict[str, Any]]:
    """Find all hypotheses where the entity is subject_a or subject_b."""
    try:
        rows = conn.execute(
            """
            SELECT hypothesis_id, hypothesis_type, subject_a, subject_b,
                   probability, confidence, supporting_evidence,
                   contradicting_evidence, insufficient_flags,
                   model, model_version, generated_at
            FROM intelligence_hypotheses
            WHERE subject_a = ? OR subject_b = ?
            ORDER BY probability DESC
            """,
            (canonical_entity_id, canonical_entity_id),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    results = []
    for r in rows:
        supporting = json.loads(r["supporting_evidence"]) if r["supporting_evidence"] else []
        contradicting = json.loads(r["contradicting_evidence"]) if r["contradicting_evidence"] else []
        insufficient = json.loads(r["insufficient_flags"]) if r["insufficient_flags"] else []
        results.append({
            "hypothesis_id": r["hypothesis_id"],
            "hypothesis_type": r["hypothesis_type"],
            "subject_a": r["subject_a"],
            "subject_b": r["subject_b"],
            "probability": r["probability"],
            "confidence": r["confidence"],
            "supporting_evidence": supporting,
            "contradicting_evidence": contradicting,
            "insufficient_flags": insufficient,
            "model": r["model"],
            "model_version": r["model_version"],
            "generated_at": r["generated_at"],
            "role": "subject_a" if r["subject_a"] == canonical_entity_id else "subject_b",
        })
    return results


def _query_intelligence_campaigns(
    conn: sqlite3.Connection,
    canonical_entity_id: str,
) -> List[Dict[str, Any]]:
    """Find all campaigns where the entity appears in actors or channels."""
    try:
        rows = conn.execute(
            """
            SELECT campaign_id, name, actors_json, channels_json,
                   wallets_json, domains_json, confidence, generated_at
            FROM intelligence_campaigns
            WHERE actors_json LIKE ? OR channels_json LIKE ?
                 OR wallets_json LIKE ? OR domains_json LIKE ?
            ORDER BY confidence DESC
            """,
            (
                f'%{canonical_entity_id}%',
                f'%{canonical_entity_id}%',
                f'%{canonical_entity_id}%',
                f'%{canonical_entity_id}%',
            ),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    results = []
    for r in rows:
        actors = json.loads(r["actors_json"]) if r["actors_json"] else []
        channels = json.loads(r["channels_json"]) if r["channels_json"] else []
        wallets = json.loads(r["wallets_json"]) if r["wallets_json"] else []
        domains = json.loads(r["domains_json"]) if r["domains_json"] else []
        results.append({
            "campaign_id": r["campaign_id"],
            "name": r["name"],
            "actors": actors,
            "channels": channels,
            "wallets": wallets,
            "domains": domains,
            "confidence": r["confidence"],
            "generated_at": r["generated_at"],
        })
    return results


def _query_graph_neighborhood(
    conn: sqlite3.Connection,
    canonical_entity_id: str,
) -> Dict[str, Any]:
    """Find the entity's graph neighborhood (nodes + edges)."""
    # Parse canonical ID to graph node type + external_id
    parts = canonical_entity_id.split(":")
    if len(parts) >= 3:
        node_type = parts[1]
        external_id = ":".join(parts[2:])
    else:
        node_type = "entity"
        external_id = canonical_entity_id
    node_key = f"{node_type}:{external_id}"

    result: Dict[str, Any] = {"node_key": node_key, "edges": [], "neighbors": []}
    try:
        node_row = conn.execute(
            "SELECT node_id, node_key, node_type, external_id FROM index_graph_nodes WHERE node_key = ?",
            (node_key,),
        ).fetchone()
        if not node_row:
            return result
        node_id = node_row["node_id"]
        result["node"] = {
            "node_id": node_id,
            "node_type": node_row["node_type"],
            "external_id": node_row["external_id"],
        }

        # Outgoing edges
        out_edges = conn.execute(
            """
            SELECT e.edge_type, e.sequence_id, e.metadata_json,
                   n.node_key, n.node_type, n.external_id
            FROM index_graph_edges e
            JOIN index_graph_nodes n ON e.to_node_id = n.node_id
            WHERE e.from_node_id = ?
            """,
            (node_id,),
        ).fetchall()
        # Incoming edges
        in_edges = conn.execute(
            """
            SELECT e.edge_type, e.sequence_id, e.metadata_json,
                   n.node_key, n.node_type, n.external_id
            FROM index_graph_edges e
            JOIN index_graph_nodes n ON e.from_node_id = n.node_id
            WHERE e.to_node_id = ?
            """,
            (node_id,),
        ).fetchall()

        for r in out_edges:
            meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
            result["edges"].append({
                "direction": "outgoing",
                "edge_type": r["edge_type"],
                "target": r["node_key"],
                "target_type": r["node_type"],
                "target_id": r["external_id"],
                "metadata": meta,
            })
        for r in in_edges:
            meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
            result["edges"].append({
                "direction": "incoming",
                "edge_type": r["edge_type"],
                "source": r["node_key"],
                "source_type": r["node_type"],
                "source_id": r["external_id"],
                "metadata": meta,
            })

        # Unique neighbors
        neighbor_keys = set()
        for e in result["edges"]:
            if "target" in e:
                neighbor_keys.add(e["target"])
            if "source" in e:
                neighbor_keys.add(e["source"])
        result["neighbors"] = sorted(neighbor_keys)
    except sqlite3.OperationalError:
        pass
    return result


def _query_intelligence_inferences(
    conn: sqlite3.Connection,
    evidence_ids: List[str],
) -> List[Dict[str, Any]]:
    """Find inferences that used any of the given evidence IDs as inputs."""
    if not evidence_ids:
        return []
    try:
        # inputs_json is a JSON array — use LIKE for each evidence_id
        conditions = " OR ".join("inputs_json LIKE ?" for _ in evidence_ids)
        params = [f'%{eid}%' for eid in evidence_ids]
        rows = conn.execute(
            f"""
            SELECT inference_id, inference_type, model, model_version,
                   inputs_json, output_json, confidence, generated_at
            FROM intelligence_inferences
            WHERE {conditions}
            """,
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    results = []
    for r in rows:
        inputs = json.loads(r["inputs_json"]) if r["inputs_json"] else []
        output = json.loads(r["output_json"]) if r["output_json"] else {}
        results.append({
            "inference_id": r["inference_id"],
            "inference_type": r["inference_type"],
            "model": r["model"],
            "model_version": r["model_version"],
            "inputs": inputs,
            "output": output,
            "confidence": r["confidence"],
            "generated_at": r["generated_at"],
        })
    return results


def cross_index_intelligence(
    db_path: Path | str,
    *,
    entity_id: int,
    entity_type: str = "user",
    platform: str = "telegram",
) -> Dict[str, Any]:
    """Cross-index an entity across all intelligence projections.

    Given an entity ID and type, find all evidence, hypotheses, campaigns,
    inferences, and graph edges involving that entity.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        entity_id: The entity's numeric ID (user_id, channel_id, etc.).
        entity_type: "user", "channel", "message", or "media".
        platform: Platform prefix for canonical ID (default "telegram").

    Returns:
        Dict with: canonical_id, evidence, hypotheses, campaigns,
        inferences, graph, summary
    """
    entity_type = entity_type.lower().strip()
    # Map entity_type to canonical ID entity type
    cid_type_map = {"user": "user", "channel": "channel", "message": "msg", "media": "media"}
    cid_type = cid_type_map.get(entity_type, entity_type)
    canonical = f"{platform}:{cid_type}:{entity_id}"

    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row

        evidence = _query_intelligence_evidence(conn, canonical)
        hypotheses = _query_intelligence_hypotheses(conn, canonical)
        campaigns = _query_intelligence_campaigns(conn, canonical)
        graph = _query_graph_neighborhood(conn, canonical)

        # Find inferences that used evidence about this entity
        evidence_ids = [e["evidence_id"] for e in evidence]
        inferences = _query_intelligence_inferences(conn, evidence_ids)

        # KEYSTONE anchors for intelligence objects about this entity
        intel_keystone = []
        try:
            for eid in evidence_ids:
                logical_key = json.dumps(["intel-evidence", eid], ensure_ascii=False, separators=(",", ":"))
                ks_row = conn.execute(
                    "SELECT projection_name, numeric_key, logical_key FROM index_projection_keys WHERE logical_key = ?",
                    (logical_key,),
                ).fetchone()
                if ks_row:
                    intel_keystone.append({
                        "projection": ks_row["projection_name"],
                        "numeric_key": ks_row["numeric_key"],
                        "evidence_id": eid,
                    })
        except sqlite3.OperationalError:
            pass  # index_projection_keys table doesn't exist yet

        summary = {
            "canonical_id": canonical,
            "entity_id": entity_id,
            "entity_type": entity_type,
            "evidence_count": len(evidence),
            "hypothesis_count": len(hypotheses),
            "campaign_count": len(campaigns),
            "inference_count": len(inferences),
            "graph_edge_count": len(graph.get("edges", [])),
            "keystone_intelligence_anchors": len(intel_keystone),
            "evidence_types": sorted({e["evidence_type"] for e in evidence}),
            "hypothesis_types": sorted({h["hypothesis_type"] for h in hypotheses}),
        }

    return {
        "canonical_id": canonical,
        "summary": summary,
        "evidence": evidence,
        "hypotheses": hypotheses,
        "campaigns": campaigns,
        "inferences": inferences,
        "graph": graph,
        "keystone_intelligence_anchors": intel_keystone,
    }


def cross_index(
    db_path: Path | str,
    *,
    entity_id: int,
    entity_type: str = "message",
) -> Dict[str, Any]:
    """Cross-index a single entity across all QIHSE/KEYSTONE projections.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        entity_id: The ID to look up (message_id, user_id, or media_id).
        entity_type: "message", "user", or "media".

    Returns:
        Dict with: keystone_anchors, projection_records, relations, summary
    """
    entity_type = entity_type.lower().strip()
    if entity_type not in ("message", "user", "media"):
        raise ValueError(f"entity_type must be 'message', 'user', or 'media', got: {entity_type}")

    source_table = {"message": "messages", "user": "users", "media": "media"}[entity_type]
    source_key = str(entity_id)
    namespace = entity_type

    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # 1. KEYSTONE anchors
        keystone_keys = _query_keystone_keys(conn, namespace=namespace, external_id=source_key)

        # 2. Projection records (QIHSE, FTS, etc.)
        projection_records = _query_projection_records(conn, source_table=source_table, source_key=source_key)

        # 3. Entity-specific relations
        if entity_type == "message":
            relations = _query_message_relations(conn, entity_id)
        elif entity_type == "user":
            relations = _query_user_relations(conn, entity_id)
        else:
            relations = _query_media_relations(conn, entity_id)

        # 4. Intelligence cross-index
        cid_type_map = {"message": "msg", "user": "user", "media": "media"}
        canonical = f"telegram:{cid_type_map.get(entity_type, entity_type)}:{entity_id}"
        intel_evidence = _query_intelligence_evidence(conn, canonical)
        intel_hypotheses = _query_intelligence_hypotheses(conn, canonical)
        intel_campaigns = _query_intelligence_campaigns(conn, canonical)
        intel_graph = _query_graph_neighborhood(conn, canonical)
        evidence_ids = [e["evidence_id"] for e in intel_evidence]
        intel_inferences = _query_intelligence_inferences(conn, evidence_ids)
        intelligence = {
            "evidence": intel_evidence,
            "hypotheses": intel_hypotheses,
            "campaigns": intel_campaigns,
            "inferences": intel_inferences,
            "graph": intel_graph,
        }

        # 5. Summary
        projections_found = sorted({r["projection"] for r in projection_records})
        summary = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "canonical_id": canonical,
            "keystone_anchors": len(keystone_keys),
            "projection_records": len(projection_records),
            "projections": projections_found,
            "has_relations": bool(relations),
            "intelligence": {
                "evidence_count": len(intel_evidence),
                "hypothesis_count": len(intel_hypotheses),
                "campaign_count": len(intel_campaigns),
                "inference_count": len(intel_inferences),
                "graph_edge_count": len(intel_graph.get("edges", [])),
                "evidence_types": sorted({e["evidence_type"] for e in intel_evidence}),
            },
        }

    return {
        "summary": summary,
        "keystone_anchors": keystone_keys,
        "projection_records": projection_records,
        "relations": relations,
        "intelligence": intelligence,
    }


__all__ = ["cross_index", "cross_index_intelligence"]
