"""
SPECTRA — Telegram Mini App (Web App) Deep-Link Parser
=======================================================

Parses Telegram Mini App URLs of the form:

    https://t.me/<bot_username>/app?startapp=<start_param>

Telegram passes ``startapp`` to the Web App via
``window.Telegram.WebApp.initDataUnsafe.start_param`` (and as the
``tgWebAppStartParam`` query arg on the actual Web App URL).  The
contents of ``startapp`` are an *application-defined* opaque string —
Telegram only guarantees it is URL-safe and <= 512 chars — so each bot
invents its own micro-encoding.

This module implements a tolerant decoder that handles the three
encodings seen in the wild:

1. **CamelCase concatenation** — ``keyValue`` (e.g. ``inviteCodeuoAAYt...``)
2. **Equals-delimited**        — ``key=value``  (e.g. ``adSegmentCode=freespin...``)
3. **Bare command**            — a leading segment with no key/value (e.g. ``openRouletteMain``)

Segments are separated by ``_`` (the only safe separator Telegram
guarantees will survive URL transmission unchanged).

The parser is integrated with :mod:`tgarchive.utils.discovery` so that
Mini App deep links discovered during crawl/archive operations are
extracted, decoded, and recorded alongside regular ``t.me/joinchat/``
invite links.

Usage (library)::

    from tgarchive.utils.webapp_parser import MiniAppURL
    m = MiniAppURL.parse("https://t.me/virus_play_bot/app?startapp=...")
    print(m.bot_username, m.command, m.params)

Usage (CLI)::

    python -m tgarchive.utils.webapp_parser "https://t.me/virus_play_bot/app?startapp=..."
"""
from __future__ import annotations

# ── Standard Library ──────────────────────────────────────────────────────
import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs, unquote

# ── Local Imports ──────────────────────────────────────────────────────────
# Reuse the shared SPECTRA logger when available; fall back to a module-level
# logger so this module stays importable standalone (discovery.py pulls in
# networkx/pandas/matplotlib which may not be installed in minimal envs).
try:
    from .discovery import logger  # type: ignore
except Exception:  # pragma: no cover - import-guard
    import logging
    logger = logging.getLogger("tgarchive.utils.webapp_parser")

# ── Link Pattern ───────────────────────────────────────────────────────────
# Matches ``https://t.me/<bot>/app?startapp=<payload>`` (and ``tg://resolve``
# style deep links).  Bot usernames are 5-32 chars of [A-Za-z0-9_].
# The ``app`` path segment is Telegram's canonical Mini App launcher.
MINIAPP_URL_PATTERN = re.compile(
    r'(?:https?://)?t\.me/'
    r'(?P<bot>[A-Za-z0-9_]{5,32})'
    r'/app'
    r'(?:\?(?P<query>[^\s]+))?'
)

# Telegram guarantees startapp payloads are URL-safe and <= 512 chars.
# Allowed chars in practice: [A-Za-z0-9_-] plus ``=`` for app-level kv
# encodings and ``.``/``~`` occasionally.  We tolerate the full URL-safe set.
_STARTAPP_ALLOWED = re.compile(r'^[A-Za-z0-9_\-=.~]+$')

# CamelCase key extractor: matches a leading camelCase identifier like
# ``inviteCode`` or ``adSegmentCode`` (lowercase run + one or more
# Capitalised chunks) and captures whatever follows as the opaque value.
# e.g. ``inviteCodeuoAAYtVHNUPG9imz`` → key="inviteCode", value="uoAAYtVHNUPG9imz".
# Crucially the value may itself start lowercase (random tokens often do),
# so a naive lowercase→uppercase split is insufficient — we require the key
# to be a *well-formed* camelCase word and treat the rest as the value.
_CAMEL_KEY_RE = re.compile(r'^([a-z]+(?:[A-Z][a-z]+)+)(.*)$')

# Known command prefixes used by gambling/casino Mini Apps — helps classify
# bare segments that have no key/value marker.  Extend as new schemas are seen.
_KNOWN_COMMANDS = {
    "openRouletteMain", "openSlots", "openWheel", "openCrash",
    "openDice", "openMines", "openBlackjack", "openPlinko",
    "openCase", "openShop", "openProfile", "openLeaderboard",
    "openAdmin", "openWallet", "openDeposit", "openWithdraw",
}

# Known parameter keys used by referral/ad-attribution Mini App schemas.
# When a segment's extracted key matches one of these, we confidently treat
# it as a ``key=value`` pair even if the value starts with a lowercase letter.
# Sorted by length (descending) so longest-prefix matching wins — e.g.
# ``adSegmentCode`` is tried before ``code``.
_KNOWN_PARAM_KEYS = {
    "inviteCode", "adSegmentCode", "refCode", "ref", "userId",
    "campaignId", "campaign", "source", "medium", "content",
    "bonus", "promo", "code", "token", "spinId", "betId",
}
_KNOWN_PARAM_KEYS_SORTED = sorted(_KNOWN_PARAM_KEYS, key=len, reverse=True)


