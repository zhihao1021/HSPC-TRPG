from asyncpg import Connection
from pydantic import BaseModel
from pydantic_snowflake import SnowflakeId

from datetime import datetime, timezone
from typing import Literal, Optional

SessionKind = Literal["game", "chargen"]


class Session(BaseModel):
    channel_id: SnowflakeId
    created_at: datetime
    updated_at: datetime
    summary: str = ""
    last_token_usage: int = 0
    kind: SessionKind = "game"
    owner_user_id: Optional[SnowflakeId] = None
    game_channel_id: Optional[SnowflakeId] = None

    async def insert(self, conn: Connection) -> None:
        await conn.execute(
            """
            INSERT INTO sessions (
                channel_id, created_at, updated_at, summary, last_token_usage,
                kind, owner_user_id, game_channel_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (channel_id) DO NOTHING
            """,
            int(self.channel_id),
            self.created_at,
            self.updated_at,
            self.summary,
            self.last_token_usage,
            self.kind,
            int(self.owner_user_id) if self.owner_user_id is not None else None,
            int(self.game_channel_id) if self.game_channel_id is not None else None,
        )

    @classmethod
    async def get(cls, conn: Connection, channel_id: int) -> Optional["Session"]:
        row = await conn.fetchrow(
            "SELECT * FROM sessions WHERE channel_id = $1", channel_id
        )
        if row is None:
            return None
        return cls(**dict(row))

    @classmethod
    async def exists(cls, conn: Connection, channel_id: int) -> bool:
        return bool(
            await conn.fetchval(
                "SELECT 1 FROM sessions WHERE channel_id = $1", channel_id
            )
        )

    @classmethod
    async def create(cls, conn: Connection, channel_id: int) -> "Session":
        now = datetime.now(timezone.utc)
        session = cls(
            channel_id=SnowflakeId(channel_id), created_at=now, updated_at=now
        )
        await session.insert(conn)
        return session

    @classmethod
    async def create_chargen(
        cls,
        conn: Connection,
        channel_id: int,
        owner_user_id: int,
        game_channel_id: int,
    ) -> "Session":
        """建立私訊創角用的臨時 session(channel_id 為玩家 DM 頻道)。"""
        now = datetime.now(timezone.utc)
        session = cls(
            channel_id=SnowflakeId(channel_id),
            created_at=now,
            updated_at=now,
            kind="chargen",
            owner_user_id=SnowflakeId(owner_user_id),
            game_channel_id=SnowflakeId(game_channel_id),
        )
        await session.insert(conn)
        return session

    @classmethod
    async def find_chargen(
        cls, conn: Connection, owner_user_id: int, game_channel_id: int
    ) -> Optional["Session"]:
        row = await conn.fetchrow(
            """
            SELECT * FROM sessions
            WHERE kind = 'chargen'
              AND owner_user_id = $1
              AND game_channel_id = $2
            """,
            owner_user_id,
            game_channel_id,
        )
        if row is None:
            return None
        return cls(**dict(row))

    @classmethod
    async def delete(cls, conn: Connection, channel_id: int) -> None:
        await conn.execute("DELETE FROM sessions WHERE channel_id = $1", channel_id)

    @classmethod
    async def update_summary(
        cls, conn: Connection, channel_id: int, summary: str
    ) -> None:
        await conn.execute(
            """
            UPDATE sessions
            SET summary = $2, updated_at = NOW()
            WHERE channel_id = $1
            """,
            channel_id,
            summary,
        )

    @classmethod
    async def update_token_usage(
        cls, conn: Connection, channel_id: int, token_usage: int
    ) -> None:
        await conn.execute(
            """
            UPDATE sessions
            SET last_token_usage = $2, updated_at = NOW()
            WHERE channel_id = $1
            """,
            channel_id,
            token_usage,
        )
