"""
QIHSE RESP Server Ctypes Wrapper
=================================

Python ctypes wrapper for QIHSE Redis Serialization Protocol (RESP) wire server.
Provides in-process, high-performance RESP server capabilities backed by the
QIHSE native C engine (KV store, task queues, vectors, timeseries).

Architecture:
- C library backend: QIHSE (libqihse.so)
- Protocol: RESP v2 / v3
- Storage: In-memory QIHSE trinary trie KV store + vector DB + task queue
- Execution model: Background worker thread running blocking accept loop
- Synchronization: Thread-safe lifecycle management, socket health probing

References:
- QIHSE/include/qihse_resp_wire.h
- docs/QIHSE_RESP_SWARM_PLAN.md
"""

import ctypes
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_bool,
    c_char_p,
    c_double,
    c_int,
    c_size_t,
    c_uint16,
    c_uint32,
    c_uint64,
    c_void_p,
)
import logging
import os
from pathlib import Path
import socket
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Grace period (seconds) to wait after a short-lived probe connection is closed
# before opening the next one.  The QIHSE C RESP engine spawns a detached
# worker thread per accepted connection; when the client disconnects the worker
# calls shutdown(fd)/close(fd).  If a *new* connection is accepted and reuses
# the same fd number before the old worker's close() lands, the old worker's
# close() will silently tear down the new connection (EPIPE on the next send).
# This is an fd-reuse race in the C library that we cannot fix from Python, but
# we can avoid triggering it by giving the old worker time to finish cleanup.
_FD_REUSE_GRACE_S = 0.01


# ============================================================================
# C Struct Definitions matching include/qihse_resp_wire.h
# ============================================================================

class QihseRespServerConfig(Structure):
    """Configuration structure for QIHSE RESP server (qihse_resp_server_config_t).

    Field order, sizes, and types must match include/qihse_resp_wire.h exactly:
        qihse_kv_store_t* store;
        qihse_vector_db_t vdb;
        qihse_tsdb_t* tsdb;
        qihse_column_store_t* column_store;
        qihse_cluster_topology_t* topology;
        const char* bind_address;
        const char* advertise_address;
        const char* node_id;
        uint16_t port;
        uint16_t bus_port;
        uint16_t local_node_index;
        size_t max_clients;
        size_t max_request_bytes;
        bool auth_required;
        bool require_full_coverage;
        bool pin_workers;
        bool strict_hardware_affinity;
        int numa_node_id;
        bool enable_bus;
        bool enable_failover;
        bool enable_guard_throttle;
        const char* xdp_interface;
        uint64_t guard_window_ms;
        double guard_saturation_fraction;
        bool enable_scatter;
        uint32_t scatter_timeout_ms;
        bool enable_task_queue;
        bool enable_task_workers;
        uint32_t task_worker_count;
        const char* task_python_binary;
        bool enable_task_scheduler;
        qihse_task_queue_t* task_queue;
        qihse_task_worker_pool_t* task_workers;
        qihse_task_scheduler_t* task_scheduler;
    """

    _fields_ = [
        ("store", c_void_p),
        ("vdb", c_void_p),
        ("tsdb", c_void_p),
        ("column_store", c_void_p),
        ("topology", c_void_p),
        ("bind_address", c_char_p),
        ("advertise_address", c_char_p),
        ("node_id", c_char_p),
        ("port", c_uint16),
        ("bus_port", c_uint16),
        ("local_node_index", c_uint16),
        ("max_clients", c_size_t),
        ("max_request_bytes", c_size_t),
        ("auth_required", c_bool),
        ("require_full_coverage", c_bool),
        ("pin_workers", c_bool),
        ("strict_hardware_affinity", c_bool),
        ("numa_node_id", c_int),
        ("enable_bus", c_bool),
        ("enable_failover", c_bool),
        ("enable_guard_throttle", c_bool),
        ("xdp_interface", c_char_p),
        ("guard_window_ms", c_uint64),
        ("guard_saturation_fraction", c_double),
        ("enable_scatter", c_bool),
        ("scatter_timeout_ms", c_uint32),
        ("enable_task_queue", c_bool),
        ("enable_task_workers", c_bool),
        ("task_worker_count", c_uint32),
        ("task_python_binary", c_char_p),
        ("enable_task_scheduler", c_bool),
        ("task_queue", c_void_p),
        ("task_workers", c_void_p),
        ("task_scheduler", c_void_p),
    ]


