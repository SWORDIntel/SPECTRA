"""
SPECTRA Intelligence — L5 Formatting Fingerprint Module
======================================================
Extracts structural and markdown formatting features from messages to characterize
an actor's layout and typographic style.

Standard library only (re, collections, statistics, math).
"""
from __future__ import annotations

import logging
import math
import re
import statistics
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Common shell command keywords for detection
COMMON_SHELL_COMMANDS: Tuple[str, ...] = (
    "ls", "cd", "git", "python", "python3", "pip", "pip3", "npm", "yarn", "pnpm",
    "docker", "docker-compose", "curl", "wget", "cat", "grep", "ripgrep", "rg",
    "mkdir", "rm", "cp", "mv", "chmod", "chown", "sudo", "su", "systemctl",
    "service", "ssh", "scp", "rsync", "tar", "zip", "unzip", "find", "sed",
    "awk", "echo", "export", "source", "bash", "sh", "zsh", "apt", "apt-get",
    "dpkg", "brew", "cargo", "make", "cmake", "pytest", "spectra", "spectra-launch",
    "node", "go", "rustc", "tail", "head", "kill", "killall", "ps", "top",
    "htop", "df", "du", "uname", "vim", "nano", "clear", "ping", "netstat",
    "ss", "nmap", "iptables", "ufw", "env", "which", "whereis",
)

# Compiled regex patterns
_BULLET_RE = re.compile(r"^\s*[-*•·][ \t]+\S")
_NUMBERED_LIST_RE = re.compile(r"^\s*\d+[\.\)][ \t]+\S")
_HEADING_RE = re.compile(r"^\s*#{1,6}[ \t]+\S")
_BLOCKQUOTE_RE = re.compile(r"^\s*>[ \t]*\S")
_CODEBLOCK_RE = re.compile(r"```([a-zA-Z0-9_#+-]*)[\r\n]([\s\S]*?)```")
_INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\r\n]+)`(?!`)")
_BOLD_RE = re.compile(r"(?:\*\*|__)(?!\s)(.+?)(?<!\s)(?:\*\*|__)")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(?!\s)([^*\r\n]+?)(?<!\s)\*(?!\*)|(?<!\_)\_(?!\_)(?!\s)([^_\r\n]+?)(?<!\s)\_(?!\_)")
_SHELL_PROMPT_RE = re.compile(r"^\s*(?:\$|#|>>>|\.\/)[ \t]+\S")
_PATH_RE = re.compile(r"(?<![a-zA-Z0-9_\-])(?:/(?:[a-zA-Z0-9_\-\.]+/)+[a-zA-Z0-9_\-\.]*|~/(?:[a-zA-Z0-9_\-\.]+/)*[a-zA-Z0-9_\-\.]+|[a-zA-Z]:\\(?:[a-zA-Z0-9_\-\.]+\\)*[a-zA-Z0-9_\-\.]+|\./(?:[a-zA-Z0-9_\-\.]+/)*[a-zA-Z0-9_\-\.]+)")
_ENV_VAR_RE = re.compile(r"(?<!\w)\$(?:[A-Z_][A-Z0-9_]{1,}|\{[A-Z_][A-Z0-9_]{1,}\})")
_URL_RE = re.compile(r"https?://[^\s<>\"']+|ftp://[^\s<>\"']+|www\.[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^\s<>\"']*")

# Default flat feature structure
DEFAULT_FORMATTING_FEATURES: Dict[str, Any] = {
    "paragraph_count": 0,
    "paragraph_length_distribution": {
        "mean": 0.0,
        "median": 0.0,
        "std": 0.0,
        "min": 0.0,
        "max": 0.0,
    },
    "blank_line_rate": 0.0,
    "bullet_usage_rate": 0.0,
    "numbered_list_rate": 0.0,
    "markdown_heading_rate": 0.0,
    "bold_rate": 0.0,
    "italic_rate": 0.0,
    "inline_code_rate": 0.0,
    "codeblock_rate": 0.0,
    "blockquote_rate": 0.0,
    "colon_usage_context": {},
    "semicolon_usage_context": {},
    "dash_type_distribution": {},
    "newline_after_punctuation_rate": 0.0,
    "shell_command_rate": 0.0,
    "code_language_distribution": {},
    "inline_path_rate": 0.0,
    "environment_variable_rate": 0.0,
    "url_rate": 0.0,
}


def _extract_text(msg: Any) -> str:
    """Safely extract string text from a message dictionary or string."""
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


