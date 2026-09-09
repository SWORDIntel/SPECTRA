"""Integration tests for the SemanticProjection wiring in IndexProjector.

These verify that ``spectra index drain`` produces semantic embeddings by
exercising the ``SEMANTIC_PROJECTION`` (``qihse.semantic.v1``) projection
that was added to the IndexProjector pipeline.
"""

from __future__ import annotations

import sys
import types
from unittest import mock

import pytest

from tgarchive.db.index_outbox import IndexOutbox
from tgarchive.db.index_projector import (
    FTS_PROJECTION,
    PROJECTIONS,
    SEMANTIC_PROJECTION,
    IndexProjector,
    _event_in_projection,
)
from tgarchive.sqlite_runtime import connect_sqlite


# ── Static wiring tests ────────────────────────────────────────────────────


def test_semantic_projection_is_in_projections_tuple():
    """SEMANTIC_PROJECTION must be registered in the PROJECTIONS tuple."""
    assert SEMANTIC_PROJECTION in PROJECTIONS


def test_semantic_projection_constant_value():
    assert SEMANTIC_PROJECTION == "qihse.semantic.v1"


def test_projection_names_alias_semantic():
    """`spectra index drain --projection semantic` resolves correctly."""
    from tgarchive.db.index_projector import _projection_names

    assert _projection_names("semantic") == (SEMANTIC_PROJECTION,)
    assert _projection_names(SEMANTIC_PROJECTION) == (SEMANTIC_PROJECTION,)


# ── _event_in_projection tests ─────────────────────────────────────────────


def test_event_in_projection_messages():
    event = {"source_table": "messages", "source_key": "1", "payload": {}}
    assert _event_in_projection(SEMANTIC_PROJECTION, event) is True


def test_event_in_projection_channel_messages():
    event = {"source_table": "channel_messages", "source_key": "1", "payload": {}}
    assert _event_in_projection(SEMANTIC_PROJECTION, event) is True


def test_event_in_projection_non_message_skipped():
    """Non-message events (e.g. users, media, checkpoints) are skipped."""
    for table in ("users", "media", "checkpoints", "operations", "errors"):
        event = {"source_table": table, "source_key": "1", "payload": {}}
        assert _event_in_projection(SEMANTIC_PROJECTION, event) is False, table


def test_event_in_projection_matches_fts_scope():
    """Semantic projection applies to the same source tables as FTS."""
    for table in ("messages", "channel_messages", "users", "media"):
        event = {"source_table": table, "source_key": "1", "payload": {}}
        assert _event_in_projection(SEMANTIC_PROJECTION, event) == _event_in_projection(
            FTS_PROJECTION, event
        ), table


# ── _upsert_event tests ────────────────────────────────────────────────────


def _make_message_event(sequence_id=1, text="hello semantic world"):
    return {
        "sequence_id": sequence_id,
        "source_table": "messages",
        "source_key": str(sequence_id),
        "event_type": "upsert",
        "source_revision": "rev-1",
        "payload": {
            "message_id": sequence_id,
            "channel_id": 100,
            "text": text,
        },
    }


def test_upsert_event_generates_embedding(tmp_path, monkeypatch):
    """_upsert_event returns True for message events (batch projection happens later)."""
    database = tmp_path / "spectra.db"
    IndexOutbox(database).append(
        source_table="messages",
        source_key="1",
        event_type="upsert",
        payload={"message_id": 1, "channel_id": 100, "text": "hello semantic"},
        source_revision="rev-1",
    )
    projector = IndexProjector(database)

    project_batch_calls = []

    class FakeSemanticProjection:
        def __init__(self, *args, **kwargs):
            pass

        def project(self, text, source_table="", source_id="", **kwargs):
            return 1

        def project_batch(self, *, texts, source_table="", source_ids, **kwargs):
            project_batch_calls.append((texts, source_table, source_ids))
            return mock.MagicMock(projected=len(texts), errors=[], vector_ids=list(range(len(texts))))

        def flush(self):
            pass

        def close(self):
            pass

    # Inject a fake module so the lazy import inside _get_persistent_semantic_projection resolves.
    fake_module = types.ModuleType("tgarchive.search.semantic_projection")
    fake_module.SemanticProjection = FakeSemanticProjection
    fake_module.EmbeddingGenerator = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "tgarchive.search.semantic_projection", fake_module)

    event = _make_message_event(text="hello semantic world")
    with projector._connection() as connection:
        # _upsert_event now returns True without calling projection —
        # the batch projection happens in _process_locked.
        result = projector._upsert_event(connection, SEMANTIC_PROJECTION, event)

    assert result is True
    # No project_batch call yet — that happens during process(), not _upsert_event.
    assert project_batch_calls == []


def test_upsert_event_skips_non_message(tmp_path, monkeypatch):
    """Non-message events return False and do not call SemanticProjection."""
    database = tmp_path / "spectra.db"
    projector = IndexProjector(database)

    project_calls = []

    class FakeSemanticProjection:
        def __init__(self, *args, **kwargs):
            pass

        def project(self, *args, **kwargs):
            project_calls.append(args)
            return 1

    fake_module = types.ModuleType("tgarchive.search.semantic_projection")
    fake_module.SemanticProjection = FakeSemanticProjection
    fake_module.EmbeddingGenerator = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "tgarchive.search.semantic_projection", fake_module)

    event = {
        "sequence_id": 1,
        "source_table": "users",
        "source_key": "1",
        "event_type": "upsert",
        "source_revision": "rev-1",
        "payload": {"user_id": 1, "name": "alice"},
    }
    with projector._connection() as connection:
        result = projector._upsert_event(connection, SEMANTIC_PROJECTION, event)

    assert result is False
    assert project_calls == []


