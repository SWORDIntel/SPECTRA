import pytest

from tgarchive.db.index_outbox import IndexOutbox
from tgarchive.services.index_benchmark import benchmark_indexing


def test_temporary_benchmark_database_is_cleaned_after_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("tgarchive.services.index_benchmark.tempfile.tempdir", str(tmp_path))

    def fail_append(self, **kwargs):
        raise RuntimeError("synthetic write failure")

    monkeypatch.setattr(IndexOutbox, "append", fail_append)

    with pytest.raises(RuntimeError, match="synthetic write failure"):
        benchmark_indexing(events=10, writers=1, lookups=1, batch_size=10)

    assert list(tmp_path.iterdir()) == []
