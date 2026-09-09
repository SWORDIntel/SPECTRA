# QIHSE RESP + MSNET Swarming Integration Plan

> **Status: IMPLEMENTED** — All 10 steps complete. 14/14 tests passing in `tgarchive/tests/test_msnet_swarm.py`.
>
> **Commits (pushed to `pii`):**
> - `4e77405` — QIHSE RESP server + MSNET swarming integration (steps 1-9)
> - `bf5a44a` — Tests for MSNET swarm stack (step 10)
> - `5287f7a` — Fix SQLite coordination thread safety for swarm heartbeat
> - `719ce89` — QIHSE RESP auto-fallback, MSNET client, CLI commands, GeoLite2
> - `0e2eae4` — API-first TelegramPasswordFinder with QIHSE RESP work distribution
>
> **Key implementation notes:**
> - QIHSE RESP auto-fallback to SQLiteCoordination when the C engine hangs on write commands
> - fd-reuse race mitigation in RESP server (grace period after short-lived connections)
> - Process-level flock on DB sidecar files to prevent QIHSE VFS global state corruption
> - `TelegramPasswordFinder` discovers dialogs live from Telegram sessions (no DB required)
> - KV convenience helpers on `QIHSEResPServer`: `kv_set`, `kv_get`, `kv_setnx`, `kv_del`, `kv_expire`

## Goal

Integrate the MSNET (MEMSHADOW) Protocol v3 C implementation as the secure
transport and swarming layer for QIHSE RESP coordination. This enables
LAN-only, handshake-authenticated work distribution across multiple SPECTRA
nodes for file search, password finding, and other distributed tasks.

## Architecture

```
SPECTRA Node A (t420, 192.168.1.91)
  ├── MSNET listener (port 8899, TCP)
  │   ├── Handshake: PQC CSNA2.0 ZKP challenge-response
  │   ├── Peer manager: health, heartbeat, ban/evict
  │   └── Gossip: epidemic broadcast for node discovery
  ├── QIHSE RESP server (port 6379, LAN-bound)
  │   └── Work items, claims, results in KV store
  ├── Swarm coordinator
  │   ├── Dialog discovery → distribute to peers
  │   ├── Work stealing (stale claims after TTL)
  │   └── Result aggregation
  └── 4 Telegram sessions

SPECTRA Node B (laptop, 192.168.1.50)
  ├── MSNET listener (joins swarm via gossip)
  ├── QIHSE RESP client → connects to Node A
  ├── 2 Telegram sessions
  └── Receives work assignments, returns results
```

## MSNET Components — Only What We Need

From the C implementation, we vendor ONLY these 6 files + headers:

| File | Purpose | Kept |
|------|---------|------|
| `memshadow.c/h` | Core protocol: 32-byte header, framing, HMAC | YES |
| `memshadow_handshake.c/h` | PQC ZKP challenge-response auth | YES |
| `memshadow_session.c/h` | Session keys, rotation, timeout | YES |
| `memshadow_peer_manager.c/h` | Health monitoring, ban, evict | YES |
| `memshadow_pqc.c/h` | Post-quantum crypto primitives | YES |
| `memshadow_gossip.c/h` | Epidemic broadcast for node discovery | YES |

**Stripped out (not needed on trusted LAN):**

| File | Reason for removal |
|------|-------------------|
| `memshadow_dpi_evasion.c/h` | No DPI on LAN |
| `memshadow_traffic_analysis_resistance.c/h` | No traffic analysis adversary |
| `memshadow_covert_vlan.c/h` | No covert channels needed |
| `memshadow_vlan_topology.c/h` | Flat LAN, no mesh routing |
| `memshadow_morphic.c/h` | No protocol morphing needed |
| `memshadow_stealth.c/h` | No stealth needed |
| `memshadow_tls.c/h` | PQC handshake replaces TLS |
| `memshadow_temporal.c/h` | No temporal/quantum messaging |
| `memshadow_relay.c/h` | No relay paths on flat LAN |
| `memshadow_file_transfer.c/h` | We send work items, not files |
| `memshadow_hub_fingerprint.c/h` | No hub fingerprinting |
| `memshadow_pfs.c/h` | PQC session keys sufficient for LAN |
| `w-slam-server/` | Full stealth server — not needed |

