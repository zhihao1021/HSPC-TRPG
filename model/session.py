from asyncpg import Connection
from pydantic import BaseModel
from pydantic_snowflake import SnowflakeId

from datetime import datetime, timezone
from typing import Optional, Self

from type.chat import SessionKind
from type.uid import UidType


class Session(BaseModel):
    channel_id: SnowflakeId
    created_at: datetime
    updated_at: datetime
    summary: str = ""
    token_usage: int = 0
    kind: SessionKind = "game"
    chargen_owner_id: Optional[SnowflakeId] = None
    chargen_channel_id: Optional[SnowflakeId] = None

    async def save(self, conn: Connection) -> None:
        now = datetime.now(timezone.utc)
        self.updated_at = now

        await conn.execute(
            """
            INSERT INTO sessions (
                channel_id, summary, token_usage, kind, chargen_owner_id, chargen_channel_id
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (channel_id) DO UPDATE SET
                updated_at = NOW(),
                summary = EXCLUDED.summary,
                token_usage = EXCLUDED.token_usage,
                kind = EXCLUDED.kind,
                chargen_owner_id = EXCLUDED.chargen_owner_id,
                chargen_channel_id = EXCLUDED.chargen_channel_id
            """,
            int(self.channel_id),
            self.summary,
            self.token_usage,
            self.kind,
            int(self.chargen_owner_id) if self.chargen_owner_id is not None else None,
            int(self.chargen_channel_id) if self.chargen_channel_id is not None else None,
        )

    @classmethod
    async def get_by_channel_id(cls, conn: Connection, channel_id: UidType) -> Optional[Self]:
        row = await conn.fetchrow(
            "SELECT * FROM sessions WHERE channel_id = $1",
            int(channel_id),
        )

        return cls.model_validate(row) if row else None

    @classmethod
    async def get_all(cls, conn: Connection) -> list[Self]:
        rows = await conn.fetch("SELECT * FROM sessions")
        return [cls.model_validate(row) for row in rows]
