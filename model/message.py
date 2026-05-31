from asyncpg import Connection
from orjson import dumps, loads
from pydantic import BaseModel, Field
from pydantic_snowflake import SnowflakeId, SnowflakeGenerator

from typing import Any, Literal, Optional

id_generator = SnowflakeGenerator()

# 對話訊息的角色:
#   user      -> 玩家發言
#   assistant -> 模型(GM)回應,可能附帶 tool_calls
#   tool      -> 工具執行結果,需附帶 tool_call_id
#   system    -> 系統訊息(一般不存 DB,僅組裝時動態加入)
Role = Literal["user", "assistant", "tool", "system"]


class Message(BaseModel):
    uid: SnowflakeId = Field(default_factory=id_generator.next)
    channel_id: SnowflakeId
    # 玩家訊息對應的 Discord Message ID;非玩家訊息(assistant/tool/system)為 None
    message_id: Optional[SnowflakeId] = None
    role: Role
    name: Optional[str] = None
    content: str = ""
    # OpenAI tool_calls 結構(list of {id, type, function:{name, arguments}})
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_call_id: Optional[str] = None

    async def insert(self, conn: Connection) -> None:
        await conn.execute(
            """
            INSERT INTO messages (
                uid, channel_id, message_id, role, name, content, tool_calls, tool_call_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            int(self.uid),
            int(self.channel_id),
            int(self.message_id) if self.message_id is not None else None,
            self.role,
            self.name,
            self.content,
            dumps(self.tool_calls).decode("utf-8")
            if self.tool_calls is not None
            else None,
            self.tool_call_id,
        )

    def to_openai(self) -> dict[str, Any]:
        """轉換成可直接傳入 OpenAI / Deepseek chat completion 的訊息格式。"""
        if self.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
            if self.tool_calls:
                msg["tool_calls"] = self.tool_calls
            return msg
        if self.role == "tool":
            return {
                "role": "tool",
                "content": self.content,
                "tool_call_id": self.tool_call_id or "",
            }
        # user / system
        msg = {"role": self.role, "content": self.content}
        if self.name:
            msg["name"] = self.name
        return msg

    @classmethod
    def _from_row(cls, row) -> "Message":
        raw_tool_calls = row["tool_calls"]
        tool_calls: Optional[list[dict[str, Any]]] = None
        if raw_tool_calls is not None:
            tool_calls = (
                loads(raw_tool_calls)
                if isinstance(raw_tool_calls, (str, bytes))
                else raw_tool_calls
            )
        return cls(
            uid=row["uid"],
            channel_id=row["channel_id"],
            message_id=row["message_id"],
            role=row["role"],
            name=row["name"],
            content=row["content"] or "",
            tool_calls=tool_calls,
            tool_call_id=row["tool_call_id"],
        )

    @classmethod
    async def fetch_recent(
        cls, conn: Connection, channel_id: int, limit: int
    ) -> list["Message"]:
        """取得最近 limit 則訊息,並以時間(uid)升冪排序回傳。"""
        rows = await conn.fetch(
            """
            SELECT * FROM (
                SELECT * FROM messages
                WHERE channel_id = $1
                ORDER BY uid DESC
                LIMIT $2
            ) sub
            ORDER BY uid ASC
            """,
            channel_id,
            limit,
        )
        return [cls._from_row(r) for r in rows]

    @classmethod
    async def fetch_oldest(
        cls, conn: Connection, channel_id: int, limit: int
    ) -> list["Message"]:
        """取得最舊的 limit 則訊息(升冪),供摘要使用。"""
        rows = await conn.fetch(
            """
            SELECT * FROM messages
            WHERE channel_id = $1
            ORDER BY uid ASC
            LIMIT $2
            """,
            channel_id,
            limit,
        )
        return [cls._from_row(r) for r in rows]

    @classmethod
    async def count(cls, conn: Connection, channel_id: int) -> int:
        result = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE channel_id = $1",
            channel_id,
        )
        return result or 0

    @classmethod
    async def delete_ids(cls, conn: Connection, uids: list[int]) -> None:
        if not uids:
            return
        await conn.execute(
            "DELETE FROM messages WHERE uid = ANY($1::bigint[])",
            uids,
        )
