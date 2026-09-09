"""Conversation Mechanics Feature Extraction for Persona Modeling.

Analyzes how a target behaves inside conversations: reply probability,
reply latency, message bursts, double/triple messages, conversation
initiation/termination, and response-length vs prompt-length correlation.

Standard library only (re, collections, math, statistics, datetime).
"""
from __future__ import annotations

import logging
import math
import re
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Burst gap: consecutive messages by same user within this many seconds
# are considered part of the same burst.
BURST_GAP_SECONDS = 300.0

# Double-message threshold: consecutive messages by same user within this
# many seconds count as a "double message" (rapid-fire).
DOUBLE_MESSAGE_SECONDS = 60.0

# Conversation idle threshold: if no messages for this many seconds,
# the conversation is considered ended.
CONVERSATION_IDLE_SECONDS = 1800.0

DEFAULT_CONVERSATION_FEATURES: Dict[str, Any] = {
    "reply_probability": 0.0,
    "reply_latency_median": 0.0,
    "reply_latency_distribution": {},
    "messages_per_burst": 0.0,
    "burst_duration": 0.0,
    "inter_message_interval_distribution": {},
    "conversation_initiation_rate": 0.0,
    "conversation_termination_rate": 0.0,
    "double_message_rate": 0.0,
    "triple_message_rate": 0.0,
    "followup_message_probability": 0.0,
    "quote_usage_rate": 0.0,
    "reply_to_message_rate": 0.0,
    "edit_rate": 0.0,
    "delete_rate": 0.0,
    "response_length_given_prompt_length": 0.0,
}


def _extract_text(msg: Any) -> str:
    if isinstance(msg, dict):
        text = msg.get("content")
        if text is None:
            text = msg.get("text")
        if text is None:
            return ""
        return str(text)
    if isinstance(msg, str):
        return msg
    return ""


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    """Parse an ISO string or unix timestamp into a UTC datetime."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    if isinstance(ts, str):
        s = ts.strip()
        if not s:
            return None
        # Try ISO format.
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
        # Try unix timestamp string.
        try:
            return datetime.fromtimestamp(float(s), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    return None


def _percentile(sorted_vals: Sequence[float], p: float) -> float:
    """Linear interpolation percentile."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def _correlation(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation coefficient."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0.0 or den_y == 0.0:
        return 0.0
    return max(-1.0, min(1.0, num / (den_x * den_y)))


_QUOTE_RE = re.compile(r"^>\s|(?<=\n)>\s", re.MULTILINE)
_REPLY_REF_RE = re.compile(r"›|❯|>>|On .+ wrote:")


