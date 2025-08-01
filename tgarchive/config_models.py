from __future__ import annotations

import json
import logging
import os # Import os module
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Imports needed by Config class, originally from sync.py
from rich.console import Console

# Logger for Config class, can be configured as needed
logger = logging.getLogger(__name__) # Or use a more specific name like "tgarchive.config"
console = Console() # For messages from Config

# DEFAULT_CFG needs to be defined here or imported if it's truly global and large.
# For simplicity in this refactor, moving it here.
# Ensure all dependent constants like os.environ.get are handled or removed if not essential for Config itself.
DEFAULT_CFG: Dict[str, Any] = {
    "api_id": int(os.environ.get("TG_API_ID", 0)) if os.environ.get("TG_API_ID") else 0, # Added check for None
    "api_hash": os.environ.get("TG_API_HASH", ""),
    "accounts": [
        {
            "api_id": 123456,
            "api_hash": "0123456789abcdef0123456789abcdef",
            "session_name": "spectra_1",
        },
    ],
    "proxy": {
        "host": "rotating.proxyempire.io",
        "user": "PROXY_USER",
        "password": "PROXY_PASS",
        "ports": list(range(9000, 9010)),
    },
    "entity": "",
    "db_path": "spectra.sqlite3",
    "media_dir": "media",
    "download_media": True,
    "download_avatars": True,
    "media_mime_whitelist": [],
    "batch": 500,
    "sleep_between_batches": 1.0,
    "use_takeout": False,
    "avatar_size": 128,
    "collect_usernames": True,
    "sidecar_metadata": True,
    "archive_topics": True,
    "default_forwarding_destination_id": None,
    "forwarding": {
        "enable_deduplication": True,
        "secondary_unique_destination": None,
        "forward_with_attribution": True,
    },
    "cloud": {
        "auto_invite_accounts": True,
        "invitation_delays": {
            "min_seconds": 120,
            "max_seconds": 600,
            "variance": 0.3
        }
    },
    "vps": {
        "enabled": False,
        "host": "",
        "port": 22,
        "username": "",
        "key_path": "~/.ssh/id_rsa",
        "remote_base_path": "/data/spectra",
        "directory_structure": {
            "archives": "archives/{date}/{channel_name}",
            "media": "media/{type}/{date}",
            "text_files": "documents/text/{channel_name}",
            "cloud_downloads": "cloud/{date}/{channel_name}"
        },
        "sync_options": {
            "auto_sync": False,
            "sync_interval_minutes": 30,
            "compression": True,
            "delete_after_sync": False
        }
    },
    "grouping": {
        "strategy": "none",
        "time_window_seconds": 300
    }
}

