"""
Handles forwarding of message attachments between Telegram entities.
"""
from __future__ import annotations

import logging
import asyncio # Added for asyncio.sleep
import sqlite3 # For handling specific DB errors
from typing import Optional, Set, List, Tuple # Added List, Tuple
import hashlib # Added for deduplication
import re # For filename grouping
import os
import tempfile
from datetime import datetime, timezone, timedelta # Added for deduplication timestamp, timedelta for time grouping

# Third-party imports
from telethon import TelegramClient, errors as telethon_errors
from telethon.tl import types
from telethon.tl.types import Message as TLMessage, InputPeerChannel, User, Channel
from telethon.errors import RPCError, ChannelPrivateError, UserDeactivatedError, AuthKeyError, UserBannedInChannelError, ChatAdminRequiredError, ForwardAccessForbiddenError

# Local application imports
from tgarchive.db import SpectraDB
from tgarchive.config_models import Config, DEFAULT_CFG # Import from new location
from tgarchive.attribution import AttributionFormatter
from tgarchive.deduplication import get_sha256_hash, get_perceptual_hash, get_fuzzy_hash, compare_fuzzy_hashes

# Conditional import for imagehash
try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except ImportError:
    IMAGEHASH_AVAILABLE = False

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
            if not IMAGEHASH_AVAILABLE:
                self.logger.warning("imagehash library not available - perceptual hash features will be disabled.")
            if self.secondary_unique_destination:
                self.logger.info(f"Unique messages will be forwarded to secondary destination: {self.secondary_unique_destination}")
            if self.db:
                # The deduplication tables are now part of the main schema in db.py
                self._load_existing_hashes()
            else:
                self.logger.warning("Deduplication is enabled, but no database is configured. Deduplication will be in-memory only for this session.")
        else:
            self.logger.info("Deduplication is DISABLED.")

        self.attribution_formatter = AttributionFormatter(self.config.data)

    def _load_existing_hashes(self):
        """Load existing SHA256 hashes from the file_hashes table."""
        if not self.db:
            self.logger.warning("Database not available, cannot load hashes.")
            return
        try:
            # Note: This loads all SHA256 hashes into memory. For very large databases,
            # this might need to be optimized (e.g., bloom filter, selective loading).
            cursor = self.db.conn.execute("SELECT sha256_hash FROM file_hashes WHERE sha256_hash IS NOT NULL")
            count = 0
            for row in cursor:
                self.message_hashes.add(row[0])
                count += 1
            self.logger.info(f"Loaded {count} existing file content hashes (SHA256) into memory.")
        except sqlite3.OperationalError as e:
            self.logger.warning(f"Could not load existing hashes from 'file_hashes' table. It might not exist if this is the first run. Error: {e}")
        except Exception as e:
            self.logger.error(f"Error loading existing file hashes: {e}", exc_info=True)

    async def _is_duplicate(self, message_group: List[TLMessage], client: TelegramClient) -> bool:
        """
        Check if any file in a message group is a duplicate based on its content hash.
        This involves downloading each file to compute its hash.
        """
        if not self.enable_deduplication or not message_group:
            return False

        with tempfile.TemporaryDirectory() as tmpdir:
            for message in message_group:
                if not message.file:
                    continue  # Skip messages without files

                # Define a temporary path for the downloaded file
                file_path = os.path.join(tmpdir, message.file.name or str(message.file.id))

                try:
                    self.logger.debug(f"Downloading file from Msg ID {message.id} for hash computation.")
                    await client.download_media(message.media, file=file_path)
                except Exception as e:
                    self.logger.error(f"Failed to download file for hashing (Msg ID: {message.id}): {e}", exc_info=True)
                    # If download fails, we cannot determine if it's a duplicate.
                    # For safety, treat as not a duplicate and continue checking other files.
                    continue

                if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                    self.logger.warning(f"File for hashing (Msg ID: {message.id}) was not downloaded correctly or is empty. Skipping duplicate check for this file.")
                    continue

                # Compute the content hash
                sha256_hash = get_sha256_hash(file_path)
                self.logger.debug(f"Computed SHA256 hash for file in Msg ID {message.id}: {sha256_hash[:10]}...")

                # 1. Check in-memory cache of hashes for this session
                if sha256_hash in self.message_hashes:
                    self.logger.info(f"Duplicate file found (Msg ID {message.id}, SHA256: {sha256_hash[:10]}...) via in-memory cache.")
                    return True

                # 2. Check database for the hash
                if self.db:
                    try:
                        result = self.db.conn.execute(
                            "SELECT 1 FROM file_hashes WHERE sha256_hash = ?",
                            (sha256_hash,)
                        ).fetchone()

                        if result:
                            self.logger.info(f"Duplicate file found (Msg ID {message.id}, SHA256: {sha256_hash[:10]}...) via database.")
                            self.message_hashes.add(sha256_hash)  # Add to cache to speed up future checks
                            return True
                    except sqlite3.OperationalError as e:
                        # This can happen if the table doesn't exist on the first run.
                        self.logger.warning(f"Could not check for duplicates in 'file_hashes' table, it might not exist yet. Error: {e}")
                    except Exception as e:
                        self.logger.error(f"Error checking for duplicate file in DB (hash {sha256_hash[:10]}...): {e}", exc_info=True)

                # 3. Near-duplicate checks
                if self.config.data.get("deduplication", {}).get("enable_near_duplicates"):
                    import mimetypes
                    mime_type, _ = mimetypes.guess_type(file_path)

                    if mime_type and mime_type.startswith("image/") and IMAGEHASH_AVAILABLE:
                        # Perceptual hash check for images
                        perceptual_hash = get_perceptual_hash(file_path)
                        if perceptual_hash and self.db:
                            self.logger.debug(f"Checking perceptual hash: {perceptual_hash}")
                            distance_threshold = self.config.data.get("deduplication", {}).get("perceptual_hash_distance_threshold", 5)
                            
                            # Check if database has get_all_perceptual_hashes method
                            if hasattr(self.db, 'get_all_perceptual_hashes'):
                                existing_phashes = self.db.get_all_perceptual_hashes()
                                for file_id, other_phash_str in existing_phashes:
                                    try:
                                        other_phash = imagehash.hex_to_hash(other_phash_str)
                                        distance = imagehash.hex_to_hash(perceptual_hash) - other_phash
                                        if distance <= distance_threshold:
                                            self.logger.info(f"Near-duplicate image found for Msg ID {message.id} (pHash distance: {distance} <= {distance_threshold}, matches file_id: {file_id}).")
                                            return True
                                    except Exception as e:
                                        self.logger.error(f"Error comparing perceptual hashes: {e}")
                            else:
                                self.logger.warning("Database method 'get_all_perceptual_hashes' not available.")
                    else:
                        # Fuzzy hash check for other files
                        fuzzy_hash = get_fuzzy_hash(file_path)
                        if fuzzy_hash and self.db:
                            self.logger.debug(f"Checking fuzzy hash: {fuzzy_hash}")
                            similarity_threshold = self.config.data.get("deduplication", {}).get("fuzzy_hash_similarity_threshold", 90)
                            
                            # Check if database has get_all_fuzzy_hashes method
                            if hasattr(self.db, 'get_all_fuzzy_hashes'):
                                existing_fhashes = self.db.get_all_fuzzy_hashes()
                                for file_id, other_fhash in existing_fhashes:
                                    try:
                                        similarity = compare_fuzzy_hashes(fuzzy_hash, other_fhash)
                                        if similarity >= similarity_threshold:
                                            self.logger.info(f"Near-duplicate file found for Msg ID {message.id} (fuzzy hash similarity: {similarity}% >= {similarity_threshold}%, matches file_id: {file_id}).")
                                            return True
                                    except Exception as e:
                                        self.logger.error(f"Error comparing fuzzy hashes: {e}")
                            else:
                                self.logger.warning("Database method 'get_all_fuzzy_hashes' not available.")

        return False

    async def _record_forwarded(self, message_group: List[TLMessage], origin_id: int, dest_id: str, client: TelegramClient):
        """
        Record that files in a message group were forwarded by storing their content hashes.
        """
        if not self.enable_deduplication or not self.db or not message_group:
            return

        # Using a single temp directory for all downloads in the group
        with tempfile.TemporaryDirectory() as tmpdir:
            for message in message_group:
                if not message.file:
                    continue

                # To avoid re-downloading, this process could be optimized by passing hashes
                # from the duplicate check phase. However, for robustness and simplicity,
                # we re-acquire the hash here.
                file_path = os.path.join(tmpdir, message.file.name or str(message.file.id))
                try:
                    await client.download_media(message.media, file=file_path)
                except Exception as e:
                    self.logger.error(f"Failed to download file for recording hash (Msg ID: {message.id}): {e}", exc_info=True)
                    continue

                if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                    self.logger.warning(f"File for recording hash (Msg ID: {message.id}) not downloaded correctly or empty. Skipping.")
                    continue

                sha256_hash = get_sha256_hash(file_path)
                perceptual_hash = None
                fuzzy_hash = None

                if self.config.data.get("deduplication", {}).get("enable_near_duplicates"):
                    perceptual_hash = get_perceptual_hash(file_path)
                    fuzzy_hash = get_fuzzy_hash(file_path)

                # Add hash to in-memory cache to prevent re-processing in the same session
                self.message_hashes.add(sha256_hash)

                try:
                    # Record the hash in the file_hashes table
                    # Note: This assumes the media item is already in the 'media' table.
                    # A more robust implementation might upsert the media item here.
                    if hasattr(self.db, 'add_file_hash'):
                        self.db.add_file_hash(
                            file_id=message.file.id,
                            sha256_hash=sha256_hash,
                            perceptual_hash=perceptual_hash,
                            fuzzy_hash=fuzzy_hash
                        )
                    else:
                        self.logger.warning("Database method 'add_file_hash' not available.")

                    # Record the file's appearance in the source channel
                    if hasattr(self.db, 'add_channel_file_inventory'):
                        self.db.add_channel_file_inventory(
                            channel_id=origin_id,
                            file_id=message.file.id,
                            message_id=message.id,
                            topic_id=getattr(message, 'reply_to_top_id', None) # General topic ID if available
                        )
                    else:
                        self.logger.warning("Database method 'add_channel_file_inventory' not available.")
                        
                    self.logger.info(f"Recorded forwarded file (Msg ID {message.id}, SHA256: {sha256_hash[:10]}...) to database.")
                except Exception as e:
                    self.logger.error(f"Failed to record forwarded file hash for Msg ID {message.id} to DB: {e}", exc_info=True)

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

    async def _resolve_entities(self, client: TelegramClient, origin_id: int | str, destination_id: int | str) -> Tuple[types.TypePeer, types.TypePeer]:
        self.logger.info(f"Attempting to resolve origin: '{origin_id}'")
        origin_entity = await client.get_entity(origin_id)
        self.logger.info(f"Origin '{origin_id}' resolved to: {origin_entity.id if hasattr(origin_entity, 'id') else 'Unknown ID'}")
        self.logger.info(f"Attempting to resolve destination: '{destination_id}'")
        destination_entity = await client.get_entity(destination_id)
        self.logger.info(f"Destination '{destination_id}' resolved to: {destination_entity.id if hasattr(destination_entity, 'id') else 'Unknown ID'}")
        if not origin_entity or not destination_entity:
            raise ValueError("Could not resolve one or both Telegram entities.")
        return origin_entity, destination_entity

    async def _fetch_and_group_messages(self, client: TelegramClient, origin_entity: types.TypePeer, start_message_id: Optional[int]) -> List[List[TLMessage]]:
        self.logger.info(f"Fetching all media messages from origin: {origin_entity.id} before grouping and forwarding.")
        all_media_messages: list[TLMessage] = []
        async for msg in client.iter_messages(origin_entity, min_id=start_message_id or 0):
            if msg.media:
                all_media_messages.append(msg)
        all_media_messages.reverse()
        self.logger.info(f"Fetched {len(all_media_messages)} media messages from {origin_entity.id}.")
        message_groups = self._group_messages(all_media_messages)
        self.logger.info(f"Processing {len(message_groups)} message group(s) after applying '{self.grouping_strategy}' strategy.")
        return message_groups

    async def _forward_message_group_to_main(self, client: TelegramClient, message_group: List[TLMessage], origin_entity: types.TypePeer, destination_entity: types.TypePeer, account_identifier: Optional[str]) -> bool:
        try:
            for msg_in_group_idx, current_message_in_group in enumerate(message_group):
                self.logger.info(f"Forwarding item {msg_in_group_idx + 1}/{len(message_group)} (Msg ID: {current_message_in_group.id}) of current group.")
                if self.prepend_origin_info and not self.destination_topic_id:
                    if destination_entity.id in self.config.get("attribution", {}).get("disable_attribution_for_groups", []):
                        attribution = ""
                    else:
                        sender = await current_message_in_group.get_sender()
                        sender_name = getattr(sender, 'username', f"{getattr(sender, 'first_name', '')} {getattr(sender, 'last_name', '')}".strip())
                        attribution = self.attribution_formatter.format_attribution(
                        message=current_message_in_group,
                        source_channel_name=getattr(origin_entity, 'title', f"ID: {origin_entity.id}"),
                        source_channel_id=origin_entity.id,
                        sender_name=sender_name,
                        sender_id=sender.id,
                        timestamp=current_message_in_group.date
                    )
                    if hasattr(self.db, 'update_attribution_stats'):
                        self.db.update_attribution_stats(origin_entity.id)
                    origin_title = getattr(origin_entity, 'title', f"ID: {origin_entity.id}")
                    group_info_header = ""
                    if len(message_group) > 1:
                        group_info_header = f"[Group item {msg_in_group_idx+1}/{len(message_group)}] "
                    header = f"{group_info_header}[Forwarded from {origin_title} (ID: {origin_entity.id})]\n"
                    message_content = attribution + "\n\n" + (current_message_in_group.text or "")
                    if client.session.filename != str(Config().path.parent / (account_identifier or self.config.accounts[0].get("session_name"))):
                            await self.close()
                            client = await self._get_client(account_identifier)
                    await client.send_message(
                        entity=destination_entity,
                        message=message_content,
                        file=current_message_in_group.media,
                        reply_to=self.destination_topic_id
                    )
                    self.logger.info(f"Successfully sent Message ID: {current_message_in_group.id} with origin info from '{origin_entity.id}' to '{destination_entity.id}'.")
                else:
                    try:
                        await client.forward_messages(
                            entity=destination_entity,
                            messages=[current_message_in_group.id],
                            from_peer=origin_entity,
                            reply_to=self.destination_topic_id
                        )
                        log_msg = f"Successfully forwarded Message ID: {current_message_in_group.id} from '{origin_entity.id}' to main destination '{destination_entity.id}'"
                        if self.destination_topic_id:
                            log_msg += f" (Topic/ReplyTo: {self.destination_topic_id})"
                        self.logger.info(log_msg)
                    except (ForwardAccessForbiddenError, telethon_errors.WebpageMediaEmptyError) as e_restricted:
                        # Fallback: Use workaround for channels with forwarding disabled
                        self.logger.warning(f"Forwarding restricted on source channel (Msg ID {current_message_in_group.id}), using workaround...")
                        attribution = ""
                        if self.prepend_origin_info:
                            origin_title = getattr(origin_entity, 'title', f"ID: {origin_entity.id}")
                            attribution = f"[Forwarded from {origin_title} (ID: {origin_entity.id})]"

                        workaround_success = await self._repost_message_workaround(
                            client,
                            current_message_in_group,
                            origin_entity,
                            destination_entity,
                            attribution
                        )
                        if not workaround_success:
                            raise  # Re-raise if workaround also fails

                if len(message_group) > 1 and msg_in_group_idx < len(message_group) - 1:
                    await asyncio.sleep(1)
            return True
        except telethon_errors.FloodWaitError as e_flood:
            self.logger.warning(f"Rate limit hit (main destination) while processing group. Waiting for {e_flood.seconds} seconds.")
            await asyncio.sleep(e_flood.seconds + 1)
            self.logger.info(f"Skipping rest of Message Group for main destination due to FloodWait.")
        except (ChannelPrivateError, ChatAdminRequiredError, UserBannedInChannelError) as e_perm:
            self.logger.error(f"Permission error forwarding Message Group to main destination: {e_perm}")
        except RPCError as rpc_error:
            self.logger.error(f"RPCError forwarding Message Group to main destination: {rpc_error}")
        except Exception as e_fwd:
            self.logger.exception(f"Unexpected error forwarding Message Group to main destination: {e_fwd}")
        return False

    async def _forward_to_secondary_destination(self, client: TelegramClient, message_group: List[TLMessage], origin_entity: types.TypePeer):
        if not self.secondary_unique_destination:
            return
        self.logger.info(f"Attempting to forward unique Message Group to secondary destination: {self.secondary_unique_destination}")
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
            self.logger.info(f"Skipping secondary forward for Message Group due to FloodWait.")
        except Exception as e_sec_fwd:
            self.logger.error(f"Error forwarding unique Message Group to secondary destination '{self.secondary_unique_destination}': {e_sec_fwd}", exc_info=True)

    async def _forward_to_saved_messages(self, client: TelegramClient, message_group: List[TLMessage], origin_entity: types.TypePeer, current_account_identifier: Optional[str]):
        if not self.forward_to_all_saved_messages:
            return
        self.logger.info(f"Forwarding Message Group to 'Saved Messages' of all configured accounts.")
        original_main_account_id = client.session.filename
        for acc_config in self.config.accounts:
            saved_messages_account_id = acc_config.get("session_name") or acc_config.get("phone_number")
            if not saved_messages_account_id:
                self.logger.warning("Skipping an account for 'Saved Messages' forwarding due to missing identifier.")
                continue
            self.logger.info(f"Attempting to forward Message Group to 'Saved Messages' for account: {saved_messages_account_id}")
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

    async def _process_message_group(self, client: TelegramClient, message_group: List[TLMessage], origin_entity: types.TypePeer, destination_entity: types.TypePeer, account_identifier: Optional[str]) -> bool:
        if not message_group:
            self.logger.warning("Skipping empty message group.")
            return False

        representative_message = message_group[0]
        self.logger.debug(f"Processing Group, Representative Msg ID: {representative_message.id} from {origin_entity.id}. Items in group: {len(message_group)}")

        if await self._is_duplicate(message_group, client):
            self.logger.info(f"Message group starting with ID: {representative_message.id} (from {origin_entity.id}) contains a duplicate file. Skipping forwarding of the entire group.")
            return False

        self.logger.info(f"Group (representative Msg ID: {representative_message.id}) has media. Attempting to forward to {destination_entity.id}.")

        successfully_forwarded_main = await self._forward_message_group_to_main(client, message_group, origin_entity, destination_entity, account_identifier)

        if successfully_forwarded_main:
            await self._record_forwarded(message_group, origin_entity.id, str(destination_entity.id), client)
            await self._forward_to_secondary_destination(client, message_group, origin_entity)
            await self._forward_to_saved_messages(client, message_group, origin_entity, account_identifier)
            return True
        return False

    async def _repost_message_workaround(
        self,
        client: TelegramClient,
        message: TLMessage,
        origin_entity,
        destination_entity,
        attribution: str = ""
    ) -> bool:
        """
        Workaround for channels with forwarding disabled.
        Re-posts the message by downloading and re-uploading media, instead of using forward.

        Args:
            client: The Telegram client
            message: The message to repost
            origin_entity: The source channel/chat
            destination_entity: The destination channel/chat
            attribution: Attribution text to prepend

        Returns:
            True if successful, False otherwise
        """
        try:
            self.logger.info(f"Using workaround for message ID {message.id} (forwarding may be restricted on source channel)")

            # Prepare message text with attribution
            text = attribution if attribution else ""
            if message.text:
                if text:
                    text += "\n\n" + message.text
                else:
                    text = message.text

            # Try to re-post with media if available
            if message.media:
                try:
                    # Download media to temporary location
                    import tempfile
                    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                        tmp_path = tmp_file.name

                    try:
                        await client.download_media(message.media, file=tmp_path)

                        # Re-upload as new message
                        await client.send_message(
                            entity=destination_entity,
                            message=text or "File",
                            file=tmp_path,
                            parse_mode=None
                        )

                        self.logger.info(f"Successfully reposted message {message.id} with media (workaround)")
                        return True
                    finally:
                        # Clean up temporary file
                        if os.path.exists(tmp_path):
                            try:
                                os.remove(tmp_path)
                            except Exception as e:
                                self.logger.debug(f"Failed to clean up temporary file: {e}")

                except Exception as e:
                    self.logger.warning(f"Workaround failed for message with media (ID {message.id}): {e}")
                    # Fall back to text-only if media handling fails
                    if text:
                        await client.send_message(
                            entity=destination_entity,
                            message=text,
                            parse_mode=None
                        )
                        self.logger.info(f"Reposted message {message.id} as text-only (media failed)")
                        return True
                    return False
            else:
                # Text-only message
                if text:
                    await client.send_message(
                        entity=destination_entity,
                        message=text,
                        parse_mode=None
                    )
                    self.logger.info(f"Reposted message {message.id} as text-only (workaround)")
                    return True
                else:
                    self.logger.warning(f"Message {message.id} has no text or media, skipping")
                    return False

        except Exception as e:
            self.logger.error(f"Workaround repost failed for message ID {message.id}: {e}")
            return False

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
            origin_entity, destination_entity = await self._resolve_entities(client, origin_id, destination_id)

            message_groups = await self._fetch_and_group_messages(client, origin_entity, start_message_id)

            for group in message_groups:
                if await self._process_message_group(client, group, origin_entity, destination_entity, account_identifier):
                    stats["messages_forwarded"] += 1
                    if group[0].file:
                        stats["files_forwarded"] += 1
                        stats["bytes_forwarded"] += group[0].file.size
                    new_last_message_id = group[0].id

        except (ValueError, ChannelPrivateError, AuthKeyError, RPCError, ConnectionError) as e:
            self.logger.error(f"A critical error occurred: {e}", exc_info=True)
            raise
        except Exception as e:
            self.logger.exception(f"An unexpected error occurred during forwarding: {e}")
            raise
        finally:
            if client:
                await self.close()

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
        """
        Forward all messages from all accessible channels to a single destination.

        This is designed for scenarios where a channel owner has been banned and needs to
        recover/move the channel content to a new location. Uses all available accounts
        to access channels the current account may not have access to.

        Args:
            destination_id: The destination channel/chat ID to forward messages to
            orchestration_account_identifier: Optional specific account to use as orchestrator
        """
        if not self.db:
            self.logger.error("Database instance (self.db) not available. Cannot proceed with total forward mode.")
            return

        self.logger.info(f"====== STARTING 'TOTAL FORWARD MODE' (Channel Recovery/Move) ======")
        self.logger.info(f"Destination channel: {destination_id}")

        try:
            if hasattr(self.db, 'get_all_unique_channels'):
                unique_channels_with_accounts = self.db.get_all_unique_channels()
            else:
                self.logger.error("Database method 'get_all_unique_channels' not available.")
                return
        except Exception as e_db:
            self.logger.error(f"Failed to retrieve channels from database: {e_db}", exc_info=True)
            return

        if not unique_channels_with_accounts:
            self.logger.warning("No channels found in account_channel_access table to process for total forward mode.")
            return

        self.logger.info(f"Found {len(unique_channels_with_accounts)} unique channels to process for recovery.")

        # Track results for summary report
        successful_channels = []
        failed_channels = []
        banned_channels = []

        for idx, (channel_id, accessing_account_phone) in enumerate(unique_channels_with_accounts, 1):
            self.logger.info(f"\n[{idx}/{len(unique_channels_with_accounts)}] Processing channel ID: {channel_id}")
            self.logger.info(f"  Using account: {accessing_account_phone}")

            try:
                await self.close()
                last_msg_id, stats = await self.forward_messages(
                    origin_id=channel_id,
                    destination_id=destination_id,
                    account_identifier=accessing_account_phone
                )

                if stats and stats.get('messages_forwarded', 0) > 0:
                    self.logger.info(f"  ✓ SUCCESS - Forwarded {stats['messages_forwarded']} messages, {stats['files_forwarded']} files ({stats['bytes_forwarded']} bytes)")
                    successful_channels.append({
                        'channel_id': channel_id,
                        'account': accessing_account_phone,
                        'messages': stats['messages_forwarded'],
                        'files': stats['files_forwarded'],
                        'bytes': stats['bytes_forwarded']
                    })
                else:
                    self.logger.info(f"  ✓ COMPLETED - No new messages to forward (already synced or empty)")
                    successful_channels.append({
                        'channel_id': channel_id,
                        'account': accessing_account_phone,
                        'messages': 0,
                        'files': 0,
                        'bytes': 0
                    })

            except UserBannedInChannelError as e_banned:
                self.logger.warning(f"  ⚠ BANNED - Account {accessing_account_phone} is banned from channel {channel_id}")
                self.logger.debug(f"     Ban reason: {e_banned}")
                banned_channels.append({
                    'channel_id': channel_id,
                    'account': accessing_account_phone,
                    'reason': 'Account banned from channel'
                })
                try:
                    await self.close()
                except:
                    pass
                continue

            except (ChannelPrivateError, ChatAdminRequiredError) as e_perm:
                self.logger.warning(f"  ⚠ PERMISSION ERROR - Cannot access channel {channel_id}: {e_perm}")
                failed_channels.append({
                    'channel_id': channel_id,
                    'account': accessing_account_phone,
                    'error': f"Permission error: {type(e_perm).__name__}"
                })
                try:
                    await self.close()
                except:
                    pass
                continue

            except Exception as e_fwd_all:
                self.logger.error(f"  ✗ ERROR - Failed to forward messages from channel {channel_id}: {type(e_fwd_all).__name__}: {e_fwd_all}")
                self.logger.debug(f"     Full traceback:", exc_info=True)
                failed_channels.append({
                    'channel_id': channel_id,
                    'account': accessing_account_phone,
                    'error': f"{type(e_fwd_all).__name__}: {str(e_fwd_all)[:100]}"
                })
                try:
                    await self.close()
                except:
                    pass
                continue

        # Summary Report
        self.logger.info(f"\n====== TOTAL FORWARD MODE SUMMARY ======")
        self.logger.info(f"Total channels processed: {len(unique_channels_with_accounts)}")
        self.logger.info(f"  ✓ Successful: {len(successful_channels)}")
        self.logger.info(f"  ⚠ Banned from: {len(banned_channels)}")
        self.logger.info(f"  ✗ Failed: {len(failed_channels)}")

        if successful_channels:
            total_messages = sum(c.get('messages', 0) for c in successful_channels)
            total_files = sum(c.get('files', 0) for c in successful_channels)
            total_bytes = sum(c.get('bytes', 0) for c in successful_channels)
            self.logger.info(f"\nRecovered content: {total_messages} messages, {total_files} files ({total_bytes} bytes)")

        if banned_channels:
            self.logger.warning(f"\nChannels inaccessible due to bans:")
            for ch in banned_channels[:10]:  # Show first 10
                self.logger.warning(f"  - Channel {ch['channel_id']} (account: {ch['account']})")
            if len(banned_channels) > 10:
                self.logger.warning(f"  ... and {len(banned_channels) - 10} more")

        if failed_channels:
            self.logger.error(f"\nChannels with errors:")
            for ch in failed_channels[:10]:  # Show first 10
                self.logger.error(f"  - Channel {ch['channel_id']}: {ch['error']}")
            if len(failed_channels) > 10:
                self.logger.error(f"  ... and {len(failed_channels) - 10} more")

        self.logger.info(f"====== TOTAL FORWARD MODE COMPLETED ======\n")

    async def forward_files(self, schedule_id: int, source_id: int | str, destination_id: int | str, file_types: Optional[str], min_file_size: Optional[int], max_file_size: Optional[int], account_identifier: Optional[str] = None):
        client = None
        try:
            client = await self._get_client(account_identifier)
            source_entity = await client.get_entity(source_id)

            if not source_entity:
                raise ValueError("Could not resolve the source Telegram entity.")

            async for message in client.iter_messages(source_entity):
                if not message.media or not message.file:
                    continue

                if file_types:
                    if message.file.mime_type not in file_types.split(','):
                        continue

                if min_file_size is not None and message.file.size < min_file_size:
                    continue

                if max_file_size is not None and message.file.size > max_file_size:
                    continue

                if await self._is_duplicate([message], client):
                    continue

                if hasattr(self.db, 'add_to_file_forward_queue'):
                    self.db.add_to_file_forward_queue(schedule_id, message.id, message.file.id)
                else:
                    self.logger.warning("Database method 'add_to_file_forward_queue' not available.")

        except Exception as e:
            self.logger.error(f"Error queueing files from {source_id}: {e}")
            raise
        finally:
            if client:
                await client.disconnect()

    async def process_file_forward_queue(self, account_identifier: Optional[str] = None):
        client = None
        try:
            client = await self._get_client(account_identifier)
            if not hasattr(self.db, 'get_file_forward_queue'):
                self.logger.error("Database method 'get_file_forward_queue' not available.")
                return
                
            queue = self.db.get_file_forward_queue()
            for queue_id, schedule_id, message_id, file_id, destination in queue:
                try:
                    if destination:
                        destination_entity = await client.get_entity(destination)
                    else:
                        if hasattr(self.db, 'get_file_forward_schedule_by_id'):
                            schedule = self.db.get_file_forward_schedule_by_id(schedule_id)
                        else:
                            self.logger.error("Database method 'get_file_forward_schedule_by_id' not available.")
                            continue
                        if not schedule:
                            if hasattr(self.db, 'update_file_forward_queue_status'):
                                self.db.update_file_forward_queue_status(queue_id, "error: schedule not found")
                            continue
                        destination_entity = await client.get_entity(schedule.destination)

                    source_entity = await client.get_entity(schedule.source)

                    await client.forward_messages(
                        entity=destination_entity,
                        messages=[message_id],
                        from_peer=source_entity,
                    )
                    message = await client.get_messages(source_entity, ids=message_id)
                    if message:
                        await self._record_forwarded([message], str(source_entity.id), str(destination_entity.id), client)
                    
                    if hasattr(self.db, 'update_file_forward_queue_status'):
                        self.db.update_file_forward_queue_status(queue_id, "success")

                    # Bandwidth throttling
                    bandwidth_limit_kbps = self.config.data.get("scheduler", {}).get("bandwidth_limit_kbps", 0)
                    if bandwidth_limit_kbps > 0:
                        if message and message.file:
                            delay = message.file.size / (bandwidth_limit_kbps * 1024)
                            await asyncio.sleep(delay)

                except Exception as e:
                    if hasattr(self.db, 'update_file_forward_queue_status'):
                        self.db.update_file_forward_queue_status(queue_id, f"error: {e}")
                    self.logger.error(f"Error processing queue item {queue_id}: {e}")
        except Exception as e:
            self.logger.error(f"Error processing file forward queue: {e}")
            raise
        finally:
            if client:
                await client.disconnect()

    async def repost_messages_in_channel(self, channel_id: int | str, account_identifier: Optional[str] = None):
        """
        Re-posts messages in a channel to remove forwarding attribution.
        """
        client = None
        try:
            client = await self._get_client(account_identifier)
            self.logger.info(f"Attempting to resolve channel: '{channel_id}'")
            entity = await client.get_entity(channel_id)
            self.logger.info(f"Channel '{channel_id}' resolved to: {entity.id if hasattr(entity, 'id') else 'Unknown ID'}")

            if not entity:
                raise ValueError("Could not resolve the Telegram entity.")

            self.logger.info(f"Starting to re-post messages in channel {channel_id}.")
            async for message in client.iter_messages(entity):
                try:
                    # Send a new message with the same content
                    await client.send_message(
                        entity=entity,
                        message=message.text,
                        file=message.media
                    )
                    # Delete the original message
                    await client.delete_messages(entity, [message.id])
                    self.logger.info(f"Successfully re-posted and deleted message ID: {message.id}")
                except telethon_errors.MessageDeleteForbiddenError:
                    self.logger.error(f"Could not delete message {message.id}. Bot is likely not an admin in the channel.")
                    # If we can't delete, we should stop to avoid creating a mess.
                    break
                except Exception as e:
                    self.logger.error(f"Error processing message {message.id}: {e}", exc_info=True)

            self.logger.info(f"Finished re-posting messages in channel {channel_id}.")

        except (ValueError, ChannelPrivateError, AuthKeyError, RPCError, ConnectionError) as e:
            self.logger.error(f"A critical error occurred: {e}", exc_info=True)
            raise
        except Exception as e:
            self.logger.exception(f"An unexpected error occurred during re-posting: {e}")
            raise
        finally:
            if client:
                await self.close()
