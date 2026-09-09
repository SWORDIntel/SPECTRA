"""
SPECTRA Benchmark Runners
=========================
End-to-end benchmark execution for analytical modules.

Runs a module against a dataset, collects predictions, and computes
all relevant metrics via the evaluation harness.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from .metrics import (
    precision, recall, f1_score, roc_auc, pr_auc,
    mrr, recall_at_k, ndcg_at_k,
    top_k_accuracy, false_link_rate, false_split_rate,
)
from .calibration import brier_score, expected_calibration_error

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Result of running a benchmark."""
    benchmark_name: str
    dataset_name: str
    model_name: str
    model_version: str
    metrics: Dict[str, float] = field(default_factory=dict)
    predictions: List[Dict[str, Any]] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "benchmark_name": self.benchmark_name,
            "dataset_name": self.dataset_name,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "metrics": self.metrics,
            "predictions": self.predictions,
            "generated_at": self.generated_at.isoformat(),
            "metadata": self.metadata,
        }


def run_attribution_benchmark(
    engine: Any,
    dataset: Any,
    model_name: str = "",
    model_version: str = "",
    threshold: float = 0.5,
) -> BenchmarkResult:
    """
    Run an attribution engine against a dataset of actor pairs.

    The engine must expose a method that takes two lists of messages
    and returns a similarity/probability score. Accepts either:
    - engine.compare(msgs_a, msgs_b) -> float
    - engine.analyze_writing_style(msgs) + engine._cosine_similarity(v1, v2)

    Args:
        engine: Attribution engine or any object with a compare method
        dataset: Dataset with pairs (each has subject_a, subject_b, label, messages_a, messages_b)
        model_name: Name of the model being benchmarked
        model_version: Version string
        threshold: Decision threshold for binary classification

    Returns:
        BenchmarkResult with classification + calibration metrics
    """
    y_true: List[int] = []
    y_prob: List[float] = []
    predictions: List[Dict[str, Any]] = []

    for pair in dataset.pairs:
        msgs_a = pair.get("messages_a", [])
        msgs_b = pair.get("messages_b", [])
        label = pair.get("label", 0)

        # Get probability score from engine
        prob = _get_attribution_score(engine, msgs_a, msgs_b)

        y_true.append(label)
        y_prob.append(prob)
        predictions.append({
            "subject_a": pair.get("subject_a"),
            "subject_b": pair.get("subject_b"),
            "label": label,
            "predicted_prob": prob,
            "predicted_label": int(prob >= threshold),
        })

    # Compute metrics
    y_pred = [int(p >= threshold) for p in y_prob]

    metrics: Dict[str, float] = {}
    if y_true:
        metrics["precision"] = precision(y_true, y_pred)
        metrics["recall"] = recall(y_true, y_pred)
        metrics["f1"] = f1_score(y_true, y_pred)
        try:
            metrics["roc_auc"] = roc_auc(y_true, y_prob)
        except Exception:
            metrics["roc_auc"] = 0.0
        try:
            metrics["pr_auc"] = pr_auc(y_true, y_prob)
        except Exception:
            metrics["pr_auc"] = 0.0
        metrics["brier_score"] = brier_score(y_true, y_prob)
        metrics["ece"] = expected_calibration_error(y_true, y_prob)
    else:
        logger.warning("Empty dataset — no metrics computed")

    return BenchmarkResult(
        benchmark_name="attribution",
        dataset_name=dataset.name,
        model_name=model_name,
        model_version=model_version,
        metrics=metrics,
        predictions=predictions,
        metadata={"threshold": threshold, "pair_count": len(y_true)},
    )


