"""
SPECTRA — Advanced Account Rotation Strategies
================================================

Six additional rotation strategies beyond the existing sequential/random/
weighted/smart modes, plus a channel de-duplication guard that prevents
multiple accounts from working the same channel concurrently.

Strategies implemented here:
  1. **floodwait_adaptive** — Parse FloodWaitError seconds and set precise
     per-account cooldowns. Accounts auto-recover when the cooldown expires.
  2. **circuit_breaker** — Track consecutive failures per account. After
     ``failure_threshold`` consecutive failures, the account is quarantined
     for ``quarantine_minutes``. A probe request must succeed before the
     account re-enters the pool.
  3. **latency** — Track round-trip time (RTT) per account and prefer the
     fastest responder. Useful when accounts route through different proxies.
  4. **sticky** — Pin specific accounts to specific target channels. A
     channel always sees the same user_id — an OPSEC requirement.
  5. **sharded** — Divide the work list into N shards, assign one account
     per shard. No overlap, maximum parallelism, clean audit trail.
  6. **primary_fallback** — One account is primary; others only activate
     when the primary hits a rate limit or fails. Minimises account
     footprint.

Channel de-duplication:
  ``ChannelDeduplicator`` tracks which channels are currently being worked
  by which account. ``acquire(channel)`` blocks until the channel is free
  (or returns False if ``timeout`` elapses). ``release(channel)`` frees it.
  This prevents two accounts from archiving the same channel simultaneously.

All strategies are designed as drop-in replacements for the existing
``AccountRotator.get_next_account()`` method and share the same SQLite
persistence layer.
"""
from __future__ import annotations

# ── Standard Library ──────────────────────────────────────────────────────
import asyncio
import logging
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)
TZ = timezone.utc


# ──────────────────────────────────────────────────────────────────────────
#  FloodWait-Adaptive
# ──────────────────────────────────────────────────────────────────────────
class FloodWaitTracker:
    """
    Tracks per-account FloodWait cooldowns extracted from real Telegram
    ``FloodWaitError`` responses.

    When ``record_flood_wait(session_name, seconds)`` is called, the account
    is marked unavailable until ``now + seconds``. ``is_available()`` checks
    the cooldown. Cooldowns auto-expire — no manual intervention needed.
    """

    def __init__(self) -> None:
        self._cooldowns: Dict[str, datetime] = {}

    def record_flood_wait(self, session_name: str, seconds: int) -> None:
        """Record a FloodWait event for an account."""
        cooldown_until = datetime.now(TZ) + timedelta(seconds=max(seconds, 1))
        self._cooldowns[session_name] = cooldown_until
        logger.warning(
            "FloodWait: account %s cooldown for %ss (until %s)",
            session_name, seconds, cooldown_until.isoformat(),
        )

    def is_available(self, session_name: str) -> bool:
        """Check if an account is past its FloodWait cooldown."""
        until = self._cooldowns.get(session_name)
        if until is None:
            return True
        if datetime.now(TZ) >= until:
            del self._cooldowns[session_name]
            logger.info("FloodWait expired for %s — back in pool", session_name)
            return True
        return False

    def remaining(self, session_name: str) -> int:
        """Seconds remaining in cooldown (0 if expired/none)."""
        until = self._cooldowns.get(session_name)
        if until is None:
            return 0
        delta = (until - datetime.now(TZ)).total_seconds()
        return max(int(delta), 0)

    def clear(self, session_name: Optional[str] = None) -> None:
        if session_name:
            self._cooldowns.pop(session_name, None)
        else:
            self._cooldowns.clear()


