"""
Temporal Feature Extraction and Comparison for Actor Attribution
================================================================
Analyzes circadian activity distribution, weekday vs. weekend ratios,
response latencies, burst characteristics, inactivity intervals,
temporal drift, and feature half-life.

V2 additions: hour_of_day_distribution, day_of_week_distribution,
message_length_by_hour, activity_session_length, session_start/end
distributions, response_latency_by_hour, persona_drift_30d/90d/365d,
and feature_half_life.

Standard library only (datetime, statistics, math, collections, logging).
"""
from __future__ import annotations

import logging
import math
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Session gap: activity gaps longer than this end a session (seconds).
SESSION_GAP_SECONDS = 1800.0

# Default flat temporal feature dictionary with zero values
DEFAULT_TEMPORAL_FEATURES: Dict[str, float] = {
    **{f"hour_{h}": 0.0 for h in range(24)},
    "weekday_ratio": 0.0,
    "weekend_ratio": 0.0,
    "response_latency_median": 0.0,
    "response_latency_iqr": 0.0,
    "burst_frequency": 0.0,
    "burst_intensity": 0.0,
    "longest_inactivity_hours": 0.0,
    "typical_gap_hours": 0.0,
    "timezone_inference_confidence": 0.0,
}

# V2 distribution features (added alongside flat features)
DEFAULT_V2_TEMPORAL_FEATURES: Dict[str, Any] = {
    "hour_of_day_distribution": {},
    "day_of_week_distribution": {},
    "message_length_by_hour": {},
    "activity_session_length": 0.0,
    "session_start_distribution": {},
    "session_end_distribution": {},
    "response_latency_by_hour": {},
    "persona_drift_30d": 0.0,
    "persona_drift_90d": 0.0,
    "persona_drift_365d": 0.0,
    "feature_half_life": 0.0,
}


