"""
SPECTRA Intelligence — Telegram Native Feature Extraction & Comparison
=======================================================================
Extracts and compares native Telegram behavioral, graph, and metadata features
for actor attribution:
- Shared channels/groups posted in
- Direct reply targets (who this actor replies to)
- Reply sources (who replies to this actor)
- Forwarded message sources (channels and users)
- Shared media IDs posted across dialogues/channels
- Temporal username change histories and transition chains
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

# Regex patterns for detecting username change notifications in service messages / text
USERNAME_CHANGE_PATTERN: re.Pattern = re.compile(
    r"(?:changed\s+(?:their\s+)?username\s+from\s+@?([a-zA-Z0-9_]{3,32})\s+to\s+@?([a-zA-Z0-9_]{3,32}))|"
    r"(?:username\s+changed\s+from\s+@?([a-zA-Z0-9_]{3,32})\s+to\s+@?([a-zA-Z0-9_]{3,32}))",
    re.IGNORECASE,
)


def _safe_str(val: Any) -> str:
    """Normalize any identifier (int, str) into a trimmed string."""
    if val is None:
        return ""
    return str(val).strip()


def _overlap_coefficient(set_a: Set[Any], set_b: Set[Any]) -> float:
    """Compute overlap coefficient between two sets."""
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / min(len(set_a), len(set_b))


def _parse_timestamp(val: Any) -> str:
    """Convert datetime/timestamp/int to ISO string or formatted string."""
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def extract_telegram_features(
    messages: List[Dict[str, Any]],
    user_id: int,
    channel_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Extract native Telegram social graph and metadata features for a user.

    Args:
        messages: List of message dictionaries from/involving this actor
        user_id: Telegram user ID for the actor
        channel_id: Optional primary channel context

    Returns:
        Dictionary with list values:
        - channels: list of channel/group IDs where user posted
        - reply_targets: list of user IDs this actor replied to
        - reply_sources: list of user IDs that replied to this actor
        - forwarded_from: list of source channel/user IDs from forwards
        - shared_media_ids: list of media IDs posted by user
        - username_changes: list of (timestamp, old_username, new_username)
    """
    channels: Set[str] = set()
    reply_targets: Set[str] = set()
    reply_sources: Set[str] = set()
    forwarded_from: Set[str] = set()
    shared_media_ids: Set[str] = set()
    username_changes: List[Tuple[str, str, str]] = []

    if channel_id is not None and channel_id != 0:
        channels.add(_safe_str(channel_id))

    if not messages:
        return {
            "channels": sorted(channels),
            "reply_targets": [],
            "reply_sources": [],
            "forwarded_from": [],
            "shared_media_ids": [],
            "username_changes": [],
        }

    # Chronological tracking of user names over time
    chronological_usernames: List[Tuple[str, str]] = []  # (timestamp, username)

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        # 1. Channels / Chats
        ch = msg.get("channel_id") or msg.get("chat_id") or msg.get("peer_id")
        if ch is not None and ch != 0:
            channels.add(_safe_str(ch))

        # 2. Reply targets (who this actor replied to)
        reply_to_u = (
            msg.get("reply_to_user_id")
            or msg.get("reply_to_peer_id")
            or msg.get("reply_to_author_id")
            or msg.get("reply_to_user")
            or msg.get("reply_to_sender")
        )
        if reply_to_u is not None and reply_to_u != 0:
            if isinstance(reply_to_u, dict):
                sub_id = reply_to_u.get("id") or reply_to_u.get("user_id")
                if sub_id:
                    reply_targets.add(_safe_str(sub_id))
            else:
                reply_targets.add(_safe_str(reply_to_u))

        # 3. Reply sources (users that replied to this actor)
        r_sources = (
            msg.get("reply_sources")
            or msg.get("replies_from")
            or msg.get("reply_from_user_id")
            or msg.get("replied_by")
        )
        if r_sources is not None:
            if isinstance(r_sources, (list, set, tuple)):
                for rs in r_sources:
                    if rs:
                        reply_sources.add(_safe_str(rs))
            else:
                reply_sources.add(_safe_str(r_sources))

        # 4. Forwarded from (sources of forwarded content)
        fwd = (
            msg.get("forward_from_id")
            or msg.get("forward_from_chat_id")
            or msg.get("forward_from_channel_id")
            or msg.get("fwd_from")
            or msg.get("forward_from")
            or msg.get("fwd_from_id")
            or msg.get("forward_sender_name")
        )
        if fwd is not None:
            if isinstance(fwd, dict):
                fwd_id = fwd.get("channel_id") or fwd.get("chat_id") or fwd.get("from_id") or fwd.get("id") or fwd.get("name")
                if fwd_id:
                    forwarded_from.add(_safe_str(fwd_id))
            else:
                forwarded_from.add(_safe_str(fwd))

        # 5. Shared media IDs
        m_id = (
            msg.get("media_id")
            or msg.get("file_id")
            or msg.get("photo_id")
            or msg.get("document_id")
        )
        if m_id is not None:
            shared_media_ids.add(_safe_str(m_id))

        m_ids = msg.get("media_ids")
        if isinstance(m_ids, (list, set, tuple)):
            for mid in m_ids:
                if mid is not None:
                    shared_media_ids.add(_safe_str(mid))

        media_obj = msg.get("media")
        if isinstance(media_obj, dict):
            inner_mid = media_obj.get("id") or media_obj.get("media_id")
            if inner_mid is not None:
                shared_media_ids.add(_safe_str(inner_mid))

        # 6. Username changes from explicit message fields or service actions
        ts = _parse_timestamp(msg.get("date") or msg.get("timestamp") or msg.get("created_at") or "")
        
        # Explicit username change list or action
        explicit_changes = msg.get("username_changes")
        if isinstance(explicit_changes, list):
            for item in explicit_changes:
                if isinstance(item, (list, tuple)) and len(item) == 3:
                    username_changes.append((_parse_timestamp(item[0]), _safe_str(item[1]), _safe_str(item[2])))
                elif isinstance(item, dict):
                    username_changes.append((
                        _parse_timestamp(item.get("timestamp") or item.get("date")),
                        _safe_str(item.get("old_username") or item.get("old")),
                        _safe_str(item.get("new_username") or item.get("new")),
                    ))

        action = str(msg.get("action") or msg.get("action_type") or "").lower()
        if "username" in action and "change" in action:
            old_u = _safe_str(msg.get("old_username") or msg.get("old"))
            new_u = _safe_str(msg.get("new_username") or msg.get("new"))
            if old_u and new_u:
                username_changes.append((ts, old_u, new_u))

        # Text regex matching for username change notifications
        text = str(msg.get("content") or msg.get("text") or msg.get("message") or "")
        if text:
            for match in USERNAME_CHANGE_PATTERN.finditer(text):
                groups = [g for g in match.groups() if g is not None]
                if len(groups) >= 2:
                    username_changes.append((ts, groups[0], groups[1]))

        # Track username attached to user's messages for timeline change detection
        msg_uname = msg.get("username") or msg.get("sender_username") or msg.get("from_username")
        msg_uid = msg.get("user_id") or msg.get("sender_id") or msg.get("from_id")
        if msg_uname and (msg_uid is None or int(_safe_str(msg_uid) or user_id) == user_id):
            chronological_usernames.append((ts, _safe_str(msg_uname).lstrip("@").lower()))

    # Chronological username transitions
    if len(chronological_usernames) > 1:
        prev_ts, prev_uname = chronological_usernames[0]
        for curr_ts, curr_uname in chronological_usernames[1:]:
            if curr_uname != prev_uname:
                transition = (curr_ts or prev_ts, prev_uname, curr_uname)
                if transition not in username_changes:
                    username_changes.append(transition)
                prev_uname = curr_uname

    # Deduplicate username changes
    deduped_changes = list(dict.fromkeys(username_changes))

    return {
        "channels": sorted(channels),
        "reply_targets": sorted(reply_targets),
        "reply_sources": sorted(reply_sources),
        "forwarded_from": sorted(forwarded_from),
        "shared_media_ids": sorted(shared_media_ids),
        "username_changes": deduped_changes,
    }