@dataclass
class MiniAppParam:
    """A single decoded key/value (or bare) segment from a startapp payload."""
    raw: str
    key: Optional[str] = None
    value: Optional[str] = None
    encoding: str = "bare"  # "bare" | "equals" | "camelcase"


@dataclass
class MiniAppURL:
    """Structured representation of a Telegram Mini App deep link."""
    raw_url: str
    bot_username: str
    startapp: str = ""
    query_params: Dict[str, List[str]] = field(default_factory=dict)
    command: Optional[str] = None
    params: List[MiniAppParam] = field(default_factory=list)

    # ── Constructors ───────────────────────────────────────────────────────
    @classmethod
    def parse(cls, url: str) -> "MiniAppURL":
        """Parse a ``t.me/<bot>/app?startapp=...`` URL into structured fields.

        Tolerates missing scheme, surrounding whitespace, and ``tg://`` style
        deep links (which are normalised to ``https://t.me/``).
        """
        if not url or not isinstance(url, str):
            raise ValueError("url must be a non-empty string")

        raw = url.strip()
        # Normalise tg://resolve?domain=<bot>&startapp=... → t.me/<bot>/app
        if raw.startswith("tg://"):
            raw = _normalise_tg_scheme(raw)

        m = MINIAPP_URL_PATTERN.search(raw)
        if not m:
            raise ValueError(f"Not a Telegram Mini App URL: {url!r}")

        bot = m.group("bot")
        query = m.group("query") or ""
        qs = parse_qs(query, keep_blank_values=True)

        startapp = ""
        # startapp may appear under either ``startapp`` or ``startApp``.
        for key in ("startapp", "startApp", "tgWebAppStartParam"):
            if key in qs and qs[key]:
                startapp = qs[key][0]
                break
        startapp = unquote(startapp)

        # Telegram caps startapp at 512 chars.  Reject oversized payloads to
        # bound resource use and prevent log/storage pollution from adversarial
        # inputs (a 10k-char payload would otherwise be stored verbatim).
        if len(startapp) > 512:
            logger.warning(
                "startapp payload exceeds Telegram's 512-char limit (%d chars); "
                "truncating for safety", len(startapp),
            )
            startapp = startapp[:512]

        if startapp and not _STARTAPP_ALLOWED.match(startapp):
            logger.warning(
                "startapp payload contains unusual characters: %r", startapp
            )

        instance = cls(
            raw_url=url.strip(),
            bot_username=bot,
            startapp=startapp,
            query_params=qs,
        )
        instance._decode_payload()
        return instance

    # ── Decoding ───────────────────────────────────────────────────────────
    def _decode_payload(self) -> None:
        """Split ``startapp`` into a leading command + ordered param list."""
        if not self.startapp:
            return

        segments = self.startapp.split("_")
        decoded: List[MiniAppParam] = []

        for i, seg in enumerate(segments):
            if not seg:
                continue

            # 1. Equals-delimited: ``key=value``
            if "=" in seg:
                k, _, v = seg.partition("=")
                decoded.append(MiniAppParam(
                    raw=seg, key=k or None, value=v or None, encoding="equals",
                ))
                continue

            # 2. Bare command on the first segment, OR a known command anywhere.
            if i == 0 and seg in _KNOWN_COMMANDS:
                self.command = seg
                decoded.append(MiniAppParam(raw=seg, encoding="bare"))
                continue

            # 3. Known parameter key prefix (longest-first).  This is the
            #    authoritative split when the value starts with a lowercase
            #    letter — case alone cannot disambiguate ``inviteCode`` from
            #    ``inviteCodeuo``, so we rely on the known-key list.
            matched_key = None
            for k in _KNOWN_PARAM_KEYS_SORTED:
                if seg.startswith(k) and len(seg) > len(k):
                    matched_key = k
                    break
                if seg == k:
                    matched_key = k
                    break
            if matched_key:
                value = seg[len(matched_key):] or None
                decoded.append(MiniAppParam(
                    raw=seg, key=matched_key, value=value, encoding="camelcase",
                ))
                continue

            # 4. CamelCase concatenation fallback: ``fooBar Baz123``.
            #    Extract a well-formed camelCase key prefix; the rest is the
            #    opaque value.  Only used when no known key matched.
            m = _CAMEL_KEY_RE.match(seg)
            if m:
                key, value = m.group(1), m.group(2)
                # Only treat as a kv pair if there's a value, OR the key is a
                # known parameter name (otherwise a bare camelCase command like
                # ``openRouletteMain`` would be misread as a key with empty value).
                if value or key in _KNOWN_PARAM_KEYS:
                    decoded.append(MiniAppParam(
                        raw=seg, key=key, value=value or None, encoding="camelcase",
                    ))
                    continue

            # 5. Fallback: treat as bare token.
            if i == 0 and self.command is None:
                self.command = seg
            decoded.append(MiniAppParam(raw=seg, encoding="bare"))

        self.params = decoded

        # If the first bare segment wasn't a known command but looks like one,
        # promote it.  Heuristic: starts with ``open`` / ``go`` / ``show``.
        if self.command is None and decoded:
            first = decoded[0]
            if first.encoding == "bare" and re.match(
                r'^(open|go|show|launch|start)[A-Z]', first.raw
            ):
                self.command = first.raw

    # ── Accessors ──────────────────────────────────────────────────────────
    def param_dict(self) -> Dict[str, Optional[str]]:
        """Flatten decoded params into a ``{key: value}`` dict (bare → key=raw)."""
        out: Dict[str, Optional[str]] = {}
        for p in self.params:
            if p.encoding == "bare":
                out[p.raw] = None
            elif p.key is not None:
                out[p.key] = p.value
        return out

    def invite_code(self) -> Optional[str]:
        """Convenience accessor for the ``inviteCode`` referral field."""
        return self.param_dict().get("inviteCode")

    def ad_segment(self) -> Optional[str]:
        """Convenience accessor for the ``adSegmentCode`` attribution field."""
        return self.param_dict().get("adSegmentCode")

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-friendly dict (for DB storage / API responses)."""
        d = asdict(self)
        d["params"] = [
            {"raw": p.raw, "key": p.key, "value": p.value, "encoding": p.encoding}
            for p in self.params
        ]
        d["decoded"] = self.param_dict()
        return d

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"MiniAppURL(bot=@{self.bot_username}, command={self.command!r}, "
            f"params={self.param_dict()})"
        )


# ── Helpers ────────────────────────────────────────────────────────────────
def _normalise_tg_scheme(raw: str) -> str:
    """Convert ``tg://resolve?domain=...&startapp=...`` to ``https://t.me/.../app``."""
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    domain = (qs.get("domain") or [""])[0]
    startapp = (qs.get("startapp") or qs.get("startApp") or [""])[0]
    if not domain:
        return raw
    if startapp:
        return f"https://t.me/{domain}/app?startapp={startapp}"
    return f"https://t.me/{domain}/app"


