from discord import Embed, Message as DiscordMessage
from discord.abc import Messageable
from pydantic_snowflake import SnowflakeId
from tokenizers import Tokenizer

from asyncio import CancelledError, gather, get_running_loop, Task
from asyncio.queues import Queue as AsyncQueue
from datetime import datetime
from os import urandom
from traceback import print_exc
from typing import cast, Optional

from config import CONFIG
from db import get_db
from llm.client import DeepseekClient
from model.message import Message
from model.session import Session
from model.user import User
from session.host import SessionHost
from tool.types.chat_context import ChatContext
from type.chat import DeepseekChatCompletionMessageParam

TOKENIZER = Tokenizer.from_file("tokenizer.json")

DISCORD_MSG_LIMIT = 2000


def _resolve_mentions(message: DiscordMessage) -> str:
    """將訊息中的 @提及 轉換為『@名稱(ID:數字)』,方便模型辨識玩家。"""
    content = message.content
    for member in message.mentions:
        label = f"@{member.display_name}(ID:{member.id})"
        content = content.replace(f"<@{member.id}>", label)
        content = content.replace(f"<@!{member.id}>", label)
    return content


def _build_player_block(message: DiscordMessage, now: datetime) -> str:
    """把玩家訊息組裝成含時間、名稱、ID 的結構化區塊。"""
    resolved = _resolve_mentions(message)
    author = message.author
    injection_id = urandom(4).hex()
    return (
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} from {author.display_name} (ID: {author.id})\n"
        f"[MessageStart][{injection_id}]\n"
        f"{resolved}\n"
        f"[MessageEnd][{injection_id}]\n"
    )


def _chunk(text: str, limit: int = DISCORD_MSG_LIMIT) -> list[str]:
    """將過長文字依長度切分,盡量在換行處斷開。"""
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


