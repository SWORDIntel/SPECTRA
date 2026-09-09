"""
QIHSE Sync — Gossip Protocol + CRDT Python Bindings
====================================================

ctypes wrapper for QIHSE's distributed sync stack:
- Gossip protocol (epidemic broadcast, peer discovery, anti-entropy)
- CRDT LWW-Set (conflict-free replicated data types)
- ML-DSA-87 post-quantum message signatures

This enables multiple SPECTRA instances on the same LAN to:
1. Discover each other via peer lists or mDNS
2. Replicate IndexOutbox events via gossip
3. Reconcile state differences via anti-entropy (Bloom filter comparison)
4. Resolve write conflicts via CRDT last-writer-wins

The C layer is in QIHSE/sync/qihse_sync_gossip.{c,h} and
QIHSE/sync/qihse_crdt.{c,h}, compiled into libqihse.so.
"""

from __future__ import annotations

import ctypes
import logging
import os
import socket
import struct
import time
from ctypes import (
    c_void_p, c_size_t, c_double, c_float, c_uint32, c_uint64, c_uint16, c_bool,
    c_int, c_char, c_char_p, POINTER, Structure, byref,
)
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Sync command types (from qihse_sync_gossip.h) ──────────────────────────

QIHSE_SYNC_CMD_HEARTBEAT = 0
QIHSE_SYNC_CMD_PEER_DISCOVERY = 1
QIHSE_SYNC_CMD_ROUTE_UPDATE = 2
QIHSE_SYNC_CMD_DATA_REPLICATE = 3
QIHSE_SYNC_CMD_FAILURE_NOTICE = 4
QIHSE_SYNC_CMD_METADATA_SYNC = 5

# ── C structures ───────────────────────────────────────────────────────────

_MLDSA87_SIG_SIZE = 4627
_UUID_SIZE = 16
_SHA384_SIZE = 48


class QihseSyncPeer(Structure):
    """qihse_sync_peer_t — gossip peer information."""
    _fields_ = [
        ("peer_id", c_char_p),
        ("address", c_char_p),
        ("port", c_uint16),
        ("last_seen", c_uint64),
        ("heartbeat_count", c_uint32),
        ("suspicion_level", c_float),
    ]


class QihseSyncMessage(Structure):
    """qihse_sync_message_t — gossip message with PQC signature."""
    _fields_ = [
        ("id", c_char * _UUID_SIZE),
        ("command_type", c_int),
        ("sender_id", c_char_p),
        ("payload", c_void_p),
        ("payload_size", c_size_t),
        ("timestamp", c_uint64),
        ("ttl", c_uint32),
        ("hop_count", c_uint32),
        ("mldsa87_signature", c_char * _MLDSA87_SIG_SIZE),
        ("has_signature", c_bool),
    ]


class QihseSyncOutgoingMessage(Structure):
    """qihse_sync_outgoing_message_t — message targeted to a specific peer."""
    _fields_ = [
        ("peer_id", c_char_p),
        ("message", QihseSyncMessage),
    ]


class QihseSyncStatistics(Structure):
    """qihse_sync_statistics_t — gossip manager stats."""
    _fields_ = [
        ("total_peers", c_size_t),
        ("seen_messages", c_size_t),
        ("queued_messages", c_size_t),
        ("suspected_failures", c_size_t),
    ]


class QihseCrdtRecord(Structure):
    """qihse_crdt_record_t — LWW-set element."""
    _fields_ = [
        ("vector_id", c_char * _UUID_SIZE),
        ("timestamp", c_uint64),
        ("is_deleted", c_bool),
        ("payload_hash", c_char * _SHA384_SIZE),
    ]


class QihseTrinaryDagNode(Structure):
    """qihse_trinary_dag_node_t — forward-declared, opaque from Python."""
    _fields_ = [
        ("hash", c_char * _SHA384_SIZE),
        ("left", c_void_p),
        ("middle", c_void_p),
        ("right", c_void_p),
        ("records", c_void_p),
        ("record_count", c_size_t),
    ]


class QihseCrdtManager(Structure):
    """qihse_crdt_manager_t — CRDT manager with trinary Merkle DAG."""
    _fields_ = [
        ("dag_root", c_void_p),
        ("local_clock", c_uint64),
    ]


# ── Library loading ────────────────────────────────────────────────────────

