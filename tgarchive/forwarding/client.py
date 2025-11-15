"""
Manages the TelegramClient instance.
"""
from __future__ import annotations

import logging
from typing import Optional

from telethon import TelegramClient
from telethon.tl import types
from tgarchive.core.config_models import Config

class ClientManager:
    """
    Manages the TelegramClient instance.
    """

    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._client: Optional[TelegramClient] = None

    async def get_client(self, account_identifier: Optional[str] = None) -> TelegramClient:
        selected_account = None
        if account_identifier:
            for acc in self.config.accounts:
                if acc.get("phone_number") == account_identifier or acc.get("session_name") == account_identifier:
                    selected_account = acc
                    break
            if not selected_account:
                raise ValueError(f"Account '{account_identifier}' not found in configuration.")
        elif self.config.accounts:
            selected_account = self.config.accounts[0]
            self.logger.info(f"No account specified, using the first configured account: {selected_account.get('session_name')}")
        else:
            raise ValueError("No accounts configured.")

        session_name = selected_account.get("session_name")
        api_id = selected_account.get("api_id")
        api_hash = selected_account.get("api_hash")

        if not all([session_name, api_id, api_hash]):
            raise ValueError(f"Account {session_name or 'Unknown'} is missing critical configuration (session_name, api_id, or api_hash).")

        if self._client and self._client.session.filename == str(Config().path.parent / session_name) and self._client.is_connected():
             if await self._client.is_user_authorized():
                self.logger.debug(f"Reusing existing connected client for session: {session_name}")
                return self._client
             else:
                self.logger.warning(f"Existing client for {session_name} is no longer authorized. Attempting to reconnect.")
                await self._client.disconnect()
                self._client = None

        proxy = None
        proxy_conf = self.config.data.get("proxy")
        if proxy_conf and proxy_conf.get("enabled"):
            try:
                import socks
                proxy_type_map = {"socks5": socks.SOCKS5, "socks4": socks.SOCKS4, "http": socks.HTTP}
                p_type = proxy_conf.get("type", "socks5").lower()
                if p_type in proxy_type_map:
                    proxy = (
                        proxy_type_map[p_type],
                        proxy_conf["host"],
                        proxy_conf["port"],
                        True,
                        proxy_conf.get("username"),
                        proxy_conf.get("password"),
                    )
                else:
                    self.logger.warning(f"Unsupported proxy type: {p_type}")
            except KeyError as e:
                self.logger.warning(f"Proxy configuration is incomplete (missing {e}). Proceeding without proxy.")
            except ImportError:
                self.logger.warning("PySocks library not found. Proceeding without proxy.")

        client_path = str(Config().path.parent / session_name)
        self._client = TelegramClient(client_path, api_id, api_hash, proxy=proxy)

        self.logger.info(f"Connecting to Telegram with account: {session_name}")
        try:
            await self._client.connect()
        except ConnectionError as e:
            self.logger.error(f"Failed to connect to Telegram for account {session_name}: {e}")
            self._client = None
            raise

        if not await self._client.is_user_authorized():
            await self._client.disconnect()
            self._client = None
            raise ValueError(f"Account {session_name} is not authorized. Please check credentials or run authorization process.")

        self.logger.info(f"Successfully connected and authorized as {session_name}.")
        return self._client

    async def close(self):
        """Closes any active Telegram client connection."""
        if self._client and self._client.is_connected():
            self.logger.info("Closing client connection.")
            await self._client.disconnect()
            self._client = None
