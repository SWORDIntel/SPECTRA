"""
EvidenceBundle — top-level result container for the unified query planner.
=========================================================================

An ``EvidenceBundle`` is the final product of :class:`QueryPlanner.plan`.  It
bundles the fused, ranked :class:`SearchCandidate` list together with
metadata describing *how* the query was executed: which subsystems were
queried, what fusion method was applied, how many raw results were found,
and how long the whole operation took.

Schema (per QUERY_PLANNER_PLAN.md)::

    query:              str
    candidates:         List[SearchCandidate]
    total_found:        int
    fusion_method:      str      # "rrf"
    subsystems_queried: List[str]
    elapsed_ms:         float
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .search_candidate import SearchCandidate


@dataclass
class EvidenceBundle:
    """The complete, fused result of a unified query-plan execution.

    Attributes:
        query: The original user query string.
        candidates: Fused and ranked candidates (best first).  Each entry's
            ``score`` is the normalized RRF score in ``[0.0, 1.0]``.
        total_found: Total number of *distinct* candidates discovered across
            all subsystems *before* top-K truncation.  This may be larger
            than ``len(candidates)`` when ``limit`` was applied.
        fusion_method: Name of the fusion algorithm used (currently always
            ``"rrf"``).
        subsystems_queried: Names of the subsystems that were actually
            queried (and returned results).  Subsystems that were skipped
            due to unavailability or timeout are *not* listed here.
        elapsed_ms: Wall-clock elapsed time of the entire plan execution,
            in milliseconds.
        errors: Optional list of per-subsystem error/timeout records for
            diagnostics.  Each dict has ``subsystem`` and ``error`` keys.
    """

    query: str
    candidates: List[SearchCandidate] = field(default_factory=list)
    total_found: int = 0
    fusion_method: str = "rrf"
    subsystems_queried: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate invariants after construction."""
        if not self.query:
            raise ValueError("query must be a non-empty string")
        if self.total_found < 0:
            raise ValueError("total_found must be non-negative")
        if self.elapsed_ms < 0:
            raise ValueError("elapsed_ms must be non-negative")
        # total_found should be consistent with candidate count when no
        # truncation occurred, but we allow total_found >= len(candidates)
        # because the planner may truncate to ``limit``.
        if self.total_found < len(self.candidates):
            raise ValueError(
                "total_found must be >= len(candidates) "
                f"({self.total_found} < {len(self.candidates)})"
            )

    # ── convenience accessors ────────────────────────────────────────────

    @property
    def top_candidate(self) -> SearchCandidate | None:
        """Return the highest-scoring candidate, or ``None`` if empty."""
        return self.candidates[0] if self.candidates else None

    @property
    def is_empty(self) -> bool:
        """``True`` when no candidates were found."""
        return len(self.candidates) == 0

    def object_ids(self) -> List[str]:
        """Return the ``object_id`` of every candidate in ranked order."""
        return [c.object_id for c in self.candidates]

    def by_type(self, object_type: str) -> List[SearchCandidate]:
        """Filter candidates by ``object_type``."""
        return [c for c in self.candidates if c.object_type == object_type]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary (JSON-friendly)."""
        return {
            "query": self.query,
            "candidates": [c.to_dict() for c in self.candidates],
            "total_found": self.total_found,
            "fusion_method": self.fusion_method,
            "subsystems_queried": list(self.subsystems_queried),
            "elapsed_ms": self.elapsed_ms,
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceBundle":
        """Reconstruct an ``EvidenceBundle`` from a dictionary."""
        return cls(
            query=data["query"],
            candidates=[
                SearchCandidate.from_dict(c) for c in data.get("candidates", [])
            ],
            total_found=int(data.get("total_found", 0)),
            fusion_method=data.get("fusion_method", "rrf"),
            subsystems_queried=list(data.get("subsystems_queried", [])),
            elapsed_ms=float(data.get("elapsed_ms", 0.0)),
            errors=list(data.get("errors", [])),
        )


__all__ = ["EvidenceBundle"]