# ============================================================================
# Native Library Loading & Prototype Registration
# ============================================================================

def _load_qihse_library() -> Optional[ctypes.CDLL]:
    """Search for and load the QIHSE shared library (libqihse.so)."""
    # 1. Try importing existing loaded handle from qihse_bindings if available
    try:
        from tgarchive.search.qihse_bindings import _qihse_lib as existing_lib

        if existing_lib is not None:
            return existing_lib
    except ImportError:
        pass

    possible_paths = []
    if os.getenv("QIHSE_LIB_PATH"):
        possible_paths.append(Path(os.environ["QIHSE_LIB_PATH"]))

    spectra_root = Path(__file__).resolve().parent.parent.parent
    possible_paths.extend([
        spectra_root / "QIHSE" / "libqihse.so",
        spectra_root / "libs" / "QIHSE" / "libqihse.so",
        spectra_root / "libs" / "search_algorithms" / "QIHSE" / "qihse" / "libqihse.so",
        spectra_root / "libs" / "search_algorithms" / "QIHSE" / "build" / "bin" / "libqihse.so",
        Path("/opt/osint-node/sources/QIHSE/qihse/libqihse.so"),
        Path("/usr/local/lib/libqihse.so"),
        Path("/usr/lib/libqihse.so"),
        Path("libqihse.so"),
    ])

    for lib_path in possible_paths:
        if lib_path.exists():
            try:
                mode = getattr(os, "RTLD_GLOBAL", 0) | getattr(os, "RTLD_NOW", 0)
                lib = ctypes.CDLL(str(lib_path), mode=mode)
                logger.info("Loaded QIHSE library from %s", lib_path)
                return lib
            except OSError as e:
                logger.debug("Failed to load %s: %s", lib_path, e)
                continue

    try:
        mode = getattr(os, "RTLD_GLOBAL", 0) | getattr(os, "RTLD_NOW", 0)
        lib = ctypes.CDLL("libqihse.so", mode=mode)
        logger.info("Loaded QIHSE library from system path")
        return lib
    except OSError:
        logger.warning("QIHSE library not found. RESP server features will be unavailable.")
        return None


_lib = _load_qihse_library()

if _lib is not None:
    # Function prototypes for RESP Server
    _lib.qihse_resp_server_config_init.argtypes = [POINTER(QihseRespServerConfig)]
    _lib.qihse_resp_server_config_init.restype = None

    _lib.qihse_resp_server_create.argtypes = [POINTER(QihseRespServerConfig)]
    _lib.qihse_resp_server_create.restype = c_void_p

    _lib.qihse_resp_server_start.argtypes = [c_void_p]
    _lib.qihse_resp_server_start.restype = c_bool

    _lib.qihse_resp_server_run.argtypes = [c_void_p]
    _lib.qihse_resp_server_run.restype = c_bool

    _lib.qihse_resp_server_stop.argtypes = [c_void_p]
    _lib.qihse_resp_server_stop.restype = None

    _lib.qihse_resp_server_destroy.argtypes = [c_void_p]
    _lib.qihse_resp_server_destroy.restype = None

    _lib.qihse_resp_server_port.argtypes = [c_void_p]
    _lib.qihse_resp_server_port.restype = c_uint16

    # Function prototypes for KV Store backing
    if hasattr(_lib, "qihse_kv_store_create"):
        _lib.qihse_kv_store_create.argtypes = []
        _lib.qihse_kv_store_create.restype = c_void_p

    if hasattr(_lib, "qihse_kv_store_destroy"):
        _lib.qihse_kv_store_destroy.argtypes = [c_void_p]
        _lib.qihse_kv_store_destroy.restype = None

    # Function prototypes for Auth & User management
    if hasattr(_lib, "qihse_auth_init"):
        _lib.qihse_auth_init.argtypes = []
        _lib.qihse_auth_init.restype = None

    if hasattr(_lib, "qihse_auth_is_operator_password_default"):
        _lib.qihse_auth_is_operator_password_default.argtypes = []
        _lib.qihse_auth_is_operator_password_default.restype = c_bool

    if hasattr(_lib, "qihse_auth_get_user"):
        _lib.qihse_auth_get_user.argtypes = [c_uint32]
        _lib.qihse_auth_get_user.restype = c_void_p

    if hasattr(_lib, "qihse_auth_modify_user"):
        _lib.qihse_auth_modify_user.argtypes = [
            c_void_p,
            c_uint32,
            c_char_p,
            c_char_p,
            c_int,
            c_int,
        ]
        _lib.qihse_auth_modify_user.restype = c_bool


