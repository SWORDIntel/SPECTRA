"""Crash-isolated native verification entry point for index projections."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from ..sqlite_runtime import connect_sqlite
from .index_projector import IndexProjector, KEYSTONE_PROJECTIONS, PROJECTIONS
from ..search.qihse_vector_backend import QihseVectorIndex


def _serve_keystone(database: Path) -> int:
    from ..search.keystone_bindings import KEYSTONE_WORKLOAD_IDS, KeystoneSearchEngine, keystone_available

    if not keystone_available():
        raise SystemExit("KEYSTONE is unavailable")
    engine = KeystoneSearchEngine(KEYSTONE_WORKLOAD_IDS)
    values_by_projection: dict[str, list[int]] = {}
    observed_state_by_projection: dict[str, str] = {}
    generation_by_projection: dict[str, str] = {}

    def values_for(connection: sqlite3.Connection, projection: str) -> tuple[list[int], str]:
        if projection not in KEYSTONE_PROJECTIONS:
            raise ValueError(f"Unsupported KEYSTONE projection: {projection}")
        connection.execute("BEGIN")
        try:
            data_version = int(connection.execute("PRAGMA data_version").fetchone()[0])
            state = connection.execute(
                """
                SELECT projection_version, last_sequence_id, source_checksum, row_count, updated_at
                FROM index_projection_state
                WHERE projection_name=?
                """,
                (projection,),
            ).fetchone()
            state_token = [
                state[column]
                for column in (
                    "projection_version",
                    "last_sequence_id",
                    "source_checksum",
                    "row_count",
                    "updated_at",
                )
            ] if state is not None else []
            observed_state = json.dumps(
                [data_version, state_token],
                ensure_ascii=True,
                separators=(",", ":"),
            )
            if observed_state == observed_state_by_projection.get(projection):
                return (
                    values_by_projection.get(projection, []),
                    generation_by_projection[projection],
                )
            values = [
                int(row[0])
                for row in connection.execute(
                    """
                    SELECT DISTINCT numeric_key
                    FROM index_projection_records
                    WHERE projection_name=? AND numeric_key IS NOT NULL
                    ORDER BY numeric_key
                    """,
                    (projection,),
                )
            ]
            key_checksum = hashlib.blake2b(digest_size=16, person=b"SPECTRA-KEYGEN")
            for value in values:
                key_checksum.update(value.to_bytes(8, byteorder="big", signed=True))
            generation = json.dumps(
                [data_version, state_token, len(values), key_checksum.hexdigest()],
                ensure_ascii=True,
                separators=(",", ":"),
            )
            values_by_projection[projection] = values
            observed_state_by_projection[projection] = observed_state
            generation_by_projection[projection] = generation
            return values, generation
        finally:
            connection.execute("ROLLBACK")

    print("SPECTRA_NATIVE_SERVER=" + json.dumps({"ok": True}), flush=True)
    with connect_sqlite(database, read_only=True) as connection:
        connection.row_factory = sqlite3.Row
        for line in sys.stdin:
            request = None
            try:
                request = json.loads(line)
                key = int(request["lookup_key"])
                request_id = int(request["request_id"])
                projection = str(request.get("projection") or "keystone.ids.v1")
                values, generation = values_for(connection, projection)
                position = engine.search(values, key)
                response = {
                    "available": True,
                    "ok": True,
                    "request_id": request_id,
                    "projection": projection,
                    "found": position is not None,
                    "position": position,
                    "numeric_key": key,
                    "generation": generation,
                }
            except Exception as exc:
                response = {
                    "available": True,
                    "ok": False,
                    "request_id": request.get("request_id") if isinstance(request, dict) else None,
                    "error": str(exc),
                }
            print("SPECTRA_NATIVE_RESPONSE=" + json.dumps(response, sort_keys=True), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="store_true")
    parser.add_argument(
        "--action",
        choices=("verify", "sync", "search", "lookup", "graph-sync", "graph-query"),
        default="verify",
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--projection", choices=PROJECTIONS)
    parser.add_argument("--sample-size", type=int, default=16)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--query-vector")
    parser.add_argument("--lookup-key", type=int)
    parser.add_argument("--sequence-ids")
    parser.add_argument("--node-id", type=int)
    parser.add_argument("--edge-type")
    parser.add_argument("--direction", choices=("outgoing", "incoming", "both"), default="both")
    arguments = parser.parse_args()
    if arguments.server:
        return _serve_keystone(arguments.db)
    if arguments.projection is None:
        parser.error("--projection is required unless --server is used")
    connection = connect_sqlite(arguments.db, read_only=True)
    connection.row_factory = sqlite3.Row
    graph_nodes: list[sqlite3.Row] = []
    graph_edges: list[sqlite3.Row] = []
    try:
        sequence_ids = json.loads(arguments.sequence_ids) if arguments.sequence_ids else None
        if sequence_ids:
            normalized_ids = [int(sequence_id) for sequence_id in sequence_ids]
            placeholders = ",".join("?" for _ in normalized_ids)
            rows = connection.execute(
                f"""
                SELECT * FROM index_projection_records
                WHERE projection_name=? AND sequence_id IN ({placeholders})
                ORDER BY sequence_id
                """,
                (arguments.projection, *normalized_ids),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM index_projection_records WHERE projection_name=? ORDER BY sequence_id",
                (arguments.projection,),
            ).fetchall()
        if arguments.action == "graph-sync":
            if arguments.rebuild or not sequence_ids:
                graph_nodes = connection.execute(
                    "SELECT * FROM index_graph_nodes ORDER BY node_id"
                ).fetchall()
                graph_edges = connection.execute(
                    "SELECT * FROM index_graph_edges ORDER BY from_node_id, to_node_id, edge_type"
                ).fetchall()
            else:
                placeholders = ",".join("?" for _ in normalized_ids)
                graph_nodes = connection.execute(
                    f"SELECT * FROM index_graph_nodes WHERE first_sequence_id IN ({placeholders}) ORDER BY node_id",
                    normalized_ids,
                ).fetchall()
                graph_edges = connection.execute(
                    f"SELECT * FROM index_graph_edges WHERE sequence_id IN ({placeholders}) "
                    "ORDER BY from_node_id, to_node_id, edge_type",
                    normalized_ids,
                ).fetchall()
    finally:
        connection.close()
    qihse_path = arguments.db.with_suffix(arguments.db.suffix + ".qihse.qdb")
    graph_path = arguments.db.with_suffix(arguments.db.suffix + ".graph.qdb")
    if arguments.action == "graph-sync":
        from ..search.qihse_graph_backend import QihseGraphIndex

        with QihseGraphIndex(graph_path, rebuild=arguments.rebuild) as index:
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
            result = {
                "available": True,
                "ok": True,
                "path": str(graph_path),
                "library": str(index.library_path),
                "nodes": len(graph_nodes),
                "edges": len(graph_edges),
                **changes,
            }
        print("SPECTRA_NATIVE_PROBE=" + json.dumps(result, default=str, sort_keys=True), flush=True)
        return 0
    if arguments.action == "graph-query":
        if arguments.node_id is None:
            raise SystemExit("--node-id is required for graph-query")
        from ..search.qihse_graph_backend import (
            EDGE_BOTH,
            EDGE_INCOMING,
            EDGE_OUTGOING,
            QihseGraphIndex,
        )

        directions = {"outgoing": EDGE_OUTGOING, "incoming": EDGE_INCOMING, "both": EDGE_BOTH}
        with QihseGraphIndex(graph_path, read_only=True) as index:
            records = index.edge_records(
                arguments.node_id,
                edge_type=arguments.edge_type,
                direction=directions[arguments.direction],
                limit=arguments.sample_size,
            )
            result = {
                "available": True,
                "ok": True,
                "library": str(index.library_path),
                "records": records,
            }
        print("SPECTRA_NATIVE_PROBE=" + json.dumps(result, default=str, sort_keys=True), flush=True)
        return 0
    if arguments.action == "sync":
        if arguments.projection != "qihse.content.v1":
            raise SystemExit("sync supports only the QIHSE projection")
        ids = [int(row["sequence_id"]) for row in rows]
        vectors = [json.loads(row["vector_json"]) for row in rows]
        with QihseVectorIndex(qihse_path, rebuild=arguments.rebuild) as index:
            changes = index.upsert(ids, vectors)
            result = {
                "available": True,
                "ok": True,
                "path": str(qihse_path),
                "library": str(index.library_path),
                "rows": len(rows),
                **changes,
            }
        print("SPECTRA_NATIVE_PROBE=" + json.dumps(result, default=str, sort_keys=True), flush=True)
        return 0
    if arguments.action == "search":
        if not arguments.query_vector:
            raise SystemExit("--query-vector is required for search")
        vector = json.loads(arguments.query_vector)
        with QihseVectorIndex(qihse_path) as index:
            matches = index.search(vector, limit=arguments.sample_size)
            result = {
                "available": True,
                "ok": True,
                "library": str(index.library_path),
                "matches": matches,
            }
        print("SPECTRA_NATIVE_PROBE=" + json.dumps(result, default=str, sort_keys=True), flush=True)
        return 0
    if arguments.action == "lookup":
        if arguments.lookup_key is None:
            raise SystemExit("--lookup-key is required for lookup")
        from ..search.keystone_bindings import KEYSTONE_WORKLOAD_IDS, KeystoneSearchEngine, keystone_available

        if not keystone_available():
            raise SystemExit("KEYSTONE is unavailable")
        values = sorted({int(row["numeric_key"]) for row in rows if row["numeric_key"] is not None})
        engine = KeystoneSearchEngine(KEYSTONE_WORKLOAD_IDS)
        position = engine.search(values, arguments.lookup_key)
        result = {
            "available": True,
            "ok": True,
            "found": position is not None,
            "position": position,
            "numeric_key": arguments.lookup_key,
        }
        print("SPECTRA_NATIVE_PROBE=" + json.dumps(result, default=str, sort_keys=True), flush=True)
        return 0
    result = IndexProjector.verify_native_in_process(
        arguments.projection,
        rows,
        arguments.sample_size,
        qihse_path=qihse_path,
    )
    print("SPECTRA_NATIVE_PROBE=" + json.dumps(result, default=str, sort_keys=True), flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