# ──────────────────────────────────────────────────────────────────────────
#  Circuit Breaker
# ──────────────────────────────────────────────────────────────────────────
class CircuitBreaker:
    """
    Per-account circuit breaker with automatic recovery probing.

    States per account:
      - **closed**   — healthy, available for selection
      - **open**     — quarantined after ``failure_threshold`` consecutive
                       failures. Stays open for ``quarantine_minutes``.
      - **half_open** — quarantine expired; a single probe request must
                        succeed before the account returns to **closed**.
                        If the probe fails, the account goes back to **open**.

    Usage:
        cb.record_failure("session_1")
        cb.record_success("session_1")
        cb.is_available("session_1")  # False if open
        cb.is_probe("session_1")      # True if half_open (caller should
                                      #  send a test request)
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 3,
        quarantine_minutes: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.quarantine_td = timedelta(minutes=quarantine_minutes)
        self._state: Dict[str, str] = defaultdict(lambda: self.CLOSED)
        self._consecutive_failures: Dict[str, int] = defaultdict(int)
        self._quarantine_until: Dict[str, datetime] = {}

    def record_failure(self, session_name: str, error: str = "") -> None:
        self._consecutive_failures[session_name] += 1
        n = self._consecutive_failures[session_name]

        if self._state[session_name] == self.HALF_OPEN:
            # Probe failed — back to open
            self._open(session_name)
            logger.warning(
                "Circuit breaker: %s probe FAILED (%s) — back to OPEN", session_name, error
            )
        elif n >= self.failure_threshold:
            self._open(session_name)
            logger.warning(
                "Circuit breaker: %s OPENED after %d consecutive failures (last: %s)",
                session_name, n, error,
            )
        else:
            logger.info(
                "Circuit breaker: %s failure %d/%d (%s)",
                session_name, n, self.failure_threshold, error,
            )

    def record_success(self, session_name: str) -> None:
        was_open = self._state[session_name] in (self.OPEN, self.HALF_OPEN)
        self._consecutive_failures[session_name] = 0
        self._state[session_name] = self.CLOSED
        self._quarantine_until.pop(session_name, None)
        if was_open:
            logger.info("Circuit breaker: %s CLOSED (recovered)", session_name)

    def is_available(self, session_name: str) -> bool:
        state = self._state[session_name]
        if state == self.CLOSED:
            return True
        if state == self.OPEN:
            # Check if quarantine has expired → transition to half_open
            until = self._quarantine_until.get(session_name)
            if until and datetime.now(TZ) >= until:
                self._state[session_name] = self.HALF_OPEN
                logger.info("Circuit breaker: %s → HALF_OPEN (probe required)", session_name)
                return True  # available for a probe
            return False
        if state == self.HALF_OPEN:
            return True  # available for a probe
        return False

    def is_probe(self, session_name: str) -> bool:
        return self._state[session_name] == self.HALF_OPEN

    def state(self, session_name: str) -> str:
        return self._state[session_name]

    def _open(self, session_name: str) -> None:
        self._state[session_name] = self.OPEN
        self._quarantine_until[session_name] = datetime.now(TZ) + self.quarantine_td

    def reset(self, session_name: Optional[str] = None) -> None:
        if session_name:
            self._state[session_name] = self.CLOSED
            self._consecutive_failures[session_name] = 0
            self._quarantine_until.pop(session_name, None)
        else:
            self._state.clear()
            self._consecutive_failures.clear()
            self._quarantine_until.clear()


# ──────────────────────────────────────────────────────────────────────────
#  Latency Tracker
# ──────────────────────────────────────────────────────────────────────────
class LatencyTracker:
    """
    Tracks rolling average round-trip time (RTT) per account in milliseconds.
    Used by the ``latency`` rotation strategy to prefer the fastest responder.

    Usage:
        lt.record(session_name, rtt_ms=120)
        lt.avg_latency(session_name)  # → 120.0
    """

    def __init__(self, window_size: int = 20) -> None:
        self.window_size = window_size
        self._samples: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))

    def record(self, session_name: str, rtt_ms: float) -> None:
        self._samples[session_name].append(rtt_ms)

    def avg_latency(self, session_name: str) -> float:
        samples = self._samples.get(session_name)
        if not samples:
            return float("inf")
        return sum(samples) / len(samples)

    def best_account(self, session_names: List[str]) -> Optional[str]:
        """Return the session_name with the lowest average latency."""
        if not session_names:
            return None
        return min(session_names, key=lambda s: self.avg_latency(s))

    def stats(self) -> Dict[str, float]:
        return {s: self.avg_latency(s) for s in self._samples}


# ──────────────────────────────────────────────────────────────────────────
#  Sticky / Affinity Mapper
# ──────────────────────────────────────────────────────────────────────────
class StickyAffinityMapper:
    """
    Pins specific accounts to specific target channels so a channel always
    sees the same user_id — an OPSEC requirement.

    Mapping can be configured explicitly (channel → session_name) or
    auto-assigned on first access (first account to touch a channel owns it).

    Usage:
        sam.assign("@target_channel", "spectra_tdata_8011484242_1")
        owner = sam.get_owner("@target_channel")  # → session_name or None
        owner = sam.get_or_assign("@target_channel", available_accounts)
    """

    def __init__(self, affinity_map: Optional[Dict[str, str]] = None) -> None:
        self._channel_to_account: Dict[str, str] = dict(affinity_map or {})

    def assign(self, channel: str, session_name: str) -> None:
        self._channel_to_account[channel] = session_name
        logger.info("Sticky affinity: %s → %s", channel, session_name)

    def get_owner(self, channel: str) -> Optional[str]:
        return self._channel_to_account.get(channel)

    def get_or_assign(
        self, channel: str, available_sessions: List[str]
    ) -> Optional[str]:
        """Return the pinned account for a channel, or auto-assign one."""
        owner = self._channel_to_account.get(channel)
        if owner and owner in available_sessions:
            return owner
        if not available_sessions:
            return None
        # Auto-assign: pick the least-assigned account for load balancing
        counts: Dict[str, int] = defaultdict(int)
        for acc in self._channel_to_account.values():
            counts[acc] += 1
        chosen = min(available_sessions, key=lambda s: counts[s])
        self.assign(channel, chosen)
        return chosen

    def mapping(self) -> Dict[str, str]:
        return dict(self._channel_to_account)


# ──────────────────────────────────────────────────────────────────────────
#  Sharded / Partitioned
# ──────────────────────────────────────────────────────────────────────────
class ShardAssigner:
    """
    Divides a work list into N shards and assigns one account per shard.
    No overlap, maximum parallelism, clean audit trail.

    Usage:
        sa = ShardAssigner(accounts, num_shards=len(accounts))
        shard = sa.get_shard_for_account("session_1")  # → 0
        account = sa.get_account_for_item("channel_xyz")  # → session_name
    """

    def __init__(self, accounts: List[Dict[str, Any]], num_shards: Optional[int] = None) -> None:
        self.accounts = accounts
        self.num_shards = num_shards or len(accounts)
        self._shard_map: Dict[int, str] = {}  # shard_idx → session_name
        self._assign_shards()

    def _assign_shards(self) -> None:
        for i, acc in enumerate(self.accounts):
            shard_idx = i % self.num_shards
            session = acc.get("session_name", f"account_{i}")
            self._shard_map[shard_idx] = session

    def get_shard_for_account(self, session_name: str) -> Optional[int]:
        for shard, session in self._shard_map.items():
            if session == session_name:
                return shard
        return None

    def get_account_for_shard(self, shard_idx: int) -> Optional[str]:
        return self._shard_map.get(shard_idx)

    def get_account_for_item(self, item_key: str) -> Optional[str]:
        """Deterministically hash an item (channel name/URL) to a shard."""
        shard_idx = hash(item_key) % self.num_shards
        return self.get_account_for_shard(shard_idx)

    def get_shard_items(self, shard_idx: int, items: List[str]) -> List[str]:
        """Return only the items that belong to a given shard."""
        return [item for item in items if hash(item) % self.num_shards == shard_idx]

    def all_shards(self) -> Dict[int, str]:
        return dict(self._shard_map)


# ──────────────────────────────────────────────────────────────────────────
#  Primary + Fallback
# ──────────────────────────────────────────────────────────────────────────
class PrimaryFallbackSelector:
    """
    One account is primary; others only activate when the primary is
    unavailable (rate-limited, banned, or in cooldown). Minimises account
    footprint — useful when you want to concentrate activity on one identity.

    Usage:
        pfs = PrimaryFallbackSelector(accounts, primary_session="session_1")
        selected = pfs.select(is_available_fn)  # → primary if available, else fallback
    """

    def __init__(
        self,
        accounts: List[Dict[str, Any]],
        primary_session: Optional[str] = None,
    ) -> None:
        self.accounts = accounts
        self.primary = primary_session or (
            accounts[0].get("session_name") if accounts else None
        )
        self._fallback_order = [
            acc.get("session_name") for acc in accounts
            if acc.get("session_name") != self.primary
        ]
        self._fallback_idx = 0

    def select(
        self,
        is_available_fn: callable,
    ) -> Optional[Dict[str, Any]]:
        """
        Select the primary if available, otherwise rotate through fallbacks.

        Args:
            is_available_fn: callable(session_name) -> bool
        """
        # Try primary first
        if self.primary and is_available_fn(self.primary):
            return next(
                (acc for acc in self.accounts if acc.get("session_name") == self.primary),
                None,
            )

        # Rotate through fallbacks
        for _ in range(len(self._fallback_order)):
            session = self._fallback_order[self._fallback_idx % len(self._fallback_order)]
            self._fallback_idx += 1
            if is_available_fn(session):
                logger.info("Primary %s unavailable — using fallback %s", self.primary, session)
                return next(
                    (acc for acc in self.accounts if acc.get("session_name") == session),
                    None,
                )

        logger.error("Primary and all fallbacks unavailable")
        return None

    def set_primary(self, session_name: str) -> None:
        self.primary = session_name
        self._fallback_order = [
            acc.get("session_name") for acc in self.accounts
            if acc.get("session_name") != session_name
        ]
        self._fallback_idx = 0


# ──────────────────────────────────────────────────────────────────────────
#  Channel De-Duplication
# ──────────────────────────────────────────────────────────────────────────
class ChannelDeduplicator:
    """
    Prevents multiple accounts from working the same channel concurrently.

    ``acquire(channel, session_name)`` claims a channel. If another account
    already holds it, returns False (or waits if ``timeout`` is set).
    ``release(channel)`` frees it. ``is_locked(channel)`` checks status.

    Also integrates with the DB ``discovered_groups`` table to skip channels
    that have already been archived (status = 'archived').

    Usage:
        dd = ChannelDeduplicator()
        if dd.acquire("@target_channel", "session_1"):
            try:
                await archive_channel(...)
            finally:
                dd.release("@target_channel")
        else:
            logger.info("Channel @target_channel already in progress")
    """

    def __init__(
        self,
        archived_channels: Optional[Set[str]] = None,
        lock_timeout: float = 3600.0,
    ) -> None:
        # channel → (session_name, acquire_timestamp)
        self._locks: Dict[str, Tuple[str, float]] = {}
        self._archived: Set[str] = archived_channels or set()
        self._lock_timeout = lock_timeout  # auto-release after this many seconds
        self._lock = asyncio.Lock()

    def is_archived(self, channel: str) -> bool:
        return channel in self._archived

    def mark_archived(self, channel: str) -> None:
        self._archived.add(channel)

    def is_locked(self, channel: str) -> bool:
        entry = self._locks.get(channel)
        if entry is None:
            return False
        _, acquired_at = entry
        if time.time() - acquired_at > self._lock_timeout:
            # Stale lock — auto-release
            del self._locks[channel]
            return False
        return True

    def acquire(self, channel: str, session_name: str, timeout: float = 0.0) -> bool:
        """
        Try to claim a channel for a session. Returns True if acquired.

        If ``timeout`` > 0, waits up to that many seconds for the channel
        to become available (busy-wait with small sleep).
        """
        deadline = time.time() + timeout if timeout > 0 else 0

        while True:
            entry = self._locks.get(channel)
            if entry is None:
                self._locks[channel] = (session_name, time.time())
                return True

            # Check if the lock is stale
            _, acquired_at = entry
            if time.time() - acquired_at > self._lock_timeout:
                self._locks[channel] = (session_name, time.time())
                return True

            # Already locked by the same session — re-entrant
            if entry[0] == session_name:
                return True

            # Locked by someone else
            if timeout <= 0 or time.time() >= deadline:
                return False

            time.sleep(0.5)

    async def acquire_async(
        self, channel: str, session_name: str, timeout: float = 0.0
    ) -> bool:
        """Async version of acquire — uses asyncio.sleep instead of blocking."""
        deadline = time.time() + timeout if timeout > 0 else 0

        while True:
            async with self._lock:
                entry = self._locks.get(channel)
                if entry is None:
                    self._locks[channel] = (session_name, time.time())
                    return True

                _, acquired_at = entry
                if time.time() - acquired_at > self._lock_timeout:
                    self._locks[channel] = (session_name, time.time())
                    return True

                if entry[0] == session_name:
                    return True

            if timeout <= 0 or time.time() >= deadline:
                return False

            await asyncio.sleep(0.5)

    def release(self, channel: str, session_name: Optional[str] = None) -> bool:
        """Release a channel lock. If session_name is given, only release if owned."""
        entry = self._locks.get(channel)
        if entry is None:
            return False
        if session_name and entry[0] != session_name:
            return False
        del self._locks[channel]
        return True

    def locked_channels(self) -> Dict[str, str]:
        """Return {channel: session_name} for all currently locked channels."""
        now = time.time()
        # Purge stale locks
        stale = [ch for ch, (_, t) in self._locks.items() if now - t > self._lock_timeout]
        for ch in stale:
            del self._locks[ch]
        return {ch: s for ch, (s, _) in self._locks.items()}

    def filter_unarchived(self, channels: List[str]) -> List[str]:
        """Return only channels that haven't been archived yet."""
        return [ch for ch in channels if ch not in self._archived]

    def filter_available(self, channels: List[str]) -> List[str]:
        """Return only channels that are neither archived nor currently locked."""
        return [
            ch for ch in channels
            if ch not in self._archived and not self.is_locked(ch)
        ]


