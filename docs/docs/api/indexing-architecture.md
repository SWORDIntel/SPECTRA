---
id: indexing-architecture
title: Lookup And Indexing Architecture
sidebar_position: 3
description: QIHSE, KEYSTONE, SQLite, and concurrent SPECTRA data paths
tags: [api, architecture, sqlite, qihse, keystone, search]
---

# Lookup And Indexing Architecture

SPECTRA uses SQLite as the authoritative relational store and native lookup engines as derived indexes. This separates correctness-sensitive writes from high-volume lookup and search work.

## Responsibilities

| Layer | Responsibility | Write model |
| --- | --- | --- |
| SQLite | Authoritative relational state, committed index outbox, projection records, and projection state | Concurrent short transactions under WAL and a 60-second busy timeout |
| QIHSE | Persistent content vectors and typed relationship edges | Idempotent external-ID upserts and checkpointed graph writes after capability-gated library loading |
| SQLite FTS5 | Durable BM25 keyword lookup over allowlisted message fields | Transactional `fts.messages.v1` rows derived from committed outbox revisions |
| KEYSTONE | Deterministic compound keys for Telegram, checkpoint, event, export-record, and archive-member identities | Rebuild in-memory sorted integer views for native lookup and sampled verification |
| Filesystem export | Media bytes, byte-addressable JSONL manifests, resumable download state, logs | Atomic file promotion, binary manifest appends, and checkpoint updates |

The current SPECTRA QIHSE adapters provide vector upsert, persistence, semantic search, stable entity nodes, typed relationship edges, checkpoint/reopen persistence, graph queries, and sampled verification. They prefer the capability-compatible framewerx QIHSE build and run native work in child processes. Vector and graph operations acquire separate bounded OS advisory locks for their backing stores, preventing sync, query, rebuild, and verification processes from opening the same native file concurrently; the kernel releases a lock if its owner crashes. The KEYSTONE adapter builds sorted `int64_t` views for Telegram messages, media manifests, checkpoints, immutable task/operation events, export ordinals, and ZIP/TAR archive members.

References:

