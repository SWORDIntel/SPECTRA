"""
SPECTRA Immutable Analyst Label Store
=====================================
Stores analyst feedback (Confirm/Reject/Unsure) as an append-only,
cryptographically chained record. Labels never get overwritten —
corrections are new entries that supersede prior ones.

This is the ground-truth source for:
- Evaluation harness benchmarks
- Training label generation
- Calibration feedback loops

Design:
- Append-only: labels are never deleted or modified
- Chain integrity: each label includes a hash of the previous label
- Supersession: a new label with same (subject_a, subject_b, label_type)
  supersedes the prior one, but both remain in the store
- Immutable: the SQLite table has no UPDATE or DELETE paths
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AnalystLabelType(Enum):
    """What kind of label the analyst is providing."""
    SAME_ACTOR = "same_actor"           # Confirms/rejects same-actor hypothesis
    DIFFERENT_ACTOR = "different_actor"  # Confirms/rejects different-actor hypothesis
    CAMPAIGN_MEMBER = "campaign_member"  # Confirms/rejects campaign membership
    RELATIONSHIP = "relationship"        # Confirms/rejects a relationship hypothesis
    THREAT_ASSESSMENT = "threat_assessment"  # Confirms/rejects a threat score
    BOT_DETECTION = "bot_detection"      # Confirms/rejects bot classification


class AnalystVerdict(Enum):
    """The analyst's verdict on a hypothesis."""
    CONFIRM = "confirm"     # Analyst agrees with the hypothesis
    REJECT = "reject"       # Analyst disagrees with the hypothesis
    UNSURE = "unsure"       # Analyst is uncertain — insufficient evidence