**Dependencies:** OpenSSL (libcrypto), zlib — both already present.

## Message Types Used (subset)

| Type | Code | Purpose |
|------|------|---------|
| `MSG_HANDSHAKE` | 0x0004 | Secure handshake |
| `MSG_HEARTBEAT` | 0x0001 | Keepalive + health |
| `MSG_NODE_REGISTER` | 0x0401 | Join swarm |
| `MSG_NODE_DEREGISTER` | 0x0402 | Leave swarm |
| `MSG_QUERY_DISTRIBUTE` | 0x0403 | Work assignment |
| `MSG_QUERY_RESPONSE` | 0x0404 | Work result |
| `MSG_MEMORY_STORE` | 0x0301 | Store result in KV |
| `MSG_MEMORY_QUERY` | 0x0302 | Query KV |
| `MSG_MEMORY_SYNC` | 0x0304 | Sync state across nodes |

## Implementation Steps

### Step 1: Vendor MSNET C core (6 files only)

- Copy only these into `tgarchive/native/msnet/`:
  - `memshadow.c/h` — core protocol
  - `memshadow_handshake.c/h` — auth
  - `memshadow_session.c/h` — sessions
  - `memshadow_peer_manager.c/h` — peer health
  - `memshadow_pqc.c/h` — crypto
  - `memshadow_gossip.c/h` — discovery
- Create minimal `Makefile` that builds only these 6 .c files
- Output: `tgarchive/native/msnet/libmemshadow.so`
- Link: `-lcrypto -lz` (already present)
- No AVX — scalar only (t420)
- Add `.so` to `.gitignore`
- **Files:** `tgarchive/native/msnet/*` (6 .c + 6 .h + Makefile)
- **Difficulty:** Low
- **% codebase touched:** ~0.1% (new files only)

### Step 2: Python ctypes bindings for MSNET core

- Create `tgarchive/search/msnet_bindings.py`
- Wrap only the functions we need:
  - `memshadow_init()` — initialize protocol
  - `memshadow_handshake_init()` — create handshake context
  - `memshadow_handshake_create_hello()` — generate hello
  - `memshadow_handshake_process_hello()` — process incoming hello
  - `memshadow_handshake_process_challenge_response()` — verify auth
  - `memshadow_session_create()` — establish session
  - `memshadow_peer_manager_init/add/remove/find/tick/ban()` — peer management
  - `memshadow_peer_record_ping/record_ping_failure/is_healthy()` — health
  - `memshadow_gossip_*` — gossip broadcast (init, add peer, tick, broadcast)
  - `memshadow_send/recv` — message framing
- Define ctypes structs for `memshadow_handshake_ctx_t`, `memshadow_peer_info_t`, `memshadow_gossip_manager_t`
- Graceful `ImportError`/`OSError` fallback if `.so` not available
- **Files:** `tgarchive/search/msnet_bindings.py`
- **Difficulty:** Medium
- **% codebase touched:** ~0.2%

### Step 3: QIHSE RESP server ctypes wrapper

- Create `tgarchive/search/qihse_resp_server.py`
- Wrap `qihse_resp_server_config_init`, `qihse_resp_server_create`, `qihse_resp_server_start`, `qihse_resp_server_run`, `qihse_resp_server_stop`, `qihse_resp_server_destroy`
- Configure KV store from existing `qihse_bindings.py`
- Run `qihse_resp_server_run` in background thread (blocking call)
- Expose: `start()`, `stop()`, `is_running()`, `port()`, `ping()`
- Bind to LAN address (configurable, not 0.0.0.0)
- **Files:** `tgarchive/search/qihse_resp_server.py`
- **Difficulty:** Medium
- **% codebase touched:** ~0.1%