# ──────────────────────────────────────────────────────────────────────────
#  Unified Strategy Selector
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class RotationConfig:
    """Configuration for all rotation strategies."""

    mode: str = "sequential"
    # FloodWait-adaptive
    floodwait_enabled: bool = True
    # Circuit breaker
    failure_threshold: int = 3
    quarantine_minutes: float = 30.0
    # Latency
    latency_window: int = 20
    # Sticky
    affinity_map: Dict[str, str] = field(default_factory=dict)
    # Sharded
    num_shards: Optional[int] = None
    # Primary + fallback
    primary_session: Optional[str] = None
    # Channel dedup
    channel_lock_timeout: float = 3600.0
    skip_archived_channels: bool = True

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "RotationConfig":
        """Build from a spectra_config.json dict."""
        rot = cfg.get("account_rotation", {})
        return cls(
            mode=cfg.get("account_rotation_mode", rot.get("mode", "sequential")),
            floodwait_enabled=rot.get("floodwait_enabled", True),
            failure_threshold=rot.get("failure_threshold", 3),
            quarantine_minutes=rot.get("quarantine_minutes", 30.0),
            latency_window=rot.get("latency_window", 20),
            affinity_map=rot.get("affinity_map", {}),
            num_shards=rot.get("num_shards"),
            primary_session=rot.get("primary_session"),
            channel_lock_timeout=rot.get("channel_lock_timeout", 3600.0),
            skip_archived_channels=rot.get("skip_archived_channels", True),
        )