def _parse_datetime(val: Any) -> Optional[datetime]:
    """Parse various timestamp representations into a naive UTC datetime object."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is not None:
            return val.astimezone(timezone.utc).replace(tzinfo=None)
        return val
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            return None
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            return None
        # Handle ISO-8601 strings
        try:
            iso_str = cleaned.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            pass
        # Common fallback formats
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%d.%m.%Y %H:%M:%S",
        ):
            try:
                return datetime.strptime(cleaned, fmt)
            except Exception:
                pass
    return None


def _metric_similarity(v1: float, v2: float, min_scale: float = 1.0) -> float:
    """Calculate normalized similarity between two non-negative scalar values."""
    diff = abs(v1 - v2)
    denom = max(abs(v1), abs(v2), min_scale)
    return max(0.0, 1.0 - diff / denom)


def _js_divergence(p: Dict[str, float], q: Dict[str, float]) -> float:
    """Jensen-Shannon divergence between two word-frequency distributions."""
    vocab = set(p.keys()) | set(q.keys())
    if not vocab:
        return 0.0
    # Normalize to probability distributions.
    p_sum = sum(p.values()) or 1.0
    q_sum = sum(q.values()) or 1.0
    total = 0.0
    for w in vocab:
        pw = p.get(w, 0.0) / p_sum
        qw = q.get(w, 0.0) / q_sum
        mw = (pw + qw) / 2.0
        if mw > 0:
            if pw > 0:
                total += pw * math.log2(pw / mw)
            if qw > 0:
                total += qw * math.log2(qw / mw)
    return max(0.0, min(1.0, total / 2.0))


def _compute_drift(
    sorted_entries: List[Tuple[Dict[str, Any], datetime]],
    word_re: re.Pattern,
    days: int,
) -> float:
    """Compute persona drift as JS divergence of vocab between recent and older messages."""
    if len(sorted_entries) < 4:
        return 0.0
    latest_dt = sorted_entries[-1][1]
    cutoff = latest_dt - timedelta(days=days)
    recent_words: List[str] = []
    older_words: List[str] = []
    for msg, dt in sorted_entries:
        text = msg.get("content") or msg.get("text") or ""
        tokens = [t.lower() for t in word_re.findall(str(text))]
        if dt > cutoff:
            recent_words.extend(tokens)
        else:
            older_words.extend(tokens)
    if not recent_words or not older_words:
        return 0.0
    recent_freq = Counter(recent_words)
    older_freq = Counter(older_words)
    p = {w: c / len(recent_words) for w, c in recent_freq.items()}
    q = {w: c / len(older_words) for w, c in older_freq.items()}
    return round(_js_divergence(p, q), 6)


def _estimate_half_life(
    sorted_entries: List[Tuple[Dict[str, Any], datetime]],
    word_re: re.Pattern,
) -> float:
    """Estimate vocabulary half-life in days.

    Tracks how word usage decays over time. For each word that appears
    in the first half of the timeline, measures what fraction of its
    total occurrences are in the second half. A low fraction means
    fast turnover (short half-life).
    """
    if len(sorted_entries) < 4:
        return 0.0
    mid = len(sorted_entries) // 2
    early = sorted_entries[:mid]
    late = sorted_entries[mid:]
    early_words = Counter()
    late_words = Counter()
    for msg, _ in early:
        text = msg.get("content") or msg.get("text") or ""
        early_words.update(t.lower() for t in word_re.findall(str(text)))
    for msg, _ in late:
        text = msg.get("content") or msg.get("text") or ""
        late_words.update(t.lower() for t in word_re.findall(str(text)))
    # For words that appear in early, compute retention rate.
    retention_rates: List[float] = []
    for word, early_count in early_words.items():
        late_count = late_words.get(word, 0)
        total = early_count + late_count
        if total >= 2:  # only words with enough data
            retention = late_count / total
            retention_rates.append(retention)
    if not retention_rates:
        return 0.0
    avg_retention = sum(retention_rates) / len(retention_rates)
    if avg_retention <= 0.001:
        return 1.0  # very fast turnover
    if avg_retention >= 0.99:
        return 0.0  # no turnover
    # Half-life estimate: time for retention to drop to 50%.
    # If the two halves span T days, and retention is R,
    # half-life ≈ T * ln(0.5) / ln(R)
    span_days = (sorted_entries[-1][1] - sorted_entries[0][1]).total_seconds() / 86400.0
    if span_days <= 0:
        return 0.0
    try:
        half_life = span_days * math.log(0.5) / math.log(avg_retention)
        return round(max(0.0, half_life), 2)
    except (ValueError, ZeroDivisionError):
        return 0.0


def extract_temporal_features(messages: List[Dict[str, Any]]) -> Dict[str, float]:
    """Extract circadian, burst, latency, inactivity, drift, and half-life features.

    Args:
        messages: List of message dicts, each with a 'date' field (datetime or ISO string).

    Returns:
        Flat dictionary of temporal feature name -> float value.
        V2 distribution features are included as dict values.
    """
    if not messages:
        return dict(DEFAULT_TEMPORAL_FEATURES)

    # Collect valid (msg, datetime) entries
    valid_entries: List[Tuple[Dict[str, Any], datetime]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        dt = _parse_datetime(msg.get("date"))
        if dt is not None:
            valid_entries.append((msg, dt))

    if not valid_entries:
        return dict(DEFAULT_TEMPORAL_FEATURES)

    # Sort messages chronologically
    sorted_entries = sorted(valid_entries, key=lambda x: x[1])
    sorted_dates = [dt for _, dt in sorted_entries]
    total_messages = len(sorted_dates)

    features: Dict[str, float] = dict(DEFAULT_TEMPORAL_FEATURES)

    # ── 1. 24-Hour Circadian Histogram (hour_0 through hour_23) ────────────
    hour_counts = Counter(d.hour for d in sorted_dates)
    for h in range(24):
        features[f"hour_{h}"] = hour_counts[h] / total_messages

    # ── 2. Weekday vs Weekend Activity Ratios ────────────────────────────────
    weekday_count = sum(1 for d in sorted_dates if d.weekday() < 5)  # 0=Mon ... 4=Fri
    weekend_count = total_messages - weekday_count
    features["weekday_ratio"] = weekday_count / total_messages
    features["weekend_ratio"] = weekend_count / total_messages

    # ── 3. Response Latency Distribution (Median & IQR) ──────────────────────
    id_to_date: Dict[Any, datetime] = {}
    for msg, dt in sorted_entries:
        mid = msg.get("id") if msg.get("id") is not None else msg.get("message_id")
        if mid is not None:
            id_to_date[mid] = dt

    latencies: List[float] = []
    for msg, dt in sorted_entries:
        # Check direct reply_latency attribute first
        if "reply_latency" in msg and msg["reply_latency"] is not None:
            try:
                lat = float(msg["reply_latency"])
                if lat >= 0.0:
                    latencies.append(lat)
            except (ValueError, TypeError):
                pass
        else:
            reply_id = msg.get("reply_to") if msg.get("reply_to") is not None else msg.get("reply_to_msg_id")
            if reply_id is not None and reply_id in id_to_date:
                parent_dt = id_to_date[reply_id]
                diff_sec = (dt - parent_dt).total_seconds()
                if diff_sec >= 0.0:
                    latencies.append(diff_sec)

    if latencies:
        features["response_latency_median"] = float(statistics.median(latencies))
        if len(latencies) >= 4:
            q = statistics.quantiles(latencies, n=4)
            features["response_latency_iqr"] = float(max(0.0, q[2] - q[0]))
        elif len(latencies) >= 2:
            sl = sorted(latencies)
            mid = len(sl) // 2
            q1 = statistics.median(sl[:mid])
            q3 = statistics.median(sl[mid if len(sl) % 2 == 0 else mid + 1:])
            features["response_latency_iqr"] = float(max(0.0, q3 - q1))
        else:
            features["response_latency_iqr"] = 0.0
    else:
        features["response_latency_median"] = 0.0
        features["response_latency_iqr"] = 0.0

    # ── 4. Burst Detection (Frequency & Intensity) ──────────────────────────
    active_days = len(set(d.date() for d in sorted_dates))
    burst_threshold = 5 if total_messages >= 10 else 3
    burst_window_sec = 3600  # 1-hour window

    bursts: List[int] = []
    i = 0
    while i < total_messages:
        window_start = sorted_dates[i]
        window_end = window_start + timedelta(seconds=burst_window_sec)
        j = i
        while j < total_messages and sorted_dates[j] <= window_end:
            j += 1
        count = j - i
        if count >= burst_threshold:
            bursts.append(count)
            i = j  # Move past this burst
        else:
            i += 1

    if bursts and active_days > 0:
        features["burst_frequency"] = len(bursts) / active_days
        features["burst_intensity"] = sum(bursts) / len(bursts)
    else:
        features["burst_frequency"] = 0.0
        features["burst_intensity"] = 0.0

    # ── 5. Inactivity Windows (Gaps) ─────────────────────────────────────────
    if total_messages >= 2:
        gaps_hours = [
            (sorted_dates[i + 1] - sorted_dates[i]).total_seconds() / 3600.0
            for i in range(total_messages - 1)
        ]
        valid_gaps = [g for g in gaps_hours if g >= 0.0]
        if valid_gaps:
            features["longest_inactivity_hours"] = max(valid_gaps)
            features["typical_gap_hours"] = float(statistics.median(valid_gaps))
        else:
            features["longest_inactivity_hours"] = 0.0
            features["typical_gap_hours"] = 0.0
    else:
        features["longest_inactivity_hours"] = 0.0
        features["typical_gap_hours"] = 0.0

    # ── 6. Timezone Inference Confidence ─────────────────────────────────────
    # Based on Shannon entropy of the 24-hour histogram (peaked = high confidence)
    entropy = 0.0
    for h in range(24):
        p = hour_counts[h] / total_messages
        if p > 0.0:
            entropy -= p * math.log2(p)

    max_entropy = math.log2(24)  # ~4.58496
    peakedness = 1.0 - (entropy / max_entropy)
    sample_factor = min(1.0, total_messages / 10.0)
    features["timezone_inference_confidence"] = max(0.0, min(1.0, peakedness * sample_factor))

    # ── V2: Distribution features ───────────────────────────────────────────
    _DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

    # Hour of day distribution (dict form)
    hour_dist = {str(h): round(hour_counts[h] / total_messages, 6)
                 for h in range(24) if hour_counts[h] > 0}
    features["hour_of_day_distribution"] = hour_dist

    # Day of week distribution
    dow_counts = Counter(d.weekday() for d in sorted_dates)
    dow_dist = {_DAY_NAMES[d]: round(dow_counts[d] / total_messages, 6)
                for d in range(7) if dow_counts[d] > 0}
    features["day_of_week_distribution"] = dow_dist

    # Message length by hour
    len_by_hour: Dict[str, float] = {}
    hour_lens: Dict[int, List[int]] = {}
    for msg, dt in sorted_entries:
        text = msg.get("content") or msg.get("text") or ""
        h = dt.hour
        hour_lens.setdefault(h, []).append(len(str(text)))
    for h in range(24):
        if h in hour_lens and hour_lens[h]:
            len_by_hour[str(h)] = round(
                sum(hour_lens[h]) / len(hour_lens[h]), 2
            )
    features["message_length_by_hour"] = len_by_hour

    # Activity session length (session = gaps < SESSION_GAP_SECONDS)
    sessions: List[List[datetime]] = []
    current_session: List[datetime] = [sorted_dates[0]]
    for i in range(1, len(sorted_dates)):
        gap = (sorted_dates[i] - sorted_dates[i - 1]).total_seconds()
        if gap < SESSION_GAP_SECONDS:
            current_session.append(sorted_dates[i])
        else:
            sessions.append(current_session)
            current_session = [sorted_dates[i]]
    sessions.append(current_session)

    session_durations = [
        (s[-1] - s[0]).total_seconds() / 60.0
        for s in sessions if len(s) > 1
    ]
    features["activity_session_length"] = round(
        sum(session_durations) / len(session_durations), 2
    ) if session_durations else 0.0

    # Session start/end distributions (hour histograms)
    start_hours = Counter(s[0].hour for s in sessions)
    end_hours = Counter(s[-1].hour for s in sessions)
    features["session_start_distribution"] = {
        str(h): round(start_hours[h] / len(sessions), 6)
        for h in range(24) if start_hours[h] > 0
    } if sessions else {}
    features["session_end_distribution"] = {
        str(h): round(end_hours[h] / len(sessions), 6)
        for h in range(24) if end_hours[h] > 0
    } if sessions else {}

    # Response latency by hour
    lat_by_hour: Dict[str, float] = {}
    if latencies:
        # Rebuild latency-hour pairs
        lat_for_hour: Dict[int, List[float]] = {}
        for msg, dt in sorted_entries:
            reply_id = msg.get("reply_to") or msg.get("reply_to_msg_id") or msg.get("reply_to_message_id")
            if reply_id is not None and reply_id in id_to_date:
                parent_dt = id_to_date[reply_id]
                diff = (dt - parent_dt).total_seconds()
                if diff >= 0:
                    lat_for_hour.setdefault(dt.hour, []).append(diff)
        for h in sorted(lat_for_hour):
            vals = lat_for_hour[h]
            lat_by_hour[str(h)] = round(statistics.median(vals), 2)
    features["response_latency_by_hour"] = lat_by_hour

    # ── V2: Persona drift (JS divergence of vocabulary over time) ──────────
    _WORD_RE = re.compile(r"\b\w+\b")
    features["persona_drift_30d"] = _compute_drift(
        sorted_entries, _WORD_RE, days=30
    )
    features["persona_drift_90d"] = _compute_drift(
        sorted_entries, _WORD_RE, days=90
    )
    features["persona_drift_365d"] = _compute_drift(
        sorted_entries, _WORD_RE, days=365
    )

    # ── V2: Feature half-life (vocabulary turnover estimate) ──────────────
    features["feature_half_life"] = _estimate_half_life(
        sorted_entries, _WORD_RE
    )

    # Round all flat values for consistency; V2 dicts are already rounded.
    flat_features = {k: round(float(v), 6)
                     for k, v in features.items()
                     if isinstance(v, (int, float))}
    flat_features.update(
        {k: v for k, v in features.items() if not isinstance(v, (int, float))}
    )
    return flat_features


def compare_temporal_features(
    feat_a: Dict[str, Any],
    feat_b: Dict[str, Any],
) -> Tuple[float, float]:
    """Compare two temporal feature dicts using histogram intersection and metric differences.

    Args:
        feat_a: First temporal feature dict.
        feat_b: Second temporal feature dict.

    Returns:
        Tuple of (similarity_score 0-1, confidence 0-1).
    """
    if not isinstance(feat_a, dict) or not isinstance(feat_b, dict) or not feat_a or not feat_b:
        return (0.0, 0.0)

    # Check for valid hour distributions
    sum_a = sum(float(feat_a.get(f"hour_{h}", 0.0)) for h in range(24))
    sum_b = sum(float(feat_b.get(f"hour_{h}", 0.0)) for h in range(24))

    if sum_a == 0.0 or sum_b == 0.0:
        return (0.0, 0.0)

    # ── 1. Circadian Histogram Intersection (Hour distribution) ──────────────
    hist_intersection = sum(
        min(float(feat_a.get(f"hour_{h}", 0.0)), float(feat_b.get(f"hour_{h}", 0.0)))
        for h in range(24)
    )
    hist_sim = max(0.0, min(1.0, hist_intersection))

    # ── 2. Weekday / Weekend Similarity ──────────────────────────────────────
    w_diff = abs(float(feat_a.get("weekday_ratio", 0.0)) - float(feat_b.get("weekday_ratio", 0.0)))
    we_diff = abs(float(feat_a.get("weekend_ratio", 0.0)) - float(feat_b.get("weekend_ratio", 0.0)))
    day_sim = max(0.0, 1.0 - (w_diff + we_diff) / 2.0)

    # ── 3. Gap & Inactivity Similarity ───────────────────────────────────────
    typ_sim = _metric_similarity(
        float(feat_a.get("typical_gap_hours", 0.0)),
        float(feat_b.get("typical_gap_hours", 0.0)),
        min_scale=1.0,
    )
    long_sim = _metric_similarity(
        float(feat_a.get("longest_inactivity_hours", 0.0)),
        float(feat_b.get("longest_inactivity_hours", 0.0)),
        min_scale=1.0,
    )
    gap_sim = (typ_sim + long_sim) / 2.0

    # ── 4. Burst Similarity ──────────────────────────────────────────────────
    bf_sim = _metric_similarity(
        float(feat_a.get("burst_frequency", 0.0)),
        float(feat_b.get("burst_frequency", 0.0)),
        min_scale=0.1,
    )
    bi_sim = _metric_similarity(
        float(feat_a.get("burst_intensity", 0.0)),
        float(feat_b.get("burst_intensity", 0.0)),
        min_scale=1.0,
    )
    burst_sim = (bf_sim + bi_sim) / 2.0

    # ── 5. Latency Similarity & Weighted Score ───────────────────────────────
    lat_a = float(feat_a.get("response_latency_median", 0.0))
    lat_b = float(feat_b.get("response_latency_median", 0.0))

    if lat_a > 0.0 and lat_b > 0.0:
        lat_sim = _metric_similarity(lat_a, lat_b, min_scale=10.0)
        similarity = (
            0.40 * hist_sim
            + 0.20 * day_sim
            + 0.15 * gap_sim
            + 0.15 * burst_sim
            + 0.10 * lat_sim
        )
    else:
        similarity = (
            0.45 * hist_sim
            + 0.25 * day_sim
            + 0.15 * gap_sim
            + 0.15 * burst_sim
        )

    # ── 6. Confidence Calculation ────────────────────────────────────────────
    conf_a = float(feat_a.get("timezone_inference_confidence", 0.0))
    conf_b = float(feat_b.get("timezone_inference_confidence", 0.0))
    avg_conf = (conf_a + conf_b) / 2.0

    numeric_keys_a = {k for k, v in feat_a.items() if isinstance(v, (int, float))}
    numeric_keys_b = {k for k, v in feat_b.items() if isinstance(v, (int, float))}
    common_keys = numeric_keys_a & numeric_keys_b
    key_coverage = min(1.0, len(common_keys) / len(DEFAULT_TEMPORAL_FEATURES))

    confidence = max(0.0, min(1.0, 0.5 * avg_conf + 0.5 * key_coverage))

    return (round(similarity, 4), round(confidence, 4))
