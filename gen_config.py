#!/usr/bin/env python3
"""
gen_configs.py  –  TELESMASHER helper

Writes two JSON config files into ~/.telegram_reporter/ with:
  • the seven Telegram accounts you provided
  • the rotating.proxyempire.io proxy settings
  • sane reporting defaults

Run:  python3 gen_configs.py
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# Logging ─ verbose, beginner-friendly messages
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(message)s"
)

# Where the JSON will be written ( ~/.telegram_reporter/ )
HOME_CONFIG_DIR = Path.home() / ".telegram_reporter"
HOME_CONFIG_DIR.mkdir(exist_ok=True)
logging.info("Target directory: %s", HOME_CONFIG_DIR)

# All seven accounts – feel free to extend this list later
ACCOUNTS_RAW = [
    ("+[PHONE_REDACTED]", [API_ID_REDACTED], "[API_HASH_REDACTED]"),
    ("+[PHONE_REDACTED]", [API_ID_REDACTED], "[API_HASH_REDACTED]"),
    ("+[PHONE_REDACTED]", [API_ID_REDACTED], "[API_HASH_REDACTED]"),
    ("+[PHONE_REDACTED]", [API_ID_REDACTED], "[API_HASH_REDACTED]"),
    ("+[PHONE_REDACTED]", [API_ID_REDACTED], "[API_HASH_REDACTED]"),
    ("+[PHONE_REDACTED]", [API_ID_REDACTED], "[API_HASH_REDACTED]"),
    ("+[PHONE_REDACTED]", [API_ID_REDACTED], "[API_HASH_REDACTED]"),
    ("+[PHONE_REDACTED]", [API_ID_REDACTED], "[API_HASH_REDACTED]")
]

def mk_account(phone: str, api_id: int, api_hash: str) -> dict:
    """Return a dict in the exact shape the reporter expects."""
    return {
        "phone_number": phone,
        "api_id": api_id,
        "api_hash": api_hash,
        "password": ""              # 2-FA password goes here (leave blank if none)
    }

ACCOUNTS = [mk_account(*row) for row in ACCOUNTS_RAW]

# Shared rotating-proxy block
PROXY_BLOCK = {
    "enabled": True,
    "host": "rotating.proxyempire.io",
    "user": "[PROXY_USER_REDACTED]",
    "password": "[PROXY_PASSWORD_REDACTED]",
    "ports": list(range(9000, 9010))
}

# ──────────────────────────────────────────────────────────────────────────────
# File 1 – telegram_reporter_config.json  (used by report.py --config …)
telegram_reporter_cfg = {
    "accounts": ACCOUNTS,
    "proxy": PROXY_BLOCK,
    "reporting": {
        "min_delay": 2,          # seconds between reports
        "max_delay": 7,
        "max_reports_per_session": 50
    },
    "generated": datetime.utcnow().isoformat() + "Z"
}

# File 2 – channel_reporter_config.json  (used by reporter.py --config …)
channel_reporter_cfg = {
    "accounts": ACCOUNTS,
    "channels": {
        "monitor": ["@example_channel"],      # edit as needed
        "target_keywords": ["scam", "spam", "fake", "illegal"],
        "auto_report": False
    },
    "proxy": PROXY_BLOCK,
    "reporting": {
        "min_delay": 2,
        "max_delay": 10
    },
    "generated": datetime.utcnow().isoformat() + "Z"
}

def write_cfg(filename: str, payload: dict) -> None:
    """Write JSON with pretty indentation and lock down permissions."""
    path = HOME_CONFIG_DIR / filename
    path.write_text(json.dumps(payload, indent=2))
    os.chmod(path, 0o600)          # user-only read/write
    logging.info("✓ Wrote %s", path)

write_cfg("telegram_reporter_config.json", telegram_reporter_cfg)
write_cfg("channel_reporter_config.json", channel_reporter_cfg)

logging.info("All done – configs ready to use!")
