"""Tests for tgarchive.evaluation.metrics and tgarchive.evaluation.splits."""
from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pytest

from tgarchive.evaluation.metrics import (
    confusion_matrix,
    f1_score,
    false_link_rate,
    false_split_rate,
    mrr,
    ndcg_at_k,
    pr_auc,
    precision,
    recall,
    recall_at_k,
    roc_auc,
    top_k_accuracy,
)
from tgarchive.evaluation.splits import (
    temporal_split,
    temporal_split_by_ratio,
)


class TestClassificationMetrics:
    def test_precision_binary(self):
        y_true = [1, 1, 0, 0, 1, 0]
        y_pred = [1, 0, 0, 1, 1, 0]
        # TP: idx 0, 4 (2). FP: idx 3 (1). Prec = 2 / 3
        assert np.isclose(precision(y_true, y_pred, average="binary"), 2.0 / 3.0)

    def test_recall_binary(self):
        y_true = [1, 1, 0, 0, 1, 0]
        y_pred = [1, 0, 0, 1, 1, 0]
        # TP: idx 0, 4 (2). FN: idx 1 (1). Rec = 2 / 3
        assert np.isclose(recall(y_true, y_pred, average="binary"), 2.0 / 3.0)

    def test_f1_score_binary(self):
        y_true = [1, 1, 0, 0, 1, 0]
        y_pred = [1, 0, 0, 1, 1, 0]
        # Prec = 2/3, Rec = 2/3 -> F1 = 2/3
        assert np.isclose(f1_score(y_true, y_pred, average="binary"), 2.0 / 3.0)

    def test_multiclass_macro_micro(self):
        y_true = [0, 1, 2, 0, 1, 2]
        y_pred = [0, 2, 1, 0, 0, 1]

        # Check micro precision equals micro recall equals accuracy
        p_micro = precision(y_true, y_pred, average="micro")
        r_micro = recall(y_true, y_pred, average="micro")
        f1_micro = f1_score(y_true, y_pred, average="micro")
        # 2 correct out of 6 (idx 0, 3) -> 2/6 = 1/3
        assert np.isclose(p_micro, 1.0 / 3.0)
        assert np.isclose(r_micro, 1.0 / 3.0)
        assert np.isclose(f1_micro, 1.0 / 3.0)

        p_macro = precision(y_true, y_pred, average="macro")
        r_macro = recall(y_true, y_pred, average="macro")
        f1_macro = f1_score(y_true, y_pred, average="macro")
        assert 0.0 <= p_macro <= 1.0
        assert 0.0 <= r_macro <= 1.0
        assert 0.0 <= f1_macro <= 1.0

    def test_roc_auc_perfect(self):
        y_true = [0, 0, 1, 1]
        y_scores = [0.1, 0.2, 0.8, 0.9]
        assert np.isclose(roc_auc(y_true, y_scores), 1.0)

    def test_roc_auc_inverted(self):
        y_true = [0, 0, 1, 1]
        y_scores = [0.9, 0.8, 0.2, 0.1]
        assert np.isclose(roc_auc(y_true, y_scores), 0.0)

    def test_roc_auc_with_ties(self):
        y_true = [0, 0, 1, 1]
        y_scores = [0.1, 0.4, 0.4, 0.8]
        # (0.1: rank 1 neg, 0.4: rank 2.5 neg & pos, 0.8: rank 4 pos)
        # Sum pos ranks: 2.5 + 4 = 6.5. U = 6.5 - 3 = 3.5. AUC = 3.5 / 4 = 0.875
        assert np.isclose(roc_auc(y_true, y_scores), 0.875)

    def test_pr_auc_perfect(self):
        y_true = [0, 0, 1, 1]
        y_scores = [0.1, 0.2, 0.8, 0.9]
        assert np.isclose(pr_auc(y_true, y_scores), 1.0)

    def test_confusion_matrix(self):
        y_true = [0, 1, 0, 1, 0]
        y_pred = [0, 1, 1, 0, 0]
        cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
        # TN=2 (pred 0 when 0), FP=1 (pred 1 when 0), FN=1 (pred 0 when 1), TP=1 (pred 1 when 1)
        expected = np.array([[2, 1], [1, 1]])
        np.testing.assert_array_equal(cm, expected)

    def test_edge_cases_empty_and_zero_division(self):
        assert precision([], []) == 0.0
        assert recall([], []) == 0.0
        assert f1_score([], []) == 0.0
        assert roc_auc([], []) == 0.0
        assert pr_auc([], []) == 0.0
        assert confusion_matrix([], []).shape == (0, 0)

        # All 0 predictions (no predicted positives)
        assert precision([1, 1], [0, 0]) == 0.0
        assert recall([1, 1], [0, 0]) == 0.0
        assert f1_score([1, 1], [0, 0]) == 0.0

        # Only one class in y_true for roc_auc / pr_auc
        assert roc_auc([0, 0, 0], [0.1, 0.2, 0.3]) == 0.0
        assert pr_auc([0, 0, 0], [0.1, 0.2, 0.3]) == 0.0

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            precision([1, 0], [1])
        with pytest.raises(ValueError):
            recall([1, 0], [1])
        with pytest.raises(ValueError):
            f1_score([1, 0], [1])
        with pytest.raises(ValueError):
            roc_auc([1, 0], [0.5])
        with pytest.raises(ValueError):
            pr_auc([1, 0], [0.5])
        with pytest.raises(ValueError):
            confusion_matrix([1, 0], [0])


