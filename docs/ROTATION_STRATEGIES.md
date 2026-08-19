# Account Rotation Strategies & Channel De-Duplication

SPECTRA supports **10 rotation strategies** for distributing work across multiple Telegram accounts, plus a **channel de-duplication** system that prevents multiple accounts from working the same channel concurrently.

---

## Quick Start

Set a rotation mode from the CLI:

```bash
./spectra accounts --set-rotation floodwait_adaptive
```

View live rotation stats:

```bash
./spectra accounts --rotation-stats
```

Or configure it in `spectra_config.json`:

```json
{
    "account_rotation": {
        "mode": "floodwait_adaptive",
        "floodwait_enabled": true,
        "failure_threshold": 3,
        "quarantine_minutes": 30.0,
        "latency_window": 20,
        "affinity_map": {},
        "num_shards": null,
        "primary_session": null,
        "channel_lock_timeout": 3600.0,
        "skip_archived_channels": true
    }
}
```

---

## All Modes at a Glance

| Mode | Speed | Network? | OPSEC | Best For |
|------|-------|----------|-------|----------|
| `sequential` | Fast | No | Low | Even load distribution |
| `random` | Fast | No | Medium | Unpredictable selection |
| `weighted` | Fast | No | Low | Least-used account first |
| `smart` | Fast | No | Low | Rested + under-used accounts |
| `floodwait_adaptive` | Fast | No* | Low | Auto-recovery from rate limits |
| `circuit_breaker` | Fast | No | Low | Flaky accounts / unreliable proxies |
| `latency` | Fast | No* | Low | Mixed proxy routes |
| `sticky` | Fast | No | **High** | Channel→account pinning |
| `sharded` | Fast | No | **High** | Parallel archiving, no overlap |
| `primary_fallback` | Fast | No | Medium | Minimise account footprint |

*Network only needed for FloodWait recovery and latency measurement, not for selection itself.

---

## Strategy 1: `sequential` (Round-Robin)

**Default.** Strict A→B→C→A→B→C order using `itertools.cycle`.

```json
{"account_rotation": {"mode": "sequential"}}
```

- **Pros**: Simple, predictable, even distribution
- **Cons**: No awareness of account health or rate limits
- **Best for**: Small account pools where all accounts are healthy

---

## Strategy 2: `random`

Randomly picks from available accounts each time.

```json
{"account_rotation": {"mode": "random"}}
```

- **Pros**: Unpredictable — harder for adversaries to pattern
- **Cons**: Uneven load distribution over short windows
- **Best for**: OPSEC scenarios where predictability is a concern

---

## Strategy 3: `weighted` (Least-Used)

Always picks the account with the lowest cumulative usage count.

```json
{"account_rotation": {"mode": "weighted"}}
```

- **Pros**: Perfectly balanced load over time
- **Cons**: No time-awareness — a recently-used but low-total account may be picked again
- **Best for**: Long-running archiving where total load matters more than recency

---

## Strategy 4: `smart`

Score = `0.7 × hours_since_last_use + 0.3 × (1 / (usage_count + 1))`

