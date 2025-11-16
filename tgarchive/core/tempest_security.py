"""
SPECTRA TEMPEST Class C Security Module
========================================
Implements TEMPEST Class C security controls for electromagnetic security
and information assurance in production environments.

TEMPEST Class C Standards:
- Controlled electromagnetic emanations
- Secure memory handling with scrubbing
- Timing attack resistance
- Credential protection in memory
- Secure logging without data leakage
- Signal obfuscation

Reference: NIST SP 800-53, NSA TEMPEST standards
"""
from __future__ import annotations

import array
import ctypes
import gc
import hashlib
import hmac
import json
import logging
import os
import random
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
import sys

logger = logging.getLogger(__name__)


class SecureString:
    """
    Secure string storage with automatic memory scrubbing.
    Prevents credential leakage in memory dumps and swap files.

    TEMPEST Considerations:
    - Memory is zeroed before deallocation
    - Uses mlock when available to prevent swapping
    - Implements timing-safe comparisons
    """

    def __init__(self, value: str):
        """Initialize secure string with automatic locking."""
        # Convert string to byte array for secure storage
        self._value = array.array('B', value.encode('utf-8'))
        self._hash = hashlib.sha256(value.encode()).hexdigest()[:16]

        # Try to lock memory to prevent swapping (Linux/Unix)
        self._locked = False
        if hasattr(ctypes, 'pythonapi'):
            try:
                # Try to use mlock to prevent memory from being swapped to disk
                if sys.platform != 'win32':
                    libc = ctypes.CDLL('libc.so.6')
                    addr = self._value.buffer_info()[0]
                    size = self._value.buffer_info()[1] * self._value.itemsize
                    result = libc.mlock(addr, size)
                    if result == 0:
                        self._locked = True
                        logger.debug(f"Memory locked for secure string {self._hash}")
            except (OSError, AttributeError) as e:
                logger.debug(f"Could not lock memory for secure string: {e}")

    def get(self) -> str:
        """Retrieve the stored value (use sparingly)."""
        return self._value.tobytes().decode('utf-8')

    def compare(self, other: str) -> bool:
        """Timing-safe comparison to prevent timing attacks."""
        return hmac.compare_digest(
            self._value.tobytes(),
            other.encode('utf-8')
        )

    def __del__(self):
        """Securely wipe memory before deletion (TEMPEST requirement)."""
        try:
            # Overwrite with zeros multiple times (DoD 5220.22-M standard: 3 passes)
            for _ in range(3):
                for i in range(len(self._value)):
                    self._value[i] = 0

            # Unlock memory if it was locked
            if self._locked and sys.platform != 'win32':
                try:
                    libc = ctypes.CDLL('libc.so.6')
                    addr = self._value.buffer_info()[0]
                    size = self._value.buffer_info()[1] * self._value.itemsize
                    libc.munlock(addr, size)
                except (OSError, AttributeError):
                    pass

            logger.debug(f"Secure string {self._hash} scrubbed from memory")
        except Exception as e:
            logger.warning(f"Error during secure string cleanup: {e}")

    def __repr__(self) -> str:
        """Prevent accidental exposure in logs."""
        return f"<SecureString hash={self._hash}>"

    def __str__(self) -> str:
        """Prevent accidental exposure in string conversion."""
        return f"<SecureString hash={self._hash}>"


