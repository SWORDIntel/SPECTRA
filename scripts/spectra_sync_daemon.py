#!/usr/bin/env python3
"""
SPECTRA Sync Daemon
===================

Runs as a systemd service to replicate IndexOutbox events between
SPECTRA instances on the same LAN using QIHSE's gossip protocol + CRDT.

Architecture:
    ┌─────────────────────────────────────────────────┐
    │              Sync Daemon Process                 │
    │                                                  │
    │  ┌──────────┐    ┌──────────┐    ┌───────────┐  │
    │  │ UDP      │───►│ Gossip   │───►│ CRDT      │  │
    │  │ Server   │    │ Manager  │    │ Manager   │  │
    │  │ (port    │    │ (C lib)  │    │ (C lib)   │  │
    │  │  7900)   │◄───│          │◄───│           │  │
    │  └──────────┘    └──────────┘    └───────────┘  │
    │       │              │               │          │
    │       │              ▼               │          │
    │       │       ┌────────────┐         │          │
    │       │       │ IndexOutbox│◄────────┘          │
    │       │       │ (SQLite)   │                    │
    │       │       └────────────┘                    │
    │       │                                         │
    │  ┌────▼─────┐                                   │
    │  │ mDNS     │   "spectra-sync" service          │
    │  │ Broadcast│   discover peers on LAN           │
    │  └──────────┘                                   │
    └─────────────────────────────────────────────────┘

Protocol:
1. mDNS broadcast: "spectra-sync" service on port 7900
2. UDP heartbeat every 1s with node ID + IP
3. Gossip round every 5s: fan-out to 3 random peers
4. Anti-entropy every 30s: compare CRDT root hashes
5. On new outbox event: broadcast DATA_REPLICATE to peers
6. On receive: insert via CRDT LWW into local outbox

Usage:
    python3 scripts/spectra_sync_daemon.py --db data/spectra.db [--port 7900]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import signal
import socket
import struct
import sys
import threading
import time
import uuid
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tgarchive.db.index_outbox import IndexOutbox
from tgarchive.search.qihse_sync import (
    QihseSyncManager,
    QihseCrdt,
    is_sync_available,
    get_local_ip,
    QIHSE_SYNC_CMD_HEARTBEAT,
    QIHSE_SYNC_CMD_PEER_DISCOVERY,
    QIHSE_SYNC_CMD_DATA_REPLICATE,
    QIHSE_SYNC_CMD_METADATA_SYNC,
)

logger = logging.getLogger("spectra-sync")

# ── Protocol constants ─────────────────────────────────────────────────────

DEFAULT_PORT = 7900
HEARTBEAT_INTERVAL = 1.0       # seconds
GOSSIP_INTERVAL = 5.0          # seconds
ANTI_ENTROPY_INTERVAL = 30.0   # seconds
FAILURE_DETECTION_INTERVAL = 10.0
CLEANUP_INTERVAL = 60.0        # clean old seen messages every 60s
MAX_SEEN_AGE_NS = 3600 * 1_000_000_000  # 1 hour
MAX_PAYLOAD_SIZE = 11000       # leave room for PQC signature overhead
MAX_UDP_SIZE = 65507


# ── Wire protocol ──────────────────────────────────────────────────────────
#
# UDP message format (simple, before PQC signing at the C layer):
#   [1 byte version] [1 byte command] [2 bytes payload_len] [payload...]
#
# Commands:
#   0 = HEARTBEAT: payload = node_id\0ip\0port
#   1 = PEER_DISCOVERY: payload = node_id\0ip\0port
#   2 = DATA_REPLICATE: payload = JSON event
#   3 = ANTI_ENTROPY_REQUEST: payload = CRDT root hash (48 bytes)
#   4 = ANTI_ENTROPY_RESPONSE: payload = JSON array of missing events

WIRE_VERSION = 1
CMD_HEARTBEAT = 0
CMD_PEER_DISCOVERY = 1
CMD_DATA_REPLICATE = 2
CMD_ANTI_ENTROPY_REQ = 3
CMD_ANTI_ENTROPY_RESP = 4


def pack_wire(command: int, payload: bytes) -> bytes:
    """Pack a wire protocol message."""
    return struct.pack("!BBH", WIRE_VERSION, command, len(payload)) + payload


def unpack_wire(data: bytes) -> tuple[int, bytes] | None:
    """Unpack a wire protocol message. Returns (command, payload) or None."""
    if len(data) < 4:
        return None
    version, command, payload_len = struct.unpack("!BBH", data[:4])
    if version != WIRE_VERSION:
        return None
    if len(data) < 4 + payload_len:
        return None
    return command, data[4:4 + payload_len]


class SyncDaemon:
    """SPECTRA LAN sync daemon using QIHSE gossip + CRDT.

    Runs a UDP server for peer communication, periodically broadcasts
    heartbeats, performs gossip rounds, and replicates IndexOutbox events.
    """

    def __init__(
        self,
        db_path: str,
        *,
        port: int = DEFAULT_PORT,
        node_id: str | None = None,
        peers: list[tuple[str, int]] | None = None,
        enable_mdns: bool = True,
    ) -> None:
        self.db_path = db_path
        self.port = port
        self.node_id = node_id or f"spectra-{socket.gethostname()}-{port}"
        self.local_ip = get_local_ip()
        self.peers = peers or []  # list of (ip, port) tuples
        self.enable_mdns = enable_mdns
        self._running = False
        self._sock: socket.socket | None = None
        self._threads: list[threading.Thread] = []
        self._known_peers: dict[str, tuple[str, int, float]] = {}  # node_id -> (ip, port, last_seen)
        self._last_broadcast_seq = 0  # last outbox sequence we broadcast

        if not is_sync_available():
            raise RuntimeError("QIHSE sync library not available")

        self.outbox = IndexOutbox(db_path)
        self.sync_mgr = QihseSyncManager(
            self.node_id,
            fan_out=3,
            gossip_interval_ms=int(GOSSIP_INTERVAL * 1000),
        )
        self.crdt = QihseCrdt()
        logger.info("Sync daemon initialized: node=%s ip=%s port=%d", self.node_id, self.local_ip, self.port)

    def add_peer(self, ip: str, port: int) -> None:
        """Add a static peer."""
        self.peers.append((ip, port))
        peer_id = f"spectra-{ip}-{port}"
        self.sync_mgr.add_peer(peer_id, ip, port)
        logger.info("Added static peer: %s:%d", ip, port)

    def start(self) -> None:
        """Start the sync daemon."""
        self._running = True
        # Bind UDP socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.port))
        self._sock.settimeout(1.0)
        logger.info("UDP server listening on port %d", self.port)

        # Add static peers
        for ip, port in self.peers:
            self.add_peer(ip, port)

        # Start threads
        self._threads = [
            threading.Thread(target=self._recv_loop, daemon=True, name="sync-recv"),
            threading.Thread(target=self._heartbeat_loop, daemon=True, name="sync-heartbeat"),
            threading.Thread(target=self._gossip_loop, daemon=True, name="sync-gossip"),
            threading.Thread(target=self._anti_entropy_loop, daemon=True, name="sync-anti-entropy"),
            threading.Thread(target=self._failure_detection_loop, daemon=True, name="sync-fd"),
            threading.Thread(target=self._cleanup_loop, daemon=True, name="sync-cleanup"),
            threading.Thread(target=self._outbox_watch_loop, daemon=True, name="sync-watch"),
        ]
        if self.enable_mdns:
            self._threads.append(
                threading.Thread(target=self._mdns_loop, daemon=True, name="sync-mdns")
            )
        for t in self._threads:
            t.start()
        logger.info("Started %d daemon threads", len(self._threads))

    def stop(self) -> None:
        """Stop the sync daemon."""
        self._running = False
        for t in self._threads:
            t.join(timeout=5)
        if self._sock:
            self._sock.close()
        self.sync_mgr.close()
        self.crdt.close()
        logger.info("Sync daemon stopped")

    def get_status(self) -> dict:
        """Return current daemon status."""
        stats = self.sync_mgr.get_stats()
        return {
            "node_id": self.node_id,
            "local_ip": self.local_ip,
            "port": self.port,
            "running": self._running,
            "known_peers": len(self._known_peers),
            "peers": [
                {"node_id": nid, "ip": ip, "port": port, "last_seen": seen}
                for nid, (ip, port, seen) in self._known_peers.items()
            ],
            "gossip_stats": stats,
            "crdt_root_hash": self.crdt.get_root_hash().hex()[:16],
            "crdt_clock": self.crdt.local_clock,
            "last_broadcast_seq": self._last_broadcast_seq,
        }

    # ── Thread loops ───────────────────────────────────────────────────────

    def _recv_loop(self) -> None:
        """Receive UDP messages from peers."""
        while self._running:
            try:
                data, addr = self._sock.recvfrom(MAX_UDP_SIZE)
                self._handle_message(data, addr)
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_message(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle an incoming UDP message."""
        result = unpack_wire(data)
        if result is None:
            return
        command, payload = result
        ip, port = addr

        if command == CMD_HEARTBEAT or command == CMD_PEER_DISCOVERY:
            # payload = node_id\0ip\0port
            parts = payload.split(b"\x00")
            if len(parts) >= 3:
                peer_node_id = parts[0].decode("utf-8", errors="replace")
                peer_ip = parts[1].decode("utf-8", errors="replace") or ip
                peer_port = int.from_bytes(parts[2], "big") if parts[2] else port
                self._register_peer(peer_node_id, peer_ip, peer_port)
                if command == CMD_PEER_DISCOVERY:
                    # Respond with our heartbeat so they learn about us
                    self._send_heartbeat((ip, port))

        elif command == CMD_DATA_REPLICATE:
            # payload = JSON event
            try:
                event = json.loads(payload)
                self._receive_event(event, addr)
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug("Failed to parse replicate event: %s", e)

        elif command == CMD_ANTI_ENTROPY_REQ:
            # payload = remote CRDT root hash (48 bytes)
            if len(payload) == 48:
                self._handle_anti_entropy_request(payload, addr)

        elif command == CMD_ANTI_ENTROPY_RESP:
            # payload = JSON array of missing events
            try:
                events = json.loads(payload)
                for event in events:
                    self._receive_event(event, addr)
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug("Failed to parse anti-entropy response: %s", e)

    def _register_peer(self, node_id: str, ip: str, port: int) -> None:
        """Register or update a known peer."""
        now = time.time()
        if node_id not in self._known_peers:
            self._known_peers[node_id] = (ip, port, now)
            self.sync_mgr.add_peer(node_id, ip, port)
            logger.info("Discovered peer: %s @ %s:%d", node_id, ip, port)
        else:
            self._known_peers[node_id] = (ip, port, now)

    def _send_heartbeat(self, addr: tuple[str, int] | None = None) -> None:
        """Send a heartbeat to a specific peer or broadcast to all."""
        payload = (
            self.node_id.encode("utf-8") + b"\x00"
            + self.local_ip.encode("utf-8") + b"\x00"
            + self.port.to_bytes(2, "big")
        )
        msg = pack_wire(CMD_HEARTBEAT, payload)
        targets = [addr] if addr else [(ip, port) for ip, port in self.peers]
        targets += [(ip, port) for ip, port, _ in self._known_peers.values()]
        for target in set(targets):
            try:
                self._sock.sendto(msg, target)
            except OSError:
                pass

    def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self._running:
            self._send_heartbeat()
            time.sleep(HEARTBEAT_INTERVAL)

    def _gossip_loop(self) -> None:
        """Perform periodic gossip rounds via the C gossip manager."""
        while self._running:
            time.sleep(GOSSIP_INTERVAL)
            try:
                outgoing = self.sync_mgr.gossip_round()
                if outgoing:
                    logger.debug("Gossip round: %d outgoing messages", len(outgoing))
                self.sync_mgr.cleanup_outgoing()
            except Exception as e:
                logger.debug("Gossip round error: %s", e)

    def _anti_entropy_loop(self) -> None:
        """Periodically compare CRDT root hashes with peers."""
        while self._running:
            time.sleep(ANTI_ENTROPY_INTERVAL)
            root_hash = self.crdt.get_root_hash()
            msg = pack_wire(CMD_ANTI_ENTROPY_REQ, root_hash)
            for ip, port, _ in self._known_peers.values():
                try:
                    self._sock.sendto(msg, (ip, port))
                except OSError:
                    pass
            logger.debug("Sent anti-entropy requests to %d peers", len(self._known_peers))

    def _handle_anti_entropy_request(self, remote_root: bytes, addr: tuple[str, int]) -> None:
        """Handle an anti-entropy request — send missing events if roots differ."""
        local_root = self.crdt.get_root_hash()
        if remote_root == local_root:
            return  # states are identical
        # Roots differ — send our recent events to the requester
        events = self.outbox.get_unsynced_events(0, limit=50)
        if events:
            payload = json.dumps(events, default=str).encode("utf-8")
            if len(payload) > MAX_UDP_SIZE - 4:
                payload = payload[:MAX_UDP_SIZE - 4]
            msg = pack_wire(CMD_ANTI_ENTROPY_RESP, payload)
            try:
                self._sock.sendto(msg, addr)
                logger.info("Anti-entropy: sent %d events to %s:%d", len(events), addr[0], addr[1])
            except OSError:
                pass

    def _failure_detection_loop(self) -> None:
        """Run periodic failure detection on peers."""
        while self._running:
            time.sleep(FAILURE_DETECTION_INTERVAL)
            try:
                self.sync_mgr.run_failure_detection()
                # Remove peers we haven't seen in 60s
                now = time.time()
                stale = [
                    nid for nid, (_, _, last_seen) in self._known_peers.items()
                    if now - last_seen > 60
                ]
                for nid in stale:
                    ip, port, _ = self._known_peers.pop(nid)
                    self.sync_mgr.remove_peer(nid)
                    logger.info("Removed stale peer: %s @ %s:%d", nid, ip, port)
            except Exception as e:
                logger.debug("Failure detection error: %s", e)

    def _cleanup_loop(self) -> None:
        """Clean up old seen messages from the gossip manager."""
        while self._running:
            time.sleep(CLEANUP_INTERVAL)
            try:
                self.sync_mgr.cleanup_old_messages(MAX_SEEN_AGE_NS)
            except Exception as e:
                logger.debug("Cleanup error: %s", e)

    def _outbox_watch_loop(self) -> None:
        """Watch for new outbox events and broadcast them to peers."""
        while self._running:
            time.sleep(2.0)
            try:
                events = self.outbox.get_unsynced_events(self._last_broadcast_seq, limit=20)
                if not events:
                    continue
                for event in events:
                    # Update CRDT
                    vid = uuid.uuid4().bytes
                    ph = hashlib.sha384(
                        event.get("payload_json", "{}").encode("utf-8")
                    ).digest()
                    self.crdt.upsert(vid, event.get("vector_clock", 0), False, ph)
                    # Broadcast to peers via UDP
                    payload = json.dumps(event, default=str).encode("utf-8")
                    if len(payload) > MAX_PAYLOAD_SIZE:
                        continue
                    msg = pack_wire(CMD_DATA_REPLICATE, payload)
                    for ip, port, _ in self._known_peers.values():
                        try:
                            self._sock.sendto(msg, (ip, port))
                        except OSError:
                            pass
                    self._last_broadcast_seq = event["sequence_id"]
                logger.debug("Broadcast %d new outbox events", len(events))
            except Exception as e:
                logger.debug("Outbox watch error: %s", e)

    def _receive_event(self, event: dict, addr: tuple[str, int]) -> None:
        """Receive a replicated event from a peer."""
        msg_id = bytes.fromhex(event.get("message_id", "")) if "message_id" in event else uuid.uuid4().bytes
        if len(msg_id) != 16:
            msg_id = uuid.uuid4().bytes
        inserted = self.outbox.receive_replicated(
            source_table=event["source_table"],
            source_key=event["source_key"],
            event_type=event["event_type"],
            payload=json.loads(event.get("payload_json", "{}")),
            source_revision=event["source_revision"],
            origin_node=event.get("origin_node", "unknown"),
            vector_clock=event.get("vector_clock", 0),
            message_id=msg_id,
        )
        if inserted:
            logger.info("Received replicated event from %s: %s/%s", addr[0], event["source_table"], event["source_key"])
            # Update CRDT
            vid = uuid.uuid4().bytes
            ph = hashlib.sha384(event.get("payload_json", "{}").encode("utf-8")).digest()
            self.crdt.upsert(vid, event.get("vector_clock", 0), False, ph)

    def _mdns_loop(self) -> None:
        """mDNS-based peer discovery on the LAN.

        Uses zeroconf if available, otherwise falls back to UDP broadcast.
        """
        try:
            from zeroconf import Zeroconf, ServiceInfo
            import zeroconf
        except ImportError:
            # Fallback: UDP broadcast peer discovery
            logger.info("zeroconf not available, using UDP broadcast for discovery")
            self._udp_broadcast_discovery()
            return

        zc = Zeroconf()
        service_type = "_spectra-sync._udp.local."
        service_name = f"{self.node_id}.{service_type}"
        info = ServiceInfo(
            service_type,
            service_name,
            addresses=[socket.inet_aton(self.local_ip)],
            port=self.port,
            properties={"node_id": self.node_id},
        )
        zc.register_service(info)
        logger.info("Registered mDNS service: %s", service_name)

        # Listen for other services
        class SyncListener(zeroconf.ServiceListener):
            def __init__(self, daemon: SyncDaemon):
                self.daemon = daemon

            def add_service(self, zc, type_, name):
                info = zc.get_service_info(type_, name)
                if info:
                    ip = socket.inet_ntoa(info.addresses[0])
                    port = info.port
                    peer_node_id = name.split(".")[0]
                    if peer_node_id != self.daemon.node_id:
                        self.daemon._register_peer(peer_node_id, ip, port)

            def remove_service(self, zc, type_, name):
                pass

            def update_service(self, zc, type_, name):
                pass

        listener = SyncListener(self)
        zc.add_service_listener(service_type, listener)

        while self._running:
            time.sleep(1)

        zc.unregister_service(info)
        zc.close()

    def _udp_broadcast_discovery(self) -> None:
        """Fallback peer discovery using UDP broadcast."""
        bcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        bcast_sock.settimeout(1.0)
        bcast_port = self.port + 1

        try:
            bcast_sock.bind(("0.0.0.0", bcast_port))
        except OSError:
            logger.warning("Broadcast port %d in use, discovery disabled", bcast_port)
            return

        payload = (
            self.node_id.encode("utf-8") + b"\x00"
            + self.local_ip.encode("utf-8") + b"\x00"
            + self.port.to_bytes(2, "big")
        )
        msg = pack_wire(CMD_PEER_DISCOVERY, payload)

        while self._running:
            # Broadcast
            try:
                bcast_sock.sendto(msg, ("255.255.255.255", bcast_port))
            except OSError:
                pass
            # Listen for other broadcasts
            try:
                data, addr = bcast_sock.recvfrom(MAX_UDP_SIZE)
                self._handle_message(data, addr)
            except socket.timeout:
                pass
            time.sleep(5.0)

        bcast_sock.close()


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="SPECTRA Sync Daemon")
    parser.add_argument("--db", default="data/spectra.db", help="SPECTRA database path")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="UDP port for sync")
    parser.add_argument("--node-id", default=None, help="Unique node ID (default: auto)")
    parser.add_argument("--peer", action="append", nargs=2, metavar=("IP", "PORT"),
                        help="Static peer to connect to (repeatable)")
    parser.add_argument("--no-mdns", action="store_true", help="Disable mDNS discovery")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    peers = []
    if args.peer:
        for ip, port in args.peer:
            peers.append((ip, int(port)))

    daemon = SyncDaemon(
        args.db,
        port=args.port,
        node_id=args.node_id,
        peers=peers,
        enable_mdns=not args.no_mdns,
    )

    def handle_signal(signum, frame):
        logger.info("Received signal %d, shutting down", signum)
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    daemon.start()
    logger.info("SPECTRA sync daemon running. Press Ctrl+C to stop.")

    # Main loop — just wait
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        daemon.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
