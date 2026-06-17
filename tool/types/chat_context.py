from asyncpg import Connection
from discord import Message as DiscordMessage

from datetime import datetime, timezone
from typing import Optional

from model.roster import Roster
from model.session import SessionKind

from .dice_event import DiceEvent


class ChatContext():
    """單次生成的執行脈絡:同時承載輸入(連線、玩家訊息、時間、摘要)與
    工具產生的副作用(擲骰、公布名單、創角完成)。"""

    conn: Connection
    message: DiscordMessage
    session_kind: SessionKind
    now: datetime
    summary: str
    # 角色相關工具實際操作的頻道;一般遊戲等同訊息頻道,創角時為對應的遊戲頻道
    target_channel_id: int
    # 創角流程專用:這個角色屬於哪位玩家
    owner_user_id: Optional[int]
    owner_username: Optional[str]
    owner_display_name: Optional[str]
    # 副作用收集
    dice_events: list[DiceEvent]
    revealed_teams: list[Roster]
    character_created: bool

    def __init__(
        self,
        conn: Connection,
        session_kind: SessionKind,
        message: DiscordMessage,
        *,
        now: Optional[datetime] = None,
        summary: str = "",
        target_channel_id: Optional[int] = None,
        owner_user_id: Optional[int] = None,
        owner_username: Optional[str] = None,
        owner_display_name: Optional[str] = None,
    ) -> None:
        self.conn = conn
        self.message = message
        self.session_kind = session_kind
        self.now = now or datetime.now(timezone.utc)
        self.summary = summary

        resolved = target_channel_id
        if resolved is None and message is not None:
            resolved = message.channel.id
        if resolved is None:
            raise ValueError("ChatContext 需要 target_channel_id 或 message 至少其一")
        self.target_channel_id = resolved

        self.owner_user_id = owner_user_id
        self.owner_username = owner_username
        self.owner_display_name = owner_display_name

        self.dice_events = []
        self.revealed_teams = []
        self.character_created = False

    @property
    def channel_id(self) -> int:
        return self.target_channel_id
