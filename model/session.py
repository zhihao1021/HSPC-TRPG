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
    seek_sid: SnowflakeId = SnowflakeId(0)
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
                channel_id,
                seek_sid,
                summary,
                token_usage,
                kind,
                chargen_owner_id,
                chargen_channel_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (channel_id) DO UPDATE SET
                updated_at = NOW(),
                summary = EXCLUDED.summary,
                token_usage = EXCLUDED.token_usage,
                kind = EXCLUDED.kind,
                chargen_owner_id = EXCLUDED.chargen_owner_id,
                chargen_channel_id = EXCLUDED.chargen_channel_id
            """,
            int(self.channel_id),
            int(self.seek_sid),
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

        return cls.model_validate(dict(row)) if row else None

    @classmethod
    async def get_all(cls, conn: Connection) -> list[Self]:
        rows = await conn.fetch("SELECT * FROM sessions")
        return [cls.model_validate(dict(row)) for row in rows]

    @classmethod
    async def exists(cls, conn: Connection, channel_id: UidType) -> bool:
        return bool(await conn.fetchval(
            "SELECT 1 FROM sessions WHERE channel_id = $1",
            int(channel_id),
        ))

    @classmethod
    async def create(
        cls,
        conn: Connection,
        channel_id: UidType,
        kind: SessionKind = "game",
        *,
        chargen_owner_id: Optional[UidType] = None,
        chargen_channel_id: Optional[UidType] = None,
    ) -> Self:
        now = datetime.now(timezone.utc)
        session = cls(
            channel_id=SnowflakeId(int(channel_id)),
            created_at=now,
            updated_at=now,
            kind=kind,
            chargen_owner_id=(
                SnowflakeId(int(chargen_owner_id))
                if chargen_owner_id is not None else None
            ),
            chargen_channel_id=(
                SnowflakeId(int(chargen_channel_id))
                if chargen_channel_id is not None else None
            ),
        )
        await session.save(conn)
        return session

    @classmethod
    async def create_chargen(
        cls,
        conn: Connection,
        channel_id: UidType,
        chargen_owner_id: UidType,
        chargen_channel_id: UidType,
    ) -> Self:
        """建立私訊創角用的臨時 session(channel_id 為玩家 DM 頻道)。"""
        return await cls.create(
            conn,
            channel_id,
            kind="chargen",
            chargen_owner_id=chargen_owner_id,
            chargen_channel_id=chargen_channel_id,
        )

    @classmethod
    async def find_chargen(
        cls,
        conn: Connection,
        chargen_owner_id: UidType,
        chargen_channel_id: UidType,
    ) -> Optional[Self]:
        """尋找某玩家對某遊戲頻道進行中的創角 session。"""
        row = await conn.fetchrow(
            """
            SELECT * FROM sessions
            WHERE kind = 'chargen'
                AND chargen_owner_id = $1
                AND chargen_channel_id = $2
            """,
            int(chargen_owner_id),
            int(chargen_channel_id),
        )
        return cls.model_validate(dict(row)) if row else None

    @classmethod
    async def delete(cls, conn: Connection, channel_id: UidType) -> None:
        await conn.execute(
            "DELETE FROM sessions WHERE channel_id = $1",
            int(channel_id),
        )