def compare_telegram_features(
    feat_a: Dict[str, Any], feat_b: Dict[str, Any]
) -> Tuple[float, float]:
    """
    Compare Telegram-native features between two actors using set similarity
    and structural continuity comparison.

    Args:
        feat_a: Feature dictionary for Actor A
        feat_b: Feature dictionary for Actor B

    Returns:
        Tuple of (similarity_score, confidence) both bounded in [0.0, 1.0].
    """
    if not feat_a or not feat_b:
        return 0.0, 0.0

    channels_a = set(feat_a.get("channels", []))
    channels_b = set(feat_b.get("channels", []))

    targets_a = set(feat_a.get("reply_targets", []))
    targets_b = set(feat_b.get("reply_targets", []))

    sources_a = set(feat_a.get("reply_sources", []))
    sources_b = set(feat_b.get("reply_sources", []))

    fwd_a = set(feat_a.get("forwarded_from", []))
    fwd_b = set(feat_b.get("forwarded_from", []))

    media_a = set(feat_a.get("shared_media_ids", []))
    media_b = set(feat_b.get("shared_media_ids", []))

    changes_a = feat_a.get("username_changes", [])
    changes_b = feat_b.get("username_changes", [])

    # Structural check 1: Username continuity
    # Check if actor A changed into a username used by actor B or shared identical transitions
    structural_score = 0.0
    has_structural = False

    transitions_a = {(str(old).lower(), str(new).lower()) for _, old, new in changes_a if old and new}
    transitions_b = {(str(old).lower(), str(new).lower()) for _, old, new in changes_b if old and new}

    all_unames_a = {u for pair in transitions_a for u in pair}
    all_unames_b = {u for pair in transitions_b for u in pair}

    if transitions_a and transitions_b and (transitions_a & transitions_b):
        # Identical username transition detected
        structural_score = 1.0
        has_structural = True
    elif all_unames_a and all_unames_b and (all_unames_a & all_unames_b):
        # Overlapping historical usernames
        structural_score = 0.9
        has_structural = True

    # Category definitions: (name, similarity, has_data, weight)
    categories = [
        ("channels", _overlap_coefficient(channels_a, channels_b), bool(channels_a | channels_b), 0.25),
        ("reply_targets", _overlap_coefficient(targets_a, targets_b), bool(targets_a | targets_b), 0.20),
        ("reply_sources", _overlap_coefficient(sources_a, sources_b), bool(sources_a | sources_b), 0.15),
        ("forwarded_from", _overlap_coefficient(fwd_a, fwd_b), bool(fwd_a | fwd_b), 0.20),
        ("shared_media_ids", _overlap_coefficient(media_a, media_b), bool(media_a | media_b), 0.20),
    ]

    if has_structural:
        categories.append(("username_structural", structural_score, True, 0.30))

    active_weight = 0.0
    weighted_sum = 0.0

    for _, sim, has_data, weight in categories:
        if has_data:
            weighted_sum += sim * weight
            active_weight += weight

    if active_weight == 0.0:
        return 0.0, 0.0

    similarity_score = weighted_sum / active_weight

    # Total observed items across both actors for confidence
    total_items = (
        len(channels_a | channels_b)
        + len(targets_a | targets_b)
        + len(sources_a | sources_b)
        + len(fwd_a | fwd_b)
        + len(media_a | media_b)
        + len(changes_a)
        + len(changes_b)
    )

    if total_items == 0:
        return 0.0, 0.0

    confidence = min(1.0, max(0.0, 1.0 - math.exp(-0.20 * total_items)))

    return round(similarity_score, 4), round(confidence, 4)


__all__ = [
    "extract_telegram_features",
    "compare_telegram_features",
]
