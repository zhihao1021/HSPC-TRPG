from discord import (
    Bot,
    Member,
    Message as DiscordMessage,
    User as DiscordUser,
)
from discord.abc import Messageable

from traceback import print_exc
from typing import Optional, Union

from db import get_db
from model.session import Session
from session.host import SessionHost
from session.manager import SessionManager

# 頻道內「隱藏提示」訊息的自動消失秒數
HIDDEN_NOTICE_DELETE_AFTER = 30.0


class BotSessionHost():
    """實作 session.host.SessionHost,負責跨頻道與 Discord 層級的編排。"""

    def __init__(self, bot: "TRPGBot") -> None:
        self._bot = bot

    @property
    def _sessions(self) -> dict[int, SessionManager]:
        return self._bot.sessions

    def _get_messageable(self, channel_id: int) -> Optional[Messageable]:
        channel = self._bot.get_channel(channel_id)
        return channel if isinstance(channel, Messageable) else None

    @staticmethod
    def _channel_link(message: DiscordMessage) -> str:
        channel_id = message.channel.id
        if message.guild is not None:
            return f"https://discord.com/channels/{message.guild.id}/{channel_id}"
        return f"<#{channel_id}>"

    @staticmethod
    async def _hidden_notice(message: DiscordMessage, text: str) -> None:
        """以『自動消失的回覆』提示玩家,降低對遊戲的干擾。"""
        try:
            await message.reply(
                text,
                delete_after=HIDDEN_NOTICE_DELETE_AFTER,
                mention_author=True,
            )
        except Exception:  # noqa: BLE001 - 訊息可能已被刪除等
            print_exc()

    def resolve_display_name(
        self,
        game_channel_id: int,
        user_id: int,
        fallback: str,
    ) -> str:
        channel = self._bot.get_channel(game_channel_id)
        guild = getattr(channel, "guild", None)
        if guild is not None:
            member = guild.get_member(user_id)
            if member is not None:
                return member.display_name
        return fallback

    async def begin_chargen(
        self,
        *,
        game_channel_id: int,
        author: Union[Member, DiscordUser],
        trigger: DiscordMessage,
    ) -> None:
        # 已在創角中:僅提醒,不重複建立
        async with get_db() as conn:
            existing = await Session.find_chargen(conn, author.id, game_channel_id)
        if existing is not None:
            await self._hidden_notice(
                trigger,
                "你正在進行角色創建,請查看與我的私訊完成創角後再回到頻道行動。",
            )
            return

        try:
            dm = await author.create_dm()
        except Exception:  # noqa: BLE001 - 玩家可能關閉私訊
            print_exc()
            await self._hidden_notice(
                trigger,
                "你還沒有冒險角色,但我無法私訊你。請開啟此伺服器的私訊權限後再發言一次。",
            )
            return

        async with get_db() as conn:
            session = await Session.create_chargen(
                conn,
                channel_id=dm.id,
                chargen_owner_id=author.id,
                chargen_channel_id=game_channel_id,
            )

        manager = SessionManager(session, host=self)
        await manager.startup()
        self._sessions[dm.id] = manager

        await self._hidden_notice(
            trigger,
            "你還沒有冒險角色!我已私訊你進行創角,請查看私訊並依指示完成,稍後再回到頻道行動。",
        )

        try:
            await dm.send(
                f"👋 這裡是**角色創建**私訊。你正在為遊戲頻道 {self._channel_link(trigger)} "
                "建立角色,完成後請回到該頻道開始冒險。"
            )
        except Exception:  # noqa: BLE001
            print_exc()

        await manager.send_opening(dm)

    async def finish_chargen(
        self,
        *,
        dm_channel_id: int,
        game_channel_id: int,
        owner_id: int,
        display_name: str,
    ) -> None:
        async with get_db() as conn:
            await Session.delete(conn, dm_channel_id)

        # manager 會在 _handle_message 回傳 True 後自行結束 task,這裡僅解除註冊
        self._sessions.pop(dm_channel_id, None)

        dm = self._get_messageable(dm_channel_id)
        if dm is not None:
            try:
                await dm.send("✅ 角色建立完成!請回到遊戲頻道,開始你的冒險吧。")
            except Exception:  # noqa: BLE001
                print_exc()

        game_channel = self._get_messageable(game_channel_id)
        if game_channel is not None:
            try:
                await game_channel.send(
                    f"🎉 <@{owner_id}> 的角色「{display_name}」已準備就緒,踏入了這場冒險!"
                )
            except Exception:  # noqa: BLE001
                print_exc()


class TRPGBot(Bot):
    """承載跨指令共享狀態(session registry 與 host)的 Bot。"""

    sessions: dict[int, SessionManager]
    host: SessionHost

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.sessions = {}
        self.host = BotSessionHost(self)