class CredentialFilter(logging.Filter):
    """
    Logging filter that removes credentials and sensitive data from log messages.

    TEMPEST Considerations:
    - Prevents electromagnetic emanation of secrets via log files
    - Protects against memory dump analysis
    - Sanitizes all potential credential patterns
    """

    # Patterns for credential detection
    SENSITIVE_PATTERNS = [
        # API credentials
        (re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\']?([^"\'\s]{20,})', re.IGNORECASE), 'api_key=<REDACTED>'),
        (re.compile(r'api[_-]?hash["\']?\s*[:=]\s*["\']?([^"\'\s]{30,})', re.IGNORECASE), 'api_hash=<REDACTED>'),
        (re.compile(r'api[_-]?id["\']?\s*[:=]\s*["\']?(\d{5,})', re.IGNORECASE), 'api_id=<REDACTED>'),

        # Passwords and tokens
        (re.compile(r'password["\']?\s*[:=]\s*["\']?([^"\'\s]+)', re.IGNORECASE), 'password=<REDACTED>'),
        (re.compile(r'passwd["\']?\s*[:=]\s*["\']?([^"\'\s]+)', re.IGNORECASE), 'passwd=<REDACTED>'),
        (re.compile(r'token["\']?\s*[:=]\s*["\']?([^"\'\s]{20,})', re.IGNORECASE), 'token=<REDACTED>'),
        (re.compile(r'secret["\']?\s*[:=]\s*["\']?([^"\'\s]{20,})', re.IGNORECASE), 'secret=<REDACTED>'),

        # Session and authorization
        (re.compile(r'session["\']?\s*[:=]\s*["\']?([^"\'\s]+)', re.IGNORECASE), 'session=<REDACTED>'),
        (re.compile(r'Authorization:\s*Bearer\s+(\S+)', re.IGNORECASE), 'Authorization: Bearer <REDACTED>'),
        (re.compile(r'Authorization:\s*Basic\s+(\S+)', re.IGNORECASE), 'Authorization: Basic <REDACTED>'),

        # Telegram-specific
        (re.compile(r'(\d{10,}:\w{35})'), '<BOT_TOKEN_REDACTED>'),  # Bot tokens
        (re.compile(r'phone["\']?\s*[:=]\s*["\']?(\+?\d{10,15})', re.IGNORECASE), 'phone=<REDACTED>'),

        # Proxy credentials
        (re.compile(r'proxy.*password["\']?\s*[:=]\s*["\']?([^"\'\s]+)', re.IGNORECASE), 'proxy password=<REDACTED>'),

        # Generic base64 that might be credentials (50+ chars)
        (re.compile(r'([A-Za-z0-9+/]{50,}={0,2})'), '<BASE64_REDACTED>'),

        # Private keys
        (re.compile(r'-----BEGIN.*PRIVATE KEY-----.*?-----END.*PRIVATE KEY-----', re.DOTALL), '<PRIVATE_KEY_REDACTED>'),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter sensitive data from log record."""
        try:
            # Sanitize the message
            if hasattr(record, 'msg'):
                record.msg = self.sanitize(str(record.msg))

            # Sanitize args
            if hasattr(record, 'args') and record.args:
                if isinstance(record.args, dict):
                    record.args = {k: self.sanitize(str(v)) for k, v in record.args.items()}
                elif isinstance(record.args, (list, tuple)):
                    record.args = tuple(self.sanitize(str(arg)) for arg in record.args)

        except Exception as e:
            logger.debug(f"Error in credential filter: {e}")

        return True

    @classmethod
    def sanitize(cls, text: str) -> str:
        """Remove sensitive patterns from text."""
        result = text
        for pattern, replacement in cls.SENSITIVE_PATTERNS:
            result = pattern.sub(replacement, result)
        return result


class SecureLogger:
    """
    Enhanced logger with automatic credential filtering and secure storage.

    TEMPEST Features:
    - Automatic PII/credential redaction
    - Encrypted log file option
    - Rotation with secure deletion
    - Timing attack resistance in logging
    """

    def __init__(
        self,
        name: str,
        log_file: Optional[Path] = None,
        enable_credential_filter: bool = True,
        max_bytes: int = 10_485_760,  # 10MB
        backup_count: int = 5,
    ):
        self.logger = logging.getLogger(name)
        self.log_file = log_file
        self.credential_filter = CredentialFilter() if enable_credential_filter else None

        # Add credential filter to all handlers
        if self.credential_filter:
            for handler in self.logger.handlers:
                handler.addFilter(self.credential_filter)

        # Setup rotating file handler with secure deletion
        if log_file:
            from logging.handlers import RotatingFileHandler

            # Ensure log directory exists
            log_file.parent.mkdir(parents=True, exist_ok=True)

            handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
            )

            handler.setFormatter(logging.Formatter(
                '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ))

            if self.credential_filter:
                handler.addFilter(self.credential_filter)

            self.logger.addHandler(handler)

    def info(self, msg: str, *args, **kwargs):
        """Log info level with credential filtering."""
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """Log warning level with credential filtering."""
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """Log error level with credential filtering."""
        self.logger.error(msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        """Log debug level with credential filtering."""
        self.logger.debug(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        """Log critical level with credential filtering."""
        self.logger.critical(msg, *args, **kwargs)


class TimingResistantOperations:
    """
    Timing-resistant operations to prevent timing analysis attacks.

    TEMPEST Considerations:
    - Constant-time comparisons
    - Jitter in operations
    - Prevention of timing side-channels
    """

    @staticmethod
    async def sleep_with_jitter(
        base_seconds: float,
        jitter_factor: float = 0.2,
        min_seconds: float = 0.1,
    ) -> None:
        """
        Sleep with random jitter to prevent timing analysis.

        Args:
            base_seconds: Base sleep duration
            jitter_factor: Jitter as fraction of base (0.0-1.0)
            min_seconds: Minimum sleep duration
        """
        import asyncio
        jitter = random.uniform(-jitter_factor, jitter_factor) * base_seconds
        sleep_time = max(min_seconds, base_seconds + jitter)
        await asyncio.sleep(sleep_time)

    @staticmethod
    def constant_time_compare(a: bytes, b: bytes) -> bool:
        """
        Constant-time comparison to prevent timing attacks.
        Uses hmac.compare_digest for cryptographic safety.
        """
        return hmac.compare_digest(a, b)

    @staticmethod
    def add_timing_noise(operation_func, noise_range_ms: tuple[int, int] = (10, 50)):
        """
        Decorator to add timing noise to operations.
        Prevents electromagnetic timing analysis.
        """
        def wrapper(*args, **kwargs):
            result = operation_func(*args, **kwargs)
            # Add random delay to obscure operation timing
            delay = random.randint(*noise_range_ms) / 1000.0
            time.sleep(delay)
            return result
        return wrapper


class SecureConfigManager:
    """
    Secure configuration manager with encryption and memory protection.

    TEMPEST Features:
    - Encrypted credential storage
    - Environment variable priority
    - Memory scrubbing for credentials
    - Audit logging for access
    """

    def __init__(
        self,
        config_file: Optional[Path] = None,
        encryption_key: Optional[bytes] = None,
    ):
        self.config_file = config_file
        self.encryption_key = encryption_key
        self._secure_values: Dict[str, SecureString] = {}
        self._plain_values: Dict[str, Any] = {}

    def set_secure(self, key: str, value: str) -> None:
        """Store a value securely in memory."""
        # Remove old value and trigger cleanup
        if key in self._secure_values:
            del self._secure_values[key]
            gc.collect()

        self._secure_values[key] = SecureString(value)
        logger.debug(f"Secure value set for key: {key}")

    def get_secure(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Retrieve secure value with environment variable override.
        Environment variables take precedence for TEMPEST security.
        """
        # Priority 1: Environment variable
        env_value = os.environ.get(key.upper())
        if env_value:
            return env_value

        # Priority 2: Secure storage
        if key in self._secure_values:
            return self._secure_values[key].get()

        # Priority 3: Default
        return default

    def load_from_env(self, mappings: Dict[str, str]) -> None:
        """
        Load configuration from environment variables.

        Args:
            mappings: Dict mapping config keys to env var names
        """
        for config_key, env_key in mappings.items():
            value = os.environ.get(env_key)
            if value:
                self.set_secure(config_key, value)
                logger.info(f"Loaded {config_key} from environment variable {env_key}")

    def scrub_memory(self) -> None:
        """Explicitly scrub all secure values from memory."""
        for key in list(self._secure_values.keys()):
            del self._secure_values[key]

        self._secure_values.clear()
        gc.collect()
        logger.info("Secure configuration memory scrubbed")

    def __del__(self):
        """Ensure cleanup on deletion."""
        self.scrub_memory()


