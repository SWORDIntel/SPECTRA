"""
MSNET (MEMSHADOW) Secure Transport Layer
=========================================

TCP server implementing the MSNET v3 secure transport for LAN-only swarming:
- Listens on a configurable port (default 8899) and accepts incoming connections
- Enforces LAN-only access via CIDR check on the peer address
- Performs the MSNET PQC ZKP challenge-response handshake on each connection
- Bans peers that fail authentication via memshadow_peer_ban()
- Creates sessions and registers peers on successful handshake
- Runs a per-connection message loop with 30s heartbeat and 90s stale eviction
- Exposes send_to_peer() / broadcast() for outbound framed messages
- Graceful degradation: pure-Python header packing when libmemshadow.so is absent

This is Step 4 of the QIHSE RESP + MSNET Swarming Integration Plan.
"""

import ipaddress
import logging
import socket
import struct
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from tgarchive.search import msnet_bindings as msb

logger = logging.getLogger(__name__)

# Re-exported constants for convenience
MSG_HEARTBEAT = msb.MSG_HEARTBEAT
MSG_HANDSHAKE = msb.MSG_HANDSHAKE
MSG_NODE_REGISTER = msb.MSG_NODE_REGISTER
MSG_NODE_DEREGISTER = msb.MSG_NODE_DEREGISTER
MSG_QUERY_DISTRIBUTE = msb.MSG_QUERY_DISTRIBUTE
MSG_QUERY_RESPONSE = msb.MSG_QUERY_RESPONSE
MSG_DISCONNECT = msb.MSG_DISCONNECT

HEADER_SIZE = msb.MEMSHADOW_HEADER_SIZE
MAGIC = msb.MEMSHADOW_MAGIC
VERSION = (msb.MEMSHADOW_VERSION_MAJOR << 8) | msb.MEMSHADOW_VERSION_MINOR
MAX_PAYLOAD = msb.MEMSHADOW_MAX_PAYLOAD_NORMAL

# Handshake step sub-types (within MSG_HANDSHAKE payload, first byte)
HANDSHAKE_STEP_HELLO = msb.HANDSHAKE_STEP_HELLO
HANDSHAKE_STEP_HELLO_ACK = msb.HANDSHAKE_STEP_HELLO_ACK
HANDSHAKE_STEP_CHALLENGE_RESPONSE = msb.HANDSHAKE_STEP_CHALLENGE_RESPONSE
HANDSHAKE_STEP_SESSION_ESTABLISHED = msb.HANDSHAKE_STEP_SESSION_ESTABLISHED
HANDSHAKE_STEP_SESSION_REJECT = msb.HANDSHAKE_STEP_SESSION_REJECT

# Capabilities we advertise (LAN-trusted subset)
DEFAULT_CAPABILITIES = (
    msb.MEMSHADOW_CAP_PQC | msb.MEMSHADOW_CAP_ZKP | msb.MEMSHADOW_CAP_GOSSIP
)

# Header struct format: big-endian — magic(8) version(2) priority(2)
# msg_type(2) flags_batch(2) payload_len(4) timestamp_ns(8) sequence_num(4)
_HEADER_STRUCT = struct.Struct(">QHHHHI QI".replace(" ", ""))


class _PeerConnection:
    """Tracks a single connected, authenticated peer."""

    __slots__ = (
        "node_id", "sock", "addr", "session_id", "last_heartbeat",
        "connected_at", "lock",
    )

    def __init__(self, node_id: str, sock: socket.socket, addr: Tuple[str, int],
                 session_id: str):
        self.node_id = node_id
        self.sock = sock
        self.addr = addr
        self.session_id = session_id
        self.last_heartbeat = time.monotonic()
        self.connected_at = time.monotonic()
        self.lock = threading.Lock()


