"""
Async File Search — Distributed across sessions using QIHSE KV/RESP coordination
=================================================================================

Distributes file search work across multiple Telegram sessions, assigning
different channel groups to each session to avoid overlap. Uses QIHSE's
RESP-compatible KV store for:
  - Atomic work-item claiming (SETNX with TTL)
  - Session → channel group assignment
  - Result aggregation
  - Progress tracking

If QIHSE RESP is not available, falls back to Redis (if installed) or to
a local SQLite-based coordination layer.

Usage (library)::

    from tgarchive.services.async_file_search import AsyncFileSearch

    searcher = AsyncFileSearch(db_path="spectra.db", sessions_dir="sessions")
    results = searcher.search_all("invoice.pdf")

Usage (CLI)::

    spectra-cli file-search-async "invoice.pdf"
    spectra-cli file-search-async "archive.zip" --workers 4
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .file_search import search_files, _extract_passwords

logger = logging.getLogger(__name__)


# ─── Coordination Layer ──────────────────────────────────────────────────────

class CoordinationBackend:
    """Abstract coordination backend for work distribution."""

    def claim(self, key: str, value: str, ttl_ms: int = 30000) -> bool:
        """Atomically claim a work item. Returns True if claimed."""
        raise NotImplementedError

    def release(self, key: str) -> None:
        """Release a claimed work item."""
        raise NotImplementedError

    def set(self, key: str, value: str, ttl_ms: int = 0) -> None:
        """Set a key-value pair with optional TTL."""
        raise NotImplementedError

    def get(self, key: str) -> Optional[str]:
        """Get a value by key."""
        raise NotImplementedError

    def delete(self, key: str) -> None:
        """Delete a key."""
        raise NotImplementedError

    def incr(self, key: str) -> int:
        """Atomically increment a counter."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class QIHSECoordination(CoordinationBackend):
    """QIHSE RESP-compatible coordination backend using a persistent socket.

    Keeps a single TCP connection open for the lifetime of the backend and
    multiplexes all commands over it, eliminating the per-command connect /
    close cycle (and the 0.01 s fd-reuse grace delay) that dominated the
    cost of thousands of coordination calls during a password search.

    Thread safety
    -------------
    A ``threading.Lock`` serialises every ``_send_and_recv`` call so the
    swarm heartbeat thread and the main search thread can safely share one
    connection.

    Stale-buffer fix
    ----------------
    The original ``RespConnection`` returned replies left over in the read
    buffer from *prior* commands (e.g. GET returned the ``+OK`` of an
    earlier SET).  This implementation reads exactly the bytes that belong
    to the current reply (one RESP frame) and, after consuming it, verifies
    the buffer is empty.  Any leftover bytes — which would corrupt the next
    reply — are discarded and logged, so every command starts from a clean
    slate.

    Automatic reconnect
    -------------------
    If the persistent socket drops (EPIPE, reset, timeout), ``_reconnect``
    closes and reopens it and the failed command is retried exactly once.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 6379, timeout: float = 5.0,
                 quiet: bool = False, fallback_db: Optional[Path | str] = None,
                 command_timeout: float = 0.5):
        self.host = host
        self.port = port
        self.timeout = timeout
        # Short per-command timeout used for recv() after the socket is
        # connected.  If the QIHSE C RESP engine hangs (known issue: the
        # kv_lock is held for the entire SET operation and the trinary-trie
        # insertion can block), we detect it quickly and fall back to
        # SQLiteCoordination instead of blocking the search indefinitely.
        self.command_timeout = command_timeout
        self._fallback_db = fallback_db
        self._available = False
        self._sock: Optional[socket.socket] = None
        self._buffer = bytearray()
        self._lock = threading.Lock()
        # Auto-fallback state — once a command times out we permanently
        # switch to SQLiteCoordination for the rest of this session.
        self._fallback = False
        self._fallback_backend: Optional[SQLiteCoordination] = None
        self._fallback_warned = False
        try:
            self._connect()
            self._available = True
            logger.info("QIHSE RESP coordination connected at %s:%d", host, port)
        except Exception as e:
            # The first probe is expected to fail when the in-process RESP
            # server has not been started yet; suppress the noisy warning in
            # that case so users don't see a misleading "not available" line.
            if quiet:
                logger.debug("QIHSE RESP not available (quiet probe): %s", e)
            else:
                logger.warning("QIHSE RESP not available: %s", e)
            self._available = False

    def available(self) -> bool:
        # Still "available" from the caller's perspective even after
        # fallback — the backend transparently delegates to SQLite.
        return self._available or self._fallback

    # ── persistent-socket transport ───────────────────────────────────────

    def _connect(self) -> None:
        """Open (or reopen) the persistent socket and reset the read buffer.

        The *connect* phase uses ``self.timeout`` (generous, e.g. 5 s) so we
        don't falsely fail on a slow loopback.  Once connected, the socket
        recv/send timeout is lowered to ``self.command_timeout`` (0.5 s) so
        that a hung QIHSE C RESP engine is detected quickly and we can fall
        back to SQLiteCoordination instead of blocking the search.
        """
        self._close_sock()
        self._buffer.clear()
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.command_timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock

    def _close_sock(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _reconnect(self) -> None:
        """Close the dead socket and open a fresh one."""
        logger.debug("QIHSE RESP reconnecting to %s:%d", self.host, self.port)
        self._connect()

    # ── RESP frame reader (exact bytes per reply type) ────────────────────

    def _read_byte(self) -> int:
        while not self._buffer:
            if self._sock is None:
                raise ConnectionError("socket closed")
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed by server")
            self._buffer.extend(chunk)
        b = self._buffer[0]
        del self._buffer[0]
        return b

    def _read_line(self) -> bytes:
        line = bytearray()
        while True:
            b = self._read_byte()
            if b == 0x0A and line and line[-1] == 0x0D:  # \n after \r
                line.pop()
                return bytes(line)
            line.append(b)

    def _read_exact(self, count: int) -> bytes:
        while len(self._buffer) < count:
            if self._sock is None:
                raise ConnectionError("socket closed")
            chunk = self._sock.recv(max(4096, count - len(self._buffer)))
            if not chunk:
                raise ConnectionError("Connection closed by server")
            self._buffer.extend(chunk)
        res = bytes(self._buffer[:count])
        del self._buffer[:count]
        return res

    def _read_response(self) -> bytes:
        """Read exactly one RESP frame and return it as raw bytes.

        The returned value is the *complete* raw frame (prefix + payload +
        CRLF where applicable) so callers can parse it the same way the
        old socket-per-command code did.
        """
        prefix = self._read_byte()
        prefix_b = bytes([prefix])
        if prefix in (0x2B, 0x2D, 0x3A):  # '+', '-', ':'
            line = self._read_line()
            return prefix_b + line + b"\r\n"
        elif prefix == 0x24:  # '$' bulk string
            line = self._read_line()
            length = int(line)
            if length < 0:
                return prefix_b + line + b"\r\n"  # nil: $-1\r\n
            data = self._read_exact(length)
            crlf = self._read_exact(2)
            if crlf != b"\r\n":
                raise ConnectionError("malformed bulk string trailer")
            return prefix_b + line + b"\r\n" + data + b"\r\n"
        elif prefix == 0x2A:  # '*' array
            line = self._read_line()
            count = int(line)
            if count < 0:
                return prefix_b + line + b"\r\n"
            frames = [prefix_b + line + b"\r\n"]
            for _ in range(count):
                frames.append(self._read_response())
            return b"".join(frames)
        else:
            # Unknown prefix — read the line and return best-effort.
            line = self._read_line()
            return prefix_b + line + b"\r\n"

    def _trigger_fallback(self) -> None:
        """Permanently switch to SQLiteCoordination for the rest of the session.

        Called when a QIHSE RESP command times out — the C engine's kv_lock
        is held for the entire SET/GET operation and the trinary-trie
        insertion can block indefinitely, so retrying or reconnecting will
        not help.  We log a single warning and create a SQLiteCoordination
        backend that all subsequent calls transparently delegate to.
        """
        if self._fallback:
            return
        self._fallback = True
        self._available = False
        self._close_sock()
        db = self._fallback_db or Path("spectra_coord.db")
        try:
            self._fallback_backend = SQLiteCoordination(db)
        except Exception as e:
            logger.error("QIHSE RESP fallback to SQLite failed: %s", e)
            self._fallback_backend = None
        if not self._fallback_warned:
            self._fallback_warned = True
            logger.warning(
                "QIHSE RESP server at %s:%d is too slow (command timed out after "
                "%.1fs) — falling back to SQLiteCoordination (%s) for the rest of "
                "this session. The QIHSE C RESP engine has a known hang issue "
                "(kv_lock held during trinary-trie insertion). Search will "
                "continue normally; QIHSE RESP will be used automatically once "
                "the C bug is fixed.",
                self.host, self.port, self.command_timeout, db,
            )

    def _send_and_recv(self, *args: str) -> Optional[bytes]:
        """Send one RESP command on the persistent socket and read its reply.

        On a transport error the socket is reopened and the command retried
        exactly once.  After a successful read the buffer is verified empty;
        any stale leftover bytes are discarded so they cannot corrupt the
        next command's reply.

        If the command times out (``socket.timeout``) — indicating the QIHSE
        C RESP engine has hung — ``_trigger_fallback`` is called and ``None``
        is returned.  All subsequent calls will be transparently delegated
        to a SQLiteCoordination backend.
        """
        if not self._available:
            return None
        # Build RESP array: *N\r\n$len\r\narg\r\n...
        parts = [f"*{len(args)}\r\n".encode("utf-8")]
        for a in args:
            ab = a.encode("utf-8")
            parts.append(f"${len(ab)}\r\n".encode("utf-8"))
            parts.append(ab)
            parts.append(b"\r\n")
        resp_data = b"".join(parts)

        with self._lock:
            for attempt in (0, 1):
                try:
                    if self._sock is None:
                        self._connect()
                    assert self._sock is not None
                    self._sock.sendall(resp_data)
                    reply = self._read_response()
                    # Stale-buffer guard: after consuming exactly one frame
                    # the buffer must be empty.  If it isn't, leftover bytes
                    # from a prior (mis-sized) reply would be returned for
                    # the next command — discard them.
                    if self._buffer:
                        logger.warning(
                            "QIHSE RESP stale buffer detected (%d leftover bytes) "
                            "after %s — clearing",
                            len(self._buffer), args[0] if args else "?",
                        )
                        self._buffer.clear()
                    return reply
                except socket.timeout as e:
                    # The C RESP engine hung — kv_lock held during a slow
                    # trinary-trie insertion.  Reconnecting won't help
                    # because the server thread is blocked on the lock.
                    # Fall back to SQLiteCoordination permanently.
                    logger.debug(
                        "QIHSE RESP %s timed out after %.1fs (attempt %d): %s",
                        args[0] if args else "?", self.command_timeout,
                        attempt + 1, e,
                    )
                    self._close_sock()
                    self._trigger_fallback()
                    return None
                except (OSError, ConnectionError) as e:
                    logger.debug(
                        "QIHSE RESP %s attempt %d failed: %s",
                        args[0] if args else "?", attempt + 1, e,
                    )
                    # Drop the dead socket; next loop iteration reconnects.
                    self._close_sock()
                    if attempt == 0:
                        try:
                            self._reconnect()
                        except Exception as re_err:
                            logger.warning("QIHSE RESP reconnect failed: %s", re_err)
                            return None
                        continue
                    return None
        return None

    # ── CoordinationBackend implementation ─────────────────────────────────

    def claim(self, key: str, value: str, ttl_ms: int = 30000) -> bool:
        """Atomically claim a work item via SET key value NX PX ttl_ms."""
        if self._fallback and self._fallback_backend is not None:
            return self._fallback_backend.claim(key, value, ttl_ms)
        resp = self._send_and_recv("SET", key, value, "NX", "PX", str(ttl_ms))
        return resp is not None and resp.startswith(b"+OK")

    def release(self, key: str) -> None:
        """Release a claimed work item via DEL key."""
        if self._fallback and self._fallback_backend is not None:
            self._fallback_backend.release(key)
            return
        self._send_and_recv("DEL", key)

    def set(self, key: str, value: str, ttl_ms: int = 0) -> None:
        """Set a key-value pair with optional TTL."""
        if self._fallback and self._fallback_backend is not None:
            self._fallback_backend.set(key, value, ttl_ms)
            return
        args = ["SET", key, value]
        if ttl_ms > 0:
            args.extend(["PX", str(ttl_ms)])
        self._send_and_recv(*args)

    def get(self, key: str) -> Optional[str]:
        """Get a value by key."""
        if self._fallback and self._fallback_backend is not None:
            return self._fallback_backend.get(key)
        resp = self._send_and_recv("GET", key)
        if resp is None or resp.startswith(b"$-1"):
            return None
        if resp.startswith(b"$"):
            hdr_end = resp.index(b"\r\n")
            data = resp[hdr_end + 2:]
            if data.endswith(b"\r\n"):
                data = data[:-2]
            return data.decode("utf-8", errors="replace")
        return None

    def delete(self, key: str) -> None:
        """Delete a key."""
        if self._fallback and self._fallback_backend is not None:
            self._fallback_backend.delete(key)
            return
        self._send_and_recv("DEL", key)

    def incr(self, key: str) -> int:
        """Atomically increment a counter."""
        if self._fallback and self._fallback_backend is not None:
            return self._fallback_backend.incr(key)
        resp = self._send_and_recv("INCR", key)
        if resp is None:
            return 0
        if resp.startswith(b":"):
            try:
                return int(resp[1:resp.index(b"\r\n")])
            except (ValueError, IndexError):
                return 0
        return 0

    def close(self) -> None:
        with self._lock:
            self._close_sock()
            self._buffer.clear()
            self._available = False
        if self._fallback_backend is not None:
            self._fallback_backend.close()


class RedisCoordination(CoordinationBackend):
    """Redis coordination backend (fallback)."""

    def __init__(self, url: str = "redis://localhost:6379"):
        self._client = None
        try:
            import redis
            self._client = redis.from_url(url, decode_responses=True)
            self._client.ping()
            logger.info("Redis coordination connected: %s", url)
        except Exception as e:
            logger.warning("Redis not available: %s", e)
            self._client = None

    def available(self) -> bool:
        return self._client is not None

    def claim(self, key: str, value: str, ttl_ms: int = 30000) -> bool:
        if not self._client:
            return False
        try:
            return self._client.set(key, value, nx=True, px=ttl_ms)
        except Exception:
            return False

    def release(self, key: str) -> None:
        if not self._client:
            return
        try:
            self._client.delete(key)
        except Exception:
            pass

    def set(self, key: str, value: str, ttl_ms: int = 0) -> None:
        if not self._client:
            return
        try:
            if ttl_ms > 0:
                self._client.set(key, value, px=ttl_ms)
            else:
                self._client.set(key, value)
        except Exception:
            pass

    def get(self, key: str) -> Optional[str]:
        if not self._client:
            return None
        try:
            return self._client.get(key)
        except Exception:
            return None

    def delete(self, key: str) -> None:
        self.release(key)

    def incr(self, key: str) -> int:
        if not self._client:
            return 0
        try:
            return self._client.incr(key)
        except Exception:
            return 0

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass


class SQLiteCoordination(CoordinationBackend):
    """Local SQLite coordination fallback (single-process only)."""

    def __init__(self, db_path: Path | str):
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, isolation_level=None, check_same_thread=False)
        self._conn_lock = threading.Lock()
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS coord_kv (
                key   TEXT PRIMARY KEY,
                value TEXT,
                expires_at REAL
            )
        """)
        self._lock = asyncio.Lock() if False else None  # Not used; SQLite is sync

    def _purge_expired(self) -> None:
        """Purge expired keys. Caller must hold _conn_lock."""
        now = time.time()
        self._conn.execute("DELETE FROM coord_kv WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))

    def claim(self, key: str, value: str, ttl_ms: int = 30000) -> bool:
        try:
            with self._conn_lock:
                self._purge_expired()
                expires_at = time.time() + (ttl_ms / 1000.0)
                self._conn.execute(
                    "INSERT INTO coord_kv(key, value, expires_at) VALUES (?, ?, ?)",
                    (key, value, expires_at),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def release(self, key: str) -> None:
        with self._conn_lock:
            self._conn.execute("DELETE FROM coord_kv WHERE key = ?", (key,))

    def set(self, key: str, value: str, ttl_ms: int = 0) -> None:
        expires_at = time.time() + (ttl_ms / 1000.0) if ttl_ms > 0 else None
        with self._conn_lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO coord_kv(key, value, expires_at) VALUES (?, ?, ?)",
                (key, value, expires_at),
            )

    def get(self, key: str) -> Optional[str]:
        with self._conn_lock:
            self._purge_expired()
            row = self._conn.execute("SELECT value FROM coord_kv WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def delete(self, key: str) -> None:
        self.release(key)

    def incr(self, key: str) -> int:
        with self._conn_lock:
            self._purge_expired()
            row = self._conn.execute("SELECT value FROM coord_kv WHERE key = ?", (key,)).fetchone()
            val = int(row[0]) if row else 0
            val += 1
            self._conn.execute(
                "INSERT OR REPLACE INTO coord_kv(key, value, expires_at) VALUES (?, ?, ?)",
                (key, str(val), None),
            )
        return val

    def close(self) -> None:
        with self._conn_lock:
            self._conn.close()


def get_coordination_backend(
    *,
    qihse_host: str = "127.0.0.1",
    qihse_port: int = 6379,
    redis_url: Optional[str] = None,
    fallback_db: Optional[Path | str] = None,
    quiet: bool = False,
) -> CoordinationBackend:
    """Get the best available coordination backend.

    Tries QIHSE RESP first, then Redis, then SQLite fallback.

    When ``quiet`` is True the QIHSE RESP probe failure is logged at DEBUG
    level instead of WARNING — use this for the initial probe that is
    expected to fail before the in-process RESP server has been started.
    """
    # Try QIHSE RESP
    qihse = QIHSECoordination(host=qihse_host, port=qihse_port, quiet=quiet,
                              fallback_db=fallback_db or Path("spectra_coord.db"))
    if qihse.available():
        return qihse
    qihse.close()

    # Try Redis
    url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
    redis_backend = RedisCoordination(url)
    if redis_backend.available():
        return redis_backend
    redis_backend.close()

    # Fallback to SQLite
    db = fallback_db or Path("spectra_coord.db")
    logger.info("Falling back to SQLite coordination: %s", db)
    return SQLiteCoordination(db)


# ─── Session Discovery ───────────────────────────────────────────────────────

@dataclass
class SessionInfo:
    """Information about a Telegram session."""
    session_path: Path
    json_path: Path
    user_id: int
    dc_id: int
    api_id: int
    api_hash: str
    phone: Optional[str] = None
    username: Optional[str] = None


def discover_sessions(sessions_dir: Path | str = "sessions") -> List[SessionInfo]:
    """Discover all available Telegram sessions in a directory."""
    sessions_dir = Path(sessions_dir)
    sessions: List[SessionInfo] = []

    if not sessions_dir.exists():
        return sessions

    for json_file in sorted(sessions_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text())
            session_file = json_file.with_suffix(".session")
            if not session_file.exists():
                continue
            sessions.append(SessionInfo(
                session_path=session_file,
                json_path=json_file,
                user_id=data.get("user_id", 0),
                dc_id=data.get("dc_id", 4),
                api_id=data.get("api_id", 2040),
                api_hash=data.get("api_hash", ""),
                phone=data.get("phone"),
                username=data.get("username"),
            ))
        except (json.JSONDecodeError, KeyError):
            continue

    return sessions


# ─── Channel Assignment ──────────────────────────────────────────────────────

def assign_channels_to_sessions(
    sessions: List[SessionInfo],
    channels: List[Tuple[int, str]],
    coord: CoordinationBackend,
) -> Dict[int, List[Tuple[int, str]]]:
    """Assign channels to sessions, avoiding overlap.

    Uses the coordination backend to atomically claim channel assignments.
    If a channel is already claimed by another session, it's skipped.

    Returns a mapping of session index → list of (channel_id, channel_name).
    """
    assignment: Dict[int, List[Tuple[int, str]]] = {i: [] for i in range(len(sessions))}
    if not sessions or not channels:
        return assignment

    # Round-robin assignment with atomic claims
    for ch_id, ch_name in channels:
        claim_key = f"spectra:filesearch:channel:{ch_id}"
        claimed_by = coord.get(claim_key)

        if claimed_by:
            # Already assigned — find which session
            try:
                session_idx = int(claimed_by)
                if 0 <= session_idx < len(sessions):
                    assignment[session_idx].append((ch_id, ch_name))
                continue
            except (ValueError, TypeError):
                pass

        # Find the session with the fewest assignments
        min_idx = min(assignment, key=lambda i: len(assignment[i]))
        session = sessions[min_idx]

        # Try to claim atomically
        claim_value = str(min_idx)
        if coord.claim(claim_key, claim_value, ttl_ms=600000):  # 10 min TTL
            assignment[min_idx].append((ch_id, ch_name))
        else:
            # Someone else claimed it — read who
            claimed_by = coord.get(claim_key)
            if claimed_by:
                try:
                    session_idx = int(claimed_by)
                    if 0 <= session_idx < len(sessions):
                        assignment[session_idx].append((ch_id, ch_name))
                except (ValueError, TypeError):
                    pass

    return assignment


# ─── Async File Search ───────────────────────────────────────────────────────

@dataclass
class FileSearchResult:
    """Result from a single session's file search."""
    session_index: int
    session_user_id: int
    channels_searched: int
    files_found: int
    passwords_found: int
    results: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


class TelegramFileSearcher:
    """Search files on Telegram directly via Telethon session.

    Connects to Telegram using a .session file, iterates media in assigned
    channels, and returns results matching the query. Merges with local DB
    results for a complete picture.
    """

    def __init__(self, session_path: Path | str, *, api_id: Optional[int] = None, api_hash: Optional[str] = None):
        self.session_path = Path(session_path)
        self.api_id = api_id
        self.api_hash = api_hash
        self._client = None

    async def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from telethon import TelegramClient
        except ImportError:
            logger.warning("Telethon not available — cannot search Telegram directly")
            return None
        # Try to load API credentials from session metadata
        if self.api_id is None or self.api_hash is None:
            meta_path = self.session_path.with_suffix(".json")
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                self.api_id = self.api_id or meta.get("api_id")
                self.api_hash = self.api_hash or meta.get("api_hash")
        if self.api_id is None or self.api_hash is None:
            logger.warning("No API credentials for session %s — cannot connect", self.session_path)
            return None
        session_stem = str(self.session_path.with_suffix(""))
        self._client = TelegramClient(session_stem, int(self.api_id), self.api_hash)
        await self._client.connect()
        if not await self._client.is_user_authorized():
            logger.warning("Session %s not authorized — skipping", self.session_path)
            await self._client.disconnect()
            self._client = None
            return None
        return self._client

    async def search_channels(
        self,
        query: str,
        channel_ids: List[int],
        *,
        fuzzy: bool = True,
        threshold: float = 0.5,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search media in Telegram channels directly via Telethon.

        Returns a list of media match dicts compatible with file_search output.
        """
        from .file_search import _fuzzy_match, _extract_filename

        client = await self._get_client()
        if client is None:
            return []

        results: List[Dict[str, Any]] = []
        q_lower = query.lower()

        for channel_id in channel_ids:
            try:
                entity = await client.get_entity(channel_id)
                async for message in client.iter_messages(entity, limit=limit * 5):
                    if not message.media:
                        continue
                    media = message.media
                    # Extract filename from document attributes
                    filename = ""
                    if hasattr(media, "document") and media.document:
                        for attr in media.document.attributes:
                            if hasattr(attr, "file_name") and attr.file_name:
                                filename = attr.file_name
                                break
                    if not filename:
                        continue

                    # Score the match
                    score = 0.0
                    match_type = "none"
                    if fuzzy:
                        score = _fuzzy_match(query, filename, threshold)
                        if score >= threshold:
                            match_type = "filename_fuzzy"
                    else:
                        if q_lower in filename.lower():
                            score = 1.0 if filename.lower() == q_lower else 0.9
                            match_type = "filename_exact"

                    if score < threshold:
                        continue

                    # Scan message text for passwords
                    text = message.text or ""
                    passwords: List[Dict[str, Any]] = []
                    if text:
                        from .file_search import _extract_passwords
                        passwords = _extract_passwords(text)

                    results.append({
                        "media_id": 0,  # Telegram media, no local ID
                        "filename": filename,
                        "title": "",
                        "type": "document",
                        "url": "",
                        "checksum": "",
                        "match_score": round(score, 4),
                        "match_type": match_type,
                        "message_refs": [{
                            "message_id": message.id,
                            "user_id": message.sender_id,
                            "date": message.date.isoformat() if message.date else None,
                            "content_preview": (text or "")[:100],
                        }],
                        "channel_refs": [{"channel_id": channel_id}],
                        "ref_count": 1,
                        "nearby_passwords": passwords,
                        "password_count": len(passwords),
                        "size": getattr(media.document, "size", None) if hasattr(media, "document") else None,
                        "mime_type": getattr(media.document, "mime_type", None) if hasattr(media, "document") else None,
                        "source": "telegram",
                    })
                    if len(results) >= limit:
                        return results
            except Exception as exc:
                logger.warning("Failed to search channel %s via Telethon: %s", channel_id, exc)
                continue
        return results

    async def close(self):
        if self._client:
            await self._client.disconnect()
            self._client = None


class TelegramPasswordFinder:
    """API-first password finder — searches Telegram directly for passwords near file mentions.

    When the local SPECTRA database is unavailable (or as a first-class method),
    this class connects to all available Telegram sessions, discovers accessible
    channels/dialogs, searches for messages mentioning the target filenames,
    and scans nearby messages (before and after) for password patterns.

    This mirrors the DB-based search_files() password scanning but pulls data
    live from Telegram instead of SQLite.
    """

    def __init__(
        self,
        sessions_dir: Path | str = "sessions",
        *,
        password_window: int = 10,
        message_limit: int = 200,
        max_workers: int = 4,
        qihse_host: str = "127.0.0.1",
        qihse_port: int = 6379,
        redis_url: Optional[str] = None,
        coord_db: Optional[Path | str] = None,
        enable_swarm: bool = True,
        msnet_port: int = 8899,
        lan_cidr: str = "192.168.1.0/24",
        hmac_key: Optional[bytes] = None,
        node_id: Optional[str] = None,
    ):
        self.sessions_dir = Path(sessions_dir)
        self.sessions = discover_sessions(sessions_dir)
        self.password_window = password_window
        self.message_limit = message_limit
        self.max_workers = max_workers
        self.enable_swarm = enable_swarm
        self._resp_server: Optional[Any] = None
        self._msnet_transport: Optional[Any] = None
        self._swarm: Optional[Any] = None
        self._qihse_host = qihse_host
        self._qihse_port = qihse_port

        # If swarm mode is enabled, ensure the QIHSE RESP server is running
        # *before* creating the coordination backend.  Previously the backend
        # was created first (always falling back to SQLite because the RESP
        # server was not up yet) and then re-created after starting the
        # server — which logged a misleading "QIHSE RESP not available"
        # warning and left the mode reporting showing the SQLite fallback.
        if enable_swarm and not self._coord_alive(qihse_host, qihse_port):
            self._start_resp_server(qihse_host, qihse_port)

        # Create the coordination backend exactly once.  By this point the
        # in-process RESP server (if any) is already listening, so the QIHSE
        # probe will succeed instead of falling back to SQLite.
        self.coord = get_coordination_backend(
            qihse_host=qihse_host,
            qihse_port=qihse_port,
            redis_url=redis_url,
            fallback_db=coord_db or self.sessions_dir.parent / "spectra_coord.db",
        )

        # Start MSNET transport and swarm coordinator
        if enable_swarm:
            self._start_msnet_and_swarm(
                msnet_port=msnet_port,
                lan_cidr=lan_cidr,
                hmac_key=hmac_key,
                node_id=node_id,
            )

        self._search_id = f"pwfind-{uuid.uuid4().hex[:8]}"

    def _coord_alive(self, host: Optional[str] = None, port: Optional[int] = None) -> bool:
        """Check if the QIHSE RESP server is reachable (responds to PING).

        Accepts explicit ``host``/``port`` so it can be called *before* the
        coordination backend has been created.  Falls back to the backend's
        own host/port (or the values captured at construction time) when the
        arguments are omitted.
        """
        try:
            import socket as _sock
            h = host or (self.coord.host if hasattr(self, 'coord') and hasattr(self.coord, 'host') else self._qihse_host)
            p = port or (self.coord.port if hasattr(self, 'coord') and hasattr(self.coord, 'port') else self._qihse_port)
            with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.connect((h, p))
                s.sendall(b"PING\r\n")
                data = s.recv(32)
                return data.startswith(b"+PONG")
        except Exception:
            return False

    def _start_resp_server(self, host: str, port: int) -> None:
        """Start QIHSE RESP server in-process if available."""
        try:
            from ..search.qihse_resp_server import QIHSEResPServer
            self._resp_server = QIHSEResPServer(host=host, port=port)
            if self._resp_server.start():
                logger.info("Started QIHSE RESP server on %s:%d", host, port)
            else:
                logger.warning("QIHSE RESP server failed to start")
                self._resp_server = None
        except Exception as exc:
            logger.warning("QIHSE RESP server unavailable: %s", exc)
            self._resp_server = None

    def _start_msnet_and_swarm(
        self,
        msnet_port: int,
        lan_cidr: str,
        hmac_key: Optional[bytes],
        node_id: Optional[str],
    ) -> None:
        """Start MSNET transport and join the swarm."""
        try:
            from ..search.msnet_transport import MSNETTransport
            self._msnet_transport = MSNETTransport(
                host="0.0.0.0",
                port=msnet_port,
                lan_cidr=lan_cidr,
                hmac_key=hmac_key or b"",
                node_id=node_id or "",
            )
            self._msnet_transport.start()
            if self._msnet_transport.is_running():
                logger.info("MSNET transport started on port %d", msnet_port)
            else:
                logger.warning("MSNET transport failed to start on port %d", msnet_port)
                self._msnet_transport = None
        except Exception as exc:
            logger.warning("MSNET transport unavailable: %s", exc)
            self._msnet_transport = None

        try:
            from ..search.swarm_coordinator import SwarmCoordinator
            self._swarm = SwarmCoordinator(
                node_id=node_id,
                coord_backend=self.coord,
            )
            self._swarm.start(capabilities={
                "sessions": len(self.sessions),
                "node_type": "spectra",
            })
            logger.info("Swarm coordinator started as node %s", self._swarm.node_id)
        except Exception as exc:
            logger.warning("Swarm coordinator unavailable: %s", exc)
            self._swarm = None

    async def _discover_dialogs(self, client) -> List[Tuple[int, str]]:
        """Discover all accessible dialogs (channels/groups/chats) from a connected client."""
        dialogs = []
        try:
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                channel_id = 0
                try:
                    channel_id = entity.id
                except AttributeError:
                    pass
                if channel_id:
                    dialogs.append((channel_id, dialog.name or str(channel_id)))
        except Exception as exc:
            logger.warning("Failed to enumerate dialogs: %s", exc)
        return dialogs

    async def _scan_nearby_for_passwords(
        self,
        client,
        entity,
        file_message_id: int,
        *,
        window: int = 10,
    ) -> List[Dict[str, Any]]:
        """Scan messages around a file mention for password patterns.

        Fetches `window` messages before and after the file message,
        extracts passwords from each using the same _extract_passwords() logic
        as the DB-based search.
        """
        from .file_search import _extract_passwords

        passwords: List[Dict[str, Any]] = []
        seen_values: Set[str] = set()

        # Fetch messages around the file mention
        try:
            async for msg in client.iter_messages(
                entity,
                offset_id=file_message_id,
                limit=window * 2 + 1,
            ):
                text = msg.text or msg.message or ""
                if not text:
                    continue
                found = _extract_passwords(text)
                for p in found:
                    val = p.get("value", "")
                    if val and val not in seen_values:
                        seen_values.add(val)
                        passwords.append({
                            "value": val,
                            "keyword": p.get("keyword", ""),
                            "context": p.get("context", "")[:200],
                            "source_message_id": msg.id,
                            "source_date": msg.date.isoformat() if msg.date else None,
                            "source_user_id": msg.sender_id,
                            "offset": msg.id - file_message_id,
                        })
        except Exception as exc:
            logger.debug("Nearby password scan failed for msg %d: %s", file_message_id, exc)

        return passwords

    async def _search_session_for_files(
        self,
        session: SessionInfo,
        filenames: List[str],
        *,
        fuzzy: bool = True,
        threshold: float = 0.4,
        assigned_dialogs: Optional[List[Tuple[int, str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Search a single session for file mentions and scan for passwords.

        If assigned_dialogs is provided, only search those dialogs (QIHSE coordination).
        Otherwise discover and search all accessible dialogs.
        """
        from .file_search import _fuzzy_match, _extract_passwords

        searcher = TelegramFileSearcher(session.session_path)
        client = await searcher._get_client()
        if client is None:
            return []

        results: List[Dict[str, Any]] = []
        q_lowers = [f.lower() for f in filenames]

        try:
            if assigned_dialogs is not None:
                dialogs = assigned_dialogs
                logger.info("Session %s: searching %d assigned dialogs", session.user_id, len(dialogs))
            else:
                dialogs = await self._discover_dialogs(client)
                logger.info("Session %s: discovered %d dialogs", session.user_id, len(dialogs))

            for channel_id, channel_name in dialogs:
                try:
                    entity = await client.get_entity(channel_id)
                except Exception:
                    continue

                channel_results: List[Dict[str, Any]] = []

                try:
                    async for message in client.iter_messages(entity, limit=self.message_limit):
                        # Check if this message has a media file matching our targets
                        filename = ""
                        if message.media:
                            media = message.media
                            if hasattr(media, "document") and media.document:
                                for attr in media.document.attributes:
                                    if hasattr(attr, "file_name") and attr.file_name:
                                        filename = attr.file_name
                                        break

                        # Also check message text for filename mentions
                        text = message.text or message.message or ""
                        matched_filename = ""
                        match_score = 0.0
                        match_type = "none"

                        if filename:
                            for i, q_lower in enumerate(q_lowers):
                                if fuzzy:
                                    score = _fuzzy_match(filenames[i], filename, threshold)
                                    if score >= threshold and score > match_score:
                                        match_score = score
                                        match_type = "filename_fuzzy"
                                        matched_filename = filename
                                else:
                                    if q_lower in filename.lower():
                                        match_score = 1.0 if filename.lower() == q_lower else 0.9
                                        match_type = "filename_exact"
                                        matched_filename = filename
                                        break

                        # Also scan text for filename mentions (even without media)
                        if not matched_filename and text:
                            for i, q_lower in enumerate(q_lowers):
                                if q_lower in text.lower():
                                    match_score = 0.7
                                    match_type = "text_mention"
                                    matched_filename = filenames[i]
                                    break

                        if not matched_filename:
                            continue

                        # Scan the file message's own text for passwords
                        own_passwords: List[Dict[str, Any]] = []
                        if text:
                            for p in _extract_passwords(text):
                                own_passwords.append({
                                    "value": p.get("value", ""),
                                    "keyword": p.get("keyword", ""),
                                    "context": p.get("context", "")[:200],
                                    "source_message_id": message.id,
                                    "source_date": message.date.isoformat() if message.date else None,
                                    "source_user_id": message.sender_id,
                                    "offset": 0,
                                })

                        # Scan nearby messages for passwords
                        nearby_passwords = await self._scan_nearby_for_passwords(
                            client, entity, message.id,
                            window=self.password_window,
                        )

                        # Merge and dedup passwords
                        all_passwords: List[Dict[str, Any]] = []
                        seen_pw: Set[str] = set()
                        for p in own_passwords + nearby_passwords:
                            val = p.get("value", "")
                            if val and val not in seen_pw:
                                seen_pw.add(val)
                                all_passwords.append(p)

                        channel_results.append({
                            "filename": matched_filename,
                            "channel_id": channel_id,
                            "channel_name": channel_name,
                            "message_id": message.id,
                            "match_score": round(match_score, 4),
                            "match_type": match_type,
                            "passwords": all_passwords,
                            "password_count": len(all_passwords),
                            "session_user_id": session.user_id,
                            "source": "telegram_api",
                        })

                except Exception as exc:
                    logger.debug("Failed to search channel %s: %s", channel_id, exc)
                    continue

                results.extend(channel_results)

        finally:
            await searcher.close()

        return results

    async def find_passwords(
        self,
        filenames: List[str],
        *,
        fuzzy: bool = True,
        threshold: float = 0.4,
    ) -> Dict[str, Any]:
        """Search all Telegram sessions for file mentions and nearby passwords.

        Uses QIHSE RESP coordination to assign dialogs to sessions, avoiding
        overlap. Each session discovers its accessible dialogs, then claims
        them atomically via the coordination backend. Only assigned dialogs
        are scanned.

        Args:
            filenames: List of filenames to search for.
            fuzzy: Use fuzzy matching for filenames.
            threshold: Minimum fuzzy match score (0-1).

        Returns:
            Dict with per-file password results, aggregated stats, and per-session breakdown.
        """
        start_time = time.time()
        search_key = f"spectra:pwfind:{self._search_id}"

        if not self.sessions:
            return {
                "mode": "api",
                "sessions": 0,
                "files_searched": len(filenames),
                "results": [],
                "file_passwords": {},
                "summary": {
                    "total_files_found": 0,
                    "total_passwords_found": 0,
                    "files_with_passwords": 0,
                    "errors": ["No Telegram sessions found"],
                    "elapsed_seconds": 0.0,
                },
                "per_session": [],
            }

        self.coord.set(f"{search_key}:status", "discovering", ttl_ms=3600000)

        # Phase 1: All sessions discover their dialogs in parallel
        semaphore = asyncio.Semaphore(self.max_workers)

        async def discover_one(session: SessionInfo) -> Tuple[int, List[Tuple[int, str]]]:
            async with semaphore:
                searcher = TelegramFileSearcher(session.session_path)
                client = await searcher._get_client()
                if client is None:
                    return (session.user_id, [])
                try:
                    dialogs = await self._discover_dialogs(client)
                finally:
                    await searcher.close()
                return (session.user_id, dialogs)

        discover_tasks = [discover_one(s) for s in self.sessions]
        discover_results = await asyncio.gather(*discover_tasks, return_exceptions=True)

        # Collect all unique dialogs across all sessions
        all_dialogs: Dict[int, str] = {}  # channel_id → name
        per_session_dialogs: Dict[int, List[Tuple[int, str]]] = {}
        for idx, result in enumerate(discover_results):
            session = self.sessions[idx]
            if isinstance(result, Exception):
                logger.warning("Dialog discovery failed for session %s: %s", session.user_id, result)
                per_session_dialogs[idx] = []
                continue
            user_id, dialogs = result
            per_session_dialogs[idx] = dialogs
            for ch_id, ch_name in dialogs:
                if ch_id not in all_dialogs:
                    all_dialogs[ch_id] = ch_name

        total_dialogs = len(all_dialogs)
        logger.info("Discovered %d unique dialogs across %d sessions", total_dialogs, len(self.sessions))
        self.coord.set(f"{search_key}:total_dialogs", str(total_dialogs), ttl_ms=3600000)

        # Phase 2: Assign dialogs to sessions via QIHSE RESP coordination
        # Build a flat list of (channel_id, name) for assignment
        dialog_list = list(all_dialogs.items())
        assignments = assign_channels_to_sessions(self.sessions, dialog_list, self.coord)

        # Log assignments
        for idx, chans in assignments.items():
            self.coord.set(
                f"{search_key}:session:{idx}:dialogs",
                json.dumps([c[0] for c in chans]),
                ttl_ms=600000,
            )
            logger.info("Session %d assigned %d dialogs", idx, len(chans))

        self.coord.set(f"{search_key}:status", "searching", ttl_ms=3600000)

        # Phase 3: Each session searches only its assigned dialogs
        async def search_one(session_idx: int, session: SessionInfo, assigned: List[Tuple[int, str]]) -> List[Dict[str, Any]]:
            async with semaphore:
                self.coord.set(f"{search_key}:session:{session_idx}:status", "searching", ttl_ms=300000)
                try:
                    result = await self._search_session_for_files(
                        session, filenames, fuzzy=fuzzy, threshold=threshold,
                        assigned_dialogs=assigned,
                    )
                    self.coord.set(f"{search_key}:session:{session_idx}:status", "completed", ttl_ms=300000)
                    return result
                except Exception as exc:
                    self.coord.set(f"{search_key}:session:{session_idx}:status", "failed", ttl_ms=300000)
                    raise

        tasks = [
            search_one(idx, self.sessions[idx], assignments.get(idx, []))
            for idx in range(len(self.sessions))
        ]
        session_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate
        all_results: List[Dict[str, Any]] = []
        per_session: List[Dict[str, Any]] = []
        errors: List[str] = []

        for idx, result in enumerate(session_results):
            session = self.sessions[idx]
            if isinstance(result, Exception):
                errors.append(f"Session {idx} (user {session.user_id}): {result}")
                per_session.append({
                    "session_index": idx,
                    "user_id": session.user_id,
                    "dialogs_assigned": len(assignments.get(idx, [])),
                    "dialogs_searched": 0,
                    "files_found": 0,
                    "passwords_found": 0,
                    "error": str(result),
                })
            else:
                all_results.extend(result)
                pw_count = sum(r.get("password_count", 0) for r in result)
                per_session.append({
                    "session_index": idx,
                    "user_id": session.user_id,
                    "dialogs_assigned": len(assignments.get(idx, [])),
                    "dialogs_searched": len({r["channel_id"] for r in result}),
                    "files_found": len(result),
                    "passwords_found": pw_count,
                    "error": None,
                })

        # Group by filename
        by_file: Dict[str, List[Dict[str, Any]]] = {}
        for r in all_results:
            fname = r["filename"]
            by_file.setdefault(fname, []).append(r)

        # Dedup passwords per file across sessions/channels
        file_passwords: Dict[str, List[Dict[str, Any]]] = {}
        for fname, matches in by_file.items():
            seen_pw: Set[str] = set()
            unique_pw: List[Dict[str, Any]] = []
            for m in matches:
                for p in m.get("passwords", []):
                    val = p.get("value", "")
                    if val and val not in seen_pw:
                        seen_pw.add(val)
                        unique_pw.append(p)
            file_passwords[fname] = unique_pw

        total_passwords = sum(len(pws) for pws in file_passwords.values())
        files_with_pw = sum(1 for pws in file_passwords.values() if pws)

        elapsed = round(time.time() - start_time, 3)
        self.coord.set(f"{search_key}:status", "completed", ttl_ms=3600000)
        self.coord.set(f"{search_key}:elapsed", str(elapsed), ttl_ms=3600000)

        # Determine coordination mode
        if isinstance(self.coord, QIHSECoordination):
            mode = "api_qihse_resp"
        elif isinstance(self.coord, RedisCoordination):
            mode = "api_redis"
        else:
            mode = "api_sqlite_fallback"

        # Append swarm status to mode
        if self._swarm is not None:
            try:
                nodes = self._swarm.get_swarm_nodes()
                if len(nodes) > 1:
                    mode += "+swarm"
            except Exception:
                pass

        # Add swarm info if available
        swarm_nodes = []
        if self._swarm is not None:
            try:
                swarm_nodes = self._swarm.get_swarm_nodes()
            except Exception:
                pass

        return {
            "mode": mode,
            "sessions": len(self.sessions),
            "files_searched": len(filenames),
            "total_dialogs": total_dialogs,
            "swarm_nodes": len(swarm_nodes),
            "swarm_node_id": self._swarm.node_id if self._swarm else None,
            "results": all_results,
            "file_passwords": file_passwords,
            "summary": {
                "total_files_found": len(by_file),
                "total_passwords_found": total_passwords,
                "files_with_passwords": files_with_pw,
                "errors": errors,
                "elapsed_seconds": elapsed,
            },
            "per_session": per_session,
        }

    def close(self) -> None:
        """Stop swarm, MSNET transport, RESP server, and coordination backend."""
        if self._swarm is not None:
            try:
                self._swarm.stop()
            except Exception:
                pass
            self._swarm = None
        if self._msnet_transport is not None:
            try:
                self._msnet_transport.stop()
            except Exception:
                pass
            self._msnet_transport = None
        if self._resp_server is not None:
            try:
                self._resp_server.stop()
            except Exception:
                pass
            self._resp_server = None
        self.coord.close()


class AsyncFileSearch:
    """Distributed file search across multiple Telegram sessions.

    Assigns different channel groups to each session to avoid overlap,
    using QIHSE KV/RESP for coordination.
    """

    def __init__(
        self,
        db_path: Path | str = "spectra.db",
        sessions_dir: Path | str = "sessions",
        *,
        qihse_host: str = "127.0.0.1",
        qihse_port: int = 6379,
        redis_url: Optional[str] = None,
        coord_db: Optional[Path | str] = None,
    ):
        self.db_path = Path(db_path)
        self.sessions = discover_sessions(sessions_dir)
        self.coord = get_coordination_backend(
            qihse_host=qihse_host,
            qihse_port=qihse_port,
            redis_url=redis_url,
            fallback_db=coord_db or self.db_path.parent / "spectra_coord.db",
        )
        self._search_id = f"filesearch-{uuid.uuid4().hex[:8]}"

    def _get_all_channels(self) -> List[Tuple[int, str]]:
        """Get all known channels from the database."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT DISTINCT channel_id, channel_name FROM account_channel_access ORDER BY channel_id"
            ).fetchall()
            channels = [(r["channel_id"], r["channel_name"] or "") for r in rows]
            conn.close()
            return channels
        except sqlite3.OperationalError:
            return []

    def _search_local(
        self,
        query: str,
        *,
        file_hash: Optional[str] = None,
        fuzzy: bool = True,
        threshold: float = 0.5,
        scan_passwords: bool = True,
        password_window: int = 5,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Search the local SPECTRA database (all channels at once)."""
        return search_files(
            self.db_path,
            query=query,
            file_hash=file_hash,
            fuzzy=fuzzy,
            threshold=threshold,
            scan_passwords=scan_passwords,
            password_window=password_window,
            limit=limit,
        )

    async def search_all(
        self,
        query: str,
        *,
        file_hash: Optional[str] = None,
        fuzzy: bool = True,
        threshold: float = 0.5,
        scan_passwords: bool = True,
        password_window: int = 5,
        limit: int = 50,
        max_workers: int = 4,
    ) -> Dict[str, Any]:
        """Search for files across all sessions asynchronously.

        Distributes channel groups to sessions using QIHSE coordination.
        Falls back to local search if no sessions or coordination is unavailable.

        Args:
            query: Filename or partial filename to search for.
            file_hash: Hash to search for (alternative to query).
            fuzzy: Use fuzzy matching.
            threshold: Minimum match score.
            scan_passwords: Scan nearby messages for password fields.
            password_window: Messages to look around for passwords.
            limit: Max results per session.
            max_workers: Maximum concurrent search workers.

        Returns:
            Dict with aggregated results, per-session breakdown, and summary.
        """
        start_time = time.time()
        search_key = f"spectra:filesearch:{self._search_id}"

        # Track search in coordination
        self.coord.set(f"{search_key}:status", "started", ttl_ms=3600000)
        self.coord.set(f"{search_key}:query", query or file_hash or "", ttl_ms=3600000)

        # If no sessions, just do a local search
        if not self.sessions:
            logger.info("No sessions found — doing local database search")
            result = self._search_local(
                query, file_hash=file_hash, fuzzy=fuzzy, threshold=threshold,
                scan_passwords=scan_passwords, password_window=password_window, limit=limit,
            )
            result["mode"] = "local"
            result["sessions"] = 0
            result["search_id"] = self._search_id
            result["elapsed_seconds"] = round(time.time() - start_time, 3)
            self.coord.set(f"{search_key}:status", "completed", ttl_ms=3600000)
            return result

        # Get all channels and assign to sessions
        channels = self._get_all_channels()
        assignments = assign_channels_to_sessions(self.sessions, channels, self.coord)

        # Log assignment
        for idx, chans in assignments.items():
            self.coord.set(
                f"{search_key}:session:{idx}:channels",
                json.dumps([c[0] for c in chans]),
                ttl_ms=600000,
            )

        # Run searches in parallel
        semaphore = asyncio.Semaphore(max_workers)

        async def search_session(session_idx: int, session: SessionInfo, assigned_channels: List[Tuple[int, str]]) -> FileSearchResult:
            async with semaphore:
                self.coord.set(f"{search_key}:session:{session_idx}:status", "searching", ttl_ms=300000)

                try:
                    # Search local DB first (fast, no network)
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None,
                        lambda: self._search_local(
                            query,
                            file_hash=file_hash,
                            fuzzy=fuzzy,
                            threshold=threshold,
                            scan_passwords=scan_passwords,
                            password_window=password_window,
                            limit=limit,
                        ),
                    )

                    # Also search Telegram directly via Telethon for channels
                    # not yet in the local DB — merges remote results with local
                    tg_results: List[Dict[str, Any]] = []
                    if query and assigned_channels:
                        assigned_ids = [ch_id for ch_id, _ in assigned_channels]
                        try:
                            tg_searcher = TelegramFileSearcher(session.path)
                            tg_results = await tg_searcher.search_channels(
                                query,
                                assigned_ids,
                                fuzzy=fuzzy,
                                threshold=threshold,
                                limit=limit,
                            )
                            await tg_searcher.close()
                        except Exception as exc:
                            logger.debug("Telegram direct search failed for session %d: %s", session_idx, exc)

                    # Filter local results to only include assigned channels
                    # (only if channel_refs are present — if not, keep all results
                    # since we can't determine channel ownership)
                    if assigned_channels:
                        assigned_ids_set = {ch_id for ch_id, _ in assigned_channels}
                        filtered_results = []
                        has_channel_refs = False
                        for r in result.get("results", []):
                            chan_refs = r.get("channel_refs", [])
                            if chan_refs:
                                has_channel_refs = True
                                if any(c["channel_id"] in assigned_ids_set for c in chan_refs):
                                    filtered_results.append(r)
                            else:
                                # No channel refs — can't filter, keep it
                                filtered_results.append(r)
                        # Only apply filter if we actually found channel refs
                        if has_channel_refs:
                            result["results"] = filtered_results
                            result["summary"]["total_matches"] = len(filtered_results)

                    # Merge Telegram remote results with local results
                    # (dedup by filename + channel_id)
                    if tg_results:
                        seen_keys = {
                            (r.get("filename", ""), r.get("channel_refs", [{}])[0].get("channel_id", 0))
                            for r in result.get("results", [])
                        }
                        for tr in tg_results:
                            key = (tr.get("filename", ""), tr.get("channel_refs", [{}])[0].get("channel_id", 0))
                            if key not in seen_keys:
                                result.setdefault("results", []).append(tr)
                                seen_keys.add(key)

                    files_found = len(result.get("results", []))
                    passwords_found = sum(r.get("password_count", 0) for r in result.get("results", []))

                    self.coord.set(f"{search_key}:session:{session_idx}:status", "completed", ttl_ms=300000)
                    self.coord.set(f"{search_key}:session:{session_idx}:files", str(files_found), ttl_ms=300000)
                    self.coord.incr(f"{search_key}:files_found")

                    return FileSearchResult(
                        session_index=session_idx,
                        session_user_id=session.user_id,
                        channels_searched=len(assigned_channels),
                        files_found=files_found,
                        passwords_found=passwords_found,
                        results=result.get("results", []),
                    )

                except Exception as e:
                    logger.error("Session %d search failed: %s", session_idx, e)
                    self.coord.set(f"{search_key}:session:{session_idx}:status", "failed", ttl_ms=300000)
                    self.coord.set(f"{search_key}:session:{session_idx}:error", str(e)[:256], ttl_ms=300000)
                    return FileSearchResult(
                        session_index=session_idx,
                        session_user_id=session.user_id,
                        channels_searched=len(assigned_channels),
                        files_found=0,
                        passwords_found=0,
                        error=str(e),
                    )

        # Launch all session searches
        tasks = [
            search_session(idx, session, assignments[idx])
            for idx, session in enumerate(self.sessions)
        ]
        session_results: List[FileSearchResult] = await asyncio.gather(*tasks)

        # Aggregate results
        all_results: List[Dict[str, Any]] = []
        total_passwords = 0
        total_files = 0
        total_channels = 0
        errors: List[str] = []

        for sr in session_results:
            all_results.extend(sr.results)
            total_passwords += sr.passwords_found
            total_files += sr.files_found
            total_channels += sr.channels_searched
            if sr.error:
                errors.append(f"Session {sr.session_index} (user {sr.session_user_id}): {sr.error}")

        # Deduplicate by media_id
        seen_ids: Set[int] = set()
        deduped: List[Dict[str, Any]] = []
        for r in all_results:
            mid = r.get("media_id")
            if mid not in seen_ids:
                seen_ids.add(mid)
                deduped.append(r)

        # Sort by match score
        deduped.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        deduped = deduped[:limit]

        elapsed = round(time.time() - start_time, 3)
        self.coord.set(f"{search_key}:status", "completed", ttl_ms=3600000)
        self.coord.set(f"{search_key}:elapsed", str(elapsed), ttl_ms=3600000)

        # Determine coordination mode
        if isinstance(self.coord, QIHSECoordination):
            mode = "qihse_resp"
        elif isinstance(self.coord, RedisCoordination):
            mode = "redis"
        else:
            mode = "sqlite_fallback"

        return {
            "search_id": self._search_id,
            "query": query or file_hash,
            "mode": mode,
            "sessions": len(self.sessions),
            "channels_assigned": total_channels,
            "results": deduped,
            "summary": {
                "total_matches": len(deduped),
                "total_files_found": total_files,
                "total_passwords_found": total_passwords,
                "files_with_passwords": sum(1 for r in deduped if r.get("password_count", 0) > 0),
                "best_match_score": deduped[0]["match_score"] if deduped else 0.0,
                "errors": errors,
                "elapsed_seconds": elapsed,
            },
            "per_session": [
                {
                    "session_index": sr.session_index,
                    "user_id": sr.session_user_id,
                    "channels_searched": sr.channels_searched,
                    "files_found": sr.files_found,
                    "passwords_found": sr.passwords_found,
                    "error": sr.error,
                }
                for sr in session_results
            ],
        }

    def close(self) -> None:
        self.coord.close()


# ─── Convenience function ────────────────────────────────────────────────────

async def async_search_files(
    db_path: Path | str,
    query: str,
    *,
    sessions_dir: Path | str = "sessions",
    **kwargs: Any,
) -> Dict[str, Any]:
    """One-shot async file search across all sessions."""
    searcher = AsyncFileSearch(db_path=db_path, sessions_dir=sessions_dir)
    try:
        return await searcher.search_all(query, **kwargs)
    finally:
        searcher.close()


async def find_passwords_api(
    filenames: List[str],
    *,
    sessions_dir: Path | str = "sessions",
    password_window: int = 10,
    message_limit: int = 200,
    max_workers: int = 4,
    fuzzy: bool = True,
    threshold: float = 0.4,
    enable_swarm: bool = True,
    msnet_port: int = 8899,
    lan_cidr: str = "192.168.1.0/24",
) -> Dict[str, Any]:
    """One-shot API-first password search across all Telegram sessions.

    Searches Telegram directly (no DB required) for messages mentioning the
    given filenames, then scans nearby messages for password patterns.
    Uses QIHSE RESP for dialog work distribution across sessions.
    Starts MSNET transport and joins swarm for multi-node work sharing.
    """
    finder = TelegramPasswordFinder(
        sessions_dir=sessions_dir,
        password_window=password_window,
        message_limit=message_limit,
        max_workers=max_workers,
        enable_swarm=enable_swarm,
        msnet_port=msnet_port,
        lan_cidr=lan_cidr,
    )
    try:
        return await finder.find_passwords(filenames, fuzzy=fuzzy, threshold=threshold)
    finally:
        finder.close()


__all__ = [
    "AsyncFileSearch",
    "CoordinationBackend",
    "QIHSECoordination",
    "RedisCoordination",
    "SQLiteCoordination",
    "SessionInfo",
    "discover_sessions",
    "assign_channels_to_sessions",
    "async_search_files",
    "TelegramPasswordFinder",
    "find_passwords_api",
]