class TestRankingMetrics:
    def test_mrr_single_query(self):
        rel = {"doc3"}
        ranked = ["doc1", "doc2", "doc3", "doc4"]
        assert np.isclose(mrr(rel, ranked), 1.0 / 3.0)

    def test_mrr_batch(self):
        rel_batch = [{"doc1"}, {"doc3"}]
        ranked_batch = [["doc1", "doc2"], ["doc1", "doc2", "doc3"]]
        # Q1: 1/1 = 1.0. Q2: 1/3. Mean = 2/3
        assert np.isclose(mrr(rel_batch, ranked_batch), (1.0 + 1.0 / 3.0) / 2.0)

    def test_recall_at_k(self):
        rel = {"doc1", "doc2", "doc3"}
        ranked = ["doc1", "doc4", "doc2", "doc5", "doc3"]
        # top 2: doc1 -> recall@2 = 1/3
        assert np.isclose(recall_at_k(rel, ranked, k=2), 1.0 / 3.0)
        # top 3: doc1, doc2 -> recall@3 = 2/3
        assert np.isclose(recall_at_k(rel, ranked, k=3), 2.0 / 3.0)
        # top 5: doc1, doc2, doc3 -> recall@5 = 1.0
        assert np.isclose(recall_at_k(rel, ranked, k=5), 1.0)

    def test_ndcg_at_k(self):
        # Graded relevance scores via dict
        scores = {"doc1": 3.0, "doc2": 2.0, "doc3": 1.0, "doc4": 0.0}
        perfect_ranked = ["doc1", "doc2", "doc3", "doc4"]
        assert np.isclose(ndcg_at_k(scores, perfect_ranked, k=3), 1.0)

        suboptimal_ranked = ["doc2", "doc1", "doc3", "doc4"]
        val = ndcg_at_k(scores, suboptimal_ranked, k=3)
        assert 0.0 < val < 1.0

        # Graded relevance scores via sequence aligned with ranked
        aligned_scores = [3.0, 2.0, 1.0, 0.0]
        assert np.isclose(ndcg_at_k(aligned_scores, perfect_ranked, k=3), 1.0)

        # Batch NDCG
        batch_scores = [{"d1": 2.0, "d2": 1.0}, {"d1": 1.0, "d2": 2.0}]
        batch_ranked = [["d1", "d2"], ["d2", "d1"]]
        assert np.isclose(ndcg_at_k(batch_scores, batch_ranked, k=2), 1.0)

    def test_ranking_edge_cases(self):
        assert mrr([], []) == 0.0
        assert recall_at_k([], [], k=5) == 0.0
        assert recall_at_k(["doc1"], ["doc1"], k=0) == 0.0
        assert ndcg_at_k({}, [], k=5) == 0.0
        assert ndcg_at_k({"doc1": 0.0}, ["doc1"], k=5) == 0.0