def qihse_resp_available() -> bool:
    """Check if QIHSE shared library and RESP server symbols are available."""
    if _lib is None:
        return False
    required_symbols = [
        "qihse_resp_server_config_init",
        "qihse_resp_server_create",
        "qihse_resp_server_start",
        "qihse_resp_server_run",
        "qihse_resp_server_stop",
        "qihse_resp_server_destroy",
        "qihse_resp_server_port",
    ]
    return all(hasattr(_lib, sym) for sym in required_symbols)


# ============================================================================
# Ctypes Function Wrappers
# ============================================================================

def qihse_resp_server_config_init(config: QihseRespServerConfig) -> None:
    """Initialize RESP server configuration struct with defaults."""
    if not qihse_resp_available():
        raise RuntimeError("QIHSE RESP library not available")
    _lib.qihse_resp_server_config_init(byref(config))


def qihse_resp_server_create(config: QihseRespServerConfig) -> Optional[int]:
    """Create a new QIHSE RESP server handle.

    Returns:
        Integer pointer handle (c_void_p value) or None on failure.
    """
    if not qihse_resp_available():
        raise RuntimeError("QIHSE RESP library not available")
    handle = _lib.qihse_resp_server_create(byref(config))
    return handle if handle else None


def qihse_resp_server_start(server_handle: int) -> bool:
    """Start RESP server with internal accept thread."""
    if not qihse_resp_available():
        raise RuntimeError("QIHSE RESP library not available")
    return bool(_lib.qihse_resp_server_start(c_void_p(server_handle)))


def qihse_resp_server_run(server_handle: int) -> bool:
    """Run RESP server accept loop synchronously (blocking)."""
    if not qihse_resp_available():
        raise RuntimeError("QIHSE RESP library not available")
    return bool(_lib.qihse_resp_server_run(c_void_p(server_handle)))


def qihse_resp_server_stop(server_handle: int) -> None:
    """Stop running RESP server."""
    if not qihse_resp_available():
        return
    _lib.qihse_resp_server_stop(c_void_p(server_handle))


def qihse_resp_server_destroy(server_handle: int) -> None:
    """Destroy RESP server and free its internal resources."""
    if not qihse_resp_available():
        return
    _lib.qihse_resp_server_destroy(c_void_p(server_handle))


def qihse_resp_server_port(server_handle: int) -> int:
    """Get the active listening port of the RESP server."""
    if not qihse_resp_available() or not server_handle:
        return 0
    return int(_lib.qihse_resp_server_port(c_void_p(server_handle)))


# ============================================================================
# High-Level QIHSEResPServer Class
# ============================================================================

