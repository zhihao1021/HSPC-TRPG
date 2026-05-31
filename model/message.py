from asyncpg import Connection
from openai.types.chat import ChatCompletionMessageToolCallUnion
from orjson import dumps
from pydantic import BaseModel, Field
from pydantic_snowflake import SnowflakeId, SnowflakeGenerator

from typing import Literal, Optional

id_generator = SnowflakeGenerator()


class Message(BaseModel):
    uid: SnowflakeId = Field(
        default_factory=id_generator.next
    )
    channel_id: SnowflakeId
    role: Literal["user", "assistant"]
    name: Optional[str] = None
    content: str = ""
    tool_calls: Optional[list[ChatCompletionMessageToolCallUnion]] = None
    tool_call_id: Optional[str] = None

    async def insert(self, conn: Connection) -> None:
        await conn.execute(
            """
            INSERT INTO messages (
                uid,
                channel_id,
                role,
                name,
                content,
                tool_calls,
                tool_call_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            self.uid,
            self.channel_id,
            self.role,
            self.name,
            self.content,
            dumps(self.tool_calls).decode("utf-8") if self.tool_calls is not None else None,
            self.tool_call_id,
        )