# ── Discovery Integration ──────────────────────────────────────────────────
def find_miniapp_links(text: str) -> List[MiniAppURL]:
    """Scan free text and return every Mini App deep link found.

    Designed to be called from
    :meth:`tgarchive.utils.discovery.GroupDiscovery.extract_from_entity`
    alongside the existing :data:`USERNAME_PATTERN` / :data:`INVITE_LINK_PATTERN`
    passes.
    """
    if not text:
        return []
    out: List[MiniAppURL] = []
    for m in MINIAPP_URL_PATTERN.finditer(text):
        candidate = m.group(0)
        # Re-attach scheme if the regex matched a bare ``t.me/...`` fragment.
        if not candidate.startswith("http"):
            candidate = "https://" + candidate
        try:
            out.append(MiniAppURL.parse(candidate))
        except ValueError:
            # Skip malformed fragments rather than aborting the whole scan.
            logger.debug("Skipping malformed Mini App fragment: %r", candidate)
    return out


# ── CLI ────────────────────────────────────────────────────────────────────
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="webapp_parser",
        description="Decode a Telegram Mini App (t.me/<bot>/app?startapp=) deep link.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("url", nargs="?", help="The Mini App URL to decode.")
    p.add_argument("--json", action="store_true", help="Emit full structured JSON.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    if not args.url:
        print("error: a URL argument is required", file=sys.stderr)
        return 2

    try:
        parsed = MiniAppURL.parse(args.url)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(parsed.to_dict(), indent=2, ensure_ascii=False))
        return 0

    # Human-readable summary.
    print(f"Bot:        @{parsed.bot_username}")
    print(f"Command:    {parsed.command or '(none)'}")
    print(f"Invite:     {parsed.invite_code() or '(none)'}")
    print(f"Ad segment: {parsed.ad_segment() or '(none)'}")
    print(f"Segments:")
    for p in parsed.params:
        if p.encoding == "bare":
            print(f"  - {p.raw}  [bare]")
        else:
            print(f"  - {p.key} = {p.value}  [{p.encoding}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
