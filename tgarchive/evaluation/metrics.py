"""Evaluation metrics for classification, ranking, and forensic attribution.

Implements all metrics from scratch using NumPy (zero scikit-learn dependency).
Provides robust edge-case handling for empty inputs, division by zero,
single-class ground truth, and tie breaking.
"""
from __future__ import annotations

import logging
from typing import Any, Collection, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification Metrics
# ---------------------------------------------------------------------------


def _extract_classes_and_binary_label(
    y_true_arr: np.ndarray, y_pred_arr: np.ndarray
) -> Tuple[np.ndarray, Any]:
    """Extract sorted unique classes and choose a sensible positive label for binary cases."""
    all_classes = np.unique(np.concatenate([y_true_arr, y_pred_arr]))
    if len(all_classes) == 0:
        return all_classes, 1

    # If {0, 1} or {False, True} or 1 is present, use 1 / True as positive label
    if 1 in all_classes:
        pos_label = 1
    elif True in all_classes:
        pos_label = True
    elif len(all_classes) == 2:
        pos_label = all_classes[1]
    else:
        pos_label = all_classes[-1]
    return all_classes, pos_label


def precision(
    y_true: Sequence[Any] | np.ndarray,
    y_pred: Sequence[Any] | np.ndarray,
    average: str = "binary",
    pos_label: Optional[Any] = None,
) -> float:
    """Compute precision score for binary or multiclass classification.

    Precision is the ratio ``tp / (tp + fp)`` where tp is the number of
    true positives and fp the number of false positives.

    Args:
        y_true: Ground truth (correct) target values.
        y_pred: Estimated targets as returned by a classifier.
        average: Averaging strategy: ``'binary'``, ``'macro'``, or ``'micro'``.
        pos_label: The class to report if ``average='binary'``. If None, defaults
            to 1 (or True) if present, or the second unique class.

    Returns:
        Precision score as a float in [0.0, 1.0]. Returns 0.0 on empty inputs
        or when tp + fp == 0.

    Raises:
        ValueError: If lengths of y_true and y_pred differ or average is unsupported.
    """
    y_t = np.asarray(y_true)
    y_p = np.asarray(y_pred)

    if len(y_t) != len(y_p):
        raise ValueError(
            f"Length mismatch: len(y_true)={len(y_t)} != len(y_pred)={len(y_p)}"
        )
    if len(y_t) == 0:
        return 0.0

    avg = average.lower()
    if avg not in ("binary", "macro", "micro"):
        raise ValueError(
            f"Unsupported average='{average}'. Choose from 'binary', 'macro', 'micro'."
        )

    all_classes, default_pos = _extract_classes_and_binary_label(y_t, y_p)
    if pos_label is None:
        pos_label = default_pos

    if avg == "binary":
        tp = np.sum((y_t == pos_label) & (y_p == pos_label))
        fp = np.sum((y_t != pos_label) & (y_p == pos_label))
        denom = tp + fp
        return float(tp / denom) if denom > 0 else 0.0

    if avg == "micro":
        # In single-label multiclass classification, micro-precision equals accuracy
        correct = np.sum(y_t == y_p)
        return float(correct / len(y_t)) if len(y_t) > 0 else 0.0

    # Macro averaging
    precisions: List[float] = []
    for cls in all_classes:
        tp = np.sum((y_t == cls) & (y_p == cls))
        fp = np.sum((y_t != cls) & (y_p == cls))
        denom = tp + fp
        precisions.append(float(tp / denom) if denom > 0 else 0.0)

    return float(np.mean(precisions)) if precisions else 0.0


