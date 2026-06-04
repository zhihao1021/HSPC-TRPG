from discord import Message as DiscordMessage
from openai.types.chat import ChatCompletionMessageParam
from pydantic_snowflake import SnowflakeId
from tokenizers import Tokenizer

from asyncio import CancelledError, gather, get_running_loop, Task, wait_for
from asyncio.queues import Queue as AsyncQueue
from typing import Optional

import config
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

    def __init__(self, data: Session) -> None:
        model = config.llm_model() if data.kind == "game"\
            else config.chargen_model()
        reasoning = config.llm_reasoning_enabled() if data.kind == "game"\
            else config.chargen_reasoning_enabled()

        self._meta = data
        self._queue = AsyncQueue()
        self._client = DeepseekClient(
            model=model,
            reasoning=reasoning,
        )
        self._messages = []
        self._task = None

    async def startup(self):
        loop = get_running_loop()
        async with get_db() as conn:
            messages = await Message.get_all_by_channel_id(
                conn=conn,
                channel_id=self._meta.channel_id,
            )

        self._messages = [
            message.to_openai()
            for message in messages
        ]

        await self.recalc_token()
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

    async def recalc_token(self):
        total_content = ""

        for message in self._messages:
            content = message.get("content")
            if content is None:
                continue

            if isinstance(content, str):
                total_content += content
            else:
                content += "".join([
                    part if isinstance(part, str)
                    else part.get("text", "")
                    for part in content
                ])

        loop = get_running_loop()
        encode_data = await loop.run_in_executor(
            None,
            TOKENIZER.encode,
            total_content
        )
        token_count = len(encode_data.tokens)

        self._meta.token_usage = token_count
        async with get_db() as conn:
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

    def enqueue(
        self,
        message: DiscordMessage,
    ) -> None:
        if self._meta.channel_id != message.channel.id:
            raise ValueError("Message channel does not match session channel.")

        self._queue.put_nowait(message)