def _classify_colon_contexts(text: str) -> List[str]:
    """Classify the syntactic/formatting context of colons in text."""
    contexts: List[str] = []
    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Find all colon positions in line
        for i, char in enumerate(line):
            if char != ":":
                continue
            # Check time format (e.g. 12:30)
            before = line[:i]
            after = line[i + 1:]
            if re.search(r"\b\d{1,2}$", before) and re.match(r"^\d{2}\b", after):
                contexts.append("in_time")
            elif before.endswith(("http", "https", "ftp", "file")):
                contexts.append("in_url")
            elif (i > 0 and line[i - 1] == ":") or (i + 1 < len(line) and line[i + 1] == ":"):
                contexts.append("in_code")
            elif re.match(r"^\s*$", after):
                contexts.append("end_of_line")
            elif re.search(r"^\s*[-*•·]?\s*[\"']?[a-zA-Z0-9_-]+[\"']?$", before):
                contexts.append("after_word")
            elif re.search(r"[a-zA-Z0-9_-]+\s+[a-zA-Z0-9_-]+$", before) and (not after or after.startswith(" ")):
                contexts.append("after_phrase")
            elif re.search(r"[\"']\w+[\"']\s*$", before):
                contexts.append("key_value")
            else:
                contexts.append("other")
    return contexts


def _classify_semicolon_contexts(text: str) -> List[str]:
    """Classify the syntactic/formatting context of semicolons in text."""
    contexts: List[str] = []
    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        for i, char in enumerate(line):
            if char != ";":
                continue
            before = line[:i]
            after = line[i + 1:]
            # Check emoticon e.g. ;) or ;-)
            if re.match(r"^[)\(\/DPpdDOo\*\-\^]", after):
                contexts.append("emoticon")
            elif re.search(r"&[a-zA-Z0-9#]+$", before):
                contexts.append("html_entity")
            elif not after.strip():
                contexts.append("code_statement")
            elif re.search(r"\w+$", before) and re.match(r"^\s+\w+", after):
                contexts.append("clause_separator")
            else:
                contexts.append("other")
    return contexts


def _extract_dashes(text: str) -> List[str]:
    """Extract dash tokens from text."""
    dashes: List[str] = []
    # Match em-dash, en-dash, horizontal bar, triple hyphen, double hyphen, single hyphen
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char == "—":
            dashes.append("—")
            pos += 1
        elif char == "–":
            dashes.append("–")
            pos += 1
        elif char == "―":
            dashes.append("―")
            pos += 1
        elif char == "-":
            if pos + 2 < len(text) and text[pos:pos + 3] == "---":
                dashes.append("---")
                pos += 3
            elif pos + 1 < len(text) and text[pos:pos + 2] == "--":
                dashes.append("--")
                pos += 2
            else:
                dashes.append("-")
                pos += 1
        else:
            pos += 1
    return dashes


def _is_shell_command_line(line: str) -> bool:
    """Check if a line matches common shell command patterns."""
    stripped = line.strip()
    if not stripped:
        return False
    if _SHELL_PROMPT_RE.match(line):
        return True
    first_token = stripped.split()[0].lower()
    return first_token in COMMON_SHELL_COMMANDS


