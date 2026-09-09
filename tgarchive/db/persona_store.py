"""Durable SQLite store for consent-based persona training data.

Persists authorized persona targets, longitudinal positive/negative examples,
domain knowledge observations (score != confidence), and style/vocabulary
snapshots into ``spectra.db``. Every write flows through ``IndexOutbox`` so the
records participate in the durable projection pipeline (QIHSE/KEYSTONE/FTS).

The store is duck-typed with respect to the analytical model in
``tgarchive.intelligence.persona_training``: it accepts any object exposing the
expected attributes rather than importing concrete dataclasses. This keeps the
persistence layer decoupled from the analytical layer and avoids circular
imports.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..sqlite_runtime import connect_sqlite
from .index_outbox import IndexOutbox
from .schema import SCHEMA_SQL, apply_migrations

# Outbox source-table names — these are the routing keys IndexProjector uses.
PERSONA_TARGET_SOURCE_TABLE = "persona_targets"
PERSONA_EXAMPLES_SOURCE_TABLE = "persona_examples"
PERSONA_KNOWLEDGE_SOURCE_TABLE = "persona_knowledge_observations"
PERSONA_SNAPSHOT_SOURCE_TABLE = "persona_profile_snapshots"

PERSONA_SOURCE_TABLES = (
    PERSONA_TARGET_SOURCE_TABLE,
    PERSONA_EXAMPLES_SOURCE_TABLE,
    PERSONA_KNOWLEDGE_SOURCE_TABLE,
    PERSONA_SNAPSHOT_SOURCE_TABLE,
)

_VALID_AUTH = {"pending", "authorized", "revoked", "denied"}
_VALID_LABELS = {"positive", "negative", "review"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(obj: Any) -> str:
    return json.dumps(obj, default=str, sort_keys=True)


def _validate_score_confidence(score: float, confidence: float) -> None:
    for name, value in (("score", score), ("confidence", confidence)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"{name} must be a number, got {type(value).__name__}")
        if not (0.0 <= float(value) <= 1.0):
            raise ValueError(f"{name} must be in [0.0, 1.0], got {value}")


def _example_id(target_id: str, source_type: str, source_message_id: Optional[int],
                source_channel_id: Optional[int], label: str, text: str = "") -> str:
    """Deterministic example ID for dedup.

    When ``source_message_id`` is None (manual entry), include a text hash so
    distinct texts get distinct IDs.
    """
    if source_message_id is None:
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        raw = f"{target_id}|{source_type}|{text_hash}|{source_channel_id}|{label}"
    else:
        raw = f"{target_id}|{source_type}|{source_message_id}|{source_channel_id}|{label}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _observation_id(target_id: str, domain: str, evaluator: str,
                    evidence_source: Optional[str], observed_at: Optional[str]) -> str:
    raw = f"{target_id}|{domain}|{evaluator}|{evidence_source}|{observed_at}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _snapshot_id(target_id: str, as_of: str) -> str:
    raw = f"{target_id}|{as_of}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# JSON columns to decode when reading snapshot rows.
# V1 columns are NOT NULL (default to {} on decode error).
# V2 columns are nullable (default to None on missing, {} on decode error).
_SNAPSHOT_V1_JSON_KEYS = (
    "vocabulary_json", "distinctive_vocab_json", "bigrams_json",
    "linguistic_features_json", "knowledge_estimates_json",
)
_SNAPSHOT_V2_JSON_KEYS = (
    "orthographic_features_json", "error_features_json",
    "discourse_features_json", "formatting_features_json",
    "notation_features_json", "register_features_json",
    "conversation_features_json", "syntax_features_json",
    "temporal_features_json",
    "conditional_features_json", "interaction_features_json",
    "dialogue_acts_features_json",
)


def _decode_snapshot_row(d: Dict[str, Any]) -> Dict[str, Any]:
    """Decode all JSON columns in a snapshot row dict."""
    for key in _SNAPSHOT_V1_JSON_KEYS:
        field = key.replace("_json", "")
        try:
            d[field] = json.loads(d.pop(key))
        except (json.JSONDecodeError, KeyError, TypeError):
            d[field] = {}
    for key in _SNAPSHOT_V2_JSON_KEYS:
        field = key.replace("_json", "")
        raw = d.pop(key, None)
        if raw is None:
            d[field] = None
        else:
            try:
                d[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d[field] = {}
    return d


# ─── Module-level record functions (use inside existing connections) ────────

def record_persona_target(
    connection: sqlite3.Connection,
    *,
    target_id: str,
    display_name: str,
    platform: str = "telegram",
    platform_user_id: Optional[str] = None,
    authorization_status: str = "pending",
    consent_record: Optional[str] = None,
    notes: str = "",
) -> int | None:
    """Insert or update a persona target row and append to IndexOutbox."""
    if not target_id or not isinstance(target_id, str):
        raise ValueError("target_id must be a non-empty string")
    if not display_name or not isinstance(display_name, str):
        raise ValueError("display_name must be a non-empty string")
    if authorization_status not in _VALID_AUTH:
        raise ValueError(f"authorization_status must be one of {_VALID_AUTH}")
    now = _now()
    connection.execute(
        """
        INSERT INTO persona_targets
            (target_id, display_name, platform, platform_user_id,
             authorization_status, consent_record, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(target_id) DO UPDATE SET
            display_name=excluded.display_name,
            platform=excluded.platform,
            platform_user_id=excluded.platform_user_id,
            authorization_status=excluded.authorization_status,
            consent_record=excluded.consent_record,
            notes=excluded.notes,
            updated_at=excluded.updated_at
        """,
        (target_id, display_name, platform, platform_user_id,
         authorization_status, consent_record, notes, now, now),
    )
    payload = {
        "target_id": target_id,
        "display_name": display_name,
        "platform": platform,
        "platform_user_id": platform_user_id,
        "authorization_status": authorization_status,
        "consent_record": consent_record,
        "notes": notes,
        "updated_at": now,
    }
    return IndexOutbox.append_to(
        connection,
        source_table=PERSONA_TARGET_SOURCE_TABLE,
        source_key=target_id,
        event_type="save",
        payload=payload,
    )


def record_persona_example(
    connection: sqlite3.Connection,
    *,
    target_id: str,
    label: str,
    text: str,
    source_type: str = "message",
    source_message_id: Optional[int] = None,
    source_channel_id: Optional[int] = None,
    source_user_id: Optional[int] = None,
    observed_at: Optional[str] = None,
    weight: float = 1.0,
    notes: str = "",
    source_revision: Optional[str] = None,
) -> tuple[str | None, int | None]:
    """Insert a persona example (dedup by natural key) and append to IndexOutbox.

    Returns ``(example_id, outbox_sequence_id)``. ``example_id`` is None only if
    the insert was skipped due to a conflict (idempotent re-insert).
    """
    if label not in _VALID_LABELS:
        raise ValueError(f"label must be one of {_VALID_LABELS}, got {label!r}")
    if not text or not isinstance(text, str):
        raise ValueError("text must be a non-empty string")
    if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
        raise ValueError("weight must be a positive number")
    example_id = _example_id(target_id, source_type, source_message_id,
                             source_channel_id, label, text)
    now = _now()
    cursor = connection.execute(
        """
        INSERT INTO persona_examples
            (example_id, target_id, label, text, source_type,
             source_message_id, source_channel_id, source_user_id,
             observed_at, collected_at, weight, notes, source_revision)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(example_id) DO NOTHING
        ON CONFLICT(target_id, source_type, source_message_id, source_channel_id, label) DO NOTHING
        """,
        (example_id, target_id, label, text, source_type,
         source_message_id, source_channel_id, source_user_id,
         observed_at, now, float(weight), notes, source_revision),
    )
    if cursor.rowcount == 0:
        return None, None
    payload = {
        "example_id": example_id,
        "target_id": target_id,
        "label": label,
        "text": text,
        "source_type": source_type,
        "source_message_id": source_message_id,
        "source_channel_id": source_channel_id,
        "source_user_id": source_user_id,
        "observed_at": observed_at,
        "collected_at": now,
        "weight": float(weight),
        "notes": notes,
    }
    seq = IndexOutbox.append_to(
        connection,
        source_table=PERSONA_EXAMPLES_SOURCE_TABLE,
        source_key=example_id,
        event_type="save",
        payload=payload,
        source_revision=source_revision,
    )
    return example_id, seq


def record_knowledge_observation(
    connection: sqlite3.Connection,
    *,
    target_id: str,
    domain: str,
    score: float,
    confidence: float,
    evidence_source: Optional[str] = None,
    evaluator: str = "manual",
    evaluator_version: str = "1.0",
    observed_at: Optional[str] = None,
    notes: str = "",
) -> tuple[str | None, int | None]:
    """Insert a domain knowledge observation and append to IndexOutbox."""
    _validate_score_confidence(score, confidence)
    if not domain or not isinstance(domain, str):
        raise ValueError("domain must be a non-empty string")
    observation_id = _observation_id(target_id, domain, evaluator,
                                     evidence_source, observed_at)
    now = _now()
    cursor = connection.execute(
        """
        INSERT INTO persona_knowledge_observations
            (observation_id, target_id, domain, score, confidence,
             evidence_source, evaluator, evaluator_version, observed_at,
             recorded_at, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(observation_id) DO NOTHING
        """,
        (observation_id, target_id, domain, float(score), float(confidence),
         evidence_source, evaluator, evaluator_version, observed_at, now, notes),
    )
    if cursor.rowcount == 0:
        return None, None
    payload = {
        "observation_id": observation_id,
        "target_id": target_id,
        "domain": domain,
        "score": float(score),
        "confidence": float(confidence),
        "evidence_source": evidence_source,
        "evaluator": evaluator,
        "evaluator_version": evaluator_version,
        "observed_at": observed_at,
        "recorded_at": now,
        "notes": notes,
    }
    seq = IndexOutbox.append_to(
        connection,
        source_table=PERSONA_KNOWLEDGE_SOURCE_TABLE,
        source_key=observation_id,
        event_type="save",
        payload=payload,
    )
    return observation_id, seq


def record_snapshot(
    connection: sqlite3.Connection,
    *,
    target_id: str,
    as_of: str,
    positive_count: int = 0,
    negative_count: int = 0,
    review_count: int = 0,
    vocabulary: Optional[Dict[str, Any]] = None,
    distinctive_vocab: Optional[Dict[str, Any]] = None,
    bigrams: Optional[Dict[str, Any]] = None,
    linguistic_features: Optional[Dict[str, Any]] = None,
    knowledge_estimates: Optional[Dict[str, Any]] = None,
    orthographic_features: Optional[Dict[str, Any]] = None,
    error_features: Optional[Dict[str, Any]] = None,
    discourse_features: Optional[Dict[str, Any]] = None,
    formatting_features: Optional[Dict[str, Any]] = None,
    notation_features: Optional[Dict[str, Any]] = None,
    register_features: Optional[Dict[str, Any]] = None,
    conversation_features: Optional[Dict[str, Any]] = None,
    syntax_features: Optional[Dict[str, Any]] = None,
    temporal_features: Optional[Dict[str, Any]] = None,
    conditional_features: Optional[Dict[str, Any]] = None,
    interaction_features: Optional[Dict[str, Any]] = None,
    dialogue_acts_features: Optional[Dict[str, Any]] = None,
    model: str = "persona-v1",
    model_version: str = "1.0",
) -> tuple[str, int | None]:
    """Insert a longitudinal persona profile snapshot and append to IndexOutbox."""
    if not target_id or not isinstance(target_id, str):
        raise ValueError("target_id must be a non-empty string")
    if not as_of or not isinstance(as_of, str):
        raise ValueError("as_of must be a non-empty string")
    snapshot_id = _snapshot_id(target_id, as_of)
    now = _now()
    vocab_json = _json(vocabulary or {})
    dist_json = _json(distinctive_vocab or {})
    bigrams_json = _json(bigrams or {})
    ling_json = _json(linguistic_features or {})
    know_json = _json(knowledge_estimates or {})
    ortho_json = _json(orthographic_features) if orthographic_features else None
    err_json = _json(error_features) if error_features else None
    disc_json = _json(discourse_features) if discourse_features else None
    fmt_json = _json(formatting_features) if formatting_features else None
    not_json = _json(notation_features) if notation_features else None
    reg_json = _json(register_features) if register_features else None
    conv_json = _json(conversation_features) if conversation_features else None
    syn_json = _json(syntax_features) if syntax_features else None
    tmp_json = _json(temporal_features) if temporal_features else None
    cond_json = _json(conditional_features) if conditional_features else None
    inter_json = _json(interaction_features) if interaction_features else None
    dial_json = _json(dialogue_acts_features) if dialogue_acts_features else None
    connection.execute(
        """
        INSERT INTO persona_profile_snapshots
            (snapshot_id, target_id, as_of, positive_count, negative_count,
             review_count, vocabulary_json, distinctive_vocab_json, bigrams_json,
             linguistic_features_json, knowledge_estimates_json,
             orthographic_features_json, error_features_json,
             discourse_features_json, formatting_features_json,
             notation_features_json, register_features_json,
             conversation_features_json, syntax_features_json,
             temporal_features_json,
             conditional_features_json, interaction_features_json,
             dialogue_acts_features_json,
             model, model_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_id) DO UPDATE SET
            positive_count=excluded.positive_count,
            negative_count=excluded.negative_count,
            review_count=excluded.review_count,
            vocabulary_json=excluded.vocabulary_json,
            distinctive_vocab_json=excluded.distinctive_vocab_json,
            bigrams_json=excluded.bigrams_json,
            linguistic_features_json=excluded.linguistic_features_json,
            knowledge_estimates_json=excluded.knowledge_estimates_json,
            orthographic_features_json=excluded.orthographic_features_json,
            error_features_json=excluded.error_features_json,
            discourse_features_json=excluded.discourse_features_json,
            formatting_features_json=excluded.formatting_features_json,
            notation_features_json=excluded.notation_features_json,
            register_features_json=excluded.register_features_json,
            conversation_features_json=excluded.conversation_features_json,
            syntax_features_json=excluded.syntax_features_json,
            temporal_features_json=excluded.temporal_features_json,
            conditional_features_json=excluded.conditional_features_json,
            interaction_features_json=excluded.interaction_features_json,
            dialogue_acts_features_json=excluded.dialogue_acts_features_json,
            model=excluded.model,
            model_version=excluded.model_version
        """,
        (snapshot_id, target_id, as_of, int(positive_count), int(negative_count),
         int(review_count), vocab_json, dist_json, bigrams_json, ling_json,
         know_json,
         ortho_json, err_json, disc_json, fmt_json, not_json, reg_json,
         conv_json, syn_json, tmp_json,
         cond_json, inter_json, dial_json,
         model, model_version, now),
    )
    payload = {
        "snapshot_id": snapshot_id,
        "target_id": target_id,
        "as_of": as_of,
        "positive_count": int(positive_count),
        "negative_count": int(negative_count),
        "review_count": int(review_count),
        "vocabulary": vocabulary or {},
        "distinctive_vocab": distinctive_vocab or {},
        "bigrams": bigrams or {},
        "linguistic_features": linguistic_features or {},
        "knowledge_estimates": knowledge_estimates or {},
        "orthographic_features": orthographic_features or {},
        "error_features": error_features or {},
        "discourse_features": discourse_features or {},
        "formatting_features": formatting_features or {},
        "notation_features": notation_features or {},
        "register_features": register_features or {},
        "conversation_features": conversation_features or {},
        "syntax_features": syntax_features or {},
        "temporal_features": temporal_features or {},
        "conditional_features": conditional_features or {},
        "interaction_features": interaction_features or {},
        "dialogue_acts_features": dialogue_acts_features or {},
        "model": model,
        "model_version": model_version,
        "created_at": now,
    }
    seq = IndexOutbox.append_to(
        connection,
        source_table=PERSONA_SNAPSHOT_SOURCE_TABLE,
        source_key=snapshot_id,
        event_type="save",
        payload=payload,
    )
    return snapshot_id, seq


# ─── PersonaStore: standalone connection manager ────────────────────────────

class PersonaStore:
    """Standalone store managing its own SQLite connection.

    Provides convenience methods for registering persona targets, adding
    examples, recording knowledge observations, saving snapshots, and querying
    longitudinal data. All writes flow through IndexOutbox.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = connect_sqlite(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA_SQL)
            apply_migrations(self._conn)
            IndexOutbox.ensure_schema(self._conn)
            self._conn.commit()
        return self._conn

    # ── Target management ───────────────────────────────────────────────

    def register_target(
        self,
        target_id: str,
        display_name: str,
        *,
        platform: str = "telegram",
        platform_user_id: Optional[str] = None,
        authorization_status: str = "pending",
        consent_record: Optional[str] = None,
        notes: str = "",
    ) -> int | None:
        conn = self._connection()
        seq = record_persona_target(
            conn,
            target_id=target_id,
            display_name=display_name,
            platform=platform,
            platform_user_id=platform_user_id,
            authorization_status=authorization_status,
            consent_record=consent_record,
            notes=notes,
        )
        conn.commit()
        return seq

    def set_authorization(
        self,
        target_id: str,
        authorization_status: str,
        *,
        consent_record: Optional[str] = None,
    ) -> int | None:
        if authorization_status not in _VALID_AUTH:
            raise ValueError(f"authorization_status must be one of {_VALID_AUTH}")
        conn = self._connection()
        row = conn.execute(
            "SELECT 1 FROM persona_targets WHERE target_id = ?",
            (target_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown persona target: {target_id}")
        now = _now()
        conn.execute(
            """
            UPDATE persona_targets
            SET authorization_status = ?, consent_record = ?, updated_at = ?
            WHERE target_id = ?
            """,
            (authorization_status, consent_record, now, target_id),
        )
        payload = {
            "target_id": target_id,
            "authorization_status": authorization_status,
            "consent_record": consent_record,
            "updated_at": now,
        }
        seq = IndexOutbox.append_to(
            conn,
            source_table=PERSONA_TARGET_SOURCE_TABLE,
            source_key=target_id,
            event_type="authorize",
            payload=payload,
        )
        conn.commit()
        return seq

    def get_target(self, target_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM persona_targets WHERE target_id = ?",
            (target_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_targets(self, authorization_status: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._connection()
        if authorization_status:
            rows = conn.execute(
                "SELECT * FROM persona_targets WHERE authorization_status = ? ORDER BY created_at",
                (authorization_status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM persona_targets ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def can_export(self, target_id: str) -> bool:
        target = self.get_target(target_id)
        if target is None:
            return False
        return target["authorization_status"] == "authorized"

    def link_surveillance_target(
        self, target_id: str, surveillance_target_id: str
    ) -> None:
        """Link a persona target to a surveillance_targets entry.

        This connects the persona training pipeline to the surveillance
        target registry so the periodic analysis can pull all data for
        a target from both systems.
        """
        conn = self._connection()
        row = conn.execute(
            "SELECT 1 FROM persona_targets WHERE target_id = ?",
            (target_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown persona target: {target_id}")
        now = _now()
        conn.execute(
            "UPDATE persona_targets SET surveillance_target_id = ?, updated_at = ? WHERE target_id = ?",
            (surveillance_target_id, now, target_id),
        )
        conn.commit()

    def get_linked_surveillance_targets(self) -> List[Dict[str, Any]]:
        """Return all persona targets that have a surveillance_target_id link."""
        conn = self._connection()
        rows = conn.execute(
            "SELECT * FROM persona_targets WHERE surveillance_target_id IS NOT NULL ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Examples ────────────────────────────────────────────────────────

    def add_example(
        self,
        target_id: str,
        label: str,
        text: str,
        *,
        source_type: str = "message",
        source_message_id: Optional[int] = None,
        source_channel_id: Optional[int] = None,
        source_user_id: Optional[int] = None,
        observed_at: Optional[str] = None,
        weight: float = 1.0,
        notes: str = "",
        source_revision: Optional[str] = None,
    ) -> tuple[str | None, int | None]:
        conn = self._connection()
        result = record_persona_example(
            conn,
            target_id=target_id,
            label=label,
            text=text,
            source_type=source_type,
            source_message_id=source_message_id,
            source_channel_id=source_channel_id,
            source_user_id=source_user_id,
            observed_at=observed_at,
            weight=weight,
            notes=notes,
            source_revision=source_revision,
        )
        conn.commit()
        return result

    def add_examples(
        self,
        target_id: str,
        examples: Sequence[Dict[str, Any]],
    ) -> int:
        """Bulk-add examples. Each dict must have at least 'label' and 'text'."""
        conn = self._connection()
        count = 0
        for ex in examples:
            label = ex.get("label")
            text = ex.get("text")
            if not label or not text:
                continue
            eid, _ = record_persona_example(
                conn,
                target_id=target_id,
                label=label,
                text=text,
                source_type=ex.get("source_type", "message"),
                source_message_id=ex.get("source_message_id"),
                source_channel_id=ex.get("source_channel_id"),
                source_user_id=ex.get("source_user_id"),
                observed_at=ex.get("observed_at"),
                weight=ex.get("weight", 1.0),
                notes=ex.get("notes", ""),
                source_revision=ex.get("source_revision"),
            )
            if eid is not None:
                count += 1
        conn.commit()
        return count

    def query_examples(
        self,
        target_id: str,
        *,
        label: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        conn = self._connection()
        clauses: List[str] = ["target_id = ?"]
        params: List[Any] = [target_id]
        if label:
            if label not in _VALID_LABELS:
                raise ValueError(f"label must be one of {_VALID_LABELS}")
            clauses.append("label = ?")
            params.append(label)
        if start:
            clauses.append("(observed_at IS NULL OR observed_at >= ?)")
            params.append(start)
        if end:
            clauses.append("(observed_at IS NULL OR observed_at <= ?)")
            params.append(end)
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM persona_examples WHERE {' AND '.join(clauses)} "
            f"ORDER BY observed_at ASC, collected_at ASC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Knowledge observations ──────────────────────────────────────────

    def save_knowledge_observation(
        self,
        target_id: str,
        domain: str,
        score: float,
        confidence: float,
        *,
        evidence_source: Optional[str] = None,
        evaluator: str = "manual",
        evaluator_version: str = "1.0",
        observed_at: Optional[str] = None,
        notes: str = "",
    ) -> tuple[str | None, int | None]:
        conn = self._connection()
        result = record_knowledge_observation(
            conn,
            target_id=target_id,
            domain=domain,
            score=score,
            confidence=confidence,
            evidence_source=evidence_source,
            evaluator=evaluator,
            evaluator_version=evaluator_version,
            observed_at=observed_at,
            notes=notes,
        )
        conn.commit()
        return result

    def query_knowledge_observations(
        self,
        target_id: str,
        *,
        domain: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        conn = self._connection()
        clauses: List[str] = ["target_id = ?"]
        params: List[Any] = [target_id]
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM persona_knowledge_observations "
            f"WHERE {' AND '.join(clauses)} ORDER BY recorded_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Snapshots ───────────────────────────────────────────────────────

    def save_snapshot(
        self,
        target_id: str,
        as_of: str,
        *,
        positive_count: int = 0,
        negative_count: int = 0,
        review_count: int = 0,
        vocabulary: Optional[Dict[str, Any]] = None,
        distinctive_vocab: Optional[Dict[str, Any]] = None,
        bigrams: Optional[Dict[str, Any]] = None,
        linguistic_features: Optional[Dict[str, Any]] = None,
        knowledge_estimates: Optional[Dict[str, Any]] = None,
        orthographic_features: Optional[Dict[str, Any]] = None,
        error_features: Optional[Dict[str, Any]] = None,
        discourse_features: Optional[Dict[str, Any]] = None,
        formatting_features: Optional[Dict[str, Any]] = None,
        notation_features: Optional[Dict[str, Any]] = None,
        register_features: Optional[Dict[str, Any]] = None,
        conversation_features: Optional[Dict[str, Any]] = None,
        syntax_features: Optional[Dict[str, Any]] = None,
        temporal_features: Optional[Dict[str, Any]] = None,
        conditional_features: Optional[Dict[str, Any]] = None,
        interaction_features: Optional[Dict[str, Any]] = None,
        dialogue_acts_features: Optional[Dict[str, Any]] = None,
        model: str = "persona-v1",
        model_version: str = "1.0",
    ) -> tuple[str, int | None]:
        conn = self._connection()
        result = record_snapshot(
            conn,
            target_id=target_id,
            as_of=as_of,
            positive_count=positive_count,
            negative_count=negative_count,
            review_count=review_count,
            vocabulary=vocabulary,
            distinctive_vocab=distinctive_vocab,
            bigrams=bigrams,
            linguistic_features=linguistic_features,
            knowledge_estimates=knowledge_estimates,
            orthographic_features=orthographic_features,
            error_features=error_features,
            discourse_features=discourse_features,
            formatting_features=formatting_features,
            notation_features=notation_features,
            register_features=register_features,
            conversation_features=conversation_features,
            syntax_features=syntax_features,
            temporal_features=temporal_features,
            conditional_features=conditional_features,
            interaction_features=interaction_features,
            dialogue_acts_features=dialogue_acts_features,
            model=model,
            model_version=model_version,
        )
        conn.commit()
        return result

    def latest_snapshot(self, target_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM persona_profile_snapshots WHERE target_id = ? "
            "ORDER BY as_of DESC, created_at DESC LIMIT 1",
            (target_id,),
        ).fetchone()
        if row is None:
            return None
        return _decode_snapshot_row(dict(row))

    def query_snapshots(
        self,
        target_id: str,
        *,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        conn = self._connection()
        rows = conn.execute(
            "SELECT * FROM persona_profile_snapshots WHERE target_id = ? "
            "ORDER BY as_of ASC LIMIT ?",
            (target_id, limit),
        ).fetchall()
        return [_decode_snapshot_row(dict(row)) for row in rows]

    # ── Stats & export manifest ─────────────────────────────────────────

    def corpus_stats(self, target_id: str) -> Dict[str, Any]:
        conn = self._connection()
        target = self.get_target(target_id)
        if target is None:
            raise KeyError(f"Unknown persona target: {target_id}")
        ex_rows = conn.execute(
            "SELECT label, COUNT(*) AS cnt, MIN(observed_at) AS min_obs, "
            "MAX(observed_at) AS max_obs FROM persona_examples WHERE target_id = ? "
            "GROUP BY label",
            (target_id,),
        ).fetchall()
        per_label: Dict[str, Any] = {}
        total = 0
        date_min: Optional[str] = None
        date_max: Optional[str] = None
        for row in ex_rows:
            cnt = int(row["cnt"])
            per_label[row["label"]] = cnt
            total += cnt
            if row["min_obs"]:
                date_min = row["min_obs"] if date_min is None else min(date_min, row["min_obs"])
            if row["max_obs"]:
                date_max = row["max_obs"] if date_max is None else max(date_max, row["max_obs"])
        know_rows = conn.execute(
            "SELECT domain, COUNT(*) AS cnt, AVG(score) AS avg_score, "
            "AVG(confidence) AS avg_conf FROM persona_knowledge_observations "
            "WHERE target_id = ? GROUP BY domain",
            (target_id,),
        ).fetchall()
        per_domain: Dict[str, Any] = {}
        for row in know_rows:
            per_domain[row["domain"]] = {
                "count": int(row["cnt"]),
                "avg_score": round(float(row["avg_score"] or 0.0), 4),
                "avg_confidence": round(float(row["avg_conf"] or 0.0), 4),
            }
        snap_count = conn.execute(
            "SELECT COUNT(*) FROM persona_profile_snapshots WHERE target_id = ?",
            (target_id,),
        ).fetchone()[0]
        return {
            "target_id": target_id,
            "display_name": target["display_name"],
            "authorization_status": target["authorization_status"],
            "total_examples": total,
            "per_label": per_label,
            "date_range": {"start": date_min, "end": date_max},
            "per_domain": per_domain,
            "snapshot_count": int(snap_count),
        }

    def export_manifest(self, target_id: str) -> Dict[str, Any]:
        """Return a manifest describing the exportable corpus (no file output)."""
        stats = self.corpus_stats(target_id)
        return {
            "target_id": target_id,
            "display_name": stats["display_name"],
            "authorization_status": stats["authorization_status"],
            "can_export": stats["authorization_status"] == "authorized",
            "disclosure_required": True,
            "total_examples": stats["total_examples"],
            "per_label": stats["per_label"],
            "per_domain": stats["per_domain"],
            "date_range": stats["date_range"],
            "snapshot_count": stats["snapshot_count"],
        }

    # ── Drift metrics ──────────────────────────────────────────────────

    def save_drift_metric(
        self,
        target_id: str,
        earlier_snapshot_id: str,
        later_snapshot_id: str,
        feature_layer: str,
        similarity_score: float,
        *,
        confidence: float = 0.0,
        js_divergence: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist a drift metric between two snapshots for one feature layer."""
        import uuid
        conn = self._connection()
        metric_id = str(uuid.uuid4())
        conn.execute(
            "INSERT OR REPLACE INTO persona_drift_metrics "
            "(metric_id, target_id, earlier_snapshot_id, later_snapshot_id, "
            " feature_layer, similarity_score, confidence, js_divergence, "
            " metric_details_json, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                metric_id, target_id, earlier_snapshot_id, later_snapshot_id,
                feature_layer, similarity_score, confidence, js_divergence,
                json.dumps(details) if details else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return metric_id

    def query_drift_metrics(
        self,
        target_id: str,
        *,
        feature_layer: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query drift metrics for a target, optionally filtered by layer."""
        conn = self._connection()
        if feature_layer:
            rows = conn.execute(
                "SELECT * FROM persona_drift_metrics "
                "WHERE target_id = ? AND feature_layer = ? "
                "ORDER BY computed_at DESC LIMIT ?",
                (target_id, feature_layer, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM persona_drift_metrics "
                "WHERE target_id = ? ORDER BY computed_at DESC LIMIT ?",
                (target_id, limit),
            ).fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            if d.get("metric_details_json"):
                try:
                    d["metric_details"] = json.loads(d.pop("metric_details_json"))
                except json.JSONDecodeError:
                    d["metric_details"] = {}
            else:
                d.pop("metric_details_json", None)
                d["metric_details"] = {}
            results.append(d)
        return results

    def latest_drift_summary(self, target_id: str) -> Dict[str, Any]:
        """Get the most recent drift metric per feature layer for a target."""
        metrics = self.query_drift_metrics(target_id, limit=200)
        by_layer: Dict[str, Dict[str, Any]] = {}
        for m in metrics:
            layer = m["feature_layer"]
            if layer not in by_layer:
                by_layer[layer] = m
        return by_layer

    # ── Calibration metrics ────────────────────────────────────────────

    def save_calibration(
        self,
        target_id: str,
        model_name: str,
        model_version: str,
        brier: float,
        ece: float,
        n_samples: int,
        *,
        n_bins: int = 10,
        reliability: Optional[List] = None,
        threshold: float = 0.5,
        calibrated_threshold: Optional[float] = None,
    ) -> str:
        """Persist a classifier calibration evaluation result."""
        import uuid
        conn = self._connection()
        cal_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO persona_calibration "
            "(calibration_id, target_id, model_name, model_version, "
            " brier_score, ece, n_samples, n_bins, reliability_json, "
            " threshold, calibrated_threshold, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cal_id, target_id, model_name, model_version,
                brier, ece, n_samples, n_bins,
                json.dumps(reliability) if reliability else None,
                threshold, calibrated_threshold,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return cal_id

    def latest_calibration(self, target_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent calibration record for a target."""
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM persona_calibration WHERE target_id = ? "
            "ORDER BY computed_at DESC LIMIT 1",
            (target_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d.get("reliability_json"):
            try:
                d["reliability"] = json.loads(d.pop("reliability_json"))
            except json.JSONDecodeError:
                d["reliability"] = []
        else:
            d.pop("reliability_json", None)
            d["reliability"] = []
        return d

    # ── Feature config (SQL mirror of QIHSE KV configs) ────────────────

    def save_feature_config(
        self,
        target_id: str,
        config: Dict[str, Any],
        *,
        updated_by: str = "system",
    ) -> None:
        """Persist feature config overrides to the SQL mirror table."""
        conn = self._connection()
        conn.execute(
            "INSERT OR REPLACE INTO persona_feature_configs "
            "(target_id, config_json, updated_by, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (
                target_id,
                json.dumps(config, sort_keys=True),
                updated_by,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    def load_feature_config(self, target_id: str) -> Optional[Dict[str, Any]]:
        """Load feature config overrides from the SQL mirror table."""
        conn = self._connection()
        row = conn.execute(
            "SELECT config_json FROM persona_feature_configs WHERE target_id = ?",
            (target_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["config_json"])
        except json.JSONDecodeError:
            return None

    # ── Deletion ────────────────────────────────────────────────────────

    def delete_target(self, target_id: str) -> int:
        """Delete a persona target and cascade-delete its examples/observations/snapshots."""
        conn = self._connection()
        cursor = conn.execute(
            "DELETE FROM persona_targets WHERE target_id = ?",
            (target_id,),
        )
        conn.commit()
        return int(cursor.rowcount)

    # ── Outbox inspection ───────────────────────────────────────────────

    def outbox_events(
        self,
        target_id: Optional[str] = None,
        source_table: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        conn = self._connection()
        clauses: List[str] = []
        params: List[Any] = []
        tables = (source_table,) if source_table else PERSONA_SOURCE_TABLES
        placeholders = ",".join("?" for _ in tables)
        clauses.append(f"source_table IN ({placeholders})")
        params.extend(tables)
        if target_id:
            clauses.append("source_key = ?")
            params.append(target_id)
        params.append(limit)
        rows = conn.execute(
            f"SELECT sequence_id, source_table, source_key, event_type, "
            f"payload_json, created_at, processed_at FROM index_outbox "
            f"WHERE {' AND '.join(clauses)} ORDER BY sequence_id DESC LIMIT ?",
            params,
        ).fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            try:
                d["payload"] = json.loads(d.pop("payload_json"))
            except json.JSONDecodeError:
                d["payload"] = {}
            results.append(d)
        return results

    # ── Context manager ─────────────────────────────────────────────────

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "PersonaStore":
        self._connection()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


__all__ = [
    "PERSONA_TARGET_SOURCE_TABLE",
    "PERSONA_EXAMPLES_SOURCE_TABLE",
    "PERSONA_KNOWLEDGE_SOURCE_TABLE",
    "PERSONA_SNAPSHOT_SOURCE_TABLE",
    "PERSONA_SOURCE_TABLES",
    "PersonaStore",
    "record_persona_target",
    "record_persona_example",
    "record_knowledge_observation",
    "record_snapshot",
]
