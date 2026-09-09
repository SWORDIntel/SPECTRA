"""
SPECTRA Evaluation Harness — Benchmark Datasets & Builders
==========================================================
Constructs forensic and stylometric evaluation datasets directly from SPECTRA's
SQLite database (messages, users, evidence, hypotheses).

Supports benchmark splits for:
- Same-Actor attribution (known linked identities)
- Different-Actor attribution (negative baseline pairs)
- Longitudinal style change (temporal author drift)
- Cross-channel posting (multi-channel style consistency)
- Forwarded / copied message control (negative control for style contamination)
- Short message benchmark (low-signal stylometry)
- Long message benchmark (high-signal stylometry)
- Bot-generated content benchmark
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Ground truth label constants
SAME_ACTOR: int = 1
DIFFERENT_ACTOR: int = 0


@dataclass
class Dataset:
    """Benchmark evaluation dataset containing subject pairs and their message samples."""

    name: str
    description: str
    pairs: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, index: int) -> Dict[str, Any]:
        return self.pairs[index]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize dataset to dictionary representation."""
        return {
            "name": self.name,
            "description": self.description,
            "pairs": self.pairs,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Dataset:
        """Instantiate dataset from dictionary."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            pairs=data.get("pairs", []),
            metadata=data.get("metadata", {}),
        )

    def summary(self) -> Dict[str, Any]:
        """Compute summary statistics for the dataset."""
        positive = sum(1 for p in self.pairs if p.get("label") == SAME_ACTOR)
        negative = sum(1 for p in self.pairs if p.get("label") == DIFFERENT_ACTOR)
        subjects: Set[str] = set()
        for p in self.pairs:
            if "subject_a" in p and p["subject_a"] is not None:
                subjects.add(str(p["subject_a"]))
            if "subject_b" in p and p["subject_b"] is not None:
                subjects.add(str(p["subject_b"]))
        return {
            "name": self.name,
            "total_pairs": len(self.pairs),
            "positive_pairs": positive,
            "negative_pairs": negative,
            "unique_subjects": len(subjects),
            "metadata": self.metadata,
        }


# ─── SQLite DB Query Helpers ──────────────────────────────────────────────────

def _get_cursor(db_conn: Any) -> Any:
    """Obtain a SQLite cursor or connection wrapper safely."""
    if hasattr(db_conn, "cursor") and callable(db_conn.cursor):
        return db_conn.cursor()
    if hasattr(db_conn, "cur"):
        return db_conn.cur
    if hasattr(db_conn, "conn"):
        if hasattr(db_conn.conn, "cursor") and callable(db_conn.conn.cursor):
            return db_conn.conn.cursor()
        return db_conn.conn
    if hasattr(db_conn, "execute"):
        return db_conn
    raise TypeError(f"Unsupported db_conn type: {type(db_conn)}")


def _table_exists(cur: Any, table_name: str) -> bool:
    """Check if a table exists in the database."""
    try:
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        row = cur.fetchone()
        return row is not None
    except Exception as e:
        logger.debug("Table check failed for %s: %s", table_name, e)
        return False


def _get_table_columns(cur: Any, table_name: str) -> List[str]:
    """Get list of column names for a table."""
    try:
        cur.execute(f"PRAGMA table_info({table_name})")
        rows = cur.fetchall()
        return [r[1] for r in rows] if rows else []
    except Exception as e:
        logger.debug("Column check failed for %s: %s", table_name, e)
        return []


def _row_to_msg_dict(row: Any, columns: List[str]) -> Dict[str, Any]:
    """Convert a SQLite message row into a dictionary."""
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys") and callable(row.keys):
        return {k: row[k] for k in row.keys()}
    if columns and len(columns) == len(row):
        return {columns[i]: row[i] for i in range(len(columns))}
    # Fallback to standard messages table schema
    fallback_cols = [
        "id", "type", "date", "edit_date", "content",
        "reply_to", "user_id", "media_id", "checksum",
    ]
    res: Dict[str, Any] = {}
    for i, val in enumerate(row):
        key = fallback_cols[i] if i < len(fallback_cols) else f"col_{i}"
        res[key] = val
    return res


def _fetch_messages_for_user(
    cur: Any,
    user_id: Any,
    limit: Optional[int] = None,
    min_words: Optional[int] = None,
    max_words: Optional[int] = None,
    channel_id: Optional[int] = None,
    order_asc: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch structured messages for a specific user ID."""
    if not _table_exists(cur, "messages"):
        return []

    cols = _get_table_columns(cur, "messages")
    clauses = ["user_id = ?", "content IS NOT NULL", "trim(content) != ''"]
    params: List[Any] = [user_id]

    if channel_id is not None and "channel_id" in cols:
        clauses.append("channel_id = ?")
        params.append(channel_id)

    order_dir = "ASC" if order_asc else "DESC"
    sql = f"SELECT * FROM messages WHERE {' AND '.join(clauses)} ORDER BY date {order_dir}"
    if limit is not None and limit > 0:
        sql += f" LIMIT {int(limit)}"

    try:
        cur.execute(sql, params)
        raw_rows = cur.fetchall()
    except Exception as e:
        logger.debug("Failed fetching messages for user %s: %s", user_id, e)
        return []

    messages: List[Dict[str, Any]] = []
    for r in raw_rows:
        msg = _row_to_msg_dict(r, cols)
        content = msg.get("content") or ""
        word_count = len(content.split())
        if min_words is not None and word_count < min_words:
            continue
        if max_words is not None and word_count > max_words:
            continue
        messages.append(msg)

    return messages


def _parse_user_id(subject: str) -> Optional[int]:
    """Parse user ID from a canonical entity ID or numeric string."""
    if isinstance(subject, int):
        return subject
    s = str(subject).strip()
    if s.startswith("telegram:user:"):
        s = s[len("telegram:user:"):]
    elif s.startswith("user:"):
        s = s[len("user:"):]
    # Remove any trailing suffixes like :early or :channel_1
    parts = s.split(":")
    try:
        return int(parts[0])
    except (ValueError, IndexError):
        return None


# ─── Dataset Builders ────────────────────────────────────────────────────────

def build_same_actor_dataset(
    db_conn: Any,
    min_messages: int = 1,
    max_pairs: int = 100,
) -> Dataset:
    """Construct benchmark dataset of accounts linked by known same-actor ground truth.

    Queries intelligence hypotheses, campaigns, and user metadata to identify
    known aliases and sockpuppet accounts.

    Args:
        db_conn: SQLite connection, cursor, or SpectraDB instance.
        min_messages: Minimum message count required per subject.
        max_pairs: Maximum number of pairs to include.

    Returns:
        Dataset with positive same-actor pairs (label=1).
    """
    cur = _get_cursor(db_conn)
    pairs: List[Dict[str, Any]] = []
    seen_pairs: Set[Tuple[str, str]] = set()

    try:
        # 1. Search intelligence_hypotheses for same_actor assertions
        if _table_exists(cur, "intelligence_hypotheses"):
            try:
                cur.execute(
                    """
                    SELECT subject_a, subject_b, probability, confidence
                    FROM intelligence_hypotheses
                    WHERE (hypothesis_type = 'same_actor' OR hypothesis_type = 'SAME_ACTOR')
                      AND subject_b IS NOT NULL
                      AND probability >= 0.5
                    ORDER BY confidence DESC
                    """
                )
                hyp_rows = cur.fetchall()
                for row in hyp_rows:
                    sub_a = str(row[0])
                    sub_b = str(row[1])
                    if sub_a == sub_b:
                        continue
                    pair_key = tuple(sorted([sub_a, sub_b]))
                    if pair_key in seen_pairs:
                        continue

                    uid_a = _parse_user_id(sub_a)
                    uid_b = _parse_user_id(sub_b)
                    if uid_a is None or uid_b is None:
                        continue

                    msgs_a = _fetch_messages_for_user(cur, uid_a)
                    msgs_b = _fetch_messages_for_user(cur, uid_b)
                    if len(msgs_a) >= min_messages and len(msgs_b) >= min_messages:
                        seen_pairs.add(pair_key)
                        pairs.append({
                            "subject_a": sub_a,
                            "subject_b": sub_b,
                            "label": SAME_ACTOR,
                            "messages_a": msgs_a,
                            "messages_b": msgs_b,
                        })
                        if len(pairs) >= max_pairs:
                            break
            except Exception as e:
                logger.debug("Failed querying intelligence_hypotheses: %s", e)

        # 2. Search intelligence_campaigns for multi-actor clusters
        if len(pairs) < max_pairs and _table_exists(cur, "intelligence_campaigns"):
            try:
                cur.execute("SELECT actors_json FROM intelligence_campaigns WHERE actors_json IS NOT NULL")
                for (actors_raw,) in cur.fetchall():
                    if not actors_raw:
                        continue
                    try:
                        actors = json.loads(actors_raw)
                        if isinstance(actors, list) and len(actors) >= 2:
                            for i in range(len(actors)):
                                for j in range(i + 1, len(actors)):
                                    sub_a = str(actors[i])
                                    sub_b = str(actors[j])
                                    pair_key = tuple(sorted([sub_a, sub_b]))
                                    if pair_key in seen_pairs:
                                        continue
                                    uid_a = _parse_user_id(sub_a)
                                    uid_b = _parse_user_id(sub_b)
                                    if uid_a is None or uid_b is None or uid_a == uid_b:
                                        continue
                                    msgs_a = _fetch_messages_for_user(cur, uid_a)
                                    msgs_b = _fetch_messages_for_user(cur, uid_b)
                                    if len(msgs_a) >= min_messages and len(msgs_b) >= min_messages:
                                        seen_pairs.add(pair_key)
                                        pairs.append({
                                            "subject_a": sub_a,
                                            "subject_b": sub_b,
                                            "label": SAME_ACTOR,
                                            "messages_a": msgs_a,
                                            "messages_b": msgs_b,
                                        })
                                        if len(pairs) >= max_pairs:
                                            break
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                logger.debug("Failed querying intelligence_campaigns: %s", e)

        # 3. Search users table for matching alias tags (e.g. tag 'sockpuppet:X' or 'alias:X')
        if len(pairs) < max_pairs and _table_exists(cur, "users"):
            try:
                cur.execute(
                    "SELECT id, tags FROM users WHERE tags IS NOT NULL AND tags != ''"
                )
                tag_map: Dict[str, List[int]] = {}
                for uid, tags_str in cur.fetchall():
                    for t in str(tags_str).split(","):
                        t_clean = t.strip().lower()
                        if ":" in t_clean and any(k in t_clean for k in ("same", "sock", "alias", "group", "actor")):
                            tag_map.setdefault(t_clean, []).append(uid)

                for tag, uids in tag_map.items():
                    if len(uids) >= 2:
                        for i in range(len(uids)):
                            for j in range(i + 1, len(uids)):
                                uid_a, uid_b = uids[i], uids[j]
                                sub_a = f"telegram:user:{uid_a}"
                                sub_b = f"telegram:user:{uid_b}"
                                pair_key = tuple(sorted([sub_a, sub_b]))
                                if pair_key in seen_pairs:
                                    continue
                                msgs_a = _fetch_messages_for_user(cur, uid_a)
                                msgs_b = _fetch_messages_for_user(cur, uid_b)
                                if len(msgs_a) >= min_messages and len(msgs_b) >= min_messages:
                                    seen_pairs.add(pair_key)
                                    pairs.append({
                                        "subject_a": sub_a,
                                        "subject_b": sub_b,
                                        "label": SAME_ACTOR,
                                        "messages_a": msgs_a,
                                        "messages_b": msgs_b,
                                    })
                                    if len(pairs) >= max_pairs:
                                        break
            except Exception as e:
                logger.debug("Failed querying user tags: %s", e)

    except Exception as e:
        logger.warning("Error building same actor dataset: %s", e)

    return Dataset(
        name="same_actor_benchmark",
        description="Known same-actor linked accounts benchmark dataset",
        pairs=pairs,
        metadata={
            "total_pairs": len(pairs),
            "positive_pairs": len(pairs),
            "negative_pairs": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def build_different_actor_dataset(
    db_conn: Any,
    max_pairs: int = 100,
    min_messages: int = 1,
) -> Dataset:
    """Construct benchmark dataset of different actors for negative baseline attribution.

    Pairs distinct users who have posted messages with text content.

    Args:
        db_conn: SQLite connection, cursor, or SpectraDB instance.
        max_pairs: Maximum number of negative pairs to construct.
        min_messages: Minimum message count required per user.

    Returns:
        Dataset with negative different-actor pairs (label=0).
    """
    cur = _get_cursor(db_conn)
    pairs: List[Dict[str, Any]] = []

    if not _table_exists(cur, "messages"):
        return Dataset(
            name="different_actor_benchmark",
            description="Distinct actors with different writing styles benchmark dataset",
            pairs=[],
            metadata={"total_pairs": 0, "generated_at": datetime.now(timezone.utc).isoformat()},
        )

    try:
        cur.execute(
            """
            SELECT user_id, COUNT(*) as cnt
            FROM messages
            WHERE user_id IS NOT NULL AND content IS NOT NULL AND trim(content) != ''
            GROUP BY user_id
            HAVING cnt >= ?
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (min_messages, max_pairs * 2),
        )
        user_rows = cur.fetchall()
        user_ids = [r[0] for r in user_rows]

        # Load messages for each user
        user_msgs = {uid: _fetch_messages_for_user(cur, uid) for uid in user_ids}

        # Form negative pairs across different users
        for i in range(len(user_ids)):
            for j in range(i + 1, len(user_ids)):
                uid_a = user_ids[i]
                uid_b = user_ids[j]
                msgs_a = user_msgs.get(uid_a, [])
                msgs_b = user_msgs.get(uid_b, [])

                if len(msgs_a) >= min_messages and len(msgs_b) >= min_messages:
                    pairs.append({
                        "subject_a": f"telegram:user:{uid_a}",
                        "subject_b": f"telegram:user:{uid_b}",
                        "label": DIFFERENT_ACTOR,
                        "messages_a": msgs_a,
                        "messages_b": msgs_b,
                    })
                    if len(pairs) >= max_pairs:
                        break
            if len(pairs) >= max_pairs:
                break

    except Exception as e:
        logger.warning("Error building different actor dataset: %s", e)

    return Dataset(
        name="different_actor_benchmark",
        description="Distinct actors with different writing styles benchmark dataset",
        pairs=pairs,
        metadata={
            "total_pairs": len(pairs),
            "positive_pairs": 0,
            "negative_pairs": len(pairs),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def build_style_change_dataset(
    db_conn: Any,
    min_messages: int = 2,
    max_pairs: int = 100,
) -> Dataset:
    """Construct benchmark dataset of the same actor across different time periods.

    Splits each user's message corpus chronologically into early and late subsets
    to evaluate author identification stability under temporal style drift.

    Args:
        db_conn: SQLite connection, cursor, or SpectraDB instance.
        min_messages: Minimum message count required per period (total >= 2 * min_messages).
        max_pairs: Maximum number of pairs to produce.

    Returns:
        Dataset with positive pairs (label=1) representing early vs late message splits.
    """
    cur = _get_cursor(db_conn)
    pairs: List[Dict[str, Any]] = []

    if not _table_exists(cur, "messages"):
        return Dataset(
            name="style_change_benchmark",
            description="Same actor across chronological time periods benchmark dataset",
            pairs=[],
            metadata={"total_pairs": 0, "generated_at": datetime.now(timezone.utc).isoformat()},
        )

    try:
        cur.execute(
            """
            SELECT user_id, COUNT(*) as cnt
            FROM messages
            WHERE user_id IS NOT NULL AND content IS NOT NULL AND trim(content) != ''
            GROUP BY user_id
            HAVING cnt >= ?
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (min_messages * 2, max_pairs),
        )
        user_rows = cur.fetchall()

        for (user_id, _) in user_rows:
            all_msgs = _fetch_messages_for_user(cur, user_id, order_asc=True)
            if len(all_msgs) < min_messages * 2:
                continue

            mid = len(all_msgs) // 2
            early_msgs = all_msgs[:mid]
            late_msgs = all_msgs[mid:]

            pairs.append({
                "subject_a": f"telegram:user:{user_id}:early",
                "subject_b": f"telegram:user:{user_id}:late",
                "label": SAME_ACTOR,
                "messages_a": early_msgs,
                "messages_b": late_msgs,
            })
            if len(pairs) >= max_pairs:
                break

    except Exception as e:
        logger.warning("Error building style change dataset: %s", e)

    return Dataset(
        name="style_change_benchmark",
        description="Same actor across chronological time periods benchmark dataset",
        pairs=pairs,
        metadata={
            "total_pairs": len(pairs),
            "positive_pairs": len(pairs),
            "negative_pairs": 0,
            "min_messages_per_period": min_messages,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def build_cross_channel_dataset(
    db_conn: Any,
    min_messages_per_channel: int = 1,
    max_pairs: int = 100,
) -> Dataset:
    """Construct benchmark dataset of the same actor posting in different channels.

    Finds users who have authored messages in multiple channels or groups and creates
    cross-channel pairs.

    Args:
        db_conn: SQLite connection, cursor, or SpectraDB instance.
        min_messages_per_channel: Minimum messages required per channel.
        max_pairs: Maximum number of pairs to produce.

    Returns:
        Dataset with positive pairs (label=1) of author samples from different channels.
    """
    cur = _get_cursor(db_conn)
    pairs: List[Dict[str, Any]] = []

    if not _table_exists(cur, "messages"):
        return Dataset(
            name="cross_channel_benchmark",
            description="Same actor posting across different channels benchmark dataset",
            pairs=[],
            metadata={"total_pairs": 0, "generated_at": datetime.now(timezone.utc).isoformat()},
        )

    cols = _get_table_columns(cur, "messages")

    try:
        # Check if messages table has a channel_id column
        if "channel_id" in cols:
            cur.execute(
                """
                SELECT user_id, channel_id, COUNT(*) as cnt
                FROM messages
                WHERE user_id IS NOT NULL AND channel_id IS NOT NULL
                  AND content IS NOT NULL AND trim(content) != ''
                GROUP BY user_id, channel_id
                HAVING cnt >= ?
                """,
                (min_messages_per_channel,),
            )
            user_ch_rows = cur.fetchall()
            user_channels: Dict[int, List[int]] = {}
            for uid, ch_id, _ in user_ch_rows:
                user_channels.setdefault(uid, []).append(ch_id)

            for uid, ch_list in user_channels.items():
                if len(ch_list) >= 2:
                    for i in range(len(ch_list)):
                        for j in range(i + 1, len(ch_list)):
                            ch_a = ch_list[i]
                            ch_b = ch_list[j]
                            msgs_a = _fetch_messages_for_user(cur, uid, channel_id=ch_a)
                            msgs_b = _fetch_messages_for_user(cur, uid, channel_id=ch_b)
                            if len(msgs_a) >= min_messages_per_channel and len(msgs_b) >= min_messages_per_channel:
                                pairs.append({
                                    "subject_a": f"telegram:user:{uid}:channel:{ch_a}",
                                    "subject_b": f"telegram:user:{uid}:channel:{ch_b}",
                                    "label": SAME_ACTOR,
                                    "messages_a": msgs_a,
                                    "messages_b": msgs_b,
                                })
                                if len(pairs) >= max_pairs:
                                    break
                        if len(pairs) >= max_pairs:
                            break

        # If no channel_id in messages, check osint_interactions
        elif _table_exists(cur, "osint_interactions"):
            cur.execute(
                """
                SELECT source_user_id, channel_id, COUNT(*) as cnt
                FROM osint_interactions
                GROUP BY source_user_id, channel_id
                HAVING cnt >= ?
                """,
                (min_messages_per_channel,),
            )
            user_ch_rows = cur.fetchall()
            user_channels = {}
            for uid, ch_id, _ in user_ch_rows:
                user_channels.setdefault(uid, []).append(ch_id)

            for uid, ch_list in user_channels.items():
                if len(ch_list) >= 2:
                    msgs = _fetch_messages_for_user(cur, uid)
                    if len(msgs) >= 2 * min_messages_per_channel:
                        mid = len(msgs) // 2
                        pairs.append({
                            "subject_a": f"telegram:user:{uid}:channel:{ch_list[0]}",
                            "subject_b": f"telegram:user:{uid}:channel:{ch_list[1]}",
                            "label": SAME_ACTOR,
                            "messages_a": msgs[:mid],
                            "messages_b": msgs[mid:],
                        })
                        if len(pairs) >= max_pairs:
                            break

    except Exception as e:
        logger.warning("Error building cross channel dataset: %s", e)

    return Dataset(
        name="cross_channel_benchmark",
        description="Same actor posting across different channels benchmark dataset",
        pairs=pairs,
        metadata={
            "total_pairs": len(pairs),
            "positive_pairs": len(pairs),
            "negative_pairs": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def build_forwarded_control_dataset(
    db_conn: Any,
    max_pairs: int = 100,
) -> Dataset:
    """Construct benchmark negative control dataset using forwarded or copied messages.

    Forwarded or verbatim copied messages carry the style of the original author rather
    than the sender. This dataset tests whether stylometric models correctly avoid
    false positive attributions on forwarded/quoted text.

    Args:
        db_conn: SQLite connection, cursor, or SpectraDB instance.
        max_pairs: Maximum number of control pairs.

    Returns:
        Dataset with negative pairs (label=0) for forwarded/copied content.
    """
    cur = _get_cursor(db_conn)
    pairs: List[Dict[str, Any]] = []

    if not _table_exists(cur, "messages"):
        return Dataset(
            name="forwarded_control_benchmark",
            description="Forwarded and copied messages negative control benchmark dataset",
            pairs=[],
            metadata={"total_pairs": 0, "generated_at": datetime.now(timezone.utc).isoformat()},
        )

    cols = _get_table_columns(cur, "messages")

    try:
        # 1. Search for forwarded messages (type = 'forward' or reply_to is present)
        cur.execute(
            """
            SELECT * FROM messages
            WHERE user_id IS NOT NULL AND (type = 'forward' OR type LIKE '%forward%' OR reply_to IS NOT NULL)
              AND content IS NOT NULL AND trim(content) != ''
            LIMIT ?
            """,
            (max_pairs * 2,),
        )
        forwarded_rows = cur.fetchall()

        for r in forwarded_rows:
            fwd_msg = _row_to_msg_dict(r, cols)
            uid = fwd_msg.get("user_id")
            if uid is None:
                continue

            # Fetch author's regular messages (non-forwarded)
            cur.execute(
                """
                SELECT * FROM messages
                WHERE user_id = ? AND type != 'forward' AND (reply_to IS NULL OR reply_to = 0)
                  AND content IS NOT NULL AND trim(content) != ''
                LIMIT 5
                """,
                (uid,),
            )
            reg_rows = cur.fetchall()
            if reg_rows:
                reg_msgs = [_row_to_msg_dict(rr, cols) for rr in reg_rows]
                pairs.append({
                    "subject_a": f"telegram:user:{uid}:original",
                    "subject_b": f"telegram:user:{uid}:forwarded",
                    "label": DIFFERENT_ACTOR,
                    "messages_a": reg_msgs,
                    "messages_b": [fwd_msg],
                })
                if len(pairs) >= max_pairs:
                    break

        # 2. Search for identical content posted by different users (copied text)
        if len(pairs) < max_pairs:
            cur.execute(
                """
                SELECT content, GROUP_CONCAT(DISTINCT user_id) as uids, COUNT(DISTINCT user_id) as user_cnt
                FROM messages
                WHERE user_id IS NOT NULL AND content IS NOT NULL AND length(trim(content)) > 20
                GROUP BY content
                HAVING user_cnt >= 2
                LIMIT ?
                """,
                (max_pairs,),
            )
            copied_rows = cur.fetchall()
            for content, uids_str, _ in copied_rows:
                uids = [int(u) for u in str(uids_str).split(",") if u.isdigit()]
                if len(uids) >= 2:
                    uid_a, uid_b = uids[0], uids[1]
                    msgs_a = _fetch_messages_for_user(cur, uid_a)
                    msgs_b = _fetch_messages_for_user(cur, uid_b)
                    if msgs_a and msgs_b:
                        pairs.append({
                            "subject_a": f"telegram:user:{uid_a}",
                            "subject_b": f"telegram:user:{uid_b}",
                            "label": DIFFERENT_ACTOR,
                            "messages_a": msgs_a,
                            "messages_b": msgs_b,
                        })
                        if len(pairs) >= max_pairs:
                            break

    except Exception as e:
        logger.warning("Error building forwarded control dataset: %s", e)

    return Dataset(
        name="forwarded_control_benchmark",
        description="Forwarded and copied messages negative control benchmark dataset",
        pairs=pairs,
        metadata={
            "total_pairs": len(pairs),
            "positive_pairs": 0,
            "negative_pairs": len(pairs),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def build_short_message_dataset(
    db_conn: Any,
    max_words: int = 20,
    max_pairs: int = 100,
) -> Dataset:
    """Construct benchmark dataset of short messages (<= max_words words).

    Evaluates attribution performance under low-information / short-message constraints.

    Args:
        db_conn: SQLite connection, cursor, or SpectraDB instance.
        max_words: Maximum word count per message (default: 20).
        max_pairs: Maximum number of pairs to produce.

    Returns:
        Dataset with short message pairs (both positive same-actor and negative different-actor).
    """
    cur = _get_cursor(db_conn)
    pairs: List[Dict[str, Any]] = []

    if not _table_exists(cur, "messages"):
        return Dataset(
            name="short_message_benchmark",
            description=f"Short messages (<= {max_words} words) benchmark dataset",
            pairs=[],
            metadata={"max_words": max_words, "total_pairs": 0, "generated_at": datetime.now(timezone.utc).isoformat()},
        )

    try:
        # Fetch active users
        cur.execute(
            """
            SELECT DISTINCT user_id FROM messages
            WHERE user_id IS NOT NULL AND content IS NOT NULL AND trim(content) != ''
            LIMIT ?
            """,
            (max_pairs * 2,),
        )
        user_ids = [r[0] for r in cur.fetchall()]

        # Collect short messages per user
        user_short_msgs: Dict[int, List[Dict[str, Any]]] = {}
        for uid in user_ids:
            s_msgs = _fetch_messages_for_user(cur, uid, max_words=max_words)
            if s_msgs:
                user_short_msgs[uid] = s_msgs

        # 1. Positive pairs: split short messages of the same user
        for uid, msgs in user_short_msgs.items():
            if len(msgs) >= 2:
                mid = len(msgs) // 2
                pairs.append({
                    "subject_a": f"telegram:user:{uid}:split1",
                    "subject_b": f"telegram:user:{uid}:split2",
                    "label": SAME_ACTOR,
                    "messages_a": msgs[:mid],
                    "messages_b": msgs[mid:],
                })
                if len(pairs) >= max_pairs // 2:
                    break

        # 2. Negative pairs: short messages from distinct users
        active_uids = list(user_short_msgs.keys())
        for i in range(len(active_uids)):
            for j in range(i + 1, len(active_uids)):
                uid_a, uid_b = active_uids[i], active_uids[j]
                pairs.append({
                    "subject_a": f"telegram:user:{uid_a}",
                    "subject_b": f"telegram:user:{uid_b}",
                    "label": DIFFERENT_ACTOR,
                    "messages_a": user_short_msgs[uid_a],
                    "messages_b": user_short_msgs[uid_b],
                })
                if len(pairs) >= max_pairs:
                    break
            if len(pairs) >= max_pairs:
                break

    except Exception as e:
        logger.warning("Error building short message dataset: %s", e)

    return Dataset(
        name="short_message_benchmark",
        description=f"Short messages (<= {max_words} words) benchmark dataset",
        pairs=pairs,
        metadata={
            "max_words": max_words,
            "total_pairs": len(pairs),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def build_long_message_dataset(
    db_conn: Any,
    min_words: int = 100,
    max_pairs: int = 100,
) -> Dataset:
    """Construct benchmark dataset of long messages (>= min_words words).

    Evaluates attribution performance on high-information / long-form samples.

    Args:
        db_conn: SQLite connection, cursor, or SpectraDB instance.
        min_words: Minimum word count per message (default: 100).
        max_pairs: Maximum number of pairs to produce.

    Returns:
        Dataset with long message pairs (both positive same-actor and negative different-actor).
    """
    cur = _get_cursor(db_conn)
    pairs: List[Dict[str, Any]] = []

    if not _table_exists(cur, "messages"):
        return Dataset(
            name="long_message_benchmark",
            description=f"Long messages (>= {min_words} words) benchmark dataset",
            pairs=[],
            metadata={"min_words": min_words, "total_pairs": 0, "generated_at": datetime.now(timezone.utc).isoformat()},
        )

    try:
        # Fetch users
        cur.execute(
            """
            SELECT DISTINCT user_id FROM messages
            WHERE user_id IS NOT NULL AND content IS NOT NULL AND trim(content) != ''
            LIMIT ?
            """,
            (max_pairs * 2,),
        )
        user_ids = [r[0] for r in cur.fetchall()]

        # Collect long messages per user
        user_long_msgs: Dict[int, List[Dict[str, Any]]] = {}
        for uid in user_ids:
            l_msgs = _fetch_messages_for_user(cur, uid, min_words=min_words)
            if l_msgs:
                user_long_msgs[uid] = l_msgs

        # 1. Positive pairs: split long messages of the same user
        for uid, msgs in user_long_msgs.items():
            if len(msgs) >= 2:
                mid = len(msgs) // 2
                pairs.append({
                    "subject_a": f"telegram:user:{uid}:split1",
                    "subject_b": f"telegram:user:{uid}:split2",
                    "label": SAME_ACTOR,
                    "messages_a": msgs[:mid],
                    "messages_b": msgs[mid:],
                })
                if len(pairs) >= max_pairs // 2:
                    break

        # 2. Negative pairs: long messages from distinct users
        active_uids = list(user_long_msgs.keys())
        for i in range(len(active_uids)):
            for j in range(i + 1, len(active_uids)):
                uid_a, uid_b = active_uids[i], active_uids[j]
                pairs.append({
                    "subject_a": f"telegram:user:{uid_a}",
                    "subject_b": f"telegram:user:{uid_b}",
                    "label": DIFFERENT_ACTOR,
                    "messages_a": user_long_msgs[uid_a],
                    "messages_b": user_long_msgs[uid_b],
                })
                if len(pairs) >= max_pairs:
                    break
            if len(pairs) >= max_pairs:
                break

    except Exception as e:
        logger.warning("Error building long message dataset: %s", e)

    return Dataset(
        name="long_message_benchmark",
        description=f"Long messages (>= {min_words} words) benchmark dataset",
        pairs=pairs,
        metadata={
            "min_words": min_words,
            "total_pairs": len(pairs),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def build_bot_dataset(
    db_conn: Any,
    max_pairs: int = 100,
) -> Dataset:
    """Construct benchmark dataset of bot and automated messages.

    Identifies bot accounts from actor classification or user tags and builds
    evaluation pairs for automated content detection.

    Args:
        db_conn: SQLite connection, cursor, or SpectraDB instance.
        max_pairs: Maximum number of pairs to produce.

    Returns:
        Dataset with bot-related message pairs.
    """
    cur = _get_cursor(db_conn)
    pairs: List[Dict[str, Any]] = []

    if not _table_exists(cur, "messages"):
        return Dataset(
            name="bot_detection_benchmark",
            description="Bot and automated message benchmark dataset",
            pairs=[],
            metadata={"total_pairs": 0, "generated_at": datetime.now(timezone.utc).isoformat()},
        )

    try:
        bot_user_ids: List[int] = []

        # Check actor_classification
        if _table_exists(cur, "actor_classification"):
            cur.execute("SELECT user_id FROM actor_classification WHERE category = 'bot' OR category = 'BOT'")
            bot_user_ids.extend([r[0] for r in cur.fetchall()])

        # Check users table
        if _table_exists(cur, "users"):
            cur.execute(
                """
                SELECT id FROM users
                WHERE (username LIKE '%bot' OR tags LIKE '%bot%')
                """
            )
            bot_user_ids.extend([r[0] for r in cur.fetchall()])

        bot_user_ids = list(set(bot_user_ids))

        # Check human users
        cur.execute(
            """
            SELECT DISTINCT user_id FROM messages
            WHERE user_id IS NOT NULL AND content IS NOT NULL AND trim(content) != ''
            LIMIT ?
            """,
            (max_pairs * 2,),
        )
        all_user_ids = [r[0] for r in cur.fetchall()]
        human_user_ids = [u for u in all_user_ids if u not in bot_user_ids]

        # Bot vs Human pairs (label = DIFFERENT_ACTOR)
        for b_uid in bot_user_ids:
            b_msgs = _fetch_messages_for_user(cur, b_uid)
            if not b_msgs:
                continue
            for h_uid in human_user_ids:
                h_msgs = _fetch_messages_for_user(cur, h_uid)
                if not h_msgs:
                    continue
                pairs.append({
                    "subject_a": f"telegram:user:{b_uid}:bot",
                    "subject_b": f"telegram:user:{h_uid}:human",
                    "label": DIFFERENT_ACTOR,
                    "messages_a": b_msgs,
                    "messages_b": h_msgs,
                })
                if len(pairs) >= max_pairs:
                    break
            if len(pairs) >= max_pairs:
                break

    except Exception as e:
        logger.warning("Error building bot dataset: %s", e)

    return Dataset(
        name="bot_detection_benchmark",
        description="Bot and automated message benchmark dataset",
        pairs=pairs,
        metadata={
            "total_pairs": len(pairs),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


__all__ = [
    "Dataset",
    "SAME_ACTOR",
    "DIFFERENT_ACTOR",
    "build_same_actor_dataset",
    "build_different_actor_dataset",
    "build_style_change_dataset",
    "build_cross_channel_dataset",
    "build_forwarded_control_dataset",
    "build_short_message_dataset",
    "build_long_message_dataset",
    "build_bot_dataset",
]
