"""
Swarm Coordinator — Distributed work distribution across SPECTRA nodes
======================================================================

Implements Step 5 of the QIHSE RESP + MSNET Swarming Integration Plan.

A :class:`SwarmCoordinator` manages node identity, swarm membership, work
distribution, work stealing, and result aggregation for distributed file
search (and other tasks) across multiple SPECTRA nodes on a trusted LAN.

All coordination state lives in the QIHSE KV store (via a
``CoordinationBackend`` instance from
:mod:`tgarchive.services.async_file_search`).  The backend exposes a
RESP-compatible interface (``get``, ``set``, ``claim``, ``delete``,
``close``) that works against QIHSE RESP, Redis, or the SQLite fallback.

KV layout
---------

::

    spectra:swarm:nodes              JSON list of registered node IDs
    spectra:swarm:node:<id>          JSON node info (TTL = node_timeout)
    spectra:swarm:claims             JSON list of active claim item IDs
    spectra:swarm:claim:<item_id>    node_id of claimer (TTL = claim_ttl)
    spectra:swarm:result:<item_id>   JSON result dict

Single-node fallback
--------------------

If no peers are discovered (only this node in the swarm), all work is
performed locally — :meth:`distribute_work` assigns every item to the
local node.
"""

from __future__ import annotations

import json
import logging
import platform
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── KV key helpers ──────────────────────────────────────────────────────────

_NODES_KEY = "spectra:swarm:nodes"
_CLAIMS_KEY = "spectra:swarm:claims"

def _node_key(node_id: str) -> str:
    return f"spectra:swarm:node:{node_id}"

def _claim_key(item_id: str) -> str:
    return f"spectra:swarm:claim:{item_id}"

def _result_key(item_id: str) -> str:
    return f"spectra:swarm:result:{item_id}"


