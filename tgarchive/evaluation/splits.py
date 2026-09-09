"""Time-separated dataset split utilities for forensic and ML evaluation.

Critical principle: Never random-split messages for temporal models or
forensic attribution, as adjacent messages leak style, topic, and context.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Sequence, Tuple, Union

logger = logging.getLogger(__name__)


def _parse_utc_datetime(val: Any) -> datetime:
    """Convert various date representations (datetime, date, ISO string, timestamp) to UTC datetime.

    Args:
        val: Input datetime value (datetime, date, ISO formatted str, or numeric epoch timestamp).

    Returns:
        Timezone-aware datetime in UTC.

    Raises:
        ValueError: If val is None or cannot be parsed into a valid datetime.
    """
    if val is None:
        raise ValueError("Cannot parse None as datetime")

    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)

    if isinstance(val, date):
        # date object (not datetime)
        return datetime(val.year, val.month, val.day, tzinfo=timezone.utc)

    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=timezone.utc)

    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            raise ValueError("Empty date string")
        # Handle trailing Z or replace spaces
        iso_str = cleaned.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso_str)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            # Fallback for formats like "YYYY-MM-DD HH:MM:SS"
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(cleaned, fmt)
                    return parsed.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
            raise ValueError(f"Unrecognized datetime string format: {val!r}")

    raise ValueError(f"Unsupported datetime type: {type(val).__name__} ({val!r})")


def temporal_split(
    messages: Sequence[Dict[str, Any]],
    train_end: datetime | str,
    val_end: datetime | str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split messages temporally using explicit boundary timestamps.

    - Messages with ``date < train_end`` -> train
    - Messages with ``train_end <= date < val_end`` -> validation
    - Messages with ``date >= val_end`` -> test (holdout)

    Each message dictionary is expected to contain a ``'date'`` field
    (either a :class:`datetime.datetime` object or an ISO format string).

    Args:
        messages: Sequence of message dictionaries.
        train_end: Boundary timestamp ending the training partition (exclusive).
        val_end: Boundary timestamp ending the validation partition (exclusive).

    Returns:
        Tuple of ``(train_messages, val_messages, test_messages)`` lists.

    Raises:
        ValueError: If train_end is greater than val_end, or dates cannot be parsed.
    """
    train_end_dt = _parse_utc_datetime(train_end)
    val_end_dt = _parse_utc_datetime(val_end)

    if train_end_dt > val_end_dt:
        raise ValueError(
            f"train_end ({train_end_dt.isoformat()}) must be <= val_end ({val_end_dt.isoformat()})"
        )

    train: List[Dict[str, Any]] = []
    val: List[Dict[str, Any]] = []
    test: List[Dict[str, Any]] = []

    for msg in messages:
        if not isinstance(msg, dict):
            logger.warning("Skipping non-dict message item: %r", msg)
            continue

        raw_date = msg.get("date")
        if raw_date is None:
            logger.warning("Message missing 'date' field: %r", msg)
            continue

        try:
            msg_dt = _parse_utc_datetime(raw_date)
        except Exception as e:
            logger.warning("Could not parse message date %r: %s", raw_date, e)
            continue

        if msg_dt < train_end_dt:
            train.append(msg)
        elif train_end_dt <= msg_dt < val_end_dt:
            val.append(msg)
        else:
            test.append(msg)

    return train, val, test


def temporal_split_by_ratio(
    messages: Sequence[Dict[str, Any]],
    train_ratio: float = 0.6,
    val_ratio: float = 0.2,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split messages temporally by relative partition ratios.

    Sorts messages chronologically by their ``'date'`` field and slices
    them into train, validation, and test partitions according to the
    provided ratios.

    Args:
        messages: Sequence of message dictionaries containing a ``'date'`` field.
        train_ratio: Proportion of messages allocated to training (default: 0.6).
        val_ratio: Proportion of messages allocated to validation (default: 0.2).

    Returns:
        Tuple of ``(train_messages, val_messages, test_messages)`` lists.

    Raises:
        ValueError: If ratios are invalid (e.g. negative or sum > 1.0).
    """
    if train_ratio < 0.0 or val_ratio < 0.0:
        raise ValueError("train_ratio and val_ratio must be non-negative")
    if train_ratio + val_ratio > 1.0 + 1e-9:
        raise ValueError(
            f"train_ratio ({train_ratio}) + val_ratio ({val_ratio}) = {train_ratio + val_ratio:.4f} > 1.0"
        )

    if not messages:
        return [], [], []

    # Filter and decorate with parsed timestamp for stable chronological sorting
    valid_items: List[Tuple[datetime, int, Dict[str, Any]]] = []
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            logger.warning("Skipping non-dict message item: %r", msg)
            continue
        raw_date = msg.get("date")
        if raw_date is None:
            logger.warning("Message missing 'date' field: %r", msg)
            continue
        try:
            msg_dt = _parse_utc_datetime(raw_date)
            valid_items.append((msg_dt, idx, msg))
        except Exception as e:
            logger.warning("Could not parse message date %r: %s", raw_date, e)
            continue

    # Sort strictly by timestamp, preserving original order for ties
    valid_items.sort(key=lambda x: (x[0], x[1]))
    sorted_messages = [item[2] for item in valid_items]

    n = len(sorted_messages)
    train_count = int(n * train_ratio)
    val_count = int(n * val_ratio)

    train = sorted_messages[:train_count]
    val = sorted_messages[train_count : train_count + val_count]
    test = sorted_messages[train_count + val_count :]

    return train, val, test


__all__ = [
    "temporal_split",
    "temporal_split_by_ratio",
]
