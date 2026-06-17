from asyncpg import Connection
from openai.types.chat import (
    ChatCompletionMessageFunctionToolCallParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)
from orjson import dumps, loads
from pydantic import BaseModel, Field
from pydantic_snowflake import SnowflakeId, SnowflakeGenerator

from typing import Literal, Optional, Self, TypeAlias

from type.chat import (
    DeepseekChatCompletionMessageParam,
    DeepseekChatCompletionAssistantMessageParam
)
from type.uid import UidType

id_generator = SnowflakeGenerator()

Role: TypeAlias = Literal["user", "assistant", "tool", "system"]


class Message(BaseModel):
    uid: SnowflakeId = Field(default_factory=id_generator.next)
    channel_id: SnowflakeId
    message_id: Optional[SnowflakeId] = None
    role: Role
    name: Optional[str] = None
    content: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: Optional[list[ChatCompletionMessageFunctionToolCallParam]] = None
    tool_call_id: Optional[str] = None

    async def save(self, conn: Connection) -> None:
        await conn.execute(
            """
            INSERT INTO messages (
                uid, channel_id, message_id, role, name, content, tool_calls, tool_call_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (uid) DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                message_id = EXCLUDED.message_id,
                role = EXCLUDED.role,
                name = EXCLUDED.name,
                content = EXCLUDED.content,
                tool_calls = EXCLUDED.tool_calls,
                tool_call_id = EXCLUDED.tool_call_id
            """,
            int(self.uid),
            int(self.channel_id),
            int(self.message_id) if self.message_id is not None else None,
            self.role,
            self.name,
            self.content,
            dumps(self.tool_calls).decode("utf-8")
            if self.tool_calls is not None else None,
            self.tool_call_id,
        )

    def to_openai(self) -> DeepseekChatCompletionMessageParam:

        if self.role == "user":
            if self.content is None:
                raise ValueError("User messages must have content")

            return ChatCompletionUserMessageParam(
                role=self.role,
                name=self.name or "",
                content=self.content,
            )
        if self.role == "assistant":
            result = DeepseekChatCompletionAssistantMessageParam(
                role=self.role,
                content=self.content,
                reasoning_content=self.reasoning_content,
                # tool_calls=self.tool_calls or None,
            )
            if self.tool_calls:
                result["tool_calls"] = self.tool_calls
            return result
        if self.role == "tool":
            if self.content is None:
                raise ValueError("Tool messages must have content")

            return ChatCompletionToolMessageParam(
                role=self.role,
                content=self.content,
                tool_call_id=self.tool_call_id or "",
            )
        if self.role == "system":
            if self.content is None:
                raise ValueError("System messages must have content")

            return ChatCompletionSystemMessageParam(
                role=self.role,
                content=self.content,
            )
        raise ValueError(f"Invalid role: {self.role}")

    @classmethod
    async def get(cls, conn: Connection, uid: UidType) -> Optional[Self]:
        row = await conn.fetchrow(
            "SELECT * FROM messages WHERE uid = $1",
            int(uid),
        )

        return cls.model_validate(dict(row)) if row else None

    @classmethod
    async def get_all_by_channel_id(cls, conn: Connection, channel_id: UidType) -> list[Self]:
        rows = await conn.fetch(
            "SELECT * FROM messages WHERE channel_id = $1 ORDER BY uid ASC",
            int(channel_id),
        )
        return [cls.model_validate(dict(row)) for row in rows]

    @classmethod
    async def get_all_after_summary_by_channel_id(
        cls,
        conn: Connection,
        channel_id: UidType,
    ) -> list[Self]:
        rows = await conn.fetch("""
            SELECT * FROM messages
            WHERE channel_id = $1
                AND uid >= (SELECT seek_sid FROM sessions WHERE channel_id = $1)
            ORDER BY uid ASC
        """, int(channel_id))
        return [cls.model_validate(dict(row)) for row in rows]
    
    @classmethod
    async def get_recent_by_channel_id(
        cls,
        conn: Connection,
        channel_id: UidType,
        keep_recent: int = 20,
    ) -> Optional[Self]:
        row = await conn.fetchrow("""
            SELECT * FROM messages
            WHERE channel_id = $1
            ORDER BY uid DESC
            LIMIT 1 OFFSET $2
        """, int(channel_id), keep_recent - 1)

        return cls.model_validate(dict(row)) if row else None

    @classmethod
    async def get_need_summary_by_channel_id(
        cls,
        conn: Connection,
        channel_id: UidType,
        recent_uid: UidType,
    ) -> list[Self]:
        rows = await conn.fetch("""
            SELECT * FROM messages
            WHERE channel_id = $1
                AND uid >= (SELECT seek_sid FROM sessions WHERE channel_id = $1)
                AND uid < $2
            ORDER BY uid ASC
        """, int(channel_id), int(recent_uid))
        return [cls.model_validate(dict(row)) for row in rows]
