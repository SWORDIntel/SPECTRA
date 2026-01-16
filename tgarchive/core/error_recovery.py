"""
SPECTRA Production Error Recovery Module
=========================================
Comprehensive error handling, retry logic, and recovery mechanisms for production deployment.
Implements TEMPEST Class C considerations for secure error handling.

Features:
- Exponential backoff with jitter
- Per-message error collection
- Checkpoint-based recovery
- Rate limit handling
- Account failover
- Secure error logging (no credential leakage)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, TypeVar, Union
import json

from telethon import errors  # type: ignore

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ErrorSeverity(Enum):
    """Error severity levels for categorization."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories for recovery strategies."""
    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    AUTH = "authentication"
    PERMISSION = "permission"
    DATA = "data_integrity"
    SYSTEM = "system"
    UNKNOWN = "unknown"


@dataclass
class ErrorContext:
    """Secure error context without sensitive data leakage."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    category: ErrorCategory = ErrorCategory.UNKNOWN
    severity: ErrorSeverity = ErrorSeverity.ERROR
    message: str = ""
    entity_id: Optional[str] = None
    message_id: Optional[int] = None
    retry_count: int = 0
    recoverable: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for logging (sanitized)."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "entity_id": self._sanitize_entity_id(self.entity_id),
            "message_id": self.message_id,
            "retry_count": self.retry_count,
            "recoverable": self.recoverable,
        }

    @staticmethod
    def _sanitize_entity_id(entity_id: Optional[str]) -> Optional[str]:
        """Sanitize entity ID to prevent information leakage (TEMPEST consideration)."""
        if not entity_id:
            return None
        # Hash the entity ID for logging while preserving uniqueness
        return hashlib.sha256(entity_id.encode()).hexdigest()[:16]


@dataclass
class RecoveryCheckpoint:
    """Checkpoint for resuming interrupted operations."""
    entity_id: str
    last_message_id: int
    timestamp: datetime
    error_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        """Save checkpoint to disk."""
        checkpoint_data = {
            "entity_id": self.entity_id,
            "last_message_id": self.last_message_id,
            "timestamp": self.timestamp.isoformat(),
            "error_count": self.error_count,
            "metadata": self.metadata,
        }
        path.write_text(json.dumps(checkpoint_data, indent=2))
        logger.debug(f"Checkpoint saved: {self.last_message_id}")

    @classmethod
    def load(cls, path: Path) -> Optional[RecoveryCheckpoint]:
        """Load checkpoint from disk."""
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return cls(
                entity_id=data["entity_id"],
                last_message_id=data["last_message_id"],
                timestamp=datetime.fromisoformat(data["timestamp"]),
                error_count=data.get("error_count", 0),
                metadata=data.get("metadata", {}),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load checkpoint from {path}: {e}")
            return None


class RateLimitHandler:
    """
    Advanced rate limit handling with exponential backoff and jitter.
    Implements TEMPEST Class C timing analysis resistance.
    """

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 300.0,
        jitter_factor: float = 0.3,
        enable_jitter: bool = True,
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter_factor = jitter_factor
        self.enable_jitter = enable_jitter
        self.rate_limit_events: Dict[str, List[float]] = {}

    async def handle_flood_wait(self, error: errors.FloodWaitError, context: str = "") -> None:
        """
        Handle FloodWaitError with proper backoff and timing obfuscation.

        Args:
            error: The FloodWaitError from Telegram
            context: Context string for logging
        """
        wait_seconds = error.seconds

        # Add jitter to prevent timing analysis (TEMPEST Class C)
        if self.enable_jitter:
            jitter = random.uniform(-self.jitter_factor, self.jitter_factor) * wait_seconds
            wait_seconds = max(1.0, wait_seconds + jitter)

        wait_seconds = min(wait_seconds, self.max_delay)

        logger.warning(
            f"Rate limit hit for {context}. Waiting {wait_seconds:.1f}s "
            f"(requested: {error.seconds}s)"
        )

        # Record rate limit event for analysis
        self.rate_limit_events.setdefault(context, []).append(time.time())

        await asyncio.sleep(wait_seconds)

    async def exponential_backoff(
        self,
        attempt: int,
        context: str = "",
        max_attempts: int = 5,
    ) -> bool:
        """
        Perform exponential backoff with jitter.

        Returns:
            True if should retry, False if max attempts reached
        """
        if attempt >= max_attempts:
            logger.error(f"Max retry attempts ({max_attempts}) reached for {context}")
            return False

        # Calculate exponential backoff: base * 2^attempt
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)

        # Add jitter to prevent synchronized retries (TEMPEST timing obfuscation)
        if self.enable_jitter:
            jitter = random.uniform(-self.jitter_factor, self.jitter_factor) * delay
            delay = max(0.1, delay + jitter)

        logger.info(f"Retry {attempt + 1}/{max_attempts} for {context} after {delay:.2f}s")
        await asyncio.sleep(delay)
        return True

    def get_rate_limit_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get rate limit statistics for monitoring."""
        stats = {}
        current_time = time.time()

        for context, events in self.rate_limit_events.items():
            # Only consider events in last hour
            recent_events = [e for e in events if current_time - e < 3600]
            stats[context] = {
                "total_events": len(events),
                "recent_events_1h": len(recent_events),
                "last_event": datetime.fromtimestamp(events[-1]).isoformat() if events else None,
            }

        return stats


