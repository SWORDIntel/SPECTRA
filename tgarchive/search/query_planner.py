"""
QueryPlanner — unified retrieval planner with Reciprocal Rank Fusion.
=====================================================================

The :class:`QueryPlanner` is the top-level entry point for SPECTRA's unified
search.  It determines which subsystems are relevant for a given query,
executes them in parallel (via :mod:`asyncio` with per-subsystem timeouts),
converts each subsystem's native result format into canonical
:class:`SearchCandidate` objects, and fuses the ranked lists using
Reciprocal Rank Fusion (RRF).

Subsystem adapters are implemented as private methods on the planner so that
the existing search-service files (``file_search.py``, ``hybrid_search.py``,
``semantic_search.py``) are **never modified** — they are only wrapped.

Supported subsystems
--------------------
* ``file_search``     — wraps :func:`tgarchive.services.file_search.search_files`
* ``hybrid_search``   — wraps :class:`tgarchive.search.hybrid_search.HybridSearchEngine`
* ``semantic_search`` — wraps :class:`tgarchive.ai.semantic_search.SemanticSearchEngine`

Graceful degradation
--------------------
If a subsystem is unavailable (missing dependency, missing database,
timeout, or raised exception) it is silently skipped and the remaining
subsystems still produce a fused result.  Per-subsystem errors are recorded
in the returned :class:`EvidenceBundle.errors`.

Usage
-----
::

    from tgarchive.search.query_planner import QueryPlanner

    planner = QueryPlanner(db_path="spectra.db")
    bundle = planner.plan("invoice.pdf", limit=20)
    for c in bundle.candidates:
        print(c.object_id, c.score, c.matched_by)
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from .evidence_bundle import EvidenceBundle
from .rank_fusion import DEFAULT_K, reciprocal_rank_fusion
from .search_candidate import SearchCandidate

logger = logging.getLogger(__name__)

# ── Subsystem registry ────────────────────────────────────────────────────

#: Canonical names of all subsystems the planner knows about.
ALL_SUBSYSTEMS: tuple[str, ...] = ("file_search", "hybrid_search", "semantic_search")

#: Sentinel meaning "query every available subsystem".
ALL: str = "all"

# Heuristics for query-type detection.
_FILE_EXTENSION_RE = re.compile(
    r"\.\w{2,5}$"  # ends with a short extension
)
_HASH_RE = re.compile(r"^[a-fA-F0-9]{8,64}$")  # MD5/SHA1/SHA256 (8-64 hex)


class QueryPlanner:
    """Unified retrieval planner that fuses multiple search subsystems via RRF.

    Args:
        db_path: Path to the SPECTRA SQLite database (used by the
            ``file_search`` adapter).  May be ``None`` if file search is not
            needed.
        db_connection: Optional open database connection / ``SpectraDB``
            instance for the ``hybrid_search`` adapter.  If ``None``, the
            hybrid adapter will try to open one from ``db_path``.
        hybrid_engine: Optional pre-built :class:`HybridSearchEngine`.  If
            ``None`` the planner constructs one lazily on first use (or
            skips the subsystem if construction fails).
        semantic_engine: Optional pre-built
            :class:`SemanticSearchEngine`.  If ``None`` the planner
            constructs one lazily on first use (or skips the subsystem if
            construction fails).
        default_timeout: Per-subsystem timeout in seconds.
        rrf_k: RRF damping constant (default ``60``).
    """

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        *,
        db_connection: Any = None,
        hybrid_engine: Any = None,
        semantic_engine: Any = None,
        default_timeout: float = 10.0,
        rrf_k: int = DEFAULT_K,
    ) -> None:
        self.db_path = Path(db_path) if db_path else None
        self._db_connection = db_connection
        self._hybrid_engine = hybrid_engine
        self._semantic_engine = semantic_engine
        self.default_timeout = float(default_timeout)
        self.rrf_k = int(rrf_k)

        # Lazily-initialized singletons.
        self._file_search_fn: Optional[Callable[..., Dict[str, Any]]] = None
        self._hybrid_ready: bool = hybrid_engine is not None
        self._semantic_ready: bool = semantic_engine is not None

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def plan(
        self,
        query: str,
        limit: int = 50,
        subsystems: Optional[Sequence[str] | str] = None,
    ) -> EvidenceBundle:
        """Execute a unified query plan and return a fused :class:`EvidenceBundle`.

        This is a synchronous wrapper around :meth:`plan_async`.

        Args:
            query: The user query string.
            limit: Maximum number of fused candidates to return.
            subsystems: Either the string ``"all"`` (default), or a list of
                subsystem names to query.  Unknown names are ignored.

        Returns:
            An :class:`EvidenceBundle` with fused, ranked candidates.
        """
        return asyncio.run(self.plan_async(query, limit=limit, subsystems=subsystems))

    async def plan_async(
        self,
        query: str,
        limit: int = 50,
        subsystems: Optional[Sequence[str] | str] = None,
    ) -> EvidenceBundle:
        """Asynchronous variant of :meth:`plan`.

        Subsystem searches are executed concurrently via
        :func:`asyncio.to_thread` with per-subsystem timeouts.  A subsystem
        that times out or raises is skipped (graceful degradation).
        """
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        if limit <= 0:
            raise ValueError("limit must be a positive integer")

        start = time.perf_counter()
        chosen = self._select_subsystems(query, subsystems)

        # Build (name, coroutine) pairs.
        tasks: Dict[str, asyncio.Task[List[SearchCandidate]]] = {}
        loop = asyncio.get_running_loop()
        # Request a larger pool from each subsystem so RRF has enough
        # candidates to fuse meaningfully and total_found reflects the
        # true hit count before truncation to ``limit``.
        pool = max(limit * 10, limit + 100)
        for name in chosen:
            adapter = self._adapter_for(name)
            if adapter is None:
                continue
            tasks[name] = loop.create_task(
                self._run_with_timeout(name, adapter, query, pool)
            )

        # Await all in parallel.
        per_subsystem: Dict[str, List[SearchCandidate]] = {}
        errors: List[Dict[str, Any]] = []
        if tasks:
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for (name, _task), result in zip(tasks.items(), results):
                if isinstance(result, BaseException):
                    errors.append(
                        {"subsystem": name, "error": f"{type(result).__name__}: {result}"}
                    )
                    logger.warning("Subsystem %s failed: %s", name, result)
                else:
                    per_subsystem[name] = result

        # Count distinct candidates before truncation.
        distinct_ids: set[str] = set()
        for cands in per_subsystem.values():
            for c in cands:
                distinct_ids.add(c.object_id)
        total_found = len(distinct_ids)

        # Fuse.
        fused = reciprocal_rank_fusion(per_subsystem, k=self.rrf_k, limit=limit)

        elapsed_ms = (time.perf_counter() - start) * 1000.0

        return EvidenceBundle(
            query=query,
            candidates=fused,
            total_found=total_found,
            fusion_method="rrf",
            subsystems_queried=list(per_subsystem.keys()),
            elapsed_ms=elapsed_ms,
            errors=errors,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Subsystem selection
    # ─────────────────────────────────────────────────────────────────────

    def _select_subsystems(
        self,
        query: str,
        subsystems: Optional[Sequence[str] | str],
    ) -> List[str]:
        """Determine which subsystems to query based on the request.

        If ``subsystems`` is ``None``, query-type heuristics pick the
        relevant set.  If ``subsystems`` is ``"all"``, every known
        subsystem is queried.  Otherwise the caller's explicit choice is
        honored (filtered to known names).
        """
        if subsystems is None:
            return self._infer_subsystems(query)
        if subsystems == ALL:
            return list(ALL_SUBSYSTEMS)

        if isinstance(subsystems, str):
            requested = [subsystems]
        else:
            requested = list(subsystems)

        chosen = [s for s in requested if s in ALL_SUBSYSTEMS]
        if not chosen:
            logger.warning(
                "No valid subsystems in %s; falling back to inference", requested
            )
            return self._infer_subsystems(query)
        return chosen

    def _infer_subsystems(self, query: str) -> List[str]:
        """Pick subsystems from the query's shape.

        * Filename-like (has a file extension) or hash-like → ``file_search``
          plus ``hybrid_search`` (which covers message/keyword search).
        * Otherwise (free text / entity name) → ``hybrid_search`` +
          ``semantic_search``.
        * When in doubt, query everything available.
        """
        q = query.strip()
        looks_like_file = bool(_FILE_EXTENSION_RE.search(q)) or bool(
            _HASH_RE.match(q)
        )
        if looks_like_file:
            return ["file_search", "hybrid_search"]
        return ["hybrid_search", "semantic_search"]

    # ─────────────────────────────────────────────────────────────────────
    # Adapter dispatch
    # ─────────────────────────────────────────────────────────────────────

    def _adapter_for(
        self, name: str
    ) -> Optional[Callable[[str, int], List[SearchCandidate]]]:
        """Return the sync adapter callable for a subsystem, or ``None``."""
        if name == "file_search":
            return self._adapter_file_search
        if name == "hybrid_search":
            return self._adapter_hybrid_search
        if name == "semantic_search":
            return self._adapter_semantic_search
        return None

    async def _run_with_timeout(
        self,
        name: str,
        adapter: Callable[[str, int], List[SearchCandidate]],
        query: str,
        limit: int,
    ) -> List[SearchCandidate]:
        """Run a sync adapter in a thread with a timeout."""
        return await asyncio.wait_for(
            asyncio.to_thread(adapter, query, limit),
            timeout=self.default_timeout,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Subsystem adapters (private)
    # ─────────────────────────────────────────────────────────────────────

    # ── file_search ──────────────────────────────────────────────────────

    def _ensure_file_search(self) -> bool:
        """Lazily import and bind the file-search function."""
        if self._file_search_fn is not None:
            return True
        if self.db_path is None or not self.db_path.exists():
            return False
        try:
            from ..services.file_search import search_files  # type: ignore

            self._file_search_fn = search_files
            return True
        except Exception as exc:  # pragma: no cover - import guard
            logger.debug("file_search unavailable: %s", exc)
            return False

    def _adapter_file_search(
        self, query: str, limit: int
    ) -> List[SearchCandidate]:
        """Wrap :func:`search_files` → ``List[SearchCandidate]``."""
        if not self._ensure_file_search():
            return []
        assert self._file_search_fn is not None
        try:
            raw = self._file_search_fn(
                str(self.db_path),
                query=query,
                limit=limit,
                scan_passwords=False,  # keep planner fast
            )
        except Exception as exc:
            logger.debug("file_search query failed: %s", exc)
            return []

        results = raw.get("results", []) if isinstance(raw, dict) else []
        candidates: List[SearchCandidate] = []
        for item in results:
            media_id = item.get("media_id")
            if media_id is None:
                continue
            match_type = item.get("match_type", "file_search")
            candidates.append(
                SearchCandidate(
                    object_id=f"media:{media_id}",
                    object_type="media",
                    score=float(item.get("match_score", 0.0)),
                    matched_by=[match_type],
                    sources=[item],
                    context=self._file_context(item),
                    provenance=[
                        {
                            "subsystem": "file_search",
                            "adapter": "_adapter_file_search",
                            "match_type": match_type,
                        }
                    ],
                )
            )
        # search_files already sorts by score desc; keep that order.
        return candidates

    @staticmethod
    def _file_context(item: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract context records (message/channel refs) from a file result."""
        ctx: List[Dict[str, Any]] = []
        for ref in item.get("message_refs", []) or []:
            ctx.append(
                {
                    "kind": "message_ref",
                    "message_id": ref.get("message_id"),
                    "user_id": ref.get("user_id"),
                    "date": ref.get("date"),
                    "content_preview": ref.get("content_preview"),
                }
            )
        for ref in item.get("channel_refs", []) or []:
            ctx.append({"kind": "channel_ref", "channel_id": ref.get("channel_id")})
        return ctx

    # ── hybrid_search ────────────────────────────────────────────────────

    def _ensure_hybrid_engine(self) -> bool:
        """Lazily build a :class:`HybridSearchEngine` if possible."""
        if self._hybrid_ready:
            return True
        if self._db_connection is None and self.db_path is None:
            return False
        try:
            from .hybrid_search import HybridSearchEngine  # type: ignore

            conn = self._db_connection
            if conn is None:
                # Open a lightweight connection for FTS5.
                from ..sqlite_runtime import connect_sqlite  # type: ignore

                conn = connect_sqlite(self.db_path)  # type: ignore[arg-type]
            self._hybrid_engine = HybridSearchEngine(conn, prebuild_vectors=False, warm_anchors=False)
            self._hybrid_ready = True
            return True
        except Exception as exc:  # pragma: no cover - heavy deps
            logger.debug("hybrid_search unavailable: %s", exc)
            return False

    def _adapter_hybrid_search(
        self, query: str, limit: int
    ) -> List[SearchCandidate]:
        """Wrap :class:`HybridSearchEngine.search` → ``List[SearchCandidate]``."""
        if not self._ensure_hybrid_engine():
            return []
        assert self._hybrid_engine is not None
        try:
            results = self._hybrid_engine.search(query, limit=limit)
        except Exception as exc:
            logger.debug("hybrid_search query failed: %s", exc)
            return []

        candidates: List[SearchCandidate] = []
        for res in results:
            msg_id = getattr(res, "message_id", None)
            if msg_id is None:
                continue
            score = float(getattr(res, "relevance_score", 0.0))
            match_type = getattr(res, "match_type", None)
            label = "hybrid"
            if match_type is not None:
                label = getattr(match_type, "value", str(match_type))
            meta = getattr(res, "metadata", {}) or {}
            candidates.append(
                SearchCandidate(
                    object_id=f"message:{msg_id}",
                    object_type="message",
                    score=max(0.0, min(1.0, score)),
                    matched_by=[label],
                    sources=[
                        {
                            "message_id": msg_id,
                            "channel_id": getattr(res, "channel_id", None),
                            "user_id": getattr(res, "user_id", None),
                            "content": getattr(res, "content", ""),
                            "relevance_score": score,
                            "metadata": meta,
                        }
                    ],
                    context=[
                        {
                            "kind": "channel",
                            "channel_id": getattr(res, "channel_id", None),
                        }
                    ],
                    provenance=[
                        {
                            "subsystem": "hybrid_search",
                            "adapter": "_adapter_hybrid_search",
                            "match_type": label,
                        }
                    ],
                )
            )
        # HybridSearchEngine.search already sorts by relevance desc.
        return candidates

    # ── semantic_search ──────────────────────────────────────────────────

    def _ensure_semantic_engine(self) -> bool:
        """Lazily build a :class:`SemanticSearchEngine` if possible."""
        if self._semantic_ready:
            return True
        try:
            from ..ai.semantic_search import SemanticSearchEngine  # type: ignore

            self._semantic_engine = SemanticSearchEngine()
            self._semantic_ready = True
            return True
        except Exception as exc:  # pragma: no cover - heavy deps
            logger.debug("semantic_search unavailable: %s", exc)
            return False

    def _adapter_semantic_search(
        self, query: str, limit: int
    ) -> List[SearchCandidate]:
        """Wrap :class:`SemanticSearchEngine.search` → ``List[SearchCandidate]``."""
        if not self._ensure_semantic_engine():
            return []
        assert self._semantic_engine is not None
        try:
            results = self._semantic_engine.search(query, top_k=limit)
        except Exception as exc:
            logger.debug("semantic_search query failed: %s", exc)
            return []

        candidates: List[SearchCandidate] = []
        for res in results:
            msg_id = getattr(res, "message_id", None)
            if msg_id is None or msg_id == 0:
                continue
            score = float(getattr(res, "score", 0.0))
            candidates.append(
                SearchCandidate(
                    object_id=f"message:{msg_id}",
                    object_type="message",
                    score=max(0.0, min(1.0, score)),
                    matched_by=["semantic"],
                    sources=[
                        {
                            "message_id": msg_id,
                            "channel_id": getattr(res, "channel_id", None),
                            "content": getattr(res, "content", ""),
                            "score": score,
                            "metadata": getattr(res, "metadata", {}) or {},
                        }
                    ],
                    context=[
                        {
                            "kind": "channel",
                            "channel_id": getattr(res, "channel_id", None),
                        }
                    ],
                    provenance=[
                        {
                            "subsystem": "semantic_search",
                            "adapter": "_adapter_semantic_search",
                        }
                    ],
                )
            )
        # Sort by score descending (SemanticSearchEngine may not pre-sort).
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates


__all__ = ["QueryPlanner", "ALL_SUBSYSTEMS", "ALL"]