class MSNETTransport:
    """
    MSNET secure TCP transport server.

    Lan-only, handshake-authenticated message transport for SPECTRA swarm nodes.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8899,
        lan_cidr: str = "192.168.1.0/24",
        hmac_key: bytes = b"",
        node_id: str = "spectra-node",
        heartbeat_interval: int = 30,
        node_timeout: int = 90,
    ):
        self.host = host
        self.port = port
        self.lan_cidr = lan_cidr
        self.hmac_key = hmac_key or b"spectra-msnet-default-hmac-key"
        self.node_id = node_id
        self.heartbeat_interval = heartbeat_interval
        self.node_timeout = node_timeout

        # LAN network for access control
        try:
            self._lan_network = ipaddress.ip_network(lan_cidr, strict=False)
        except ValueError as exc:
            logger.warning("Invalid lan_cidr %r: %s — allowing all", lan_cidr, exc)
            self._lan_network = None

        # Runtime state
        self._server_sock: Optional[socket.socket] = None
        self._server_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._peers: Dict[str, _PeerConnection] = {}
        self._peers_lock = threading.Lock()
        self._seq_counter = 0
        self._seq_lock = threading.Lock()

        # Caller-supplied message callback: (peer_node_id, msg_type, payload_bytes)
        self.on_message: Optional[Callable[[str, int, bytes], None]] = None

        # Side-channel storage for per-socket session keys (Python 3.13+ socket
        # objects don't support arbitrary attribute assignment, so we store
        # session_key/hmac_key here keyed by id(sock) as a fallback).
        self._sock_session_keys: Dict[int, Tuple[bytes, bytes]] = {}

        # Native C structures (only if library available)
        self._use_native = msb.msnet_available()
        if self._use_native:
            self._session_mgr = msb.memshadow_session_manager_t()
            msb.memshadow_session_manager_init(self._session_mgr, node_timeout * 1000)
            self._peer_mgr = msb.memshadow_peer_manager_t()
            msb.memshadow_peer_manager_init(self._peer_mgr, msb.MEMSHADOW_PEER_MAX)
        else:
            self._session_mgr = None
            self._peer_mgr = None
            logger.warning(
                "MSNET native library unavailable — using pure-Python fallback. "
                "Handshake authentication is disabled; transport is unauthenticated."
            )

    # ── Public API ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the TCP server in a background thread."""
        if self._running.is_set():
            logger.warning("MSNET transport already running")
            return

        self._running.set()
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(64)
        self._server_sock.settimeout(1.0)  # so accept loop can check _running

        self._server_thread = threading.Thread(
            target=self._accept_loop, name="msnet-accept", daemon=True
        )
        self._server_thread.start()

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="msnet-heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

        logger.info(
            "MSNET transport listening on %s:%d (CIDR %s, native=%s)",
            self.host, self.port, self.lan_cidr, self._use_native,
        )

    def stop(self) -> None:
        """Stop the server and close all peer connections."""
        if not self._running.is_set():
            return
        self._running.clear()

        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None

        # Close all peer sockets
        with self._peers_lock:
            peers = list(self._peers.values())
            self._peers.clear()
        for pc in peers:
            self._close_peer(pc, reason="server shutdown")

        if self._server_thread is not None:
            self._server_thread.join(timeout=5)
            self._server_thread = None
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)
            self._heartbeat_thread = None

        logger.info("MSNET transport stopped")

    def is_running(self) -> bool:
        """Return True if the transport server is currently running."""
        return self._running.is_set()

    def send_to_peer(self, node_id: str, msg_type: int, payload: bytes) -> bool:
        """
        Send a framed message to a specific connected peer.

        Returns True on success, False if peer not connected or send failed.
        """
        with self._peers_lock:
            pc = self._peers.get(node_id)
        if pc is None:
            logger.debug("send_to_peer: peer %s not connected", node_id)
            return False
        return self._send_frame(pc, msg_type, payload)

    def broadcast(self, msg_type: int, payload: bytes) -> int:
        """
        Send a framed message to all connected peers.

        Returns the number of peers the message was sent to.
        """
        with self._peers_lock:
            peers = list(self._peers.values())
        sent = 0
        for pc in peers:
            if self._send_frame(pc, msg_type, payload):
                sent += 1
        return sent

    def connected_peers(self) -> Dict[str, Tuple[str, int]]:
        """Return mapping of node_id -> (ip, port) for connected peers."""
        with self._peers_lock:
            return {nid: pc.addr for nid, pc in self._peers.items()}

    def get_connected_peers(self) -> List[str]:
        """Return a list of currently connected peer node IDs."""
        with self._peers_lock:
            return list(self._peers.keys())

    def _set_sock_session(self, sock: socket.socket, session_key: bytes, hmac_key: bytes) -> None:
        """Store session key material for a socket.

        Tries to set attributes directly on the socket first (works on some
        Python versions), then falls back to a side-dict keyed by id(sock)
        for Python 3.13+ where socket objects lack __dict__.
        """
        try:
            sock._msnet_session_key = session_key  # type: ignore[attr-defined]
            sock._msnet_hmac_key = hmac_key  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            self._sock_session_keys[id(sock)] = (session_key, hmac_key)

    def _get_sock_session(self, sock: socket.socket) -> Tuple[bytes, bytes]:
        """Retrieve session key material for a socket."""
        try:
            sk = getattr(sock, "_msnet_session_key", None)
            hk = getattr(sock, "_msnet_hmac_key", None)
            if sk is not None and hk is not None:
                return sk, hk
        except (AttributeError, TypeError):
            pass
        return self._sock_session_keys.get(id(sock), (b"\x00" * 32, b"\x00" * 32))

    def connect_to_peer(self, host: str, port: int, node_id: str = "") -> Optional[str]:
        """
        Connect to a remote MSNET server and run the CLIENT-side handshake.

        This is the outbound connection counterpart to the server-side accept
        loop. It performs the full MSNET PQC ZKP challenge-response handshake
        from the client perspective:

            create_hello → send HELLO → receive HELLO_ACK →
            process_hello_ack → send CHALLENGE_RESPONSE →
            receive SESSION_ESTABLISHED

        On success the peer is registered in the same _peers dict used by the
        server side, and a background message-loop thread is started so
        incoming messages from this peer are dispatched to on_message.

        Args:
            host: Remote host IP or hostname to connect to.
            port: Remote MSNET TCP port.
            node_id: Optional expected peer node ID (for validation/logging).
                If empty, the peer node ID is taken from the handshake context.

        Returns:
            The peer's node ID on success, or None on connection/handshake failure.
        """
        if not self._running.is_set():
            logger.warning("connect_to_peer: transport not running — call start() first")
            return None

        # LAN-only enforcement for outbound connections too
        if not self._is_lan_allowed(host):
            logger.warning(
                "connect_to_peer: refusing outbound to %s:%d — outside LAN CIDR %s",
                host, port, self.lan_cidr,
            )
            return None

        logger.info("Connecting to MSNET peer %s:%d", host, port)

        sock: Optional[socket.socket] = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)  # connect + handshake timeout
            sock.connect((host, port))
        except OSError as exc:
            logger.warning("connect_to_peer: failed to connect to %s:%d: %s", host, port, exc)
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            return None

        try:
            # Run the client-side handshake
            peer_node_id = self._do_client_handshake(sock, self.hmac_key)
            if peer_node_id is None:
                logger.warning(
                    "connect_to_peer: client handshake failed for %s:%d", host, port
                )
                sock.close()
                return None

            # If caller supplied an expected node_id, validate
            if node_id and node_id != peer_node_id:
                logger.warning(
                    "connect_to_peer: peer node_id mismatch — expected %r, got %r (from %s:%d)",
                    node_id, peer_node_id, host, port,
                )
                # Still accept the connection using the handshake-derived ID

            # Register the peer in the shared _peers dict
            session_id = self._register_peer(peer_node_id, host, port, sock)

            # Start a background message loop for this outbound connection
            sock.settimeout(self.heartbeat_interval)
            t = threading.Thread(
                target=self._client_conn_loop,
                args=(sock, peer_node_id, host, port),
                name=f"msnet-client-{peer_node_id}",
                daemon=True,
            )
            t.start()

            logger.info(
                "Connected to peer %s at %s:%d (session=%s)",
                peer_node_id, host, port,
                session_id[:8] if session_id else "none",
            )
            return peer_node_id

        except (OSError, Exception) as exc:  # noqa: BLE001
            logger.warning("connect_to_peer: error connecting to %s:%d: %s", host, port, exc)
            try:
                sock.close()
            except OSError:
                pass
            return None

    def disconnect_peer(self, node_id: str) -> bool:
        """
        Cleanly close a peer connection.

        Sends a MSG_DISCONNECT frame (best-effort), closes the socket, removes
        the peer from the _peers dict, and notifies the native peer manager.

        Args:
            node_id: The node ID of the peer to disconnect.

        Returns:
            True if the peer was connected and has been disconnected, False if
            the peer was not found.
        """
        with self._peers_lock:
            pc = self._peers.pop(node_id, None)

        if pc is None:
            logger.debug("disconnect_peer: peer %s not connected", node_id)
            return False

        # Best-effort: send a DISCONNECT frame before closing
        try:
            self._send_frame(pc, MSG_DISCONNECT, b"")
        except Exception:  # noqa: BLE001
            pass  # socket may already be broken

        self._close_peer(pc, reason="local disconnect")
        logger.info("Disconnected peer %s", node_id)
        return True

    # ── Connection handling ───────────────────────────────────────────────

    def _accept_loop(self) -> None:
        while self._running.is_set():
            try:
                sock, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break  # server socket closed
            # Spawn a handler thread per connection
            t = threading.Thread(
                target=self._handle_connection,
                args=(sock, addr),
                name=f"msnet-conn-{addr[0]}:{addr[1]}",
                daemon=True,
            )
            t.start()

    def _handle_connection(self, sock: socket.socket, addr: Tuple[str, int]) -> None:
        """Per-connection handler: LAN check, handshake, message loop."""
        peer_ip, peer_port = addr
        try:
            # 1. LAN-only enforcement
            if not self._is_lan_allowed(peer_ip):
                logger.warning(
                    "Rejecting connection from %s:%d — outside LAN CIDR %s",
                    peer_ip, peer_port, self.lan_cidr,
                )
                sock.close()
                return

            sock.settimeout(10.0)  # handshake timeout

            # 2. Handshake
            peer_node_id = self._do_handshake(sock)
            if peer_node_id is None:
                # Auth failed — ban and close
                logger.warning(
                    "Handshake failed for %s:%d — banning peer", peer_ip, peer_port
                )
                self._ban_peer(peer_ip)
                sock.close()
                return

            # 3. Handshake succeeded — register peer + session
            session_id = self._register_peer(peer_node_id, peer_ip, peer_port, sock)

            # 4. Message loop
            sock.settimeout(self.heartbeat_interval)
            self._message_loop(sock, peer_node_id, peer_ip, peer_port)

        except (OSError, Exception) as exc:  # noqa: BLE001
            logger.debug("Connection %s:%d error: %s", peer_ip, peer_port, exc)
        finally:
            # Cleanup: remove peer, close socket
            self._unregister_peer_by_addr(peer_ip, peer_port)
            try:
                sock.close()
            except OSError:
                pass

    def _do_handshake(self, sock: socket.socket) -> Optional[str]:
        """
        Run the MSNET handshake protocol (server side).

        Flow:
          1. Receive HELLO (framed MSG_HANDSHAKE with step=HELLO)
          2. memshadow_handshake_process_hello() -> HELLO_ACK
          3. Send HELLO_ACK
          4. Receive CHALLENGE_RESPONSE
          5. memshadow_handshake_process_challenge_response() -> SESSION_ESTABLISHED
          6. Send SESSION_ESTABLISHED
          7. Return peer node_id on success, None on failure

        If the native library is unavailable, a simplified unauthenticated
        handshake is performed (graceful degradation for development).
        """
        if self._use_native:
            return self._do_handshake_native(sock)
        return self._do_handshake_fallback(sock)

    def _do_handshake_native(self, sock: socket.socket) -> Optional[str]:
        """Full MSNET handshake via libmemshadow.so."""
        ctx = msb.memshadow_handshake_ctx_t()
        msb.memshadow_handshake_init(ctx, DEFAULT_CAPABILITIES)

        # Step 1: Receive HELLO
        header, payload = self._parse_frame(sock)
        if header is None:
            logger.debug("Handshake: failed to receive HELLO frame")
            return None
        if header.msg_type != MSG_HANDSHAKE:
            logger.debug("Handshake: expected MSG_HANDSHAKE, got 0x%04x", header.msg_type)
            return None

        # Step 2: Process HELLO -> HELLO_ACK
        try:
            ack_payload = msb.memshadow_handshake_process_hello(ctx, payload)
        except (ValueError, RuntimeError) as exc:
            logger.debug("Handshake: process_hello failed: %s", exc)
            return None

        # Step 3: Send HELLO_ACK
        ack_frame = self._frame_message(MSG_HANDSHAKE, ack_payload, priority=2)
        if not self._raw_send(sock, ack_frame):
            return None

        # Step 4: Receive CHALLENGE_RESPONSE
        header, payload = self._parse_frame(sock)
        if header is None or header.msg_type != MSG_HANDSHAKE:
            logger.debug("Handshake: failed to receive CHALLENGE_RESPONSE")
            return None

        # Step 5: Process CHALLENGE_RESPONSE -> SESSION_ESTABLISHED
        try:
            established_payload = msb.memshadow_handshake_process_challenge_response(
                ctx, payload, self.hmac_key
            )
        except (ValueError, RuntimeError) as exc:
            logger.debug("Handshake: challenge_response failed: %s", exc)
            return None

        # Step 6: Send SESSION_ESTABLISHED
        est_frame = self._frame_message(MSG_HANDSHAKE, established_payload, priority=2)
        if not self._raw_send(sock, est_frame):
            return None

        # Extract peer node id from context
        peer_node_id = ctx.peer_node_id.decode("utf-8", errors="replace").strip("\x00")
        if not peer_node_id:
            peer_node_id = "unknown-peer"

        # Derive session key for session creation
        session_key = msb.memshadow_handshake_get_session_key(ctx)
        if session_key is None:
            logger.debug("Handshake: no session key derived")
            return None

        # Store session key for _register_peer to use
        self._set_sock_session(sock, session_key, self.hmac_key.ljust(32, b"\x00")[:32])

        return peer_node_id

    def _do_handshake_fallback(self, sock: socket.socket) -> Optional[str]:
        """
        Simplified unauthenticated handshake for when libmemshadow.so is absent.

        Protocol:
          1. Receive MSG_HANDSHAKE with payload = node_id (UTF-8)
          2. Send MSG_HANDSHAKE ACK with payload = b"OK"
          3. Return node_id
        """
        header, payload = self._parse_frame(sock)
        if header is None or header.msg_type != MSG_HANDSHAKE:
            return None
        peer_node_id = payload.decode("utf-8", errors="replace").strip("\x00")
        if not peer_node_id:
            peer_node_id = "fallback-peer"
        ack_frame = self._frame_message(MSG_HANDSHAKE, b"OK", priority=2)
        if not self._raw_send(sock, ack_frame):
            return None
        self._set_sock_session(sock, b"\x00" * 32, b"\x00" * 32)
        return peer_node_id

    # ── Client-side handshake (outbound connections) ──────────────────────

    def _do_client_handshake(self, sock: socket.socket, hmac_key: bytes) -> Optional[str]:
        """
        Run the MSNET handshake protocol from the CLIENT side.

        This is the mirror of the server-side _do_handshake():

          1. Create HELLO with memshadow_handshake_create_hello()
          2. Send framed HELLO message
          3. Receive HELLO_ACK, process with memshadow_handshake_process_hello_ack()
          4. Create CHALLENGE_RESPONSE, send it
          5. Receive SESSION_ESTABLISHED
          6. Return peer node_id from the handshake context

        If the native library is unavailable, a simplified unauthenticated
        handshake is performed (graceful degradation for development).

        Args:
            sock: Connected socket to the remote MSNET server.
            hmac_key: HMAC key for challenge-response authentication.

        Returns:
            Peer node ID string on success, None on failure.
        """
        if self._use_native:
            return self._do_client_handshake_native(sock, hmac_key)
        return self._do_client_handshake_fallback(sock)

    def _do_client_handshake_native(
        self, sock: socket.socket, hmac_key: bytes
    ) -> Optional[str]:
        """Full MSNET client-side handshake via libmemshadow.so."""
        ctx = msb.memshadow_handshake_ctx_t()
        msb.memshadow_handshake_init(ctx, DEFAULT_CAPABILITIES)

        # Pad/truncate hmac_key to 32 bytes for the native call
        padded_hmac = hmac_key.ljust(32, b"\x00")[:32]

        # Step 1: Create HELLO
        try:
            hello_payload = msb.memshadow_handshake_create_hello(ctx, self.node_id)
        except (ValueError, RuntimeError) as exc:
            logger.debug("Client handshake: create_hello failed: %s", exc)
            return None

        # Step 2: Send HELLO (framed as MSG_HANDSHAKE)
        hello_frame = self._frame_message(MSG_HANDSHAKE, hello_payload, priority=2)
        if not self._raw_send(sock, hello_frame):
            logger.debug("Client handshake: failed to send HELLO")
            return None

        # Step 3: Receive HELLO_ACK
        header, ack_payload = self._parse_frame(sock)
        if header is None:
            logger.debug("Client handshake: failed to receive HELLO_ACK frame")
            return None
        if header.msg_type != MSG_HANDSHAKE:
            logger.debug(
                "Client handshake: expected MSG_HANDSHAKE (HELLO_ACK), got 0x%04x",
                header.msg_type,
            )
            return None

        # Step 4: Process HELLO_ACK -> CHALLENGE_RESPONSE
        try:
            challenge_response_payload = msb.memshadow_handshake_process_hello_ack(
                ctx, ack_payload, padded_hmac
            )
        except (ValueError, RuntimeError) as exc:
            logger.debug("Client handshake: process_hello_ack failed: %s", exc)
            return None

        # Step 5: Send CHALLENGE_RESPONSE
        cr_frame = self._frame_message(
            MSG_HANDSHAKE, challenge_response_payload, priority=2
        )
        if not self._raw_send(sock, cr_frame):
            logger.debug("Client handshake: failed to send CHALLENGE_RESPONSE")
            return None

        # Step 6: Receive SESSION_ESTABLISHED
        header, _established_payload = self._parse_frame(sock)
        if header is None:
            logger.debug("Client handshake: failed to receive SESSION_ESTABLISHED frame")
            return None
        if header.msg_type != MSG_HANDSHAKE:
            logger.debug(
                "Client handshake: expected MSG_HANDSHAKE (SESSION_ESTABLISHED), got 0x%04x",
                header.msg_type,
            )
            return None

        # Step 7: Extract peer node_id from handshake context
        peer_node_id = ctx.peer_node_id.decode("utf-8", errors="replace").strip("\x00")
        if not peer_node_id:
            peer_node_id = "unknown-peer"

        # Derive session key
        session_key = msb.memshadow_handshake_get_session_key(ctx)
        if session_key is None:
            logger.debug("Client handshake: no session key derived")
            return None

        # Store session key on socket for _register_peer to use
        self._set_sock_session(sock, session_key, padded_hmac)

        return peer_node_id

    def _do_client_handshake_fallback(self, sock: socket.socket) -> Optional[str]:
        """
        Simplified unauthenticated client-side handshake for when
        libmemshadow.so is absent.

        Protocol:
          1. Send MSG_HANDSHAKE with payload = our node_id (UTF-8)
          2. Receive MSG_HANDSHAKE ACK with payload = b"OK"
          3. Return a placeholder peer node_id
        """
        hello_frame = self._frame_message(
            MSG_HANDSHAKE, self.node_id.encode("utf-8"), priority=2
        )
        if not self._raw_send(sock, hello_frame):
            return None

        header, payload = self._parse_frame(sock)
        if header is None or header.msg_type != MSG_HANDSHAKE:
            return None

        # In fallback mode the server sends back its node_id or "OK"
        peer_node_id = payload.decode("utf-8", errors="replace").strip("\x00")
        if not peer_node_id or peer_node_id == "OK":
            peer_node_id = "fallback-peer"

        self._set_sock_session(sock, b"\x00" * 32, b"\x00" * 32)
        return peer_node_id

    def _client_conn_loop(
        self,
        sock: socket.socket,
        peer_node_id: str,
        peer_ip: str,
        peer_port: int,
    ) -> None:
        """
        Message loop for an outbound (client-initiated) connection.

        This wraps the existing _message_loop with the same cleanup semantics
        as _handle_connection: on exit, the peer is unregistered and the
        socket is closed.
        """
        try:
            self._message_loop(sock, peer_node_id, peer_ip, peer_port)
        except (OSError, Exception) as exc:  # noqa: BLE001
            logger.debug("Client connection %s:%d error: %s", peer_ip, peer_port, exc)
        finally:
            self._unregister_peer_by_addr(peer_ip, peer_port)
            try:
                sock.close()
            except OSError:
                pass

    def _message_loop(
        self,
        sock: socket.socket,
        peer_node_id: str,
        peer_ip: str,
        peer_port: int,
    ) -> None:
        """Main per-connection message loop after handshake."""
        while self._running.is_set():
            try:
                header, payload = self._parse_frame(sock)
            except socket.timeout:
                # No data within heartbeat interval — send heartbeat
                if not self._send_heartbeat(peer_node_id):
                    break
                continue
            except OSError:
                break

            if header is None:
                break

            msg_type = header.msg_type

            if msg_type == MSG_HEARTBEAT:
                # Update last heartbeat time
                with self._peers_lock:
                    pc = self._peers.get(peer_node_id)
                if pc is not None:
                    pc.last_heartbeat = time.monotonic()
                # Record ping with native peer manager
                self._record_ping(peer_node_id, 0.0)
                continue

            if msg_type == MSG_DISCONNECT:
                logger.debug("Peer %s sent DISCONNECT", peer_node_id)
                break

            if msg_type == MSG_NODE_REGISTER:
                # Peer announcing itself — already registered via handshake
                continue

            if msg_type == MSG_NODE_DEREGISTER:
                logger.debug("Peer %s deregistering", peer_node_id)
                break

            # Application-level message — dispatch to callback
            if self.on_message is not None:
                try:
                    self.on_message(peer_node_id, msg_type, payload)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("on_message callback error: %s", exc)

    # ── Heartbeat & eviction ──────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        """Background thread: send heartbeats and evict stale peers."""
        while self._running.is_set():
            time.sleep(min(self.heartbeat_interval, 5))
            if not self._running.is_set():
                break

            now = time.monotonic()
            stale: list = []

            with self._peers_lock:
                for node_id, pc in self._peers.items():
                    # Send heartbeat
                    self._send_frame_nolock(pc, MSG_HEARTBEAT, b"")
                    # Check staleness
                    if (now - pc.last_heartbeat) > self.node_timeout:
                        stale.append(pc)

            # Evict stale peers
            for pc in stale:
                logger.info(
                    "Evicting stale peer %s (last heartbeat %.1fs ago)",
                    pc.node_id, now - pc.last_heartbeat,
                )
                self._close_peer(pc, reason="stale")
                with self._peers_lock:
                    self._peers.pop(pc.node_id, None)

            # Tick native peer manager for unban / timeout processing
            if self._use_native and self._peer_mgr is not None:
                try:
                    msb.memshadow_peer_tick(self._peer_mgr)
                except (RuntimeError, ValueError) as exc:
                    logger.debug("peer_tick error: %s", exc)

    def _send_heartbeat(self, peer_node_id: str) -> bool:
        """Send a heartbeat to a single peer."""
        with self._peers_lock:
            pc = self._peers.get(peer_node_id)
        if pc is None:
            return False
        return self._send_frame(pc, MSG_HEARTBEAT, b"")

    # ── Framing ───────────────────────────────────────────────────────────

    def _frame_message(
        self, msg_type: int, payload: bytes, priority: int = 1, flags: int = 0
    ) -> bytes:
        """
        Pack a 32-byte header + payload into a framed message.

        Uses the native memshadow_pack_header() when available, otherwise
        falls back to pure-Python struct packing.
        """
        if len(payload) > MAX_PAYLOAD:
            raise ValueError(f"Payload too large: {len(payload)} > {MAX_PAYLOAD}")

        seq = self._next_sequence()
        ts_ns = self._timestamp_ns()

        if self._use_native:
            header = msb.memshadow_header_t()
            header.magic = MAGIC
            header.version = VERSION
            header.priority = priority
            header.msg_type = msg_type
            header.flags_batch = flags
            header.payload_len = len(payload)
            header.timestamp_ns = ts_ns
            header.sequence_num = seq
            header_bytes = msb.memshadow_pack_header(header)
        else:
            header_bytes = _HEADER_STRUCT.pack(
                MAGIC, VERSION, priority, msg_type, flags,
                len(payload), ts_ns, seq,
            )

        return header_bytes + payload

    def _parse_frame(self, sock: socket.socket) -> Tuple[Optional[object], Optional[bytes]]:
        """
        Read a 32-byte header then the payload from the socket.

        Returns (header, payload) or (None, None) on error/EOF.
        The header is a memshadow_header_t when native is available, otherwise
        a simple namedtuple-like object with attribute access.
        """
        header_bytes = self._recv_exact(sock, HEADER_SIZE)
        if header_bytes is None or len(header_bytes) < HEADER_SIZE:
            return None, None

        if self._use_native:
            try:
                header = msb.memshadow_unpack_header(header_bytes)
            except (ValueError, RuntimeError):
                return None, None
            payload_len = header.payload_len
        else:
            fields = _HEADER_STRUCT.unpack(header_bytes)
            magic, version, priority, msg_type, flags_batch, payload_len, ts_ns, seq = fields
            if magic != MAGIC:
                logger.debug("Invalid magic: 0x%016x", magic)
                return None, None
            header = _FallbackHeader(
                magic=magic, version=version, priority=priority,
                msg_type=msg_type, flags_batch=flags_batch,
                payload_len=payload_len, timestamp_ns=ts_ns, sequence_num=seq,
            )

        if payload_len > MAX_PAYLOAD:
            logger.warning("Payload too large in frame: %d", payload_len)
            return None, None

        if payload_len > 0:
            payload = self._recv_exact(sock, payload_len)
            if payload is None:
                return None, None
        else:
            payload = b""

        return header, payload

    # ── Low-level socket I/O ──────────────────────────────────────────────

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
        """Read exactly n bytes from socket, or None on EOF/error."""
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except socket.timeout:
                raise  # let caller handle
            except OSError:
                return None
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    @staticmethod
    def _raw_send(sock: socket.socket, data: bytes) -> bool:
        """Send all bytes to socket. Returns True on success."""
        try:
            sock.sendall(data)
            return True
        except OSError as exc:
            logger.debug("send failed: %s", exc)
            return False

    def _send_frame(self, pc: _PeerConnection, msg_type: int, payload: bytes) -> bool:
        """Send a framed message to a peer (thread-safe per peer)."""
        frame = self._frame_message(msg_type, payload)
        with pc.lock:
            return self._raw_send(pc.sock, frame)

    def _send_frame_nolock(self, pc: _PeerConnection, msg_type: int, payload: bytes) -> bool:
        """Send a framed message without acquiring the peer lock (caller holds peers_lock)."""
        frame = self._frame_message(msg_type, payload)
        with pc.lock:
            return self._raw_send(pc.sock, frame)

    # ── Peer / session management ─────────────────────────────────────────

    def _register_peer(
        self, node_id: str, ip: str, port: int, sock: socket.socket
    ) -> str:
        """Register a newly authenticated peer and create a session."""
        session_id = ""

        # Create native session
        if self._use_native and self._session_mgr is not None:
            session_key, hmac_key = self._get_sock_session(sock)
            try:
                session_id = msb.memshadow_session_create(
                    self._session_mgr, node_id, session_key, hmac_key
                )
            except (ValueError, RuntimeError) as exc:
                logger.warning("Failed to create session for %s: %s", node_id, exc)
                session_id = ""

        # Add to native peer manager
        if self._use_native and self._peer_mgr is not None:
            peer_info = msb.memshadow_peer_info_t()
            peer_info.node_id = node_id.encode("utf-8")
            try:
                peer_info.address_ipv4 = int(
                    ipaddress.IPv4Address(ip)
                )
            except (ipaddress.AddressValueError, ValueError):
                peer_info.address_ipv4 = 0
            peer_info.port = port
            peer_info.status = msb.PEER_CONNECTED
            peer_info.capabilities = DEFAULT_CAPABILITIES
            peer_info.version = VERSION
            peer_info.connected_since_ns = self._timestamp_ns()
            try:
                msb.memshadow_peer_add(self._peer_mgr, peer_info)
            except (ValueError, RuntimeError) as exc:
                logger.debug("peer_add failed: %s", exc)

        # Track in local dict
        pc = _PeerConnection(node_id, sock, (ip, port), session_id)
        with self._peers_lock:
            # If peer already connected (reconnect), close old connection
            old = self._peers.get(node_id)
            if old is not None:
                self._close_peer(old, reason="replaced by new connection")
            self._peers[node_id] = pc

        logger.info(
            "Peer registered: %s (%s:%d) session=%s",
            node_id, ip, port, session_id[:8] if session_id else "none",
        )
        return session_id

    def _unregister_peer_by_addr(self, ip: str, port: int) -> None:
        """Remove a peer from tracking by its address (on disconnect)."""
        with self._peers_lock:
            to_remove = None
            for node_id, pc in self._peers.items():
                if pc.addr == (ip, port):
                    to_remove = node_id
                    break
            if to_remove is not None:
                self._peers.pop(to_remove, None)

        if to_remove and self._use_native and self._peer_mgr is not None:
            try:
                msb.memshadow_peer_disconnect(self._peer_mgr, to_remove)
            except (RuntimeError, ValueError):
                pass

    def _close_peer(self, pc: _PeerConnection, reason: str = "") -> None:
        """Close a peer's socket and update native peer manager."""
        try:
            pc.sock.close()
        except OSError:
            pass
        if self._use_native and self._peer_mgr is not None:
            try:
                msb.memshadow_peer_disconnect(self._peer_mgr, pc.node_id)
            except (RuntimeError, ValueError):
                pass
        logger.debug("Closed peer %s: %s", pc.node_id, reason)

    def _ban_peer(self, ip: str) -> None:
        """Ban a peer by IP-derived node id (auth failure)."""
        ban_id = f"banned-{ip}"
        if self._use_native and self._peer_mgr is not None:
            try:
                msb.memshadow_peer_ban(self._peer_mgr, ban_id)
            except (RuntimeError, ValueError) as exc:
                logger.debug("peer_ban failed: %s", exc)
        logger.warning("Banned peer %s (auth failure)", ip)

    def _record_ping(self, node_id: str, latency_ms: float) -> None:
        """Record a successful heartbeat ping with the native peer manager."""
        if not self._use_native or self._peer_mgr is None:
            return
        try:
            ptr = msb.memshadow_peer_find(self._peer_mgr, node_id)
            if ptr:
                msb.memshadow_peer_record_ping(ptr, latency_ms)
        except (RuntimeError, ValueError) as exc:
            logger.debug("record_ping failed: %s", exc)

    # ── Utilities ─────────────────────────────────────────────────────────

    def _is_lan_allowed(self, ip: str) -> bool:
        """Check if an IP address is within the configured LAN CIDR."""
        if self._lan_network is None:
            return True  # no CIDR configured — allow all
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return addr in self._lan_network

    def _next_sequence(self) -> int:
        """Get the next monotonic sequence number."""
        with self._seq_lock:
            self._seq_counter = (self._seq_counter + 1) & 0xFFFFFFFF
            return self._seq_counter

    def _timestamp_ns(self) -> int:
        """Get current timestamp in nanoseconds (native or Python fallback)."""
        if self._use_native:
            try:
                return msb.memshadow_get_timestamp_ns()
            except (RuntimeError, ValueError):
                pass
        return int(time.time_ns())


class _FallbackHeader:
    """Simple header container for pure-Python mode (no native library)."""

    __slots__ = (
        "magic", "version", "priority", "msg_type",
        "flags_batch", "payload_len", "timestamp_ns", "sequence_num",
    )

    def __init__(self, magic, version, priority, msg_type, flags_batch,
                 payload_len, timestamp_ns, sequence_num):
        self.magic = magic
        self.version = version
        self.priority = priority
        self.msg_type = msg_type
        self.flags_batch = flags_batch
        self.payload_len = payload_len
        self.timestamp_ns = timestamp_ns
        self.sequence_num = sequence_num

    def __repr__(self):
        return (
            f"_FallbackHeader(msg_type=0x{self.msg_type:04x}, "
            f"payload_len={self.payload_len}, seq={self.sequence_num})"
        )