class ErrorCollector:
    """
    Collects errors during batch operations without stopping execution.
    Enables post-operation analysis and selective retry.
    """

    def __init__(self, max_errors_per_category: int = 100):
        self.errors: List[ErrorContext] = []
        self.max_errors_per_category = max_errors_per_category
        self.category_counts: Dict[ErrorCategory, int] = {}

    def add_error(
        self,
        exception: Exception,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        entity_id: Optional[str] = None,
        message_id: Optional[int] = None,
        retry_count: int = 0,
        recoverable: bool = True,
    ) -> None:
        """Add an error to the collection with secure sanitization."""

        # Sanitize exception message to prevent credential leakage
        error_msg = self._sanitize_error_message(str(exception))

        error_ctx = ErrorContext(
            category=category,
            severity=severity,
            message=error_msg,
            entity_id=entity_id,
            message_id=message_id,
            retry_count=retry_count,
            recoverable=recoverable,
        )

        # Check if we're collecting too many errors of this category
        self.category_counts[category] = self.category_counts.get(category, 0) + 1

        if self.category_counts[category] <= self.max_errors_per_category:
            self.errors.append(error_ctx)
        elif self.category_counts[category] == self.max_errors_per_category + 1:
            logger.warning(
                f"Error category {category.value} has exceeded limit "
                f"({self.max_errors_per_category}). Further errors will not be stored."
            )

    @staticmethod
    def _sanitize_error_message(message: str) -> str:
        """
        Sanitize error messages to prevent credential leakage (TEMPEST Class C).
        Removes potential passwords, tokens, and sensitive data patterns.
        """
        # Patterns to redact
        patterns = [
            (r'password["\']?\s*[:=]\s*["\']?[^"\'\s]+', 'password=<REDACTED>'),
            (r'token["\']?\s*[:=]\s*["\']?[^"\'\s]+', 'token=<REDACTED>'),
            (r'api[_-]?key["\']?\s*[:=]\s*["\']?[^"\'\s]+', 'api_key=<REDACTED>'),
            (r'api[_-]?hash["\']?\s*[:=]\s*["\']?[^"\'\s]+', 'api_hash=<REDACTED>'),
            (r'api[_-]?id["\']?\s*[:=]\s*["\']?\d+', 'api_id=<REDACTED>'),
            (r'session["\']?\s*[:=]\s*["\']?[^"\'\s]+', 'session=<REDACTED>'),
            (r'Authorization:\s*Bearer\s+\S+', 'Authorization: Bearer <REDACTED>'),
            (r'\d{10,}:\w{35}', '<BOT_TOKEN_REDACTED>'),  # Telegram bot tokens
        ]

        import re
        sanitized = message
        for pattern, replacement in patterns:
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

        return sanitized

    def get_errors_by_category(self, category: ErrorCategory) -> List[ErrorContext]:
        """Get all errors of a specific category."""
        return [e for e in self.errors if e.category == category]

    def get_recoverable_errors(self) -> List[ErrorContext]:
        """Get all recoverable errors for potential retry."""
        return [e for e in self.errors if e.recoverable]

    def get_summary(self) -> Dict[str, Any]:
        """Get error summary for reporting."""
        return {
            "total_errors": len(self.errors),
            "by_category": {
                cat.value: count for cat, count in self.category_counts.items()
            },
            "by_severity": {
                severity.value: len([e for e in self.errors if e.severity == severity])
                for severity in ErrorSeverity
            },
            "recoverable_count": len(self.get_recoverable_errors()),
        }

    def clear(self) -> None:
        """Clear all collected errors."""
        self.errors.clear()
        self.category_counts.clear()