def _load_qihse_lib() -> ctypes.CDLL | None:
    """Load libqihse.so with RTLD_GLOBAL (shared with VFS)."""
    possible_paths = [
        Path(__file__).resolve().parent.parent.parent / "QIHSE" / "libqihse.so",
        Path(__file__).resolve().parent.parent.parent / "libs" / "QIHSE" / "libqihse.so",
        Path("/usr/local/lib/libqihse.so"),
        Path("/usr/lib/libqihse.so"),
    ]
    for p in possible_paths:
        if p.exists():
            try:
                mode = getattr(os, "RTLD_GLOBAL", 0) | getattr(os, "RTLD_NOW", 0)
                lib = ctypes.CDLL(str(p), mode=mode)
                logger.info("Loaded QIHSE sync library from %s", p)
                return lib
            except OSError as e:
                logger.debug("Failed to load %s: %s", p, e)
    try:
        mode = getattr(os, "RTLD_GLOBAL", 0) | getattr(os, "RTLD_NOW", 0)
        lib = ctypes.CDLL("libqihse.so", mode=mode)
        logger.info("Loaded QIHSE sync library from system path")
        return lib
    except OSError:
        logger.warning("QIHSE library not found — sync features unavailable")
        return None


_lib = _load_qihse_lib()

# ── Function signatures ────────────────────────────────────────────────────

if _lib is not None:
    # Peer functions
    _lib.qihse_sync_peer_init.argtypes = [
        POINTER(QihseSyncPeer), c_char_p, c_char_p, c_uint16,
    ]
    _lib.qihse_sync_peer_init.restype = c_int

    _lib.qihse_sync_peer_cleanup.argtypes = [POINTER(QihseSyncPeer)]
    _lib.qihse_sync_peer_cleanup.restype = None

    _lib.qihse_sync_peer_update_last_seen.argtypes = [POINTER(QihseSyncPeer)]
    _lib.qihse_sync_peer_update_last_seen.restype = None

    _lib.qihse_sync_peer_increase_suspicion.argtypes = [POINTER(QihseSyncPeer)]
    _lib.qihse_sync_peer_increase_suspicion.restype = None

    _lib.qihse_sync_peer_is_suspected_failed.argtypes = [
        POINTER(QihseSyncPeer), c_float,
    ]
    _lib.qihse_sync_peer_is_suspected_failed.restype = c_bool

    # Message functions
    _lib.qihse_sync_message_init.argtypes = [
        POINTER(QihseSyncMessage), c_int, c_char_p,
        c_void_p, c_size_t, c_uint32,
    ]
    _lib.qihse_sync_message_init.restype = c_int

    _lib.qihse_sync_message_cleanup.argtypes = [POINTER(QihseSyncMessage)]
    _lib.qihse_sync_message_cleanup.restype = None

    _lib.qihse_sync_message_is_expired.argtypes = [POINTER(QihseSyncMessage)]
    _lib.qihse_sync_message_is_expired.restype = c_bool

    _lib.qihse_sync_message_decrement_ttl.argtypes = [POINTER(QihseSyncMessage)]
    _lib.qihse_sync_message_decrement_ttl.restype = None

    # Manager functions
    _lib.qihse_sync_manager_init.argtypes = [
        POINTER(c_void_p),  # qihse_sync_manager_t** (opaque from Python)
        c_char_p, c_uint32, c_uint64,
    ]
    _lib.qihse_sync_manager_init.restype = c_int

    _lib.qihse_sync_manager_cleanup.argtypes = [c_void_p]
    _lib.qihse_sync_manager_cleanup.restype = None

    _lib.qihse_sync_manager_add_peer.argtypes = [
        c_void_p, QihseSyncPeer,
    ]
    _lib.qihse_sync_manager_add_peer.restype = c_int

    _lib.qihse_sync_manager_remove_peer.argtypes = [
        c_void_p, c_char_p,
    ]
    _lib.qihse_sync_manager_remove_peer.restype = c_bool

    _lib.qihse_sync_manager_broadcast_message.argtypes = [
        c_void_p, c_int, c_void_p, c_size_t, c_uint32,
    ]
    _lib.qihse_sync_manager_broadcast_message.restype = c_int

    _lib.qihse_sync_manager_receive_message.argtypes = [
        c_void_p, QihseSyncMessage, c_char_p,
    ]
    _lib.qihse_sync_manager_receive_message.restype = c_int

    _lib.qihse_sync_manager_perform_gossip_round.argtypes = [
        c_void_p,
        POINTER(POINTER(QihseSyncOutgoingMessage)),
        POINTER(c_size_t),
    ]
    _lib.qihse_sync_manager_perform_gossip_round.restype = c_int

    _lib.qihse_sync_outgoing_messages_cleanup.argtypes = [
        POINTER(QihseSyncOutgoingMessage), c_size_t,
    ]
    _lib.qihse_sync_outgoing_messages_cleanup.restype = None

    _lib.qihse_sync_manager_run_failure_detection.argtypes = [c_void_p]
    _lib.qihse_sync_manager_run_failure_detection.restype = c_int

    _lib.qihse_sync_manager_get_statistics.argtypes = [
        c_void_p, POINTER(QihseSyncStatistics),
    ]
    _lib.qihse_sync_manager_get_statistics.restype = None

    _lib.qihse_sync_manager_cleanup_old_messages.argtypes = [
        c_void_p, c_uint64,
    ]
    _lib.qihse_sync_manager_cleanup_old_messages.restype = None

    _lib.qihse_sync_manager_perform_anti_entropy.argtypes = [
        c_void_p,
        c_void_p,  # remote_bloom_filter
        c_size_t,  # filter_size
        POINTER(POINTER(QihseSyncMessage)),  # missing_messages
        POINTER(c_size_t),  # missing_count
    ]
    _lib.qihse_sync_manager_perform_anti_entropy.restype = c_int

    # CRDT functions
    _lib.qihse_crdt_init.argtypes = [POINTER(QihseCrdtManager)]
    _lib.qihse_crdt_init.restype = c_bool

    _lib.qihse_crdt_destroy.argtypes = [POINTER(QihseCrdtManager)]
    _lib.qihse_crdt_destroy.restype = None

    _lib.qihse_crdt_upsert.argtypes = [
        POINTER(QihseCrdtManager),
        c_char_p,  # vector_id[16]
        c_uint64,  # timestamp
        c_bool,    # is_deleted
        c_char_p,  # payload_hash[48]
    ]
    _lib.qihse_crdt_upsert.restype = c_bool

    _lib.qihse_crdt_get_root_hash.argtypes = [
        POINTER(QihseCrdtManager),
        c_char_p,  # out_hash[48]
    ]
    _lib.qihse_crdt_get_root_hash.restype = None


