"""
SearchCandidate — canonical candidate object for the unified query planner.
=========================================================================

A ``SearchCandidate`` represents a single retrievable object (media file,
message, person, channel, entity, or evidence record) discovered by one or
more search subsystems.  Each subsystem adapter converts its native result
format into a ``SearchCandidate`` so that the :mod:`rank_fusion` module can
fuse results from heterogeneous backends using Reciprocal Rank Fusion (RRF).

Schema (per QUERY_PLANNER_PLAN.md)::

    object_id:   str           # e.g. "media:123", "message:456", "user:789"
    object_type: str           # "media" | "message" | "person" | "channel"
                               #   | "entity" | "evidence"
    score:       float         # fused score 0-1
    matched_by:  List[str]     # ["filename_fuzzy", "semantic", "graph_1hop"]
    sources:     List[Dict]    # original source results from each subsystem
    context:     List[Dict]    # surrounding context (messages, channels, etc.)
    provenance:  List[Dict]    # chain of transformations
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


# Object-type vocabulary used across subsystems.
VALID_OBJECT_TYPES = frozenset(
    {"media", "message", "person", "channel", "entity", "evidence"}
)


@dataclass
class SearchCandidate:
    """A single retrievable object discovered by one or more search subsystems.

    Attributes:
        object_id: Stable, globally-unique identifier for the object,
            prefixed by type (e.g. ``"media:123"``, ``"message:456"``).
        object_type: One of ``media``, ``message``, ``person``, ``channel``,
            ``entity``, or ``evidence``.
        score: Fused relevance score in the range ``[0.0, 1.0]``.  Subsystem
            adapters populate this with the subsystem-native score; the RRF
            fusion step overwrites it with the normalized fused score.
        matched_by: Human-readable labels describing *how* each subsystem
            matched this candidate (e.g. ``"filename_fuzzy"``,
            ``"semantic"``, ``"graph_1hop"``).  Multiple labels indicate the
            candidate was surfaced by several subsystems.
        sources: Original, unmodified result dictionaries from each
            subsystem that returned this candidate.  Preserved for audit and
            debugging.
        context: Surrounding context records (nearby messages, channels,
            timestamps) that help an analyst interpret the candidate.
        provenance: Chain-of-transformations records documenting how the
            candidate was derived (adapter name, subsystem, timestamp).
    """

    object_id: str
    object_type: str
    score: float = 0.0
    matched_by: List[str] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    context: List[Dict[str, Any]] = field(default_factory=list)
    provenance: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate invariants after construction."""
        if not self.object_id:
            raise ValueError("object_id must be a non-empty string")
        if self.object_type not in VALID_OBJECT_TYPES:
            raise ValueError(
                f"object_type must be one of {sorted(VALID_OBJECT_TYPES)}, "
                f"got {self.object_type!r}"
            )
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(
                f"score must be in [0.0, 1.0], got {self.score}"
            )

    # ── convenience helpers ──────────────────────────────────────────────

    def add_source(self, source: Dict[str, Any]) -> None:
        """Append an original subsystem result to ``sources``."""
        self.sources.append(source)

    def add_context(self, ctx: Dict[str, Any]) -> None:
        """Append a surrounding-context record to ``context``."""
        self.context.append(ctx)

    def add_provenance(self, record: Dict[str, Any]) -> None:
        """Append a provenance/transform record to ``provenance``."""
        self.provenance.append(record)

    def merge_from(self, other: "SearchCandidate") -> "SearchCandidate":
        """Merge another candidate's metadata into this one (in-place).

        Used by RRF when the same ``object_id`` is surfaced by multiple
        subsystems.  ``matched_by``, ``sources``, ``context``, and
        ``provenance`` are extended (deduplicated for ``matched_by``); the
        ``score`` is left untouched (the fusion step assigns it).

        Args:
            other: Another candidate with the same ``object_id``.

        Returns:
            ``self`` (for chaining).
        """
        for label in other.matched_by:
            if label not in self.matched_by:
                self.matched_by.append(label)
        self.sources.extend(other.sources)
        self.context.extend(other.context)
        self.provenance.extend(other.provenance)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary (JSON-friendly)."""
        return {
            "object_id": self.object_id,
            "object_type": self.object_type,
            "score": self.score,
            "matched_by": list(self.matched_by),
            "sources": list(self.sources),
            "context": list(self.context),
            "provenance": list(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SearchCandidate":
        """Reconstruct a ``SearchCandidate`` from a dictionary."""
        return cls(
            object_id=data["object_id"],
            object_type=data["object_type"],
            score=float(data.get("score", 0.0)),
            matched_by=list(data.get("matched_by", [])),
            sources=list(data.get("sources", [])),
            context=list(data.get("context", [])),
            provenance=list(data.get("provenance", [])),
        )


__all__ = ["SearchCandidate", "VALID_OBJECT_TYPES"]
