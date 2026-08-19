"""
SPECTRA — tdata → .session converter
=====================================

Converts logged-in Telegram Desktop / Alternatives ``tdata`` folders into Telethon
SQLite ``.session`` files (plus a JSON sidecar holding ``api_id`` / ``api_hash``
/ ``user_id``), so the accounts can be driven by SPECTRA's archiver, discovery
crawler, and forwarder without re-login.

The heavy lifting (decrypting the MTP authorization block out of
``key_datas`` + the per-account ``...s`` files) is delegated to the
dependency-light ``tdata_reader`` library, which only requires ``telethon``.
The resulting ``auth_key`` + ``dc_id`` are then written into a native Telethon
``SQLiteSession`` so any Telethon-based tool can open them directly.

Usage from the CLI::

    ./spectra tdata2session
    ./spectra tdata2session --tdata /path/to/tdata --output sessions --register
    ./spectra tdata2session --passcode 1234 --string-sessions
"""
from __future__ import annotations

# ── Standard Library ──────────────────────────────────────────────────────
import json
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Third-party ───────────────────────────────────────────────────────────
try:
    from tdata_reader import read_all_tdata, read_tdata
    from tdata_reader.exceptions import TDataError
    HAS_TDATA_READER = True
except ImportError:  # pragma: no cover - optional at import time
    HAS_TDATA_READER = False

try:
    from telethon.sessions import SQLiteSession
    from telethon.crypto import AuthKey
    HAS_TELETHON = True
except ImportError:  # pragma: no cover
    HAS_TELETHON = False

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────
# Common tdata locations on Linux (Telegram Desktop + popular alternatives).
DEFAULT_TDATA_CANDIDATES: List[str] = [
    "~/.local/share/64Gram/tdata",
    "~/.local/share/TelegramDesktop/tdata",
    "~/.local/share/Telegram Desktop/tdata",
    "~/.telegram/tdata",
    "~/snap/telegram-desktop/current/.local/share/TelegramDesktop/tdata",
]

# Telegram's well-known DC IP map (used as a fallback if tdata_reader doesn't
# expose dc_ip / dc_port for an account).
DC_IPS: Dict[int, str] = {
    1: "149.154.175.50",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "91.108.56.130",
}


@dataclass
class ConvertedAccount:
    """Result of converting a single tdata account."""

    user_id: int
    dc_id: int
    api_id: int
    api_hash: str
    session_path: Path
    json_path: Path
    string_session: Optional[str] = None
    phone: Optional[str] = None
    username: Optional[str] = None
    device_model: Optional[str] = None
    system_version: Optional[str] = None


@dataclass
class ConversionReport:
    """Aggregate result of a conversion run."""

    tdata_path: Path
    output_dir: Path
    converted: List[ConvertedAccount] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"tdata source : {self.tdata_path}",
            f"output dir   : {self.output_dir}",
            f"converted    : {len(self.converted)}",
            f"skipped      : {len(self.skipped)}",
            f"errors       : {len(self.errors)}",
        ]
        if self.converted:
            lines.append("")
            lines.append("Converted accounts:")
            for acc in self.converted:
                lines.append(
                    f"  • user_id={acc.user_id}  dc={acc.dc_id}  "
                    f"api_id={acc.api_id}  → {acc.session_path.name}"
                )
        return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────
def autodetect_tdata() -> Optional[Path]:
    """Return the first existing default tdata location, if any."""
    for candidate in DEFAULT_TDATA_CANDIDATES:
        p = Path(os.path.expanduser(candidate))
        # A real tdata folder always has a key_datas file.
        if p.is_dir() and (p / "key_datas").exists():
            return p
    return None


def _safe_session_name(user_id: int, index: int) -> str:
    return f"spectra_tdata_{user_id}_{index}"