def recall(
    y_true: Sequence[Any] | np.ndarray,
    y_pred: Sequence[Any] | np.ndarray,
    average: str = "binary",
    pos_label: Optional[Any] = None,
) -> float:
    """Compute recall score for binary or multiclass classification.

    Recall is the ratio ``tp / (tp + fn)`` where tp is the number of
    true positives and fn the number of false negatives.

    Args:
        y_true: Ground truth (correct) target values.
        y_pred: Estimated targets as returned by a classifier.
        average: Averaging strategy: ``'binary'``, ``'macro'``, or ``'micro'``.
        pos_label: The class to report if ``average='binary'``. If None, defaults
            to 1 (or True) if present, or the second unique class.

    Returns:
        Recall score as a float in [0.0, 1.0]. Returns 0.0 on empty inputs
        or when tp + fn == 0.

    Raises:
        ValueError: If lengths of y_true and y_pred differ or average is unsupported.
    """
    y_t = np.asarray(y_true)
    y_p = np.asarray(y_pred)

    if len(y_t) != len(y_p):
        raise ValueError(
            f"Length mismatch: len(y_true)={len(y_t)} != len(y_pred)={len(y_p)}"
        )
    if len(y_t) == 0:
        return 0.0

    avg = average.lower()
    if avg not in ("binary", "macro", "micro"):
        raise ValueError(
            f"Unsupported average='{average}'. Choose from 'binary', 'macro', 'micro'."
        )

    all_classes, default_pos = _extract_classes_and_binary_label(y_t, y_p)
    if pos_label is None:
        pos_label = default_pos

    if avg == "binary":
        tp = np.sum((y_t == pos_label) & (y_p == pos_label))
        fn = np.sum((y_t == pos_label) & (y_p != pos_label))
        denom = tp + fn
        return float(tp / denom) if denom > 0 else 0.0

    if avg == "micro":
        correct = np.sum(y_t == y_p)
        return float(correct / len(y_t)) if len(y_t) > 0 else 0.0

    # Macro averaging
    recalls: List[float] = []
    for cls in all_classes:
        tp = np.sum((y_t == cls) & (y_p == cls))
        fn = np.sum((y_t == cls) & (y_p != cls))
        denom = tp + fn
        recalls.append(float(tp / denom) if denom > 0 else 0.0)

    return float(np.mean(recalls)) if recalls else 0.0


def f1_score(
    y_true: Sequence[Any] | np.ndarray,
    y_pred: Sequence[Any] | np.ndarray,
    average: str = "binary",
    pos_label: Optional[Any] = None,
) -> float:
    """Compute the F1 score (harmonic mean of precision and recall).

    Args:
        y_true: Ground truth (correct) target values.
        y_pred: Estimated targets as returned by a classifier.
        average: Averaging strategy: ``'binary'``, ``'macro'``, or ``'micro'``.
        pos_label: The class to report if ``average='binary'``.

    Returns:
        F1 score as a float in [0.0, 1.0]. Returns 0.0 when precision + recall == 0.

    Raises:
        ValueError: If lengths of y_true and y_pred differ or average is unsupported.
    """
    y_t = np.asarray(y_true)
    y_p = np.asarray(y_pred)

    if len(y_t) != len(y_p):
        raise ValueError(
            f"Length mismatch: len(y_true)={len(y_t)} != len(y_pred)={len(y_p)}"
        )
    if len(y_t) == 0:
        return 0.0

    avg = average.lower()
    if avg not in ("binary", "macro", "micro"):
        raise ValueError(
            f"Unsupported average='{average}'. Choose from 'binary', 'macro', 'micro'."
        )

    all_classes, default_pos = _extract_classes_and_binary_label(y_t, y_p)
    if pos_label is None:
        pos_label = default_pos

    if avg == "binary":
        p = precision(y_t, y_p, average="binary", pos_label=pos_label)
        r = recall(y_t, y_p, average="binary", pos_label=pos_label)
        denom = p + r
        return float((2.0 * p * r) / denom) if denom > 0 else 0.0

    if avg == "micro":
        p = precision(y_t, y_p, average="micro")
        r = recall(y_t, y_p, average="micro")
        denom = p + r
        return float((2.0 * p * r) / denom) if denom > 0 else 0.0

    # Macro averaging: unweighted mean of per-class F1 scores
    f1_list: List[float] = []
    for cls in all_classes:
        p_c = precision(y_t, y_p, average="binary", pos_label=cls)
        r_c = recall(y_t, y_p, average="binary", pos_label=cls)
        denom = p_c + r_c
        f1_list.append(float((2.0 * p_c * r_c) / denom) if denom > 0 else 0.0)

    return float(np.mean(f1_list)) if f1_list else 0.0