def run_search_benchmark(
    search_fn: Callable[[str], List[Tuple[str, float]]],
    queries: List[Dict[str, Any]],
    model_name: str = "",
    model_version: str = "",
) -> BenchmarkResult:
    """
    Run a search/retrieval function against a set of queries.

    Args:
        search_fn: Function that takes a query string and returns
                   a list of (doc_id, score) tuples, ranked by score
        queries: List of {query: str, relevant_doc_ids: List[str]}
        model_name: Name of the search model
        model_version: Version string

    Returns:
        BenchmarkResult with ranking metrics (MRR, Recall@10, NDCG@10)
    """
    all_mrr: List[float] = []
    all_recall_10: List[float] = []
    all_recall_50: List[float] = []
    all_ndcg_10: List[float] = []
    predictions: List[Dict[str, Any]] = []

    for q in queries:
        query_text = q["query"]
        relevant = q.get("relevant_doc_ids", [])

        results = search_fn(query_text)
        ranked_ids = [doc_id for doc_id, _ in results]

        q_mrr = mrr(relevant, ranked_ids)
        q_r10 = recall_at_k(relevant, ranked_ids, k=10)
        q_r50 = recall_at_k(relevant, ranked_ids, k=50)
        q_ndcg = ndcg_at_k(
            {doc_id: 1.0 for doc_id in relevant}, ranked_ids, k=10
        )

        all_mrr.append(q_mrr)
        all_recall_10.append(q_r10)
        all_recall_50.append(q_r50)
        all_ndcg_10.append(q_ndcg)

        predictions.append({
            "query": query_text,
            "relevant_count": len(relevant),
            "mrr": q_mrr,
            "recall@10": q_r10,
            "ndcg@10": q_ndcg,
        })

    metrics: Dict[str, float] = {}
    if all_mrr:
        metrics["mrr"] = sum(all_mrr) / len(all_mrr)
        metrics["recall@10"] = sum(all_recall_10) / len(all_recall_10)
        metrics["recall@50"] = sum(all_recall_50) / len(all_recall_50)
        metrics["ndcg@10"] = sum(all_ndcg_10) / len(all_ndcg_10)
    else:
        logger.warning("No queries — no metrics computed")

    return BenchmarkResult(
        benchmark_name="search",
        dataset_name="search_queries",
        model_name=model_name,
        model_version=model_version,
        metrics=metrics,
        predictions=predictions,
        metadata={"query_count": len(queries)},
    )


def compare_versions(
    result_v1: BenchmarkResult,
    result_v2: BenchmarkResult,
) -> Dict[str, Any]:
    """
    Compare two benchmark results (e.g., model v1 vs v2).

    Returns:
        Dict with per-metric delta, improvement flags, and summary
    """
    comparison: Dict[str, Any] = {
        "v1_model": f"{result_v1.model_name}@{result_v1.model_version}",
        "v2_model": f"{result_v2.model_name}@{result_v2.model_version}",
        "dataset": result_v1.dataset_name,
        "metrics": {},
    }

    all_metrics = set(result_v1.metrics.keys()) | set(result_v2.metrics.keys())
    improvements = 0
    regressions = 0

    for metric in sorted(all_metrics):
        v1_val = result_v1.metrics.get(metric)
        v2_val = result_v2.metrics.get(metric)

        if v1_val is None or v2_val is None:
            continue

        delta = v2_val - v1_val
        # For most metrics, higher is better; for brier_score and ece, lower is better
        lower_is_better = metric in ("brier_score", "ece")
        improved = (delta > 0 and not lower_is_better) or (delta < 0 and lower_is_better)

        if improved:
            improvements += 1
        elif delta != 0:
            regressions += 1

        comparison["metrics"][metric] = {
            "v1": v1_val,
            "v2": v2_val,
            "delta": delta,
            "improved": improved,
        }

    comparison["summary"] = {
        "improvements": improvements,
        "regressions": regressions,
        "net_improvement": improvements - regressions,
    }

    return comparison


def _get_attribution_score(engine: Any, msgs_a: List[Dict], msgs_b: List[Dict]) -> float:
    """Extract a probability score from an attribution engine."""
    # Try compare() method first
    compare_fn = getattr(engine, "compare", None)
    if callable(compare_fn):
        return float(compare_fn(msgs_a, msgs_b))

    # Fall back to writing style + cosine similarity
    analyze_fn = getattr(engine, "analyze_writing_style", None)
    cosine_fn = getattr(engine, "_cosine_similarity", None)
    if callable(analyze_fn) and callable(cosine_fn):
        profile_a = analyze_fn(msgs_a)
        profile_b = analyze_fn(msgs_b)
        vec_a = profile_a.to_vector() if hasattr(profile_a, "to_vector") else profile_a
        vec_b = profile_b.to_vector() if hasattr(profile_b, "to_vector") else profile_b
        return float(cosine_fn(vec_a, vec_b))

    logger.warning("Engine has no compare() or analyze_writing_style() method")
    return 0.0


__all__ = [
    "BenchmarkResult",
    "run_attribution_benchmark",
    "run_search_benchmark",
    "compare_versions",
]