class TestAttributionMetrics:
    def test_top_k_accuracy(self):
        true_actors = ["A1", "A2", "A3", "A4"]
        pred_actors = [
            ["A1", "A9", "A8"],
            ["A9", "A2", "A8"],
            ["A9", "A8", "A3"],
            ["A9", "A8", "A7"],
        ]
        # top-1: only sample 0 has A1 at rank 1 -> 1/4 = 0.25
        assert np.isclose(top_k_accuracy(true_actors, pred_actors, k=1), 0.25)
        # top-2: sample 0 (A1@1) and sample 1 (A2@2) -> 2/4 = 0.50
        assert np.isclose(top_k_accuracy(true_actors, pred_actors, k=2), 0.50)
        # top-3: samples 0, 1, 2 -> 3/4 = 0.75
        assert np.isclose(top_k_accuracy(true_actors, pred_actors, k=3), 0.75)

    def test_false_link_rate(self):
        # Pairs are undirected (A, B) == (B, A)
        true_pairs = [("A", "B"), ("C", "D")]
        pred_pairs = [("B", "A"), ("C", "D"), ("A", "C"), ("B", "D")]
        # Pred has 4 pairs: (A, B) [True], (C, D) [True], (A, C) [False], (B, D) [False]
        # False links = 2 out of 4 = 0.5
        assert np.isclose(false_link_rate(true_pairs, pred_pairs), 0.5)

    def test_false_split_rate(self):
        true_pairs = [("A", "B"), ("C", "D"), ("E", "F"), ("G", "H")]
        pred_pairs = [("A", "B"), ("D", "C")]
        # True has 4 pairs. Model found (A, B) and (C, D). Missed (E, F) and (G, H) -> 2 missed / 4 = 0.5
        assert np.isclose(false_split_rate(true_pairs, pred_pairs), 0.5)

    def test_attribution_edge_cases(self):
        assert top_k_accuracy([], []) == 0.0
        assert false_link_rate([], []) == 0.0
        assert false_split_rate([], []) == 0.0

        with pytest.raises(ValueError):
            top_k_accuracy(["A"], [])


class TestSplits:
    def test_temporal_split_dates_and_strings(self):
        messages = [
            {"id": 1, "date": "2023-01-01T10:00:00Z"},
            {"id": 2, "date": "2023-03-01T10:00:00+00:00"},
            {"id": 3, "date": datetime(2023, 6, 1, 10, 0, 0, tzinfo=timezone.utc)},
            {"id": 4, "date": datetime(2023, 9, 1, 10, 0, 0)},  # naive -> treated as UTC
            {"id": 5, "date": "2023-12-01 10:00:00"},
        ]

        train_end = "2023-02-01T00:00:00Z"
        val_end = "2023-08-01T00:00:00Z"

        train, val, test = temporal_split(messages, train_end, val_end)

        assert [m["id"] for m in train] == [1]
        assert [m["id"] for m in val] == [2, 3]
        assert [m["id"] for m in test] == [4, 5]

    def test_temporal_split_by_ratio(self):
        messages = [
            {"id": 3, "date": "2023-03-01T00:00:00Z"},
            {"id": 1, "date": "2023-01-01T00:00:00Z"},
            {"id": 5, "date": "2023-05-01T00:00:00Z"},
            {"id": 2, "date": "2023-02-01T00:00:00Z"},
            {"id": 4, "date": "2023-04-01T00:00:00Z"},
        ]

        # 5 items: train_ratio=0.6 -> int(5*0.6) = 3 items. val_ratio=0.2 -> int(5*0.2) = 1 item. test = 1 item.
        train, val, test = temporal_split_by_ratio(messages, train_ratio=0.6, val_ratio=0.2)

        assert [m["id"] for m in train] == [1, 2, 3]
        assert [m["id"] for m in val] == [4]
        assert [m["id"] for m in test] == [5]

    def test_temporal_split_invalid_ratios_and_bounds(self):
        messages = [{"id": 1, "date": "2023-01-01T00:00:00Z"}]
        with pytest.raises(ValueError):
            temporal_split(messages, train_end="2023-05-01", val_end="2023-01-01")

        with pytest.raises(ValueError):
            temporal_split_by_ratio(messages, train_ratio=0.8, val_ratio=0.3)

        with pytest.raises(ValueError):
            temporal_split_by_ratio(messages, train_ratio=-0.1, val_ratio=0.2)

    def test_empty_messages(self):
        train, val, test = temporal_split([], "2023-01-01", "2023-06-01")
        assert train == [] and val == [] and test == []

        train_r, val_r, test_r = temporal_split_by_ratio([], 0.6, 0.2)
        assert train_r == [] and val_r == [] and test_r == []