def roc_auc(
    y_true: Sequence[Any] | np.ndarray,
    y_scores: Sequence[float] | np.ndarray,
    pos_label: Optional[Any] = None,
) -> float:
    """Compute Area Under the Receiver Operating Characteristic Curve (ROC AUC).

    Calculates ROC AUC using the rank-sum (Wilcoxon-Mann-Whitney U) formulation
    with exact tie handling, matching standard definitions.

    Args:
        y_true: Binary ground truth labels (0/1 or boolean).
        y_scores: Target scores / probability estimates of the positive class.
        pos_label: Positive class label. Defaults to 1/True or the second class.

    Returns:
        ROC AUC score as a float in [0.0, 1.0]. Returns 0.0 if empty or if only
        one class is present in y_true.

    Raises:
        ValueError: If lengths of y_true and y_scores differ.
    """
    y_t = np.asarray(y_true)
    scores = np.asarray(y_scores, dtype=float)

    if len(y_t) != len(scores):
        raise ValueError(
            f"Length mismatch: len(y_true)={len(y_t)} != len(y_scores)={len(scores)}"
        )
    if len(y_t) == 0:
        return 0.0

    # Normalize ground truth to binary 0 / 1
    unique_labels = np.unique(y_t)
    if len(unique_labels) < 2:
        logger.warning("ROC AUC is undefined with only one class present in y_true; returning 0.0")
        return 0.0

    if pos_label is None:
        _, pos_label = _extract_classes_and_binary_label(y_t, np.array([]))
    y_bin = (y_t == pos_label).astype(int)

    n_pos = int(np.sum(y_bin))
    n_neg = len(y_bin) - n_pos

    if n_pos == 0 or n_neg == 0:
        return 0.0

    # Rank-sum calculation with tied-rank averaging
    order = np.argsort(scores)
    sorted_scores = scores[order]
    _, inv, counts = np.unique(sorted_scores, return_inverse=True, return_counts=True)
    cum_counts = np.cumsum(counts)
    avg_ranks_per_unique = cum_counts - (counts - 1) / 2.0
    sorted_ranks = avg_ranks_per_unique[inv]

    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = sorted_ranks

    sum_pos_ranks = float(np.sum(ranks[y_bin == 1]))
    auc = (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return float(np.clip(auc, 0.0, 1.0))


def pr_auc(
    y_true: Sequence[Any] | np.ndarray,
    y_scores: Sequence[float] | np.ndarray,
    pos_label: Optional[Any] = None,
) -> float:
    """Compute Area Under the Precision-Recall Curve (PR AUC / Average Precision).

    Integrates the precision-recall curve using the trapezoidal rule across
    all distinct operating thresholds.

    Args:
        y_true: Binary ground truth labels (0/1 or boolean).
        y_scores: Target scores / probability estimates of the positive class.
        pos_label: Positive class label. Defaults to 1/True or the second class.

    Returns:
        PR AUC score as a float in [0.0, 1.0]. Returns 0.0 if empty or if no
        positive instances exist in y_true.

    Raises:
        ValueError: If lengths of y_true and y_scores differ.
    """
    y_t = np.asarray(y_true)
    scores = np.asarray(y_scores, dtype=float)

    if len(y_t) != len(scores):
        raise ValueError(
            f"Length mismatch: len(y_true)={len(y_t)} != len(y_scores)={len(scores)}"
        )
    if len(y_t) == 0:
        return 0.0

    unique_labels = np.unique(y_t)
    if len(unique_labels) < 2:
        logger.warning("PR AUC is undefined with only one class present in y_true; returning 0.0")
        return 0.0

    if pos_label is None:
        _, pos_label = _extract_classes_and_binary_label(y_t, np.array([]))
    y_bin = (y_t == pos_label).astype(int)
    n_pos = int(np.sum(y_bin))

    if n_pos == 0 or n_pos == len(y_bin):
        logger.warning("PR AUC is undefined when no positive samples exist in y_true; returning 0.0")
        return 0.0

    # Sort descending by score
    desc_order = np.argsort(-scores, kind="mergesort")
    y_sorted = y_bin[desc_order]
    scores_sorted = scores[desc_order]

    # Find indices where threshold changes (or at the end)
    distinct_mask = np.diff(scores_sorted) != 0
    distinct_indices = np.concatenate([np.where(distinct_mask)[0], [len(scores_sorted) - 1]])

    tps = np.cumsum(y_sorted)[distinct_indices]
    fps = (distinct_indices + 1) - tps

    recalls = tps / float(n_pos)
    precisions = tps / (tps + fps)

    # Prepend starting point (recall=0, precision of first point or 1.0)
    recalls = np.concatenate([[0.0], recalls])
    precisions = np.concatenate([[precisions[0] if len(precisions) > 0 else 1.0], precisions])

    # Trapezoidal integration along recall axis
    r_diff = np.diff(recalls)
    p_avg = (precisions[:-1] + precisions[1:]) / 2.0
    auc = float(np.sum(r_diff * p_avg))
    return float(np.clip(auc, 0.0, 1.0))


def confusion_matrix(
    y_true: Sequence[Any] | np.ndarray,
    y_pred: Sequence[Any] | np.ndarray,
    labels: Optional[Sequence[Any]] = None,
) -> np.ndarray:
    """Compute confusion matrix to evaluate the accuracy of a classification.

    By definition a confusion matrix :math:`C` is such that :math:`C_{i, j}`
    is equal to the number of observations known to be in group :math:`i` and
    predicted to be in group :math:`j`.

    Args:
        y_true: Ground truth (correct) target values.
        y_pred: Estimated targets as returned by a classifier.
        labels: List of labels to index the matrix. If None, uses sorted unique
            labels appearing in y_true or y_pred.

    Returns:
        2D NumPy array of shape ``(len(labels), len(labels))`` containing counts.

    Raises:
        ValueError: If lengths of y_true and y_pred differ.
    """
    y_t = np.asarray(y_true)
    y_p = np.asarray(y_pred)

    if len(y_t) != len(y_p):
        raise ValueError(
            f"Length mismatch: len(y_true)={len(y_t)} != len(y_pred)={len(y_p)}"
        )
    if len(y_t) == 0:
        return np.zeros((0, 0), dtype=int)

    if labels is None:
        target_labels = list(np.unique(np.concatenate([y_t, y_p])))
    else:
        target_labels = list(labels)

    n_labels = len(target_labels)
    label_to_idx = {lbl: idx for idx, lbl in enumerate(target_labels)}

    cm = np.zeros((n_labels, n_labels), dtype=int)
    for true_val, pred_val in zip(y_t, y_p):
        t_idx = label_to_idx.get(true_val)
        p_idx = label_to_idx.get(pred_val)
        if t_idx is not None and p_idx is not None:
            cm[t_idx, p_idx] += 1

    return cm


# ---------------------------------------------------------------------------
# Ranking Metrics
# ---------------------------------------------------------------------------


def _is_batch_ranking(
    ranked_results: Any, relevant: Any
) -> bool:
    """Detect if input represents multiple queries (batch) vs a single query."""
    if not isinstance(ranked_results, (list, tuple, np.ndarray)):
        return False
    if len(ranked_results) == 0:
        return False
    first_elem = ranked_results[0]
    return isinstance(first_elem, (list, tuple, np.ndarray))


def mrr(
    relevant_docs: Collection[Any] | Sequence[Collection[Any]],
    ranked_results: Sequence[Any] | Sequence[Sequence[Any]],
) -> float:
    """Compute Mean Reciprocal Rank (MRR).

    Accepts either a single query evaluation or a batch of queries. For each
    query, finds the rank :math:`r` (1-indexed) of the first retrieved item
    that is in the set of relevant documents, scoring :math:`1 / r`.

    Args:
        relevant_docs: Collection of relevant document IDs (or a list of such
            collections for batch evaluation).
        ranked_results: Ordered sequence of retrieved document IDs (or a list
            of ordered sequences for batch evaluation).

    Returns:
        MRR score as a float in [0.0, 1.0]. Returns 0.0 if no relevant items
        are found or if inputs are empty.
    """
    if len(ranked_results) == 0 or len(relevant_docs) == 0:
        return 0.0

    if _is_batch_ranking(ranked_results, relevant_docs):
        rr_scores: List[float] = []
        for rel, ranked in zip(relevant_docs, ranked_results):
            rr_scores.append(mrr(rel, ranked))
        return float(np.mean(rr_scores)) if rr_scores else 0.0

    rel_set = set(relevant_docs)
    if not rel_set:
        return 0.0

    for rank, doc in enumerate(ranked_results, start=1):
        if doc in rel_set:
            return 1.0 / rank

    return 0.0


def recall_at_k(
    relevant_docs: Collection[Any] | Sequence[Collection[Any]],
    ranked_results: Sequence[Any] | Sequence[Sequence[Any]],
    k: int = 10,
) -> float:
    """Compute Recall@k for search and retrieval.

    Proportion of relevant documents retrieved within the top ``k`` ranked results.
    Accepts single query or batch of queries.

    Args:
        relevant_docs: Collection of relevant document IDs (or list of collections).
        ranked_results: Ordered sequence of retrieved document IDs (or list of sequences).
        k: Cutoff rank (must be > 0).

    Returns:
        Recall@k as a float in [0.0, 1.0]. Returns 0.0 if empty or k <= 0.
    """
    if k <= 0 or len(ranked_results) == 0 or len(relevant_docs) == 0:
        return 0.0

    if _is_batch_ranking(ranked_results, relevant_docs):
        recalls: List[float] = []
        for rel, ranked in zip(relevant_docs, ranked_results):
            recalls.append(recall_at_k(rel, ranked, k=k))
        return float(np.mean(recalls)) if recalls else 0.0

    rel_set = set(relevant_docs)
    if not rel_set:
        return 0.0

    top_k = set(ranked_results[:k])
    hits = len(top_k & rel_set)
    return float(hits / len(rel_set))


def ndcg_at_k(
    relevant_scores: Union[
        Dict[Any, float],
        Sequence[float],
        Sequence[Union[Dict[Any, float], Sequence[float]]],
    ],
    ranked_results: Sequence[Any] | Sequence[Sequence[Any]],
    k: int = 10,
) -> float:
    """Compute Normalized Discounted Cumulative Gain at k (NDCG@k).

    Uses exponential relevance weighting :math:`(2^{rel} - 1) / \\log_2(i + 1)`
    for graded relevance and binary relevance alike.

    Args:
        relevant_scores: Either:
            - Dict mapping doc_id -> numeric relevance score.
            - Sequence of numeric relevance scores aligned with ranked_results.
            - List of the above for batch evaluation.
        ranked_results: Ordered sequence of retrieved document IDs (or list of sequences).
        k: Cutoff rank (must be > 0).

    Returns:
        NDCG@k score as a float in [0.0, 1.0]. Returns 0.0 if ideal DCG is 0 or inputs empty.
    """
    if k <= 0 or len(ranked_results) == 0:
        return 0.0

    if _is_batch_ranking(ranked_results, relevant_scores):
        ndcg_list: List[float] = []
        for rel_s, ranked in zip(relevant_scores, ranked_results):
            ndcg_list.append(ndcg_at_k(rel_s, ranked, k=k))
        return float(np.mean(ndcg_list)) if ndcg_list else 0.0

    # Single query case
    gains: List[float] = []
    ideal_pool: List[float] = []

    if isinstance(relevant_scores, dict):
        for doc in ranked_results[:k]:
            gains.append(float(relevant_scores.get(doc, 0.0)))
        ideal_pool = sorted([float(v) for v in relevant_scores.values()], reverse=True)
    elif isinstance(relevant_scores, (list, tuple, np.ndarray)):
        # List of scores aligned with ranked_results
        scores_list = [float(s) for s in relevant_scores]
        gains = scores_list[:k]
        ideal_pool = sorted(scores_list, reverse=True)
    else:
        return 0.0

    if not ideal_pool or all(g <= 0.0 for g in ideal_pool):
        return 0.0

    # Compute DCG@k
    dcg = 0.0
    for idx, gain in enumerate(gains, start=1):
        if gain > 0:
            dcg += (2.0 ** gain - 1.0) / np.log2(idx + 1.0)

    # Compute IDCG@k
    idcg = 0.0
    for idx, gain in enumerate(ideal_pool[:k], start=1):
        if gain > 0:
            idcg += (2.0 ** gain - 1.0) / np.log2(idx + 1.0)

    if idcg <= 0.0:
        return 0.0

    return float(np.clip(dcg / idcg, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Attribution Metrics
# ---------------------------------------------------------------------------


def top_k_accuracy(
    true_actors: Sequence[Any],
    predicted_actors: Sequence[Sequence[Any]],
    k: int = 1,
) -> float:
    """Compute Top-k Attribution Accuracy.

    Measures the fraction of samples where the ground truth actor is present
    within the top ``k`` candidate predictions.

    Args:
        true_actors: True actor identifiers for each query sample.
        predicted_actors: Ranked list/tuple of predicted actor IDs for each sample.
        k: Cutoff rank for prediction list (default: 1).

    Returns:
        Top-k accuracy as a float in [0.0, 1.0]. Returns 0.0 if empty or k <= 0.

    Raises:
        ValueError: If lengths of true_actors and predicted_actors differ.
    """
    if len(true_actors) != len(predicted_actors):
        raise ValueError(
            f"Length mismatch: len(true_actors)={len(true_actors)} != len(predicted_actors)={len(predicted_actors)}"
        )
    if len(true_actors) == 0 or k <= 0:
        return 0.0

    hits = 0
    for true_actor, preds in zip(true_actors, predicted_actors):
        top_k_candidates = preds[:k] if preds is not None else []
        if true_actor in top_k_candidates:
            hits += 1

    return float(hits / len(true_actors))


def _canonicalize_pairs(pairs: Collection[Tuple[Any, Any]]) -> set[Tuple[Any, Any]]:
    """Normalize pairs into unordered canonical 2-tuples excluding self-pairs."""
    canonical: set[Tuple[Any, Any]] = set()
    for pair in pairs:
        if len(pair) == 2 and pair[0] != pair[1]:
            # Sort pair elements if comparable, else use string representation
            try:
                elem1, elem2 = (pair[0], pair[1]) if pair[0] < pair[1] else (pair[1], pair[0])
            except TypeError:
                elem1, elem2 = (pair[0], pair[1]) if str(pair[0]) < str(pair[1]) else (pair[1], pair[0])
            canonical.add((elem1, elem2))
    return canonical


def false_link_rate(
    true_pairs: Collection[Tuple[Any, Any]],
    predicted_pairs: Collection[Tuple[Any, Any]],
) -> float:
    """Compute False Link Rate (FLR / Link False Discovery Rate).

    In entity resolution and forensic actor attribution, False Link Rate is
    the fraction of predicted linked pairs that are incorrect (i.e. not in
    true_pairs): ``FP / (TP + FP) = FP / |predicted_pairs|``.

    Pairs are treated as undirected edges between two entities (e.g. (A, B) == (B, A)).

    Args:
        true_pairs: Ground truth same-actor entity pairs.
        predicted_pairs: Model-predicted same-actor entity pairs.

    Returns:
        False link rate as a float in [0.0, 1.0]. Returns 0.0 if predicted_pairs is empty.
    """
    c_pred = _canonicalize_pairs(predicted_pairs)
    if not c_pred:
        return 0.0

    c_true = _canonicalize_pairs(true_pairs)
    false_links = c_pred - c_true
    return float(len(false_links) / len(c_pred))


def false_split_rate(
    true_pairs: Collection[Tuple[Any, Any]],
    predicted_pairs: Collection[Tuple[Any, Any]],
) -> float:
    """Compute False Split Rate (FSR / Link Miss Rate).

    In entity resolution and forensic actor attribution, False Split Rate is
    the fraction of true same-actor pairs that the model failed to link:
    ``FN / (TP + FN) = FN / |true_pairs|``.

    Pairs are treated as undirected edges between two entities (e.g. (A, B) == (B, A)).

    Args:
        true_pairs: Ground truth same-actor entity pairs.
        predicted_pairs: Model-predicted same-actor entity pairs.

    Returns:
        False split rate as a float in [0.0, 1.0]. Returns 0.0 if true_pairs is empty.
    """
    c_true = _canonicalize_pairs(true_pairs)
    if not c_true:
        return 0.0

    c_pred = _canonicalize_pairs(predicted_pairs)
    false_splits = c_true - c_pred
    return float(len(false_splits) / len(c_true))


__all__ = [
    "precision",
    "recall",
    "f1_score",
    "roc_auc",
    "pr_auc",
    "confusion_matrix",
    "mrr",
    "recall_at_k",
    "ndcg_at_k",
    "top_k_accuracy",
    "false_link_rate",
    "false_split_rate",
]