@dataclass
class Config:
    path: Path = Path("spectra_config.json")
    data: Dict[str, Any] = field(default_factory=lambda: DEFAULT_CFG.copy())

    def __post_init__(self):
        auto_config_loaded = self._try_load_generated_configs()
        loaded_from_file = False
        if not auto_config_loaded and self.path.exists():
            try:
                file_data = json.loads(self.path.read_text())
                self.data.update(file_data)
                logger.info(f"Loaded config from {self.path}") # Changed from "legacy config"
                loaded_from_file = True
            except json.JSONDecodeError as exc:
                logger.warning("Bad JSON in config – using defaults (%s)", exc)

        if not loaded_from_file and not auto_config_loaded:
            self.save()
            console.print(
                f"[yellow]Config not found; default created at {self.path}. Edit credentials then rerun.[/yellow]"
            )
            # Avoid sys.exit(1) in a model class if possible, handle upstream or raise exception
            # For now, keeping original behavior for direct compatibility
            # Consider raising a custom ConfigNotFoundError for cleaner handling
            # For this refactor, to minimize changes, we'll keep sys.exit if it was the original intent for missing config.
            # However, it's better if the calling code (e.g. main()) handles this.
            # Let's assume for now that if this class is initialized, a config is expected or will be created.
            # The original code did sys.exit(1), so if this path is hit, it implies a critical setup failure.

        # Ensure all top-level keys from DEFAULT_CFG are present, and nested ones too
        for key, default_value in DEFAULT_CFG.items():
            if key not in self.data:
                self.data[key] = default_value
            elif isinstance(default_value, dict): # For nested dicts
                # Ensure all sub-keys from default are present in loaded config's dict
                current_sub_dict = self.data.setdefault(key, {})
                for sub_key, sub_default_value in default_value.items():
                    current_sub_dict.setdefault(sub_key, sub_default_value)
                    # Further nesting can be handled recursively if needed, but current DEFAULT_CFG is mostly 2 levels

        # Specific handling for accounts back-compat as in original
        if "accounts" not in self.data or not self.data.get("accounts"): # Check if accounts is missing or empty
            if "api_id" in self.data and self.data["api_id"] and "api_hash" in self.data and self.data["api_hash"]:
                 self.data["accounts"] = [
                    {
                        "api_id": self.data["api_id"],
                        "api_hash": self.data["api_hash"],
                        "session_name": "spectra_legacy", # Default name for legacy
                    }
                ]
            else: # If no legacy api_id/hash, ensure accounts is at least an empty list from default
                self.data["accounts"] = DEFAULT_CFG.get("accounts", [])


        self._normalize_accounts()

    def _try_load_generated_configs(self) -> bool:
        # This method relies on logger, Path, json
        # Assuming logger is available (e.g. logging.getLogger(__name__))
        config_paths = [
            Path("config/telegram_reporter_config.json"),
            Path("./config/telegram_reporter_config.json"),
            Path("../config/telegram_reporter_config.json"),
            Path.cwd() / "config" / "telegram_reporter_config.json",
        ]
        for cfg_path in config_paths:
            if cfg_path.exists():
                try:
                    generated_config = json.loads(cfg_path.read_text())
                    logger.info(f"Found generated config at {cfg_path}")
                    if "accounts" in generated_config:
                        self.data["telesmasher_accounts"] = generated_config["accounts"]
                        logger.info(f"Loaded {len(generated_config['accounts'])} accounts from generated config")
                    if "proxy" in generated_config:
                        self.data["proxy"] = generated_config["proxy"] # Overwrite proxy if found
                        logger.info("Loaded proxy settings from generated config")
                    return True
                except (json.JSONDecodeError, PermissionError) as e:
                    logger.warning(f"Error loading generated config from {cfg_path}: {e}")
        return False

    def _normalize_accounts(self):
        # This method relies on logger
        telesmasher_accounts = self.data.get("telesmasher_accounts", [])
        if telesmasher_accounts:
            current_accounts = self.data.get("accounts", [])
            # Create a set of (api_id, api_hash) for quick lookup of existing accounts
            existing_api_pairs = set()
            for acc in current_accounts:
                if acc.get("api_id") and acc.get("api_hash"):
                    existing_api_pairs.add((acc["api_id"], acc["api_hash"]))

            newly_added_accounts = 0
            for idx, acc_data in enumerate(telesmasher_accounts):
                if all(k in acc_data for k in ("phone_number", "api_id", "api_hash")):
                    api_id = acc_data["api_id"]
                    api_hash = acc_data["api_hash"]

                    if (api_id, api_hash) not in existing_api_pairs:
                        phone = acc_data["phone_number"].replace("+", "")
                        new_account = {
                            "api_id": api_id,
                            "api_hash": api_hash,
                            "session_name": f"spectra_auto_{phone}_{idx}",
                            "phone_number": acc_data["phone_number"],
                            "password": acc_data.get("password", ""),
                        }
                        current_accounts.append(new_account)
                        existing_api_pairs.add((api_id, api_hash)) # Add to set to prevent duplicates from telesmasher list
                        newly_added_accounts +=1

            if newly_added_accounts > 0:
                 logger.info(f"Normalized and added {newly_added_accounts} new accounts from TELESMASHER format.")
            self.data["accounts"] = current_accounts


    def save(self):
        # Make a copy to avoid serializing temporary/internal keys like 'telesmasher_accounts'
        data_to_save = self.data.copy()
        data_to_save.pop("telesmasher_accounts", None) # Remove before saving
        try:
            self.path.write_text(json.dumps(data_to_save, indent=2))
            logger.info(f"Configuration saved to {self.path}")
        except Exception as e:
            logger.error(f"Failed to save configuration to {self.path}: {e}")


    def __getitem__(self, item):
        return self.data[item]

    def __setitem__(self, key, value):
        self.data[key] = value
        # Potentially trigger save or a dirty flag if needed: self.save()

    @property
    def accounts(self) -> List[Dict[str, Any]]: # Added type hint
        return self.data.get("accounts", []) # Ensure it returns a list

    @property
    def default_forwarding_destination_id(self) -> Optional[str]: # Added type hint
        return self.data.get("default_forwarding_destination_id")

    @default_forwarding_destination_id.setter
    def default_forwarding_destination_id(self, value: Optional[str]):
        self.data["default_forwarding_destination_id"] = value

    @property
    def active_accounts(self) -> List[Dict[str, Any]]:
        # This method relies on logger
        all_accounts = self.accounts # Use the property
        preferred = [acc for acc in all_accounts
                    if acc.get("api_id") and acc.get("api_hash") and
                    acc.get("session_name", "").startswith("spectra_auto_")]
        return preferred if preferred else all_accounts

    def auto_select_account(self) -> Optional[Dict[str, Any]]:
        # This method relies on logger, random
        import random # Moved import here as it's only used here
        active = self.active_accounts
        if not active:
            logger.warning("No active accounts available for auto-selection.")
            return None
        selected = random.choice(active)
        logger.info(f"Auto-selected account: {selected.get('session_name', 'unknown_session')}")
        return selected

    @property
    def proxy_conf(self) -> Dict[str, Any]: # Added type hint
        return self.data.get("proxy", {}) # Ensure it returns a dict

    @property
    def forward_with_attribution(self) -> bool:
        return self.data.get("forwarding", {}).get("forward_with_attribution", True)

    @property
    def vps_conf(self) -> Dict[str, Any]: # Added type hint
        # Ensure the vps config is fully populated with defaults if accessed.
        vps_settings = self.data.setdefault("vps", {})
        default_vps_settings = DEFAULT_CFG.get("vps", {}) # Get from current DEFAULT_CFG
        for key, default_value in default_vps_settings.items():
            if key not in vps_settings:
                vps_settings[key] = default_value
            elif isinstance(default_value, dict):
                for sub_key, sub_default_value in default_value.items():
                    vps_settings[key].setdefault(sub_key, sub_default_value)
        return vps_settings