# ── Python wrappers ────────────────────────────────────────────────────────

class SyncUnavailableError(RuntimeError):
    """Raised when QIHSE sync library is not loaded."""


class QihseSyncManager:
    """High-level Python wrapper for QIHSE gossip sync manager.

    Wraps the C gossip manager to provide:
    - Peer management (add/remove peers)
    - Message broadcasting (with PQC signatures)
    - Gossip rounds (fan-out to random peers)
    - Anti-entropy sync (Bloom filter comparison)
    - Failure detection (suspicion-based)
    - Statistics reporting
    """

    def __init__(
        self,
        node_id: str,
        *,
        fan_out: int = 3,
        gossip_interval_ms: int = 1000,
    ) -> None:
        if _lib is None:
            raise SyncUnavailableError("QIHSE library not loaded")
        self._node_id = node_id.encode("utf-8")
        self._manager = c_void_p()
        # The C function expects qihse_sync_manager_t** which we pass as
        # POINTER(c_void_p). The actual struct is opaque from Python.
        ret = _lib.qihse_sync_manager_init(
            byref(self._manager),
            self._node_id,
            c_uint32(fan_out),
            c_uint64(gossip_interval_ms),
        )
        if ret != 0:
            raise RuntimeError(f"qihse_sync_manager_init failed: {ret}")
        self._closed = False
        logger.info("QIHSE sync manager initialized: node=%s fan_out=%d", node_id, fan_out)

    def add_peer(self, peer_id: str, address: str, port: int) -> bool:
        """Add a peer to the gossip network."""
        if self._closed:
            return False
        peer = QihseSyncPeer()
        ret = _lib.qihse_sync_peer_init(
            byref(peer),
            peer_id.encode("utf-8"),
            address.encode("utf-8"),
            c_uint16(port),
        )
        if ret != 0:
            logger.error("Failed to init peer %s: %d", peer_id, ret)
            return False
        ret = _lib.qihse_sync_manager_add_peer(self._manager, peer)
        if ret != 0:
            logger.error("Failed to add peer %s: %d", peer_id, ret)
            return False
        logger.info("Added peer: %s @ %s:%d", peer_id, address, port)
        return True

    def remove_peer(self, peer_id: str) -> bool:
        """Remove a peer from the gossip network."""
        if self._closed:
            return False
        return bool(_lib.qihse_sync_manager_remove_peer(
            self._manager, peer_id.encode("utf-8"),
        ))

    def broadcast(
        self,
        command_type: int,
        payload: bytes,
        ttl: int = 10,
    ) -> bool:
        """Broadcast a message to the gossip network.

        Args:
            command_type: One of QIHSE_SYNC_CMD_*
            payload: Message payload bytes (max ~11KB after PQC signature overhead)
            ttl: Time-to-live for gossip propagation

        Returns:
            True if the message was queued for gossip.
        """
        if self._closed:
            return False
        # TLS 1.3 max record = 16384, ML-DSA-87 sig = 4627, overhead ~256
        max_payload = 16384 - _MLDSA87_SIG_SIZE - 256
        if len(payload) > max_payload:
            logger.warning("Payload too large (%d > %d), truncating", len(payload), max_payload)
            payload = payload[:max_payload]
        buf = ctypes.create_string_buffer(payload, len(payload))
        ret = _lib.qihse_sync_manager_broadcast_message(
            self._manager,
            c_int(command_type),
            buf,
            c_size_t(len(payload)),
            c_uint32(ttl),
        )
        if ret != 0:
            logger.error("Broadcast failed: %d", ret)
            return False
        return True

    def receive(self, message: QihseSyncMessage, from_peer: str) -> int:
        """Receive a sync message from a peer.

        Returns 0 on success, -1 on error, 1 if duplicate (ignored).
        """
        if self._closed:
            return -1
        return int(_lib.qihse_sync_manager_receive_message(
            self._manager,
            message,
            from_peer.encode("utf-8"),
        ))

    def gossip_round(self) -> list[QihseSyncOutgoingMessage]:
        """Perform one gossip round — returns outgoing messages to send.

        The caller is responsible for sending these messages to their
        target peers over the network, then calling cleanup.
        """
        if self._closed:
            return []
        outgoing = POINTER(QihseSyncOutgoingMessage)()
        count = c_size_t(0)
        ret = _lib.qihse_sync_manager_perform_gossip_round(
            self._manager,
            byref(outgoing),
            byref(count),
        )
        if ret != 0:
            logger.error("Gossip round failed: %d", ret)
            return []
        result = []
        for i in range(count.value):
            result.append(outgoing[i])
        # Note: caller must call cleanup_outgoing when done with the messages
        self._pending_outgoing = (outgoing, count.value)
        return result

    def cleanup_outgoing(self) -> None:
        """Free memory from the last gossip_round()."""
        if hasattr(self, "_pending_outgoing"):
            outgoing, count = self._pending_outgoing
            if count > 0:
                _lib.qihse_sync_outgoing_messages_cleanup(outgoing, count)
            del self._pending_outgoing

    def run_failure_detection(self) -> int:
        """Run one round of failure detection on peers."""
        if self._closed:
            return -1
        return int(_lib.qihse_sync_manager_run_failure_detection(self._manager))

    def get_stats(self) -> dict[str, Any]:
        """Return gossip statistics."""
        if self._closed:
            return {}
        stats = QihseSyncStatistics()
        _lib.qihse_sync_manager_get_statistics(self._manager, byref(stats))
        return {
            "total_peers": stats.total_peers,
            "seen_messages": stats.seen_messages,
            "queued_messages": stats.queued_messages,
            "suspected_failures": stats.suspected_failures,
        }

    def cleanup_old_messages(self, max_age_ns: int) -> None:
        """Remove seen messages older than max_age_ns nanoseconds."""
        if self._closed:
            return
        _lib.qihse_sync_manager_cleanup_old_messages(
            self._manager, c_uint64(max_age_ns),
        )

    def anti_entropy(
        self,
        remote_bloom: bytes,
    ) -> list[QihseSyncMessage]:
        """Perform anti-entropy sync using a remote Bloom filter.

        The remote peer sends its Bloom filter of seen message IDs.
        We return messages that the remote peer is missing.

        Args:
            remote_bloom: Bloom filter bytes from the remote peer.

        Returns:
            List of messages the remote peer is missing.
        """
        if self._closed:
            return []
        buf = ctypes.create_string_buffer(remote_bloom, len(remote_bloom))
        missing = POINTER(QihseSyncMessage)()
        missing_count = c_size_t(0)
        ret = _lib.qihse_sync_manager_perform_anti_entropy(
            self._manager,
            buf,
            c_size_t(len(remote_bloom)),
            byref(missing),
            byref(missing_count),
        )
        if ret != 0:
            logger.error("Anti-entropy failed: %d", ret)
            return []
        result = []
        for i in range(missing_count.value):
            result.append(missing[i])
        # Free the C-allocated array (the messages themselves are copies)
        if missing_count.value > 0:
            ctypes.free(missing)
        return result

    def close(self) -> None:
        """Cleanup and free all resources."""
        if self._closed:
            return
        self.cleanup_outgoing()
        if self._manager:
            _lib.qihse_sync_manager_cleanup(self._manager)
            self._manager = None
        self._closed = True
        logger.info("QIHSE sync manager closed")

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class QihseCrdt:
    """High-level Python wrapper for QIHSE CRDT LWW-Set.

    Provides conflict-free replication for IndexOutbox events:
    - Each event gets a (vector_id, timestamp, payload_hash) record
    - Last-writer-wins resolution via timestamps
    - Trinary Merkle DAG for efficient state comparison
    - Root hash comparison enables fast anti-entropy
    """

    def __init__(self) -> None:
        if _lib is None:
            raise SyncUnavailableError("QIHSE library not loaded")
        self._manager = QihseCrdtManager()
        if not _lib.qihse_crdt_init(byref(self._manager)):
            raise RuntimeError("qihse_crdt_init failed")
        self._closed = False
        logger.info("QIHSE CRDT manager initialized")

    def upsert(
        self,
        vector_id: bytes,  # 16-byte UUID
        timestamp: int,     # uint64 logical/physical clock
        is_deleted: bool,
        payload_hash: bytes,  # 48-byte SHA-384
    ) -> bool:
        """Insert or update a record using LWW rules.

        Returns True if the local state was modified (incoming record
        was newer), False if the incoming record was older and ignored.
        """
        if self._closed:
            return False
        if len(vector_id) != _UUID_SIZE:
            raise ValueError(f"vector_id must be {_UUID_SIZE} bytes, got {len(vector_id)}")
        if len(payload_hash) != _SHA384_SIZE:
            raise ValueError(f"payload_hash must be {_SHA384_SIZE} bytes, got {len(payload_hash)}")
        vid = ctypes.create_string_buffer(vector_id, _UUID_SIZE)
        ph = ctypes.create_string_buffer(payload_hash, _SHA384_SIZE)
        return bool(_lib.qihse_crdt_upsert(
            byref(self._manager),
            vid,
            c_uint64(timestamp),
            c_bool(is_deleted),
            ph,
        ))

    def get_root_hash(self) -> bytes:
        """Return the SHA-384 root hash of the trinary Merkle DAG.

        Compare this between peers to determine if anti-entropy sync
        is needed. If the root hashes match, the states are identical.
        """
        if self._closed:
            return b"\x00" * _SHA384_SIZE
        out = ctypes.create_string_buffer(_SHA384_SIZE)
        _lib.qihse_crdt_get_root_hash(byref(self._manager), out)
        return bytes(out.raw[:_SHA384_SIZE])

    @property
    def local_clock(self) -> int:
        """Current local logical clock value."""
        return int(self._manager.local_clock)

    def close(self) -> None:
        """Cleanup and free the DAG."""
        if self._closed:
            return
        _lib.qihse_crdt_destroy(byref(self._manager))
        self._closed = True
        logger.info("QIHSE CRDT manager closed")

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


# ── Utility functions ──────────────────────────────────────────────────────

def get_node_id() -> str:
    """Generate a unique node ID for this SPECTRA instance.

    Uses hostname + process PID + timestamp for uniqueness.
    """
    return f"spectra-{socket.gethostname()}-{os.getpid()}-{int(time.time())}"


def get_local_ip() -> str:
    """Get the primary local IP address for LAN peer discovery."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def is_sync_available() -> bool:
    """Check if QIHSE sync library is available."""
    return _lib is not None
