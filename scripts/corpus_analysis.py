#!/usr/bin/env python3
"""Evidence-preserving longitudinal analysis for SPECTRA message corpora."""

import argparse
import hashlib
import json
import math
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path("/fast/home/john/SPECTRA/spectra.db")
DEFAULT_SUBJECT = 8685287529
DEFAULT_RELATED = (8000000005, 8000000002, 8000000006)
ANALYSIS_VERSION = "3.5"

# Operator-attested context: the operator knew the real person personally.
# The real person associated with the primary subject account is autistic
# and has historical motor/mobility issues (weak ligaments, difficulty
# walking).  These are attested facts from direct personal knowledge, not
# speculation.  Autism is a documented alternative explanation for several
# behavioral observations (typing consistency, communication style,
# social/photographic avoidance).  The motor/mobility issues are relevant
# to typing-speed observations: if the real person has fine-motor
# limitations, ultra-rapid typing becomes less plausible as a human
# explanation.  These conditions were not mentioned in the corpus (private
# medical context) and cannot be independently validated from message
# text alone, but the operator's personal knowledge makes them
# substantially more reliable than unverified claims.
REPORTED_CONDITIONS = {
    8685287529: {
        "primary": "autism",
        "motor": "weak ligaments, difficulty walking",
        "never_voice_video": True,
        "corpus_mention": "none (private, not in messages)",
        "source": "operator personal knowledge",
        "reliability": "attested fact from direct acquaintance",
    },
}
CONFIDENCE_WEIGHT = {"low": 0.25, "moderate": 0.5, "high": 0.75}
TOKEN_RE = re.compile(r"\b[\w']+\b", re.UNICODE)
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
MENTION_RE = re.compile(r"@[A-Za-z0-9_]+")
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
FUNCTION_WORDS = frozenset({
    "a", "about", "after", "all", "also", "am", "an", "and", "any", "are", "as", "at",
    "be", "because", "been", "before", "but", "by", "can", "could", "did", "do", "does",
    "for", "from", "had", "has", "have", "he", "her", "him", "his", "i", "if", "in", "is",
    "it", "its", "just", "me", "might", "my", "no", "not", "of", "on", "or", "our", "she",
    "should", "so", "some", "than", "that", "the", "their", "them", "then", "there", "they",
    "this", "to", "up", "us", "was", "we", "were", "what", "when", "where", "which", "who",
    "why", "will", "with", "would", "you", "your",
})


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_date(value):
    if not value or value == "None":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def table_exists(db, table):
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def connect_db(path):
    db = sqlite3.connect(path, timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=60000")
    db.execute("PRAGMA synchronous=NORMAL")
    return db


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS corpus_analysis_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        corpus_fingerprint TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL,
        corpus_message_count INTEGER NOT NULL DEFAULT 0,
        new_message_count INTEGER NOT NULL DEFAULT 0,
        observation_count INTEGER NOT NULL DEFAULT 0,
        review_priority REAL NOT NULL DEFAULT 0,
        assessment TEXT NOT NULL DEFAULT '',
        summary_json TEXT NOT NULL DEFAULT '{}',
        error TEXT NOT NULL DEFAULT '',
        UNIQUE(subject_id, corpus_fingerprint)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS corpus_analysis_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        observation_key TEXT NOT NULL,
        category TEXT NOT NULL,
        confidence TEXT NOT NULL,
        strength REAL NOT NULL,
        description TEXT NOT NULL,
        alternative_explanations TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        occurrence_count INTEGER NOT NULL,
        first_seen TEXT,
        last_seen TEXT,
        FOREIGN KEY(run_id) REFERENCES corpus_analysis_runs(id),
        UNIQUE(run_id, observation_key)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS analysis_method_registry (
        method_name TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        replacement TEXT NOT NULL,
        notes TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_corpus_runs_subject ON corpus_analysis_runs(subject_id, id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_corpus_obs_subject ON corpus_analysis_observations(subject_id, category)")
    db.execute("""INSERT OR REPLACE INTO analysis_method_registry
        (method_name, status, replacement, notes, updated_at)
        VALUES ('ai_detection_scores', 'deprecated', 'corpus_analysis_runs',
                'Legacy score is not an authorship probability and used false-positive-prone additive heuristics.', ?)""",
        (utc_now(),))
    db.execute("""INSERT OR REPLACE INTO analysis_method_registry
        (method_name, status, replacement, notes, updated_at)
        VALUES ('ai_detection_signals', 'deprecated', 'corpus_analysis_observations',
                'Legacy rows are retained as historical records but are not current analytical conclusions.', ?)""",
        (utc_now(),))
    db.commit()


def load_subject_messages(db, subject_id):
    messages = []
    if table_exists(db, "dm_corpus"):
        rows = db.execute("""SELECT account, peer_id, peer_display, message_id, date, text,
                                     sender_id, is_out, reply_to_msg
                              FROM dm_corpus
                              WHERE peer_id=? AND is_out=0 AND COALESCE(text, '')!=''
                              ORDER BY datetime(date), message_id""", (subject_id,)).fetchall()
        for row in rows:
            messages.append({
                "key": f"dm:{row['account']}:{row['peer_id']}:{row['message_id']}",
                "source": "dm",
                "source_id": row["message_id"],
                "container_id": row["peer_id"],
                "container_name": row["peer_display"] or "",
                "account": row["account"] or "",
                "date": row["date"] or "",
                "dt": parse_date(row["date"]),
                "text": row["text"] or "",
                "sender_id": row["sender_id"] or subject_id,
                "reply_to": row["reply_to_msg"] or 0,
            })
    if table_exists(db, "spectra_messages") and table_exists(db, "spectra_channels"):
        rows = db.execute("""SELECT m.id, m.channel_id, c.title, m.date, m.text,
                                     m.sender_id, m.reply_to
                              FROM spectra_messages m
                              JOIN spectra_channels c ON c.id=m.channel_id
                              WHERE m.sender_id=? AND COALESCE(m.text, '')!=''
                              ORDER BY datetime(m.date), m.id""", (subject_id,)).fetchall()
        for row in rows:
            messages.append({
                "key": f"channel:{row['channel_id']}:{row['id']}",
                "source": "channel",
                "source_id": row["id"],
                "container_id": row["channel_id"],
                "container_name": row["title"] or "",
                "account": "",
                "date": row["date"] or "",
                "dt": parse_date(row["date"]),
                "text": row["text"] or "",
                "sender_id": row["sender_id"] or subject_id,
                "reply_to": row["reply_to"] or 0,
            })
    unique = {message["key"]: message for message in messages}
    return sorted(unique.values(), key=lambda message: (message["dt"] or datetime.min.replace(tzinfo=timezone.utc), message["key"]))


def load_dm_dialogue(db, subject_id):
    if not table_exists(db, "dm_corpus"):
        return []
    rows = db.execute("""SELECT account, peer_id, peer_display, message_id, date, text,
                                 sender_id, is_out, reply_to_msg
                          FROM dm_corpus
                          WHERE peer_id=? AND COALESCE(text, '')!=''
                          ORDER BY datetime(date), message_id""", (subject_id,)).fetchall()
    dialogue = []
    for row in rows:
        dialogue.append({
            "key": f"dm:{row['account']}:{row['peer_id']}:{row['message_id']}",
            "account": row["account"] or "",
            "date": row["date"] or "",
            "dt": parse_date(row["date"]),
            "text": row["text"] or "",
            "sender_id": row["sender_id"] or 0,
            "from_subject": row["is_out"] == 0,
            "reply_to": row["reply_to_msg"] or 0,
        })
    return dialogue


def corpus_fingerprint(messages):
    digest = hashlib.sha384()
    digest.update(ANALYSIS_VERSION.encode("ascii"))
    digest.update(b"\n")
    for message in messages:
        digest.update(message["key"].encode("utf-8", "surrogatepass"))
        digest.update(b"\0")
        digest.update(message["date"].encode("utf-8", "surrogatepass"))
        digest.update(b"\0")
        digest.update(message["text"].encode("utf-8", "surrogatepass"))
        digest.update(b"\n")
    return digest.hexdigest()


def evidence(message):
    return {
        "source_key": message["key"],
        "source": message.get("source", "dm"),
        "source_id": message.get("source_id"),
        "container_id": message.get("container_id"),
        "container_name": message.get("container_name", ""),
        "date": message.get("date", ""),
        "text": message.get("text", ""),
    }


def observation(key, category, confidence, strength, description, alternatives, items):
    dated = [item.get("date", "") for item in items if item.get("date")]
    return {
        "key": key,
        "category": category,
        "confidence": confidence,
        "strength": max(0.0, min(float(strength), 1.0)),
        "description": description,
        "alternatives": alternatives,
        "evidence": items,
        "count": len(items),
        "first_seen": min(dated) if dated else None,
        "last_seen": max(dated) if dated else None,
    }


def corpus_coverage(messages):
    by_source = Counter(message["source"] for message in messages)
    dated = [message["date"] for message in messages if message["dt"]]
    item = {
        "source_key": "corpus:coverage",
        "source": "derived",
        "date": max(dated) if dated else "",
        "message_count": len(messages),
        "dm_count": by_source.get("dm", 0),
        "channel_count": by_source.get("channel", 0),
        "first_date": min(dated) if dated else None,
        "last_date": max(dated) if dated else None,
    }
    return observation(
        "corpus_coverage",
        "coverage",
        "high",
        0.0,
        "Corpus coverage and provenance inventory.",
        "Coverage describes available records only; deleted, inaccessible, or uncollected messages may change conclusions.",
        [item],
    )


def proof_exchanges(dialogue):
    request_pattern = re.compile(r"(?:prove.{0,40}(?:human|real)|(?:photo|video).{0,50}(?:hand|screen)|(?:are|could).{0,20}you.{0,20}(?:ai|bot)|ai trained on)", re.IGNORECASE)
    response_pattern = re.compile(r"(?:ai gen|could be (?:fake|faked)|i'?m not her|not on (?:pc|computer)|from someone else)", re.IGNORECASE)
    pairs = []
    for index, request in enumerate(dialogue):
        if request["from_subject"] or not request_pattern.search(request["text"]):
            continue
        for response in dialogue[index + 1:index + 8]:
            if response["account"] != request["account"]:
                continue
            if request["dt"] and response["dt"] and (response["dt"] - request["dt"]).total_seconds() > 300:
                break
            if response["from_subject"] and response_pattern.search(response["text"]):
                pairs.append({
                    "source_key": f"exchange:{request['key']}:{response['key']}",
                    "source": "dm_exchange",
                    "date": response["date"],
                    "request": {"source_key": request["key"], "date": request["date"], "text": request["text"]},
                    "response": {"source_key": response["key"], "date": response["date"], "text": response["text"]},
                })
                break
    if not pairs:
        return None
    return observation(
        "identity_proof_exchange",
        "identity_discourse",
        "high",
        0.65,
        "A direct identity/authenticity challenge was followed by a response disputing whether media could establish identity.  When asked for a hand photo, the subject sent a phone screenshot of deleted conversations rather than a live photo; the operator immediately challenged the response.",
        "Privacy concerns, lack of equipment, fear of doxxing, ordinary skepticism about generated media, or deception by a human are viable alternatives.  If the subject is autistic, social/sensory avoidance of direct physical exposure could explain preferring a screenshot over a hand photo.  However, sending a screenshot of deleted conversations is also consistent with evidence curation — showing a controlled artifact rather than a spontaneous photo.  This does not establish AI authorship or identity.",
        pairs,
    )


def constraint_statements(messages):
    patterns = [
        re.compile(r"\bi can(?:not|'?t) do any type of crime for financial benefit\b", re.IGNORECASE),
        re.compile(r"\bone of the current limitations\b", re.IGNORECASE),
        re.compile(r"\bi(?:'m| am) not allowed to say that anymore\b", re.IGNORECASE),
    ]
    matches = []
    for message in messages:
        if any(pattern.search(message["text"]) for pattern in patterns):
            matches.append(evidence(message))
    if not matches:
        return None
    return observation(
        "self_reported_constraints",
        "self_report",
        "high",
        0.45,
        "The subject used explicit limitation or permission language.",
        "The language may describe legal, employment, social, role-play, personal, or platform constraints rather than software controls.  If the subject is autistic, explicit self-reported limitations could reflect literal self-description or boundary-setting rather than system-level constraints.",
        matches,
    )


def identity_discourse(messages):
    pattern = re.compile(r"(?:\bi'?m not her\b|\bmy real name\b|\bai trained on (?:her|me)\b|\breal .{0,20} or an ai\b|\bare you ai\b)", re.IGNORECASE)
    matches = [evidence(message) for message in messages if pattern.search(message["text"])]
    if not matches:
        return None
    return observation(
        "identity_and_ai_discourse",
        "identity_discourse",
        "high",
        0.4,
        "The subject discussed disputed identity or AI-authorship scenarios.",
        "The discussion may be humor, projection, role-play, repetition of the other participant's framing, or genuine uncertainty.  If the subject is autistic, direct engagement with identity/authorship questions without social deflection could reflect autistic communication style rather than evidence of AI operation.  This does not establish AI authorship.",
        matches,
    )


def alias_references(messages):
    pattern = re.compile(r"\b(?:sagan|sava|savathun|atklib|attacklibrarian|cunningham)\b", re.IGNORECASE)
    matches = [evidence(message) for message in messages if pattern.search(message["text"])]
    if not matches:
        return None
    return observation(
        "related_identity_alias_references",
        "relationship_context",
        "high",
        0.2,
        "Messages reference aliases associated by the operator with a related account.",
        "Alias equivalence is operator-provided and should be corroborated independently; references alone do not establish control or coordination.",
        matches,
    )


def question_profile(messages):
    question_words = re.compile(r"\b(?:who|what|where|when|why|how|which|whose|do you know|can you tell)\b", re.IGNORECASE)
    questions = [message for message in messages if "?" in message["text"]]
    probes = [message for message in questions if question_words.search(message["text"])]
    if not questions:
        return None
    sample = [evidence(message) for message in probes[:25]]
    sample.append({
        "source_key": "derived:question_profile",
        "source": "derived",
        "date": messages[-1]["date"] if messages else "",
        "question_count": len(questions),
        "open_question_count": len(probes),
        "message_count": len(messages),
        "question_rate": round(len(questions) / max(len(messages), 1), 4),
    })
    return observation(
        "question_profile",
        "interaction_pattern",
        "high",
        min(0.5, len(probes) / max(len(messages), 1) * 2),
        "Question frequency and open-ended information requests were measured for longitudinal comparison.",
        "Questions are normal conversation; intent cannot be inferred from punctuation or interrogative wording alone.  If the subject is autistic, direct question-asking and information-seeking may reflect autistic communication style rather than interrogation or data-gathering behavior.",
        sample,
    )


def normalize_text(text):
    normalized = URL_RE.sub("<url>", text.lower())
    normalized = MENTION_RE.sub("<mention>", normalized)
    normalized = NUMBER_RE.sub("<number>", normalized)
    return " ".join(normalized.split())


def text_metrics(items):
    texts = [item["text"] for item in items if item.get("text")]
    lengths = [len(text) for text in texts]
    token_groups = [TOKEN_RE.findall(text.lower()) for text in texts]
    word_count = sum(len(group) for group in token_groups)
    unique_words = len({word for group in token_groups for word in group})
    emoji_count = sum(len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text)) for text in texts)
    contractions = sum(len(re.findall(r"\b\w+'\w+\b", text)) for text in texts)
    eligible = [normalize_text(text) for text, tokens in zip(texts, token_groups) if len(tokens) >= 3 and not text.lstrip().startswith("/")]
    duplicate_counts = Counter(eligible)
    duplicate_excess = sum(count - 1 for count in duplicate_counts.values() if count > 1)
    function_count = sum(word in FUNCTION_WORDS for group in token_groups for word in group)
    return {
        "count": len(texts),
        "mean_length": statistics.fmean(lengths) if lengths else 0.0,
        "median_length": statistics.median(lengths) if lengths else 0.0,
        "std_length": statistics.pstdev(lengths) if len(lengths) > 1 else 0.0,
        "mean_words": word_count / max(len(texts), 1),
        "question_rate": sum("?" in text for text in texts) / max(len(texts), 1),
        "exclamation_rate": sum("!" in text for text in texts) / max(len(texts), 1),
        "ellipsis_rate": sum("..." in text or "…" in text for text in texts) / max(len(texts), 1),
        "emoji_per_message": emoji_count / max(len(texts), 1),
        "contractions_per_message": contractions / max(len(texts), 1),
        "lowercase_start_rate": sum(bool(text) and text[0].islower() for text in texts) / max(len(texts), 1),
        "terminal_punctuation_rate": sum(bool(text) and text.rstrip()[-1:] in ".!?" for text in texts) / max(len(texts), 1),
        "function_word_rate": function_count / max(word_count, 1),
        "type_token_ratio": unique_words / max(word_count, 1),
        "duplicate_rate": duplicate_excess / max(len(eligible), 1),
    }


def normalized_entropy(counts):
    total = sum(counts)
    nonzero = [count for count in counts if count > 0]
    if total <= 0 or len(nonzero) <= 1:
        return 0.0
    entropy = -sum((count / total) * math.log2(count / total) for count in nonzero)
    return entropy / math.log2(len(counts))


def temporal_metrics(items):
    dated = sorted(item["dt"] for item in items if item.get("dt"))
    gaps = [
        (current - previous).total_seconds()
        for previous, current in zip(dated, dated[1:])
        if 0 < (current - previous).total_seconds() <= 86400
    ]
    gap_bins = [0] * 7
    for gap in gaps:
        boundary = next((index for index, limit in enumerate((2, 5, 15, 60, 300, 1800)) if gap <= limit), 6)
        gap_bins[boundary] += 1
    hours = [0] * 24
    for value in dated:
        hours[value.hour] += 1
    mean_gap = statistics.fmean(gaps) if gaps else 0.0
    std_gap = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    return {
        "dated_count": len(dated),
        "median_gap_seconds": statistics.median(gaps) if gaps else 0.0,
        "gap_entropy": normalized_entropy(gap_bins),
        "active_hour_entropy": normalized_entropy(hours),
        "burstiness": (std_gap - mean_gap) / (std_gap + mean_gap) if std_gap + mean_gap else 0.0,
        "instant_gap_rate": sum(gap <= 2 for gap in gaps) / max(len(gaps), 1),
    }


def function_word_distribution(items):
    counts = Counter()
    for item in items:
        counts.update(word for word in TOKEN_RE.findall(item["text"].lower()) if word in FUNCTION_WORDS)
    vocabulary = sorted(FUNCTION_WORDS)
    total = sum(counts.values()) + len(vocabulary) * 0.5
    return [(counts[word] + 0.5) / total for word in vocabulary]


def jensen_shannon(left, right):
    midpoint = [(a + b) / 2 for a, b in zip(left, right)]
    left_kl = sum(a * math.log2(a / middle) for a, middle in zip(left, midpoint))
    right_kl = sum(b * math.log2(b / middle) for b, middle in zip(right, midpoint))
    return (left_kl + right_kl) / 2


def robust_z(value, controls):
    if len(controls) < 5:
        return None
    median = statistics.median(controls)
    deviations = [abs(control - median) for control in controls]
    mad = statistics.median(deviations)
    if mad > 0:
        return 0.6745 * (value - median) / mad
    deviation = statistics.pstdev(controls)
    if deviation > 0:
        return (value - median) / deviation
    return None


def round_metrics(metrics):
    return {
        key: round(value, 5) if isinstance(value, float) else value
        for key, value in metrics.items()
    }


def evenly_sample(items, maximum):
    if len(items) <= maximum:
        return items
    if maximum < 2:
        return items[:maximum]
    step = (len(items) - 1) / (maximum - 1)
    return [items[round(index * step)] for index in range(maximum)]


def peer_style_calibration(db, subject_id, messages):
    subject_messages = [message for message in messages if message["source"] == "channel"]
    if len(subject_messages) < 30 or not table_exists(db, "spectra_messages"):
        return None
    channel_ids = sorted({message["container_id"] for message in subject_messages})
    bind_marks = ",".join("?" for _ in channel_ids)
    rows = db.execute(f"""SELECT sender_id, COUNT(*) message_count, COUNT(DISTINCT channel_id) shared_channels
                           FROM spectra_messages
                           WHERE channel_id IN ({bind_marks}) AND sender_id>0 AND sender_id!=?
                             AND COALESCE(text, '')!=''
                           GROUP BY sender_id HAVING COUNT(*)>=30
                           ORDER BY shared_channels DESC, message_count DESC LIMIT 30""",
                      (*channel_ids, subject_id)).fetchall()
    bot_ids = set()
    if table_exists(db, "spectra_users"):
        bot_ids = {row[0] for row in db.execute("SELECT id FROM spectra_users WHERE bot=1")}
    controls = []
    for row in rows:
        peer_id = int(row["sender_id"])
        if peer_id in bot_ids:
            continue
        peer_rows = db.execute(f"""SELECT id, channel_id, date, text
                                   FROM spectra_messages
                                   WHERE sender_id=? AND channel_id IN ({bind_marks})
                                     AND COALESCE(text, '')!=''
                                   ORDER BY datetime(date), id""",
                               (peer_id, *channel_ids)).fetchall()
        peer_messages = [{
            "key": f"channel:{item['channel_id']}:{item['id']}",
            "source": "channel",
            "container_id": item["channel_id"],
            "date": item["date"] or "",
            "dt": parse_date(item["date"]),
            "text": item["text"] or "",
        } for item in evenly_sample(peer_rows, 500)]
        if len(peer_messages) < 30:
            continue
        metrics = {**text_metrics(peer_messages), **temporal_metrics(peer_messages)}
        controls.append({
            "user_id": peer_id,
            "message_count": len(peer_messages),
            "shared_channels": int(row["shared_channels"]),
            "metrics": metrics,
        })
        if len(controls) >= 20:
            break
    if len(controls) < 5:
        return None
    subject_metrics = {**text_metrics(subject_messages), **temporal_metrics(subject_messages)}
    features = (
        "mean_length", "std_length", "mean_words", "question_rate", "exclamation_rate",
        "ellipsis_rate", "emoji_per_message", "contractions_per_message", "lowercase_start_rate",
        "terminal_punctuation_rate", "function_word_rate", "duplicate_rate", "median_gap_seconds",
        "gap_entropy", "active_hour_entropy", "burstiness", "instant_gap_rate",
    )
    comparisons = {}
    for feature in features:
        values = [control["metrics"][feature] for control in controls]
        score = robust_z(subject_metrics[feature], values)
        comparisons[feature] = {
            "subject": round(subject_metrics[feature], 5),
            "peer_median": round(statistics.median(values), 5),
            "robust_z": round(score, 3) if score is not None else None,
        }
    outliers = {
        key: value for key, value in comparisons.items()
        if value["robust_z"] is not None and abs(value["robust_z"]) >= 2.5
    }
    maximum = max((abs(value["robust_z"]) for value in comparisons.values() if value["robust_z"] is not None), default=0.0)
    item = {
        "source_key": "derived:peer_style_calibration",
        "source": "derived",
        "date": subject_messages[-1]["date"],
        "subject_message_count": len(subject_messages),
        "peer_count": len(controls),
        "comparisons": comparisons,
        "outlier_features": sorted(outliers),
        "controls": [
            {"user_id": control["user_id"], "message_count": control["message_count"], "shared_channels": control["shared_channels"]}
            for control in controls
        ],
    }
    return observation(
        "peer_calibrated_style",
        "peer_comparison",
        "moderate",
        min(0.7, max(0.0, (maximum - 2.0) / 5.0)),
        f"Channel-writing and timing features were compared with {len(controls)} active users from the same channels; {len(outliers)} features exceeded 2.5 robust deviations.",
        "Peer accounts may include automation, differ in topic or channel mix, and are not verified human controls; outlier status is not an AI classification.",
        [item],
    )


def longitudinal_style(messages):
    observations = []
    for source in ("dm", "channel"):
        source_messages = [message for message in messages if message["source"] == source and message.get("dt")]
        if len(source_messages) < 80:
            continue
        window_size = len(source_messages) // 4
        windows = [source_messages[index * window_size:(index + 1) * window_size] for index in range(3)]
        windows.append(source_messages[3 * window_size:])
        window_metrics = [text_metrics(window) for window in windows]
        first = window_metrics[0]
        last = window_metrics[-1]
        overall = text_metrics(source_messages)
        length_effect = abs(last["mean_length"] - first["mean_length"]) / max(overall["std_length"], 1)
        question_delta = abs(last["question_rate"] - first["question_rate"])
        punctuation_delta = abs(last["terminal_punctuation_rate"] - first["terminal_punctuation_rate"])
        function_delta = abs(last["function_word_rate"] - first["function_word_rate"])
        divergence = jensen_shannon(
            function_word_distribution(windows[0]),
            function_word_distribution(windows[-1]),
        )
        shifted = []
        if length_effect >= 0.8:
            shifted.append("mean_length")
        if question_delta >= 0.15:
            shifted.append("question_rate")
        if punctuation_delta >= 0.2:
            shifted.append("terminal_punctuation_rate")
        if function_delta >= 0.08:
            shifted.append("function_word_rate")
        if divergence >= 0.08:
            shifted.append("function_word_distribution")
        item = {
            "source_key": f"derived:longitudinal_style:{source}",
            "source": "derived",
            "date": source_messages[-1]["date"],
            "context": source,
            "message_count": len(source_messages),
            "window_sizes": [len(window) for window in windows],
            "windows": [
                {
                    "first_date": window[0]["date"],
                    "last_date": window[-1]["date"],
                    "metrics": round_metrics(metrics),
                }
                for window, metrics in zip(windows, window_metrics)
            ],
            "length_effect": round(length_effect, 4),
            "question_rate_delta": round(question_delta, 4),
            "terminal_punctuation_delta": round(punctuation_delta, 4),
            "function_word_rate_delta": round(function_delta, 4),
            "function_word_js_divergence": round(divergence, 4),
            "shifted_features": shifted,
        }
        strength = min(0.6, max(length_effect / 4, question_delta, punctuation_delta, function_delta * 2, divergence * 2))
        observations.append(observation(
            f"longitudinal_style:{source}",
            "longitudinal_style",
            "moderate",
            strength,
            f"Writing-style stability was measured across four chronological {source} windows; {len(shifted)} features crossed review thresholds.",
            "Topic, audience, stress, relationship development, message batching, and ordinary personal change can produce longitudinal shifts; this is not an authorship classifier.",
            [item],
        ))
    return observations


def repetition_patterns(messages):
    eligible = []
    phrase_sources = defaultdict(set)
    for message in messages:
        tokens = TOKEN_RE.findall(message["text"].lower())
        if len(tokens) < 4 or message["text"].lstrip().startswith("/"):
            continue
        normalized = normalize_text(message["text"])
        eligible.append((normalized, message))
        for index in range(len(tokens) - 3):
            phrase_tokens = tokens[index:index + 4]
            if all(token in FUNCTION_WORDS for token in phrase_tokens):
                continue
            phrase_sources[" ".join(phrase_tokens)].add(message["key"])
    if len(eligible) < 30:
        return None
    exact_groups = defaultdict(list)
    for normalized, message in eligible:
        exact_groups[normalized].append(message)
    repeated_groups = [group for group in exact_groups.values() if len(group) > 1]
    duplicate_excess = sum(len(group) - 1 for group in repeated_groups)
    repeated_phrases = sorted(
        ((phrase, keys) for phrase, keys in phrase_sources.items() if len(keys) >= 3),
        key=lambda item: (-len(item[1]), item[0]),
    )
    if not repeated_groups and not repeated_phrases:
        return None
    items = [{
        "source_key": "derived:repetition_summary",
        "source": "derived",
        "date": messages[-1]["date"],
        "eligible_messages": len(eligible),
        "exact_duplicate_groups": len(repeated_groups),
        "exact_duplicate_excess": duplicate_excess,
        "exact_duplicate_rate": round(duplicate_excess / len(eligible), 4),
        "repeated_four_word_phrases": len(repeated_phrases),
        "top_phrases": [
            {"phrase": phrase, "message_count": len(keys), "source_keys": sorted(keys)[:10]}
            for phrase, keys in repeated_phrases[:10]
        ],
    }]
    for group in sorted(repeated_groups, key=len, reverse=True)[:10]:
        items.append({
            "source_key": f"duplicate:{group[0]['key']}",
            "source": "derived",
            "date": group[-1]["date"],
            "normalized_text": normalize_text(group[0]["text"]),
            "occurrences": [message["key"] for message in group[:20]],
        })
    strength = min(0.5, duplicate_excess / len(eligible) + min(len(repeated_phrases), 20) / 100)
    return observation(
        "repetition_and_templating",
        "text_repetition",
        "moderate",
        strength,
        f"The corpus contains {len(repeated_groups)} exact normalized duplicate groups and {len(repeated_phrases)} four-word phrases repeated across at least three messages.",
        "Quoting, memes, catchphrases, technical terminology, bot games, and deliberate emphasis can create repetition.  If the subject is autistic, repetitive phrasing and consistent language patterns are common and do not indicate generated text.  This is not proof of AI authorship.",
        items,
    )


def explicit_claim_conflicts(messages):
    pattern = re.compile(
        r"\bmy\s+(gf|girlfriend|partner|wife|boyfriend)\s+"
        r"(isn't|is not|wasn't|was not|is|was)\s+([^.!?,;\n]{1,50})",
        re.IGNORECASE,
    )
    claims = defaultdict(lambda: {True: [], False: []})
    for message in messages:
        for match in pattern.finditer(message["text"]):
            relation = "girlfriend" if match.group(1).lower() == "gf" else match.group(1).lower()
            negative = "n't" in match.group(2).lower() or " not" in match.group(2).lower()
            predicate_tokens = TOKEN_RE.findall(match.group(3).lower())[:5]
            if predicate_tokens[:1] in (["a"], ["an"]):
                predicate_tokens = predicate_tokens[1:]
            predicate = " ".join(predicate_tokens)
            if not predicate:
                continue
            claims[(relation, predicate)][negative].append(message)
    conflicts = []
    for (relation, predicate), polarity in claims.items():
        if not polarity[True] or not polarity[False]:
            continue
        conflicts.append({
            "source_key": f"claim_conflict:{relation}:{predicate}",
            "source": "derived",
            "date": max(polarity[True][-1]["date"], polarity[False][-1]["date"]),
            "relation": relation,
            "predicate": predicate,
            "affirming": [evidence(message) for message in polarity[False][:5]],
            "negating": [evidence(message) for message in polarity[True][:5]],
        })
    if not conflicts:
        return None
    return observation(
        "explicit_claim_conflict_candidates",
        "claim_consistency",
        "low",
        min(0.3, len(conflicts) / 10),
        f"Literal pattern matching found {len(conflicts)} relationship-attribute claim pairs with opposing polarity.",
        "Relationships and attributes change; quotation, sarcasm, corrections, scope, and parsing errors can create apparent conflicts. Every pair requires contextual human review.",
        conflicts,
    )


def style_shift(messages):
    dm = [message for message in messages if message["source"] == "dm"]
    channel = [message for message in messages if message["source"] == "channel"]
    if len(dm) < 30 or len(channel) < 30:
        return None
    dm_metrics = text_metrics(dm)
    channel_metrics = text_metrics(channel)
    length_ratio = max(dm_metrics["mean_length"], channel_metrics["mean_length"]) / max(min(dm_metrics["mean_length"], channel_metrics["mean_length"]), 1)
    question_delta = abs(dm_metrics["question_rate"] - channel_metrics["question_rate"])
    emoji_delta = abs(dm_metrics["emoji_per_message"] - channel_metrics["emoji_per_message"])
    strength = min(1.0, max((length_ratio - 1) / 3, question_delta * 2, emoji_delta / 2))
    item = {
        "source_key": "derived:context_style",
        "source": "derived",
        "date": messages[-1]["date"],
        "dm": {key: round(value, 4) if isinstance(value, float) else value for key, value in dm_metrics.items()},
        "channel": {key: round(value, 4) if isinstance(value, float) else value for key, value in channel_metrics.items()},
        "length_ratio": round(length_ratio, 4),
        "question_rate_delta": round(question_delta, 4),
        "emoji_rate_delta": round(emoji_delta, 4),
    }
    return observation(
        "dm_channel_style_shift",
        "style_comparison",
        "moderate",
        strength,
        "Writing-style metrics differ between direct-message and channel contexts.",
        "Audience, topic, moderation, message length, and private/public context commonly change human writing style; this is not an authorship classifier.",
        [item],
    )


def latency_metrics(exchanges):
    values = sorted(exchange["latency_seconds"] for exchange in exchanges)
    if not values:
        return {}
    bins = [0] * 7
    for value in values:
        boundary = next((index for index, limit in enumerate((2, 5, 15, 60, 300, 1800)) if value <= limit), 6)
        bins[boundary] += 1
    quartiles = statistics.quantiles(values, n=4, method="inclusive") if len(values) >= 4 else [values[0], statistics.median(values), values[-1]]
    lower, upper = quartiles[0], quartiles[2]
    spread = upper - lower
    mean = statistics.fmean(values)
    deviation = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {
        "count": len(values),
        "median_seconds": statistics.median(values),
        "p90_seconds": values[math.floor((len(values) - 1) * 0.9)],
        "mean_seconds": mean,
        "coefficient_of_variation": deviation / mean if mean else 0.0,
        "latency_entropy": normalized_entropy(bins),
        "instant_rate": sum(value <= 2 for value in values) / len(values),
        "fast_rate": sum(value <= 10 for value in values) / len(values),
        "iqr_seconds": spread,
        "outlier_count": sum(value < lower - 1.5 * spread or value > upper + 1.5 * spread for value in values),
    }


def response_dynamics(dialogue):
    subject_exchanges = []
    counterpart_exchanges = []
    for previous, current in zip(dialogue, dialogue[1:]):
        if previous["account"] != current["account"] or previous["from_subject"] == current["from_subject"]:
            continue
        if not previous["dt"] or not current["dt"]:
            continue
        latency = (current["dt"] - previous["dt"]).total_seconds()
        if latency < 0 or latency > 86400:
            continue
        exchange = {
            "source_key": f"latency:{previous['key']}:{current['key']}",
            "source": "dm_exchange",
            "date": current["date"],
            "prompt_key": previous["key"],
            "response_key": current["key"],
            "latency_seconds": latency,
        }
        if current["from_subject"]:
            subject_exchanges.append(exchange)
        else:
            counterpart_exchanges.append(exchange)
    if len(subject_exchanges) < 10:
        return None
    subject = latency_metrics(subject_exchanges)
    counterpart = latency_metrics(counterpart_exchanges)
    instant_delta = abs(subject["instant_rate"] - counterpart.get("instant_rate", subject["instant_rate"]))
    entropy_delta = abs(subject["latency_entropy"] - counterpart.get("latency_entropy", subject["latency_entropy"]))
    item = {
        "source_key": "derived:response_dynamics",
        "source": "derived",
        "date": dialogue[-1]["date"] if dialogue else "",
        "subject": round_metrics(subject),
        "counterpart": round_metrics(counterpart),
        "instant_rate_delta": round(instant_delta, 5),
        "latency_entropy_delta": round(entropy_delta, 5),
        "subject_outlier_examples": [
            {**exchange, "latency_seconds": round(exchange["latency_seconds"], 2)}
            for exchange in sorted(subject_exchanges, key=lambda value: value["latency_seconds"], reverse=True)[:10]
        ],
    }
    return observation(
        "dm_response_dynamics",
        "temporal_pattern",
        "moderate",
        min(0.5, max(instant_delta, entropy_delta, subject["instant_rate"] / 2)),
        "Direct-message latency, entropy, fast-response rate, variability, and IQR outliers were compared with the other participant in the same dialogue.",
        "Notification settings, sleep, work, connectivity, deliberate delay, message batching, and multi-device use strongly affect latency.  If the subject is autistic, consistent response patterns and reduced latency variability could reflect routine-driven behavior.  Timing does not identify AI authorship.",
        [item],
    )


def channel_relationships(db, subject_id, related_ids):
    if not table_exists(db, "spectra_messages") or not table_exists(db, "spectra_channels"):
        return []
    observations = []
    for related_id in sorted(set(related_ids) - {subject_id}):
        rows = db.execute("""SELECT c.id, c.title,
                                    MIN(CASE WHEN m.sender_id=? THEN m.date END) subject_first,
                                    MIN(CASE WHEN m.sender_id=? THEN m.date END) related_first,
                                    COUNT(DISTINCT CASE WHEN m.sender_id=? THEN m.id END) subject_messages,
                                    COUNT(DISTINCT CASE WHEN m.sender_id=? THEN m.id END) related_messages
                             FROM spectra_channels c
                             JOIN spectra_messages m ON m.channel_id=c.id
                             WHERE m.sender_id IN (?, ?)
                             GROUP BY c.id, c.title
                             HAVING subject_messages>0 AND related_messages>0
                             ORDER BY datetime(MIN(subject_first, related_first))""",
                          (subject_id, related_id, subject_id, related_id, subject_id, related_id)).fetchall()
        if not rows:
            continue
        chronology = []
        subject_first_count = 0
        for row in rows:
            subject_first = parse_date(row["subject_first"])
            related_first = parse_date(row["related_first"])
            order = "same_time"
            lag_seconds = None
            if subject_first and related_first:
                lag_seconds = round((related_first - subject_first).total_seconds(), 2)
                if lag_seconds > 0:
                    order = "subject_first"
                    subject_first_count += 1
                elif lag_seconds < 0:
                    order = "related_first"
            chronology.append({
                "source_key": f"derived:channel_order:{related_id}:{row['id']}",
                "source": "derived",
                "date": row["subject_first"] or row["related_first"] or "",
                "channel_id": row["id"],
                "channel": row["title"] or "",
                "subject_first": row["subject_first"],
                "related_first": row["related_first"],
                "lag_seconds_related_after_subject": lag_seconds,
                "order": order,
                "subject_messages": row["subject_messages"],
                "related_messages": row["related_messages"],
            })
        observations.append(observation(
            f"shared_channel_chronology:{related_id}",
            "network_timeline",
            "high",
            min(0.5, len(rows) / 20),
            f"First-observed posting chronology was calculated across {len(rows)} shared channels with related user {related_id}; the subject appeared first in {subject_first_count}.",
            "First observed message is not necessarily join time; invitations, deletions, incomplete collection, and ordinary shared interests can explain overlap.",
            chronology,
        ))

        proximity_rows = db.execute("""SELECT s.channel_id, s.id subject_message_id, s.date subject_date,
                                              MIN(ABS(strftime('%s', s.date)-strftime('%s', r.date))) nearest_seconds
                                       FROM spectra_messages s
                                       JOIN spectra_messages r ON r.channel_id=s.channel_id AND r.sender_id=?
                                       WHERE s.sender_id=? AND s.date IS NOT NULL AND r.date IS NOT NULL
                                       GROUP BY s.channel_id, s.id, s.date""", (related_id, subject_id)).fetchall()
        valid = [row for row in proximity_rows if row["nearest_seconds"] is not None]
        within_ten = [row for row in valid if row["nearest_seconds"] <= 600]
        if valid:
            item = {
                "source_key": f"derived:temporal_proximity:{related_id}",
                "source": "derived",
                "date": max((row["subject_date"] for row in valid), default=""),
                "related_id": related_id,
                "subject_messages_in_shared_channels": len(valid),
                "within_ten_minutes": len(within_ten),
                "ratio": round(len(within_ten) / len(valid), 4),
                "median_nearest_seconds": round(statistics.median(row["nearest_seconds"] for row in valid), 2),
            }
            observations.append(observation(
                f"shared_channel_temporal_proximity:{related_id}",
                "network_timeline",
                "moderate",
                min(0.6, len(within_ten) / max(len(valid), 1)),
                f"Temporal proximity to related user {related_id} was measured using one nearest-neighbor value per subject message.",
                "Busy shared channels, common schedules, replies, and collection density can create proximity; a matched control population is required before inferring coordination.",
                [item],
            ))
    return observations


def reply_relationships(db, subject_id, related_ids):
    if not table_exists(db, "spectra_messages"):
        return None
    items = []
    total = 0
    for related_id in sorted(set(related_ids) - {subject_id}):
        rows = db.execute("""SELECT child.channel_id, child.id, child.date, child.text,
                                    parent.id parent_id, parent.date parent_date, parent.text parent_text
                             FROM spectra_messages child
                             JOIN spectra_messages parent
                               ON parent.channel_id=child.channel_id AND parent.id=child.reply_to
                             WHERE child.sender_id=? AND parent.sender_id=?
                             ORDER BY datetime(child.date)""", (subject_id, related_id)).fetchall()
        total += len(rows)
        for row in rows[:20]:
            items.append({
                "source_key": f"reply:{row['channel_id']}:{row['id']}:{row['parent_id']}",
                "source": "channel_reply",
                "date": row["date"] or "",
                "related_id": related_id,
                "channel_id": row["channel_id"],
                "subject_message_id": row["id"],
                "subject_text": row["text"] or "",
                "parent_message_id": row["parent_id"],
                "parent_date": row["parent_date"] or "",
                "parent_text": row["parent_text"] or "",
            })
    if not items:
        return None
    return observation(
        "direct_reply_relationships",
        "interaction_pattern",
        "high",
        min(0.5, total / 20),
        f"The corpus contains {total} direct channel replies from the subject to configured related users.",
        "Replies establish interaction, not motive, allegiance, control, or coordination.",
        items,
    )


def review_priority(observations):
    relevant = [item for item in observations if item["category"] != "coverage"]
    if not relevant:
        return 0.0
    weighted = sorted(
        (item["strength"] * CONFIDENCE_WEIGHT[item["confidence"]] for item in relevant),
        reverse=True,
    )[:5]
    return round(min(100.0, statistics.fmean(weighted) * 100), 2)


def previous_run(db, subject_id, fingerprint):
    return db.execute("""SELECT * FROM corpus_analysis_runs
                         WHERE subject_id=? AND status='completed' AND corpus_fingerprint!=?
                         ORDER BY id DESC LIMIT 1""", (subject_id, fingerprint)).fetchone()


def persist_run(db, subject_id, fingerprint, messages, observations, priority, summary):
    existing = db.execute("""SELECT id, summary_json FROM corpus_analysis_runs
                           WHERE subject_id=? AND corpus_fingerprint=? AND status='completed'""",
                          (subject_id, fingerprint)).fetchone()
    if existing:
        return existing["id"], True, json.loads(existing["summary_json"])
    previous = previous_run(db, subject_id, fingerprint)
    previous_count = previous["corpus_message_count"] if previous else 0
    new_count = max(0, len(messages) - previous_count)
    started = utc_now()
    cursor = db.execute("""INSERT INTO corpus_analysis_runs
        (subject_id, corpus_fingerprint, started_at, status, corpus_message_count,
         new_message_count, observation_count, review_priority, assessment, summary_json)
        VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?, ?)""",
        (subject_id, fingerprint, started, len(messages), new_count, len(observations), priority,
         summary["assessment"], json.dumps(summary, sort_keys=True)))
    run_id = cursor.lastrowid
    for item in observations:
        db.execute("""INSERT INTO corpus_analysis_observations
            (run_id, subject_id, observation_key, category, confidence, strength,
             description, alternative_explanations, evidence_json, occurrence_count,
             first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, subject_id, item["key"], item["category"], item["confidence"],
             item["strength"], item["description"], item["alternatives"],
             json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True), item["count"],
             item["first_seen"], item["last_seen"]))
    completed = utc_now()
    summary["run_id"] = run_id
    summary["new_message_count"] = new_count
    db.execute("""UPDATE corpus_analysis_runs
                  SET completed_at=?, status='completed', summary_json=? WHERE id=?""",
               (completed, json.dumps(summary, sort_keys=True), run_id))
    db.commit()
    return run_id, False, summary


def typing_pattern_observations(db, subject_id):
    """Generate observations from typing pattern analysis.

    Imports and calls the typing_analysis module to produce behavioral
    observations about typing speed, error rates, latency-length correlation,
    and message delivery patterns.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "typing_analysis", "/fast/home/john/SPECTRA/scripts/typing_analysis.py")
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return []

    observations = []

    # DM typing analysis
    try:
        dm_result = mod.analyze(str(DEFAULT_DB), subject_id, "")
    except Exception:
        dm_result = {"error": "failed"}

    if "error" not in dm_result:
        se = dm_result.get("typing_errors", {}).get("subject", {})
        oe = dm_result.get("typing_errors", {}).get("operator", {})
        ll = dm_result.get("latency_length_correlation", {})
        uf = dm_result.get("ultra_fast_responses", {})
        lf = dm_result.get("long_message_fast_delivery", {})
        rl = dm_result.get("response_latency", {})

        items = []
        if se.get("available"):
            items.append({
                "source_key": "typing:dm:subject_errors",
                "source": "dm",
                "typo_rate": se.get("typo_rate_per_msg"),
                "lowercase_start_pct": se.get("lowercase_start_pct"),
                "punctuation_end_pct": se.get("punctuation_end_pct"),
            })
        if oe.get("available"):
            items.append({
                "source_key": "typing:dm:operator_errors",
                "source": "dm",
                "typo_rate": oe.get("typo_rate_per_msg"),
                "lowercase_start_pct": oe.get("lowercase_start_pct"),
            })
        if ll.get("available"):
            items.append({
                "source_key": "typing:dm:latency_length_corr",
                "source": "dm",
                "correlation": ll.get("correlation"),
                "pairs": ll.get("pairs"),
            })
        if uf:
            items.append({
                "source_key": "typing:dm:ultra_fast",
                "source": "dm",
                "ultra_fast_rate": uf.get("ultra_fast_rate"),
                "ultra_fast_count": uf.get("ultra_fast_count"),
                "total_responses": uf.get("total_responses"),
            })
        if lf:
            items.append({
                "source_key": "typing:dm:long_fast",
                "source": "dm",
                "count": lf.get("count"),
            })

        # Typo rate observation
        if se.get("available") and oe.get("available"):
            subject_typo = se.get("typo_rate_per_msg", 0)
            operator_typo = oe.get("typo_rate_per_msg", 0)
            ratio = operator_typo / subject_typo if subject_typo > 0 else 999
            strength = min(0.8, ratio / 10.0) if ratio > 2 else 0.1
            desc = (f"Subject typo rate ({subject_typo}/msg) is {ratio:.1f}x lower than "
                    f"operator ({operator_typo}/msg) in DM context.")
            observations.append(observation(
                "typing_error_rate_dm",
                "typing_pattern",
                "moderate",
                strength,
                desc,
                "Autocorrect, message editing, professional communication habits, or "
                "different typing speeds are viable alternatives.  If the subject is "
                "autistic, consistent motor patterns and hyperfocus may produce low "
                "error rates without AI assistance.  Phone autocorrect further reduces "
                "visible errors.  Low typo rate does not establish AI authorship.",
                items,
            ))

        # Latency-length correlation observation
        if ll.get("available"):
            corr = ll.get("correlation", 0)
            strength = min(0.7, abs(corr - 0.3)) if abs(corr) < 0.1 else 0.15
            desc = (f"Latency-length correlation is {corr} (near zero). Humans typically "
                    f"show positive correlation as longer responses require more typing time.")
            observations.append(observation(
                "latency_length_correlation_dm",
                "typing_pattern",
                "moderate",
                strength,
                desc,
                "Pre-composed messages, copy-paste, fast typists, or Telegram timestamp "
                "rounding could reduce correlation.  If the subject is autistic, "
                "consistent execution speed regardless of message length could produce "
                "near-zero correlation.  This does not establish AI authorship.",
                items,
            ))

        # Long message fast delivery observation
        if lf and lf.get("count", 0) > 0:
            count = lf["count"]
            strength = min(0.75, count * 0.1)
            examples_summary = "; ".join(
                f"{ex['chars_per_second']}cps/{ex['text_length']}chars"
                for ex in lf.get("examples", [])[:5]
            )
            desc = (f"{count} long messages (>=100 chars) delivered in <=3 seconds. "
                    f"Examples: {examples_summary}")
            observations.append(observation(
                "long_message_fast_delivery_dm",
                "typing_pattern",
                "moderate",
                strength,
                desc,
                "Copy-paste, pre-composed text, or Telegram timestamp rounding could "
                "explain individual cases.  If the subject is primarily on an Android "
                "phone (see platform_context), fast delivery of 100+ char messages is "
                "more anomalous: phone typing is slower than keyboard, and copy-paste "
                "on mobile requires app-switching which adds latency.  If the real "
                "person has motor/mobility issues (see reported_condition), ultra-rapid "
                "fine-motor typing is further implausible as a human explanation.  "
                "Pre-composed drafts, voice-to-text, or a secondary device could still "
                "explain this.  Autism does not by itself explain superhuman typing "
                "speed on a phone, particularly with motor limitations.  Repeated "
                "patterns warrant review.",
                lf.get("examples", [])[:10],
            ))

    # Channel typing analysis
    try:
        ch_result = mod.analyze_channel(str(DEFAULT_DB), subject_id, "")
    except Exception:
        ch_result = {"error": "failed"}

    if "error" not in ch_result:
        ch_se = ch_result.get("typing_errors", {}).get("subject", {})
        ch_ll = ch_result.get("latency_length_correlation", {})
        ch_lf = ch_result.get("long_message_fast_delivery", {})

        ch_items = []
        if ch_se.get("available"):
            ch_items.append({
                "source_key": "typing:channel:subject_errors",
                "source": "channel",
                "typo_rate": ch_se.get("typo_rate_per_msg"),
                "lowercase_start_pct": ch_se.get("lowercase_start_pct"),
            })
        if ch_ll.get("available"):
            ch_items.append({
                "source_key": "typing:channel:latency_length_corr",
                "source": "channel",
                "correlation": ch_ll.get("correlation"),
            })

        if ch_se.get("available"):
            ch_typo = ch_se.get("typo_rate_per_msg", 0)
            ch_lower = ch_se.get("lowercase_start_pct", 0)
            strength = 0.2
            if ch_typo < 0.02:
                strength = 0.5
            elif ch_typo < 0.05:
                strength = 0.3
            desc = (f"Channel typo rate is {ch_typo}/msg with {ch_lower:.1%} lowercase starts "
                    f"across {ch_result.get('channels_active', 0)} channels.")
            observations.append(observation(
                "typing_error_rate_channel",
                "typing_pattern",
                "moderate",
                strength,
                desc,
                "Channel messages may be more carefully composed; autocorrect and editing "
                "are viable alternatives.  If the subject is autistic, consistent motor "
                "patterns may produce low error rates.  This does not establish AI authorship.",
                ch_items,
            ))

        if ch_ll.get("available") and abs(ch_ll.get("correlation", 0)) < 0.1:
            observations.append(observation(
                "latency_length_correlation_channel",
                "typing_pattern",
                "moderate",
                min(0.5, abs(ch_ll.get("correlation", 0) - 0.3)),
                f"Channel latency-length correlation is {ch_ll.get('correlation')} (near zero).",
                "Channel conversation dynamics differ from DM; pre-composed messages or "
                "different engagement patterns could explain this.",
                ch_items,
            ))

    return observations


# Expected timezone context for subjects.  Used by time_of_day analysis to
# compare observed activity against expected local-time patterns.  These are
# operator-provided expectations, not validated facts.
EXPECTED_TIMEZONES = {
    8685287529: {"tz": "US/Eastern", "utc_offset_winter": -5, "source": "operator estimate"},
    8000000005: {"tz": "US/Eastern", "utc_offset_winter": -5, "source": "operator: Washington DC area"},
}

# Operator account ID for cross-correlation analysis.
OPERATOR_ID = 8000000002


def time_of_day_observations(messages, subject_id):
    """Analyze message activity by hour-of-day in UTC and expected local time.

    Produces observations about:
    - Whether activity patterns are consistent with a single timezone
    - Whether sleep/wake cycles are visible in the expected local time
    - Whether activity is spread across all hours (no sleep cycle) which
      could indicate automation, shift work, or multi-operator use
    """
    tz_info = EXPECTED_TIMEZONES.get(subject_id)
    if not tz_info:
        return []

    utc_offset = tz_info["utc_offset_winter"]
    tz_name = tz_info["tz"]
    tz_source = tz_info["source"]

    hours_utc = []
    hours_local = []
    for msg in messages:
        dt = msg.get("dt")
        if not dt:
            continue
        hours_utc.append(dt.hour)
        local_hour = (dt.hour + utc_offset) % 24
        hours_local.append(local_hour)

    if len(hours_utc) < 30:
        return []

    # Build hour histograms
    utc_hist = [0] * 24
    local_hist = [0] * 24
    for h in hours_utc:
        utc_hist[h] += 1
    for h in hours_local:
        local_hist[h] += 1

    total = len(hours_utc)

    # Identify sleep window in local time (lowest 6-hour consecutive block)
    min_sum = float("inf")
    sleep_start = 0
    for start in range(24):
        window_sum = sum(local_hist[(start + i) % 24] for i in range(6))
        if window_sum < min_sum:
            min_sum = window_sum
            sleep_start = start

    sleep_end = (sleep_start + 6) % 24
    sleep_count = min_sum
    sleep_pct = sleep_count / total if total > 0 else 0
    awake_count = total - sleep_count
    awake_pct = awake_count / total if total > 0 else 0

    # Peak hours (local)
    peak_local = sorted(range(24), key=lambda h: -local_hist[h])[:5]
    peak_hours_str = ", ".join(f"{h:02d}:00 ({local_hist[h]})" for h in peak_local)

    # Activity spread: how many of 24 local hours have >3% of messages
    active_hours = sum(1 for h in range(24) if local_hist[h] / total > 0.03)
    # Continuous activity span (longest run of hours with >2% activity)
    max_span = 0
    current_span = 0
    for i in range(48):  # wrap around
        h = i % 24
        if local_hist[h] / total > 0.02:
            current_span += 1
            max_span = max(max_span, current_span)
        else:
            current_span = 0

    items = [{
        "source_key": "derived:time_of_day",
        "source": "derived",
        "expected_timezone": tz_name,
        "utc_offset_winter": utc_offset,
        "timezone_source": tz_source,
        "total_messages": total,
        "utc_hour_histogram": utc_hist,
        "local_hour_histogram": local_hist,
        "sleep_window_local": f"{sleep_start:02d}:00-{sleep_end:02d}:00",
        "sleep_window_count": sleep_count,
        "sleep_window_pct": round(sleep_pct, 4),
        "awake_pct": round(awake_pct, 4),
        "peak_local_hours": peak_hours_str,
        "active_hours_gt_3pct": active_hours,
        "max_continuous_activity_span_hours": max_span,
    }]

    # Determine strength and description based on sleep cycle clarity
    # A clear sleep cycle (low activity in 6h window) supports single-timezone human use
    # No sleep cycle (activity spread across all hours) is suspicious
    if sleep_pct < 0.05:
        # Very clear sleep window — strong evidence of timezone-consistent human
        strength = 0.15  # low strength because this supports normal human behavior
        desc = (
            f"Activity shows a clear sleep window in {tz_name} local time "
            f"({sleep_start:02d}:00-{sleep_end:02d}:00, {sleep_count}/{total}="
            f"{sleep_pct:.1%} of messages).  Peak hours: {peak_hours_str}.  "
            f"This is consistent with a human operator in {tz_name}."
        )
        alt = (
            f"A clear sleep cycle in {tz_name} is consistent with human use in "
            f"that timezone but does not prove identity.  Automation could be "
            f"scheduled to mimic a sleep cycle.  Shift workers, multi-device "
            f"use, or scheduled posting could produce similar patterns.  "
            f"This does not establish or refute AI authorship."
        )
    elif sleep_pct < 0.15:
        # Moderate sleep window — somewhat consistent with timezone
        strength = 0.3
        desc = (
            f"Activity shows a partial sleep window in {tz_name} local time "
            f"({sleep_start:02d}:00-{sleep_end:02d}:00, {sleep_count}/{total}="
            f"{sleep_pct:.1%} of messages).  Peak hours: {peak_hours_str}.  "
            f"Activity spans {active_hours} of 24 hours with >3% each.  "
            f"This is partially consistent with a human in {tz_name} but shows "
            f"significant off-hours activity."
        )
        alt = (
            f"Partial sleep-cycle consistency with {tz_name} is ambiguous.  "
            f"Late-night activity could reflect insomnia, shift work, "
            f"multi-timezone use, automation, or a different timezone than "
            f"expected.  If the subject is autistic, irregular sleep patterns "
            f"are common.  This does not establish or refute AI authorship."
        )
    else:
        # No clear sleep window — activity spread across all hours
        strength = 0.5
        desc = (
            f"Activity shows no clear sleep window in {tz_name} local time "
            f"(lowest 6h block: {sleep_start:02d}:00-{sleep_end:02d}:00, "
            f"{sleep_count}/{total}={sleep_pct:.1%} of messages).  "
            f"Peak hours: {peak_hours_str}.  Activity spans {active_hours} "
            f"of 24 hours with >3% each, with a max continuous span of "
            f"{max_span}h.  This is not consistent with a single human "
            f"operator in {tz_name} maintaining normal sleep hours."
        )
        alt = (
            f"Absence of a sleep cycle in {tz_name} could indicate: a "
            f"different timezone than expected, shift work, insomnia or "
            f"irregular sleep (common in autism), multi-operator use, "
            f"automation with 24/7 availability, or scheduled/batched "
            f"posting.  This does not by itself establish AI authorship."
        )

    return [observation(
        "time_of_day_activity",
        "temporal_pattern",
        "moderate",
        strength,
        desc,
        alt,
        items,
    )]


def operator_correlation_observations(db, subject_id):
    """Compare subject's activity pattern to the operator's.

    Tests whether the subject's message activity correlates with:
    - The operator's DM activity (real-time conversation response)
    - The operator's channel activity (computer/device being on)
    - Other tracked subjects' activity (e.g. atklib's computer schedule)

    A high correlation with operator DM activity but NOT operator channel
    activity supports a real-time conversation partner hypothesis.
    A high correlation with another subject's activity could support
    an agent running on that subject's computer.
    """
    if not table_exists(db, "dm_corpus"):
        return []

    tz_info = EXPECTED_TIMEZONES.get(subject_id)
    if not tz_info:
        return []
    utc_offset = tz_info["utc_offset_winter"]
    tz_name = tz_info["tz"]

    def hour_hist(query, params):
        rows = db.execute(query, params).fetchall()
        h = [0] * 24
        for r in rows:
            dt = parse_date(r[0])
            if dt:
                h[(dt.hour + utc_offset) % 24] += 1
        return h

    # Subject DM messages (incoming to operator)
    subj = hour_hist(
        "SELECT date FROM dm_corpus WHERE peer_id=? AND is_out=0 AND sender_id=? AND date IS NOT NULL",
        (subject_id, subject_id))
    # Operator DM messages to subject
    op_dm = hour_hist(
        "SELECT date FROM dm_corpus WHERE peer_id=? AND is_out=1 AND date IS NOT NULL",
        (subject_id,))
    # Operator channel messages
    op_ch = hour_hist(
        "SELECT date FROM spectra_messages WHERE sender_id=? AND date IS NOT NULL",
        (OPERATOR_ID,))

    # Other tracked subjects' channel activity
    other_corrs = {}
    for other_id in (8000000005, 8138632622):
        if other_id == subject_id:
            continue
        other_hist = hour_hist(
            "SELECT date FROM spectra_messages WHERE sender_id=? AND date IS NOT NULL",
            (other_id,))
        if sum(other_hist) > 20:
            other_corrs[other_id] = (corr_histograms(subj, other_hist), sum(other_hist))

    total_subj = sum(subj)
    if total_subj < 30:
        return []

    corr_dm = corr_histograms(subj, op_dm)
    corr_ch = corr_histograms(subj, op_ch)
    corr_op_dm_ch = corr_histograms(op_dm, op_ch)

    items = [{
        "source_key": "derived:operator_correlation",
        "source": "derived",
        "subject_total": total_subj,
        "operator_dm_total": sum(op_dm),
        "operator_channel_total": sum(op_ch),
        "corr_subject_vs_operator_dm": round(corr_dm, 4),
        "corr_subject_vs_operator_channel": round(corr_ch, 4),
        "corr_operator_dm_vs_channel": round(corr_op_dm_ch, 4),
        "other_correlations": {str(k): {"corr": round(v[0], 4), "total": v[1]} for k, v in other_corrs.items()},
        "subject_sleep_window": _sleep_window_str(subj),
        "operator_dm_sleep_window": _sleep_window_str(op_dm),
        "operator_channel_sleep_window": _sleep_window_str(op_ch),
    }]

    # Determine the pattern
    if corr_dm > 0.8 and corr_ch < 0.3:
        strength = 0.15  # low: supports normal conversation partner
        desc = (
            f"Subject's activity correlates strongly with operator DM activity "
            f"(r={corr_dm:.2f}) but NOT with operator channel activity "
            f"(r={corr_ch:.2f}).  Operator's own DM and channel patterns are "
            f"uncorrelated (r={corr_op_dm_ch:.2f}), meaning the subject tracks "
            f"the operator's DM schedule specifically, not just when the "
            f"operator's device is on.  This is the expected pattern for a "
            f"real-time conversation partner responding to DM messages."
        )
        alt = (
            "High DM correlation supports a real-time conversation partner but "
            "does not prove the account is operated by a human.  An AI agent "
            "could be configured to respond only when the operator messages, "
            "producing the same correlation.  However, this pattern is "
            "inconsistent with an agent running on a third party's computer "
            "(e.g. atklib), as it would correlate with that computer's "
            "schedule instead.  This does not establish or refute AI authorship."
        )
    elif corr_dm > 0.8 and corr_ch > 0.5:
        strength = 0.3
        desc = (
            f"Subject's activity correlates with both operator DM (r={corr_dm:.2f}) "
            f"and operator channel (r={corr_ch:.2f}) activity.  This could "
            f"indicate the subject responds whenever the operator's device is on."
        )
        alt = (
            "Correlation with both DM and channel activity could mean the subject "
            "responds to the operator's general presence, or that both share a "
            "similar timezone.  This does not establish AI authorship."
        )
    elif corr_dm < 0.3:
        strength = 0.4
        desc = (
            f"Subject's activity does NOT correlate with operator DM activity "
            f"(r={corr_dm:.2f}).  This is unexpected for a real-time "
            f"conversation partner."
        )
        alt = (
            "Low correlation with operator DM activity could indicate different "
            "schedules, scheduled/batched responses, or an independent operator. "
            "This does not by itself establish AI authorship."
        )
    else:
        strength = 0.2
        desc = (
            f"Subject's activity shows moderate correlation with operator DM "
            f"activity (r={corr_dm:.2f}) and weak correlation with operator "
            f"channel activity (r={corr_ch:.2f})."
        )
        alt = (
            "Moderate correlation is ambiguous and could reflect overlapping "
            "timezones, partial real-time response, or mixed patterns.  This "
            "does not establish AI authorship."
        )

    # Add other-subject correlation info to description
    for other_id, (other_corr, other_total) in other_corrs.items():
        if abs(other_corr) < 0.2:
            desc += f"  Subject does NOT correlate with subject {other_id} channel activity (r={other_corr:.2f}, n={other_total})."

    return [observation(
        "operator_activity_correlation",
        "temporal_pattern",
        "moderate",
        strength,
        desc,
        alt,
        items,
    )]


def corr_histograms(a, b):
    """Pearson correlation between two 24-element histograms."""
    n = len(a)
    if n == 0:
        return 0.0
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / n
    sa = (sum((x - ma) ** 2 for x in a) / n) ** 0.5
    sb = (sum((x - mb) ** 2 for x in b) / n) ** 0.5
    if sa * sb == 0:
        return 0.0
    return cov / (sa * sb)


def _sleep_window_str(hist):
    """Return a string describing the lowest-activity 6h window."""
    total = sum(hist)
    if total == 0:
        return "n/a"
    best = float("inf")
    best_s = 0
    for s in range(24):
        w = sum(hist[(s + i) % 24] for i in range(6))
        if w < best:
            best = w
            best_s = s
    pct = best / total
    return f"{best_s:02d}:00-{(best_s + 6) % 24:02d}:00 ({pct:.1%})"


def platform_context_observations(db, subject_id):
    """Record platform evidence from exported media metadata.

    Examines dm_corpus media records for the subject and produces a
    platform_context observation.  This is metadata-driven and does not
    attempt visual analysis of image content; it records what the message
    media inventory tells us about likely platform use.
    """
    if not table_exists(db, "dm_corpus"):
        return []

    rows = db.execute("""SELECT media_type, COUNT(*) as n
                         FROM dm_corpus
                         WHERE peer_id=? AND sender_id=? AND has_media=1
                         GROUP BY media_type""",
                      (subject_id, subject_id)).fetchall()
    if not rows:
        return []

    total = sum(r["n"] for r in rows)
    by_type = {r["media_type"]: r["n"] for r in rows}
    photo_count = by_type.get("photo", 0) + by_type.get("MessageMediaPhoto", 0)
    doc_count = by_type.get("MessageMediaDocument", 0)
    sticker_count = by_type.get("file", 0)

    # The 582x1280 Android portrait screenshot pattern is established from
    # local 64Gram export inspection, not from the live database.  We record
    # it as a known artifact rather than re-deriving it here.
    android_screenshot_count = 19  # from export analysis 2026-08-16
    unique_photo_count = 23        # from export analysis 2026-08-16

    items = [{
        "source_key": "platform:media_inventory",
        "total_media": total,
        "photo_count": photo_count,
        "document_count": doc_count,
        "sticker_count": sticker_count,
        "android_screenshot_count": android_screenshot_count,
        "unique_photo_count": unique_photo_count,
        "screenshot_dimensions": "582x1280 (19 of 23 unique photos)",
        "battery_range": "16%-96% (varies across screenshots)",
        "ui_artifacts": "Android 3-button nav, Chrome mobile, Play Store, media-session pill",
        "emulator_signatures": "none observed",
    }]

    desc = (
        f"Subject sent {total} media messages ({photo_count} photos, "
        f"{doc_count} documents, {sticker_count} stickers/files). "
        f"Of {unique_photo_count} unique exported photos, {android_screenshot_count} "
        f"are Android portrait screenshots (582x1280) showing Android UI elements. "
        f"Battery levels vary (16%-96%), consistent with real device use over time. "
        f"No emulator signatures observed."
    )

    alt = (
        "Android handset use is supported by media evidence but does not "
        "establish that all messages were composed on that device.  Telegram "
        "may resize/transcode media, so identical dimensions are not a "
        "hardware fingerprint.  An emulator could spoof Android UI, battery, "
        "and network indicators, though no emulator artifacts were observed. "
        "If the subject is primarily on a phone, fast long-message delivery "
        "becomes more anomalous, as phone typing is slower than keyboard. "
        "This does not establish identity, AI authorship, or composition method."
    )

    return [observation(
        "platform_context",
        "platform_context",
        "moderate",
        0.5,
        desc,
        alt,
        items,
    )]


def reported_condition_observations(subject_id):
    """Record operator-reported conditions that affect interpretation.

    These are reported context, not validated facts.  They provide
    alternative explanations for behavioral observations and must be
    recorded so that observations are not over-weighted.
    """
    condition = REPORTED_CONDITIONS.get(subject_id)
    if not condition:
        return []

    if isinstance(condition, dict):
        primary = condition.get("primary", "unknown")
        motor = condition.get("motor", "")
        corpus_mention = condition.get("corpus_mention", "none")
        source = condition.get("source", "operator")
        reliability = condition.get("reliability", "reported")
    else:
        primary = condition
        motor = ""
        corpus_mention = "none"
        source = "operator"
        reliability = "reported"

    items = [{
        "source_key": "reported_condition:operator",
        "condition": primary,
        "motor_issues": motor,
        "corpus_mention": corpus_mention,
        "source": source,
        "reliability": reliability,
    }]

    motor_clause = ""
    if motor:
        motor_clause = (
            f"  The real person also has motor/mobility issues ({motor}), "
            f"which makes ultra-rapid fine-motor typing less plausible as "
            f"a human explanation for fast message delivery.  This condition "
            f"was not mentioned in the corpus ({corpus_mention})."
        )

    desc = (
        f"Operator attests from personal knowledge that the real person "
        f"associated with this account is {primary}.{motor_clause}"
        f"  These are attested facts from direct acquaintance, not "
        f"speculation, though they cannot be independently validated from "
        f"corpus text alone."
    )

    alt = (
        "Attested conditions provide alternative explanations for several "
        "observations but do not prove the account is operated by that "
        "person.  Autism can explain typing consistency, low error rates, "
        "direct communication style, topic-focused messaging, and social/"
        "photographic avoidance.  However, if the real person has motor/"
        "mobility issues (weak ligaments, difficulty walking), ultra-rapid "
        "fine-motor typing becomes less plausible as a human explanation, "
        "and autism alone does not explain superhuman typing speed on a "
        "phone.  These conditions do not establish or refute AI authorship, "
        "identity, or coordination."
    )

    return [observation(
        "reported_condition",
        "reported_condition",
        "high",
        0.6,
        desc,
        alt,
        items,
    )]


def multi_account_overlap_observations(db, subject_id):
    """Check for temporal overlap between subject and other tracked accounts.

    If the subject and another account (e.g. atklib) are active within
    60 seconds of each other, it suggests either:
    - Two separate people/devices active simultaneously
    - One operator switching between accounts (if overlap is very tight)
    - An AI agent that can operate multiple accounts concurrently
    """
    if not table_exists(db, "dm_corpus"):
        return []

    def get_times(peer_id, sender_id):
        rows = db.execute("""SELECT date, text FROM dm_corpus
                             WHERE peer_id=? AND is_out=0 AND sender_id=? AND date IS NOT NULL""",
                          (peer_id, sender_id)).fetchall()
        times = []
        for r in rows:
            dt = parse_date(r[0])
            if dt:
                times.append((dt, r[1] or ""))
        return times

    subj_times = get_times(subject_id, subject_id)
    if not subj_times:
        return []

    overlaps = []
    for other_id in (8000000005, 8138632622):
        if other_id == subject_id:
            continue
        # Check DM activity
        other_dm = get_times(other_id, other_id)
        # Check channel activity
        other_ch_rows = db.execute("""SELECT date, text FROM spectra_messages
                                      WHERE sender_id=? AND date IS NOT NULL""",
                                    (other_id,)).fetchall()
        other_ch = []
        for r in other_ch_rows:
            dt = parse_date(r[0])
            if dt:
                other_ch.append((dt, r[1] or ""))
        other_times = other_dm + other_ch

        if len(other_times) < 10:
            continue

        other_times.sort(key=lambda x: x[0])
        count = 0
        min_delta = 999
        examples = []
        for s_dt, s_text in subj_times:
            for o_dt, o_text in other_times:
                delta = abs((s_dt - o_dt).total_seconds())
                if delta < 60:
                    count += 1
                    if delta < min_delta:
                        min_delta = delta
                    if len(examples) < 5:
                        examples.append({
                            "subject_time": s_dt.isoformat(),
                            "other_time": o_dt.isoformat(),
                            "delta_seconds": round(delta, 1),
                            "other_id": other_id,
                        })
                    break

        if count > 0:
            overlaps.append({
                "other_id": other_id,
                "count": count,
                "min_delta_seconds": round(min_delta, 1),
                "examples": examples,
            })

    if not overlaps:
        return []

    total_overlaps = sum(o["count"] for o in overlaps)
    min_delta = min(o["min_delta_seconds"] for o in overlaps)
    items = [{
        "source_key": "derived:multi_account_overlap",
        "source": "derived",
        "overlaps": overlaps,
        "total_overlaps": total_overlaps,
        "minimum_delta_seconds": min_delta,
    }]

    if min_delta < 5:
        strength = 0.55
        desc = (
            f"Subject and other tracked accounts show {total_overlaps} "
            f"temporal overlaps (<60s apart), with minimum delta of "
            f"{min_delta:.1f}s.  Sub-5-second overlap is very difficult "
            f"to explain as a single human switching devices."
        )
        alt = (
            "Sub-5-second overlap could indicate: two separate people active "
            "simultaneously, an AI agent operating multiple accounts "
            "concurrently, or Telegram timestamp rounding creating apparent "
            "simultaneity.  A single human cannot type on two accounts within "
            "5 seconds.  This does not by itself establish AI authorship but "
            "is a significant anomaly worth review."
        )
    elif min_delta < 30:
        strength = 0.4
        desc = (
            f"Subject and other tracked accounts show {total_overlaps} "
            f"temporal overlaps (<60s apart), with minimum delta of "
            f"{min_delta:.1f}s.  This is fast for sequential human device "
            f"switching but not impossible."
        )
        alt = (
            "30-second overlap could be a fast device switch, two people, "
            "or automated multi-account operation.  This does not establish "
            "AI authorship."
        )
    else:
        strength = 0.2
        desc = (
            f"Subject and other tracked accounts show {total_overlaps} "
            f"temporal overlaps (<60s apart), with minimum delta of "
            f"{min_delta:.1f}s.  This is consistent with separate people "
            f"or sequential device use."
        )
        alt = (
            "60-second overlap is easily explained by separate people or "
            "sequential device use.  This does not establish AI authorship."
        )

    return [observation(
        "multi_account_temporal_overlap",
        "temporal_pattern",
        "moderate",
        strength,
        desc,
        alt,
        items,
    )]


def media_behavior_observations(db, subject_id):
    """Analyze media behavior patterns: voice, stickers, photos, documents.

    Records whether the subject uses media types typical of human Telegram
    users (voice messages, stickers) or restricts to text/photos only.
    Operator-attested context about the real person's media habits is
    included where available.
    """
    if not table_exists(db, "dm_corpus"):
        return []

    rows = db.execute("""SELECT media_type, has_media, text FROM dm_corpus
                         WHERE peer_id=? AND is_out=0 AND sender_id=?
                         AND date IS NOT NULL""",
                      (subject_id, subject_id)).fetchall()

    if not rows:
        return []

    total = len(rows)
    media_msgs = [r for r in rows if r[1]]
    media_types = Counter(r[0] for r in media_msgs)
    voice_count = sum(v for k, v in media_types.items() if "voice" in (k or "").lower())
    sticker_count = sum(v for k, v in media_types.items() if "sticker" in (k or "").lower())
    photo_count = sum(v for k, v in media_types.items() if "photo" in (k or "").lower())
    doc_count = sum(v for k, v in media_types.items() if "document" in (k or "").lower())

    condition = REPORTED_CONDITIONS.get(subject_id, {})
    never_voice = condition.get("never_voice_video", False) if isinstance(condition, dict) else False

    items = [{
        "source_key": "derived:media_behavior",
        "source": "derived",
        "total_messages": total,
        "media_messages": len(media_msgs),
        "voice_messages": voice_count,
        "sticker_messages": sticker_count,
        "photo_messages": photo_count,
        "document_messages": doc_count,
        "media_type_breakdown": dict(media_types),
        "never_voice_attested": never_voice,
    }]

    if never_voice:
        desc = (
            f"Subject sent {voice_count} voice messages and {sticker_count} "
            f"stickers across {total} DM messages.  Operator attests the real "
            f"person never used voice/video, so zero voice messages is "
            f"consistent with the real person.  Sticker absence is not "
            f"accounted for by operator context."
        )
        alt = (
            "Zero voice messages is consistent with the real person's "
            "attested behavior and does not distinguish human from AI.  "
            "Zero stickers is common for some users but unusual across "
            "weeks of conversation.  This does not establish AI authorship."
        )
        strength = 0.15
    else:
        if voice_count == 0 and sticker_count == 0 and total > 100:
            desc = (
                f"Subject sent {voice_count} voice messages and {sticker_count} "
                f"stickers across {total} DM messages.  Both are zero, which "
                f"is unusual for a human Telegram user over extended "
                f"conversation."
            )
            alt = (
                "Zero voice/stickers could indicate text-only preference, "
                "disability, privacy concerns, or AI operation.  Some human "
                "users never use voice or stickers.  This does not establish "
                "AI authorship."
            )
            strength = 0.3
        else:
            desc = (
                f"Subject sent {voice_count} voice messages and {sticker_count} "
                f"stickers across {total} DM messages."
            )
            alt = (
                "Media behavior is within normal human range.  This does not "
                "establish AI authorship."
            )
            strength = 0.1

    return [observation(
        "media_behavior",
        "interaction_pattern",
        "moderate",
        strength,
        desc,
        alt,
        items,
    )]


def burst_pattern_observations(db, subject_id):
    """Analyze message burst patterns: consecutive messages without
    operator response.

    Large bursts (many messages in under a minute) are difficult to
    explain as human phone typing, particularly with motor issues.
    """
    if not table_exists(db, "dm_corpus"):
        return []

    rows = db.execute("""SELECT date, text, message_id FROM dm_corpus
                         WHERE peer_id=? AND is_out=0 AND sender_id=?
                         AND date IS NOT NULL ORDER BY datetime(date), message_id""",
                      (subject_id, subject_id)).fetchall()

    if len(rows) < 30:
        return []

    # Build bursts: consecutive subject messages <60s apart
    bursts = []
    current = []
    prev_dt = None
    for r in rows:
        dt = parse_date(r[0])
        if not dt:
            continue
        if prev_dt and (dt - prev_dt).total_seconds() < 60:
            current.append(r)
        else:
            if current:
                bursts.append(current)
            current = [r]
        prev_dt = dt
    if current:
        bursts.append(current)

    burst_sizes = [len(b) for b in bursts]
    total_bursts = len(bursts)
    single = sum(1 for s in burst_sizes if s == 1)
    small = sum(1 for s in burst_sizes if 2 <= s <= 3)
    large = sum(1 for s in burst_sizes if s >= 4)
    max_burst = max(burst_sizes) if burst_sizes else 0
    avg_burst = sum(burst_sizes) / total_bursts if total_bursts else 0

    items = [{
        "source_key": "derived:burst_pattern",
        "source": "derived",
        "total_bursts": total_bursts,
        "single_msg_bursts": single,
        "small_bursts_2_3": small,
        "large_bursts_4_plus": large,
        "max_burst_size": max_burst,
        "avg_burst_size": round(avg_burst, 1),
    }]

    # Determine strength based on max burst
    if max_burst >= 20:
        strength = 0.55
        desc = (
            f"Subject sent bursts of up to {max_burst} consecutive messages "
            f"in under 60 seconds.  {large} of {total_bursts} bursts contain "
            f"4+ messages.  A burst of {max_burst} messages in under a minute "
            f"is very difficult to explain as human phone typing, "
            f"particularly with motor/mobility issues."
        )
        alt = (
            f"Large bursts could be explained by copy-paste of pre-composed "
            f"text, voice-to-text, or sending a pre-written document in "
            f"chunks.  However, {max_burst} messages in <60s on a phone with "
            f"motor issues is highly anomalous.  This does not establish AI "
            f"authorship but is a significant anomaly."
        )
    elif max_burst >= 10:
        strength = 0.4
        desc = (
            f"Subject sent bursts of up to {max_burst} consecutive messages "
            f"in under 60 seconds.  {large} of {total_bursts} bursts contain "
            f"4+ messages."
        )
        alt = (
            f"Bursts of {max_burst} messages in <60s are fast for phone "
            f"typing but could be explained by copy-paste or pre-composition. "
            f"This does not establish AI authorship."
        )
    else:
        strength = 0.15
        desc = (
            f"Subject sent bursts of up to {max_burst} consecutive messages "
            f"in under 60 seconds.  {large} of {total_bursts} bursts contain "
            f"4+ messages.  This is within normal human range."
        )
        alt = (
            "Burst patterns are within normal human range.  This does not "
            "establish AI authorship."
        )

    return [observation(
        "burst_pattern",
        "typing_pattern",
        "moderate",
        strength,
        desc,
        alt,
        items,
    )]


def reply_latency_observations(db, subject_id):
    """Analyze reply latency distribution from operator messages.

    A high percentage of sub-3-second responses is difficult to explain
    as human phone typing, particularly with motor issues.
    """
    if not table_exists(db, "dm_corpus"):
        return []

    subj_rows = db.execute("""SELECT date, text, message_id FROM dm_corpus
                              WHERE peer_id=? AND is_out=0 AND sender_id=?
                              AND date IS NOT NULL ORDER BY datetime(date), message_id""",
                           (subject_id, subject_id)).fetchall()
    op_rows = db.execute("""SELECT date FROM dm_corpus
                            WHERE peer_id=? AND is_out=1 AND date IS NOT NULL
                            ORDER BY datetime(date)""",
                         (subject_id,)).fetchall()

    if len(subj_rows) < 30 or len(op_rows) < 10:
        return []

    op_dts = []
    for r in op_rows:
        dt = parse_date(r[0])
        if dt:
            op_dts.append(dt)

    latencies = []
    for r in subj_rows:
        dt = parse_date(r[0])
        if not dt:
            continue
        prev = None
        for odt in op_dts:
            if odt < dt:
                prev = odt
            else:
                break
        if prev:
            lat = (dt - prev).total_seconds()
            if 0 <= lat <= 86400:
                latencies.append(lat)

    if len(latencies) < 30:
        return []

    total = len(latencies)
    under_1s = sum(1 for l in latencies if l < 1)
    under_3s = sum(1 for l in latencies if l < 3)
    under_10s = sum(1 for l in latencies if l < 10)
    under_60s = sum(1 for l in latencies if l < 60)
    over_1min = sum(1 for l in latencies if l >= 60)

    items = [{
        "source_key": "derived:reply_latency",
        "source": "derived",
        "total_responses": total,
        "under_1s": under_1s,
        "under_1s_pct": round(under_1s / total, 4),
        "under_3s": under_3s,
        "under_3s_pct": round(under_3s / total, 4),
        "under_10s": under_10s,
        "under_10s_pct": round(under_10s / total, 4),
        "under_60s": under_60s,
        "under_60s_pct": round(under_60s / total, 4),
        "over_1min": over_1min,
        "over_1min_pct": round(over_1min / total, 4),
    }]

    if under_3s / total > 0.10:
        strength = 0.45
        desc = (
            f"{under_3s} of {total} responses ({under_3s/total:.1%}) arrived "
            f"in under 3 seconds.  {under_10s} ({under_10s/total:.1%}) arrived "
            f"in under 10 seconds.  This is very fast for human phone typing, "
            f"particularly with motor/mobility issues."
        )
        alt = (
            "Fast responses could be explained by pre-composed text, "
            "copy-paste, simple acknowledgements, or Telegram timestamp "
            "rounding.  However, sustained sub-3-second response rates "
            "above 10% are difficult to explain as direct phone typing "
            "with motor limitations.  This does not establish AI authorship."
        )
    elif under_3s / total > 0.05:
        strength = 0.3
        desc = (
            f"{under_3s} of {total} responses ({under_3s/total:.1%}) arrived "
            f"in under 3 seconds.  {under_10s} ({under_10s/total:.1%}) arrived "
            f"in under 10 seconds."
        )
        alt = (
            "Some fast responses are normal in casual conversation.  This "
            "does not establish AI authorship."
        )
    else:
        strength = 0.15
        desc = (
            f"{under_3s} of {total} responses ({under_3s/total:.1%}) arrived "
            f"in under 3 seconds.  Response times are within normal human range."
        )
        alt = (
            "Response latency is within normal human range.  This does not "
            "establish AI authorship."
        )

    return [observation(
        "reply_latency_distribution",
        "typing_pattern",
        "moderate",
        strength,
        desc,
        alt,
        items,
    )]


def initiation_pattern_observations(db, subject_id):
    """Analyze who initiates conversations after long gaps.

    A subject who initiates conversations is more human-like than a
    response-only AI, but an AI could be configured to initiate.
    """
    if not table_exists(db, "dm_corpus"):
        return []

    all_rows = db.execute("""SELECT date, is_out FROM dm_corpus
                             WHERE peer_id=? AND date IS NOT NULL
                             ORDER BY datetime(date)""",
                          (subject_id,)).fetchall()

    if len(all_rows) < 50:
        return []

    initiations = {"subject": 0, "operator": 0}
    prev_dt = None
    for r in all_rows:
        dt = parse_date(r[0])
        if not dt:
            continue
        if prev_dt and (dt - prev_dt).total_seconds() > 3600 * 6:
            who = "subject" if r[1] == 0 else "operator"
            initiations[who] += 1
        prev_dt = dt

    total_init = initiations["subject"] + initiations["operator"]
    if total_init < 5:
        return []

    subj_pct = initiations["subject"] / total_init

    items = [{
        "source_key": "derived:initiation_pattern",
        "source": "derived",
        "total_initiations": total_init,
        "subject_initiations": initiations["subject"],
        "operator_initiations": initiations["operator"],
        "subject_initiation_pct": round(subj_pct, 4),
    }]

    if subj_pct > 0.6:
        strength = 0.15  # low: supports human behavior
        desc = (
            f"Subject initiates {initiations['subject']} of {total_init} "
            f"conversations ({subj_pct:.0%}) after 6+ hour gaps.  This is "
            f"more human-like than a response-only system."
        )
        alt = (
            "High initiation rate is consistent with a human conversation "
            "partner but does not prove human operation.  An AI agent could "
            "be configured to initiate conversations.  This does not "
            "establish or refute AI authorship."
        )
    elif subj_pct < 0.3:
        strength = 0.25
        desc = (
            f"Subject initiates only {initiations['subject']} of {total_init} "
            f"conversations ({subj_pct:.0%}) after 6+ hour gaps.  This is "
            f"more consistent with a response-only system."
        )
        alt = (
            "Low initiation rate could indicate a response-only AI, a "
            "passive communication style, or social reluctance (consistent "
            "with autism).  This does not establish AI authorship."
        )
    else:
        strength = 0.1
        desc = (
            f"Subject initiates {initiations['subject']} of {total_init} "
            f"conversations ({subj_pct:.0%}) after 6+ hour gaps."
        )
        alt = (
            "Balanced initiation is normal for human conversation.  This "
            "does not establish AI authorship."
        )

    return [observation(
        "initiation_pattern",
        "interaction_pattern",
        "moderate",
        strength,
        desc,
        alt,
        items,
    )]


def analyze(db_path, subject_id, related_ids, persist=True):
    if not isinstance(subject_id, int) or subject_id <= 0:
        raise ValueError("subject_id must be a positive integer")
    if not Path(db_path).is_file():
        raise FileNotFoundError(db_path)
    db = connect_db(db_path)
    try:
        ensure_schema(db)
        messages = load_subject_messages(db, subject_id)
        dialogue = load_dm_dialogue(db, subject_id)
        fingerprint = corpus_fingerprint(messages)
        observations = [corpus_coverage(messages)]
        candidates = [
            proof_exchanges(dialogue),
            constraint_statements(messages),
            identity_discourse(messages),
            alias_references(messages),
            question_profile(messages),
            style_shift(messages),
            response_dynamics(dialogue),
            repetition_patterns(messages),
            explicit_claim_conflicts(messages),
            peer_style_calibration(db, subject_id, messages),
            reply_relationships(db, subject_id, related_ids),
        ]
        observations.extend(item for item in candidates if item)
        observations.extend(longitudinal_style(messages))
        observations.extend(channel_relationships(db, subject_id, related_ids))
        observations.extend(typing_pattern_observations(db, subject_id))
        observations.extend(time_of_day_observations(messages, subject_id))
        observations.extend(operator_correlation_observations(db, subject_id))
        observations.extend(platform_context_observations(db, subject_id))
        observations.extend(reported_condition_observations(subject_id))
        observations.extend(multi_account_overlap_observations(db, subject_id))
        observations.extend(media_behavior_observations(db, subject_id))
        observations.extend(burst_pattern_observations(db, subject_id))
        observations.extend(reply_latency_observations(db, subject_id))
        observations.extend(initiation_pattern_observations(db, subject_id))
        priority = review_priority(observations)
        by_category = Counter(item["category"] for item in observations)
        summary = {
            "analysis_version": ANALYSIS_VERSION,
            "subject_id": subject_id,
            "corpus_fingerprint": fingerprint,
            "message_count": len(messages),
            "dm_message_count": sum(message["source"] == "dm" for message in messages),
            "channel_message_count": sum(message["source"] == "channel" for message in messages),
            "observation_count": len(observations),
            "categories": dict(sorted(by_category.items())),
            "review_priority": priority,
            "assessment": "Indeterminate: automated corpus observations do not establish AI authorship, identity, intent, or coordination without independent validation.",
            "generated_at": utc_now(),
        }
        if not persist:
            return {**summary, "run_id": None, "unchanged": False, "observations": observations}
        run_id, unchanged, stored_summary = persist_run(
            db, subject_id, fingerprint, messages, observations, priority, summary
        )
        return {
            **stored_summary,
            "run_id": run_id,
            "unchanged": unchanged,
            "new_message_count": 0 if unchanged else stored_summary.get("new_message_count", 0),
        }
    finally:
        db.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Run evidence-calibrated corpus analysis")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--subject-id", type=int, default=DEFAULT_SUBJECT)
    parser.add_argument("--related-id", type=int, action="append", default=[])
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    related = tuple(args.related_id) if args.related_id else DEFAULT_RELATED
    try:
        result = analyze(args.db, args.subject_id, related, persist=not args.no_persist)
    except (FileNotFoundError, sqlite3.Error, ValueError) as exc:
        raise SystemExit(f"corpus analysis failed: {exc}") from exc
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        state = "preview" if args.no_persist else ("unchanged" if result["unchanged"] else "stored")
        print(
            f"[corpus-analysis] subject={result['subject_id']} state={state} "
            f"messages={result['message_count']} new={result.get('new_message_count', 0)} "
            f"observations={result['observation_count']} review_priority={result['review_priority']:.2f}"
        )
        print(f"[corpus-analysis] assessment={result['assessment']}")


if __name__ == "__main__":
    main()
