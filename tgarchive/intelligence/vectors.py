"""
SPECTRA Intelligence Vector Backend
====================================
Dedicated vector search and feature embeddings for analytical intelligence evidence.

Provides:
- Fixed 64-dimensional feature embeddings for ``AnalysisEvidence`` objects
  encoding evidence type, score, confidence, direction, model, and metadata.
- ``IntelligenceVectorIndex``: QIHSE vector database wrapper storing evidence
  vectors in a dedicated sidecar store (``<database>.intelligence.qdb``).
- ``resolve_search_results``: Maps sequence IDs from vector queries back to
  canonical evidence IDs and deserialized payloads.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
from pathlib import Path
from typing import Any

from ..sqlite_runtime import connect_sqlite
from ..search.qihse_vector_backend import QihseVectorIndex
from .schema import AnalysisEvidence, EvidenceDirection

logger = logging.getLogger(__name__)

# Vector dimensionality must match QIHSE and index_projector standard
INTELLIGENCE_VECTOR_DIMENSIONS = 64


def _hash_position(key: str, dimensions: int = INTELLIGENCE_VECTOR_DIMENSIONS) -> int:
    """Map a string key to a deterministic vector dimension position using blake2b."""
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") % dimensions


def evidence_to_vector(
    evidence: AnalysisEvidence,
    dimensions: int = INTELLIGENCE_VECTOR_DIMENSIONS,
) -> list[float]:
    """Convert an ``AnalysisEvidence`` instance into a 64-dimensional feature vector.

    Encodes analytical properties (evidence type, score, confidence,
    direction, model, and metadata) into an L2-normalized unit vector. This
    captures the 'analytical signature' of the evidence so similar evidence
    types with similar scores cluster together in semantic vector space.

    Args:
        evidence: The ``AnalysisEvidence`` object to embed.
        dimensions: Vector dimensionality (defaults to 64).

    Returns:
        A list of 64 floats normalized to unit length.
    """
    vector = [0.0] * dimensions

    # 1. Evidence Type (primary anchor)
    pos_type = _hash_position(f"type:{evidence.evidence_type}", dimensions)
    vector[pos_type] += 1.0

    # 2. Scale score (0-1 range; if raw score > 1.0 assume 0-10 scale and divide by 10)
    raw_score = float(evidence.score)
    if raw_score > 1.0:
        scaled_score = max(0.0, min(1.0, raw_score / 10.0))
    else:
        scaled_score = max(0.0, min(1.0, raw_score))

    # 3. Scale confidence (0-1 range)
    scaled_confidence = max(0.0, min(1.0, float(evidence.confidence)))

    # Modulate type positions with score and confidence
    pos_type_score = _hash_position(f"type_score:{evidence.evidence_type}", dimensions)
    vector[pos_type_score] += scaled_score

    pos_type_conf = _hash_position(f"type_conf:{evidence.evidence_type}", dimensions)
    vector[pos_type_conf] += scaled_confidence

    pos_type_combined = _hash_position(f"type_combined:{evidence.evidence_type}", dimensions)
    vector[pos_type_combined] += scaled_score * scaled_confidence

    # Global score & confidence features
    pos_score = _hash_position("global:score", dimensions)
    vector[pos_score] += scaled_score

    pos_conf = _hash_position("global:confidence", dimensions)
    vector[pos_conf] += scaled_confidence

    # 4. Direction
    dir_val = (
        evidence.direction.value
        if isinstance(evidence.direction, EvidenceDirection)
        else str(evidence.direction)
    )
    pos_dir = _hash_position(f"direction:{dir_val}", dimensions)
    vector[pos_dir] += 0.5

    pos_dir_score = _hash_position(f"dir_score:{dir_val}", dimensions)
    vector[pos_dir_score] += scaled_score

    # 5. Model & model version
    if evidence.model:
        pos_model = _hash_position(f"model:{evidence.model}", dimensions)
        vector[pos_model] += 0.5
    if evidence.model_version:
        pos_model_ver = _hash_position(
            f"model_version:{evidence.model}:{evidence.model_version}",
            dimensions,
        )
        vector[pos_model_ver] += 0.25

    # 6. Metadata keys
    if isinstance(evidence.metadata, dict):
        for key in sorted(evidence.metadata.keys()):
            pos_meta = _hash_position(f"metadata:{key}", dimensions)
            vector[pos_meta] += 0.25

    # 7. Normalize vector to unit length (L2 norm)
    magnitude = math.sqrt(sum(v * v for v in vector))
    if magnitude > 0.0:
        return [v / magnitude for v in vector]
    return vector


class IntelligenceVectorIndex:
    """Dedicated vector index for intelligence evidence feature vectors.

    Wraps a vector backend (QIHSE or KEYSTONE) with a separate sidecar
    database (``<db_path>.intelligence.qdb``) to isolate evidence feature
    vectors from content full-text vectors.

    Falls back to the KEYSTONE vector engine (LSH + SIMD) when QIHSE is
    unavailable, providing hardware-agnostic vector search with 8-level
    graceful fallback (CUDA → AVX-512 → AVX2 → AVX → SSE4.2 → scalar).
    """

    def __init__(self, db_path: Path | str, *, rebuild: bool = False) -> None:
        self.db_path = Path(db_path)
        self.qdb_path = Path(f"{self.db_path}.intelligence.qdb")
        self._backend = "qihse"
        try:
            self._index = QihseVectorIndex(self.qdb_path, rebuild=rebuild)
        except Exception as exc:
            logger.info(
                "IntelligenceVectorIndex: QIHSE unavailable (%s), "
                "trying KEYSTONE vector engine.",
                exc,
            )
            from ..search.keystone_vector_backend import KeystoneVectorIndex
            ks_path = Path(f"{self.db_path}.intelligence.keystone_vec.bin")
            self._index = KeystoneVectorIndex(
                ks_path,
                dim=INTELLIGENCE_VECTOR_DIMENSIONS,
                rebuild=rebuild,
            )
            self._backend = "keystone"
            logger.info(
                "IntelligenceVectorIndex: using KEYSTONE vector engine "
                "(backend=%s) at %s",
                self._index.backend,
                ks_path,
            )

    @property
    def path(self) -> Path:
        """Path to the underlying vector store file."""
        return self.qdb_path

    @property
    def library_path(self) -> Path:
        """Path to the loaded native library."""
        return self._index.library_path

    @property
    def backend(self) -> str:
        """Active vector backend name: 'qihse' or 'keystone'."""
        return self._backend

    def upsert_evidence(
        self,
        evidence: AnalysisEvidence,
        sequence_id: int,
    ) -> dict[str, Any]:
        """Convert evidence to a feature vector and upsert under sequence_id.

        Args:
            evidence: The AnalysisEvidence object to index.
            sequence_id: The durable outbox sequence ID.

        Returns:
            Dictionary with counts of inserted and updated records.
        """
        vector = evidence_to_vector(evidence)
        return self._index.upsert([int(sequence_id)], [vector])

    def upsert_many(
        self,
        items: list[tuple[int, AnalysisEvidence]],
    ) -> dict[str, Any]:
        """Batch upsert multiple (sequence_id, evidence) pairs into the vector index.

        Args:
            items: List of (sequence_id, AnalysisEvidence) tuples.

        Returns:
            Dictionary with counts of inserted and updated records.
        """
        if not items:
            return {"inserted": 0, "updated": 0}
        ids = [int(seq_id) for seq_id, _ in items]
        vectors = [evidence_to_vector(evidence) for _, evidence in items]
        return self._index.upsert(ids, vectors)

    def search_similar(
        self,
        evidence: AnalysisEvidence,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find the top-k most similar evidence vectors to the provided evidence.

        Args:
            evidence: The query AnalysisEvidence object.
            limit: Maximum number of matches to return.

        Returns:
            List of dictionaries with 'id' (sequence_id) and 'score'.
        """
        vector = evidence_to_vector(evidence)
        return self.search_by_vector(vector, limit=limit)

    def search_by_vector(
        self,
        vector: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search the index directly using a raw query vector.

        Args:
            vector: 64-dimensional query vector.
            limit: Maximum number of matches to return.

        Returns:
            List of dictionaries with 'id' (sequence_id) and 'score'.
        """
        return self._index.search(vector, limit=limit)

    def close(self) -> None:
        """Close the underlying QIHSE vector database."""
        if hasattr(self, "_index") and self._index is not None:
            self._index.close()

    def __enter__(self) -> IntelligenceVectorIndex:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def resolve_search_results(
    db_path: Path | str,
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join vector search results against SQLite projection records.

    Maps sequence IDs returned by vector searches to canonical evidence IDs
    and their deserialized payload dictionaries.

    Args:
        db_path: Path to the SQLite database (e.g. spectra.db).
        results: List of search result dictionaries containing at least 'id'
                 and optional 'score'.

    Returns:
        List of resolved dictionaries with keys:
        - sequence_id: int
        - score: float
        - evidence_id: str
        - source_table: str
        - payload: dict
    """
    if not results:
        return []

    seq_ids = [int(item["id"]) for item in results if "id" in item]
    if not seq_ids:
        return []

    records_by_id: dict[int, dict[str, Any]] = {}
    with connect_sqlite(db_path, read_only=True) as conn:
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in seq_ids)
        try:
            cursor = conn.execute(
                f"""
                SELECT sequence_id, source_table, source_key, payload_json
                FROM index_projection_records
                WHERE sequence_id IN ({placeholders})
                """,
                seq_ids,
            )
            for row in cursor.fetchall():
                seq_id = int(row["sequence_id"])
                if seq_id not in records_by_id:
                    payload = {}
                    if row["payload_json"]:
                        try:
                            payload = json.loads(row["payload_json"])
                        except (json.JSONDecodeError, TypeError):
                            payload = {}
                    records_by_id[seq_id] = {
                        "evidence_id": str(row["source_key"]),
                        "source_table": str(row["source_table"]),
                        "payload": payload,
                    }
        except sqlite3.OperationalError:
            pass

        # Fallback to index_outbox if projection records are missing
        missing_ids = [seq_id for seq_id in seq_ids if seq_id not in records_by_id]
        if missing_ids:
            missing_placeholders = ",".join("?" for _ in missing_ids)
            try:
                cursor = conn.execute(
                    f"""
                    SELECT sequence_id, source_table, source_key, payload_json
                    FROM index_outbox
                    WHERE sequence_id IN ({missing_placeholders})
                    """,
                    missing_ids,
                )
                for row in cursor.fetchall():
                    seq_id = int(row["sequence_id"])
                    if seq_id not in records_by_id:
                        payload = {}
                        if row["payload_json"]:
                            try:
                                payload = json.loads(row["payload_json"])
                            except (json.JSONDecodeError, TypeError):
                                payload = {}
                        records_by_id[seq_id] = {
                            "evidence_id": str(row["source_key"]),
                            "source_table": str(row["source_table"]),
                            "payload": payload,
                        }
            except sqlite3.OperationalError:
                pass

    resolved: list[dict[str, Any]] = []
    for item in results:
        if "id" not in item:
            continue
        seq_id = int(item["id"])
        score = float(item.get("score", 0.0))
        rec = records_by_id.get(seq_id)
        if rec is not None:
            resolved.append({
                "sequence_id": seq_id,
                "score": score,
                "evidence_id": rec["evidence_id"],
                "source_table": rec["source_table"],
                "payload": rec["payload"],
            })
        else:
            resolved.append({
                "sequence_id": seq_id,
                "score": score,
                "evidence_id": str(seq_id),
                "source_table": "unknown",
                "payload": {},
            })

    return resolved


__all__ = [
    "INTELLIGENCE_VECTOR_DIMENSIONS",
    "IntelligenceVectorIndex",
    "evidence_to_vector",
    "resolve_search_results",
]
