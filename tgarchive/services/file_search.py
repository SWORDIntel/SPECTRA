"""
File Search Service — Search all chats and accounts for a particular file
==========================================================================

Searches across all archived media for a specific file or the closest matching
file name. Supports:
  - Exact filename match
  - Fuzzy filename matching (typo-tolerant)
  - File hash lookup (SHA256/MD5)
  - File type filtering
  - Per-channel and per-user breakdown
  - Media metadata search (title, description, URL)
  - Password field detection — scans nearby messages for password keywords
    (password, pass, pwd, key, secret, passphrase, code, unlock) and extracts
    the associated password value

Usage (library)::

    from tgarchive.services.file_search import search_files

    results = search_files(db_path="spectra.db", query="invoice.pdf")

Usage (CLI)::

    spectra-cli file-search "invoice.pdf"
    spectra-cli file-search "invoice" --fuzzy --limit 20
    spectra-cli file-search --hash abc123def456
"""

from __future__ import annotations

import logging
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..sqlite_runtime import connect_sqlite

logger = logging.getLogger(__name__)

try:
    from ..native.filesearch_bindings import (
        extract_passwords as _native_extract_passwords,
        fuzzy_match as _native_fuzzy_match,
        batch_score as _native_batch_score,
        match_type_name as _native_match_type_name,
        batch_available as _native_batch_available,
    )
except (ImportError, OSError):
    _native_extract_passwords = None
    _native_fuzzy_match = None
    _native_batch_score = None
    _native_match_type_name = None
    _native_batch_available = None


# ─── Password field detection ────────────────────────────────────────────────

_PASSWORD_KEYWORDS = [
    "password", "pass", "pwd", "passphrase", "passcode",
    "secret", "unlock", "key", "code", "pin",
]

# Patterns: keyword followed by separator and value
_PASSWORD_PATTERNS = [
    # password: value / password = value / password - value
    re.compile(
        r"(?i)\b(password|passwd|pwd|passphrase|passcode|secret|unlock\s+key|unlock\s+code|key|code|pin)\b"
        r"\s*[:=]\s*([^\s\n\r,;|]{1,256})",
    ),
    # password is value / password: value
    re.compile(
        r"(?i)\b(password|passwd|pwd|passphrase|passcode)\s+is\s+[:=]?\s*([^\s\n\r,;|]{1,256})",
    ),
    # "pass:" value  /  "pwd:" value  (compact forms)
    re.compile(
        r"(?i)\b(pass|pwd)\b\s*[:\-=]\s*([^\s\n\r,;|]{1,256})",
    ),
    # password → value (arrow notation)
    re.compile(
        r"(?i)\b(password|passwd|pwd|passphrase|passcode|secret)\b\s*[→>]+\s*([^\s\n\r,;|]{1,256})",
    ),
    # "the password is value" / "password is 'value'"
    re.compile(
        r"(?i)\b(?:the\s+)?(password|passwd|pwd|passphrase|passcode|secret\s+code|unlock\s+code)\s+is\s+['\"]?([^\s\n\r,;|'\"]{1,256})",
    ),
    # pass: value (at start of line, common in Telegram)
    # Group 1 = keyword, Group 2 = value
    re.compile(
        r"(?i)^(password|passwd|pwd|pass|passphrase|passcode|secret|key|code|pin)\s*[:=]\s*(.+)$",
    ),
    # Quoted string after a filename: file.zip "s3cr3t"  or  file.zip 'pass123'
    # Group 1 = filename (discarded), Group 2 = the quoted password
    re.compile(
        r"(?i)(\b\w+\.(?:zip|rar|7z|tar|gz|pdf|doc|docx|xls|xlsx|enc|aes|gpg|pgp|bz2|xz)\b)"
        r"\s*[\"'`]([^\"'`]{1,256})[\"'`]",
    ),
    # Quoted string after a password keyword: key "s3cr3t" / password 'pass123'
    re.compile(
        r"(?i)\b(password|passwd|pwd|passphrase|passcode|pass|secret|unlock\s+key|key|code|pin)\b"
        r"\s+[\"'`]([^\"'`]{1,256})[\"'`]",
    ),
    # Bare word on its own line after a file mention (common Telegram pattern):
    #   "Here's the archive: files.zip\npassword123"
    # Group 1 = filename (discarded), Group 2 = the bare password
    re.compile(
        r"(?i)(\b\w+\.(?:zip|rar|7z|tar|gz|pdf|doc|docx|xls|xlsx|enc|aes|gpg|pgp|bz2|xz)\b)"
        r"[\s\S]{0,200}?\n\s*([A-Za-z0-9!@#$%^&*()_+\-=\[\]{}|;:,.<>?/~`]{3,64})\s*(?:\n|$)",
    ),
]

