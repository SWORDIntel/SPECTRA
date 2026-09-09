"""
SPECTRA Intelligence — Boilerplate Filter
=========================================
Strips forwarding footers, link wrappers, bot signatures, and other
platform-injected boilerplate from message text before feature extraction.

This prevents non-author content (forwarded from, via @bot, t.me links,
etc.) from contaminating persona feature profiles.

Standard library only (re).
"""
from __future__ import annotations

import re
from typing import List, Tuple

# ── Boilerplate Patterns ───────────────────────────────────────────────────

# Telegram forwarding footer: "Forwarded from X" / "Переслано от X"
_FORWARD_HEADER_RE = re.compile(
    r"(?im)^(?:Forwarded from|Переслано от|Переслано из)\s+.+$"
)

# "via @BotName" footer (Telegram bot signature)
_VIA_BOT_RE = re.compile(
    r"(?im)\s*via\s+@[\w]{3,64}\s*$"
)

# Bare t.me / telegram.me link lines (often appended by forwards/shares)
_TME_LINK_LINE_RE = re.compile(
    r"(?im)^\s*https?://(?:t\.me|telegram\.me)/[^\s]+\s*$"
)

# Generic URL-only lines (link-only messages add no stylistic signal)
_URL_ONLY_LINE_RE = re.compile(
    r"^\s*https?://[^\s]+\s*$"
)

# "Sent from my iPhone/Android/BlackBerry" email signatures
_SENT_FROM_RE = re.compile(
    r"(?im)^Sent from my\s+\w+"
)

# Discord-style message link footer
_DISCORD_MSG_LINK_RE = re.compile(
    r"(?im)^\s*https?://(?:discord\.com|discordapp\.com)/channels/\d+/\d+/\d+\s*$"
)

# WhatsApp-style forwarded label
_WHATSAPP_FORWARDED_RE = re.compile(
    r"(?im)^Forwarded\s*$"
)

# "X reacted with Y" / "X joined the chat" system messages
_SYSTEM_MSG_RE = re.compile(
    r"(?im)^(?:.+\s+(?:reacted with|joined the chat|left the chat|was added|was removed)\b)"
)

# Multi-line forward block (Telegram "Forwarded from\nName\n" header)
_FORWARD_BLOCK_RE = re.compile(
    r"(?is)(?:Forwarded from|Переслано от|Переслано из)\s*\n.+\n"
)

# Patterns that mark the START of a boilerplate section — everything from
# the match onward is stripped.  These are true footers/signatures that
# appear AFTER the author's content.
_BOILERPLATE_START_PATTERNS: Tuple[re.Pattern, ...] = (
    _WHATSAPP_FORWARDED_RE,
    _SENT_FROM_RE,
)

# Forward headers that should be REMOVED but the following content kept.
# In Telegram, "Forwarded from X\n<message>" — the header is boilerplate
# but the message is the actual content we want to analyze.
_FORWARD_HEADER_STRIP_RE = re.compile(
    r"(?im)^(?:Forwarded from|Переслано от|Переслано из)\s+.+(?:\n|$)"
)

# Patterns that match lines to REMOVE (but keep surrounding text)
_LINE_REMOVE_PATTERNS: Tuple[re.Pattern, ...] = (
    _TME_LINK_LINE_RE,
    _DISCORD_MSG_LINK_RE,
    _VIA_BOT_RE,
    _SYSTEM_MSG_RE,
)


def strip_boilerplate(text: str) -> str:
    """Remove platform-injected boilerplate from a message.

    Args:
        text: Raw message text.

    Returns:
        Cleaned text with boilerplate lines/sections removed.
    """
    if not text:
        return text

    result = text

    # Strip forward headers (remove the header line but keep the forwarded content)
    result = _FORWARD_HEADER_STRIP_RE.sub("", result)

    # Strip from boilerplate start patterns to end of message
    for pat in _BOILERPLATE_START_PATTERNS:
        m = pat.search(result)
        if m:
            result = result[:m.start()].rstrip()

    # Remove individual matching lines
    for pat in _LINE_REMOVE_PATTERNS:
        result = pat.sub("", result)

    # Collapse multiple blank lines left by removals
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result.strip()


def is_url_only_message(text: str) -> bool:
    """Check if a message is effectively just a URL with no author content."""
    if not text or not text.strip():
        return False
    stripped = text.strip()
    # Single URL line
    if _URL_ONLY_LINE_RE.match(stripped):
        return True
    # URL + trailing whitespace/newlines
    lines = [l for l in stripped.split("\n") if l.strip()]
    if len(lines) == 1 and _URL_ONLY_LINE_RE.match(lines[0]):
        return True
    return False


def filter_messages(
    messages: List[dict],
    *,
    strip_footer: bool = True,
    drop_url_only: bool = True,
) -> List[dict]:
    """Filter and clean a list of message dicts in-place-ish.

    Args:
        messages: List of message dicts with 'content'/'text' field.
        strip_footer: If True, strip boilerplate from each message.
        drop_url_only: If True, drop messages that are URL-only after stripping.

    Returns:
        New list of cleaned message dicts (originals not mutated).
    """
    result = []
    for msg in messages:
        msg_copy = dict(msg) if isinstance(msg, dict) else msg
        if not isinstance(msg_copy, dict):
            result.append(msg_copy)
            continue

        text = (
            msg_copy.get("content")
            or msg_copy.get("text")
            or msg_copy.get("message")
            or msg_copy.get("caption")
            or msg_copy.get("raw_text")
            or ""
        )
        text = str(text)

        if strip_footer:
            text = strip_boilerplate(text)

        if drop_url_only and is_url_only_message(text):
            continue

        if not text.strip():
            continue

        # Update the first non-None field we found
        for field in ("content", "text", "message", "caption", "raw_text"):
            if field in msg_copy:
                msg_copy[field] = text
                break
        else:
            msg_copy["content"] = text

        result.append(msg_copy)

    return result


__all__ = [
    "strip_boilerplate",
    "is_url_only_message",
    "filter_messages",
]