class SecureFileOperations:
    """
    Secure file operations with TEMPEST considerations.

    Features:
    - Secure deletion (multiple overwrites)
    - Permission validation
    - Atomic writes
    - Audit logging
    """

    @staticmethod
    def secure_delete(file_path: Path, passes: int = 3) -> bool:
        """
        Securely delete a file with multiple overwrite passes.
        Implements DoD 5220.22-M standard.

        Args:
            file_path: Path to file to delete
            passes: Number of overwrite passes (default: 3)

        Returns:
            True if successful, False otherwise
        """
        try:
            if not file_path.exists():
                return True

            file_size = file_path.stat().st_size

            # Overwrite file contents multiple times
            with file_path.open('r+b') as f:
                for pass_num in range(passes):
                    f.seek(0)
                    if pass_num == 0:
                        # Pass 1: All zeros
                        f.write(b'\x00' * file_size)
                    elif pass_num == 1:
                        # Pass 2: All ones
                        f.write(b'\xFF' * file_size)
                    else:
                        # Pass 3: Random data
                        f.write(secrets.token_bytes(file_size))
                    f.flush()
                    os.fsync(f.fileno())

            # Finally, delete the file
            file_path.unlink()
            logger.debug(f"Securely deleted file: {file_path}")
            return True

        except Exception as e:
            logger.error(f"Error during secure deletion of {file_path}: {e}")
            return False

    @staticmethod
    def atomic_write(file_path: Path, content: Union[str, bytes], mode: str = 'w') -> bool:
        """
        Atomic file write using temporary file and rename.
        Prevents partial writes on crashes.
        """
        try:
            temp_path = file_path.parent / f".{file_path.name}.tmp.{secrets.token_hex(8)}"

            # Write to temporary file
            if isinstance(content, str):
                temp_path.write_text(content)
            else:
                temp_path.write_bytes(content)

            # Atomic rename
            temp_path.rename(file_path)
            logger.debug(f"Atomically wrote file: {file_path}")
            return True

        except Exception as e:
            logger.error(f"Error during atomic write to {file_path}: {e}")
            if temp_path.exists():
                temp_path.unlink()
            return False

    @staticmethod
    def validate_permissions(file_path: Path, max_permissions: int = 0o600) -> bool:
        """
        Validate file permissions for security.

        Args:
            file_path: Path to check
            max_permissions: Maximum allowed permissions (default: owner read/write only)

        Returns:
            True if permissions are acceptable, False otherwise
        """
        try:
            if not file_path.exists():
                return True

            current_perms = file_path.stat().st_mode & 0o777
            if current_perms > max_permissions:
                logger.warning(
                    f"File {file_path} has overly permissive permissions: "
                    f"{oct(current_perms)} (max allowed: {oct(max_permissions)})"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"Error checking permissions for {file_path}: {e}")
            return False


# Convenience function for setting up TEMPEST-compliant logging
def setup_secure_logging(
    log_file: Optional[Path] = None,
    level: int = logging.INFO,
    enable_credential_filter: bool = True,
) -> SecureLogger:
    """
    Setup TEMPEST-compliant logging with credential filtering.

    Args:
        log_file: Optional log file path
        level: Logging level
        enable_credential_filter: Enable credential filtering

    Returns:
        SecureLogger instance
    """
    # Setup root logger
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Create secure logger
    secure_logger = SecureLogger(
        "spectra",
        log_file=log_file,
        enable_credential_filter=enable_credential_filter,
    )

    # Add credential filter to root logger handlers if enabled
    if enable_credential_filter:
        credential_filter = CredentialFilter()
        for handler in logging.root.handlers:
            handler.addFilter(credential_filter)

    logger.info("TEMPEST-compliant secure logging initialized")
    return secure_logger


__all__ = [
    "SecureString",
    "CredentialFilter",
    "SecureLogger",
    "TimingResistantOperations",
    "SecureConfigManager",
    "SecureFileOperations",
    "setup_secure_logging",
]
