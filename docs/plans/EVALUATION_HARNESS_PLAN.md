# WP2: Evaluation / Forensic Ground-Truth Harness — Implementation Plan

## Structure
```
tgarchive/evaluation/
├── __init__.py
├── metrics.py        # Classification + ranking + attribution metrics
├── splits.py         # Time-separated train/val/test splits
├── datasets.py       # Benchmark dataset builders + loaders
├── benchmarks.py     # End-to-end benchmark runners
├── calibration.py    # Brier score, ECE, reliability diagrams
└── reports.py        # Human-readable benchmark reports
```

## metrics.py

### Classification metrics
- precision(y_true, y_pred, average='binary'|'macro'|'micro')
- recall(y_true, y_pred, average='binary'|'macro'|'micro')
- f1_score(y_true, y_pred, average='binary'|'macro'|'micro')
- roc_auc(y_true, y_scores)
- pr_auc(y_true, y_scores)
- confusion_matrix(y_true, y_pred)

### Ranking metrics
- mrr(relevant_docs, ranked_results)
- recall_at_k(relevant_docs, ranked_results, k)
- ndcg_at_k(relevant_scores, ranked_results, k)

### Attribution metrics
- top_k_accuracy(true_actors, predicted_actors, k=1|5)
- false_link_rate(true_pairs, predicted_pairs)
- false_split_rate(true_pairs, predicted_pairs)

All functions accept plain lists/arrays. No sklearn dependency required — implement from scratch using numpy only.

## splits.py

### Time-separated splits
- temporal_split(messages, train_end, val_end) → (train, val, test)
  - Messages before train_end → train
  - Messages between train_end and val_end → validation
  - Messages after val_end → test (holdout)
- temporal_split_by_ratio(messages, train_ratio=0.6, val_ratio=0.2) → (train, val, test)
  - Sort by date, split chronologically

**Critical:** Never random-split messages — adjacent messages leak style/topic/context.

## datasets.py

### Benchmark dataset builders
Each returns a Dataset object: {name, description, pairs: [(subject_a, subject_b, label, messages_a, messages_b)], metadata}

- build_same_actor_dataset(db) — known same-actor accounts
- build_different_actor_dataset(db) — known different actors with similar interests
- build_style_change_dataset(db) — same actor across time periods
- build_cross_channel_dataset(db) — same actor across channels
- build_forwarded_control_dataset(db) — forwarded/copied text controls
- build_bot_dataset(db) — bot-generated messages
- build_short_message_dataset(db) — short-message samples
- build_long_message_dataset(db) — long-message samples

### Label values
- SAME_ACTOR = 1, DIFFERENT_ACTOR = 0
- Labels come from analyst label store (WP7) or manual annotation

## calibration.py

- brier_score(y_true, y_prob)
- expected_calibration_error(y_true, y_prob, n_bins=10)
- reliability_data(y_true, y_prob, n_bins=10) → [(bin_lower, bin_upper, mean_confidence, mean_accuracy, count)]
- calibration_map(y_true, y_prob) → function that recalibrates probabilities

## benchmarks.py

- run_attribution_benchmark(engine, dataset) → BenchmarkResult
- run_search_benchmark(search_fn, queries, relevant_docs) → BenchmarkResult
- compare_versions(result_v1, result_v2) → ComparisonReport
- BenchmarkResult dataclass: {dataset_name, metrics: Dict, predictions: List, generated_at}

## reports.py

- generate_benchmark_report(results: List[BenchmarkResult]) → str (markdown)
- generate_comparison_report(comparison) → str (markdown)
- format_metric_table(results) → str (markdown table)
