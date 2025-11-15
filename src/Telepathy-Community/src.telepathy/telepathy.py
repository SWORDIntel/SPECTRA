#!/usr/bin/python3

"""Telepathy cli interface:
    An OSINT toolkit for investigating Telegram chats.
"""

import pandas as pd
import datetime
import os
import getpass
import click
import configparser
import asyncio

from src.telepathy.utils import (
    print_banner,
    color_print_green,
    print_shell,
    createPlaceholdeCls,
)

from telethon.tl.functions.messages import GetDialogsRequest
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import (
    InputPeerEmpty,
    PeerUser,
    User,
    PeerLocated,
)
from telethon import TelegramClient, functions, types
from colorama import Fore, Style
from src.telepathy.telepathy_lib import Group_Chat_Analisys


class Telepathy_cli:

    alt = None
    target_type = None
    export = False

    def __init__(
        self,
        target,
        comprehensive,
        media,
        forwards,
        user,
        bot,
        location,
        alt,
        json,
        export,
        replies,
        translate,
        triangulate_membership,
    ):

        self.config_p = configparser.ConfigParser()
        self.config_p.read(os.path.join("config", "config.ini"))
        # Defining default values
        self.user_check = self.location_check = False
        self.basic = True if target else False
        self.reply_analysis = True if replies else False
        self.forwards_check = True if forwards else False
        self.comp_check = True if comprehensive else False
        self.media_archive = True if media else False
        self.json_check = True if json else False
        self.translate_check = True if translate else False
        self.last_date, self.chunk_size, self.user_language = None, 1000, "en"
        self.bot = bot is not None
        self.alt = 0 if alt is None else int(alt)
        self.filetime = datetime.datetime.now().strftime("%Y_%m_%d-%H_%M")
        self.filetime_clean = str(self.filetime)

        if bot:
            if ":" in bot:
                self.bot_id = bot.split(":")[0]
                self.hash = bot.split(":")[1]
            else:
                color_print_green(
                    " [!] ",
                    "The bot_id/bot_hash isn't valid. Pls insert a valid api_id//api_hash",
                )
        if user:
            self.user_check, self.basic = True, False
        if location:
            self.location_check, self.basic = True, False
        if export:
            self.export = True
            self.t = " "

        self.triangulate = True if triangulate_membership else False

        if "telepathy" in self.config_p.keys():
            self.telepathy_file = self.config_p["telepathy"]["telepathy_files"]
            self.json_file = os.path.join(
                self.telepathy_file, self.config_p["telepathy"]["json_file"]
            )
            self.login = os.path.join(
                self.telepathy_file, self.config_p["telepathy"]["login"]
            )
            self.log_file = os.path.join(
                self.telepathy_file, self.config_p["telepathy"]["log_file"]
            )
            self.export_file = os.path.join(
                self.telepathy_file, self.config_p["telepathy"]["export_file"]
            )
        else:
            self.telepathy_file = os.path.join(
                "..", "src", "telepathy", "telepathy_files"
            )
            self.json_file = os.path.join(self.telepathy_file, "json_files")
            self.login = os.path.join(self.telepathy_file, "login.txt")
            self.log_file = os.path.join(self.telepathy_file, "log.csv")
            self.export_file = os.path.join(self.telepathy_file, "export.csv")
        self.create_path(self.telepathy_file)
        self.overlaps_dir = os.path.join(self.telepathy_file, "overlaps")
        self.bots_dir = os.path.join(self.telepathy_file, "bots")
        self.create_path(self.overlaps_dir)
        self.target = target
        self.create_tg_client()

    @staticmethod
    def create_path(path_d):
        if not os.path.exists(path_d):
            os.makedirs(path_d)
        return path_d

    @staticmethod
    def login_function():
        api_id = input("Please enter your API ID:\n")
        api_hash = input("Please enter your API Hash:\n")
        phone_number = input("Please enter your phone number:\n")
        return api_id, api_hash, phone_number

    @staticmethod
    def clean_private_invite(url):
        if "https://t.me/+" in url:
            return url.replace("https://t.me/+", "https://t.me/joinchat/")

    def retrieve_alt(self):
        with open(self.login, encoding="utf-8") as file:
            _api_id = ""
            _api_hash = ""
            _phone_number = ""
            try:
                content = file.readlines()
                details = content[self.alt]
                _api_id, _api_hash, _phone_number = details.split(sep=",")
            except:
                _api_id, _api_hash, _phone_number = self.login_function()
                with open(self.login, "a+", encoding="utf-8") as file_io:
                    file_io.write(
                        _api_id + "," + _api_hash + "," + _phone_number + "\n"
                    )
            return _api_id, _api_hash, _phone_number

    def create_tg_client(self):
        if os.path.isfile(self.login) == False:
            api_id, api_hash, phone_number = self.login_function()
            with open(self.login, "w+", encoding="utf-8") as f:
                f.write(api_id + "," + api_hash + "," + phone_number + "\n")
        else:
            self.api_id, self.api_hash, self.phone_number = self.retrieve_alt()
        """End of API details"""
        self.client = TelegramClient(
            os.path.join(self.telepathy_file, "{}.session".format(self.phone_number)),
            self.api_id,
            self.api_hash,
        )

    async def connect_tg_client_and_run(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            await self.client.send_code_request(self.phone_number)
            try:
                await self.client.sign_in(
                    phone=self.phone_number,
                    code=input("Enter code: "),
                )
            except SessionPasswordNeededError:
                await self.client.sign_in(
                    password=getpass.getpass(
                        prompt="Password: ",
                        stream=None,
                    )
                )
            self.client(
                GetDialogsRequest(
                    offset_date=self.last_date,
                    offset_id=0,
                    offset_peer=InputPeerEmpty(),
                    limit=self.chunk_size,
                    hash=0,
                )
            )
        await self.start_process()

    async def start_process(self):
        if self.location_check:
            for _t in self.target:
                await self.analyze_location(_t)
        elif self.user_check:
            for _t in self.target:
                await self.analyze_user(_t)
        else:
            for _t in self.target:
                if self.export:
                    group_channel = Group_Chat_Analisys(
                        _t,
                        self.client,
                        self.log_file,
                        self.filetime,
                        self.reply_analysis,
                        self.forwards_check,
                        self.comp_check,
                        self.media_archive,
                        self.json_check,
                        self.translate_check,
                    )
                    await group_channel.f_export()
                else:
                    group_channel = Group_Chat_Analisys(
                        _t,
                        self.client,
                        self.log_file,
                        self.filetime,
                        self.reply_analysis,
                        self.forwards_check,
                        self.comp_check,
                        self.media_archive,
                        self.json_check,
                        self.translate_check,
                    )
                    await group_channel.analyze_group_channel()

    async def analyze_location(self, _target):
        print(
            Fore.GREEN
            + " [!] "
            + Style.RESET_ALL
            + "Searching for users near "
            + _target
            + "\n"
        )

        latitude, longitude = map(float, _target.split(','))

        locations_file = self.create_path(
            os.path.join(self.telepathy_file, self.config_p["telepathy"]["location"])
        )
        save_file = (
            locations_file
            + f"/{latitude}_{longitude}_locations_{self.filetime_clean}.csv"
        )

        locations_list = []
        l_save_list = []

        result = await self.client(
            functions.contacts.GetLocatedRequest(
                geo_point=types.InputGeoPoint(
                    lat=latitude,
                    long=longitude,
                )
            )
        )

        for user in result.updates[0].peers:
            try:
                if "PeerLocated" in str(user):
                    user_id = user.peer.user_id
                    distance = user.distance
                    locations_list.append([user_id, distance])
                    l_save_list.append(
                        [user_id, distance, latitude, longitude, self.filetime]
                    )
            except:
                pass

        user_df = pd.DataFrame(locations_list, columns=["User_ID", "Distance"])
        l_save_df = pd.DataFrame(
            l_save_list,
            columns=["User_ID", "Distance", "Latitude", "Longitude", "Date_retrieved"],
        )
        with open(save_file, "w+", encoding="utf-8") as f:
            l_save_df.to_csv(f, sep=";", index=False)
        total = len(locations_list)
        report = createPlaceholdeCls()
        report.save_file = save_file
        report.total = total
        print_shell("location_report", report)

    async def analyze_user(self, _target):
        self.target_type = "u"
        try:
            if "@" in _target:
                my_user = await self.client.get_entity(_target)
            else:
                user = int(_target)
                my_user = await self.client.get_entity(user)
        except:
            my_user = None
            pass

        if my_user is not None:
            user_first_name = my_user.first_name
            user_last_name = my_user.last_name
            if user_last_name is not None:
                user_full_name = str(user_first_name) + " " + str(user_last_name)
            else:
                user_full_name = str(user_first_name)

            if my_user.photo is not None:
                user_photo = my_user.photo.photo_id
            else:
                user_photo = "None"

            user_status = "Not found"
            if my_user.status is not None:
                if "Empty" in str(my_user.status):
                    user_status = "Last seen over a month ago"
                elif "Month" in str(my_user.status):
                    user_status = "Between a week and a month"
                elif "Week" in str(my_user.status):
                    user_status = "Between three and seven days"
                elif "Offline" in str(my_user.status):
                    user_status = "Offline"
                elif "Online" in str(my_user.status):
                    user_status = "Online"
                elif "Recently" in str(my_user.status):
                    user_status = "Recently (within two days)"
            else:
                user_status = "Not found"

            if my_user.restriction_reason is not None:
                ios_restriction = my_user.restriction_reason[0]
                if 1 in my_user.restriction_reason:
                    android_restriction = my_user.restriction_reason[1]
                    user_restrictions = (
                        str(ios_restriction) + ", " + str(android_restriction)
                    )
                else:
                    user_restrictions = str(ios_restriction)
            else:
                user_restrictions = "None"

            setattr(my_user, "user_restrictions", str(user_restrictions))
            setattr(my_user, "user_full_name", str(user_full_name))
            setattr(my_user, "user_photo", str(user_photo))
            setattr(my_user, "user_status", str(user_status))
            setattr(my_user, "id", str(my_user.id))
            setattr(my_user, "target", _target)
            print_shell("user", my_user)

        else:
            print(
                Fore.GREEN
                + " [!] "
                + Style.RESET_ALL
                + "User not found, this is likely because Telepathy has not encountered them yet."
            )

@click.command()
@click.option(
    "--target",
    "-t",
    multiple=True,
    help="Specifies a chat to investigate.",
)
@click.option(
    "--bot",
    "-b",
    multiple=True,
    help="BOT info, analyzing bot info, it needs API_HASH:API_ID.",
)
@click.option(
    "--comprehensive",
    "-c",
    is_flag=True,
    help="Comprehensive scan, includes archiving.",
)
@click.option(
    "--media", "-m", is_flag=True, help="Archives media in the specified chat."
)
@click.option("--forwards", "-f", is_flag=True, help="Scrapes forwarded messages.")
@click.option("--user", "-u", is_flag=True, help="Looks up a specified user ID.")
@click.option(
    "--location", "-l", is_flag=True, help="Finds users near to specified coordinates."
)
@click.option("--alt", "-a", default=0, help="Uses an alternative login.")
@click.option("--json", "-j", is_flag=True, default=False, help="Export to JSON.")
@click.option(
    "--export",
    "-e",
    is_flag=True,
    default=False,
    help="Export a list of chats your account is part of.",
)
@click.option(
    "--replies",
    "-r",
    is_flag=True,
    default=False,
    help="Enable replies analysis in channels.",
)
@click.option(
    "--translate",
    "-tr",
    is_flag=True,
    default=False,
    help="Enable translation of chat content.",
)
@click.option(
    "--triangulate_membership",
    "-tm",
    is_flag=True,
    default=False,
    help="Get interpolation from a list of groups",
)
def cli(
    target,
    comprehensive,
    media,
    forwards,
    user,
    bot,
    location,
    alt,
    json,
    export,
    replies,
    translate,
    triangulate_membership,
):
    print_banner()
    telepathy_cli = Telepathy_cli(
        target,
        comprehensive,
        media,
        forwards,
        user,
        bot,
        location,
        alt,
        json,
        export,
        replies,
        translate,
        triangulate_membership,
    )
    loop = asyncio.get_event_loop()
    loop.run_until_complete(telepathy_cli.connect_tg_client_and_run())

if __name__ == "__main__":
    cli()