class SessionManager():
    _meta: Session
    _host: SessionHost
    _queue: AsyncQueue[DiscordMessage]
    _client: DeepseekClient
    _messages: list[DeepseekChatCompletionMessageParam]
    _task: Optional[Task]
    _context_limit: int
    _keep_recent: int

    def __init__(self, data: Session, host: SessionHost) -> None:
        mode = CONFIG.llm.mode[data.kind]
        self._context_limit = mode.context_limit
        self._keep_recent = mode.keep_recent

        self._meta = data
        self._host = host
        self._queue = AsyncQueue()
        self._client = DeepseekClient(
            model=mode.model,
            reasoning=mode.reasoning,
            max_tokens=mode.max_tokens,
            temperature=mode.temperature,
            session_kind=data.kind,
        )
        self._messages = []
        self._task = None

    # ----- 生命週期 -----

    async def _fetch_messages(self) -> None:
        async with get_db() as conn:
            messages = await Message.get_all_after_summary_by_channel_id(
                conn=conn,
                channel_id=self._meta.channel_id,
            )

        self._messages = [message.to_openai() for message in messages]

    async def startup(self) -> None:
        loop = get_running_loop()
        await self._fetch_messages()
        self._task = loop.create_task(self._task_func())

    def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def enqueue(self, message: DiscordMessage) -> None:
        if self._meta.channel_id != message.channel.id:
            raise ValueError("Message channel does not match session channel.")
        self._queue.put_nowait(message)

    # ----- token 計算與摘要 -----

    async def _calc_tokens(self, content: Optional[str]) -> int:
        if not content:
            return 0
        loop = get_running_loop()
        encode_data = await loop.run_in_executor(None, TOKENIZER.encode, content)
        return len(encode_data.tokens)

    async def _recalc_token(self, save: bool = True) -> None:
        total_content = ""
        for message in self._messages:
            content = message.get("content")
            if isinstance(content, str):
                total_content += content

        loop = get_running_loop()
        encode_data = await loop.run_in_executor(None, TOKENIZER.encode, total_content)
        self._meta.token_usage = len(encode_data.tokens)

        if save:
            async with get_db() as conn:
                await self._meta.save(conn=conn)

    async def check_and_summarize(self) -> None:
        if self._meta.token_usage < self._context_limit:
            return

        last_summary = self._meta.summary
        async with get_db() as conn:
            recent_split_message = await Message.get_recent_by_channel_id(
                conn=conn,
                channel_id=self._meta.channel_id,
                keep_recent=self._keep_recent,
            )
            if recent_split_message is None:
                return

            recent_split_uid = recent_split_message.uid
            need_summary_messages = await Message.get_need_summary_by_channel_id(
                conn=conn,
                channel_id=self._meta.channel_id,
                recent_uid=recent_split_uid,
            )

            new_summary = await self._client.summarize(
                last_summary=last_summary,
                messages=need_summary_messages,
            )

            self._meta.summary = new_summary
            self._meta.seek_sid = recent_split_uid

            await self._fetch_messages()
            await self._recalc_token(save=False)
            await self._meta.save(conn=conn)

    # ----- 脈絡與訊息轉換 -----

    def _build_context(
        self,
        conn,
        message: DiscordMessage,
        now: datetime,
    ) -> ChatContext:
        if self._meta.kind == "chargen":
            owner_id = (
                int(self._meta.chargen_owner_id)
                if self._meta.chargen_owner_id is not None else 0
            )
            game_channel_id = (
                int(self._meta.chargen_channel_id)
                if self._meta.chargen_channel_id is not None
                else int(self._meta.channel_id)
            )
            fallback = message.author.display_name if message else "冒險者"
            display_name = self._host.resolve_display_name(
                game_channel_id, owner_id, fallback
            )
            username = str(message.author) if message else str(owner_id)
            return ChatContext(
                conn,
                "chargen",
                message=message,
                now=now,
                summary=self._meta.summary,
                target_channel_id=game_channel_id,
                owner_user_id=owner_id,
                owner_username=username,
                owner_display_name=display_name,
            )

        return ChatContext(
            conn,
            "game",
            message=message,
            now=now,
            summary=self._meta.summary,
            target_channel_id=int(self._meta.channel_id),
        )

    def _to_models(
        self,
        new_messages: list[DeepseekChatCompletionMessageParam],
    ) -> list[Message]:
        channel_id = SnowflakeId(int(self._meta.channel_id))
        models: list[Message] = []
        for msg in new_messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "assistant":
                models.append(Message(
                    channel_id=channel_id,
                    role="assistant",
                    content=content if isinstance(content, str) else None,
                    reasoning_content=msg.get("reasoning_content"),
                    tool_calls=[
                        call_data
                        for call_data in msg.get("tool_calls", [])
                        if "function" in call_data
                    ] or None,
                ))
            elif role == "tool":
                models.append(Message(
                    channel_id=channel_id,
                    role="tool",
                    content=content if isinstance(content, str) else "",
                    tool_call_id=msg.get("tool_call_id"),
                ))
        return models

    @staticmethod
    def _extract_reply(
        new_messages: list[DeepseekChatCompletionMessageParam],
    ) -> tuple[Optional[str], Optional[str]]:
        content: Optional[str] = None
        reasoning_parts: list[str] = []
        for msg in new_messages:
            if msg.get("role") != "assistant":
                continue
            reasoning = msg.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                reasoning_parts.append(reasoning)
            value = msg.get("content")
            if isinstance(value, str) and value:
                content = value
        reasoning = "\n\n".join(reasoning_parts) if reasoning_parts else None
        return content, reasoning

    # ----- 送出 Discord 訊息 -----

    @staticmethod
    async def _first_send(
        channel: Messageable,
        reply_to: Optional[DiscordMessage],
        content: Optional[str],
        embeds: list[Embed],
    ) -> None:
        if reply_to is not None:
            if content is not None:
                await reply_to.reply(content=content, embeds=embeds)
            else:
                await reply_to.reply(embeds=embeds)
        else:
            if content is not None:
                await channel.send(content=content, embeds=embeds)
            else:
                await channel.send(embeds=embeds)

    async def _send(
        self,
        channel: Messageable,
        content: str,
        ctx: Optional[ChatContext] = None,
        *,
        reply_to: Optional[DiscordMessage] = None,
        reasoning: Optional[str] = None,
    ) -> None:
        embeds = [
            event.to_discord_embed()
            for event in ctx.dice_events
        ] if ctx else []
        chunks = _chunk(content)

        if not chunks:
            if embeds:
                await self._first_send(channel, reply_to, None, embeds[:10])
            rest: list[str] = []
        else:
            await self._first_send(channel, reply_to, chunks[0], embeds[:10])
            rest = chunks[1:]

        for chunk in rest:
            await channel.send(content=chunk)

        if CONFIG.game.show_reasoning and reasoning:
            for chunk in _chunk(f"🧠 思考過程:\n{reasoning}"):
                await channel.send(content=chunk)

    # ----- 開場導言 -----

    async def send_opening(self, channel: Messageable) -> None:
        """產生並送出開場導言(/start 的遊戲開場或私訊創角的開場引導)。"""
        async with get_db() as conn:
            content = await self._client.generate_opening()

            opening = Message(
                channel_id=SnowflakeId(int(self._meta.channel_id)),
                role="assistant",
                content=content,
            )
            await opening.save(conn)

            self._messages.append(opening.to_openai())
            add_tokens = await self._calc_tokens(content)
            self._meta.token_usage += add_tokens
            await self._meta.save(conn)

        await self._send(channel, content or "（無法生成開場）")

    # ----- 訊息處理 -----

    async def _handle_message(self, discord_message: DiscordMessage) -> bool:
        """處理單則訊息。回傳 True 代表此 session 已結束(創角完成)。"""
        now = datetime.now().astimezone()
        channel_id = int(self._meta.channel_id)

        # 私訊創角:僅擁有者本人可推進
        if self._meta.kind == "chargen":
            owner_id = self._meta.chargen_owner_id
            if owner_id is not None and int(owner_id) != discord_message.author.id:
                return False

        async with get_db() as conn:
            # 一般遊戲:沒有角色的玩家先導向私訊創角,不在頻道回應
            if self._meta.kind == "game":
                user = await User.get_by_uid_and_channel_id(
                    conn, discord_message.author.id, channel_id
                )
                if user is None:
                    await self._host.begin_chargen(
                        game_channel_id=channel_id,
                        author=discord_message.author,
                        trigger=discord_message,
                    )
                    return False

            ctx = self._build_context(conn, discord_message, now)
            user_message = Message(
                channel_id=SnowflakeId(channel_id),
                message_id=SnowflakeId(discord_message.id),
                role="user",
                name=discord_message.author.display_name,
                content=_build_player_block(discord_message, now),
            )
            user_openai = user_message.to_openai()

            new_messages = await self._client.generate(
                ctx=ctx,
                messages=self._messages + [user_openai],
            )

            self._messages.append(user_openai)
            self._messages.extend(new_messages)

            # 持久化:玩家訊息 + 本回合所有 assistant / tool 訊息
            await user_message.save(conn)
            for model in self._to_models(new_messages):
                await model.save(conn)

            # token 統計
            str_content = [
                user_message.content,
            ] + cast(list[str], [
                msg.get("content")
                for msg in new_messages
                if isinstance(msg.get("content"), str)
            ])
            token_counts = await gather(*[
                self._calc_tokens(content)
                for content in str_content
            ])

            self._meta.token_usage += sum(token_counts)
            await self._meta.save(conn)

        reply_content, reasoning = self._extract_reply(new_messages)
        await self._send(
            discord_message.channel,
            reply_content or "無法生成回覆內容",
            ctx,
            reply_to=discord_message,
            reasoning=reasoning,
        )

        # 創角完成 -> 收尾並結束此 session
        if self._meta.kind == "chargen" and ctx.character_created:
            await self._host.finish_chargen(
                dm_channel_id=channel_id,
                game_channel_id=(
                    int(self._meta.chargen_channel_id)
                    if self._meta.chargen_channel_id is not None else channel_id
                ),
                owner_id=(
                    int(self._meta.chargen_owner_id)
                    if self._meta.chargen_owner_id is not None else 0
                ),
                display_name=ctx.owner_display_name or "冒險者",
            )
            return True

        await self.check_and_summarize()
        return False

    async def _task_func(self) -> None:
        while True:
            discord_message = await self._queue.get()
            try:
                finished = await self._handle_message(discord_message)
                if finished:
                    return
            except CancelledError:
                return
            except Exception:  # noqa: BLE001 - 單則訊息失敗不應終止 worker
                print_exc()
                continue
