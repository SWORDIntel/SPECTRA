"""
Reciprocal Rank Fusion (RRF) for the unified query planner.
==========================================================

RRF is a simple, parameter-light rank-fusion method that combines ranked
result lists from multiple search subsystems without needing score
calibration.  For each candidate that appears in a subsystem's ranked list
at position ``rank`` (1-based), it contributes::

    1 / (k + rank)

to that candidate's fused score.  The contributions are summed across all
subsystems and then normalized to ``[0.0, 1.0]`` so the top candidate has a
score of ``1.0``.

The standard RRF constant is ``k = 60``, which dampens the influence of
high-ranked (low-relevance) items and is robust across collections of
varying size.

Reference:
    Cormack, Clarke & Buettcher (2009), "Reciprocal Rank Fusion outperforms
    Condorcet and individual rank learning methods", SIGIR '09.
"""
from __future__ import annotations

from typing import Dict, List

from .search_candidate import SearchCandidate

# Standard RRF damping constant.
DEFAULT_K: int = 60


def reciprocal_rank_fusion(
    results: Dict[str, List[SearchCandidate]],
    k: int = DEFAULT_K,
    limit: int = 50,
) -> List[SearchCandidate]:
    """Fuse ranked results from multiple subsystems using RRF.

    Args:
        results: Mapping of ``subsystem_name`` → ranked list of
            :class:`SearchCandidate` objects.  Each list **must** be in
            descending order of subsystem-native relevance (rank 1 = best).
            The candidates' ``object_id`` is used as the merge key; their
            ``object_type`` is taken from the first occurrence.
        k: RRF damping constant (default ``60``).  Larger values flatten
            the rank curve, reducing the advantage of top ranks.
        limit: Maximum number of fused candidates to return (top-K).

    Returns:
        A new list of :class:`SearchCandidate` objects sorted by fused
        score descending, truncated to ``limit``.  Each candidate's
        ``score`` is the normalized RRF score in ``[0.0, 1.0]``, and its
        ``matched_by``, ``sources``, ``context``, and ``provenance`` lists
        are the union of all subsystems that surfaced it.

    Notes:
        - The input candidates are **not** mutated; fresh merged candidates
          are returned.
        - When ``results`` is empty, an empty list is returned.
        - Normalization divides every fused score by the maximum fused
          score, so the top candidate always receives ``1.0``.
    """
    if k <= 0:
        raise ValueError(f"k must be a positive integer, got {k}")
    if limit <= 0:
        raise ValueError(f"limit must be a positive integer, got {limit}")

    if not results:
        return []

    # Accumulators keyed by object_id.
    fused_scores: Dict[str, float] = {}
    merged: Dict[str, SearchCandidate] = {}

    for subsystem_name, ranked in results.items():
        if not ranked:
            continue
        for rank, candidate in enumerate(ranked, start=1):
            oid = candidate.object_id
            rrf_score = 1.0 / (k + rank)
            fused_scores[oid] = fused_scores.get(oid, 0.0) + rrf_score

            if oid not in merged:
                # First sighting — clone so we don't mutate the input.
                merged[oid] = SearchCandidate(
                    object_id=candidate.object_id,
                    object_type=candidate.object_type,
                    score=0.0,  # assigned after normalization
                    matched_by=list(candidate.matched_by),
                    sources=list(candidate.sources),
                    context=list(candidate.context),
                    provenance=list(candidate.provenance),
                )
            else:
                # Subsequent sighting — merge metadata (dedup matched_by).
                merged[oid].merge_from(candidate)

    if not fused_scores:
        return []

    # Normalize to [0, 1] so the best candidate scores 1.0.
    max_score = max(fused_scores.values())
    if max_score <= 0:
        max_score = 1.0

    for oid, raw in fused_scores.items():
        merged[oid].score = raw / max_score

    ranked_final = sorted(
        merged.values(), key=lambda c: c.score, reverse=True
    )
    return ranked_final[:limit]


# Convenience alias matching the plan's naming.
rrf = reciprocal_rank_fusion


__all__ = ["reciprocal_rank_fusion", "rrf", "DEFAULT_K"]