### Step 4: MSNET secure transport layer

- Create `tgarchive/search/msnet_transport.py`
- TCP server on configured port (default 8899)
- On incoming connection:
  1. Receive MSNET hello message (32-byte header + payload)
  2. Process handshake via `memshadow_handshake_process_hello()`
  3. Send challenge → receive response → verify via `memshadow_handshake_process_challenge_response()`
  4. If auth fails → `memshadow_peer_ban()`, close connection
  5. If auth succeeds → `memshadow_session_create()`, `memshadow_peer_add()`
  6. Enter message loop: heartbeat, work distribution, results
- LAN-only enforcement: reject connections outside configured CIDR
- Heartbeat every 30s via `MSG_HEARTBEAT`
- Stale peers evicted after 90s via `memshadow_peer_tick()`
- **Files:** `tgarchive/search/msnet_transport.py`
- **Difficulty:** Medium-High
- **% codebase touched:** ~0.3%

### Step 5: Swarm coordinator

- Create `tgarchive/search/swarm_coordinator.py`
- Node identity: hostname + UUID, persisted to config
- Swarm registry in QIHSE KV:
  - `spectra:swarm:nodes` → set of node IDs
  - `spectra:swarm:node:<id>` → JSON {node_id, address, capabilities, sessions, last_heartbeat}
- Work distribution protocol:
  1. Originating node discovers dialogs (Telegram sessions)
  2. Dialogs split across all swarm nodes (weighted by session count)
  3. `MSG_QUERY_DISTRIBUTE` sent to each peer with assigned dialog list
  4. Peers search their assigned dialogs via Telethon
  5. Results sent back via `MSG_QUERY_RESPONSE`
  6. Originating node aggregates and deduplicates
- Work stealing:
  - Claims have TTL (10 min default) in QIHSE KV
  - If peer heartbeat stops, claims expire
  - Other nodes can steal expired claims via `SETNX`
- Single-node fallback: if no peers, do everything locally
- **Files:** `tgarchive/search/swarm_coordinator.py`
- **Difficulty:** High
- **% codebase touched:** ~0.4%

### Step 6: Integrate swarm into TelegramPasswordFinder

- Modify `tgarchive/services/async_file_search.py`
- `TelegramPasswordFinder.find_passwords()`:
  1. Start QIHSE RESP server (if not running, auto-start)
  2. Start MSNET transport (if not running, auto-start)
  3. Join swarm (register node, gossip announce)
  4. Discover dialogs across local sessions
  5. Publish dialog list + node capabilities to swarm
  6. Coordinator assigns dialogs to nodes (including self)
  7. Search locally assigned dialogs
  8. Receive results from peers via MSNET
  9. Aggregate all results, dedup passwords per file
  10. Write passwords back to source file
- Single-node mode: if no peers discovered, current behavior (QIHSE/SQLite coord)
- **Files:** `tgarchive/services/async_file_search.py` (modify)
- **Difficulty:** Medium
- **% codebase touched:** ~0.5%

### Step 7: Config and CLI commands

- Add to `tgarchive/core/config_models.py`:
  - `resp.port` (default 6379)
  - `resp.bind_address` (default 192.168.1.91)
  - `resp.lan_cidr` (default 192.168.1.0/24)
  - `resp.auto_start` (default true)
  - `resp.max_clients` (default 64)
  - `msnet.port` (default 8899)
  - `msnet.cluster_name` (default "SPECTRA")
  - `msnet.heartbeat_interval` (default 30)
  - `msnet.node_timeout` (default 90)
  - `swarm.enabled` (default true)
  - `swarm.node_id` (default auto: hostname + UUID)
  - `swarm.bootstrap_peers` (default [])