def list_tdata_accounts(
    tdata_path: Path,
    *,
    passcode: str = "",
    resolve: bool = False,
    output_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """
    Read a tdata folder and return a list of account summaries.

    Parameters
    ----------
    tdata_path:
        Path to the ``tdata`` folder.
    passcode:
        Local passcode if the tdata is passcode-protected.
    resolve:
        If True, connect each session to Telegram to resolve username, phone,
        and first/last name. Requires the sessions to be written first (or
        pass ``output_dir`` to use existing sessions). If False, only the
        fields stored in tdata (user_id, dc_id, api_id, device_model) are
        returned.
    output_dir:
        Directory to write temporary sessions into for resolution. If None
        and ``resolve`` is True, a temp directory is used and cleaned up.

    Returns
    -------
    List of dicts with keys: user_id, dc_id, api_id, device_model,
    system_version, and (if resolved) username, phone, first_name, last_name.
    """
    if not HAS_TDATA_READER:
        raise RuntimeError(
            "tdata-reader is not installed. Install it with: pip install tdata-reader"
        )

    tdata_path = Path(tdata_path).expanduser().resolve()
    if not tdata_path.is_dir():
        raise FileNotFoundError(f"tdata folder not found: {tdata_path}")

    try:
        accounts = read_all_tdata(str(tdata_path), passcode=passcode)
    except TDataError as exc:
        raise RuntimeError(f"Failed to read tdata ({tdata_path}): {exc}") from exc

    results: List[Dict[str, Any]] = []
    for idx, acc in enumerate(accounts, start=1):
        entry: Dict[str, Any] = {
            "index": idx,
            "user_id": acc.user_id or 0,
            "dc_id": acc.dc_id,
            "api_id": acc.api_id,
            "device_model": getattr(acc, "device_model", None),
            "system_version": getattr(acc, "system_version", None),
            "username": None,
            "phone": None,
            "first_name": None,
            "last_name": None,
        }
        results.append(entry)

    if resolve and results:
        # Caller should use resolve_account_info_async instead if inside
        # a running event loop. This path is for sync callers only.
        try:
            results = asyncio.run(_resolve_account_info_async(results, tdata_path, passcode, output_dir))
        except RuntimeError:
            # Already inside a running loop — caller should use the async version
            logger.warning("Cannot resolve usernames from sync context inside a running event loop")

    return results


async def resolve_account_info_async(
    accounts: List[Dict[str, Any]],
    tdata_path: Path,
    passcode: str = "",
    output_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Async version of account resolution — call from async handlers."""
    return await _resolve_account_info_async(accounts, tdata_path, passcode, output_dir)


async def _resolve_account_info_async(
    accounts: List[Dict[str, Any]],
    tdata_path: Path,
    passcode: str,
    output_dir: Optional[Path],
) -> List[Dict[str, Any]]:
    """Connect each session to resolve username/phone/name from Telegram."""
    import tempfile

    from telethon import TelegramClient

    tmp_dir = None
    if output_dir is None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="tdata_resolve_"))
        output_dir = tmp_dir
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    # Write sessions for all accounts (needed to connect).
    report = convert_tdata(
        tdata_path, output_dir,
        passcode=passcode, overwrite=True,
    )

    # Build user_id → session_path map.
    session_map = {acc.user_id: acc.session_path for acc in report.converted}

    for entry in accounts:
        uid = entry["user_id"]
        session_path = session_map.get(uid)
        if not session_path or not session_path.exists():
            continue
        try:
            client = TelegramClient(
                str(session_path.with_suffix("")),
                entry["api_id"],
                # We need the api_hash from the converted account
                next((a.api_hash for a in report.converted if a.user_id == uid), ""),
            )
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                entry["username"] = me.username
                entry["phone"] = me.phone
                entry["first_name"] = me.first_name
                entry["last_name"] = me.last_name
            await client.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to resolve user_id=%s: %s", uid, exc)

    # Clean up temp dir.
    if tmp_dir:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return accounts


def parse_account_filter(
    account_spec: Optional[str],
    username: Optional[str],
) -> tuple[Optional[set[int]], Optional[str]]:
    """
    Parse --account and --username CLI flags into a filter specification.

    Returns (user_id_filter, username_filter) where:
    - user_id_filter is None (all) or a set of ints
    - username_filter is None or a lowercase username string (without @)
    """
    if username:
        username = username.lstrip("@").lower()
        return None, username

    if account_spec and account_spec.lower() != "all":
        # Parse comma-separated user IDs
        try:
            ids = set()
            for part in account_spec.split(","):
                part = part.strip()
                if part:
                    ids.add(int(part))
            return ids, None
        except ValueError:
            raise ValueError(
                f"Invalid --account value '{account_spec}'. "
                "Use 'all', a numeric user_id, or comma-separated user_ids."
            )

    return None, None


def _write_sqlite_session(
    session_path: Path,
    dc_id: int,
    auth_key: bytes,
    server_address: str,
    port: int,
) -> None:
    """Write a native Telethon SQLiteSession file with the given auth key."""
    # SQLiteSession appends ".session" itself if not present; pass the stem.
    stem = str(session_path)
    if stem.endswith(".session"):
        stem = stem[: -len(".session")]

    session = SQLiteSession(stem)
    session.set_dc(dc_id, server_address, port)
    session.auth_key = AuthKey(data=auth_key)
    session.save()
    session.close()


def _write_json_sidecar(
    json_path: Path,
    *,
    user_id: int,
    dc_id: int,
    api_id: int,
    api_hash: str,
    server_address: str,
    port: int,
    phone: Optional[str],
    username: Optional[str],
    device_model: Optional[str],
    system_version: Optional[str],
    string_session: Optional[str],
) -> None:
    payload = {
        "user_id": user_id,
        "dc_id": dc_id,
        "api_id": api_id,
        "api_hash": api_hash,
        "server_address": server_address,
        "port": port,
        "phone": phone,
        "username": username,
        "device_model": device_model,
        "system_version": system_version,
        "string_session": string_session,
    }
    json_path.write_text(json.dumps(payload, indent=2))


# ── Core conversion ───────────────────────────────────────────────────────
def convert_tdata(
    tdata_path: Path,
    output_dir: Path,
    *,
    passcode: str = "",
    string_sessions: bool = False,
    overwrite: bool = False,
    user_id_filter: Optional[set] = None,
    username_filter: Optional[str] = None,
) -> ConversionReport:
    """
    Convert every logged-in account inside ``tdata_path`` into a Telethon
    ``.session`` file (plus a JSON sidecar) written into ``output_dir``.

    Parameters
    ----------
    tdata_path:
        Path to the ``tdata`` folder (the one containing ``key_datas``).
    output_dir:
        Directory where ``*.session`` + ``*.json`` files are written.
    passcode:
        Local passcode if the tdata is passcode-protected (empty otherwise).
    string_sessions:
        Also emit Telethon ``StringSession`` strings in the JSON sidecars.
    overwrite:
        Overwrite existing output files instead of skipping them.
    user_id_filter:
        If set, only convert accounts whose user_id is in this set.
    username_filter:
        If set, only convert the account whose Telegram username matches.
        Requires connecting to Telegram to resolve (all sessions are written
        first, then non-matching ones are deleted).
    """
    if not HAS_TDATA_READER:
        raise RuntimeError(
            "tdata-reader is not installed. Install it with: "
            "pip install tdata-reader"
        )
    if not HAS_TELETHON:
        raise RuntimeError(
            "telethon is not installed. Install it with: pip install telethon"
        )

    tdata_path = Path(tdata_path).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    if not tdata_path.is_dir():
        raise FileNotFoundError(f"tdata folder not found: {tdata_path}")
    if not (tdata_path / "key_datas").exists():
        raise FileNotFoundError(
            f"Not a valid tdata folder (missing key_datas): {tdata_path}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    report = ConversionReport(tdata_path=tdata_path, output_dir=output_dir)

    try:
        accounts = read_all_tdata(str(tdata_path), passcode=passcode)
    except TDataError as exc:
        raise RuntimeError(f"Failed to read tdata ({tdata_path}): {exc}") from exc

    if not accounts:
        report.errors.append(
            {"reason": "no_accounts", "detail": "No logged-in accounts found in tdata"}
        )
        return report

    for idx, acc in enumerate(accounts, start=1):
        try:
            auth_key = acc.auth_key
            if not auth_key or len(auth_key) != 256:
                report.skipped.append(
                    {
                        "user_id": getattr(acc, "user_id", None),
                        "reason": "no_valid_auth_key",
                    }
                )
                continue

            dc_id = acc.dc_id
            server_address = getattr(acc, "dc_ip", None) or DC_IPS.get(dc_id, "")
            port = getattr(acc, "dc_port", None) or 443
            user_id = acc.user_id or 0

            # ── Filter by user_id (fast path — no network needed) ──
            if user_id_filter is not None and user_id not in user_id_filter:
                report.skipped.append(
                    {"user_id": user_id, "reason": "filtered_by_user_id"}
                )
                continue
            api_id = acc.api_id
            api_hash = acc.api_hash
            device_model = getattr(acc, "device_model", None)
            system_version = getattr(acc, "system_version", None)
            phone = getattr(acc, "phone", None)
            username = getattr(acc, "username", None)

            session_name = _safe_session_name(user_id, idx)
            session_path = output_dir / f"{session_name}.session"
            json_path = output_dir / f"{session_name}.json"

            if session_path.exists() and not overwrite:
                report.skipped.append(
                    {
                        "user_id": user_id,
                        "reason": "exists",
                        "path": str(session_path),
                    }
                )
                continue

            # Write the native Telethon SQLite session.
            _write_sqlite_session(
                session_path,
                dc_id=dc_id,
                auth_key=auth_key,
                server_address=server_address,
                port=port,
            )

            # Optional StringSession (base64 of dc_id + auth_key).
            string_session = acc.to_string_session() if string_sessions else None

            _write_json_sidecar(
                json_path,
                user_id=user_id,
                dc_id=dc_id,
                api_id=api_id,
                api_hash=api_hash,
                server_address=server_address,
                port=port,
                phone=phone,
                username=username,
                device_model=device_model,
                system_version=system_version,
                string_session=string_session,
            )

            report.converted.append(
                ConvertedAccount(
                    user_id=user_id,
                    dc_id=dc_id,
                    api_id=api_id,
                    api_hash=api_hash,
                    session_path=session_path,
                    json_path=json_path,
                    string_session=string_session,
                    phone=phone,
                    username=username,
                    device_model=device_model,
                    system_version=system_version,
                )
            )
            logger.info(
                "Converted account user_id=%s dc=%s → %s",
                user_id,
                dc_id,
                session_path.name,
            )
        except Exception as exc:  # noqa: BLE001 - keep going on per-account errors
            report.errors.append(
                {
                    "user_id": getattr(acc, "user_id", None),
                    "reason": type(exc).__name__,
                    "detail": str(exc),
                }
            )
            logger.exception("Failed to convert account #%s", idx)

    # ── Filter by username is handled by the async caller ──
    # (see filter_by_username_async in the handler)

    return report


async def filter_by_username_async(
    report: ConversionReport, username_filter: str
) -> ConversionReport:
    """
    Connect each converted session, check get_me().username, and remove
    non-matching sessions (delete their files + remove from report).
    """
    from telethon import TelegramClient  # local import

    username_filter = username_filter.lstrip("@").lower()
    kept: List[ConvertedAccount] = []
    removed: List[Dict[str, Any]] = []

    for acc in report.converted:
        matched = False
        try:
            client = TelegramClient(
                str(acc.session_path.with_suffix("")),
                acc.api_id,
                acc.api_hash,
            )
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                if (me.username or "").lower() == username_filter:
                    # Update the account with resolved info.
                    acc.username = me.username
                    acc.phone = me.phone
                    matched = True
            await client.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Username resolution failed for user_id=%s: %s", acc.user_id, exc)

        if matched:
            kept.append(acc)
        else:
            # Delete the non-matching session + json files.
            try:
                acc.session_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            try:
                acc.json_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            removed.append(
                {"user_id": acc.user_id, "reason": "filtered_by_username",
                 "username_filter": username_filter}
            )

    report.converted = kept
    report.skipped.extend(removed)
    return report


def register_into_config(
    report: ConversionReport,
    config_path: Path,
    *,
    session_dir: Optional[Path] = None,
) -> int:
    """
    Register converted accounts into a SPECTRA ``spectra_config.json`` so the
    archiver / discovery crawler can pick them up automatically.

    Returns the number of newly-registered accounts.
    """
    from tgarchive.core.config_models import Config  # local import to avoid cycle

    cfg = Config(Path(config_path))
    accounts: List[Dict[str, Any]] = cfg.data.setdefault("accounts", [])

    existing_keys = {
        (a.get("api_id"), a.get("api_hash"), a.get("session_name"))
        for a in accounts
    }

    session_dir = Path(session_dir) if session_dir else report.output_dir
    added = 0
    for acc in report.converted:
        session_name = acc.session_path.stem  # without .session extension
        key = (acc.api_id, acc.api_hash, session_name)
        if key in existing_keys:
            continue
        accounts.append(
            {
                "api_id": acc.api_id,
                "api_hash": acc.api_hash,
                "session_name": session_name,
                "session_dir": str(session_dir),
                "user_id": acc.user_id,
                "phone": acc.phone,
            }
        )
        existing_keys.add(key)
        added += 1

    cfg.save()
    logger.info("Registered %s new account(s) into %s", added, config_path)
    return added