# Example of how it might be used (for testing this file independently)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    cfg_path = Path("test_spectra_config.json")

    # Clean up previous test file if exists
    if cfg_path.exists():
        cfg_path.unlink()

    console.print("[bold blue]Initializing Config (should create default)...[/]")
    config = Config(path=cfg_path)
    console.print(f"Config data: {config.data}")
    config.save()
    console.print(f"Config saved to {cfg_path}")

    console.print("\n[bold blue]Loading existing Config...[/]")
    config_loaded = Config(path=cfg_path)
    console.print(f"Loaded config accounts: {config_loaded.accounts}")
    console.print(f"Active accounts: {config_loaded.active_accounts}")
    console.print(f"Selected account: {config_loaded.auto_select_account()}")

    # Test adding telesmasher accounts
    config_loaded.data["telesmasher_accounts"] = [
        {"phone_number": "+1234567890", "api_id": 99999, "api_hash": "telesmasherhash1", "password": "pw1"},
        {"phone_number": "+0987654321", "api_id": 88888, "api_hash": "telesmasherhash2"},
        # Duplicate of default to test no re-add
        {"phone_number": "default_phone", "api_id": 123456, "api_hash": "0123456789abcdef0123456789abcdef"}
    ]
    config_loaded._normalize_accounts() # Call directly for test
    console.print(f"Accounts after telesmasher normalization: {config_loaded.accounts}")
    config_loaded.save()

    # Test getItem/setItem
    console.print(f"\n[bold blue]Current entity: {config_loaded['entity']}[/]")
    config_loaded['entity'] = '@testchannel'
    console.print(f"New entity: {config_loaded['entity']}")
    config_loaded.save()

    if cfg_path.exists():
        cfg_path.unlink()
        console.print(f"\nTest config file {cfg_path} removed.")

# Need to ensure os is imported if os.environ is used in DEFAULT_CFG
import os
