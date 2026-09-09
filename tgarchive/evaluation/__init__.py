"""
SPECTRA Evaluation Harness
==========================
Forensic ground-truth benchmarking, dataset builders, calibration metrics,
and reporting for attribution and stylometry models.

Modules:
- metrics: Classification, ranking, and attribution metrics
- splits: Time-separated train/val/test splits
- datasets: Benchmark dataset builders from SPECTRA's SQLite DB
- calibration: Brier score, ECE, reliability diagrams
- benchmarks: End-to-end benchmark runners
- reports: Human-readable benchmark reports
"""
from __future__ import annotations

from .metrics import (
    precision,
    recall,
    f1_score,
    roc_auc,
    pr_auc,
    confusion_matrix,
    mrr,
    recall_at_k,
    ndcg_at_k,
    top_k_accuracy,
    false_link_rate,
    false_split_rate,
)
from .splits import (
    temporal_split,
    temporal_split_by_ratio,
)
from .calibration import (
    brier_score,
    calibration_map,
    expected_calibration_error,
    reliability_data,
)
from .datasets import (
    DIFFERENT_ACTOR,
    SAME_ACTOR,
    Dataset,
    build_bot_dataset,
    build_cross_channel_dataset,
    build_different_actor_dataset,
    build_forwarded_control_dataset,
    build_long_message_dataset,
    build_same_actor_dataset,
    build_short_message_dataset,
    build_style_change_dataset,
)
from .benchmarks import (
    BenchmarkResult,
    run_attribution_benchmark,
    run_search_benchmark,
    compare_versions,
)
from .reports import (
    generate_benchmark_report,
    generate_comparison_report,
    format_metric_table,
)

__all__ = [
    # metrics
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
    # splits
    "temporal_split",
    "temporal_split_by_ratio",
    # calibration
    "brier_score",
    "expected_calibration_error",
    "reliability_data",
    "calibration_map",
    # datasets
    "Dataset",
    "SAME_ACTOR",
    "DIFFERENT_ACTOR",
    "build_same_actor_dataset",
    "build_different_actor_dataset",
    "build_style_change_dataset",
    "build_cross_channel_dataset",
    "build_forwarded_control_dataset",
    "build_short_message_dataset",
    "build_long_message_dataset",
    "build_bot_dataset",
    # benchmarks
    "BenchmarkResult",
    "run_attribution_benchmark",
    "run_search_benchmark",
    "compare_versions",
    # reports
    "generate_benchmark_report",
    "generate_comparison_report",
    "format_metric_table",
]
