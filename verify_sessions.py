#!/usr/bin/env python3
"""Verify all converted tdata sessions can actually connect to Telegram."""
import asyncio
import glob
import json
import os
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import AuthKeyError, UserDeactivatedError, UserDeactivatedBanError

SESSIONS_DIR = Path(__file__).parent / "sessions"


async def verify_one(session_stem: str, meta: dict) -> dict:
    """Connect a single session and call get_me(). Returns a result dict."""
    result = {
        "session": session_stem,
        "user_id_expected": meta.get("user_id"),
        "api_id": meta.get("api_id"),
        "status": "unknown",
        "detail": "",
    }
    client = TelegramClient(
        str(SESSIONS_DIR / session_stem),
        meta["api_id"],
        meta["api_hash"],
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            result["status"] = "UNAUTHORIZED"
            result["detail"] = "Session connected but is not authorized (auth key rejected)"
            return result
        me = await client.get_me()
        result["status"] = "OK"
        result["user_id_actual"] = me.id
        result["first_name"] = me.first_name
        result["last_name"] = me.last_name
        result["username"] = me.username
        result["phone"] = me.phone
        result["detail"] = f"id={me.id} name={me.first_name or ''} {me.last_name or ''}".strip()
        # Cross-check user_id matches what tdata_reader extracted
        if meta.get("user_id") and me.id != meta["user_id"]:
            result["status"] = "MISMATCH"
            result["detail"] = f"Expected user_id={meta['user_id']} but got {me.id}"
    except (AuthKeyError, UserDeactivatedError, UserDeactivatedBanError) as exc:
        result["status"] = "DEAD"
        result["detail"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        result["status"] = "ERROR"
        result["detail"] = f"{type(exc).__name__}: {exc}"
    finally:
        await client.disconnect()
    return result


async def main() -> int:
    session_files = sorted(glob.glob(str(SESSIONS_DIR / "*.session")))
    if not session_files:
        print(f"No .session files found in {SESSIONS_DIR}")
        return 1

    print(f"Verifying {len(session_files)} session(s) in {SESSIONS_DIR}\n")
    results = []
    for sf in session_files:
        stem = Path(sf).stem
        json_path = SESSIONS_DIR / f"{stem}.json"
        if not json_path.exists():
            results.append({"session": stem, "status": "ERROR", "detail": "missing JSON sidecar"})
            continue
        meta = json.loads(json_path.read_text())
        print(f"  → {stem} ...", flush=True)
        r = await verify_one(stem, meta)
        results.append(r)
        tag = {"OK": "[OK]", "UNAUTHORIZED": "[FAIL]", "DEAD": "[DEAD]",
               "MISMATCH": "[WARN]", "ERROR": "[ERROR]"}.get(r["status"], "[?]")
        print(f"    {tag} {r['status']}: {r['detail']}\n", flush=True)

    # Summary
    ok = sum(1 for r in results if r["status"] == "OK")
    bad = len(results) - ok
    print(f"=== Summary: {ok}/{len(results)} functional, {bad} problem(s) ===")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
