"""
SPECTRA-004 Data Models
=======================
NamedTuple definitions for the SPECTRA archiver system.
"""
from datetime import datetime
from typing import List, NamedTuple, Optional


class User(NamedTuple):
    id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    tags: List[str]
    avatar: Optional[str]
    last_updated: Optional[datetime]


class Media(NamedTuple):
    id: int
    type: str
    url: Optional[str]
    title: Optional[str]
    description: Optional[str | List | dict]
    thumb: Optional[str]
    checksum: Optional[str]


class Message(NamedTuple):
    id: int
    type: str
    date: datetime
    edit_date: Optional[datetime]
    content: Optional[str]
    reply_to: Optional[int]
    user: Optional[User]
    media: Optional[Media]
    checksum: Optional[str]


class Month(NamedTuple):
    date: datetime
    slug: str
    label: str
    count: int


class Day(NamedTuple):
    date: datetime
    slug: str
    label: str
    count: int
    page: int


__all__ = ["User", "Media", "Message", "Month", "Day"]
