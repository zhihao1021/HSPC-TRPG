from discord import Message as DiscordMessage
from openai.types.chat import ChatCompletionMessageParam
from pydantic_snowflake import SnowflakeId
from tokenizers import Tokenizer

from asyncio import CancelledError, gather, get_running_loop, Task, wait_for
from asyncio.queues import Queue as AsyncQueue
from typing import Optional

from config import CONFIG
from db import get_db
from llm.client import DeepseekClient
from model.message import Message
from model.session import Session
from tool.types.chat_context import ChatContext

TOKENIZER = Tokenizer.from_file("tokenizer.json")


class SessionManager():
    _meta: Session
    _queue: AsyncQueue[DiscordMessage]
    _client: DeepseekClient
    _messages: list[ChatCompletionMessageParam]
    _task: Optional[Task]
    _context_limit: int
    _keep_recent: int

    def __init__(self, data: Session) -> None:
        model = CONFIG.llm.mode[data.kind].model
        reasoning = CONFIG.llm.mode[data.kind].reasoning
        max_tokens = CONFIG.llm.mode[data.kind].max_tokens
        temperature = CONFIG.llm.mode[data.kind].temperature
        self._context_limit = CONFIG.llm.mode[data.kind].context_limit
        self._keep_recent = CONFIG.llm.mode[data.kind].keep_recent

        self._meta = data
        self._queue = AsyncQueue()
        self._client = DeepseekClient(
            model=model,
            reasoning=reasoning,
            max_tokens=max_tokens,
            temperature=temperature,
            chat_type=data.kind,
        )
        self._messages = []
        self._task = None

    async def _fetch_messages(self):
        async with get_db() as conn:
            messages = await Message.get_all_after_summary_by_channel_id(
                conn=conn,
                channel_id=self._meta.channel_id,
            )

        self._messages = [
            message.to_openai()
            for message in messages
        ]

    async def startup(self):
        loop = get_running_loop()
        await self._fetch_messages()
        self._task = loop.create_task(self._task_func())

    def shutdown(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _calc_tokens(self, content: Optional[str]) -> int:
        if content is None:
            return 0

        loop = get_running_loop()
        encode_data = await loop.run_in_executor(
            None,
            TOKENIZER.encode,
            content
        )
        return len(encode_data.tokens)

    async def _recalc_token(self, save: bool = True) -> None:
        total_content = ""

        for message in self._messages:
            content = message.get("content")
            if content is None:
                continue

            if isinstance(content, str):
                total_content += content

        loop = get_running_loop()
        encode_data = await loop.run_in_executor(
            None,
            TOKENIZER.encode,
            total_content
        )
        token_count = len(encode_data.tokens)

        self._meta.token_usage = token_count
        if save:
            async with get_db() as conn:
                await self._meta.save(conn=conn)

    async def check_and_summarize(self):
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

    async def reply_message(self, ctx: ChatContext, content: str) -> None:
        pass

    async def _task_func(self):
        while True:
            discord_message = await wait_for(
                self._queue.get(),
                timeout=None
            )

            message = Message(
                channel_id=SnowflakeId(discord_message.channel.id),
                message_id=SnowflakeId(discord_message.id),
                role="user",
                name=discord_message.author.name,
                content=discord_message.content,
            )

            async with get_db() as conn:
                try:
                    chat_context = ChatContext(
                        conn=conn,
                        message=discord_message,
                        session_kind=self._meta.kind,
                    )

                    message_openai = message.to_openai()

                    new_messages = await self._client.generate(
                        ctx=chat_context,
                        messages=self._messages + [message_openai]
                    )

                    self._messages.append(message_openai)
                    self._messages.extend(new_messages)

                    reply_content = new_messages[-1].get("content")
                    if isinstance(reply_content, str):
                        await self.reply_message(chat_context, reply_content)
                    else:
                        await self.reply_message(chat_context, "無法生成回覆內容")
                except CancelledError:
                    return
                except Exception as e:
                    print(f"Error processing message: {e}")
                    continue

            message_tokens = await gather(*[
                self._calc_tokens(msg["content"])
                for msg in new_messages
                if "content" in msg and isinstance(msg["content"], str)
            ])
            add_tokens = await self._calc_tokens(message.content) + sum(message_tokens)

            self._meta.token_usage += add_tokens
            async with get_db() as conn:
                await message.save(conn=conn)
                await self._meta.save(conn=conn)

            await self.check_and_summarize()

    def enqueue(
        self,
        message: DiscordMessage,
    ) -> None:
        if self._meta.channel_id != message.channel.id:
            raise ValueError("Message channel does not match session channel.")

        self._queue.put_nowait(message)