Picks the account with the highest score — favours accounts that are both **rested** (haven't been used recently) and **under-used** (low total count).

```json
{"account_rotation": {"mode": "smart"}}
```

- **Pros**: Balances recency and total load
- **Cons**: Slightly more CPU than sequential (negligible)
- **Best for**: General-purpose multi-account operations

---

## Strategy 5: `floodwait_adaptive` ★

Sequential rotation, but when Telegram returns a `FloodWaitError(seconds)`, the exact wait time is parsed and the account is placed in a **precise cooldown**. The account is automatically skipped until the cooldown expires, then returned to the pool — no manual intervention.

```json
{
    "account_rotation": {
        "mode": "floodwait_adaptive",
        "floodwait_enabled": true
    }
}
```

### How it works

1. Account A gets `FloodWaitError(seconds=300)` from Telegram
2. `FloodWaitTracker.record_flood_wait("acc_A", 300)` is called automatically
3. Account A is marked unavailable for exactly 300 seconds
4. Rotator skips A, moves to B, C, D...
5. After 300 seconds, A auto-recovers and is eligible again

### Integration

The `GroupManager` in `discovery.py` automatically calls `record_failure(floodwait_seconds=e.seconds)` when catching `FloodWaitError` — no code changes needed in your workflows.

### Config options

| Option | Default | Description |
|--------|---------|-------------|
| `floodwait_enabled` | `true` | Enable/disable FloodWait tracking (works in all modes) |

- **Pros**: Self-healing — no manual cooldown management
- **Cons**: Requires the FloodWait to actually be caught (already wired in)
- **Best for**: Any scenario with aggressive rate limits. Combine with `circuit_breaker` for maximum resilience.

---

## Strategy 6: `circuit_breaker` ★

Each account has a **circuit breaker** with three states:

```
closed ──(N consecutive failures)──→ open
   ↑                                    │
   └──(probe succeeds)── half_open ←──(quarantine expires)
```

- **closed**: Healthy, available for selection
- **open**: Quarantined after `failure_threshold` consecutive failures. Stays open for `quarantine_minutes`.
- **half_open**: Quarantine expired. A single **probe** request must succeed before the account returns to closed. If the probe fails, back to open.

```json
{
    "account_rotation": {
        "mode": "circuit_breaker",
        "failure_threshold": 3,
        "quarantine_minutes": 30.0
    }
}
```

### Config options

| Option | Default | Description |
|--------|---------|-------------|
| `failure_threshold` | `3` | Consecutive failures before opening the circuit |
| `quarantine_minutes` | `30.0` | How long the circuit stays open before half-open probe |

### State transitions

| Event | From → To |
|-------|-----------|
| Success | any → closed |
| Failure (count < threshold) | closed → closed (increment counter) |
| Failure (count ≥ threshold) | closed → open |
| Quarantine expires | open → half_open |
| Probe succeeds | half_open → closed |
| Probe fails | half_open → open |

- **Pros**: Auto-quarantine of flaky accounts, gradual recovery
- **Cons**: Accounts may be unavailable for `quarantine_minutes` even if they recover early
- **Best for**: Unstable proxies, accounts with intermittent auth issues

---

## Strategy 7: `latency` ★

Tracks rolling average **round-trip time (RTT)** per account in milliseconds. Always picks the fastest responder.

```json
{
    "account_rotation": {
        "mode": "latency",
        "latency_window": 20
    }
}
```

### How it works

1. Each successful operation records RTT: `rotator.record_success(session, rtt_ms=120)`
2. A rolling window of the last `latency_window` samples is kept per account
3. `get_next_account()` picks the account with the lowest average RTT
4. If no data exists yet (cold start), falls back to sequential

### Config options

| Option | Default | Description |
|--------|---------|-------------|
| `latency_window` | `20` | Number of RTT samples to average |

### Recording latency

The `GroupManager` records success automatically. To record RTT, wrap your operations:

```python
import time
start = time.time()
await client.get_messages(channel, limit=1)
rtt_ms = (time.time() - start) * 1000
rotator.record_success(session_name, rtt_ms=rtt_ms)
```

- **Pros**: Prefers fastest route — useful with mixed proxy quality
- **Cons**: Cold start has no data; requires RTT recording
- **Best for**: Accounts on different proxy routes with varying latency

---

## Strategy 8: `sticky` (Affinity) ★

Pins specific accounts to specific target channels. A channel **always sees the same user_id** — an OPSEC requirement to prevent pattern detection.

```json
{
    "account_rotation": {
        "mode": "sticky",
        "affinity_map": {
            "@target_channel_1": "spectra_tdata_8011484242_1",
            "@target_channel_2": "spectra_tdata_8583035195_3"
        }
    }
}
```

### How it works

1. **Explicit mapping**: Set `affinity_map` in config to pin channel→account
2. **Auto-assignment**: If a channel isn't in the map, SPECTRA auto-assigns the least-assigned available account
3. **Persistence**: Once assigned, the mapping stays for the session
4. **Selection**: `get_next_account(channel="@target")` returns the pinned account

### Usage

The `GroupManager.join_group(target_link)` automatically passes the channel to the rotator:

```python
# This will always use the same account for @target_channel
await manager.join_group("@target_channel")
```

### Config options

| Option | Default | Description |
|--------|---------|-------------|
| `affinity_map` | `{}` | Channel → session_name mapping. Empty = auto-assign. |

- **Pros**: Strong OPSEC — same user_id per channel, no cross-contamination
- **Cons**: Less load balancing; pinned account must be healthy
- **Best for**: Long-term surveillance of specific targets where pattern detection is a concern

---

## Strategy 9: `sharded` (Partitioned) ★

Divides the work list into N **shards**, assigns one account per shard. Each channel is deterministically hashed to a shard — no two accounts will ever work the same channel.

```json
{
    "account_rotation": {
        "mode": "sharded",
        "num_shards": 4
    }
}
```

### How it works

1. `num_shards` defaults to the number of accounts
2. Each account is assigned a shard index: `acc_1 → shard 0, acc_2 → shard 1, ...`
3. For any channel, `hash(channel) % num_shards` determines the shard
4. The account owning that shard handles the channel — always

### Determinism

The same channel always maps to the same shard/account, even across restarts. This means:
- Clean audit trail: "which account touched which channel?"
- No overlap: impossible for two accounts to archive the same channel
- Parallel-safe: multiple workers can run simultaneously without coordination

### Config options

| Option | Default | Description |
|--------|---------|-------------|
| `num_shards` | `null` (auto = number of accounts) | Number of shards to divide work into |

### Getting shard assignments

```bash
./spectra accounts --rotation-stats
```

Output includes:
```
  Shard Assignments:
    Shard 0: spectra_tdata_8011484242_1
    Shard 1: spectra_tdata_8199441474_2
    Shard 2: spectra_tdata_8583035195_3
    Shard 3: spectra_tdata_8641643406_4
```

- **Pros**: Zero overlap, deterministic, parallel-safe, clean audit trail
- **Cons**: No load balancing — if one shard has more work, that account does more
- **Best for**: Parallel archiving across many channels with multiple workers

---

## Strategy 10: `primary_fallback` ★

One account is **primary**; others only activate when the primary is unavailable (rate-limited, banned, or circuit open). Minimises account footprint.

```json
{
    "account_rotation": {
        "mode": "primary_fallback",
        "primary_session": "spectra_tdata_8011484242_1"
    }
}
```

### How it works

1. `primary_session` is tried first for every operation
2. If primary is unavailable (FloodWait cooldown, circuit open, etc.), fallbacks are tried in round-robin order
3. Once primary recovers, it's used again exclusively
4. Fallbacks rotate among themselves to avoid overloading one

### Config options

| Option | Default | Description |
|--------|---------|-------------|
| `primary_session` | `null` (first account) | Session name of the primary account |

### Use case

You have one "main" identity that should handle 95% of traffic, and 3 backup identities that only kick in during rate limits. This concentrates activity on one account (simpler audit trail) while maintaining resilience.

- **Pros**: Minimal account footprint, clean primary audit trail
- **Cons**: Primary takes most load — may hit rate limits faster
- **Best for**: Concentrating activity on one identity with fallback resilience

---

## Channel De-Duplication ★

All rotation modes include the `ChannelDeduplicator` — a lock-based system that prevents multiple accounts from working the same channel concurrently.

### Features

| Feature | Description |
|---------|-------------|
| **Lock** | When an account starts working a channel, it acquires a lock. Other accounts skip it. |
| **Archive tracking** | Channels marked as `archived` in the `discovered_groups` DB table are automatically skipped. |
| **Stale lock auto-release** | Locks older than `channel_lock_timeout` seconds (default: 1 hour) are automatically released. |
| **Re-entrant** | The same account can re-acquire a channel it already holds. |
| **Async + sync** | Both `acquire()` (sync) and `acquire_async()` (async) APIs available. |

### Config options

| Option | Default | Description |
|--------|---------|-------------|
| `channel_lock_timeout` | `3600.0` (1 hour) | Auto-release locks after this many seconds |
| `skip_archived_channels` | `true` | Skip channels already marked as archived in DB |

### How it integrates

1. **On join**: `GroupManager.join_group(target_link)` checks `is_channel_available()` before joining. If archived or locked, it skips.
2. **On acquire**: After selecting an account, `acquire_channel_async()` is called. If another account holds the lock, the channel is skipped.
3. **On archive complete**: When a channel is successfully archived, `mark_channel_archived()` is called — adding it to the deduplicator's archive set.
4. **On startup**: The rotator loads all channels with `status = 'archived'` from the `discovered_groups` DB table.

### Disabling archive check

To re-archive channels (e.g., after a config change):

```json
{
    "account_rotation": {
        "skip_archived_channels": false
    }
}
```

### Filtering channels

```python
# Get only channels that are neither archived nor locked
available = rotator.filter_available_channels(["@chan1", "@chan2", "@chan3"])
```

---

## Combined Strategies

The `AdvancedAccountRotator` combines multiple safety layers regardless of the selected mode:

```
┌─────────────────────────────────────────────────────┐
│           get_next_account(channel="@target")        │
│                                                      │
│  1. Filter by FloodWait cooldowns (if enabled)       │
│  2. Filter by Circuit Breaker state                  │
│  3. Apply mode-specific selection:                   │
│     • sequential / random / weighted / smart         │
│     • floodwait_adaptive / circuit_breaker           │
│     • latency / sticky / sharded / primary_fallback  │
│  4. Return selected account                          │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│              join_group("@target")                   │
│                                                      │
│  1. Check channel dedup (archived? locked?)          │
│  2. Select account (passing channel for sticky/shard)│
│  3. Acquire channel lock                             │
│  4. Perform operation                                │
│  5. Record success/failure + RTT                     │
│  6. Release lock (or mark archived on success)       │
└─────────────────────────────────────────────────────┘
```

This means even in `sequential` mode, you get:
- FloodWait auto-cooldowns (if `floodwait_enabled: true`)
- Circuit breaker protection (if failures are recorded)
- Channel de-duplication (always on)

---

## CLI Commands

### Set rotation mode

```bash
./spectra accounts --set-rotation <mode>
```

Valid modes:
- `sequential`, `random`, `weighted`, `smart` (basic)
- `floodwait_adaptive`, `circuit_breaker`, `latency` (adaptive)
- `sticky`, `sharded`, `primary_fallback` (OPSEC/structural)

### View rotation stats

```bash
./spectra accounts --rotation-stats
```

Sample output:

```
============================================================
  Rotation Strategy Stats
============================================================
  Mode:                 floodwait_adaptive
  Total accounts:       4
  Available:            3
  Archived channels:    42

  Circuit Breaker States:
    spectra_tdata_8011484242_1            closed
    spectra_tdata_8199441474_2            open
    spectra_tdata_8583035195_3            closed
    spectra_tdata_8641643406_4            closed

  FloodWait Cooldowns:
    spectra_tdata_8199441474_2            287s remaining

  Latency (avg ms):
    spectra_tdata_8011484242_1            85ms
    spectra_tdata_8583035195_3            120ms
    spectra_tdata_8641643406_4            210ms

  Sticky Affinity Mapping:
    @target_channel_1                     → spectra_tdata_8011484242_1
    @target_channel_2                     → spectra_tdata_8583035195_3

  Shard Assignments:
    Shard 0: spectra_tdata_8011484242_1
    Shard 1: spectra_tdata_8199441474_2
    Shard 2: spectra_tdata_8583035195_3
    Shard 3: spectra_tdata_8641643406_4

  Locked Channels (in progress):
    @target_channel_1                     ← spectra_tdata_8011484242_1

  Primary account:      spectra_tdata_8011484242_1
============================================================
```

---

## Full Config Reference

```json
{
    "account_rotation": {
        "mode": "sequential",
        "floodwait_enabled": true,
        "failure_threshold": 3,
        "quarantine_minutes": 30.0,
        "latency_window": 20,
        "affinity_map": {},
        "num_shards": null,
        "primary_session": null,
        "channel_lock_timeout": 3600.0,
        "skip_archived_channels": true
    }
}
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `mode` | string | `"sequential"` | Rotation strategy (see table above) |
| `floodwait_enabled` | bool | `true` | Enable FloodWait auto-cooldowns in all modes |
| `failure_threshold` | int | `3` | Consecutive failures before circuit breaker opens |
| `quarantine_minutes` | float | `30.0` | Circuit breaker quarantine duration |
| `latency_window` | int | `20` | RTT sample window size for latency mode |
| `affinity_map` | object | `{}` | Channel → session_name mapping for sticky mode |
| `num_shards` | int\|null | `null` | Number of shards for sharded mode (auto = # accounts) |
| `primary_session` | string\|null | `null` | Primary session name for primary_fallback mode |
| `channel_lock_timeout` | float | `3600.0` | Channel lock auto-release timeout (seconds) |
| `skip_archived_channels` | bool | `true` | Skip channels already marked as archived in DB |

---

## Programmatic API

```python
from tgarchive.utils.rotation_strategies import (
    AdvancedAccountRotator,
    FloodWaitTracker,
    CircuitBreaker,
    LatencyTracker,
    StickyAffinityMapper,
    ShardAssigner,
    PrimaryFallbackSelector,
    ChannelDeduplicator,
    RotationConfig,
)

# Create rotator
rotator = AdvancedAccountRotator(accounts, config=config_dict, db_path=db_path)

# Select an account (pass channel for sticky/sharded)
account = rotator.get_next_account(channel="@target")

# Record success with latency
rotator.record_success("session_1", rtt_ms=120)

# Record failure with FloodWait
rotator.record_failure("session_1", error="FloodWaitError: 300s", floodwait_seconds=300)

# Channel de-duplication
await rotator.acquire_channel_async("@channel", "session_1")
rotator.release_channel("@channel", "session_1")
rotator.mark_channel_archived("@channel")

# Get stats
stats = rotator.get_stats()
```

---

## Implementation Reference

| Component | File | Description |
|-----------|------|-------------|
| `FloodWaitTracker` | `tgarchive/utils/rotation_strategies.py` | Per-account FloodWait cooldown tracking |
| `CircuitBreaker` | `tgarchive/utils/rotation_strategies.py` | Closed/open/half-open state machine |
| `LatencyTracker` | `tgarchive/utils/rotation_strategies.py` | Rolling average RTT per account |
| `StickyAffinityMapper` | `tgarchive/utils/rotation_strategies.py` | Channel→account pinning |
| `ShardAssigner` | `tgarchive/utils/rotation_strategies.py` | Deterministic hash-based sharding |
| `PrimaryFallbackSelector` | `tgarchive/utils/rotation_strategies.py` | Primary with fallback rotation |
| `ChannelDeduplicator` | `tgarchive/utils/rotation_strategies.py` | Lock-based channel de-dup |
| `AdvancedAccountRotator` | `tgarchive/utils/rotation_strategies.py` | Unified rotator combining all strategies |
| `AccountRotator` (legacy) | `tgarchive/utils/discovery.py` | Original 4-mode rotator (sequential/random/weighted/smart) |
| `GroupManager` | `tgarchive/utils/discovery.py` | Auto-selects legacy vs advanced rotator based on mode |