class QIHSEResPServer:
    """High-level Python controller for the QIHSE RESP Wire Server.

    Manages lifecycle, background threading, KV storage backend, health pinging,
    and clean teardown.

    Usage:
        server = QIHSEResPServer(host='127.0.0.1', port=6379)
        if server.start():
            print(f"RESP server active on port {server.port()}")
            ...
            server.stop()

        # Or as a context manager:
        with QIHSEResPServer(port=6379) as srv:
            assert srv.ping()
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 6379,
        max_clients: int = 64,
        enable_task_queue: bool = True,
        auth_required: Optional[bool] = None,
        password: Optional[str] = None,
        kv_store: Optional[Any] = None,
    ):
        """Initialize QIHSE RESP server controller.

        Args:
            host: IP address or hostname to bind to (e.g. '127.0.0.1', '192.168.1.91').
            port: TCP port to listen on (0 for dynamic/ephemeral port).
            max_clients: Maximum concurrent client connections (default 64).
            enable_task_queue: Whether to enable task queue engine support.
            auth_required: Whether AUTH command is enforced. If None, auto-disabled
                           for loopback addresses and enabled for LAN/external addresses.
            password: Optional operator password when authentication is required.
            kv_store: Optional external QIHSE KV store pointer/handle. If None, an
                      internal KV store is created and managed automatically.
        """
        self.host = host
        self.port_requested = int(port)
        self.max_clients = int(max_clients)
        self.enable_task_queue = bool(enable_task_queue)
        self.password = password

        # Loopback detection
        is_loopback = self._is_loopback_host(self.host)
        if auth_required is None:
            # On loopback, authentication is disabled by default for zero-friction local operations.
            # On non-loopback (LAN / 0.0.0.0), C engine strictly requires auth_required = True.
            self.auth_required = not is_loopback
        else:
            self.auth_required = bool(auth_required)

        self._kv_handle = kv_store
        self._owns_kv = False
        self._server_handle: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._host_bytes: Optional[bytes] = None

    @staticmethod
    def _is_loopback_host(host: str) -> bool:
        """Check if host is a local loopback address."""
        if not host:
            return True
        h = host.strip().lower()
        return h in ("127.0.0.1", "localhost", "::1") or h.startswith("127.")

    def _ensure_auth_configured(self) -> None:
        """Ensure QIHSE authentication is initialized with a valid operator password."""
        if _lib is None:
            return
        if hasattr(_lib, "qihse_auth_init"):
            _lib.qihse_auth_init()
        if (
            hasattr(_lib, "qihse_auth_is_operator_password_default")
            and _lib.qihse_auth_is_operator_password_default()
        ):
            if hasattr(_lib, "qihse_auth_get_user") and hasattr(_lib, "qihse_auth_modify_user"):
                op = _lib.qihse_auth_get_user(0)
                if op:
                    pw = (self.password or "SPECTRA_QIHSE_RESP_2026!").encode("utf-8")
                    _lib.qihse_auth_modify_user(op, 0, b"operator", pw, -1, -1)

    def _check_port_ready(self, timeout: float = 0.5) -> bool:
        """Check if the server is accepting TCP connections (no RESP data sent).

        This is a lightweight readiness probe that avoids the fd-reuse race
        inherent in the C engine's per-connection thread cleanup.  We only
        verify that ``connect()`` succeeds; no RESP command is sent so the
        server worker thread has minimal work to do and its subsequent
        shutdown/close of the fd is very fast.
        """
        target_port = self.port()
        if target_port == 0:
            target_port = self.port_requested
        if target_port == 0:
            return False
        connect_host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((connect_host, target_port))
                # If auth is required, send AUTH so the worker doesn't block
                # waiting for credentials (which would delay fd cleanup).
                if self.auth_required:
                    pw = self.password or "SPECTRA_QIHSE_RESP_2026!"
                    s.sendall(f"AUTH operator {pw}\r\n".encode("utf-8"))
                    s.recv(512)  # consume +OK
            return True
        except Exception:
            return False

    def start(self, timeout: float = 3.0) -> bool:
        """Start the QIHSE RESP server in a background thread.

        Args:
            timeout: Maximum seconds to wait for server initialization and socket binding.

        Returns:
            True if started and healthy, False otherwise.
        """
        with self._lock:
            if self._running and self.is_running():
                logger.debug("QIHSE RESP server already running on port %d", self.port())
                return True

            if not qihse_resp_available():
                logger.warning("QIHSE library not available; cannot start RESP server.")
                return False

            try:
                # 1. Create KV store if not provided
                if not self._kv_handle and hasattr(_lib, "qihse_kv_store_create"):
                    self._kv_handle = _lib.qihse_kv_store_create()
                    self._owns_kv = True

                # 2. Configure auth if required
                if self.auth_required:
                    self._ensure_auth_configured()

                # 3. Setup configuration struct
                cfg = QihseRespServerConfig()
                _lib.qihse_resp_server_config_init(byref(cfg))

                cfg.store = self._kv_handle
                self._host_bytes = self.host.encode("utf-8")
                cfg.bind_address = self._host_bytes
                cfg.advertise_address = self._host_bytes
                cfg.port = self.port_requested
                cfg.max_clients = self.max_clients
                cfg.auth_required = self.auth_required
                cfg.enable_task_queue = self.enable_task_queue
                cfg.enable_task_workers = False
                cfg.enable_task_scheduler = False

                # 4. Create server instance
                self._server_handle = _lib.qihse_resp_server_create(byref(cfg))
                if not self._server_handle:
                    logger.error("qihse_resp_server_create failed for %s:%d", self.host, self.port_requested)
                    self._cleanup_resources()
                    return False

                # 5. Launch blocking qihse_resp_server_run in background thread
                started_event = threading.Event()
                run_error: list[Optional[Exception]] = [None]

                def _server_thread_main() -> None:
                    started_event.set()
                    try:
                        _lib.qihse_resp_server_run(c_void_p(self._server_handle))
                    except Exception as err:
                        run_error[0] = err
                        logger.exception("Error in QIHSE RESP server run thread: %s", err)

                self._thread = threading.Thread(
                    target=_server_thread_main,
                    name=f"QIHSEResPServer-{self.host}:{self.port_requested}",
                    daemon=True,
                )
                self._thread.start()

                # Wait for thread to begin
                started_event.wait(timeout=1.0)
                self._running = True

                # 6. Poll for readiness using a lightweight connect-only probe.
                #    We deliberately avoid sending PING here because each
                #    short-lived probe connection triggers the C engine's
                #    per-connection thread cleanup, which races with subsequent
                #    connections reusing the same fd (fd-reuse race).  A
                #    connect-only probe minimises the window.
                deadline = time.time() + timeout
                bound_ready = False

                while time.time() < deadline:
                    if not self._thread.is_alive() or run_error[0] is not None:
                        logger.error("QIHSE RESP server background thread terminated unexpectedly.")
                        break

                    active_port = self.port()
                    if active_port > 0:
                        if self._check_port_ready(timeout=0.3):
                            bound_ready = True
                            break

                    time.sleep(0.05)

                if not bound_ready:
                    logger.error(
                        "QIHSE RESP server failed to become ready on %s:%d within %.1fs",
                        self.host,
                        self.port_requested,
                        timeout,
                    )
                    self._stop_internal()
                    return False

                # 7. Grace period: let the probe connection's worker thread
                #    finish shutdown(fd)/close(fd) so that the fd number is
                #    not reused by the next client while the old worker is
                #    still cleaning up (which would cause EPIPE on send).
                time.sleep(_FD_REUSE_GRACE_S)

                logger.info(
                    "QIHSE RESP server successfully running on %s:%d",
                    self.host,
                    self.port(),
                )
                return True

            except Exception as e:
                logger.exception("Exception starting QIHSE RESP server: %s", e)
                self._stop_internal()
                return False

    def _stop_internal(self) -> None:
        """Internal helper to stop server and clean up without outer lock nesting."""
        if self._server_handle:
            try:
                _lib.qihse_resp_server_stop(c_void_p(self._server_handle))
            except Exception as e:
                logger.debug("Error during qihse_resp_server_stop: %s", e)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

        if self._server_handle:
            try:
                _lib.qihse_resp_server_destroy(c_void_p(self._server_handle))
            except Exception as e:
                logger.debug("Error during qihse_resp_server_destroy: %s", e)
            self._server_handle = None

        self._cleanup_resources()
        self._running = False

    def _cleanup_resources(self) -> None:
        """Clean up internal KV store if owned."""
        if self._owns_kv and self._kv_handle and _lib and hasattr(_lib, "qihse_kv_store_destroy"):
            try:
                _lib.qihse_kv_store_destroy(c_void_p(self._kv_handle))
            except Exception as e:
                logger.debug("Error destroying KV store: %s", e)
            self._kv_handle = None
            self._owns_kv = False

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the QIHSE RESP server and release all resources.

        Args:
            timeout: Maximum seconds to wait for worker thread shutdown.
        """
        with self._lock:
            if not self._running and self._server_handle is None:
                return
            self._stop_internal()
            logger.info("QIHSE RESP server stopped.")

    def is_running(self) -> bool:
        """Check if server is active and the background worker thread is running."""
        return (
            self._running
            and self._server_handle is not None
            and self._thread is not None
            and self._thread.is_alive()
        )

    def port(self) -> int:
        """Get actual bound port of the server (0 if not running)."""
        if not self.is_running() or not self._server_handle or not _lib:
            return 0
        try:
            return int(_lib.qihse_resp_server_port(c_void_p(self._server_handle)))
        except Exception:
            return 0

    def ping(self, timeout: float = 1.0) -> bool:
        """Check server health by sending a RESP PING and validating response.

        Args:
            timeout: Socket connection and read timeout in seconds.

        Returns:
            True if server responded with +PONG, False otherwise.

        Note:
            This method opens a short-lived connection that triggers the C
            engine's per-connection thread cleanup.  A brief grace pause is
            inserted after the socket closes so that the fd is not reused by
            a subsequent connection before the old worker thread finishes
            shutdown(fd)/close(fd).
        """
        target_port = self.port()
        if target_port == 0:
            target_port = self.port_requested
        if target_port == 0:
            return False

        connect_host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host

        ok = False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.connect((connect_host, target_port))

                # If auth is enabled and password configured, send AUTH first
                if self.auth_required:
                    pw = self.password or "SPECTRA_QIHSE_RESP_2026!"
                    auth_cmd = f"AUTH operator {pw}\r\n".encode("utf-8")
                    s.sendall(auth_cmd)
                    auth_resp = s.recv(512)
                    if not auth_resp.startswith(b"+OK"):
                        return False

                s.sendall(b"PING\r\n")

                buf = bytearray()
                while b"\r\n" not in buf and len(buf) < 512:
                    chunk = s.recv(512)
                    if not chunk:
                        break
                    buf.extend(chunk)

                ok = buf.startswith(b"+PONG")
        except Exception:
            ok = False
        finally:
            # Grace period to avoid fd-reuse race (see _FD_REUSE_GRACE_S).
            time.sleep(_FD_REUSE_GRACE_S)
        return ok

    def __enter__(self) -> "QIHSEResPServer":
        """Context manager entry - starts the server."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - stops the server."""
        self.stop()

    # ------------------------------------------------------------------
    # RESP KV convenience helpers
    # ------------------------------------------------------------------
    # These methods open a *persistent* connection for the duration of the
    # call sequence, avoiding the fd-reuse race that affects short-lived
    # probe connections.  They are useful for testing and for lightweight
    # coordination use-cases that don't need a full RespConnection client.

    def _resp_exchange(self, sock: socket.socket, data: bytes, read_bytes: int = 4096) -> bytes:
        """Send raw RESP bytes and read the full response."""
        sock.sendall(data)
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(read_bytes)
            if not chunk:
                break
            chunks.append(chunk)
            # Heuristic: stop once we have a complete RESP reply.  For simple
            # replies (+OK\r\n, $N\r\n...\r\n, :N\r\n, $-1\r\n) a single recv
            # is sufficient.  For bulk strings we check the declared length.
            buf = b"".join(chunks)
            if b"\r\n" in buf:
                if buf[0:1] in (b"+", b"-", b":"):
                    break
                if buf[0:1] == b"$":
                    # Bulk string: parse $<len>\r\n<data>\r\n
                    hdr_end = buf.index(b"\r\n")
                    try:
                        bulk_len = int(buf[1:hdr_end])
                    except ValueError:
                        break
                    if bulk_len < 0:
                        break  # $-1 = nil
                    if len(buf) >= hdr_end + 2 + bulk_len + 2:
                        break
        return b"".join(chunks)

    def resp_command(self, *args: str, timeout: float = 2.0) -> Optional[bytes]:
        """Send a single RESP command on a fresh connection and return the raw reply.

        This is a convenience helper for one-shot commands.  For repeated
        commands prefer keeping a persistent socket open.

        Args:
            *args: Command and arguments (e.g. ``"SET"``, ``"key"``, ``"val"``).
            timeout: Socket timeout in seconds.

        Returns:
            Raw RESP reply bytes, or None on failure.
        """
        target_port = self.port()
        if target_port == 0:
            target_port = self.port_requested
        if target_port == 0:
            return None
        connect_host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host

        # Build RESP array: *N\r\n$len\r\narg\r\n...
        parts = []
        for a in args:
            ab = a.encode("utf-8")
            parts.append(f"${len(ab)}\r\n".encode("utf-8"))
            parts.append(ab)
            parts.append(b"\r\n")
        resp_data = f"*{len(args)}\r\n".encode("utf-8") + b"".join(parts)

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.connect((connect_host, target_port))
                if self.auth_required:
                    pw = self.password or "SPECTRA_QIHSE_RESP_2026!"
                    auth_resp = self._resp_exchange(
                        s, f"AUTH operator {pw}\r\n".encode("utf-8")
                    )
                    if not auth_resp.startswith(b"+OK"):
                        return None
                return self._resp_exchange(s, resp_data)
        except Exception:
            return None
        finally:
            time.sleep(_FD_REUSE_GRACE_S)

    def kv_set(self, key: str, value: str, ttl_ms: int = 0) -> bool:
        """SET key value [PX ttl_ms].  Returns True if the server replied +OK."""
        args = ["SET", key, value]
        if ttl_ms > 0:
            args.extend(["PX", str(ttl_ms)])
        resp = self.resp_command(*args)
        return resp is not None and resp.startswith(b"+OK")

    def kv_setnx(self, key: str, value: str, ttl_ms: int = 0) -> bool:
        """SET key value NX [PX ttl_ms].  Returns True if set (key was absent)."""
        args = ["SET", key, value, "NX"]
        if ttl_ms > 0:
            args.extend(["PX", str(ttl_ms)])
        resp = self.resp_command(*args)
        return resp is not None and resp.startswith(b"+OK")

    def kv_get(self, key: str) -> Optional[str]:
        """GET key.  Returns the value string, or None if key doesn't exist."""
        resp = self.resp_command("GET", key)
        if resp is None or resp.startswith(b"$-1"):
            return None
        # Parse bulk string: $<len>\r\n<data>\r\n
        if resp.startswith(b"$"):
            hdr_end = resp.index(b"\r\n")
            data = resp[hdr_end + 2:]
            # Strip trailing \r\n
            if data.endswith(b"\r\n"):
                data = data[:-2]
            return data.decode("utf-8")
        return None

    def kv_del(self, key: str) -> bool:
        """DEL key.  Returns True if the key was deleted."""
        resp = self.resp_command("DEL", key)
        return resp is not None and resp.startswith(b":1")

    def kv_expire(self, key: str, ttl_ms: int) -> bool:
        """PEXPIRE key ttl_ms.  Returns True if the TTL was set."""
        resp = self.resp_command("PEXPIRE", key, str(ttl_ms))
        return resp is not None and resp.startswith(b":1")


# Alias matching alternative naming conventions
QihseRespServer = QIHSEResPServer

__all__ = [
    "QIHSEResPServer",
    "QihseRespServer",
    "QihseRespServerConfig",
    "qihse_resp_available",
    "qihse_resp_server_config_init",
    "qihse_resp_server_create",
    "qihse_resp_server_start",
    "qihse_resp_server_run",
    "qihse_resp_server_stop",
    "qihse_resp_server_destroy",
    "qihse_resp_server_port",
]

