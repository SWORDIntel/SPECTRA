#!/usr/bin/python3

"""Telepathy lib:
    An OSINT toolkit for investigating Telegram chats.
"""

import pandas as pd
import datetime
import os
import re
import time
import asyncio

from src.telepathy.utils import (
    populate_user,
    process_message,
    process_description,
    parse_tg_date,
    parse_html_page,
    print_shell,
    createPlaceholdeCls,
    create_path,
    create_file_report,
    clean_private_invite,
    evaluate_reactions,
    color_print_green,
)

from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types.messages import Messages
from telethon.errors import ChannelPrivateError
from telethon.tl.types import (
    User,
    PeerUser,
    PeerChat,
    PeerChannel,
)
from telethon import utils
from telethon.utils import get_display_name
from alive_progress import alive_bar
from colorama import Fore, Style
from src.telepathy.const import telepathy_file

class Group_Chat_Analisys:

    save_directory = None
    media_directory = None
    file_archive = None
    reply_file_archive = None
    forward_directory = None
    file_forwards = None
    edgelist_file = None
    memberlist_directory = None
    memberlist_filename = None
    reply_memberlist_filename = None
    history = None
    history_count = 0

    _target = None
    _target_entity = None
    _alphanumeric = None
    _log_file = None
    _filetime = None

    client = None

    def __init__(
        self,
        target,
        client,
        log_file,
        filetime,
        replies,
        forwards,
        comprehensive,
        media,
        json,
        translate,
    ):
        self.client = client
        self._target = target
        self._log_file = log_file
        self._filetime = filetime
        self._alphanumeric = self.calculate_alfanumeric()
        self.user_check = self.location_check = False
        self.basic = True if target else False
        self.reply_analysis = True if replies else False
        self.forwards_check = True if forwards else False
        self.comp_check = True if comprehensive else False
        self.media_archive = True if media else False
        self.json_check = True if json else False
        self.translate_check = True if translate else False
        self.last_date, self.chunk_size, self.user_language = None, 1000, "en"
        self.create_dirs_files()

    def telepathy_log_run(self):
        log = []
        log.append(
            [
                self._filetime,
                self._entity.title,
                self._group_description,
                self._translated_description,
                self._total_participants,
                self._found_participants,
                self._group_username,
                self._group_url,
                self._chat_type,
                self._entity.id,
                self._entity.access_hash,
                str(self._entity.scam),
                self._date,
                self._mtime,
                self._group_status,
            ]
        )
        log_df = pd.DataFrame(
            log,
            columns=[
                "Access Date",
                "Title",
                "Description",
                "Translated description",
                "Total participants",
                "Participants found",
                "Username",
                "URL",
                "Chat type",
                "Chat ID",
                "Access hash",
                "Scam",
                "First post date",
                "First post time (UTC)",
                "Restrictions",
            ],
        )

        if not os.path.isfile(self._log_file):
            log_df.to_csv(self._log_file, sep=";", index=False)
        else:
            log_df.to_csv(self._log_file, sep=";", mode="a", index=False, header=False)

    def calculate_alfanumeric(self):
        alphanumeric = ""
        for character in self._target:
            if character.isalnum():
                alphanumeric += character
        return alphanumeric

    async def retrieve_entity(self, _target):
        current_entity = None
        target = None
        try:
            current_entity = await self.client.get_entity(_target)
            target = _target
        except Exception as exx:
            try:
                current_entity = await self.client.get_entity(int(_target))
                target = int(_target)
            except:
                pass
            pass
        if not current_entity:
            try:
                current_entity = await self.client.get_entity(PeerChannel(_target))
                target = _target
            except Exception as exx:
                pass
        if not current_entity:
            try:
                current_entity = await self.client.get_entity(PeerChat(_target))
                target = _target
            except Exception as exx:
                pass
        if type(target) is int and current_entity.username:
            target = current_entity.username
        return current_entity, target

    async def looking_for_members(self, _target):
        members = []
        members_df = None
        all_participants = await self.client.get_participants(_target, limit=5000)

        for user in all_participants:
            members_df = pd.DataFrame(
                members,
                columns=[
                    "Username",
                    "Full name",
                    "User ID",
                    "Phone number",
                    "Group name",
                ],
            )
            members.append(populate_user(user, _target))
        return members_df, all_participants

    async def retrieve_memberlist(self):
        members_df, all_participants = await self.looking_for_members(self._target)
        if members_df is not None:
            with open(self.memberlist_filename, "w+", encoding="utf-8") as save_members:
                members_df.to_csv(save_members, sep=";")

            if self.json_check:
                members_df.to_json(
                    self.memberlist_filename_json,
                    orient="records",
                    compression="infer",
                    lines=True,
                    index=True,
                )

        found_participants = len(all_participants)
        found_percentage = 0
        if self._total_participants > 0:
            found_percentage = (
                int(found_participants) / int(self._total_participants) * 100
            )
        print("\n")
        color_print_green(" [+] Memberlist fetched", "")
        return found_participants, found_percentage

    async def retrieve_entity_info(self, _handle, _check_user=False):
        _result = {"entity": None}
        web_req = None

        _result["entity"], self._target = await self.retrieve_entity(_handle)

        if not _result["entity"] or (
            _result["entity"].__class__ == User and _check_user
        ):
            if _result["entity"].__class__ == User:
                color_print_green(
                    " [!] ",
                    "You can't search for users using flag -c, run Telepathy using the flag -u.",
                )
                exit(1)
            else:
                color_print_green(
                    " [!] ", "Telegram handle: {} wasn't found. !!!!".format(_handle)
                )
                exit(1)
            return
        elif _check_user:
            if _result["entity"].__class__ == User:
                _result = {"chat_type": "User"}
                substring_1 = "PeerUser"

                if _result["entity"].username is not None:
                    _result["username"] = _result["entity"].username
                else:
                    username = "none"

                string_1 = str(_result["entity"].user_id)
                if substring_1 in string_1:
                    user_id = re.sub(
                        "[^0-9]",
                        "",
                        string_1,
                    )
                    user_id = await self.client.get_entity(PeerUser(int(user_id)))
                    user_id = str(user_id)
                    _result["user_id"] = user_id
                    _result["first_name"] = _result["entity"].first_name
                    return _result

        _result["total_participants"] = 0
        (
            _result["chat_type"],
            _result["group_url"],
            _result["group_username"],
            _result["group_description"],
            _result["group_status"],
            _result["translated_description"],
        ) = ("", "", "", "", "", "")

        if _result["entity"].broadcast is True:
            _result["chat_type"] = "Channel"
        elif _result["entity"].megagroup is True:
            _result["chat_type"] = "Megagroup"
        elif _result["entity"].gigagroup is True:
            _result["chat_type"] = "Gigagroup"
        else:
            _result["chat_type"] = "Chat"

        if _result["entity"].username:
            _result["group_url"] = "http://t.me/" + _result["entity"].username
            _result["group_username"] = _result["entity"].username
            web_req = parse_html_page(_result["group_url"])
        elif "https://t.me/" in _handle:
            _result["group_url"] = _handle
            web_req = parse_html_page(_result["group_url"])
            _result["group_username"] = "Private group"
        else:
            _result["group_url"], _result["group_username"] = (
                "Private group",
                "Private group",
            )

        if web_req:
            _result["group_description"] = web_req["group_description"]
            _result["total_participants"] = web_req["total_participants"]

        if self.translate_check:
            _result["desc"] = process_description(
                _result["group_description"], self.user_language
            )
            _original_language = _result["desc"]["original_language"]
            _result["translated_description"] = _result["desc"]["translated_text"]
        else:
            _result["translated_description"] = "N/A"

        _result["first_post"] = "Not found"
        _result["date"] = "N/A"
        _result["datepost"] = "N/A"
        _result["mtime"] = "N/A"

        async for message in self.client.iter_messages(self._target, reverse=True):
            _result["datepost"] = parse_tg_date(message.date)
            _result["date"] = _result["date"]
            _result["mtime"] = _result["mtime"]
            _result["first_post"] = _result["datepost"]["timestamp"]
            break

        if _result["entity"].restriction_reason is not None:
            ios_restriction = _result["entity"].restriction_reason[0]
            if 1 in _result["entity"].restriction_reason:
                android_restriction = _result["entity"].restriction_reason[1]
                _result["group_status"] = (
                    str(ios_restriction) + ", " + str(android_restriction)
                )
            else:
                _result["group_status"] = str(ios_restriction)
        else:
            _result["group_status"] = "None"
        return _result

    async def retrieve_chat_group_entity(self, _handle):
        try:
            _entitydetails = await self.retrieve_entity_info(_handle)
        except Exception as exx:
            pass

        self._entity = _entitydetails["entity"]
        self._total_participants = _entitydetails["total_participants"]
        (
            self._chat_type,
            self._group_url,
            self._group_username,
            self._group_description,
            self._group_status,
            self._translated_description,
        ) = (
            _entitydetails["chat_type"],
            _entitydetails["group_url"],
            _entitydetails["group_username"],
            _entitydetails["group_description"],
            _entitydetails["group_status"],
            _entitydetails["translated_description"],
        )
        self._first_post = _entitydetails["first_post"]
        self._date = _entitydetails["date"]
        self._datepost = _entitydetails["datepost"]
        self._mtime = _entitydetails["mtime"]
        if self._entity.broadcast is True:
            self._chat_type = "Channel"
        elif self._entity.megagroup is True:
            self._chat_type = "Megagroup"
        elif self._entity.gigagroup is True:
            self._chat_type = "Gigagroup"
        else:
            self._chat_type = "Chat"

        if self._entity.username:
            self._group_url = "http://t.me/" + self._entity.username
            self._group_username = self._entity.username
            web_req = parse_html_page(self._group_url)
        elif "https://t.me/" in _handle:
            self._group_url = _handle
            web_req = parse_html_page(self._group_url)
            self._group_username = "Private group"
        else:
            web_req = None
            self._group_url, self._group_username = "Private group", "Private group"

        if web_req:
            self._group_description = web_req["group_description"]
            self._total_participants = web_req["total_participants"]

        if self.translate_check == True:
            self._desc = process_description(
                self._group_description, self.user_language
            )
            _original_language = self._desc["original_language"]
            self._translated_description = self._desc["translated_text"]
        else:
            self._translated_description = "N/A"

        self._group_status = _entitydetails["group_status"]
        self._first_post = _entitydetails["first_post"]
        self._date = _entitydetails["date"]
        self._datepost = _entitydetails["datepost"]
        self._mtime = _entitydetails["mtime"]

    def create_dirs_files(self):
        self.save_directory = None
        self.media_directory = None
        self.file_archive = None
        self.reply_file_archive = None
        self.forward_directory = None
        self.file_forwards = None
        self.edgelist_file = None
        self.memberlist_directory = None
        self.memberlist_filename = None
        self.reply_memberlist_filename = None

        if self.basic or self.comp_check:
            self.save_directory = create_path(
                os.path.join(telepathy_file, self._alphanumeric)
            )

        if self.media_archive and self.save_directory:
            self.media_directory = create_path(
                os.path.join(self.save_directory, "media")
            )

        if self.comp_check:
            self.file_archive = create_file_report(
                self.save_directory,
                self._alphanumeric,
                "archive",
                "csv",
                self._filetime,
            )
            self.reply_file_archive = create_file_report(
                self.save_directory,
                self._alphanumeric,
                "reply_archive",
                "csv",
                self._filetime,
            )
            if self.json_check:
                self.archive_filename_json = create_file_report(
                    self.memberlist_directory,
                    self._alphanumeric,
                    "archive",
                    "json",
                    self._filetime,
                    False,
                )

        if self.forwards_check == True:
            self.forward_directory = create_path(
                os.path.join(self.save_directory, "edgelist")
            )
            self.file_forwards = create_file_report(
                self.forward_directory,
                self._alphanumeric,
                "edgelist",
                "csv",
                self._filetime,
            )
            self.edgelist_file = create_file_report(
                self.forward_directory,
                self._alphanumeric,
                "edgelist",
                "csv",
                self._filetime,
                False,
            )
            if self.json_check:
                self.edgelist_filename_json = create_file_report(
                    self.memberlist_directory,
                    self._alphanumeric,
                    "edgelist",
                    "json",
                    self._filetime,
                    False,
                )

        if self.basic is True or self.comp_check is True:
            self.memberlist_directory = create_path(
                os.path.join(self.save_directory, "memeberlist")
            )
            self.memberlist_filename = create_file_report(
                self.memberlist_directory,
                self._alphanumeric,
                "members",
                "csv",
                self._filetime,
            )
            if self.json_check:
                self.memberlist_filename_json = create_file_report(
                    self.memberlist_directory,
                    self._alphanumeric,
                    "members",
                    "json",
                    self._filetime,
                    False,
                )
            self.reply_memberlist_filename = create_file_report(
                self.memberlist_directory,
                self._alphanumeric,
                "active_members",
                "csv",
                self._filetime,
            )

    async def analyze_group_channel(self, _target=None):
        if not _target:
            _target = self._target
        _target = clean_private_invite(_target)
        self._found_participants = 0
        await self.retrieve_chat_group_entity(_target)

        if self.basic and not self.comp_check:
            color_print_green(" [!] ", "Performing basic scan")
        elif self.comp_check:
            color_print_green(" [!] ", "Performing comprehensive scan")
        if self.forwards_check:
            color_print_green(" [!] ", "Forwards will be fetched")

        if self.basic is True or self.comp_check is True:
            if self._chat_type != "Channel":
                (
                    self._found_participants,
                    self._found_percentage,
                ) = await self.retrieve_memberlist()

            setattr(self._entity, "group_description", self._group_description)
            setattr(self._entity, "group_status", self._group_status)
            setattr(self._entity, "group_username", self._group_username)
            setattr(self._entity, "first_post", self._first_post)
            setattr(self._entity, "group_url", self._group_url)
            setattr(self._entity, "chat_type", self._chat_type)
            setattr(
                self._entity, "translated_description", self._translated_description
            )
            setattr(self._entity, "total_participants", self._total_participants)

            if self._chat_type != "Channel":
                setattr(self._entity, "found_participants", self._found_participants)
                setattr(self._entity, "found_percentage", self._found_percentage)
                setattr(self._entity, "memberlist_filename", self.memberlist_filename)
            else:
                setattr(self._entity, "found_participants", self._found_participants)
            print_flag = "group_recap"

            if self._chat_type == "Channel":
                print_flag = "channel_recap"
            print_shell(print_flag, self._entity)
            self.telepathy_log_run()
            await self.process_group_channel_messages(self._target)

    async def f_export(self):
        exports = []
        for Dialog in await self.client.get_dialogs():
            try:
                if Dialog.entity.username:
                    self._group_url = "http://t.me/" + Dialog.entity.username
                    self._group_username = Dialog.entity.username

                    web_req = parse_html_page(self._group_url)
                    self._group_description = web_req["group_description"]
                    self._total_participants = web_req["total_participants"]

                    if self.translate_check:
                        _desc = process_description(
                            self._group_description, self.user_language
                        )
                        self._translated_description = _desc["translated_text"]
                    else:
                        self._translated_description = "N/A"

                    if Dialog.entity.broadcast is True:
                        self._chat_type = "Channel"
                    elif Dialog.entity.megagroup is True:
                        self._chat_type = "Megagroup"
                    elif Dialog.entity.gigagroup is True:
                        self._chat_type = "Gigagroup"
                    else:
                        self._chat_type = "Chat"
                    if not self.target_type:
                        self.target_type = "g"

                    if Dialog.entity.restriction_reason is not None:
                        ios_restriction = Dialog.entity.restriction_reason[0]
                        if 1 in Dialog.entity.restriction_reason:
                            android_restriction = Dialog.entity.restriction_reason[1]
                            self._group_status = (
                                str(ios_restriction) + ", " + str(android_restriction)
                            )
                        else:
                            self._group_status = str(ios_restriction)
                    else:
                        self._group_status = "None"

                    exports.append(
                        [
                            self.filetime,
                            Dialog.entity.title,
                            self._group_description,
                            self._translated_description,
                            self._total_participants,
                            self._group_username,
                            self._group_url,
                            self._chat_type,
                            Dialog.entity.id,
                            Dialog.entity.access_hash,
                            self._group_status,
                        ]
                    )

                    export_df = pd.DataFrame(
                        exports,
                        columns=[
                            "Access Date",
                            "Title",
                            "Description",
                            "Translated description",
                            "Total participants",
                            "Username",
                            "URL",
                            "Chat type",
                            "Chat ID",
                            "Access hash",
                            "Restrictions",
                        ],
                    )

                    if not os.path.isfile(self.export_file):
                        export_df.to_csv(
                            self.export_file,
                            sep=";",
                            index=False,
                        )
                    else:
                        export_df.to_csv(
                            self.export_file,
                            sep=";",
                            mode="w",
                            index=False,
                        )

            except AttributeError:
                pass

    async def retrieve_self_history(self, _target=None):
        cc = False
        if not _target:
            _target = self._target
            cc = True

        _target = clean_private_invite(_target)
        await self.retrieve_chat_group_entity(_target)

        get_history = GetHistoryRequest(
            peer=self._entity,
            offset_id=0,
            offset_date=None,
            add_offset=0,
            limit=1,
            max_id=0,
            min_id=0,
            hash=0,
        )
        history = await self.client(get_history)
        if isinstance(history, Messages):
            count = len(history.messages)
        else:
            count = history.count

        if cc:
            self.history = history
            self.history_count = count
            return None, None
        else:
            return history, count

    async def process_group_channel_messages(self, _target):
        if self.forwards_check is True and self.comp_check is False:
            color_print_green(" [-] ", "Calculating number of forwarded messages...")
            forwards_list = []
            forward_count = 0
            private_count = 0
            to_ent = await self.client.get_entity(_target)
            to_title = to_ent.title

            forwards_df = pd.DataFrame(
                forwards_list,
                columns=[
                    "Source",
                    "Target",
                    "Label",
                    "Source_ID",
                    "Username",
                    "Timestamp",
                ],
            )

            await self.retrieve_self_history()
            for message in self.history.messages:
                if message.forward is not None:
                    forward_count += 1

            color_print_green(" [-] ", "Fetching forwarded messages...")
            progress_bar = Fore.GREEN + " [-] " + Style.RESET_ALL + "Progress: "

            with alive_bar(
                forward_count, dual_line=True, title=progress_bar, length=20
            ) as bar:

                async for message in self.client.iter_messages(_target):
                    if message.forward is not None:
                        try:
                            f_from_id = message.forward.original_fwd.from_id
                            if f_from_id is not None:
                                ent = await self.client.get_entity(f_from_id)
                                username = ent.username
                                timestamp = parse_tg_date(message.date)["timestamp"]

                                substring = "PeerUser"
                                string = str(f_from_id)
                                if self._chat_type != "Channel":
                                    if substring in string:
                                        user_id = re.sub("[^0-9]", "", string)
                                        user_id = await self.client.get_entity(
                                            PeerUser(int(user_id))
                                        )
                                        user_id = str(user_id)
                                        result = (
                                            "User: "
                                            + str(ent.first_name)
                                            + " / ID: "
                                            + str(user_id.id)
                                        )
                                    else:
                                        result = str(ent.title)
                                else:
                                    result = str(ent.title)

                                forwards_df = pd.DataFrame(
                                    forwards_list,
                                    columns=[
                                        "Source",
                                        "Target",
                                        "Label",
                                        "Source_ID",
                                        "Username",
                                        "Timestamp",
                                    ],
                                )

                                forwards_list.append(
                                    [
                                        result,
                                        _target,
                                        to_title,
                                        f_from_id,
                                        username,
                                        timestamp,
                                    ]
                                )

                        except Exception as e:
                            if e is ChannelPrivateError:
                                private_count += 1
                                print("Private channel")
                            continue

                        time.sleep(0.5)
                        bar()

                        with open(
                            self.edgelist_file, "w+", encoding="utf-8"
                        ) as save_forwards:
                            forwards_df.to_csv(save_forwards, sep=";", index=False) # missing index=False (Gephi issue)

                        if self.json_check:
                            forwards_df.to_json(
                                self.edgelist_filename_json,
                                orient="records",
                                compression="infer",
                                lines=True,
                                index=True,
                            )

            if forward_count >= 15:
                forwards_found = forwards_df.Source.count()
                value_count = forwards_df["Source"].value_counts()
                df01 = value_count.rename_axis("unique_values").reset_index(
                    name="counts"
                )

                report_forward = createPlaceholdeCls()
                report_forward.forward_one = (
                    str(df01.iloc[0]["unique_values"])
                    + ", "
                    + str(df01.iloc[0]["counts"])
                    + " forwarded messages"
                )
                report_forward.forward_two = (
                    str(df01.iloc[1]["unique_values"])
                    + ", "
                    + str(df01.iloc[1]["counts"])
                    + " forwarded messages"
                )
                report_forward.forward_three = (
                    str(df01.iloc[2]["unique_values"])
                    + ", "
                    + str(df01.iloc[2]["counts"])
                    + " forwarded messages"
                )
                report_forward.forward_four = (
                    str(df01.iloc[3]["unique_values"])
                    + ", "
                    + str(df01.iloc[3]["counts"])
                    + " forwarded messages"
                )
                report_forward.forward_five = (
                    str(df01.iloc[4]["unique_values"])
                    + ", "
                    + str(df01.iloc[4]["counts"])
                    + " forwarded messages"
                )

                df02 = forwards_df.Source.unique()
                report_forward.unique_forwards = len(df02)
                report_forward.edgelist_file = self.edgelist_file
                report_forward.forward_count = forward_count
                report_forward.forwards_found = forwards_found
                print_shell("forwarder_stat", report_forward)
            else:
                print(
                    "\n"
                    + Fore.GREEN
                    + " [!] Insufficient forwarded messages found"
                    + Style.RESET_ALL
                )

        else:
            if self.comp_check is True:

                files = []
                message_list = []
                forwards_list = []
                replies_list = []
                user_replier_list = []
                forward_count, private_count, message_count, total_reactions = (
                    0,
                    0,
                    0,
                    0,
                )

                if self.media_archive is True:
                    print("\n")
                    color_print_green(" [!] ", "Media content will be archived")

                color_print_green(" [!] ", "Calculating number of messages...")

                await self.retrieve_self_history()
                print("\n")
                color_print_green(" [-] ", "Fetching message archive...")
                progress_bar = Fore.GREEN + " [-] " + Style.RESET_ALL + "Progress: "

                with alive_bar(
                    self.history_count,
                    dual_line=True,
                    title=progress_bar,
                    length=20,
                ) as bar:

                    to_ent = self._entity

                    async for message in self.client.iter_messages(_target, limit=None):
                        if message is not None:
                            try:
                                c_archive = pd.DataFrame(
                                    message_list,
                                    columns=[
                                        "To",
                                        "Message ID",
                                        "Display_name",
                                        "User ID",
                                        "Message_text",
                                        "Original_language",
                                        "Translated_text",
                                        "Translation_confidence",
                                        "Timestamp",
                                        "Has_media",
                                        "Reply_to_ID",
                                        "Replies",
                                        "Forwards",
                                        "Views",
                                        "Total_reactions",
                                        "Reply_ER_reach",
                                        "Reply_ER_impressions",
                                        "Forwards_ER_reach",
                                        "Forwards_ER_impressions",
                                        "Reaction_ER_reach",
                                        "Reactions_ER_impressions",
                                        "Thumbs_up",
                                        "Thumbs_down",
                                        "Heart",
                                        "Fire",
                                        "Smile_with_hearts",
                                        "Clap",
                                        "Smile",
                                        "Thinking",
                                        "Exploding_head",
                                        "Scream",
                                        "Angry",
                                        "Single_tear",
                                        "Party",
                                        "Starstruck",
                                        "Vomit",
                                        "Poop",
                                        "Pray",
                                        "Edit_date",
                                        "URL",
                                        "Media save directory",
                                    ],
                                )

                                c_forwards = pd.DataFrame(
                                    forwards_list,
                                    columns=[
                                        "Source",
                                        "Target",
                                        "Label",
                                        "Source_ID",
                                        "Username",
                                        "Timestamp",
                                    ],
                                )

                                # if message.reactions:
                                #    if message.reactions.can_see_list:
                                #        c_reactioneer = pd.DataFrame(
                                #            user_reaction_list,
                                #            columns=[
                                #                "Username",
                                #                "Full name",
                                #                "User ID",
                                #                "Phone number",
                                #                "Group name",
                                #            ],
                                #        )

                                if (
                                    message.replies
                                    and self.reply_analysis
                                    and self._chat_type == "Channel"
                                ):
                                    if message.replies.replies > 0:
                                        c_repliers = pd.DataFrame(
                                            user_replier_list,
                                            columns=[
                                                "Username",
                                                "Full name",
                                                "User ID",
                                                "Phone number",
                                                "Group name",
                                            ],
                                        )

                                        c_replies = pd.DataFrame(
                                            replies_list,
                                            columns=[
                                                "To",
                                                "Message ID",
                                                "Reply ID",
                                                "Display_name",
                                                "ID",
                                                "Message_text",
                                                "Original_language",
                                                "Translated_text",
                                                "Translation_confidence",
                                                "Timestamp",
                                            ],
                                        )

                                if message.replies:
                                    if message.replies.replies > 0:
                                        async for repl in self.client.iter_messages(
                                            message.chat_id,
                                            reply_to=message.id,
                                        ):

                                            user = await self.client.get_entity(
                                                repl.from_id.user_id
                                            )

                                            userdet = populate_user(user, _target)
                                            user_replier_list.append(userdet)

                                            if self.translate_check:
                                                mss_txt = process_message(
                                                    repl.text, self.user_language
                                                )
                                                original_language = (
                                                    mss_txt["original_language"],
                                                )
                                                translated_text = (
                                                    mss_txt["translated_text"],
                                                )
                                                translation_confidence = (
                                                    mss_txt["translation_confidence"],
                                                )
                                                reply_text = mss_txt["message_text"]
                                            else:
                                                original_language = "N/A"
                                                translated_text = "N/A"
                                                translation_confidence = "N/A"
                                                reply_text = repl.text

                                            replies_list.append(
                                                [
                                                    _target,
                                                    message.id,
                                                    repl.id,
                                                    userdet[1],
                                                    userdet[2],
                                                    reply_text,
                                                    original_language,
                                                    translated_text,
                                                    translation_confidence,
                                                    parse_tg_date(repl.date)[
                                                        "timestamp"
                                                    ],
                                                ]
                                            )

                                display_name = get_display_name(message.sender)
                                if self._chat_type != "Channel":
                                    substring = "PeerUser"
                                    string = str(message.from_id)
                                    if substring in string:
                                        user_id = re.sub("[^0-9]", "", string)
                                        nameID = str(user_id)
                                    else:
                                        nameID = str(message.from_id)
                                else:
                                    nameID = to_ent.id

                                timestamp = parse_tg_date(message.date)["timestamp"]
                                reply = message.reply_to_msg_id

                                if self.translate_check:
                                    _mess = process_message(
                                        message.text, self.user_language
                                    )
                                    message_text = _mess["message_text"]
                                    original_language = _mess["original_language"]
                                    translated_text = _mess["translated_text"]
                                    translation_confidence = _mess[
                                        "translation_confidence"
                                    ]
                                else:
                                    message_text = message.text
                                    original_language = "N/A"
                                    translated_text = "N/A"
                                    translation_confidence = "N/A"

                                if message.forwards is not None:
                                    forwards = int(message.forwards)
                                else:
                                    forwards = "N/A"

                                if message.views is not None:
                                    views = int(message.views)
                                else:
                                    views = "N/A"

                                total_reactions, reaction_detail = evaluate_reactions(
                                    message
                                )

                                if self.media_archive:
                                    if message.media is not None:
                                        path = await message.download_media(
                                            file=self.media_directory
                                        )
                                        files.append(path)
                                        media_file = path
                                    else:
                                        media_file = "N/A"
                                else:
                                    media_file = "N/A"

                                if message.media is not None:
                                    has_media = "TRUE"
                                else:
                                    has_media = "FALSE"

                                if message.replies:
                                    reply_count = int(message.replies.replies)
                                else:
                                    reply_count = "N/A"

                                if message.edit_date:
                                    edit_date = str(message.edit_date)
                                else:
                                    edit_date = "None"

                                """Need to find a way to calculate these in case these figures don't exist to make it
                                comparable across channels for a total engagement number (e.g. if replies/reactions are off).
                                If not N/A would cover if it's off, zero if it's none. Working on some better logic here."""

                                if (
                                    reply_count != "N/A"
                                    and self._total_participants is not None
                                ):
                                    reply_reach_ER = (
                                        reply_count / int(self._total_participants)
                                    ) * 100
                                else:
                                    reply_reach_ER = "N/A"

                                if reply_count != "N/A" and views != "N/A":
                                    reply_impressions_ER = (
                                        reply_count / int(views)
                                    ) * 100
                                else:
                                    reply_impressions_ER = "N/A"

                                if (
                                    forwards != "N/A"
                                    and self._total_participants is not None
                                ):
                                    forwards_reach_ER = (
                                        forwards / int(self._total_participants)
                                    ) * 100
                                else:
                                    forwards_reach_ER = "N/A"

                                if forwards != "N/A" and views != "N/A":
                                    forwards_impressions_ER = (
                                        forwards / int(views)
                                    ) * 100
                                else:
                                    forwards_impressions_ER = "N/A"

                                if (
                                    total_reactions != "N/A"
                                    and self._total_participants is not None
                                ):
                                    reactions_reach_ER = (
                                        total_reactions / int(self._total_participants)
                                    ) * 100
                                else:
                                    reactions_reach_ER = "N/A"

                                if total_reactions != "N/A" and views != "N/A":
                                    reactions_impressions_ER = (
                                        total_reactions / int(views)
                                    ) * 100
                                else:
                                    reactions_impressions_ER = "N/A"

                                post_url = (
                                    "https://t.me/s/" + _target + "/" + str(message.id)
                                )

                                message_list.append(
                                    [
                                        _target,
                                        message.id,
                                        display_name,
                                        nameID,
                                        message_text,
                                        original_language,
                                        translated_text,
                                        translation_confidence,
                                        timestamp,
                                        has_media,
                                        reply,
                                        reply_count,
                                        forwards,
                                        views,
                                        total_reactions,
                                        reply_reach_ER,
                                        reply_impressions_ER,
                                        forwards_reach_ER,
                                        forwards_impressions_ER,
                                        reactions_reach_ER,
                                        reactions_impressions_ER,
                                        reaction_detail["thumbs_up"],
                                        reaction_detail["thumbs_down"],
                                        reaction_detail["heart"],
                                        reaction_detail["fire"],
                                        reaction_detail["smile_with_hearts"],
                                        reaction_detail["clap"],
                                        reaction_detail["smile"],
                                        reaction_detail["thinking"],
                                        reaction_detail["exploding_head"],
                                        reaction_detail["scream"],
                                        reaction_detail["angry"],
                                        reaction_detail["single_tear"],
                                        reaction_detail["party_popper"],
                                        reaction_detail["starstruck"],
                                        reaction_detail["vomiting"],
                                        reaction_detail["poop"],
                                        reaction_detail["praying"],
                                        edit_date,
                                        post_url,
                                        media_file,
                                    ]
                                )

                                if message.forward is not None:
                                    try:
                                        forward_count += 1
                                        to_title = to_ent.title
                                        f_from_id = message.forward.original_fwd.from_id

                                        if f_from_id is not None:
                                            ent_info = await self.retrieve_entity_info(
                                                f_from_id, True
                                            )
                                            result = ""
                                            username = ent_info["entity"].username
                                            if ent_info:
                                                if ent_info["chat_type"] == "User":
                                                    result = (
                                                        "User: {} / ID: {} ".format(
                                                            ent_info["first_name"], ent_info["user_id"]
                                                        )
                                                    )
                                                elif (
                                                    ent_info["chat_type"] == "Megagroup"
                                                    or ent_info["chat_type"]
                                                    == "Gigagroup"
                                                    or ent_info["chat_type"] == "Chat"
                                                ):
                                                    result = ent_info["entity"].title
                                                elif ent_info["chat_type"] == "Channel":
                                                    result = ent_info["entity"].title
                                                    print("user")

                                            forwards_list.append(
                                                [
                                                    result,
                                                    _target,
                                                    to_title,
                                                    f_from_id,
                                                    username,
                                                    timestamp,
                                                ]
                                            )

                                    except ChannelPrivateError:
                                        private_count += 1
                                        continue

                                    except Exception as e:
                                        print("An exception occurred.", e)
                                        continue

                            except Exception as e:
                                print("An exception occurred.", e)

                        else:
                            message_list.append(
                                [
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                    "None",
                                ]
                            )

                        time.sleep(0.5)
                        bar()

                if self.reply_analysis is True:
                    if len(replies_list) > 0:
                        with open(
                            self.reply_file_archive, "w+", encoding="utf-8"
                        ) as rep_file:
                            c_replies.to_csv(rep_file, sep=";")

                    if len(user_replier_list) > 0:
                        with open(
                            self.reply_memberlist_filename, "w+", encoding="utf-8"
                        ) as repliers_file:
                            c_repliers.to_csv(repliers_file, sep=";")

                with open(self.file_archive, "w+", encoding="utf-8") as archive_file:
                    c_archive.to_csv(archive_file, sep=";")

                if self.json_check:
                    c_archive.to_json(
                        self.archive_filename_json,
                        orient="records",
                        compression="infer",
                        lines=True,
                        index=True,
                    )

                if self.forwards_check:
                    with open(
                        self.file_forwards, "w+", encoding="utf-8"
                    ) as forwards_file:
                        c_forwards.to_csv(forwards_file, sep=";")

                    if self.json_check:
                        c_forwards.to_json(
                            self.edgelist_filename_json,
                            orient="records",
                            compression="infer",
                            lines=True,
                            index=True,
                        )

                messages_found = int(c_archive.To.count()) - 1
                report_obj = createPlaceholdeCls()
                report_obj.messages_found = messages_found
                report_obj.file_archive = self.file_archive

                if self._chat_type == "Channel":
                    print_shell("channel_stat", report_obj)
                else:
                    pvalue_count = c_archive["Display_name"].value_counts()
                    df03 = pvalue_count.rename_axis("unique_values").reset_index(
                        name="counts"
                    )

                    """
                    message_frequency_count = {}
                    message_text = {}
                    word_count = {}
                    most_used_words = {}
                    most_used_words_filtered = {}
                    """
                    # message stats, top words

                    report_obj.poster_one = (
                        str(df03.iloc[0]["unique_values"])
                        + ", "
                        + str(df03.iloc[0]["counts"])
                        + " messages"
                    )
                    report_obj.poster_two = (
                        str(df03.iloc[1]["unique_values"])
                        + ", "
                        + str(df03.iloc[1]["counts"])
                        + " messages"
                    )
                    report_obj.poster_three = (
                        str(df03.iloc[2]["unique_values"])
                        + ", "
                        + str(df03.iloc[2]["counts"])
                        + " messages"
                    )
                    report_obj.poster_four = (
                        str(df03.iloc[3]["unique_values"])
                        + ", "
                        + str(df03.iloc[3]["counts"])
                        + " messages"
                    )
                    report_obj.poster_five = (
                        str(df03.iloc[4]["unique_values"])
                        + ", "
                        + str(df03.iloc[4]["counts"])
                        + " messages"
                    )

                    df04 = c_archive.Display_name.unique()
                    unique_active = len(df04)
                    report_obj.unique_active = unique_active
                    print_shell("group_stat", report_obj)

                if self.reply_analysis is True:
                    if len(replies_list) > 0:
                        replier_value_count = c_repliers["User ID"].value_counts()
                        replier_df = replier_value_count.rename_axis(
                            "unique_values"
                        ).reset_index(name="counts")

                        repliers = createPlaceholdeCls()
                        repliers.replier_one = (
                            str(replier_df.iloc[0]["unique_values"])
                            + ", "
                            + str(replier_df.iloc[0]["counts"])
                            + " replies"
                        )
                        repliers.replier_two = (
                            str(replier_df.iloc[1]["unique_values"])
                            + ", "
                            + str(replier_df.iloc[1]["counts"])
                            + " replies"
                        )
                        repliers.replier_three = (
                            str(replier_df.iloc[2]["unique_values"])
                            + ", "
                            + str(replier_df.iloc[2]["counts"])
                            + " replies"
                        )
                        repliers.replier_four = (
                            str(replier_df.iloc[3]["unique_values"])
                            + ", "
                            + str(replier_df.iloc[3]["counts"])
                            + " replies"
                        )
                        repliers.replier_five = (
                            str(replier_df.iloc[4]["unique_values"])
                            + ", "
                            + str(replier_df.iloc[4]["counts"])
                            + " replies"
                        )

                        replier_count_df = c_repliers["User ID"].unique()
                        replier_unique = len(replier_count_df)
                        repliers.user_replier_list_len = len(user_replier_list)
                        repliers.reply_file_archive = str(self.reply_file_archive)
                        repliers.reply_memberlist_filename = str(
                            self.reply_memberlist_filename
                        )
                        repliers.replier_unique = str(replier_unique)
                        print_shell("reply_stat", repliers)

                if self.forwards_check is True:
                    if forward_count >= 15:
                        forwards_found = c_forwards.Source.count()
                        value_count = c_forwards["Source"].value_counts()
                        c_f_stats = value_count.rename_axis(
                            "unique_values"
                        ).reset_index(name="counts")

                        report_forward = createPlaceholdeCls()
                        report_forward.forward_one = (
                            str(c_f_stats.iloc[0]["unique_values"])
                            + ", "
                            + str(c_f_stats.iloc[0]["counts"])
                            + " forwarded messages"
                        )
                        report_forward.forward_two = (
                            str(c_f_stats.iloc[1]["unique_values"])
                            + ", "
                            + str(c_f_stats.iloc[1]["counts"])
                            + " forwarded messages"
                        )
                        report_forward.forward_three = (
                            str(c_f_stats.iloc[2]["unique_values"])
                            + ", "
                            + str(c_f_stats.iloc[2]["counts"])
                            + " forwarded messages"
                        )
                        report_forward.forward_four = (
                            str(c_f_stats.iloc[3]["unique_values"])
                            + ", "
                            + str(c_f_stats.iloc[3]["counts"])
                            + " forwarded messages"
                        )
                        report_forward.forward_five = (
                            str(c_f_stats.iloc[4]["unique_values"])
                            + ", "
                            + str(c_f_stats.iloc[4]["counts"])
                            + " forwarded messages"
                        )

                        c_f_unique = c_forwards.Source.unique()
                        report_forward.unique_forwards = len(c_f_unique)
                        report_forward.forward_count = forward_count
                        report_forward.forwards_found = forwards_found
                        report_forward.edgelist_file = self.edgelist_file
                        report_forward.private_count = private_count
                        print_shell("forwarder_stat", report_forward)
                    else:
                        color_print_green(
                            " [!] Insufficient forwarded messages found",
                            self.edgelist_file,
                        )
