"""
Bot-as-Human Detection Service — Behavioral fingerprinting to detect bots
==========================================================================

Detects automated accounts pretending to be human by analyzing:
  - Message timing regularity (bots post at machine-precise intervals)
  - Vocabulary diversity (bots have lower lexical diversity than humans)
  - Response time patterns (bots respond in <1s, humans take variable time)
  - Content repetition (bots reuse templates with minor variations)
  - Activity patterns (bots post 24/7 without sleep cycles)
  - Edit behavior (bots rarely edit, humans frequently do)
  - Emoji/punctuation patterns (bots use uniform emoji patterns)
  - Cross-channel coordination (same content posted across channels simultaneously)

Usage (library)::

    from tgarchive.services.bot_detection import detect_bot_behavior

    result = detect_bot_behavior(db_path="spectra.db", user_id=123)

Usage (CLI)::

    spectra-cli analyze bot-detection 123
    spectra-cli analyze bot-detection --scan-all
"""

from __future__ import annotations

import logging
import math
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from itertools import groupby
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore[assignment]
    NUMPY_AVAILABLE = False

from ..sqlite_runtime import connect_sqlite
from .utils import parse_dt as _parse_dt

logger = logging.getLogger(__name__)


def _to_timestamp_seconds(val: Any) -> float:
    """Convert datetime, timestamp, or numeric value to epoch seconds float."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, datetime):
        return float(val.timestamp())
    if hasattr(val, "timestamp"):
        try:
            return float(val.timestamp())
        except Exception:
            pass
    return 0.0


def _calculate_intervals(timestamps: Sequence[Any] | np.ndarray) -> np.ndarray | List[float]:
    """Calculate sorted time intervals (in seconds) between successive timestamps.

    Uses numpy vectorization when available, with pure Python fallback.
    """
    if len(timestamps) < 2:
        return np.empty(0, dtype=np.float64) if (NUMPY_AVAILABLE and np is not None) else []

    if NUMPY_AVAILABLE and np is not None:
        if isinstance(timestamps, np.ndarray) and np.issubdtype(timestamps.dtype, np.number):
            ts_arr = np.sort(timestamps.astype(np.float64))
        elif isinstance(timestamps, np.ndarray) and np.issubdtype(timestamps.dtype, np.datetime64):
            ts_arr = np.sort(timestamps.astype("datetime64[ns]").astype(np.float64) / 1e9)
        else:
            ts_arr = np.fromiter(
                (_to_timestamp_seconds(t) for t in timestamps),
                dtype=np.float64,
                count=len(timestamps),
            )
            ts_arr.sort()
        return np.diff(ts_arr)

    # Pure Python fallback
    sorted_ts = sorted(timestamps, key=lambda t: _to_timestamp_seconds(t))
    intervals: List[float] = []
    for i in range(1, len(sorted_ts)):
        t1 = sorted_ts[i - 1]
        t2 = sorted_ts[i]
        if isinstance(t1, datetime) and isinstance(t2, datetime):
            delta = (t2 - t1).total_seconds()
        else:
            delta = _to_timestamp_seconds(t2) - _to_timestamp_seconds(t1)
        intervals.append(delta)
    return intervals


def _calculate_autocorrelation(series: Sequence[float] | np.ndarray, max_lag: int = 10) -> List[float]:
    """Calculate normalized autocorrelation for lags 1 to min(max_lag, N-2).

    Uses numpy vectorization when available, with pure Python fallback.
    """
    if len(series) < 4:
        return []

    if NUMPY_AVAILABLE and np is not None:
        arr = np.asarray(series, dtype=np.float64)
        n = len(arr)
        max_lag = min(max_lag, n - 2)
        if max_lag < 1:
            return []
        mean_val = float(np.mean(arr))
        centered = arr - mean_val
        variance = float(np.var(arr, ddof=0))
        if variance == 0 or np.isnan(variance):
            return [0.0] * max_lag
        autocorr: List[float] = []
        for lag in range(1, max_lag + 1):
            c_k = float(np.dot(centered[:-lag], centered[lag:]) / (n * variance))
            autocorr.append(round(c_k, 4))
        return autocorr

    # Pure Python fallback
    n = len(series)
    max_lag = min(max_lag, n - 2)
    if max_lag < 1:
        return []
    mean_val = sum(series) / n
    centered_py = [x - mean_val for x in series]
    variance_py = sum(x ** 2 for x in centered_py) / n
    if variance_py == 0:
        return [0.0] * max_lag
    autocorr_py: List[float] = []
    for lag in range(1, max_lag + 1):
        c_k = sum(centered_py[i] * centered_py[i + lag] for i in range(n - lag)) / (n * variance_py)
        autocorr_py.append(round(c_k, 4))
    return autocorr_py


def _calculate_hour_histogram(timestamps: Sequence[datetime] | np.ndarray) -> Dict[int, int]:
    """Compute 24-hour distribution histogram from timestamps.

    Uses numpy vectorization (np.unique / np.bincount) when available.
    """
    if not timestamps:
        return {}

    if NUMPY_AVAILABLE and np is not None:
        if isinstance(timestamps, np.ndarray) and np.issubdtype(timestamps.dtype, np.integer):
            hours = timestamps
        elif isinstance(timestamps, np.ndarray) and np.issubdtype(timestamps.dtype, np.datetime64):
            hours = (timestamps.astype("datetime64[h]").astype(int) % 24).astype(np.int32)
        else:
            hours = np.fromiter((t.hour for t in timestamps if hasattr(t, "hour")), dtype=np.int32)
        if len(hours) == 0:
            return {}
        unique_h, counts = np.unique(hours, return_counts=True)
        return {int(h): int(c) for h, c in zip(unique_h, counts)}

    return dict(Counter(ts.hour for ts in timestamps if hasattr(ts, "hour")))


def _calculate_message_interval_regularity(timestamps: List[datetime] | Sequence[Any] | np.ndarray) -> Dict[str, Any]:
    """Analyze timing regularity between messages.

    Bots post at machine-precise intervals (low variance),
    humans have irregular timing (high variance).
    """
    if len(timestamps) < 3:
        return {"score": 0.0, "detail": "Insufficient messages for timing analysis"}

    if NUMPY_AVAILABLE and np is not None:
        if isinstance(timestamps, np.ndarray) and np.issubdtype(timestamps.dtype, np.number):
            ts_arr = np.sort(timestamps.astype(np.float64))
        elif isinstance(timestamps, np.ndarray) and np.issubdtype(timestamps.dtype, np.datetime64):
            ts_arr = np.sort(timestamps.astype("datetime64[ns]").astype(np.float64) / 1e9)
        else:
            ts_arr = np.fromiter(
                (_to_timestamp_seconds(t) for t in timestamps),
                dtype=np.float64,
                count=len(timestamps),
            )
            ts_arr.sort()

        intervals = np.diff(ts_arr)
        if len(intervals) == 0:
            return {"score": 0.0, "detail": "No intervals to analyze"}

        mean_interval = float(np.mean(intervals))
        if mean_interval == 0:
            return {"score": 0.0, "detail": "All messages at same timestamp"}

        std_dev = float(np.std(intervals, ddof=0))
        cv = std_dev / mean_interval
    else:
        sorted_ts = sorted(timestamps, key=lambda t: _to_timestamp_seconds(t))
        intervals_list: List[float] = []
        for i in range(1, len(sorted_ts)):
            t1 = sorted_ts[i - 1]
            t2 = sorted_ts[i]
            if isinstance(t1, datetime) and isinstance(t2, datetime):
                delta = (t2 - t1).total_seconds()
            else:
                delta = _to_timestamp_seconds(t2) - _to_timestamp_seconds(t1)
            intervals_list.append(delta)

        if not intervals_list:
            return {"score": 0.0, "detail": "No intervals to analyze"}

        mean_interval = sum(intervals_list) / len(intervals_list)
        if mean_interval == 0:
            return {"score": 0.0, "detail": "All messages at same timestamp"}

        variance = sum((x - mean_interval) ** 2 for x in intervals_list) / len(intervals_list)
        std_dev = math.sqrt(variance)
        cv = std_dev / mean_interval  # Coefficient of variation

    # Low CV = regular intervals = bot-like
    # High CV = irregular intervals = human-like
    # CV < 0.1 is extremely regular (bot)
    # CV > 0.5 is irregular (human)

    if cv < 0.05:
        score = 0.95  # Very bot-like
        detail = f"Extremely regular timing (CV={cv:.4f}) — machine-precise intervals"
    elif cv < 0.1:
        score = 0.8
        detail = f"Very regular timing (CV={cv:.4f}) — likely automated"
    elif cv < 0.3:
        score = 0.5
        detail = f"Moderately regular timing (CV={cv:.4f}) — possibly scheduled"
    elif cv < 0.5:
        score = 0.2
        detail = f"Irregular timing (CV={cv:.4f}) — human-like"
    else:
        score = 0.05
        detail = f"Highly irregular timing (CV={cv:.4f}) — very human-like"

    return {
        "score": round(score, 4),
        "cv": round(cv, 4),
        "mean_interval_seconds": round(mean_interval, 2),
        "std_dev_seconds": round(std_dev, 2),
        "detail": detail,
    }


def _calculate_vocabulary_diversity(messages: List[str]) -> Dict[str, Any]:
    """Analyze vocabulary diversity (type-token ratio).

    Bots tend to have lower lexical diversity (reuse same words),
    humans have richer vocabulary.
    """
    all_words = []
    for msg in messages:
        if not msg:
            continue
        words = msg.lower().split()
        all_words.extend(words)

    if not all_words:
        return {"score": 0.0, "detail": "No text to analyze"}

    total_tokens = len(all_words)
    unique_tokens = len(set(all_words))
    ttr = unique_tokens / total_tokens  # Type-Token Ratio

    # Low TTR = repetitive vocabulary = bot-like
    # High TTR = diverse vocabulary = human-like
    # TTR < 0.3 is very repetitive (bot)
    # TTR > 0.7 is diverse (human)

    if ttr < 0.2:
        score = 0.9
        detail = f"Very low vocabulary diversity (TTR={ttr:.4f}) — highly repetitive"
    elif ttr < 0.3:
        score = 0.7
        detail = f"Low vocabulary diversity (TTR={ttr:.4f}) — repetitive patterns"
    elif ttr < 0.5:
        score = 0.4
        detail = f"Moderate vocabulary diversity (TTR={ttr:.4f})"
    elif ttr < 0.7:
        score = 0.15
        detail = f"Good vocabulary diversity (TTR={ttr:.4f}) — human-like"
    else:
        score = 0.05
        detail = f"High vocabulary diversity (TTR={ttr:.4f}) — very human-like"

    return {
        "score": round(score, 4),
        "ttr": round(ttr, 4),
        "total_tokens": total_tokens,
        "unique_tokens": unique_tokens,
        "detail": detail,
    }


def _calculate_content_repetition(messages: List[str]) -> Dict[str, Any]:
    """Detect content repetition (template-based posting).

    Bots reuse message templates with minor variations.
    We detect this by computing pairwise similarity between messages.
    """
    if len(messages) < 5:
        return {"score": 0.0, "detail": "Insufficient messages for repetition analysis"}

    # Sample up to 50 messages for pairwise comparison
    sample = messages[:50]
    high_similarity_pairs = 0
    total_pairs = 0

    for i in range(len(sample)):
        for j in range(i + 1, len(sample)):
            if not sample[i] or not sample[j]:
                continue
            total_pairs += 1
            sim = SequenceMatcher(None, sample[i].lower(), sample[j].lower()).ratio()
            if sim > 0.8:
                high_similarity_pairs += 1

    if total_pairs == 0:
        return {"score": 0.0, "detail": "No comparable message pairs"}

    repetition_ratio = high_similarity_pairs / total_pairs

    if repetition_ratio > 0.3:
        score = 0.85
        detail = f"High content repetition ({repetition_ratio:.1%} of message pairs >80% similar) — template-based posting"
    elif repetition_ratio > 0.15:
        score = 0.6
        detail = f"Moderate content repetition ({repetition_ratio:.1%} of pairs >80% similar)"
    elif repetition_ratio > 0.05:
        score = 0.3
        detail = f"Low content repetition ({repetition_ratio:.1%} of pairs >80% similar)"
    else:
        score = 0.05
        detail = f"Minimal content repetition ({repetition_ratio:.1%} of pairs >80% similar) — human-like"

    return {
        "score": round(score, 4),
        "repetition_ratio": round(repetition_ratio, 4),
        "high_similarity_pairs": high_similarity_pairs,
        "total_pairs": total_pairs,
        "detail": detail,
    }


def _calculate_activity_patterns(timestamps: List[datetime] | Sequence[Any] | np.ndarray) -> Dict[str, Any]:
    """Analyze 24/7 activity patterns.

    Bots post at all hours without sleep cycles.
    Humans have clear activity gaps (sleep, work, etc.).
    """
    if len(timestamps) < 10:
        return {"score": 0.0, "detail": "Insufficient messages for activity pattern analysis"}

    if NUMPY_AVAILABLE and np is not None:
        if isinstance(timestamps, np.ndarray) and np.issubdtype(timestamps.dtype, np.integer):
            hours = timestamps
        elif isinstance(timestamps, np.ndarray) and np.issubdtype(timestamps.dtype, np.datetime64):
            hours = (timestamps.astype("datetime64[h]").astype(int) % 24).astype(np.int32)
        else:
            hours = np.fromiter((t.hour for t in timestamps if hasattr(t, "hour")), dtype=np.int32)

        counts_24 = np.bincount(hours, minlength=24)[:24]
        active_hours = int(np.count_nonzero(counts_24))

        # Check for sleep gap (3+ consecutive hours with no activity in 24h cycle)
        extended = np.concatenate([counts_24, counts_24[:5]])
        is_zero = (extended == 0)
        has_sleep_gap = bool(np.any(is_zero[:-2] & is_zero[1:-1] & is_zero[2:]))

        unique_h, counts = np.unique(hours, return_counts=True)
        hour_distribution = {int(h): int(c) for h, c in zip(unique_h, counts)}
    else:
        hour_counts = Counter(ts.hour for ts in timestamps if hasattr(ts, "hour"))
        active_hours = len([h for h in range(24) if hour_counts.get(h, 0) > 0])
        hour_distribution = dict(hour_counts)

        # Check for sleep gap (3+ consecutive hours with no activity)
        has_sleep_gap = False
        for start in range(24):
            gap = 0
            for offset in range(6):  # Check up to 6 hour window
                hour = (start + offset) % 24
                if hour_counts.get(hour, 0) == 0:
                    gap += 1
                else:
                    break
            if gap >= 3:
                has_sleep_gap = True
                break

    if active_hours >= 23 and not has_sleep_gap:
        score = 0.9
        detail = f"Active in {active_hours}/24 hours with no sleep gap — 24/7 activity pattern"
    elif active_hours >= 20 and not has_sleep_gap:
        score = 0.7
        detail = f"Active in {active_hours}/24 hours with no sleep gap — near-continuous activity"
    elif active_hours >= 15:
        score = 0.3
        detail = f"Active in {active_hours}/24 hours — some gaps present"
    else:
        score = 0.1
        detail = f"Active in {active_hours}/24 hours — clear activity gaps (human-like)"

    return {
        "score": round(score, 4),
        "active_hours": active_hours,
        "has_sleep_gap": has_sleep_gap,
        "hour_distribution": hour_distribution,
        "detail": detail,
    }


def _calculate_response_time(
    timestamps: List[datetime], reply_to_ids: List, all_msg_times: Dict[int, datetime]
) -> Dict[str, Any]:
    """Analyze response times to other messages.

    Bots respond in <1 second (instant API response).
    Humans take variable time (seconds to hours).
    """
    response_times: List[float] = []
    for i, reply_to in enumerate(reply_to_ids):
        if reply_to is None or reply_to not in all_msg_times:
            continue
        if i >= len(timestamps):
            continue
        parent_time = all_msg_times[reply_to]
        reply_time = timestamps[i]
        if reply_time and parent_time:
            delta = (reply_time - parent_time).total_seconds()
            if 0 < delta < 86400:  # Within 24 hours
                response_times.append(delta)

    if len(response_times) < 3:
        return {"score": 0.0, "detail": "Insufficient reply data for response time analysis"}

    if NUMPY_AVAILABLE and np is not None:
        rt_arr = np.array(response_times, dtype=np.float64)
        fast_responses = int(np.sum(rt_arr < 1.0))
        fast_ratio = fast_responses / len(rt_arr)
        sorted_rt = np.sort(rt_arr)
        median_response_time = float(sorted_rt[len(sorted_rt) // 2])
    else:
        fast_responses = sum(1 for r in response_times if r < 1.0)
        fast_ratio = fast_responses / len(response_times)
        median_response_time = sorted(response_times)[len(response_times) // 2]

    if fast_ratio > 0.5:
        score = 0.85
        detail = f"{fast_ratio:.1%} of replies sent in <1 second — instant API response pattern"
    elif fast_ratio > 0.2:
        score = 0.5
        detail = f"{fast_ratio:.1%} of replies sent in <1 second — some instant responses"
    else:
        score = 0.1
        detail = f"Only {fast_ratio:.1%} of replies in <1 second — human-like response times"

    return {
        "score": round(score, 4),
        "fast_response_ratio": round(fast_ratio, 4),
        "median_response_time": round(median_response_time, 2),
        "detail": detail,
    }


def _calculate_edit_behavior(messages: List[Any], edit_dates: List) -> Dict[str, Any]:
    """Analyze edit behavior.

    Bots rarely edit messages (they post pre-computed content).
    Humans frequently edit (typos, afterthoughts, corrections).
    """
    total = len(messages)
    if total == 0:
        return {"score": 0.0, "detail": "No messages to analyze"}

    edited = sum(1 for e in edit_dates if e is not None)
    edit_ratio = edited / total

    if edit_ratio == 0 and total > 20:
        score = 0.6
        detail = f"0 edits across {total} messages — bots rarely edit, humans do"
    elif edit_ratio < 0.02:
        score = 0.4
        detail = f"Very low edit rate ({edit_ratio:.2%}) — possibly automated"
    elif edit_ratio < 0.1:
        score = 0.15
        detail = f"Low edit rate ({edit_ratio:.2%})"
    else:
        score = 0.05
        detail = f"Normal edit rate ({edit_ratio:.2%}) — human-like"

    return {
        "score": round(score, 4),
        "edit_ratio": round(edit_ratio, 4),
        "edited_count": edited,
        "total_messages": total,
        "detail": detail,
    }


def detect_bot_behavior(
    db_path: Path | str,
    *,
    user_id: Optional[int] = None,
    scan_all: bool = False,
) -> Dict[str, Any]:
    """Detect bot-like behavior in user accounts.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        user_id: Specific user to analyze.
        scan_all: If True, analyze all users.

    Returns:
        Dict with: results, summary
    """
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    if not scan_all and user_id is None:
        return {"error": "Must specify user_id or scan_all", "results": [], "summary": {}}

    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Batch user activity with SQL window functions
        try:
            if scan_all:
                query = """
                WITH user_activity AS (
                    SELECT
                        m.id,
                        m.user_id,
                        m.content,
                        m.date,
                        m.edit_date,
                        m.reply_to,
                        p.date AS parent_date,
                        COUNT(*) OVER (PARTITION BY m.user_id) AS user_msg_count,
                        LAG(m.date) OVER (PARTITION BY m.user_id ORDER BY m.date) AS prev_date
                    FROM messages m
                    LEFT JOIN messages p ON m.reply_to = p.id
                    WHERE m.user_id IS NOT NULL
                )
                SELECT id, user_id, content, date, edit_date, reply_to, parent_date, user_msg_count, prev_date
                FROM user_activity
                WHERE user_msg_count >= 5
                ORDER BY user_id, date
                """
                rows = conn.execute(query).fetchall()
            else:
                query = """
                WITH user_activity AS (
                    SELECT
                        m.id,
                        m.user_id,
                        m.content,
                        m.date,
                        m.edit_date,
                        m.reply_to,
                        p.date AS parent_date,
                        COUNT(*) OVER () AS user_msg_count,
                        LAG(m.date) OVER (ORDER BY m.date) AS prev_date
                    FROM messages m
                    LEFT JOIN messages p ON m.reply_to = p.id
                    WHERE m.user_id = ?
                )
                SELECT id, user_id, content, date, edit_date, reply_to, parent_date, user_msg_count, prev_date
                FROM user_activity
                ORDER BY date
                """
                rows = conn.execute(query, (user_id,)).fetchall()
        except sqlite3.OperationalError:
            # Fallback if messages table not found or window functions error
            try:
                # Check if messages table exists
                conn.execute("SELECT 1 FROM messages LIMIT 1")
            except sqlite3.OperationalError:
                return {"error": "messages table not found", "results": [], "summary": {}}

            # Fallback for plain queries without CTE / window functions
            if scan_all:
                users = conn.execute(
                    "SELECT DISTINCT user_id FROM messages WHERE user_id IS NOT NULL ORDER BY user_id"
                ).fetchall()
                user_ids = [u["user_id"] for u in users]
                rows = []
                for uid in user_ids:
                    user_rows = conn.execute(
                        "SELECT id, user_id, content, date, edit_date, reply_to, NULL as parent_date, 0 as user_msg_count, NULL as prev_date FROM messages WHERE user_id = ? ORDER BY date",
                        (uid,),
                    ).fetchall()
                    if len(user_rows) >= 5:
                        rows.extend(user_rows)
            else:
                rows = conn.execute(
                    "SELECT id, user_id, content, date, edit_date, reply_to, NULL as parent_date, 0 as user_msg_count, NULL as prev_date FROM messages WHERE user_id = ? ORDER BY date",
                    (user_id,),
                ).fetchall()

        results: List[Dict[str, Any]] = []

        # Group messages by user_id
        for uid, user_msgs_iter in groupby(rows, key=lambda r: r["user_id"]):
            msgs = list(user_msgs_iter)
            if len(msgs) < 5:
                continue  # Skip users with too few messages

            timestamps: List[datetime] = []
            contents: List[str] = []
            edit_dates: List[Any] = []
            reply_to_ids: List[Any] = []
            all_msg_times: Dict[int, datetime] = {}

            for m in msgs:
                dt = _parse_dt(m["date"])
                if dt:
                    timestamps.append(dt)
                    all_msg_times[m["id"]] = dt
                contents.append(m["content"] or "")
                edit_dates.append(m["edit_date"])
                reply_to_ids.append(m["reply_to"])

                # Include parent message timestamp if available from join
                if m["reply_to"] is not None and m["parent_date"] and m["reply_to"] not in all_msg_times:
                    pdt = _parse_dt(m["parent_date"])
                    if pdt:
                        all_msg_times[m["reply_to"]] = pdt

            # Run all behavioral checks
            timing = _calculate_message_interval_regularity(timestamps)
            vocab = _calculate_vocabulary_diversity(contents)
            repetition = _calculate_content_repetition(contents)
            activity = _calculate_activity_patterns(timestamps)
            response_time = _calculate_response_time(timestamps, reply_to_ids, all_msg_times)
            edit_behavior = _calculate_edit_behavior(msgs, edit_dates)

            # Weighted confidence score
            weights = {
                "timing": 0.25,
                "vocabulary": 0.15,
                "repetition": 0.2,
                "activity": 0.2,
                "response_time": 0.1,
                "edit_behavior": 0.1,
            }

            checks = {
                "timing_regularity": timing,
                "vocabulary_diversity": vocab,
                "content_repetition": repetition,
                "activity_pattern": activity,
                "response_time": response_time,
                "edit_behavior": edit_behavior,
            }

            confidence = sum(
                checks[k]["score"] * w
                for k, w in zip(
                    ["timing_regularity", "vocabulary_diversity", "content_repetition",
                     "activity_pattern", "response_time", "edit_behavior"],
                    [weights["timing"], weights["vocabulary"], weights["repetition"],
                     weights["activity"], weights["response_time"], weights["edit_behavior"]],
                )
            )

            verdict = "human"
            if confidence >= 0.75:
                verdict = "bot_likely"
            elif confidence >= 0.5:
                verdict = "bot_possible"
            elif confidence >= 0.3:
                verdict = "ambiguous"

            results.append({
                "user_id": uid,
                "message_count": len(msgs),
                "bot_confidence": round(confidence, 4),
                "verdict": verdict,
                "checks": checks,
            })

        # Sort by bot confidence (highest first)
        results.sort(key=lambda x: x["bot_confidence"], reverse=True)

        summary = {
            "users_analyzed": len(results),
            "bots_likely": sum(1 for r in results if r["verdict"] == "bot_likely"),
            "bots_possible": sum(1 for r in results if r["verdict"] == "bot_possible"),
            "ambiguous": sum(1 for r in results if r["verdict"] == "ambiguous"),
            "human": sum(1 for r in results if r["verdict"] == "human"),
        }

    return {
        "results": results,
        "summary": summary,
    }


__all__ = [
    "detect_bot_behavior",
    "NUMPY_AVAILABLE",
]