class SwarmCoordinator:
    """Coordinates distributed work across SPECTRA swarm nodes.

    Parameters
    ----------
    node_id:
        Unique node identifier.  Auto-generated as ``hostname-<uuid4hex[:8]>``
        when not provided.
    coord_backend:
        A :class:`CoordinationBackend` instance (QIHSE/Redis/SQLite) from
        :mod:`tgarchive.services.async_file_search`.  All KV operations go
        through this backend.
    heartbeat_interval:
        Seconds between heartbeat updates (default 30).
    node_timeout:
        Seconds after which a node with no heartbeat is considered stale
        and evicted (default 90).
    claim_ttl:
        Default TTL in seconds for work-item claims (default 600 = 10 min).
    """

    def __init__(
        self,
        node_id: Optional[str] = None,
        coord_backend: Any = None,
        heartbeat_interval: int = 30,
        node_timeout: int = 90,
        claim_ttl: int = 600,
    ) -> None:
        if coord_backend is None:
            raise ValueError("coord_backend is required (CoordinationBackend instance)")
        self.coord = coord_backend
        self.heartbeat_interval = heartbeat_interval
        self.node_timeout = node_timeout
        self.claim_ttl = claim_ttl

        # Node identity — hostname + UUID, persisted
        if node_id:
            self.node_id = node_id
        else:
            host = platform.node().split(".")[0] or "node"
            self.node_id = f"{host}-{uuid.uuid4().hex[:8]}"

        self._capabilities: Dict[str, Any] = {}
        self._address: str = ""
        self._sessions: int = 0

        # Heartbeat thread state
        self._hb_thread: Optional[threading.Thread] = None
        self._hb_stop = threading.Event()
        self._started = False
        self._lock = threading.Lock()

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    def start(self, capabilities: Optional[Dict[str, Any]] = None) -> None:
        """Register this node in the swarm and start the heartbeat thread."""
        if self._started:
            return
        self.register_node(capabilities or {})
        self._hb_stop.clear()
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"swarm-hb-{self.node_id}",
            daemon=True,
        )
        self._hb_thread.start()
        self._started = True
        logger.info("SwarmCoordinator started for node %s", self.node_id)

    def stop(self) -> None:
        """Stop the heartbeat thread and deregister from the swarm."""
        if not self._started:
            return
        self._hb_stop.set()
        if self._hb_thread is not None:
            self._hb_thread.join(timeout=self.heartbeat_interval + 5)
            self._hb_thread = None
        self._started = False
        self.deregister_node()
        logger.info("SwarmCoordinator stopped for node %s", self.node_id)

    # ─── Node registration ──────────────────────────────────────────────────

    def register_node(self, capabilities: Dict[str, Any]) -> None:
        """Write this node's info to the swarm registry in QIHSE KV."""
        self._capabilities = capabilities or {}
        self._address = capabilities.get("address", "")
        self._sessions = int(capabilities.get("sessions", 0))

        node_info = self._build_node_info()
        self._write_node_info(node_info)
        self._add_to_nodes_registry(self.node_id)
        logger.debug("Registered node %s in swarm", self.node_id)

    def deregister_node(self) -> None:
        """Remove this node from the swarm registry."""
        self._remove_from_nodes_registry(self.node_id)
        self.coord.delete(_node_key(self.node_id))
        logger.debug("Deregistered node %s from swarm", self.node_id)

    def _build_node_info(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "address": self._address,
            "capabilities": self._capabilities,
            "sessions": self._sessions,
            "last_heartbeat": time.time(),
        }

    def _write_node_info(self, node_info: Dict[str, Any]) -> None:
        """Persist node info with a TTL so stale nodes auto-expire."""
        ttl_ms = self.node_timeout * 1000
        self.coord.set(_node_key(self.node_id), json.dumps(node_info), ttl_ms=ttl_ms)

    def _add_to_nodes_registry(self, node_id: str) -> None:
        with self._lock:
            raw = self.coord.get(_NODES_KEY)
            nodes: List[str] = []
            if raw:
                try:
                    nodes = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    nodes = []
            if node_id not in nodes:
                nodes.append(node_id)
            self.coord.set(_NODES_KEY, json.dumps(nodes))

    def _remove_from_nodes_registry(self, node_id: str) -> None:
        with self._lock:
            raw = self.coord.get(_NODES_KEY)
            nodes: List[str] = []
            if raw:
                try:
                    nodes = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    nodes = []
            if node_id in nodes:
                nodes.remove(node_id)
                self.coord.set(_NODES_KEY, json.dumps(nodes))

    # ─── Swarm membership ───────────────────────────────────────────────────

    def get_swarm_nodes(self) -> List[Dict[str, Any]]:
        """Return a list of all active node info dicts from the KV store."""
        raw = self.coord.get(_NODES_KEY)
        if not raw:
            return []
        try:
            node_ids = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

        nodes: List[Dict[str, Any]] = []
        for nid in node_ids:
            info_raw = self.coord.get(_node_key(nid))
            if not info_raw:
                # Entry expired — skip (will be cleaned up by eviction)
                continue
            try:
                info = json.loads(info_raw)
            except (json.JSONDecodeError, TypeError):
                continue
            nodes.append(info)
        return nodes

    def _evict_stale_nodes(self) -> None:
        """Remove nodes whose heartbeat is older than ``node_timeout``."""
        now = time.time()
        raw = self.coord.get(_NODES_KEY)
        if not raw:
            return
        try:
            node_ids = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return

        stale: List[str] = []
        for nid in node_ids:
            info_raw = self.coord.get(_node_key(nid))
            if not info_raw:
                # KV entry already expired (TTL) — node is stale
                stale.append(nid)
                continue
            try:
                info = json.loads(info_raw)
            except (json.JSONDecodeError, TypeError):
                stale.append(nid)
                continue
            last_hb = info.get("last_heartbeat", 0)
            if now - last_hb > self.node_timeout:
                stale.append(nid)

        for nid in stale:
            logger.info("Evicting stale swarm node %s", nid)
            self._remove_from_nodes_registry(nid)
            self.coord.delete(_node_key(nid))

    # ─── Work distribution ──────────────────────────────────────────────────

    def distribute_work(
        self,
        items: List[Any],
        weight_key: str = "sessions",
    ) -> Dict[str, List[Any]]:
        """Split *items* across swarm nodes weighted by session count.

        Each node receives a share proportional to its ``weight_key`` value
        (default ``sessions``).  Returns a mapping of ``node_id ->
        assigned_items``.

        If no peers are discovered, all items are assigned to this node
        (single-node fallback).
        """
        if not items:
            return {}

        nodes = self.get_swarm_nodes()
        if not nodes:
            # Total failure — assign everything to self
            return {self.node_id: list(items)}

        # Only include this node if no peers (single-node fallback)
        peer_nodes = [n for n in nodes if n.get("node_id") != self.node_id]
        if not peer_nodes:
            # No peers — do everything locally
            return {self.node_id: list(items)}

        # Include self in the distribution
        all_nodes = nodes
        weights = []
        for n in all_nodes:
            w = self._node_weight(n, weight_key)
            weights.append(max(w, 1))  # floor of 1 so every node gets something

        total_weight = sum(weights)
        if total_weight == 0:
            # Degenerate — equal split
            weights = [1] * len(all_nodes)
            total_weight = len(all_nodes)

        assignment: Dict[str, List[Any]] = {n["node_id"]: [] for n in all_nodes}
        node_ids = [n["node_id"] for n in all_nodes]

        # Proportional allocation with remainder distributed to highest-weight nodes
        n_items = len(items)
        quotas = [int(n_items * w / total_weight) for w in weights]
        assigned = sum(quotas)
        remainder = n_items - assigned

        # Distribute remainder to nodes with the largest fractional parts
        if remainder > 0:
            fractions = [
                (n_items * w / total_weight) - q
                for w, q in zip(weights, quotas)
            ]
            order = sorted(range(len(all_nodes)), key=lambda i: fractions[i], reverse=True)
            for i in range(remainder):
                quotas[order[i % len(order)]] += 1

        # Assign items in order
        idx = 0
        for i, nid in enumerate(node_ids):
            count = quotas[i]
            assignment[nid] = items[idx: idx + count]
            idx += count

        # Safety: if rounding left any items unassigned, give them to self
        if idx < n_items:
            assignment.setdefault(self.node_id, [])
            assignment[self.node_id].extend(items[idx:])

        logger.debug(
            "Distributed %d items across %d nodes: %s",
            n_items,
            len(all_nodes),
            {nid: len(v) for nid, v in assignment.items()},
        )
        return assignment

    @staticmethod
    def _node_weight(node: Dict[str, Any], weight_key: str) -> float:
        """Extract a numeric weight from a node info dict."""
        # Try top-level first (e.g. "sessions"), then capabilities
        val = node.get(weight_key)
        if val is None:
            caps = node.get("capabilities", {})
            val = caps.get(weight_key, 0)
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    # ─── Work claiming & stealing ───────────────────────────────────────────

    def claim_work(self, item_id: str, ttl: int = 600) -> bool:
        """Atomically claim a work item via SETNX in the KV store.

        Returns ``True`` if this node successfully claimed *item_id*.
        """
        ttl = ttl if ttl > 0 else self.claim_ttl
        ttl_ms = ttl * 1000
        claim_k = _claim_key(item_id)
        ok = self.coord.claim(claim_k, self.node_id, ttl_ms=ttl_ms)
        if ok:
            self._register_claim(item_id)
            logger.debug("Node %s claimed item %s", self.node_id, item_id)
        return ok

    def release_claim(self, item_id: str) -> None:
        """Release a previously held claim on *item_id*."""
        self.coord.delete(_claim_key(item_id))
        self._unregister_claim(item_id)
        logger.debug("Node %s released claim on item %s", self.node_id, item_id)

    def steal_expired_claims(self) -> List[str]:
        """Find claims whose TTL has expired and re-claim them for this node.

        Returns a list of item IDs that were successfully stolen.
        """
        stolen: List[str] = []
        raw = self.coord.get(_CLAIMS_KEY)
        if not raw:
            return stolen
        try:
            claim_ids = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return stolen

        still_active: List[str] = []
        for item_id in claim_ids:
            claim_val = self.coord.get(_claim_key(item_id))
            if claim_val is None:
                # Claim expired — try to steal it
                if self.claim_work(item_id, ttl=self.claim_ttl):
                    stolen.append(item_id)
                    still_active.append(item_id)
            else:
                still_active.append(item_id)

        # Compact the claims registry
        self.coord.set(_CLAIMS_KEY, json.dumps(still_active))
        if stolen:
            logger.info("Node %s stole %d expired claims: %s", self.node_id, len(stolen), stolen)
        return stolen

    def _register_claim(self, item_id: str) -> None:
        with self._lock:
            raw = self.coord.get(_CLAIMS_KEY)
            claims: List[str] = []
            if raw:
                try:
                    claims = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    claims = []
            if item_id not in claims:
                claims.append(item_id)
                self.coord.set(_CLAIMS_KEY, json.dumps(claims))

    def _unregister_claim(self, item_id: str) -> None:
        with self._lock:
            raw = self.coord.get(_CLAIMS_KEY)
            claims: List[str] = []
            if raw:
                try:
                    claims = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    claims = []
            if item_id in claims:
                claims.remove(item_id)
                self.coord.set(_CLAIMS_KEY, json.dumps(claims))

    # ─── Result aggregation ─────────────────────────────────────────────────

    def report_result(self, item_id: str, result: dict) -> None:
        """Store a result for *item_id* in the KV store."""
        payload = json.dumps(result)
        # Results persist for 1 hour by default
        self.coord.set(_result_key(item_id), payload, ttl_ms=3600 * 1000)
        logger.debug("Node %s reported result for item %s", self.node_id, item_id)

    def get_results(self, item_ids: List[str]) -> Dict[str, dict]:
        """Fetch results for a list of item IDs from the KV store."""
        results: Dict[str, dict] = {}
        for item_id in item_ids:
            raw = self.coord.get(_result_key(item_id))
            if not raw:
                continue
            try:
                results[item_id] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupt result for item %s", item_id)
        return results

    # ─── Heartbeat ──────────────────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        """Background thread: update heartbeat, evict stale nodes, steal claims."""
        while not self._hb_stop.is_set():
            try:
                # Refresh this node's heartbeat + TTL
                node_info = self._build_node_info()
                self._write_node_info(node_info)

                # Evict stale peers
                self._evict_stale_nodes()

                # Attempt to steal expired work claims
                self.steal_expired_claims()
            except Exception:
                logger.exception("Heartbeat loop error for node %s", self.node_id)

            # Wait for the interval, but respond promptly to stop()
            self._hb_stop.wait(self.heartbeat_interval)

    # ─── Convenience ────────────────────────────────────────────────────────

    def is_single_node(self) -> bool:
        """Return True if this is the only active node in the swarm."""
        nodes = self.get_swarm_nodes()
        peers = [n for n in nodes if n.get("node_id") != self.node_id]
        return len(peers) == 0

    def close(self) -> None:
        """Stop the coordinator and close the backend."""
        self.stop()
        try:
            self.coord.close()
        except Exception:
            pass
