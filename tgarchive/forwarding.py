"""
Handles forwarding of message attachments between Telegram entities.
"""
from __future__ import annotations

import logging
import asyncio # Added for asyncio.sleep
from typing import Optional, Set, List, Tuple # Added List, Tuple
import hashlib # Added for deduplication
import re # For filename grouping
from datetime import datetime, timezone, timedelta # Added for deduplication timestamp, timedelta for time grouping

# Third-party imports
from telethon import TelegramClient, errors as telethon_errors
from telethon.tl import types
from telethon.tl.types import Message as TLMessage, InputPeerChannel, User, Channel
from telethon.errors import RPCError, ChannelPrivateError, UserDeactivatedError, AuthKeyError, UserBannedInChannelError, ChatAdminRequiredError

# Local application imports
from tgarchive.db import SpectraDB
from tgarchive.config_models import Config, DEFAULT_CFG # Import from new location

logger = logging.getLogger("tgarchive.forwarding")

class AttachmentForwarder:
    """
    Manages forwarding of attachments from an origin to a destination Telegram entity.
    """

    def __init__(self, config: Config, db: Optional[SpectraDB] = None,
                 forward_to_all_saved_messages: bool = False,
                 prepend_origin_info: bool = False,
                 destination_topic_id: Optional[int] = None,
                 secondary_unique_destination: Optional[str] = None,
                 enable_deduplication: bool = True,
                 grouping_strategy: str = "none",  # "none", "filename", "time"
                 grouping_time_window_seconds: int = 300): # 5 minutes default
        """
        Initializes the AttachmentForwarder.
        Enhanced with deduplication and grouping support.

        Args:
            config: The SPECTRA configuration object.
            db: An optional SpectraDB instance for database interactions.
            forward_to_all_saved_messages: If True, forward to all accounts' Saved Messages.
            prepend_origin_info: If True, prepend origin info to message text.
            destination_topic_id: Optional topic ID for the destination.
            secondary_unique_destination: Channel ID for unique messages only.
            enable_deduplication: Enable duplicate detection.
            grouping_strategy: Strategy for grouping files ("none", "filename", "time").
            grouping_time_window_seconds: Time window for time-based grouping.
        """
        self.config = config
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._client: Optional[TelegramClient] = None
        self.forward_to_all_saved_messages = forward_to_all_saved_messages
        self.prepend_origin_info = prepend_origin_info
        self.destination_topic_id = destination_topic_id

        # Deduplication related attributes
        self.enable_deduplication = enable_deduplication
        self.secondary_unique_destination = secondary_unique_destination
        self.message_hashes: Set[str] = set()  # In-memory cache for hashes

        # Grouping related attributes
        self.grouping_strategy = grouping_strategy.lower()
        self.grouping_time_window_seconds = grouping_time_window_seconds
        if self.grouping_strategy not in ["none", "filename", "time"]:
            self.logger.warning(f"Invalid grouping strategy '{self.grouping_strategy}'. Defaulting to 'none'.")
            self.grouping_strategy = "none"

        self.logger.info(f"File grouping strategy: {self.grouping_strategy}")
        if self.grouping_strategy == "time":
            self.logger.info(f"Grouping time window: {self.grouping_time_window_seconds} seconds")

        # Regex to capture base, part identifier (and number within), and full extension (including multi-part like .tar.gz)
        # Group 1: base_name
        # Group 2: full part string (e.g., _part1, _1, (1))
        # Group 1: base_name
        # Group 2: full part string (e.g., _part1, _1, (1), .part1, .1)
        # Groups for part numbers:
        #   3: for _part(\d+)
        #   4: for _(\d+)
        #   5: for \s\((\d+)\)
        #   7: for \.part(\d+) (note: group 6 is the start of this pattern)
        # Simplified Regex:
        # Group 1: base_name (non-greedy)
        # Group 2: part_separator_and_identifier (e.g., "_part", ".part", "_", ".", " (")
        # Group 1: base_name
        # Group 2: full part string (e.g., _part1, _1, (1), .part1, .1)
        # Groups for part numbers within Group 2's alternatives:
        #   3: for _part(\d+)
        #   4: for _(\d+)
        #   5: for \s\((\d+)\)
        #   6: for \.part(\d+)
        #   7: for \.(\d+)
        # Group 8: full extension (e.g., .rar, .tar.gz, or empty if no extension)
        self.filename_group_pattern = re.compile(
            r"(.+?)"  # Group 1: base_name (non-greedy)
            r"((?:_part(\d+))|(?:_(\d+))|(?:\s\((\d+)\))|(?:\.part(\d+))|(?:\.(\d+)))?"  # Group 2: Full Part String (optional)
            # Inner groups for numbers: 3, 4, 5, 6, 7
            r"((?:\.[a-zA-Z0-9]+)+|)$",  # Group 8: Extension
            re.IGNORECASE
        )
        if self.forward_to_all_saved_messages:
            self.logger.info("Forwarding to 'Saved Messages' of all configured accounts is ENABLED.")
        if self.prepend_origin_info:
            self.logger.info("Prepending origin info to forwarded messages is ENABLED.")
        if self.destination_topic_id:
            self.logger.info(f"Forwarding to destination topic ID: {self.destination_topic_id}")
        if self.enable_deduplication:
            self.logger.info("Deduplication is ENABLED.")
            if self.secondary_unique_destination:
                self.logger.info(f"Unique messages will be forwarded to secondary destination: {self.secondary_unique_destination}")
            if self.db:
                self._init_dedup_table()
                self._load_existing_hashes() # Load hashes from DB into memory
            else:
                self.logger.warning("Deduplication is enabled, but no database is configured. Deduplication will be in-memory only for this session.")
        else:
            self.logger.info("Deduplication is DISABLED.")

    def _init_dedup_table(self):
        """Create deduplication tracking table if it doesn't exist."""
        if not self.db:
            self.logger.error("Database not available, cannot initialize dedup table.")
            return
        try:
            self.db.conn.execute("""
                CREATE TABLE IF NOT EXISTS forwarded_messages (
                    hash TEXT PRIMARY KEY,
                    origin_id TEXT,
                    destination_id TEXT,
                    message_id INTEGER,
                    forwarded_at TEXT,
                    content_preview TEXT
                )
            """)
            self.db.conn.commit()
            self.logger.info("Deduplication table 'forwarded_messages' initialized successfully.")
        except Exception as e:
            self.logger.error(f"Failed to create/ensure dedup table 'forwarded_messages': {e}", exc_info=True)

    def _load_existing_hashes(self):
        """Load existing message hashes from the database into the in-memory set."""
        if not self.db:
            self.logger.warning("Database not available, cannot load existing hashes for deduplication.")
            return
        try:
            cursor = self.db.conn.execute("SELECT hash FROM forwarded_messages")
            count = 0
            for row in cursor:
                self.message_hashes.add(row[0])
                count += 1
            self.logger.info(f"Loaded {count} existing message hashes into memory for deduplication.")
        except Exception as e:
            self.logger.error(f"Failed to load existing message hashes from database: {e}", exc_info=True)

    def _compute_message_hash(self, message: TLMessage) -> str:
        """Compute a unique hash for message content (text and media)."""
        content_parts = []

        # Add message text
        if message.text:
            content_parts.append(message.text)

        # Add media identifiers (if media exists)
        if message.media:
            # General media attributes
            if hasattr(message.media, 'id'): # Common for Photo, Document
                content_parts.append(f"media_id:{message.media.id}")
            if hasattr(message.media, 'access_hash'): # Common for Photo, Document
                content_parts.append(f"media_hash:{message.media.access_hash}")

            # Specific file attributes if message.file exists (for documents, videos, photos etc.)
            if message.file:
                if hasattr(message.file, 'id') and message.file.id is not None: # Ensure ID is not None
                    content_parts.append(f"file_id:{message.file.id}")
                if hasattr(message.file, 'size') and message.file.size is not None:
                    content_parts.append(f"file_size:{message.file.size}")

            if isinstance(message.media, types.MessageMediaWebPage) and hasattr(message.media.webpage, 'url'):
                 content_parts.append(f"webpage_url:{message.media.webpage.url}")

        if not content_parts and message.media:
            content_parts.append(f"media_type:{type(message.media).__name__}")

        if not content_parts and not message.text:
             content_parts.append(f"message_obj_id:{message.id}")

        content_string = "|".join(sorted(str(p) for p in content_parts))
        return hashlib.sha256(content_string.encode('utf-8')).hexdigest()

    def _compute_group_hash(self, message_group: List[TLMessage]) -> str:
        """Computes a hash for an entire group of messages."""
        if not message_group:
            return ""

        individual_hashes = sorted([self._compute_message_hash(msg) for msg in message_group])
        combined_hash_input = "|".join(individual_hashes)
        return hashlib.sha256(combined_hash_input.encode('utf-8')).hexdigest()

    async def _is_duplicate(self, message_group: List[TLMessage]) -> bool:
        """Check if a message group has been forwarded before using its combined hash."""
        if not self.enable_deduplication or not message_group:
            return False

        group_hash = self._compute_group_hash(message_group)
        representative_msg_id = message_group[0].id

        if group_hash in self.message_hashes:
            self.logger.info(f"Message group starting with ID {representative_msg_id} (group hash: {group_hash[:8]}...) found in memory cache as duplicate.")
            return True

        if self.db:
            try:
                result = self.db.conn.execute(
                    "SELECT 1 FROM forwarded_messages WHERE hash = ?",
                    (group_hash,)
                ).fetchone()

                if result:
                    self.message_hashes.add(group_hash)
                    self.logger.info(f"Message group starting with ID {representative_msg_id} (group hash: {group_hash[:8]}...) found in DB as duplicate.")
                    return True
            except Exception as e:
                self.logger.error(f"Error checking duplicate group in DB for hash {group_hash[:8]}...: {e}", exc_info=True)
        return False

    async def _record_forwarded(self, message_group: List[TLMessage], origin_id: str, dest_id: str):
        """Record that a message group was forwarded by storing its combined hash."""
        if not self.enable_deduplication or not self.db or not message_group:
            return

        group_hash = self._compute_group_hash(message_group)
        self.message_hashes.add(group_hash)

        representative_message = message_group[0]
        content_preview = f"Group of {len(message_group)} file(s)."
        if len(message_group) == 1:
            if representative_message.text:
                content_preview = (representative_message.text[:100] + '...') if len(representative_message.text) > 100 else representative_message.text
            elif representative_message.file and representative_message.file.name:
                content_preview = f"File: {getattr(representative_message.file, 'name', 'N/A')}"
        else:
            if representative_message.file and representative_message.file.name:
                 content_preview += f" Starts with: {getattr(representative_message.file, 'name', 'N/A')}"

        try:
            self.db.conn.execute("""
                INSERT OR IGNORE INTO forwarded_messages
                (hash, origin_id, destination_id, message_id, forwarded_at, content_preview)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                group_hash,
                str(origin_id),
                str(dest_id),
                representative_message.id,
                datetime.now(timezone.utc).isoformat(),
                content_preview
            ))
            self.db.conn.commit()
            self.logger.info(f"Recorded forwarded message group (representative ID {representative_message.id}, group hash {group_hash[:8]}...) to DB.")
        except Exception as e:
            self.logger.error(f"Failed to record forwarded message group (group hash {group_hash[:8]}...) to DB: {e}", exc_info=True)

    async def _get_client(self, account_identifier: Optional[str] = None) -> TelegramClient:
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

    def _parse_filename_for_grouping(self, filename: str) -> Optional[Tuple[str, str, int, str]]:
        if not filename:
            return None

        name_sans_ext = filename
        current_ext = ""

        # 1. Handle known multi-part extensions first
        common_multi_extensions = {
            '.tar.gz': '.tar.gz', '.tar.bz2': '.tar.bz2', '.tar.xz': '.tar.xz',
        }
        lower_filename = filename.lower()
        for multi_ext_key, actual_ext_val in common_multi_extensions.items():
            if lower_filename.endswith(multi_ext_key):
                name_sans_ext = filename[:-len(actual_ext_val)]
                current_ext = actual_ext_val
                break

        # 2. If not a multi-part, get single extension
        if not current_ext:
            if '.' in name_sans_ext: # Check on potentially already stripped name_sans_ext
                parts = name_sans_ext.rsplit('.', 1)
                # Handle cases like ".bashrc" where parts[0] would be empty
                if len(parts) == 2 : # parts[0] can be empty here
                    name_sans_ext = parts[0]
                    current_ext = "." + parts[1]
                # If no dot or only at start and no base, name_sans_ext remains as is, current_ext is ""
            # else: no dot, name_sans_ext is filename, current_ext is ""

        # 3. Define part regexes that match *standalone* part strings.
        #    (pattern_regex, number_group_index_in_pattern)
        #    Order can matter if a string could match multiple (e.g., ".part1" vs ".1").
        #    More specific patterns (like those with "part") should come first.
        standalone_part_regexes = [
            (re.compile(r"^\.part(\d+)$", re.IGNORECASE), 1),  # e.g., ".part1"
            (re.compile(r"^_part(\d+)$", re.IGNORECASE), 1),  # e.g., "_part1"
            (re.compile(r"^\s*\((\d+)\)$", re.IGNORECASE), 1),# e.g., " (1)" (space is part of it)
            # Removed purely numeric patterns like r"^\.(\d{1,4})$" from here,
            # as they are too general for classifying a standard-looking extension as a part.
            # These numeric patterns are better suited for finding parts at the end of a base name (step 4).
        ]

        # 3a. Check if the extracted 'current_ext' is actually a part indicator.
        # This handles cases like "filename.part1" (no further real extension).
        if current_ext: # Only if there was something that looked like an extension
            for pattern, num_idx in standalone_part_regexes:
                match = pattern.fullmatch(current_ext) # Must match the whole extension string
                if match:
                    number_str = match.group(num_idx)
                    try:
                        part_number = int(number_str)
                        # Yes, the 'extension' was a part. True extension is empty.
                        # name_sans_ext is already the base. current_ext is the part_string.
                        return name_sans_ext, current_ext, part_number, ""
                    except ValueError:
                        pass # Should not happen with \d+

        # 4. If current_ext wasn't a part, look for part indicators at the end of name_sans_ext.
        #    Part regexes here are anchored to the end of the string ($).
        #    (pattern_regex, whole_part_group_idx, number_group_idx_in_pattern)
        part_regexes_at_end = [
            (re.compile(r"(\.part(\d+))$", re.IGNORECASE), 1, 2),
            (re.compile(r"(_part(\d+))$", re.IGNORECASE), 1, 2),
            (re.compile(r"(\s*\((\d+)\))$", re.IGNORECASE), 0, 2), # Group 0 for whole match " (N)"
            (re.compile(r"(\.(\d{1,4}))$", re.IGNORECASE), 1, 2),
            (re.compile(r"(_(\d{1,4}))$", re.IGNORECASE), 1, 2),
        ]

        for pattern, whole_part_idx, num_idx in part_regexes_at_end:
            match = pattern.search(name_sans_ext)
            if match:
                part_string = match.group(whole_part_idx)
                number_str = match.group(num_idx)
                base_name = name_sans_ext[:match.start(whole_part_idx)] # Use start of whole_part_idx

                # Handle case like " (1)" where base_name might have a trailing space
                # if part_string itself doesn't include it from group 0.
                if whole_part_idx == 0 and base_name.endswith(" ") and not part_string.startswith(" "): # For " (N)"
                    base_name = base_name.rstrip(" ")

                # If base_name became empty and part_string is the whole name_sans_ext
                # (e.g. name_sans_ext was "_part1", matched by "(_part(\d+))$")
                if not base_name and part_string == name_sans_ext:
                    return name_sans_ext, "", 0, current_ext # Treat as base, no part

                try:
                    part_number = int(number_str)
                    return base_name, part_string, part_number, current_ext
                except ValueError:
                    continue # Should not happen

        # 5. No part indicator found by any means. name_sans_ext is the final base.
        return name_sans_ext, "", 0, current_ext

    def _group_messages(self, messages: List[TLMessage]) -> List[List[TLMessage]]:
        if not messages:
            return []

        self.logger.debug(f"Starting message grouping with strategy: {self.grouping_strategy} for {len(messages)} messages.")

        if self.grouping_strategy == "none":
            grouped = [[msg] for msg in messages]
            self.logger.debug(f"Grouping strategy 'none': {len(grouped)} groups created.")
            return grouped
        elif self.grouping_strategy == "time":
            grouped = self._group_by_time(messages)
            self.logger.debug(f"Grouping strategy 'time': {len(grouped)} groups created.")
            return grouped
        elif self.grouping_strategy == "filename":
            grouped = self._group_by_filename(messages)
            self.logger.debug(f"Grouping strategy 'filename': {len(grouped)} groups created.")
            return grouped

        self.logger.warning(f"Unknown grouping strategy '{self.grouping_strategy}'. Defaulting to 'none'.")
        return [[msg] for msg in messages]

    def _group_by_time(self, messages: List[TLMessage]) -> List[List[TLMessage]]:
        if not messages: return []
        groups: List[List[TLMessage]] = []
        if not messages: return groups
        current_group: List[TLMessage] = [messages[0]]
        for i in range(1, len(messages)):
            prev_msg = current_group[-1]
            curr_msg = messages[i]
            time_diff = curr_msg.date - prev_msg.date
            same_sender = curr_msg.sender_id == prev_msg.sender_id
            if same_sender and time_diff <= timedelta(seconds=self.grouping_time_window_seconds):
                current_group.append(curr_msg)
            else:
                groups.append(current_group)
                current_group = [curr_msg]
        if current_group: groups.append(current_group)
        return groups

    def _group_by_filename(self, messages: List[TLMessage]) -> List[List[TLMessage]]:
        if not messages: return []
        candidate_keyed_groups: dict[Tuple[int, str, str], list[TLMessage]] = {}
        lone_messages: list[TLMessage] = []
        for msg in messages:
            filename = getattr(msg.file, 'name', None)
            if not msg.sender_id or not filename :
                lone_messages.append(msg)
                continue
            parsed_info = self._parse_filename_for_grouping(filename)
            if not parsed_info or not parsed_info[0] or not parsed_info[3]:
                lone_messages.append(msg)
                continue
            base_name, _, _, extension = parsed_info
            key = (msg.sender_id, base_name.lower(), extension.lower())
            if key not in candidate_keyed_groups:
                candidate_keyed_groups[key] = []
            candidate_keyed_groups[key].append(msg)
        final_groups: List[List[TLMessage]] = []
        for key_tuple, group_msgs_list in candidate_keyed_groups.items():
            if len(group_msgs_list) > 1:
                group_msgs_list.sort(key=lambda m: (
                    self._parse_filename_for_grouping(getattr(m.file, 'name', ''))[2]
                        if self._parse_filename_for_grouping(getattr(m.file, 'name', '')) else 0,
                    m.id
                ))
                final_groups.append(group_msgs_list)
            else:
                lone_messages.extend(group_msgs_list)
        for lone_msg in lone_messages:
            final_groups.append([lone_msg])
        final_groups.sort(key=lambda g: g[0].id if g else float('inf'))
        return final_groups

    async def forward_messages(
        self,
        origin_id: int | str,
        destination_id: int | str,
        account_identifier: Optional[str] = None,
        start_message_id: Optional[int] = None
    ) -> Tuple[Optional[int], dict]:
        stats = {
            "messages_forwarded": 0,
            "files_forwarded": 0,
            "bytes_forwarded": 0,
        }
        new_last_message_id = None
        client = None
        try:
            client = await self._get_client(account_identifier)
            self.logger.info(f"Attempting to resolve origin: '{origin_id}'")
            origin_entity = await client.get_entity(origin_id)
            self.logger.info(f"Origin '{origin_id}' resolved to: {origin_entity.id if hasattr(origin_entity, 'id') else 'Unknown ID'}")
            self.logger.info(f"Attempting to resolve destination: '{destination_id}'")
            destination_entity = await client.get_entity(destination_id)
            self.logger.info(f"Destination '{destination_id}' resolved to: {destination_entity.id if hasattr(destination_entity, 'id') else 'Unknown ID'}")

            if not origin_entity or not destination_entity:
                raise ValueError("Could not resolve one or both Telegram entities.")

            self.logger.info(f"Fetching all media messages from origin: {origin_id} before grouping and forwarding.")
            all_media_messages: list[TLMessage] = []
            async for msg in client.iter_messages(origin_entity, min_id=start_message_id or 0):
                if msg.media:
                    all_media_messages.append(msg)
            all_media_messages.reverse()
            self.logger.info(f"Fetched {len(all_media_messages)} media messages from {origin_id}.")

            message_groups = self._group_messages(all_media_messages)
            self.logger.info(f"Processing {len(message_groups)} message group(s) after applying '{self.grouping_strategy}' strategy.")

            for group_idx, message_group in enumerate(message_groups):
                if not message_group:
                    self.logger.warning(f"Skipping empty message group at index {group_idx}.")
                    continue
                representative_message = message_group[0]
                message = representative_message
                self.logger.debug(f"Processing Group {group_idx + 1}/{len(message_groups)}, Representative Msg ID: {message.id} from {origin_id}. Items in group: {len(message_group)}")

                if await self._is_duplicate(message_group):
                    self.logger.info(f"Message group starting with ID: {representative_message.id} (from {origin_id}) is a duplicate. Skipping forwarding.")
                    continue
                self.logger.info(f"Group (representative Msg ID: {message.id}) has media. Attempting to forward to {destination_id}.")
                successfully_forwarded_main = False
                main_reply_to_arg = self.destination_topic_id 
                try:
                    for msg_in_group_idx, current_message_in_group in enumerate(message_group):
                        self.logger.info(f"Forwarding item {msg_in_group_idx + 1}/{len(message_group)} (Msg ID: {current_message_in_group.id}) of current group.")
                        if self.prepend_origin_info and not self.destination_topic_id:
                            origin_title = getattr(origin_entity, 'title', f"ID: {origin_entity.id}")
                            group_info_header = ""
                            if len(message_group) > 1:
                                group_info_header = f"[Group item {msg_in_group_idx+1}/{len(message_group)}] "
                            header = f"{group_info_header}[Forwarded from {origin_title} (ID: {origin_entity.id})]\n"
                            message_content = header + (current_message_in_group.text or "")
                            if client.session.filename != str(Config().path.parent / (account_identifier or self.config.accounts[0].get("session_name"))):
                                 await self.close()
                                 client = await self._get_client(account_identifier)
                            await client.send_message(
                                entity=destination_entity,
                                message=message_content,
                                file=current_message_in_group.media,
                                reply_to=main_reply_to_arg
                            )
                            self.logger.info(f"Successfully sent Message ID: {current_message_in_group.id} with origin info from '{origin_id}' to '{destination_id}'.")
                        else:
                            await client.forward_messages(
                                entity=destination_entity,
                                messages=[current_message_in_group.id],
                                from_peer=origin_entity,
                                reply_to=main_reply_to_arg
                            )
                            log_msg = f"Successfully forwarded Message ID: {current_message_in_group.id} from '{origin_id}' to main destination '{destination_id}'"
                            if main_reply_to_arg:
                                log_msg += f" (Topic/ReplyTo: {main_reply_to_arg})"
                            self.logger.info(log_msg)
                        if len(message_group) > 1 and msg_in_group_idx < len(message_group) - 1:
                            await asyncio.sleep(1)
                    successfully_forwarded_main = True
                    stats["messages_forwarded"] += 1
                    if message.file:
                        stats["files_forwarded"] += 1
                        stats["bytes_forwarded"] += message.file.size
                    new_last_message_id = message.id
                except telethon_errors.FloodWaitError as e_flood:
                    self.logger.warning(f"Rate limit hit (main destination) while processing group (representative Msg ID: {message.id}). Waiting for {e_flood.seconds} seconds.")
                    await asyncio.sleep(e_flood.seconds + 1)
                    self.logger.info(f"Skipping rest of Message Group (representative Msg ID: {message.id}) for main destination due to FloodWait.")
                    continue
                except (ChannelPrivateError, ChatAdminRequiredError, UserBannedInChannelError) as e_perm:
                    self.logger.error(f"Permission error forwarding Message Group (representative Msg ID: {message.id}) to main destination: {e_perm}")
                    continue 
                except RPCError as rpc_error:
                    self.logger.error(f"RPCError forwarding Message Group (representative Msg ID: {message.id}) to main destination: {rpc_error}")
                    continue 
                except Exception as e_fwd:
                    self.logger.exception(f"Unexpected error forwarding Message Group (representative Msg ID: {message.id}) to main destination: {e_fwd}")
                    continue
                if successfully_forwarded_main:
                    await self._record_forwarded(message_group, str(origin_entity.id), str(destination_entity.id))
                    if self.secondary_unique_destination:
                        self.logger.info(f"Attempting to forward unique Message Group (representative Msg ID: {message.id}) to secondary destination: {self.secondary_unique_destination}")
                        try:
                            secondary_dest_entity = await client.get_entity(self.secondary_unique_destination)
                            for msg_s_idx, msg_in_group_secondary in enumerate(message_group):
                                await client.forward_messages(
                                    entity=secondary_dest_entity,
                                    messages=[msg_in_group_secondary.id],
                                    from_peer=origin_entity
                                )
                                self.logger.info(f"  Forwarded item {msg_s_idx+1}/{len(message_group)} (Msg ID: {msg_in_group_secondary.id}) of group to secondary_dest '{self.secondary_unique_destination}'.")
                                if len(message_group) > 1 and msg_s_idx < len(message_group) - 1:
                                    await asyncio.sleep(1)
                        except telethon_errors.FloodWaitError as e_flood_sec:
                            self.logger.warning(f"Rate limit hit (secondary destination: {self.secondary_unique_destination}). Waiting for {e_flood_sec.seconds} seconds.")
                            await asyncio.sleep(e_flood_sec.seconds + 1)
                            self.logger.info(f"Skipping secondary forward for Message Group (representative Msg ID: {message.id}) due to FloodWait.")
                        except Exception as e_sec_fwd:
                            self.logger.error(f"Error forwarding unique Message Group (representative Msg ID: {message.id}) to secondary destination '{self.secondary_unique_destination}': {e_sec_fwd}", exc_info=True)
                    if self.forward_to_all_saved_messages:
                        self.logger.info(f"Forwarding Message Group (representative Msg ID: {message.id}) to 'Saved Messages' of all configured accounts.")
                        original_main_account_id = client.session.filename
                        for acc_config in self.config.accounts:
                            saved_messages_account_id = acc_config.get("session_name") or acc_config.get("phone_number")
                            if not saved_messages_account_id:
                                self.logger.warning("Skipping an account for 'Saved Messages' forwarding due to missing identifier.")
                                continue
                            self.logger.info(f"Attempting to forward Message Group (representative Msg ID: {message.id}) to 'Saved Messages' for account: {saved_messages_account_id}")
                            try:
                                if self._client and self._client.session.filename != str(Config().path.parent / saved_messages_account_id):
                                    await self.close()
                                target_client = await self._get_client(saved_messages_account_id)
                                for msg_sv_idx, msg_in_group_saved in enumerate(message_group):
                                    await target_client.forward_messages(
                                        entity='me',
                                        messages=[msg_in_group_saved.id],
                                        from_peer=origin_entity
                                    )
                                    self.logger.info(f"  Forwarded item {msg_sv_idx+1}/{len(message_group)} (Msg ID: {msg_in_group_saved.id}) of group to Saved Messages for {saved_messages_account_id}.")
                                    if len(message_group) > 1 and msg_sv_idx < len(message_group) - 1:
                                        await asyncio.sleep(1)
                                await asyncio.sleep(1)
                            except telethon_errors.FloodWaitError as e_flood_saved:
                                self.logger.warning(f"Rate limit hit (Saved Messages for {saved_messages_account_id}). Waiting for {e_flood_saved.seconds} seconds.")
                                await asyncio.sleep(e_flood_saved.seconds + 1)
                            except (UserDeactivatedError, AuthKeyError) as e_auth_saved:
                                self.logger.error(f"Auth error for account {saved_messages_account_id} when forwarding to Saved Messages: {e_auth_saved}. Skipping this account.")
                            except RPCError as e_rpc_saved:
                                self.logger.error(f"RPCError for account {saved_messages_account_id} when forwarding to Saved Messages: {e_rpc_saved}. Skipping this account.")
                            except Exception as e_saved:
                                self.logger.exception(f"Unexpected error for account {saved_messages_account_id} when forwarding to Saved Messages: {e_saved}. Skipping this account.")
                        if self._client and self._client.session.filename != original_main_account_id:
                             await self.close()
            self.logger.info(f"Finished processing all message groups from {origin_id}.")
        except ValueError as e:
            self.logger.error(f"Configuration or resolution error: {e}")
            raise
        except (ChannelPrivateError, ChatAdminRequiredError) as e:
            self.logger.error(f"Telegram channel access error: {e}")
            raise
        except (AuthKeyError, UserDeactivatedError) as e:
            self.logger.error(f"Telegram authentication error with account {account_identifier or 'default'}: {e}. This account might be banned or need re-authentication.")
            raise
        except RPCError as e:
            self.logger.error(f"Telegram API RPCError (potentially during entity resolution or initial connection phase): {e}")
            raise
        except ConnectionError as e:
            self.logger.error(f"Connection error: {e}")
            raise
        except Exception as e:
            self.logger.exception(f"An unexpected error occurred during forwarding: {e}")
            raise
        finally:
            if client and client.is_connected():
                self.logger.info("Disconnecting Telegram client.")
                await client.disconnect()
            self._client = None
        return new_last_message_id, stats

    async def close(self):
        """Closes any active Telegram client connection."""
        if self._client and self._client.is_connected():
            self.logger.info("Closing client connection in AttachmentForwarder.")
            await self._client.disconnect()
            self._client = None

    async def forward_all_accessible_channels(
        self,
        destination_id: int | str,
        orchestration_account_identifier: Optional[str] = None
    ):
        if not self.db:
            self.logger.error("Database instance (self.db) not available. Cannot proceed with total forward mode.")
            return
        self.logger.info(f"Starting 'Total Forward Mode'. Destination: {destination_id}")
        try:
            unique_channels_with_accounts = self.db.get_all_unique_channels()
        except Exception as e_db:
            self.logger.error(f"Failed to retrieve channels from database: {e_db}", exc_info=True)
            return
        if not unique_channels_with_accounts:
            self.logger.warning("No channels found in account_channel_access table to process for total forward mode.")
            return
        self.logger.info(f"Found {len(unique_channels_with_accounts)} unique channels to process.")
        for channel_id, accessing_account_phone in unique_channels_with_accounts:
            self.logger.info(f"--- Processing channel ID: {channel_id} using account: {accessing_account_phone} ---")
            try:
                await self.close() 
                await self.forward_messages(
                    origin_id=channel_id,
                    destination_id=destination_id,
                    account_identifier=accessing_account_phone
                )
                self.logger.info(f"--- Finished processing channel ID: {channel_id} ---")
            except Exception as e_fwd_all:
                self.logger.error(f"Failed to forward messages for channel ID {channel_id} using account {accessing_account_phone}: {e_fwd_all}", exc_info=True)
                await self.close() 
                self.logger.info(f"Continuing to the next channel after error with channel ID: {channel_id}.")
                continue
        self.logger.info("'Total Forward Mode' completed.")