# File extensions that are commonly password-protected
_PROTECTED_EXTENSIONS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".pdf", ".doc", ".docx",
    ".xls", ".xlsx", ".enc", ".aes", ".gpg", ".pgp", ".bz2", ".xz",
    ".tar.gz", ".tar.bz2", ".tar.xz",
}

# Stopwords — values that are not actual passwords
_PASSWORD_STOPWORDS = {
    "none", "null", "n/a", "na", "empty", "required", "optional",
    "yes", "no", "true", "false", "unknown", "hidden", "redacted",
    "todo", "tbd", "xxxx", "****", "...", "see", "below", "above",
    "here", "link", "dm", "pm", "ask", "request", "contact",
    "not", "set", "unset", "change", "reset", "new", "old",
}


def _extract_passwords(text: str) -> List[Dict[str, Any]]:
    """Extract password-like values from text.

    Scans for password keywords followed by a value and returns
    all matches with the keyword, extracted value, and context.
    Also detects bare standalone strings near file references.
    """
    if not text:
        return []

    if _native_extract_passwords is not None:
        native_result = _native_extract_passwords(text, "")
        if native_result:
            return native_result
        # Native returned empty — fall through to Python patterns
        # (Python has additional patterns like keyword + quoted value)

    found: List[Dict[str, Any]] = []
    seen_values: set = set()

    for pattern in _PASSWORD_PATTERNS:
        for match in pattern.finditer(text):
            keyword = match.group(1).strip().lower() if match.lastindex >= 2 else "bare_word"
            value = match.group(2).strip().strip("\"'`")

            # Filter out stopwords and too-short values
            if value.lower() in _PASSWORD_STOPWORDS:
                continue
            if len(value) < 2:
                continue
            # Skip pure URLs
            if value.startswith("http://") or value.startswith("https://"):
                continue
            # Skip if it looks like a path
            if value.startswith("/") and value.count("/") >= 2:
                continue

            # Get surrounding context (±50 chars)
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 50)
            context = text[start:end].replace("\n", " ").strip()

            if value not in seen_values:
                seen_values.add(value)
                found.append({
                    "keyword": keyword,
                    "value": value,
                    "context": context,
                })

    # Heuristic: bare standalone word on a line near a file extension
    # e.g. "archive.zip\ns3cr3t" or "file.7z\n\nunlock42"
    _heuristic_bare_passwords(text, found, seen_values)

    return found