def extract_formatting_features(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract structural and markdown formatting features from messages.

    Args:
        messages: List of dicts, each with a 'content' or 'text' field.

    Returns:
        JSON-serializable dictionary of formatting features.
    """
    if not messages:
        return {
            k: (dict(v) if isinstance(v, dict) else v)
            for k, v in DEFAULT_FORMATTING_FEATURES.items()
        }

    texts = [_extract_text(m) for m in messages]
    non_empty_texts = [t for t in texts if t]
    num_messages = len(messages)

    if not non_empty_texts:
        return {
            k: (dict(v) if isinstance(v, dict) else v)
            for k, v in DEFAULT_FORMATTING_FEATURES.items()
        }

    corpus = "\n".join(non_empty_texts)
    all_lines = [line for t in texts for line in t.splitlines()]
    total_lines = len(all_lines)

    # ── Paragraph Extraction & Distribution ─────────────────────────────────
    all_paragraphs: List[str] = []
    for text in texts:
        if not text:
            continue
        paras = [p.strip() for p in re.split(r"(?:\r?\n\s*){2,}", text) if p.strip()]
        all_paragraphs.extend(paras)

    para_count = len(all_paragraphs)
    if para_count > 0:
        para_lengths = [len(p) for p in all_paragraphs]
        para_mean = float(statistics.mean(para_lengths))
        para_median = float(statistics.median(para_lengths))
        para_std = float(statistics.stdev(para_lengths)) if para_count > 1 else 0.0
        para_min = float(min(para_lengths))
        para_max = float(max(para_lengths))
    else:
        para_mean = para_median = para_std = para_min = para_max = 0.0

    para_dist = {
        "mean": round(para_mean, 6),
        "median": round(para_median, 6),
        "std": round(para_std, 6),
        "min": round(para_min, 6),
        "max": round(para_max, 6),
    }

    # ── Line Level Metrics ──────────────────────────────────────────────────
    blank_lines = sum(1 for line in all_lines if not line.strip())
    blank_line_rate = (blank_lines / total_lines) if total_lines > 0 else 0.0

    bullet_lines = sum(1 for line in all_lines if _BULLET_RE.match(line))
    bullet_usage_rate = (bullet_lines / total_lines) if total_lines > 0 else 0.0

    numbered_lines = sum(1 for line in all_lines if _NUMBERED_LIST_RE.match(line))
    numbered_list_rate = (numbered_lines / total_lines) if total_lines > 0 else 0.0

    heading_lines = sum(1 for line in all_lines if _HEADING_RE.match(line))
    markdown_heading_rate = (heading_lines / total_lines) if total_lines > 0 else 0.0

    blockquote_lines = sum(1 for line in all_lines if _BLOCKQUOTE_RE.match(line))
    blockquote_rate = (blockquote_lines / total_lines) if total_lines > 0 else 0.0

    shell_lines = sum(1 for line in all_lines if _is_shell_command_line(line))
    shell_command_rate = (shell_lines / total_lines) if total_lines > 0 else 0.0

    # ── Markdown Formatting Elements ────────────────────────────────────────
    # Bold, Italic, Inline Code, Codeblocks
    bold_matches = _BOLD_RE.findall(corpus)
    bold_rate = len(bold_matches) / num_messages

    italic_matches = _ITALIC_RE.findall(corpus)
    italic_rate = len(italic_matches) / num_messages

    inline_code_matches = _INLINE_CODE_RE.findall(corpus)
    inline_code_rate = len(inline_code_matches) / num_messages

    codeblocks = _CODEBLOCK_RE.findall(corpus)
    codeblock_rate = len(codeblocks) / num_messages

    # Code languages from fence info
    code_languages = [cb[0].strip().lower() for cb in codeblocks if cb[0].strip()]
    if code_languages:
        lang_counts = Counter(code_languages)
        total_tagged = len(code_languages)
        code_language_dist = {
            lang: round(cnt / total_tagged, 6)
            for lang, cnt in lang_counts.most_common(20)
        }
    else:
        code_language_dist = {}

    # ── Colon & Semicolon Usage Context ─────────────────────────────────────
    colon_contexts = _classify_colon_contexts(corpus)
    if colon_contexts:
        colon_counts = Counter(colon_contexts)
        total_colons = len(colon_contexts)
        colon_usage_dist = {
            ctx: round(cnt / total_colons, 6)
            for ctx, cnt in colon_counts.most_common(50)
        }
    else:
        colon_usage_dist = {}

    semicolon_contexts = _classify_semicolon_contexts(corpus)
    if semicolon_contexts:
        semicolon_counts = Counter(semicolon_contexts)
        total_semicolons = len(semicolon_contexts)
        semicolon_usage_dist = {
            ctx: round(cnt / total_semicolons, 6)
            for ctx, cnt in semicolon_counts.most_common(50)
        }
    else:
        semicolon_usage_dist = {}

    # ── Dash Type Distribution ──────────────────────────────────────────────
    dashes = _extract_dashes(corpus)
    if dashes:
        dash_counts = Counter(dashes)
        total_dashes = len(dashes)
        dash_type_dist = {
            dash: round(cnt / total_dashes, 6)
            for dash, cnt in dash_counts.most_common(50)
        }
    else:
        dash_type_dist = {}

    # ── Newline After Punctuation Rate ──────────────────────────────────────
    punct_with_newline = len(re.findall(r"[.!?](?:\r?\n)", corpus))
    punct_with_space = len(re.findall(r"[.!?][ \t]+\S", corpus))
    total_punct_transitions = punct_with_newline + punct_with_space
    newline_after_punct_rate = (
        (punct_with_newline / total_punct_transitions)
        if total_punct_transitions > 0
        else 0.0
    )

    # ── Paths, Environment Variables, URLs ──────────────────────────────────
    # Clean URLs before path extraction so URLs aren't counted as paths
    cleaned_for_paths = _URL_RE.sub(" ", corpus)
    path_matches = _PATH_RE.findall(cleaned_for_paths)
    inline_path_rate = len(path_matches) / num_messages

    env_var_matches = _ENV_VAR_RE.findall(corpus)
    environment_variable_rate = len(env_var_matches) / num_messages

    url_matches = _URL_RE.findall(corpus)
    url_rate = len(url_matches) / num_messages

    return {
        "paragraph_count": int(para_count),
        "paragraph_length_distribution": para_dist,
        "blank_line_rate": round(float(blank_line_rate), 6),
        "bullet_usage_rate": round(float(bullet_usage_rate), 6),
        "numbered_list_rate": round(float(numbered_list_rate), 6),
        "markdown_heading_rate": round(float(markdown_heading_rate), 6),
        "bold_rate": round(float(bold_rate), 6),
        "italic_rate": round(float(italic_rate), 6),
        "inline_code_rate": round(float(inline_code_rate), 6),
        "codeblock_rate": round(float(codeblock_rate), 6),
        "blockquote_rate": round(float(blockquote_rate), 6),
        "colon_usage_context": colon_usage_dist,
        "semicolon_usage_context": semicolon_usage_dist,
        "dash_type_distribution": dash_type_dist,
        "newline_after_punctuation_rate": round(float(newline_after_punct_rate), 6),
        "shell_command_rate": round(float(shell_command_rate), 6),
        "code_language_distribution": code_language_dist,
        "inline_path_rate": round(float(inline_path_rate), 6),
        "environment_variable_rate": round(float(environment_variable_rate), 6),
        "url_rate": round(float(url_rate), 6),
    }