def extract_conversation_features(
    messages: List[Dict[str, Any]],
    *,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract conversation mechanics features from a list of messages.

    Messages are dicts with 'content'/'text' and optional 'date',
    'user_id', 'reply_to_message_id', 'id', 'edited', 'deleted'.

    config: Optional per-target feature config (from feature_config.get_config).
    """
    if not messages:
        return dict(DEFAULT_CONVERSATION_FEATURES)

    cfg = config or {}
    burst_gap = cfg.get("conversation_burst_gap_seconds", BURST_GAP_SECONDS)
    double_msg_sec = cfg.get("conversation_double_message_seconds", DOUBLE_MESSAGE_SECONDS)
    idle_sec = cfg.get("conversation_idle_seconds", CONVERSATION_IDLE_SECONDS)

    # Parse timestamps and sort by time.
    parsed: List[tuple] = []  # (datetime, msg_dict, index)
    for i, msg in enumerate(messages):
        ts = _parse_timestamp(msg.get("date") or msg.get("observed_at"))
        if ts is not None:
            parsed.append((ts, msg, i))

    total = len(messages)
    has_timestamps = len(parsed) == total

    features: Dict[str, Any] = {}

    # ── Reply probability and latency ────────────────────────────────────
    reply_count = sum(1 for m in messages if m.get("reply_to_message_id") is not None)
    features["reply_probability"] = round(reply_count / total, 6) if total > 0 else 0.0
    features["reply_to_message_rate"] = features["reply_probability"]

    # Reply latency: time between the replied-to message and the reply.
    # Requires timestamps and reply_to_message_id.
    latencies: List[float] = []
    if has_timestamps and reply_count > 0:
        # Build index: message_id -> timestamp
        id_to_ts: Dict[Any, datetime] = {}
        for ts, msg, _ in parsed:
            mid = msg.get("id") or msg.get("message_id")
            if mid is not None:
                id_to_ts[mid] = ts
        for ts, msg, _ in parsed:
            reply_to = msg.get("reply_to_message_id")
            if reply_to is not None and reply_to in id_to_ts:
                delta = (ts - id_to_ts[reply_to]).total_seconds()
                if delta >= 0:
                    latencies.append(delta)

    if latencies:
        sorted_lat = sorted(latencies)
        features["reply_latency_median"] = round(statistics.median(sorted_lat), 2)
        features["reply_latency_distribution"] = {
            "median": round(statistics.median(sorted_lat), 2),
            "p25": round(_percentile(sorted_lat, 0.25), 2),
            "p75": round(_percentile(sorted_lat, 0.75), 2),
            "p90": round(_percentile(sorted_lat, 0.90), 2),
            "std": round(statistics.stdev(sorted_lat), 2) if len(sorted_lat) > 1 else 0.0,
        }
    else:
        features["reply_latency_median"] = 0.0
        features["reply_latency_distribution"] = {}

    # ── Burst detection ──────────────────────────────────────────────────
    # Burst = consecutive messages by same user with gaps < BURST_GAP_SECONDS.
    bursts: List[List[tuple]] = []  # each burst is a list of (ts, msg, idx)
    current_burst: List[tuple] = []
    last_ts: Optional[datetime] = None
    last_user: Any = None

    for item in sorted(parsed, key=lambda x: x[0]):
        ts, msg, idx = item
        user = msg.get("user_id")
        if last_ts is not None and last_user is not None:
            gap = (ts - last_ts).total_seconds()
            if gap < burst_gap and user == last_user:
                current_burst.append(item)
            else:
                if current_burst:
                    bursts.append(current_burst)
                current_burst = [item]
        else:
            current_burst = [item]
        last_ts = ts
        last_user = user
    if current_burst:
        bursts.append(current_burst)

    if bursts:
        burst_sizes = [len(b) for b in bursts]
        burst_durations = [
            (b[-1][0] - b[0][0]).total_seconds() for b in bursts if len(b) > 1
        ]
        features["messages_per_burst"] = round(
            sum(burst_sizes) / len(burst_sizes), 2
        )
        features["burst_duration"] = round(
            sum(burst_durations) / len(burst_durations), 2
        ) if burst_durations else 0.0
    else:
        features["messages_per_burst"] = 0.0
        features["burst_duration"] = 0.0

    # ── Inter-message interval distribution ──────────────────────────────
    intervals: List[float] = []
    if len(parsed) >= 2:
        sorted_parsed = sorted(parsed, key=lambda x: x[0])
        for i in range(1, len(sorted_parsed)):
            gap = (sorted_parsed[i][0] - sorted_parsed[i - 1][0]).total_seconds()
            if gap >= 0:
                intervals.append(gap)

    if intervals:
        sorted_int = sorted(intervals)
        features["inter_message_interval_distribution"] = {
            "median": round(statistics.median(sorted_int), 2),
            "p25": round(_percentile(sorted_int, 0.25), 2),
            "p75": round(_percentile(sorted_int, 0.75), 2),
            "std": round(statistics.stdev(sorted_int), 2) if len(sorted_int) > 1 else 0.0,
        }
    else:
        features["inter_message_interval_distribution"] = {}

    # ── Conversation initiation/termination ──────────────────────────────
    # A conversation starts after CONVERSATION_IDLE_SECONDS of inactivity.
    # Initiation rate = fraction of messages that start a new conversation.
    # Termination rate = fraction of messages that are the last in a conversation.
    if has_timestamps and len(parsed) >= 2:
        sorted_parsed = sorted(parsed, key=lambda x: x[0])
        conv_starts = 1  # first message always starts a conversation
        conv_ends = 0
        for i in range(1, len(sorted_parsed)):
            gap = (sorted_parsed[i][0] - sorted_parsed[i - 1][0]).total_seconds()
            if gap >= idle_sec:
                conv_starts += 1
                conv_ends += 1
        conv_ends += 1  # last message always ends a conversation
        features["conversation_initiation_rate"] = round(conv_starts / total, 6)
        features["conversation_termination_rate"] = round(conv_ends / total, 6)
    else:
        features["conversation_initiation_rate"] = 0.0
        features["conversation_termination_rate"] = 0.0

    # ── Double/triple message rate ───────────────────────────────────────
    # Consecutive messages by same user within DOUBLE_MESSAGE_SECONDS.
    double_count = 0
    triple_count = 0
    if has_timestamps and len(parsed) >= 2:
        sorted_parsed = sorted(parsed, key=lambda x: x[0])
        run = 1
        for i in range(1, len(sorted_parsed)):
            gap = (sorted_parsed[i][0] - sorted_parsed[i - 1][0]).total_seconds()
            same_user = (
                sorted_parsed[i][1].get("user_id")
                == sorted_parsed[i - 1][1].get("user_id")
            )
            if same_user and gap < double_msg_sec:
                run += 1
            else:
                if run >= 2:
                    double_count += 1
                if run >= 3:
                    triple_count += 1
                run = 1
        if run >= 2:
            double_count += 1
        if run >= 3:
            triple_count += 1

    features["double_message_rate"] = round(double_count / total, 6) if total > 0 else 0.0
    features["triple_message_rate"] = round(triple_count / total, 6) if total > 0 else 0.0

    # ── Followup probability ─────────────────────────────────────────────
    # Probability that a message is followed by another from the same user
    # within BURST_GAP_SECONDS.
    followup_count = 0
    if has_timestamps and len(parsed) >= 2:
        sorted_parsed = sorted(parsed, key=lambda x: x[0])
        for i in range(len(sorted_parsed) - 1):
            gap = (sorted_parsed[i + 1][0] - sorted_parsed[i][0]).total_seconds()
            same_user = (
                sorted_parsed[i + 1][1].get("user_id")
                == sorted_parsed[i][1].get("user_id")
            )
            if same_user and gap < burst_gap:
                followup_count += 1
    features["followup_message_probability"] = round(
        followup_count / total, 6
    ) if total > 0 else 0.0

    # ── Quote usage rate ─────────────────────────────────────────────────
    quote_count = sum(
        1 for m in messages
        if _QUOTE_RE.search(_extract_text(m)) or _REPLY_REF_RE.search(_extract_text(m))
    )
    features["quote_usage_rate"] = round(quote_count / total, 6) if total > 0 else 0.0

    # ── Edit/delete rate ─────────────────────────────────────────────────
    edit_count = sum(1 for m in messages if m.get("edited"))
    delete_count = sum(1 for m in messages if m.get("deleted"))
    features["edit_rate"] = round(edit_count / total, 6) if total > 0 else 0.0
    features["delete_rate"] = round(delete_count / total, 6) if total > 0 else 0.0

    # ── Response length vs prompt length correlation ─────────────────────
    # For reply pairs: correlate replied-to message length with reply length.
    prompt_lengths: List[float] = []
    response_lengths: List[float] = []
    if has_timestamps and reply_count > 0:
        id_to_len: Dict[Any, int] = {}
        for ts, msg, _ in parsed:
            mid = msg.get("id") or msg.get("message_id")
            if mid is not None:
                id_to_len[mid] = len(_extract_text(msg))
        for ts, msg, _ in parsed:
            reply_to = msg.get("reply_to_message_id")
            if reply_to is not None and reply_to in id_to_len:
                prompt_lengths.append(float(id_to_len[reply_to]))
                response_lengths.append(float(len(_extract_text(msg))))

    features["response_length_given_prompt_length"] = round(
        _correlation(prompt_lengths, response_lengths), 6
    )

    return features


__all__ = ["extract_conversation_features", "DEFAULT_CONVERSATION_FEATURES"]