def _heuristic_bare_passwords(text: str, found: List[Dict[str, Any]], seen_values: set) -> None:
    """Detect bare standalone strings near file references.

    Common Telegram pattern:
        Check this out: archive.zip
        s3cr3t

    The password is just a word on its own line with no keyword prefix.
    We look for short standalone lines (3-64 chars) near file extensions.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Check if this line mentions a protected file extension
        has_file = any(ext in stripped.lower() for ext in _PROTECTED_EXTENSIONS)
        if not has_file:
            continue

        # Look at the next 1-3 non-empty lines for a bare password
        for j in range(i + 1, min(i + 4, len(lines))):
            candidate = lines[j].strip()
            if not candidate:
                continue

            # Skip lines that are clearly sentences (contain common words)
            lower_cand = candidate.lower()
            sentence_indicators = [" the ", " this ", " that ", " here ", " please ",
                                   " check ", " download ", " thanks ", " thank ",
                                   " http", " www.", " telegram", " channel"]
            if any(ind in lower_cand for ind in sentence_indicators):
                continue

            # Skip if too long (likely a sentence, not a password)
            if len(candidate) > 64:
                continue
            # Skip if it has too many spaces (likely a sentence)
            if candidate.count(" ") > 3:
                continue

            # Skip if it contains a password keyword (already caught above)
            if any(kw in lower_cand for kw in _PASSWORD_KEYWORDS):
                continue

            # Skip URLs
            if candidate.startswith("http://") or candidate.startswith("https://"):
                continue

            # Skip if it looks like another filename
            if any(candidate.lower().endswith(ext) for ext in _PROTECTED_EXTENSIONS):
                continue

            # Skip stopwords
            if lower_cand in _PASSWORD_STOPWORDS:
                continue

            # This looks like a bare password
            if candidate not in seen_values:
                seen_values.add(candidate)
                # Get context (the file mention line + this line)
                context_start = max(0, i)
                context_end = min(len(lines), j + 2)
                context = " ".join(lines[context_start:context_end]).strip()
                found.append({
                    "keyword": "bare_word",
                    "value": candidate,
                    "context": context,
                })
            break  # Only take the first bare word after the file mention


def _scan_nearby_for_passwords(
    conn: sqlite3.Connection,
    message_ids: List[int],
    *,
    window: int = 5,
) -> List[Dict[str, Any]]:
    """Scan messages near the given message IDs for password fields.

    Uses set-based batch queries (4 total) instead of N+1 per-message queries.
    Contextual neighbourhood is determined by:
      1. The message itself
      2. Reply chain (parent + children) — true conversational proximity
      3. Same-channel messages within a timestamp window — NOT global ID proximity

    Returns a list of password findings with source message info.
    """
    if not message_ids:
        return []

    id_ph = ",".join("?" * len(message_ids))

    # ── 1. Fetch all source messages themselves (1 query) ──
    source_msgs: Dict[int, sqlite3.Row] = {}
    try:
        rows = conn.execute(
            f"SELECT id, user_id, date, content, reply_to FROM messages WHERE id IN ({id_ph})",
            message_ids,
        ).fetchall()
        for r in rows:
            source_msgs[r["id"]] = r
    except sqlite3.OperationalError:
        pass

    # ── 2. Fetch reply parents (1 query) ──
    parent_ids = [r["reply_to"] for r in source_msgs.values() if r["reply_to"]]
    parents: Dict[int, sqlite3.Row] = {}
    if parent_ids:
        pph = ",".join("?" * len(parent_ids))
        try:
            p_rows = conn.execute(
                f"SELECT id, user_id, date, content FROM messages WHERE id IN ({pph})",
                parent_ids,
            ).fetchall()
            for r in p_rows:
                parents[r["id"]] = r
        except sqlite3.OperationalError:
            pass

    # ── 3. Fetch reply children (1 query) ──
    children: Dict[int, List[sqlite3.Row]] = {}
    try:
        c_rows = conn.execute(
            f"SELECT id, user_id, date, content, reply_to FROM messages WHERE reply_to IN ({id_ph}) LIMIT 100",
            message_ids,
        ).fetchall()
        for r in c_rows:
            children.setdefault(r["reply_to"], []).append(r)
    except sqlite3.OperationalError:
        pass

    # ── 4. Fetch same-channel contextual neighbours by timestamp (1 query) ──
    # Uses channel_messages join to find same-channel messages within a time
    # window around each source message — NOT global ID proximity.
    # Falls back to ID-proximity if channel_messages table doesn't exist.
    neighbors: Dict[int, List[sqlite3.Row]] = {}
    try:
        # Check if channel_messages table exists
        conn.execute("SELECT 1 FROM channel_messages LIMIT 0")
        has_channel_table = True
    except sqlite3.OperationalError:
        has_channel_table = False

    if has_channel_table and source_msgs:
        # Build per-message time windows and query same-channel neighbors
        # We query channels for our source messages first
        try:
            chan_rows = conn.execute(
                f"SELECT DISTINCT channel_id, message_id FROM channel_messages WHERE message_id IN ({id_ph})",
                message_ids,
            ).fetchall()
        except sqlite3.OperationalError:
            chan_rows = []

        if chan_rows:
            # Group source messages by channel
            chan_to_msgs: Dict[int, List[int]] = {}
            for cr in chan_rows:
                chan_to_msgs.setdefault(cr["channel_id"], []).append(cr["message_id"])

            # For each channel, find messages within ±window seconds of any source msg
            # window is in message count; convert to a time-based window using the
            # source message dates. We use a generous ±300s (5 min) default.
            time_window_seconds = max(60, window * 60)
            all_neighbor_ids: Set[int] = set()
            neighbor_rows: List[sqlite3.Row] = []

            for chan_id, src_ids in chan_to_msgs.items():
                # Get dates of source messages in this channel
                src_dates = [
                    source_msgs[mid]["date"]
                    for mid in src_ids
                    if mid in source_msgs and source_msgs[mid]["date"]
                ]
                if not src_dates:
                    continue
                min_date = min(src_dates)
                max_date = max(src_dates)

                # Query same-channel messages in the time window
                try:
                    n_rows = conn.execute(
                        """
                        SELECT m.id, m.user_id, m.date, m.content
                        FROM messages m
                        JOIN channel_messages cm ON cm.message_id = m.id
                        WHERE cm.channel_id = ?
                          AND m.date BETWEEN datetime(?, ?) AND datetime(?, ?)
                          AND m.content IS NOT NULL
                        ORDER BY m.date
                        LIMIT 200
                        """,
                        (
                            chan_id,
                            min_date,
                            f"-{time_window_seconds} seconds",
                            max_date,
                            f"+{time_window_seconds} seconds",
                        ),
                    ).fetchall()
                    for nr in n_rows:
                        if nr["id"] not in source_msgs and nr["id"] not in all_neighbor_ids:
                            all_neighbor_ids.add(nr["id"])
                            neighbor_rows.append(nr)
                except sqlite3.OperationalError:
                    pass

            # Group neighbors by which source message they're closest to (by date)
            for nr in neighbor_rows:
                # Find nearest source message by date
                best_src = None
                best_diff = None
                for mid, sm in source_msgs.items():
                    if not sm["date"] or not nr["date"]:
                        continue
                    try:
                        from datetime import datetime
                        d1 = datetime.fromisoformat(sm["date"].replace("Z", "+00:00"))
                        d2 = datetime.fromisoformat(nr["date"].replace("Z", "+00:00"))
                        diff = abs((d1 - d2).total_seconds())
                    except (ValueError, TypeError):
                        continue
                    if best_diff is None or diff < best_diff:
                        best_diff = diff
                        best_src = mid
                if best_src is not None:
                    neighbors.setdefault(best_src, []).append(nr)

    elif source_msgs:
        # Fallback: ID-proximity (legacy behavior) when no channel_messages table
        # This is less accurate but maintains backward compatibility
        all_ids = set()
        for mid in message_ids:
            for nid in range(mid - window, mid + window + 1):
                all_ids.add(nid)
        all_ids -= set(message_ids)
        if all_ids:
            id_list = list(all_ids)
            nph = ",".join("?" * len(id_list))
            try:
                n_rows = conn.execute(
                    f"SELECT id, user_id, date, content FROM messages WHERE id IN ({nph}) AND content IS NOT NULL",
                    id_list,
                ).fetchall()
                for nr in n_rows:
                    # Assign to nearest source by ID
                    best_src = min(message_ids, key=lambda x: abs(x - nr["id"]))
                    if abs(nr["id"] - best_src) <= window:
                        neighbors.setdefault(best_src, []).append(nr)
            except sqlite3.OperationalError:
                pass

    # ── Extract passwords from all collected messages ──
    passwords: List[Dict[str, Any]] = []
    seen_values: set = set()

    def _process_msg(row: sqlite3.Row, proximity: str) -> None:
        if not row or not row["content"]:
            return
        found = _extract_passwords(row["content"])
        for f in found:
            if f["value"] not in seen_values:
                seen_values.add(f["value"])
                passwords.append({
                    **f,
                    "source_message_id": row["id"],
                    "source_user_id": row["user_id"],
                    "source_date": row["date"],
                    "proximity": proximity,
                })

    for mid in message_ids:
        sm = source_msgs.get(mid)
        if sm:
            _process_msg(sm, "same_message")

        # Reply parent
        if sm and sm["reply_to"] and sm["reply_to"] in parents:
            _process_msg(parents[sm["reply_to"]], "parent_reply")

        # Reply children
        for cr in children.get(mid, []):
            _process_msg(cr, "child_reply")

        # Channel/timestamp neighbors
        for nr in neighbors.get(mid, []):
            _process_msg(nr, "channel_neighbor")

    return passwords


def _extract_filename(url: str) -> str:
    """Extract a filename from a URL or path."""
    if not url:
        return ""
    # Handle URLs
    if "/" in url:
        return url.rsplit("/", 1)[-1]
    return url


def _fuzzy_match(query: str, candidate: str, threshold: float = 0.6) -> float:
    """Fuzzy match two strings, returns similarity 0-1."""
    if not query or not candidate:
        return 0.0

    if _native_fuzzy_match is not None:
        native_score = _native_fuzzy_match(query, candidate)
        if native_score is not None:
            return native_score

    q_lower = query.lower()
    c_lower = candidate.lower()

    # Exact match
    if q_lower == c_lower:
        return 1.0

    # Substring match (query is part of candidate)
    if q_lower in c_lower:
        return 0.9

    # Candidate is part of query
    if c_lower in q_lower:
        return 0.8

    # Fuzzy similarity
    return SequenceMatcher(None, q_lower, c_lower).ratio()


def search_files(
    db_path: Path | str,
    query: Optional[str] = None,
    *,
    file_hash: Optional[str] = None,
    fuzzy: bool = True,
    file_type: Optional[str] = None,
    channel_id: Optional[int] = None,
    user_id: Optional[int] = None,
    limit: int = 50,
    threshold: float = 0.5,
    scan_passwords: bool = True,
    password_window: int = 5,
) -> Dict[str, Any]:
    """Search all archived media for a file or closest matching filename.

    Args:
        db_path: Path to the SPECTRA SQLite database.
        query: Filename or partial filename to search for.
        file_hash: Hash (SHA256/MD5) to search for.
        fuzzy: If True, use fuzzy matching for filenames.
        file_type: Filter by media type (photo, video, document, etc.).
        channel_id: Filter by channel.
        user_id: Filter by uploading user.
        limit: Maximum results.
        threshold: Minimum fuzzy match score (0-1).
        scan_passwords: If True, scan nearby messages for password fields.
        password_window: How many messages to look around for passwords.

    Returns:
        Dict with: results, summary
    """
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with connect_sqlite(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Build query
        conditions = []
        params: list = []

        if file_hash:
            conditions.append("checksum LIKE ?")
            params.append(f"%{file_hash}%")

        if file_type:
            conditions.append("type = ?")
            params.append(file_type)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        # Try to select the new columns — fall back gracefully if they don't exist yet
        media_cols = "id, type, url, title, description, thumb, checksum"
        try:
            # Test if the new columns exist
            conn.execute("SELECT size, mime_type, file_name, duration, width, height, dc_id, date, posted_by FROM media LIMIT 0")
            has_extended_cols = True
            media_cols = "id, type, url, title, description, thumb, checksum, size, mime_type, file_name, duration, width, height, dc_id, date, posted_by"
        except sqlite3.OperationalError:
            has_extended_cols = False

        try:
            rows = conn.execute(
                f"SELECT {media_cols} FROM media {where} ORDER BY id",
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return {"results": [], "summary": {"error": "media table not found"}}

        # ── First pass: score all media rows using bulk C scorer ────────────
        scored: List[Tuple[float, str, sqlite3.Row, str]] = []

        # Build candidate list for bulk scoring
        candidates: List[Tuple[int, str, str, str]] = []
        row_by_id: Dict[int, Tuple[sqlite3.Row, str]] = {}

        for row in rows:
            media_id = row["id"]
            url = row["url"] or ""
            title = row["title"] or ""
            checksum = row["checksum"] or ""
            if has_extended_cols and row["file_name"]:
                filename = row["file_name"]
            else:
                filename = _extract_filename(url) or title
            row_by_id[media_id] = (row, filename, checksum)
            candidates.append((media_id, filename, title, url))

        if file_hash:
            # Hash matching — no need for fuzzy scoring
            for media_id, (_, filename, checksum) in row_by_id.items():
                if checksum and file_hash.lower() in checksum.lower():
                    score = 1.0 if checksum.lower() == file_hash.lower() else 0.9
                    scored.append((score, "hash_match", row_by_id[media_id][0], filename))
        elif query and candidates:
            # ── Bulk C scoring path ─────────────────────────────────────────
            if _native_batch_score is not None:
                batch_results = _native_batch_score(query, candidates, threshold=threshold, fuzzy=fuzzy)
                if batch_results is not None:
                    for i, (score, match_type_int) in enumerate(batch_results):
                        if score >= threshold:
                            media_id = candidates[i][0]
                            row, filename, _ = row_by_id[media_id]
                            match_type = _native_match_type_name(match_type_int) if _native_match_type_name else "fuzzy"
                            scored.append((score, match_type, row, filename))
                else:
                    # Batch failed — fall through to Python fallback
                    pass
            # ── Python fallback (if native unavailable or batch failed) ─────
            if not scored:
                for media_id, (row, filename, _) in row_by_id.items():
                    url = row["url"] or ""
                    title = row["title"] or ""
                    if fuzzy:
                        filename_score = _fuzzy_match(query, filename, threshold)
                        title_score = _fuzzy_match(query, title, threshold)
                        url_score = _fuzzy_match(query, url, threshold)
                        best_score = max(filename_score, title_score, url_score)
                        if best_score >= threshold:
                            if best_score == filename_score:
                                match_type = "filename_fuzzy"
                            elif best_score == title_score:
                                match_type = "title_fuzzy"
                            else:
                                match_type = "url_fuzzy"
                            scored.append((best_score, match_type, row, filename))
                    else:
                        if query.lower() in filename.lower():
                            score = 1.0 if filename.lower() == query.lower() else 0.9
                            scored.append((score, "filename_exact", row, filename))
                        elif query.lower() in title.lower():
                            scored.append((0.8, "title_exact", row, filename))
                        elif query.lower() in url.lower():
                            scored.append((0.7, "url_exact", row, filename))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[:limit]
        matching_ids = [r["id"] for _, _, r, _ in scored]

        # ── Batch preload: messages for all matching media ──────────────────
        msg_by_media: Dict[int, List[sqlite3.Row]] = {}
        if matching_ids:
            ph = ",".join("?" * len(matching_ids))
            try:
                msg_rows = conn.execute(
                    f"""SELECT id, user_id, date, content, media_id FROM (
                        SELECT *, ROW_NUMBER() OVER (PARTITION BY media_id ORDER BY date DESC) as rn
                        FROM messages WHERE media_id IN ({ph})
                    ) WHERE rn <= 10""",
                    matching_ids,
                ).fetchall()
                for mr in msg_rows:
                    msg_by_media.setdefault(mr["media_id"], []).append(mr)
            except sqlite3.OperationalError:
                pass

        # ── Batch preload: channels for all matching media ──────────────────
        chan_by_media: Dict[int, List[int]] = {}
        if matching_ids:
            ph = ",".join("?" * len(matching_ids))
            try:
                chan_rows = conn.execute(
                    f"SELECT DISTINCT channel_id, media_id FROM channel_messages WHERE media_id IN ({ph})",
                    matching_ids,
                ).fetchall()
                for cr in chan_rows:
                    chan_by_media.setdefault(cr["media_id"], []).append(cr["channel_id"])
            except sqlite3.OperationalError:
                pass

        # ── Batch preload: users for all referenced user_ids ────────────────
        user_cache: Dict[int, str] = {}
        all_user_ids: Set[int] = set()
        for msgs in msg_by_media.values():
            for mr in msgs:
                if mr["user_id"]:
                    all_user_ids.add(mr["user_id"])
        if has_extended_cols:
            for _, _, r, _ in scored:
                if r["posted_by"]:
                    all_user_ids.add(r["posted_by"])
        if all_user_ids:
            ph = ",".join("?" * len(all_user_ids))
            try:
                u_rows = conn.execute(
                    f"SELECT id, username FROM users WHERE id IN ({ph})",
                    list(all_user_ids),
                ).fetchall()
                for ur in u_rows:
                    user_cache[ur["id"]] = ur["username"]
            except sqlite3.OperationalError:
                pass

        def _resolve_user(uid: Optional[int]) -> Optional[str]:
            if uid is None:
                return None
            return user_cache.get(uid)

        # ── Second pass: build result dicts from preloaded data ─────────────
        results: List[Dict[str, Any]] = []

        for score, match_type, row, filename in scored:
            media_id = row["id"]
            url = row["url"] or ""
            title = row["title"] or ""
            checksum = row["checksum"] or ""

            message_refs: List[Dict[str, Any]] = []
            ref_message_ids: List[int] = []
            for mr in msg_by_media.get(media_id, []):
                ref_message_ids.append(mr["id"])
                message_refs.append({
                    "message_id": mr["id"],
                    "user_id": mr["user_id"],
                    "date": mr["date"],
                    "content_preview": (mr["content"] or "")[:100],
                })

            nearby_passwords: List[Dict[str, Any]] = []
            if scan_passwords and ref_message_ids:
                nearby_passwords = _scan_nearby_for_passwords(conn, ref_message_ids, window=password_window)

            channel_refs: List[Dict[str, Any]] = [{"channel_id": cid} for cid in chan_by_media.get(media_id, [])]

            if channel_id and channel_refs and not any(c["channel_id"] == channel_id for c in channel_refs):
                continue
            if user_id and message_refs and not any(m["user_id"] == user_id for m in message_refs):
                continue

            results.append({
                "media_id": media_id,
                "filename": filename,
                "title": title,
                "type": row["type"],
                "url": url,
                "checksum": checksum[:16] + "..." if len(checksum) > 16 else checksum,
                "match_score": round(score, 4),
                "match_type": match_type,
                "message_refs": message_refs,
                "channel_refs": channel_refs,
                "ref_count": len(message_refs),
                "nearby_passwords": nearby_passwords,
                "password_count": len(nearby_passwords),
                "size": row["size"] if has_extended_cols else None,
                "mime_type": row["mime_type"] if has_extended_cols else None,
                "duration": row["duration"] if has_extended_cols else None,
                "width": row["width"] if has_extended_cols else None,
                "height": row["height"] if has_extended_cols else None,
                "dc_id": row["dc_id"] if has_extended_cols else None,
                "media_date": row["date"] if has_extended_cols else None,
                "posted_by_user_id": row["posted_by"] if has_extended_cols else None,
                "posted_by_username": _resolve_user(row["posted_by"]) if has_extended_cols else None,
            })

        # Build summary (results already sorted+limited in first pass)
        by_type: Dict[str, int] = {}
        by_channel: Dict[int, int] = {}
        for r in results:
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
            for c in r["channel_refs"]:
                by_channel[c["channel_id"]] = by_channel.get(c["channel_id"], 0) + 1

    return {
        "query": query or file_hash,
        "results": results,
        "summary": {
            "total_matches": len(results),
            "by_type": by_type,
            "by_channel": by_channel,
            "best_match_score": results[0]["match_score"] if results else 0.0,
            "files_with_passwords": sum(1 for r in results if r.get("password_count", 0) > 0),
            "total_passwords_found": sum(r.get("password_count", 0) for r in results),
        },
    }


__all__ = ["search_files"]