@dataclass
class AnalystLabel:
    """
    A single analyst label — immutable once created.

    The label_hash chains to the previous label for tamper detection.
    """
    label_id: str = ""          # Deterministic ID (auto-generated if empty)
    label_type: AnalystLabelType = AnalystLabelType.SAME_ACTOR
    verdict: AnalystVerdict = AnalystVerdict.UNSURE
    subject_a: str = ""         # Canonical entity ID
    subject_b: Optional[str] = None  # Canonical entity ID (for pairwise labels)
    hypothesis_id: Optional[str] = None  # The hypothesis being labeled
    evidence_ids: List[str] = field(default_factory=list)  # Evidence reviewed
    analyst_id: str = ""        # Who made the label
    notes: str = ""             # Free-text justification
    confidence: float = 1.0     # Analyst's confidence in their own verdict
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    prev_hash: str = ""         # Hash of the previous label (chain integrity)
    label_hash: str = ""        # Hash of this label (computed in __post_init__)

    def __post_init__(self):
        if not self.label_id:
            self.label_id = self._compute_id()
        if not self.label_hash:
            self.label_hash = self._compute_hash()

    def _compute_id(self) -> str:
        """Deterministic label ID."""
        payload = (
            self.label_type.value
            + "|"
            + self.subject_a
            + "|"
            + (self.subject_b or "")
            + "|"
            + (self.hypothesis_id or "")
            + "|"
            + self.analyst_id
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _compute_hash(self) -> str:
        """Chain hash — includes prev_hash for tamper detection."""
        payload = (
            self.label_id
            + "|"
            + self.label_type.value
            + "|"
            + self.verdict.value
            + "|"
            + self.subject_a
            + "|"
            + (self.subject_b or "")
            + "|"
            + (self.hypothesis_id or "")
            + "|"
            + ",".join(sorted(self.evidence_ids))
            + "|"
            + self.analyst_id
            + "|"
            + self.notes
            + "|"
            + str(self.confidence)
            + "|"
            + self.created_at.isoformat()
            + "|"
            + self.prev_hash
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label_id": self.label_id,
            "label_type": self.label_type.value,
            "verdict": self.verdict.value,
            "subject_a": self.subject_a,
            "subject_b": self.subject_b,
            "hypothesis_id": self.hypothesis_id,
            "evidence_ids": self.evidence_ids,
            "analyst_id": self.analyst_id,
            "notes": self.notes,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "prev_hash": self.prev_hash,
            "label_hash": self.label_hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AnalystLabel":
        label_type = d["label_type"]
        if isinstance(label_type, str):
            label_type = AnalystLabelType(label_type)
        verdict = d["verdict"]
        if isinstance(verdict, str):
            verdict = AnalystVerdict(verdict)
        created = d.get("created_at")
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                created = datetime.now(timezone.utc)
        return cls(
            label_id=d.get("label_id", ""),
            label_type=label_type,
            verdict=verdict,
            subject_a=d["subject_a"],
            subject_b=d.get("subject_b"),
            hypothesis_id=d.get("hypothesis_id"),
            evidence_ids=d.get("evidence_ids", []),
            analyst_id=d.get("analyst_id", ""),
            notes=d.get("notes", ""),
            confidence=d.get("confidence", 1.0),
            created_at=created or datetime.now(timezone.utc),
            prev_hash=d.get("prev_hash", ""),
            label_hash=d.get("label_hash", ""),
        )

    def to_sql_row(self) -> Tuple:
        return (
            self.label_id,
            self.label_type.value,
            self.verdict.value,
            self.subject_a,
            self.subject_b,
            self.hypothesis_id,
            json.dumps(self.evidence_ids),
            self.analyst_id,
            self.notes,
            self.confidence,
            self.created_at.isoformat(),
            self.prev_hash,
            self.label_hash,
        )


class AnalystLabelStore:
    """
    Append-only store for analyst labels.

    Labels are never deleted or updated. A new label with the same
    (subject_a, subject_b, label_type) supersedes prior labels, but
    all entries remain in the store for audit purposes.

    Usage:
        store = AnalystLabelStore(db_conn)
        store.add_label(AnalystLabel(
            label_type=AnalystLabelType.SAME_ACTOR,
            verdict=AnalystVerdict.CONFIRM,
            subject_a="telegram:user:123",
            subject_b="telegram:user:456",
            analyst_id="analyst-1",
            notes="Confirmed via external OSINT",
        ))
        labels = store.get_labels("telegram:user:123", "telegram:user:456")
        latest = store.get_latest_label("telegram:user:123", "telegram:user:456",
                                         AnalystLabelType.SAME_ACTOR)
    """

    def __init__(self, db_conn):
        """
        Args:
            db_conn: SQLite connection (will create table if needed)
        """
        self.conn = db_conn
        self._ensure_table()

    def _ensure_table(self):
        """Create the analyst_labels table if it doesn't exist."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS analyst_labels (
                label_id        TEXT PRIMARY KEY,
                label_type      TEXT NOT NULL,
                verdict         TEXT NOT NULL,
                subject_a       TEXT NOT NULL,
                subject_b       TEXT,
                hypothesis_id   TEXT,
                evidence_ids    TEXT,
                analyst_id      TEXT NOT NULL DEFAULT '',
                notes           TEXT DEFAULT '',
                confidence      REAL DEFAULT 1.0,
                created_at      TEXT NOT NULL,
                prev_hash       TEXT DEFAULT '',
                label_hash      TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_analyst_labels_subjects
            ON analyst_labels(subject_a, subject_b)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_analyst_labels_type
            ON analyst_labels(label_type)
        """)
        self.conn.commit()

    def add_label(self, label: AnalystLabel) -> str:
        """
        Add a label to the store. The label's prev_hash is set to the
        hash of the most recent label in the store (chain integrity).

        Args:
            label: The AnalystLabel to add

        Returns:
            The label_id of the added label
        """
        # Get the last label's hash for chain integrity
        cursor = self.conn.execute(
            "SELECT label_hash FROM analyst_labels ORDER BY created_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            label.prev_hash = row[0]
            # Recompute hash with updated prev_hash
            label.label_hash = label._compute_hash()

        self.conn.execute(
            """INSERT OR IGNORE INTO analyst_labels
               (label_id, label_type, verdict, subject_a, subject_b,
                hypothesis_id, evidence_ids, analyst_id, notes, confidence,
                created_at, prev_hash, label_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            label.to_sql_row(),
        )
        self.conn.commit()
        logger.info(f"Added analyst label {label.label_id} ({label.verdict.value})")
        return label.label_id

    def get_labels(
        self,
        subject_a: str,
        subject_b: Optional[str] = None,
        label_type: Optional[AnalystLabelType] = None,
    ) -> List[AnalystLabel]:
        """
        Get all labels for a subject pair, optionally filtered by type.

        Returns labels in chronological order (oldest first).
        Superseded labels are included — use get_latest_label() for the
        current verdict.
        """
        query = "SELECT * FROM analyst_labels WHERE subject_a = ?"
        params: list = [subject_a]

        if subject_b is not None:
            query += " AND subject_b = ?"
            params.append(subject_b)
        if label_type is not None:
            query += " AND label_type = ?"
            params.append(label_type.value)

        query += " ORDER BY created_at ASC"

        cursor = self.conn.execute(query, params)
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return [self._row_to_label(dict(zip(columns, row))) for row in rows]

    def get_latest_label(
        self,
        subject_a: str,
        subject_b: str,
        label_type: AnalystLabelType,
    ) -> Optional[AnalystLabel]:
        """
        Get the most recent label for a subject pair and type.
        This is the 'current' verdict — prior labels are superseded.
        """
        labels = self.get_labels(subject_a, subject_b, label_type)
        return labels[-1] if labels else None

    def get_all_labels(self) -> List[AnalystLabel]:
        """Get all labels in the store (chronological order)."""
        cursor = self.conn.execute(
            "SELECT * FROM analyst_labels ORDER BY created_at ASC"
        )
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return [self._row_to_label(dict(zip(columns, row))) for row in rows]

    def get_training_labels(
        self,
        label_type: Optional[AnalystLabelType] = None,
    ) -> List[Tuple[AnalystLabel, str]]:
        """
        Get labels suitable for training/evaluation.

        Returns list of (label, ground_truth) tuples where ground_truth
        is "positive" for CONFIRM, "negative" for REJECT, and "abstain"
        for UNSURE.

        Only the latest label per (subject_a, subject_b, label_type) is
        included — superseded labels are excluded.
        """
        all_labels = self.get_all_labels()
        if label_type:
            all_labels = [l for l in all_labels if l.label_type == label_type]

        # Group by (subject_a, subject_b, label_type) and keep latest
        latest: Dict[Tuple, AnalystLabel] = {}
        for label in all_labels:
            key = (label.subject_a, label.subject_b, label.label_type)
            latest[key] = label  # Last one wins (chronological order)

        result = []
        for label in latest.values():
            if label.verdict == AnalystVerdict.CONFIRM:
                gt = "positive"
            elif label.verdict == AnalystVerdict.REJECT:
                gt = "negative"
            else:
                gt = "abstain"
            result.append((label, gt))

        return result

    def verify_chain(self) -> bool:
        """
        Verify the integrity of the label chain.

        Each label's prev_hash should match the label_hash of the
        preceding label. Returns True if the chain is intact.
        """
        labels = self.get_all_labels()
        prev_hash = ""
        for label in labels:
            if label.prev_hash != prev_hash:
                logger.error(f"Chain broken at label {label.label_id}")
                return False
            # Verify hash
            expected_hash = label._compute_hash()
            if label.label_hash != expected_hash:
                logger.error(f"Hash mismatch at label {label.label_id}")
                return False
            prev_hash = label.label_hash
        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics about the label store."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM analyst_labels")
        total = cursor.fetchone()[0]

        cursor = self.conn.execute(
            "SELECT verdict, COUNT(*) FROM analyst_labels GROUP BY verdict"
        )
        by_verdict = dict(cursor.fetchall())

        cursor = self.conn.execute(
            "SELECT label_type, COUNT(*) FROM analyst_labels GROUP BY label_type"
        )
        by_type = dict(cursor.fetchall())

        return {
            "total_labels": total,
            "by_verdict": by_verdict,
            "by_type": by_type,
        }

    def _row_to_label(self, row: Dict) -> AnalystLabel:
        """Convert a DB row dict to an AnalystLabel."""
        evidence_ids = row.get("evidence_ids", "[]")
        if isinstance(evidence_ids, str):
            try:
                evidence_ids = json.loads(evidence_ids)
            except (json.JSONDecodeError, TypeError):
                evidence_ids = []

        created = row.get("created_at", "")
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                created = datetime.now(timezone.utc)

        return AnalystLabel(
            label_id=row["label_id"],
            label_type=AnalystLabelType(row["label_type"]),
            verdict=AnalystVerdict(row["verdict"]),
            subject_a=row["subject_a"],
            subject_b=row.get("subject_b"),
            hypothesis_id=row.get("hypothesis_id"),
            evidence_ids=evidence_ids,
            analyst_id=row.get("analyst_id", ""),
            notes=row.get("notes", ""),
            confidence=row.get("confidence", 1.0),
            created_at=created,
            prev_hash=row.get("prev_hash", ""),
            label_hash=row.get("label_hash", ""),
        )


__all__ = [
    "AnalystLabelType",
    "AnalystVerdict",
    "AnalystLabel",
    "AnalystLabelStore",
]
