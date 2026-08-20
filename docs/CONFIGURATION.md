# SPECTRA Configuration Guide

SPECTRA stores operational configuration and runtime states under `data/config/`.

---

## 🔑 Telegram API Credentials

To interact with the Telegram MTProto API, you must obtain an `api_id` and `api_hash` from [my.telegram.org](https://my.telegram.org).

Set up `data/config/spectra_config.json`:

```json
{
    "api_id": 1234567,
    "api_hash": "0123456789abcdef0123456789abcdef"
}
```

---

## 👥 Multi-Account Orchestration & Proxies

SPECTRA supports managing multiple Telegram account sessions with dedicated SOCKS5/HTTP proxy rotation to avoid rate limiting and maintain OPSEC.

```json
{
    "api_id": 1234567,
    "api_hash": "0123456789abcdef0123456789abcdef",
    "accounts": [
        {
            "session_name": "worker_node_1",
            "proxy": {
                "proxy_type": "socks5",
                "addr": "127.0.0.1",
                "port": 9050
            }
        }
    ]
}
```

---

## 🧪 Testing Connectivity

Verify your configured account pools and proxy connectivity:

```bash
./spectra accounts --test
```

---

## 🔄 Account Rotation Strategies

SPECTRA supports 10 rotation strategies for distributing work across multiple accounts, plus channel de-duplication that prevents multiple accounts from working the same channel concurrently.

> **Full reference**: See [ROTATION_STRATEGIES.md](ROTATION_STRATEGIES.md) for complete details, state diagrams, config examples, and programmatic API for all 10 strategies.

Configure the mode in `spectra_config.json`:

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

Or set it from the CLI:

```bash
./spectra accounts --set-rotation floodwait_adaptive
```

View live rotation stats (circuit breaker states, FloodWait cooldowns, latency, channel locks):

```bash
./spectra accounts --rotation-stats
```

### All Modes

| Mode | Description |
|------|-------------|
| `sequential` | Round-robin: strict A→B→C→A order (default) |
| `random` | Randomly pick from available accounts |
| `weighted` | Pick the account with the lowest usage count |
| `smart` | Score = 0.7 × hours_since_last_use + 0.3 × (1/(usage+1)) |
| `floodwait_adaptive` | Sequential, but auto-parses `FloodWaitError` seconds and sets precise per-account cooldowns. Accounts auto-recover when cooldown expires. |
| `circuit_breaker` | Tracks consecutive failures. After N failures, account is quarantined for M minutes. A probe request must succeed before re-entry. |
| `latency` | Tracks rolling average RTT per account and prefers the fastest responder. Useful with different proxy routes. |
| `sticky` | Pins specific accounts to specific channels. A channel always sees the same user_id — OPSEC requirement. Auto-assigns on first access. |
| `sharded` | Divides work into N shards, one account per shard. Deterministic hash(channel) → shard → account. No overlap, clean audit trail. |
| `primary_fallback` | One account is primary; others only activate when the primary is rate-limited or fails. Minimises account footprint. |

### Mode Details

**`floodwait_adaptive`** — When Telegram returns a `FloodWaitError(seconds)`, the exact wait time is recorded and the account is skipped until the cooldown expires. No manual intervention. Combine with `circuit_breaker` behaviour by leaving `floodwait_enabled: true`.

**`circuit_breaker`** — Each account has a circuit breaker with three states:
- **closed**: healthy, available
- **open**: quarantined after `failure_threshold` consecutive failures for `quarantine_minutes`
- **half_open**: quarantine expired; a single probe must succeed before returning to closed

**`latency`** — Records RTT in milliseconds for each successful operation. Selects the account with the lowest rolling average (window size: `latency_window`). Falls back to sequential when no data exists yet.

**`sticky`** — Configure explicit channel→account pins via `affinity_map`, or let SPECTRA auto-assign (first account to touch a channel owns it, balanced by least-assigned). The same channel always sees the same user_id.

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

**`sharded`** — Set `num_shards` to the number of accounts (default). Each channel is deterministically hashed to a shard. No two accounts will ever work the same channel. Ideal for parallel archiving with clean audit trails.

**`primary_fallback`** — Set `primary_session` to the session name of the primary account. Fallbacks activate only when the primary is unavailable (FloodWait, banned, or circuit open). Fallbacks rotate round-robin among themselves.

```json
{
    "account_rotation": {
        "mode": "primary_fallback",
        "primary_session": "spectra_tdata_8011484242_1"
    }
}
```

### Channel De-Duplication

All modes include channel de-duplication via `ChannelDeduplicator`:
- **Lock**: When an account starts working a channel, it acquires a lock. Other accounts skip it.
- **Archive tracking**: Channels marked as `archived` in the `discovered_groups` DB table are automatically skipped.
- **Stale lock auto-release**: Locks older than `channel_lock_timeout` seconds (default: 1 hour) are automatically released.
- **Filter**: `filter_available_channels()` returns only channels that are neither archived nor locked.

Set `skip_archived_channels: false` to disable the archive check (e.g., for re-archiving).

---

## 🔑 Importing Accounts from tdata (Telegram Desktop / Alternatives)

If you already have logged-in accounts in a Telegram Desktop or Alternatives `tdata` folder, you can convert them into Telethon `.session` files without re-login — no phone number, no verification code required. SPECTRA extracts the existing MTProto authorization keys directly from the on-disk `tdata`.

```bash
# Auto-detect tdata (Telegram Desktop / Alternatives / snap) and write sessions to ./sessions
./spectra tdata2session

# Convert and register the accounts into spectra_config.json in one step
./spectra tdata2session --register

# Passcode-protected tdata
./spectra tdata2session --passcode 1234
```

Each converted account produces:
- `sessions/spectra_tdata_<user_id>_<n>.session` — native Telethon SQLite session
- `sessions/spectra_tdata_<user_id>_<n>.json` — sidecar with `api_id`, `api_hash`, `user_id`, `dc_id`, and device info

With `--register`, the accounts are appended to the `accounts` array in `spectra_config.json`:

```json
{
    "accounts": [
        {
            "api_id": 2040,
            "api_hash": "b18441a1ff607e10a989891a5462e627",
            "session_name": "spectra_tdata_8011484242_1",
            "session_dir": "/path/to/sessions",
            "user_id": 8011484242,
            "phone": null
        }
    ]
}
```

The `sessions/` directory is gitignored by default, so converted sessions stay local. See the [CLI Reference](CLI_REFERENCE.md#7-tdata--session-import) for the full flag list.

---

## ⚡ Optional: Search Cache (Redis or QIHSE KV)

SPECTRA can use an optional caching layer for search results, KEYSTONE anchor tables, and message metadata. When no cache is configured, the cache silently no-ops and all searches hit the database directly — no functionality is lost, just the speedup.

Two backends are supported:

| Backend | Type | Notes |
|---------|------|-------|
| **Redis** | External server | Standard `redis://` protocol. Use `redis:7-alpine` or any Redis-compatible server. |
| **QIHSE KV** | Built-in (in-process) | QIHSE's native multi-model database engine with RESP2/RESP3 wire protocol, PostgreSQL wire protocol, full SQL engine (JOIN, GROUP BY, ORDER BY, subqueries), ACID transactions with MVCC, B+ tree and hash secondary indexes, unified WAL with crash recovery, and 16,384-slot cluster sharding. No external process needed — runs in the same process space as SPECTRA. Any standard Redis or PostgreSQL client connects out-of-the-box. See [`QIHSE/docs/architecture/system_overview.md`](../QIHSE/docs/architecture/system_overview.md) for the full architecture overview. |

### What the cache stores

| Cache | TTL | Purpose |
|-------|-----|---------|
| Search results | 1 hour | Hybrid search queries (KEYSTONE + FTS5 + Qdrant) skip re-ranking on repeated queries |
| KEYSTONE anchor tables | 24 hours | Structured timestamp index lookups avoid repeated DB scans |
| Message metadata | 1 hour | Per-message metadata avoids repeated DB reads |

### Enabling the cache

**Docker with Redis (default):** Redis is included in `docker-compose.yml` and starts automatically:

```bash
docker-compose up -d
```

The `spectra` container connects to `redis://redis:6379` automatically.

**Docker with QIHSE KV (no external Redis container):** Comment out or remove the `redis` service in `docker-compose.yml` and set `REDIS_URL` to point at a QIHSE RESP server instance. QIHSE's RESP engine listens on a standard Redis-compatible port and accepts the same wire protocol.

**Local / manual with Redis:**

```bash
pip install redis
# Start a Redis server (e.g. via your package manager or Docker)
redis-server &
```

**Local / manual with QIHSE KV:** Build and run the QIHSE RESP server (see [`QIHSE/Makefile`](../QIHSE/Makefile) target `redis-cluster-node`):

```bash
cd QIHSE && make lib && make redis-cluster-node
LD_LIBRARY_PATH=. ./tests/qihse_cluster_node --port 6379
```

Any `redis://` client URL works — QIHSE's RESP engine is wire-compatible with Redis.

Set `REDIS_URL` in your `.env` or environment (works for both Redis and QIHSE KV):

```bash
REDIS_URL=redis://localhost:6379
```

### Disabling the cache

Leave `REDIS_URL` blank or unset, or don't install the `redis` package. The cache manager will silently skip all reads/writes and search will use the database directly. No warning is printed at startup.

---

## ⚡ Task Queue & Worker Scheduling (QIHSE Celery-Equivalent)

For background crawling, media downloading, entity extraction, and periodic reconnaissance sweeps, SPECTRA integrates with **QIHSE's native Task Queue and Scheduler Engine** (`qihse_task`), eliminating the need for an external Celery or RabbitMQ cluster.

### Key Capabilities

| Capability | QIHSE Task Engine | Conventional Alternative (Celery + Redis) |
|---|---|---|
| **Broker & Results** | In-process (Event Stream + Trinary Trie KV) | External Redis / RabbitMQ process + DB |
| **Worker Threads** | NUMA-pinned C worker threads | OS prefork Python worker processes |
| **Priorities** | 4 priority levels (`CRITICAL`, `HIGH`, `NORMAL`, `LOW`) | Limited queue routing |
| **Periodic Scheduling** | 10ms timing wheel cron engine | Separate Celery Beat daemon |
| **Wire Protocol** | Native RESP `TASK.*` & `SCHEDULE.*` commands | Custom AMQP / Redis serialization |
| **Python Interface** | `@task` decorator, `.delay()`, `.apply_async()`, `AsyncResult` | Standard Celery API |

### Python Task Definition & Usage

```python
from QIHSE.sdks.python.qihse_task import task, TaskClient

# Define an async background job with automatic retry & timeout
@task(queue="media_download", priority="HIGH", max_retries=3, timeout=60)
def download_channel_media(channel_id: int, message_ids: list):
    # Background extraction and deduplication
    return {"channel_id": channel_id, "downloaded": len(message_ids)}

# Dispatch asynchronously (.delay)
handle = download_channel_media.delay(123456789, [101, 102, 103])
print(f"Task dispatched: {handle.id} (State: {handle.status})")

# Wait for completion
result = handle.get(timeout=30.0)
print("Finished:", result)
```

### Periodic Reconnaissance Sweeps (Cron Scheduling)

```python
client = TaskClient(port=6379)

# Schedule nightly channel crawl at 02:00 daily
client.schedule_add(
    schedule_id="nightly_crawl",
    cron_expr="0 2 * * *",
    queue_name="crawling",
    payload={"func": "spectra.recon.sweep_active_targets"},
    priority="LOW"
)
```

