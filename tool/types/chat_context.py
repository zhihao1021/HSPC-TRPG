from typing import Any

from asyncpg import Connection
from discord import Message as DiscordMessage
from pydantic import Field

from model.session import SessionKind

from .dice_event import DiceEvent


class ChatContext():
    conn: Connection
    message: DiscordMessage
    session_kind: SessionKind
    dice_events: list[DiceEvent]

    def __init__(
        self,
        conn: Connection,
        message: DiscordMessage,
        session_kind: SessionKind,
    ) -> None:
        self.conn = conn
        self.message = message
        self.session_kind = session_kind
        self.dice_events = []
