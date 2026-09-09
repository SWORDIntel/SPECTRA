"""
Tests for the evaluation harness — metrics, splits, calibration, benchmarks.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from tgarchive.evaluation.metrics import (
    precision, recall, f1_score, roc_auc, pr_auc,
    confusion_matrix, mrr, recall_at_k, ndcg_at_k,
    top_k_accuracy, false_link_rate, false_split_rate,
)
from tgarchive.evaluation.splits import temporal_split, temporal_split_by_ratio
from tgarchive.evaluation.calibration import (
    brier_score, expected_calibration_error, reliability_data, calibration_map,
)
from tgarchive.evaluation.benchmarks import (
    BenchmarkResult, run_attribution_benchmark, run_search_benchmark, compare_versions,
)
from tgarchive.evaluation.datasets import Dataset, SAME_ACTOR, DIFFERENT_ACTOR


# ─── Classification Metrics ─────────────────────────────────────────────────

class TestClassificationMetrics:
    def test_precision_binary(self):
        y_true = [1, 0, 1, 1, 0]
        y_pred = [1, 0, 1, 0, 0]
        # predicted positives: positions 0,2 → both correct → precision=1.0
        p = precision(y_true, y_pred)
        assert 0 <= p <= 1
        assert p == pytest.approx(1.0, abs=0.01)

    def test_recall_binary(self):
        y_true = [1, 0, 1, 1, 0]
        y_pred = [1, 0, 1, 0, 0]
        r = recall(y_true, y_pred)
        assert 0 <= r <= 1
        assert r == pytest.approx(2/3, abs=0.01)

    def test_f1_binary(self):
        y_true = [1, 0, 1, 1, 0]
        y_pred = [1, 0, 1, 0, 0]
        # precision=1.0, recall=2/3 → f1=0.8
        f = f1_score(y_true, y_pred)
        assert 0 <= f <= 1
        assert f == pytest.approx(0.8, abs=0.01)

    def test_perfect_classification(self):
        y_true = [1, 0, 1, 0]
        y_pred = [1, 0, 1, 0]
        assert precision(y_true, y_pred) == 1.0
        assert recall(y_true, y_pred) == 1.0
        assert f1_score(y_true, y_pred) == 1.0

    def test_roc_auc(self):
        y_true = [1, 0, 1, 1, 0, 1, 0, 0]
        y_prob = [0.9, 0.1, 0.8, 0.7, 0.2, 0.6, 0.3, 0.1]
        auc = roc_auc(y_true, y_prob)
        assert 0 <= auc <= 1
        assert auc > 0.8  # Good separation

    def test_pr_auc(self):
        y_true = [1, 0, 1, 1, 0, 1, 0, 0]
        y_prob = [0.9, 0.1, 0.8, 0.7, 0.2, 0.6, 0.3, 0.1]
        auc = pr_auc(y_true, y_prob)
        assert 0 <= auc <= 1

    def test_confusion_matrix(self):
        y_true = [1, 0, 1, 0]
        y_pred = [1, 0, 0, 0]
        cm = confusion_matrix(y_true, y_pred)
        assert cm is not None

    def test_empty_input(self):
        assert precision([], []) == 0.0
        assert recall([], []) == 0.0
        assert f1_score([], []) == 0.0


# ─── Ranking Metrics ────────────────────────────────────────────────────────

class TestRankingMetrics:
    def test_mrr(self):
        relevant = ["doc1", "doc3"]
        ranked = ["doc2", "doc1", "doc5", "doc3"]
        # First relevant at position 2 → 1/2 = 0.5
        assert mrr(relevant, ranked) == pytest.approx(0.5, abs=0.01)

    def test_mrr_first_position(self):
        relevant = ["doc1"]
        ranked = ["doc1", "doc2", "doc3"]
        assert mrr(relevant, ranked) == pytest.approx(1.0, abs=0.01)

    def test_mrr_no_relevant(self):
        relevant = ["doc99"]
        ranked = ["doc1", "doc2", "doc3"]
        assert mrr(relevant, ranked) == 0.0

    def test_recall_at_k(self):
        relevant = ["doc1", "doc3"]
        ranked = ["doc1", "doc2", "doc3"]
        assert recall_at_k(relevant, ranked, k=3) == pytest.approx(1.0, abs=0.01)
        assert recall_at_k(relevant, ranked, k=1) == pytest.approx(0.5, abs=0.01)

    def test_ndcg_at_k(self):
        scores = {"doc1": 3.0, "doc2": 2.0, "doc3": 1.0}
        ranked = ["doc1", "doc2", "doc3"]
        ndcg = ndcg_at_k(scores, ranked, k=3)
        assert 0 <= ndcg <= 1
        # Perfect ranking → NDCG = 1
        assert ndcg == pytest.approx(1.0, abs=0.01)


# ─── Attribution Metrics ────────────────────────────────────────────────────

class TestAttributionMetrics:
    def test_top_1_accuracy(self):
        # true_actors and predicted_actors are parallel sequences
        true_actors = ["actor1", "actor2"]
        predicted = [["actor1", "actor3"], ["actor3", "actor2"]]
        acc = top_k_accuracy(true_actors, predicted, k=1)
        # Only first has correct top-1
        assert acc == pytest.approx(0.5, abs=0.01)

    def test_top_5_accuracy(self):
        true_actors = ["actor1", "actor2"]
        predicted = [["actor1", "actor3"], ["actor3", "actor2"]]
        acc = top_k_accuracy(true_actors, predicted, k=5)
        # Both correct in top-5
        assert acc == pytest.approx(1.0, abs=0.01)

    def test_false_link_rate(self):
        true_pairs = {("a", "b"), ("c", "d")}
        predicted_pairs = {("a", "b"), ("e", "f")}
        # 1 false link out of 2 predicted
        flr = false_link_rate(true_pairs, predicted_pairs)
        assert 0 <= flr <= 1

    def test_false_split_rate(self):
        true_pairs = {("a", "b"), ("c", "d")}
        predicted_pairs = {("a", "b")}
        # 1 true pair missed out of 2
        fsr = false_split_rate(true_pairs, predicted_pairs)
        assert 0 <= fsr <= 1


# ─── Calibration ────────────────────────────────────────────────────────────

class TestCalibration:
    def test_brier_score_perfect(self):
        y_true = [1, 0, 1, 0]
        y_prob = [1.0, 0.0, 1.0, 0.0]
        bs = brier_score(y_true, y_prob)
        assert bs == pytest.approx(0.0, abs=0.001)

    def test_brier_score_worst(self):
        y_true = [1, 0, 1, 0]
        y_prob = [0.0, 1.0, 0.0, 1.0]
        bs = brier_score(y_true, y_prob)
        assert bs == pytest.approx(1.0, abs=0.001)

    def test_ece(self):
        y_true = [1, 0, 1, 1, 0, 1, 0, 0]
        y_prob = [0.9, 0.1, 0.8, 0.7, 0.2, 0.6, 0.3, 0.1]
        ece = expected_calibration_error(y_true, y_prob)
        assert 0 <= ece <= 1

    def test_reliability_data(self):
        y_true = [1, 0, 1, 1, 0, 1, 0, 0]
        y_prob = [0.9, 0.1, 0.8, 0.7, 0.2, 0.6, 0.3, 0.1]
        data = reliability_data(y_true, y_prob, n_bins=5)
        assert len(data) > 0
        for entry in data:
            assert len(entry) == 5  # (bin_lower, bin_upper, mean_conf, mean_acc, count)

    def test_calibration_map(self):
        y_true = [1, 0, 1, 1, 0, 1, 0, 0]
        y_prob = [0.9, 0.1, 0.8, 0.7, 0.2, 0.6, 0.3, 0.1]
        cal_fn = calibration_map(y_true, y_prob)
        calibrated = cal_fn(0.5)
        assert 0 <= calibrated <= 1


# ─── Temporal Splits ────────────────────────────────────────────────────────

class TestTemporalSplits:
    def test_temporal_split(self):
        msgs = [
            {"id": 1, "date": datetime(2024, 1, 15)},
            {"id": 2, "date": datetime(2024, 6, 1)},
            {"id": 3, "date": datetime(2025, 1, 1)},
            {"id": 4, "date": datetime(2025, 7, 1)},
        ]
        train, val, test = temporal_split(msgs, datetime(2024, 12, 1), datetime(2025, 6, 1))
        assert len(train) == 2
        assert len(val) == 1
        assert len(test) == 1

    def test_temporal_split_by_ratio(self):
        msgs = [
            {"id": i, "date": datetime(2024, 1, 1 + i)}
            for i in range(1, 11)
        ]
        train, val, test = temporal_split_by_ratio(msgs, 0.6, 0.2)
        assert len(train) == 6
        assert len(val) == 2
        assert len(test) == 2

    def test_temporal_split_iso_strings(self):
        msgs = [
            {"id": 1, "date": "2024-01-15T00:00:00"},
            {"id": 2, "date": "2024-06-01T00:00:00"},
            {"id": 3, "date": "2025-01-01T00:00:00"},
        ]
        train, val, test = temporal_split(msgs, datetime(2024, 12, 1), datetime(2025, 6, 1))
        assert len(train) == 2
        assert len(val) == 1
        assert len(test) == 0


# ─── Benchmarks ─────────────────────────────────────────────────────────────

class TestBenchmarks:
    def test_run_attribution_benchmark(self):
        class MockEngine:
            def compare(self, msgs_a, msgs_b):
                return 0.9 if len(msgs_a) > 0 and len(msgs_b) > 0 else 0.1

        dataset = Dataset(
            name="test",
            description="test dataset",
            pairs=[
                {"subject_a": "u1", "subject_b": "u2", "label": 1, "messages_a": [{"text": "hi"}], "messages_b": [{"text": "hello"}]},
                {"subject_a": "u3", "subject_b": "u4", "label": 0, "messages_a": [{"text": "hi"}], "messages_b": [{"text": "hello"}]},
            ],
        )
        result = run_attribution_benchmark(MockEngine(), dataset, model_name="mock", model_version="1.0")
        assert result.benchmark_name == "attribution"
        assert "precision" in result.metrics
        assert len(result.predictions) == 2

    def test_run_search_benchmark(self):
        def search_fn(query):
            if "malware" in query:
                return [("doc1", 0.9), ("doc2", 0.7), ("doc3", 0.5)]
            return [("doc4", 0.8)]

        queries = [
            {"query": "malware seller", "relevant_doc_ids": ["doc1", "doc3"]},
            {"query": "benign topic", "relevant_doc_ids": ["doc4"]},
        ]
        result = run_search_benchmark(search_fn, queries, model_name="mock", model_version="1.0")
        assert result.benchmark_name == "search"
        assert "mrr" in result.metrics
        assert len(result.predictions) == 2

    def test_compare_versions(self):
        r1 = BenchmarkResult("attr", "ds", "model", "v1", metrics={"precision": 0.7, "recall": 0.8})
        r2 = BenchmarkResult("attr", "ds", "model", "v2", metrics={"precision": 0.85, "recall": 0.75})
        comp = compare_versions(r1, r2)
        assert comp["metrics"]["precision"]["delta"] == pytest.approx(0.15, abs=0.01)
        assert comp["metrics"]["precision"]["improved"] is True
        assert comp["metrics"]["recall"]["improved"] is False
        assert comp["summary"]["improvements"] == 1
        assert comp["summary"]["regressions"] == 1


# ─── Dataset ────────────────────────────────────────────────────────────────

class TestDataset:
    def test_empty_dataset(self):
        ds = Dataset(name="empty", description="no data", pairs=[])
        assert ds.name == "empty"
        assert len(ds.pairs) == 0

    def test_label_constants(self):
        assert SAME_ACTOR == 1
        assert DIFFERENT_ACTOR == 0