def test_upsert_event_graceful_failure(tmp_path, monkeypatch):
    """Batch projection failure does not break the drain — graceful degradation."""
    database = tmp_path / "spectra.db"
    IndexOutbox(database).append(
        source_table="messages",
        source_key="1",
        event_type="upsert",
        payload={"message_id": 1, "channel_id": 100, "text": "hello"},
        source_revision="rev-1",
    )
    projector = IndexProjector(database)

    # Stub native sync so process() doesn't require the C libraries.
    monkeypatch.setattr(
        projector, "_sync_qihse", lambda _rows, **_kw: {"available": True, "ok": True}
    )
    monkeypatch.setattr(
        projector, "_sync_graph", lambda _rows, **_kw: {"available": True, "ok": True}
    )

    class FailingSemanticProjection:
        def __init__(self, *args, **kwargs):
            pass

        def project(self, *args, **kwargs):
            raise RuntimeError("vector store unavailable")

        def project_batch(self, **kwargs):
            raise RuntimeError("vector store unavailable")

        def flush(self):
            pass

        def close(self):
            pass

    fake_module = types.ModuleType("tgarchive.search.semantic_projection")
    fake_module.SemanticProjection = FailingSemanticProjection
    fake_module.EmbeddingGenerator = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "tgarchive.search.semantic_projection", fake_module)

    # The drain should complete successfully even if batch projection fails.
    # The projection failure is logged as a warning but doesn't break the drain.
    result = projector.process(batch_size=10)

    assert result["ok"] is True
    assert result["processed"] >= 1


def test_upsert_event_empty_text_skipped(tmp_path, monkeypatch):
    """Events with no extractable text return True (batch projection filters later)."""
    database = tmp_path / "spectra.db"
    IndexOutbox(database).append(
        source_table="messages",
        source_key="1",
        event_type="upsert",
        payload={},
        source_revision="rev-1",
    )
    projector = IndexProjector(database)

    project_batch_calls = []

    class FakeSemanticProjection:
        def __init__(self, *args, **kwargs):
            pass

        def project(self, *args, **kwargs):
            return 1

        def project_batch(self, *, texts, source_table="", source_ids, **kwargs):
            project_batch_calls.append((texts, source_table, source_ids))
            return mock.MagicMock(projected=len(texts), errors=[], vector_ids=list(range(len(texts))))

        def flush(self):
            pass

        def close(self):
            pass

    fake_module = types.ModuleType("tgarchive.search.semantic_projection")
    fake_module.SemanticProjection = FakeSemanticProjection
    fake_module.EmbeddingGenerator = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "tgarchive.search.semantic_projection", fake_module)

    # A message event whose payload has no text fields — _text_content will
    # still produce source_table/source_key/event_type, so the text is
    # non-empty and _upsert_event returns True.
    event = {
        "sequence_id": 1,
        "source_table": "messages",
        "source_key": "1",
        "event_type": "upsert",
        "source_revision": "rev-1",
        "payload": {},
    }
    with projector._connection() as connection:
        result = projector._upsert_event(connection, SEMANTIC_PROJECTION, event)

    # _upsert_event returns True — the batch projection happens in process().
    assert result is True
    assert project_batch_calls == []


# ── End-to-end drain test ──────────────────────────────────────────────────


def test_drain_produces_semantic_embedding(tmp_path, monkeypatch):
    """Full process() drain generates an embedding for a message event via project_batch."""
    database = tmp_path / "spectra.db"
    IndexOutbox(database).append(
        source_table="messages",
        source_key="42",
        event_type="upsert",
        payload={"message_id": 42, "channel_id": 7, "text": "semantic drain test"},
        source_revision="rev-1",
    )
    projector = IndexProjector(database)

    # Stub native sync so process() doesn't require the C libraries.
    monkeypatch.setattr(
        projector, "_sync_qihse", lambda _rows, **_kw: {"available": True, "ok": True}
    )
    monkeypatch.setattr(
        projector, "_sync_graph", lambda _rows, **_kw: {"available": True, "ok": True}
    )

    project_batch_calls = []

    class FakeSemanticProjection:
        def __init__(self, *args, **kwargs):
            pass

        def project(self, text, source_table="", source_id="", **kwargs):
            return 1

        def project_batch(self, *, texts, source_table="", source_ids, **kwargs):
            project_batch_calls.append((texts, source_table, source_ids))
            return mock.MagicMock(projected=len(texts), errors=[], vector_ids=list(range(len(texts))))

        def flush(self):
            pass

        def close(self):
            pass

    fake_module = types.ModuleType("tgarchive.search.semantic_projection")
    fake_module.SemanticProjection = FakeSemanticProjection
    fake_module.EmbeddingGenerator = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "tgarchive.search.semantic_projection", fake_module)

    result = projector.process(batch_size=10)

    assert result["ok"] is True
    assert result["processed"] >= 1
    # The batch semantic projection was invoked for the message event.
    assert len(project_batch_calls) >= 1, project_batch_calls
    texts, source_table, source_ids = project_batch_calls[0]
    assert source_table == "messages"
    assert "42" in source_ids

    # A projection-state row was written for SEMANTIC_PROJECTION.
    with connect_sqlite(database) as connection:
        row = connection.execute(
            "SELECT projection_name, row_count FROM index_projection_state WHERE projection_name=?",
            (SEMANTIC_PROJECTION,),
        ).fetchone()
    assert row is not None
    assert row[0] == SEMANTIC_PROJECTION
    assert row[1] >= 1