class MessageProcessingRecovery:
    """
    Wrapper for message processing operations with comprehensive error recovery.
    Implements checkpoint-based resumption and per-message error handling.
    """

    def __init__(
        self,
        checkpoint_dir: Path,
        rate_limiter: Optional[RateLimitHandler] = None,
        error_collector: Optional[ErrorCollector] = None,
    ):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self.rate_limiter = rate_limiter or RateLimitHandler()
        self.error_collector = error_collector or ErrorCollector()

        self.processed_messages: Set[int] = set()
        self.failed_messages: Set[int] = set()

    async def process_with_recovery(
        self,
        func: Callable,
        *args,
        entity_id: str,
        message_id: Optional[int] = None,
        max_retries: int = 3,
        **kwargs,
    ) -> tuple[bool, Any]:
        """
        Execute a function with comprehensive error recovery.

        Returns:
            (success: bool, result: Any)
        """
        retry_count = 0
        last_exception = None

        while retry_count <= max_retries:
            try:
                result = await func(*args, **kwargs)

                # Success - clear from failed set if it was there
                if message_id:
                    self.failed_messages.discard(message_id)
                    self.processed_messages.add(message_id)

                return True, result

            except errors.FloodWaitError as e:
                # Handle rate limiting
                await self.rate_limiter.handle_flood_wait(e, context=entity_id)
                self.error_collector.add_error(
                    e,
                    category=ErrorCategory.RATE_LIMIT,
                    severity=ErrorSeverity.WARNING,
                    entity_id=entity_id,
                    message_id=message_id,
                    retry_count=retry_count,
                    recoverable=True,
                )
                retry_count += 1
                continue

            except (errors.ChannelPrivateError, errors.UserBannedInChannelError) as e:
                # Non-recoverable permission errors
                self.error_collector.add_error(
                    e,
                    category=ErrorCategory.PERMISSION,
                    severity=ErrorSeverity.ERROR,
                    entity_id=entity_id,
                    message_id=message_id,
                    retry_count=retry_count,
                    recoverable=False,
                )
                if message_id:
                    self.failed_messages.add(message_id)
                return False, None

            except errors.AuthKeyError as e:
                # Authentication error - critical
                self.error_collector.add_error(
                    e,
                    category=ErrorCategory.AUTH,
                    severity=ErrorSeverity.CRITICAL,
                    entity_id=entity_id,
                    message_id=message_id,
                    retry_count=retry_count,
                    recoverable=False,
                )
                if message_id:
                    self.failed_messages.add(message_id)
                return False, None

            except (ConnectionError, TimeoutError, asyncio.TimeoutError) as e:
                # Network errors - recoverable
                self.error_collector.add_error(
                    e,
                    category=ErrorCategory.NETWORK,
                    severity=ErrorSeverity.WARNING,
                    entity_id=entity_id,
                    message_id=message_id,
                    retry_count=retry_count,
                    recoverable=True,
                )

                if await self.rate_limiter.exponential_backoff(retry_count, context=entity_id):
                    retry_count += 1
                    continue
                else:
                    if message_id:
                        self.failed_messages.add(message_id)
                    return False, None

            except Exception as e:
                # Unknown errors
                last_exception = e
                self.error_collector.add_error(
                    e,
                    category=ErrorCategory.UNKNOWN,
                    severity=ErrorSeverity.ERROR,
                    entity_id=entity_id,
                    message_id=message_id,
                    retry_count=retry_count,
                    recoverable=True,
                )

                if await self.rate_limiter.exponential_backoff(retry_count, context=entity_id):
                    retry_count += 1
                    continue
                else:
                    if message_id:
                        self.failed_messages.add(message_id)
                    logger.error(
                        f"Failed after {max_retries} retries for message {message_id}: {e}"
                    )
                    return False, None

        # Max retries exceeded
        if message_id:
            self.failed_messages.add(message_id)
        return False, None

    def save_checkpoint(
        self,
        entity_id: str,
        last_message_id: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Save checkpoint for recovery."""
        checkpoint = RecoveryCheckpoint(
            entity_id=entity_id,
            last_message_id=last_message_id,
            timestamp=datetime.now(timezone.utc),
            error_count=len(self.error_collector.errors),
            metadata=metadata or {},
        )

        checkpoint_file = self.checkpoint_dir / f"checkpoint_{hashlib.sha384(entity_id.encode()).hexdigest()[:32]}.json"
        checkpoint.save(checkpoint_file)

    def load_checkpoint(self, entity_id: str) -> Optional[RecoveryCheckpoint]:
        """Load checkpoint for entity."""
        checkpoint_file = self.checkpoint_dir / f"checkpoint_{hashlib.sha384(entity_id.encode()).hexdigest()[:32]}.json"
        return RecoveryCheckpoint.load(checkpoint_file)

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics."""
        return {
            "processed_messages": len(self.processed_messages),
            "failed_messages": len(self.failed_messages),
            "error_summary": self.error_collector.get_summary(),
            "rate_limit_stats": self.rate_limiter.get_rate_limit_stats(),
        }


# Convenience decorator for automatic error recovery
def with_recovery(
    recovery_handler: MessageProcessingRecovery,
    entity_id: str,
    message_id: Optional[int] = None,
    max_retries: int = 3,
):
    """Decorator for automatic error recovery on async functions."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            return await recovery_handler.process_with_recovery(
                func,
                *args,
                entity_id=entity_id,
                message_id=message_id,
                max_retries=max_retries,
                **kwargs,
            )
        return wrapper
    return decorator


__all__ = [
    "ErrorSeverity",
    "ErrorCategory",
    "ErrorContext",
    "RecoveryCheckpoint",
    "RateLimitHandler",
    "ErrorCollector",
    "MessageProcessingRecovery",
    "with_recovery",
]
