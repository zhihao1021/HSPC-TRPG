"""SessionManager 與 Bot 之間的橋接介面。

SessionManager 負責單一頻道的對話處理,但「跨頻道」與「Discord 層級」的編排
(開啟私訊創角、創角完成後的清理與公告、解析玩家在群組中的顯示名稱)需要
Bot 提供。為避免 manager 與 bot 互相 import 形成循環,這裡以 Protocol 定義
manager 對 host 的需求,由 bot 端的物件實作。
"""
from discord import Member, Message as DiscordMessage, User as DiscordUser

from typing import Protocol, Union


class SessionHost(Protocol):
    async def begin_chargen(
        self,
        *,
        game_channel_id: int,
        author: Union[Member, DiscordUser],
        trigger: DiscordMessage,
    ) -> None:
        """為尚無角色的玩家開啟私訊創角流程。"""
        ...

    async def finish_chargen(
        self,
        *,
        dm_channel_id: int,
        game_channel_id: int,
        owner_id: int,
        display_name: str,
    ) -> None:
        """創角完成後:刪除臨時 session、解除註冊、於遊戲頻道公告。"""
        ...

    def resolve_display_name(
        self,
        game_channel_id: int,
        user_id: int,
        fallback: str,
    ) -> str:
        """取得玩家在遊戲頻道所屬群組中的顯示名稱。"""
        ...