- [QIHSE](https://github.com/SWORDIntel/QIHSE)
- [KEYSTONE](https://github.com/SWORDIntel/KEYSTONE)

## Why SQLite Still Needs A Writer Boundary

WAL improves reader/writer overlap, but it does not create multiple simultaneous SQLite writers. SPECTRA therefore uses these rules:

- enable WAL for the primary database and task-registry sidecar;
- set a bounded busy timeout on every connection;
- initialize schema once per process startup, not inside every hot operation;
- keep write transactions short and avoid network calls while a transaction is open;
- commit source changes and their outbox events in the same short transaction where the producer supports it;
- run QIHSE and KEYSTONE index updates asynchronously from committed outbox rows;
- treat indexes as rebuildable projections, never as the only copy of authoritative metadata.

The downloader's media transfers remain concurrent. Their transfer concurrency is independent from SQLite write concurrency. Media bytes continue to land in the filesystem, while short SQLite transactions record metadata and index-outbox entries. Schema setup occurs when each command or long-running process initializes its outbox/projector, not for each record. The projector writes a claimed batch in one transaction, isolates malformed events with per-event savepoints, and acknowledges all successes/failures in one follow-up transaction.

## Data Flow

```text
Telegram workers
    |
    +--> filesystem media/.part -> atomic final media
    |
    +--> short SQLite transaction
             |
             +--> authoritative metadata/state
             |
             +--> committed index_outbox row
                        |
                        v
                 asynchronous projector
                        |
                        +--> SQLite projection records/state
                        +--> QIHSE content-vector database
                        +--> QIHSE typed relationship graph
                        +--> SQLite FTS5 keyword index
                        +--> KEYSTONE compound-key lookup views
                        +--> byte-addressable media manifest metadata
```

The commit order is authoritative data first, derived indexes second. A crash between those phases leaves an outbox item that can be replayed. Filesystem manifest appends cannot share SQLite's atomic commit; an interruption between the manifest append and outbox commit is reconciled by the idempotent `index backfill-export` operation. A stale or corrupt derived index is repaired by replay or full rebuild from SQLite and filesystem manifests.

The implemented projections are versioned as `keystone.ids.v1`, `keystone.media_manifest.v1`, `keystone.checkpoints.v1`, `keystone.events.v1`, `keystone.export_records.v1`, `keystone.archive_members.v1`, `qihse.content.v1`, `qihse.graph.v1`, and `fts.messages.v1`. Projection records remain in SQLite for deterministic replay and checksums. QIHSE vectors and graphs are materialized into `<database>.qihse.qdb` and `<database>.graph.qdb`; KEYSTONE operates over sorted integer views. Native work runs in a child process so a library ABI failure becomes a structured verification failure instead of terminating the CLI.

Outbox acknowledgement occurs only after the QIHSE child confirms persistence. Incremental synchronization receives only the current batch's sequence IDs. Failed delivery remains retryable for five attempts and then stays visible as failed without causing an unbounded drain loop. `index verify` exits with code `7` when counts, checksums, state, or native samples disagree.

## Index Keys And Projections

KEYSTONE currently indexes:

- a deterministic signed `int64_t` key derived from `(channel_id, message_id)`;
- the matching SQLite projection records used to recover authoritative payloads after native lookup;
- media-manifest path, byte offset, byte length, record SHA-256, media path, media size, media checksum, and transfer state;
- immutable checkpoint and task/operation event identities;
- persistent `(export_id, record_ordinal)` identities for byte-addressable export records;
- `(archive_id, member_index)` identities, where `archive_id` is derived from a verified content snapshot, plus ZIP/TAR header/data offsets, sizes, compression, CRC/header checksum, and member type.

Media manifests are written in binary append mode. The downloader serializes each JSON record once, captures the byte offset before writing, and stores the exact byte length and line checksum in the same committed outbox payload. Each export persists a UUID in `manifest.json`; record ordinals remain stable across resume and backfill. A unique SQLite identity map atomically rejects native-key collisions before revisions reference a key. Archive scans hash the immutable input snapshot before and after parsing, and ZIP entry counts are checked from EOCD/ZIP64 metadata before the standard library loads the central directory.

`index scan-archive` supports bounded ZIP and TAR metadata scans without opening or extracting member contents. It rejects encrypted, unsafe, duplicate, linked, sparse, ambiguous, mutated, or unsupported archives rather than producing uncertain offsets.

QIHSE content search indexes normalized, non-sensitive textual values from outbox payloads as deterministic hashed vectors. The graph adapter uses stable collision-checked entity IDs and currently projects `IN_CHANNEL`, `POSTED_BY`, `REPLIES_TO`, and crawler `DISCOVERED` edges. `index graph` resolves native edges back to authoritative SQLite node identities.

SQLite FTS5 indexes only `content`, `message`, `raw_text`, `text`, and `caption` from message producers. Queries suppress stale revisions and tombstones. QIHSE's in-memory FTS API is not used as a durable projection because it does not currently expose persistence, update, or delete operations.

The privacy-reviewed training adapter exports allowlisted `operation_audit` rows with versioned redaction, stable deduplication, execution outcome, provenance, and command/envelope agreement fields. It uses SQLite audit records as its authority; QIHSE product-quantization training is unrelated to operator corpus curation.

Every SQLite projection record carries its outbox sequence ID, source table and key, optional source revision, content hash, and projection name/version. This makes updates idempotent and makes rebuild drift measurable.

## Recovery And Rebuild

Each index has a state record containing:

- index name and version;
- last committed SQLite outbox sequence;
- row count and checksum;
- last successful update time;
- last error and state update time.

Recovery sequence:

1. Stop only the affected index consumer, not the Telegram transfer pool.
2. Inspect SQLite migration and outbox state.
3. Replay uncommitted outbox rows.
4. Verify source/index counts and sampled key lookups.
5. Rebuild the affected projection if checksums diverge.
6. Resume the consumer and record the recovery operation in the audit trail.

Operator commands:

```bash
spectra index status --output json
spectra index process --batch-size 1000 --output json
spectra index drain --batch-size 1000 --output json
spectra index watch --batch-size 1000 --poll-interval 0.1
spectra index rebuild --projection all --output json
spectra index verify --projection all --native --sample-size 32 --output json
spectra index lookup --channel-id -1002407846598 --message-id 12 --output json
spectra index checkpoint CHECKPOINT_ID --output json
spectra index event task EVENT_ID --output json
spectra index event operation EVENT_ID --output json
spectra index event audit EVENT_ID --output json
spectra index export-record EXPORT_ID RECORD_ORDINAL --output json
spectra index archive-member ARCHIVE_ID MEMBER_INDEX --output json
spectra index graph --node-type message --external-id=-1002407846598:12 --direction outgoing --output json
spectra index backfill-export /fast/ULPs/Channel_123 --output json
spectra index backfill-database --output json
spectra index scan-archive /fast/ULPs/archive.zip --limit 10000 --output json
spectra index benchmark --events 1000 --writers 16 --lookups 10 --output json
spectra search fulltext "wallet access" --output json
```

The identity-specific commands are the normal operator interface. `index checkpoint` accepts a positive checkpoint ID. `index event` accepts `task`, `operation`, or `audit` plus a positive event ID. `index export-record` and `index archive-member` address records by persistent parent ID and a zero-based ordinal or member index.

All four are convenience routes over the generic KEYSTONE interface:

```bash
spectra index lookup-record PROJECTION NAMESPACE EXTERNAL_ID --output json
```

Keep `lookup-record` for lower-level integrations that already carry projection and namespace metadata. For example, `index archive-member ARCHIVE_ID 0` maps to `index lookup-record archive-members ARCHIVE_ID 0`.

## Validation And Benchmarks

The implemented tests and verification paths cover:

- repeated outbox delivery is idempotent;
- concurrent short WAL transactions retain all submitted outbox events;
- KEYSTONE sampled compound-key lookup agrees with SQLite projection records;
- QIHSE vector results retain the exact source row identity, including duplicate-vector groups;
- index rebuild produces the same counts and checksums as incremental indexing;
- native work is isolated in a child process and reports structured failures.
- vector and graph native stores serialize cross-process access with bounded lock waits and crash-safe release;
- repeated KEYSTONE lookups reuse a crash-isolated child and reload from projection metadata plus ordered-key checksums when keys change;
- native persistence failures are not acknowledged and stop retrying after a bounded attempt count;
- supervised watchers emit redacted JSON diagnostics on stderr and exponentially back off after exceptions or failed batches;
- incremental native writes contain only the current outbox batch;
- media-manifest offsets seek to and verify the exact JSONL byte range;
- export backfill snapshots an actively appended manifest, ignores incomplete trailing records, and is rerunnable;
- expired worker leases are reclaimed after a simulated process crash, and stale owners cannot acknowledge reclaimed rows;
- the installed CLI entrypoint routes directly to the lazy modern command tree.

### Workstation Outbox Benchmark

A synthetic workstation benchmark submitted 1,000 message events from 16 writer threads after the graph and FTS upgrades. Writes completed in 0.757 seconds, or 1,321.0 events per second. Draining all events into content, graph, FTS, and KEYSTONE projections took 10.263 seconds. The batch created 1,051 graph nodes and 2,999 typed edges. Sampled native and SQLite verification across all five projection types completed in 3.793 seconds with no failures.

The earlier content-plus-KEYSTONE baseline completed writes in 0.902 seconds and projection drain in 4.522 seconds. The newer number includes the additional durable FTS and checkpointed graph work, so the two drain timings are not directly interchangeable.

A reproducible `index benchmark` run with 200 base events, eight writers, and 40 events written while projection batches were draining measured 1,100.86 initial writes/second, a 3.398-second initial drain, 3.046 ms warm KEYSTONE p50, and 557.453 ms p95 including isolated-worker cold start. Replaying 240 events across all five projections took 1.714 seconds. An intentionally expired lease was reclaimed on attempt two, and final native verification passed.

After serialized batch projection and acknowledgement replaced per-event commits, the same 200-event/eight-writer shape measured 1,436.64 initial writes/second and a 0.810-second drain. Warm KEYSTONE p50 was 1.815 ms, replay of 240 events took 0.803 seconds, crash recovery still reclaimed attempt two, and all nine projections passed native verification.

A live contention run kept the 32-transfer Telegram downloader active while the crawler read 100 messages from `-1001878378176`. The crawler found one relationship and committed four outbox events; an index watcher polling every 100 ms processed all four with zero failed events, worker errors, or SQLite lock failures.

L40S/H100 host measurements remain outstanding. Those hosts are training targets rather than runtime requirements for the workstation index. Run the same workload through `training/cloud_training_framework/remote_index_benchmark.py`; it requires an explicit SSH target, preflights working native QIHSE and KEYSTONE operations, uses bounded stage timeouts, and emits a redacted `spectra.remote-index-benchmark.v1` result.

The implementation is not a database replacement. It is a WAL-enabled SQLite write boundary plus rebuildable QIHSE and KEYSTONE projections that remove lookup work from the relational source of truth.