- CLI commands:
  - `spectra index resp start|stop|status|restart`
  - `spectra swarm join|leave|status|nodes`
- **Files:** `tgarchive/cli/app.py`, `tgarchive/core/config_models.py`
- **Difficulty:** Low-Medium
- **% codebase touched:** ~0.3%

### Step 8: systemd user service

- Create `~/.config/systemd/user/qihse-resp.service`
- Auto-start on boot, restart on crash
- Runs `spectra index resp start --foreground`
- Logs to journald
- **Files:** `~/.config/systemd/user/qihse-resp.service`
- **Difficulty:** Low
- **% codebase touched:** 0%

### Step 9: Key generation

- Generate PQC CSNA2.0 keypair on first run
- Store in `~/.config/spectra/msnet_keys/`
- `spectra crypto generate-keys --protocol msnet`
- Share public keys with peers out-of-band or via trusted bootstrap
- **Files:** `tgarchive/cli/app.py` (modify crypto command)
- **Difficulty:** Low
- **% codebase touched:** ~0.1%

### Step 10: Tests

- Unit tests for MSNET bindings (handshake init/process, peer add/remove/ban)
- Integration test: two local nodes, handshake, work distribution
- Test: auth failure → peer banned
- Test: stale peer → evicted, work stolen
- Test: single-node fallback (no peers)
- Test: RESP server start/stop/ping
- **Files:** `tgarchive/tests/test_msnet_swarm.py`
- **Difficulty:** Medium
- **% codebase touched:** ~0.2%

## Summary

| Step | Description | Difficulty | Est. Lines |
|------|-------------|-----------|------------|
| 1 | Vendor MSNET C core (6 files) | Low | ~1200 (vendored) |
| 2 | Python ctypes bindings | Medium | ~350 |
| 3 | QIHSE RESP server wrapper | Medium | ~200 |
| 4 | MSNET secure transport | Medium-High | ~400 |
| 5 | Swarm coordinator | High | ~500 |
| 6 | Integrate into password finder | Medium | ~150 (modifications) |
| 7 | Config and CLI | Low-Medium | ~250 |
| 8 | systemd service | Low | ~30 |
| 9 | Key generation | Low | ~80 |
| 10 | Tests | Medium | ~350 |

**Total new code:** ~1900 lines (excluding vendored C)
**Vendored C:** ~1200 lines (6 files, stripped from ~3000)
**Total codebase touched:** ~2%
**Build deps:** libcrypto (OpenSSL), libz — both already present

## Security Properties

- **LAN-only**: Connections rejected outside configured CIDR
- **PQC authentication**: CSNA2.0 ZKP handshake (quantum-resistant)
- **Integrity**: HMAC-SHA256 per message
- **Replay protection**: Nonces + timestamps
- **Peer banning**: Auth failures → 1hr ban
- **No cloud**: All coordination local, no external dependencies
- **Graceful degradation**: No peers → single-node, no MSNET → SQLite fallback

## What We Stripped and Why

| Component | Why removed |
|-----------|-------------|
| DPI evasion | No DPI on LAN |
| Traffic analysis resistance | No adversary on LAN |
| Covert VLAN | No covert channels needed |
| VLAN topology / mesh routing | Flat LAN |
| Protocol morphing | No statistical adversary |
| Stealth | Trusted LAN |
| TLS | PQC handshake replaces it |
| Temporal/quantum messaging | Not needed |
| Relay paths | Flat LAN |
| File transfer | Work items, not files |
| Hub fingerprinting | Not needed |
| PFS | PQC session keys sufficient |
| w-slam-server | Full stealth server — overkill |

## Rollout

1. Steps 1-3: Build and bind (no behavior change)
2. Steps 4-5: Transport and swarm (opt-in via config)
3. Steps 6-7: Integration and CLI (default on for LAN)
4. Steps 8-9: Auto-start and keys
5. Step 10: Tests and verification