class AdvancedAccountRotator:
    """
    Unified rotator that combines all strategies with the existing
    sequential/random/weighted/smart modes.

    This wraps the original ``AccountRotator`` logic and adds the new
    strategies on top. It's designed as a drop-in replacement:

        rotator = AdvancedAccountRotator(accounts, config_dict, db_path)
        account = rotator.get_next_account(channel="@target")
        ...
        rotator.record_success(session_name, rtt_ms=120)
        rotator.record_failure(session_name, error="FloodWait", floodwait_seconds=300)
    """

    # All supported modes
    BASIC_MODES = {"sequential", "random", "weighted", "smart"}
    ADVANCED_MODES = {
        "floodwait_adaptive", "circuit_breaker", "latency",
        "sticky", "sharded", "primary_fallback",
    }
    ALL_MODES = BASIC_MODES | ADVANCED_MODES

    def __init__(
        self,
        accounts: List[Dict[str, Any]],
        config: Optional[Dict[str, Any]] = None,
        db_path: Optional[Any] = None,
    ) -> None:
        self.accounts = accounts
        self.rc = RotationConfig.from_config(config or {})
        self.db_path = db_path
        self.current_index = 0
        self._iterator = self._cycle(range(len(accounts)))

        # Sub-components
        self.floodwait = FloodWaitTracker()
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.rc.failure_threshold,
            quarantine_minutes=self.rc.quarantine_minutes,
        )
        self.latency_tracker = LatencyTracker(window_size=self.rc.latency_window)
        self.sticky = StickyAffinityMapper(affinity_map=self.rc.affinity_map)
        self.shard_assigner = ShardAssigner(
            accounts, num_shards=self.rc.num_shards or len(accounts)
        )
        self.primary_fallback = PrimaryFallbackSelector(
            accounts, primary_session=self.rc.primary_session
        )
        self.channel_dedup = ChannelDeduplicator(
            lock_timeout=self.rc.channel_lock_timeout
        )

        # Usage tracking (shared with original AccountRotator semantics)
        self.usage_counts: Dict[int, int] = {i: 0 for i in range(len(accounts))}
        self.last_used: Dict[int, datetime] = {
            i: datetime.now(TZ) for i in range(len(accounts))
        }

        # Load DB stats if available
        if db_path:
            self._load_db_stats()
            self._load_archived_channels()

    # ── Helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _cycle(iterable):
        """itertools.cycle without importing itertools at module level."""
        while True:
            for item in iterable:
                yield item

    def _session_to_idx(self, session_name: str) -> Optional[int]:
        for i, acc in enumerate(self.accounts):
            if acc.get("session_name") == session_name:
                return i
        return None

    def _idx_to_session(self, idx: int) -> Optional[str]:
        if 0 <= idx < len(self.accounts):
            return self.accounts[idx].get("session_name")
        return None

    def _is_available(self, idx: int) -> bool:
        """Check if an account is available across all guards."""
        session = self._idx_to_session(idx)
        if session is None:
            return False
        if self.rc.floodwait_enabled and not self.floodwait.is_available(session):
            return False
        if not self.circuit_breaker.is_available(session):
            return False
        return True

    def _available_indices(self) -> List[int]:
        return [i for i in range(len(self.accounts)) if self._is_available(i)]

    # ── DB ────────────────────────────────────────────────────────────────
    def _load_db_stats(self) -> None:
        """Load usage stats from the account_rotation table if it exists."""
        try:
            from ..db import SpectraDB
            db = SpectraDB(self.db_path)
            for idx, acc in enumerate(self.accounts):
                session = acc.get("session_name")
                if not session:
                    continue
                row = db.conn.execute(
                    "SELECT usage_count, last_used, is_banned, cooldown_until "
                    "FROM account_rotation WHERE session_name = ?",
                    (session,),
                ).fetchone()
                if row:
                    self.usage_counts[idx] = row[0]
                    if row[2]:
                        self.circuit_breaker._open(session)
        except Exception as exc:
            logger.debug("Could not load DB stats: %s", exc)

    def _load_archived_channels(self) -> None:
        """Load already-archived channels from the discovered_groups table."""
        try:
            from ..db import SpectraDB
            db = SpectraDB(self.db_path)
            rows = db.conn.execute(
                "SELECT group_link FROM discovered_groups WHERE status = 'archived'"
            ).fetchall()
            for row in rows:
                self.channel_dedup.mark_archived(row[0])
            if rows:
                logger.info("Loaded %d archived channels from DB", len(rows))
        except Exception as exc:
            logger.debug("Could not load archived channels: %s", exc)

    def _save_db_stats(self, idx: int) -> None:
        if not self.db_path or idx >= len(self.accounts):
            return
        session = self._idx_to_session(idx)
        if not session:
            return
        try:
            from ..db import SpectraDB
            db = SpectraDB(self.db_path)
            db.conn.execute(
                "UPDATE account_rotation SET usage_count = ?, last_used = ? "
                "WHERE session_name = ?",
                (self.usage_counts[idx], self.last_used[idx].isoformat(), session),
            )
            db.conn.commit()
        except Exception as exc:
            logger.debug("Could not save DB stats: %s", exc)

    # ── Selection ─────────────────────────────────────────────────────────
    def get_next_account(
        self, channel: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get the next account based on the configured rotation mode.

        Args:
            channel: Optional target channel. Used by sticky/sharded modes
                     to pick the account pinned to this channel.
        """
        available = self._available_indices()
        if not available:
            logger.error("No accounts available for rotation")
            return None

        mode = self.rc.mode
        selected_idx: Optional[int] = None

        # ── Sticky: channel → pinned account ──
        if mode == "sticky" and channel:
            sessions = [self._idx_to_session(i) for i in available]
            owner = self.sticky.get_or_assign(channel, sessions)
            if owner:
                selected_idx = self._session_to_idx(owner)

        # ── Sharded: deterministic hash of channel → shard → account ──
        elif mode == "sharded" and channel:
            session = self.shard_assigner.get_account_for_item(channel)
            if session:
                idx = self._session_to_idx(session)
                if idx is not None and idx in available:
                    selected_idx = idx
                else:
                    # Shard owner unavailable — fall back to any available
                    selected_idx = available[0]

        # ── Primary + fallback ──
        elif mode == "primary_fallback":
            account = self.primary_fallback.select(
                lambda s: (
                    self._is_available(self._session_to_idx(s))
                    if self._session_to_idx(s) is not None
                    else False
                )
            )
            if account:
                selected_idx = self._session_to_idx(account["session_name"])

        # ── Latency: pick fastest ──
        elif mode == "latency":
            sessions = [self._idx_to_session(i) for i in available]
            best = self.latency_tracker.best_account(sessions)
            if best:
                selected_idx = self._session_to_idx(best)
            else:
                # No latency data yet — fall back to sequential
                selected_idx = available[0]

        # ── FloodWait-adaptive: sequential but skip cooldowns ──
        elif mode == "floodwait_adaptive":
            for _ in range(len(self.accounts)):
                idx = next(self._iterator)
                if idx in available:
                    selected_idx = idx
                    break

        # ── Circuit breaker: weighted (least-used) but skip open circuits ──
        elif mode == "circuit_breaker":
            selected_idx = min(available, key=lambda i: self.usage_counts[i])

        # ── Basic modes (sequential/random/weighted/smart) ──
        elif mode == "random":
            selected_idx = random.choice(available)
        elif mode == "weighted":
            selected_idx = min(available, key=lambda i: self.usage_counts[i])
        elif mode == "smart":
            now = datetime.now(TZ)
            scores = {}
            for idx in available:
                time_factor = (now - self.last_used[idx]).total_seconds() / 3600
                usage_factor = 1 / (self.usage_counts[idx] + 1)
                scores[idx] = time_factor * 0.7 + usage_factor * 0.3
            selected_idx = max(scores, key=scores.get)
        else:  # sequential (default)
            for _ in range(len(self.accounts)):
                idx = next(self._iterator)
                if idx in available:
                    selected_idx = idx
                    break

        if selected_idx is None:
            logger.error("No account could be selected (mode=%s)", mode)
            return None

        # Update usage
        self.usage_counts[selected_idx] += 1
        self.last_used[selected_idx] = datetime.now(TZ)
        self.current_index = selected_idx
        self._save_db_stats(selected_idx)

        logger.info(
            "Selected account: %s (mode=%s%s)",
            self._idx_to_session(selected_idx), mode,
            f", channel={channel}" if channel else "",
        )
        return self.accounts[selected_idx]

    # ── Feedback ──────────────────────────────────────────────────────────
    def record_success(
        self,
        session_name: str,
        rtt_ms: Optional[float] = None,
    ) -> None:
        """Record a successful operation. Optionally record latency."""
        self.circuit_breaker.record_success(session_name)
        if rtt_ms is not None:
            self.latency_tracker.record(session_name, rtt_ms)

    def record_failure(
        self,
        session_name: str,
        error: str = "",
        floodwait_seconds: Optional[int] = None,
    ) -> None:
        """
        Record a failed operation.

        If ``floodwait_seconds`` is provided (from a FloodWaitError),
        the FloodWait tracker sets a precise cooldown. The circuit breaker
        also records the failure.
        """
        if floodwait_seconds is not None and self.rc.floodwait_enabled:
            self.floodwait.record_flood_wait(session_name, floodwait_seconds)
        self.circuit_breaker.record_failure(session_name, error)

    # ── Channel De-Duplication ────────────────────────────────────────────
    def acquire_channel(
        self, channel: str, session_name: str, timeout: float = 0.0
    ) -> bool:
        """Claim a channel for a session (sync)."""
        return self.channel_dedup.acquire(channel, session_name, timeout)

    async def acquire_channel_async(
        self, channel: str, session_name: str, timeout: float = 0.0
    ) -> bool:
        """Claim a channel for a session (async)."""
        return await self.channel_dedup.acquire_async(channel, session_name, timeout)

    def release_channel(self, channel: str, session_name: Optional[str] = None) -> bool:
        """Release a channel lock."""
        return self.channel_dedup.release(channel, session_name)

    def is_channel_available(self, channel: str) -> bool:
        """Check if a channel is neither archived nor locked."""
        if self.rc.skip_archived_channels and self.channel_dedup.is_archived(channel):
            return False
        return not self.channel_dedup.is_locked(channel)

    def filter_available_channels(self, channels: List[str]) -> List[str]:
        """Return channels that are available for work."""
        return self.channel_dedup.filter_available(channels)

    def mark_channel_archived(self, channel: str) -> None:
        self.channel_dedup.mark_archived(channel)

    # ── Stats ─────────────────────────────────────────────────────────────
    def get_stats(self) -> Dict[str, Any]:
        """Return a summary of all rotator state for debugging/display."""
        return {
            "mode": self.rc.mode,
            "accounts": len(self.accounts),
            "available": len(self._available_indices()),
            "floodwait_cooldowns": {
                s: self.floodwait.remaining(s)
                for s in (a.get("session_name", "") for a in self.accounts)
                if self.floodwait.remaining(s) > 0
            },
            "circuit_breaker_states": {
                a.get("session_name", f"acc_{i}"): self.circuit_breaker.state(
                    a.get("session_name", f"acc_{i}")
                )
                for i, a in enumerate(self.accounts)
            },
            "latency_ms": self.latency_tracker.stats(),
            "sticky_mapping": self.sticky.mapping(),
            "shards": self.shard_assigner.all_shards(),
            "primary": self.primary_fallback.primary,
            "locked_channels": self.channel_dedup.locked_channels(),
            "archived_channels": len(self.channel_dedup._archived),
        }
