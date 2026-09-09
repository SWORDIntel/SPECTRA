"""Bounded cross-process serialization for native index stores.

Supports two lock modes:
  - exclusive (default): LOCK_EX — no other process can hold any lock
  - shared: LOCK_SH — multiple processes can hold shared locks simultaneously,
    but an exclusive lock waits for all shared locks to release

This enables simultaneous access: multiple projector workers can hold shared
locks during SQLite projection (which is already safe under WAL), while only
the QIHSE native sync phase takes an exclusive lock.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import time
from pathlib import Path


class NativeStoreLockTimeout(TimeoutError):
    """Raised when a native store remains busy past the lock deadline."""


class NativeStoreLock:
    """Hold an advisory lock for one native store path.

    By default takes an exclusive lock (LOCK_EX). Pass shared=True for a
    shared lock (LOCK_SH) that allows concurrent readers/projection workers.
    """

    def __init__(
        self,
        store_path: Path | str,
        *,
        timeout: float,
        poll_interval: float = 0.05,
        shared: bool = False,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.store_path = Path(store_path)
        self.lock_path = self.store_path.with_name(self.store_path.name + ".lock")
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self.shared = shared
        self._descriptor: int | None = None

    def __enter__(self) -> "NativeStoreLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise RuntimeError(f"cannot open native store lock {self.lock_path}: {exc}") from exc
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RuntimeError(f"native store lock is not a regular file: {self.lock_path}")
            lock_op = fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    fcntl.flock(descriptor, lock_op | fcntl.LOCK_NB)
                    self._descriptor = descriptor
                    return self
                except OSError as exc:
                    if exc.errno == errno.EINTR:
                        continue
                    if exc.errno not in (errno.EACCES, errno.EAGAIN):
                        raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    mode = "shared" if self.shared else "exclusive"
                    raise NativeStoreLockTimeout(
                        f"native store lock ({mode}) timed out after {self.timeout:g} seconds: "
                        f"{self.store_path}"
                    )
                time.sleep(min(self.poll_interval, remaining))
        except Exception:
            os.close(descriptor)
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
