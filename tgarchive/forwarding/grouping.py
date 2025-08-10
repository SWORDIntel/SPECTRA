"""
Handles grouping of messages before forwarding.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import List, Tuple, Optional

from telethon.tl.types import Message as TLMessage


class MessageGrouper:
    """
    Groups messages based on different strategies.
    """

    def __init__(self, grouping_strategy: str = "none", grouping_time_window_seconds: int = 300):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.grouping_strategy = grouping_strategy.lower()
        self.grouping_time_window_seconds = grouping_time_window_seconds
        if self.grouping_strategy not in ["none", "filename", "time"]:
            self.logger.warning(f"Invalid grouping strategy '{self.grouping_strategy}'. Defaulting to 'none'.")
            self.grouping_strategy = "none"

        self.logger.info(f"File grouping strategy: {self.grouping_strategy}")
        if self.grouping_strategy == "time":
            self.logger.info(f"Grouping time window: {self.grouping_time_window_seconds} seconds")

        self.filename_group_pattern = re.compile(
            r"(.+?)"
            r"((?:_part(\d+))|(?:_(\d+))|(?:\s\((\d+)\))|(?:\.part(\d+))|(?:\.(\d+)))?"
            r"((?:\.[a-zA-Z0-9]+)+|)$",
            re.IGNORECASE
        )

    def group_messages(self, messages: List[TLMessage]) -> List[List[TLMessage]]:
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

    def _parse_filename_for_grouping(self, filename: str) -> Optional[Tuple[str, str, int, str]]:
        if not filename:
            return None

        name_sans_ext = filename
        current_ext = ""

        common_multi_extensions = {
            '.tar.gz': '.tar.gz', '.tar.bz2': '.tar.bz2', '.tar.xz': '.tar.xz',
        }
        lower_filename = filename.lower()
        for multi_ext_key, actual_ext_val in common_multi_extensions.items():
            if lower_filename.endswith(multi_ext_key):
                name_sans_ext = filename[:-len(actual_ext_val)]
                current_ext = actual_ext_val
                break

        if not current_ext:
            if '.' in name_sans_ext:
                parts = name_sans_ext.rsplit('.', 1)
                if len(parts) == 2 :
                    name_sans_ext = parts[0]
                    current_ext = "." + parts[1]

        standalone_part_regexes = [
            (re.compile(r"^\.part(\d+)$", re.IGNORECASE), 1),
            (re.compile(r"^_part(\d+)$", re.IGNORECASE), 1),
            (re.compile(r"^\s*\((\d+)\)$", re.IGNORECASE), 1),
        ]

        if current_ext:
            for pattern, num_idx in standalone_part_regexes:
                match = pattern.fullmatch(current_ext)
                if match:
                    number_str = match.group(num_idx)
                    try:
                        part_number = int(number_str)
                        return name_sans_ext, current_ext, part_number, ""
                    except ValueError:
                        pass

        part_regexes_at_end = [
            (re.compile(r"(\.part(\d+))$", re.IGNORECASE), 1, 2),
            (re.compile(r"(_part(\d+))$", re.IGNORECASE), 1, 2),
            (re.compile(r"(\s*\((\d+)\))$", re.IGNORECASE), 0, 2),
            (re.compile(r"(\.(\d{1,4}))$", re.IGNORECASE), 1, 2),
            (re.compile(r"(_(\d{1,4}))$", re.IGNORECASE), 1, 2),
        ]

        for pattern, whole_part_idx, num_idx in part_regexes_at_end:
            match = pattern.search(name_sans_ext)
            if match:
                part_string = match.group(whole_part_idx)
                number_str = match.group(num_idx)
                base_name = name_sans_ext[:match.start(whole_part_idx)]

                if whole_part_idx == 0 and base_name.endswith(" ") and not part_string.startswith(" "):
                    base_name = base_name.rstrip(" ")

                if not base_name and part_string == name_sans_ext:
                    return name_sans_ext, "", 0, current_ext

                try:
                    part_number = int(number_str)
                    return base_name, part_string, part_number, current_ext
                except ValueError:
                    continue
        return name_sans_ext, "", 0, current_ext
