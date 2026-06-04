from asyncpg import Connection
from pydantic import BaseModel
from pydantic_snowflake import SnowflakeId

from datetime import datetime
from typing import Optional, Self

from type.uid import UidType


class Roster(BaseModel):
    channel_id: SnowflakeId
    name: str
    suggested: datetime
    revealed: bool
    revealed_at: datetime

    async def save(self, conn: Connection) -> None:
        await conn.execute(
            """
            INSERT INTO roster (channel_id, name, suggested, revealed, revealed_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (channel_id, name) DO UPDATE SET
                suggested = EXCLUDED.suggested,
                revealed = EXCLUDED.revealed,
                revealed_at = EXCLUDED.revealed_at
            """,
            int(self.channel_id),
            self.name,
            self.suggested,
            self.revealed,
            self.revealed_at,
        )

    @classmethod
    async def get_all_by_channel_id(
        cls,
        conn: Connection,
        channel_id: UidType,
        *,
        revealed: Optional[bool] = None,
    ) -> list[Self]:
        if revealed is not None:
            rows = await conn.fetch(
                "SELECT * FROM roster WHERE channel_id = $1 AND revealed = $2 ORDER BY suggested ASC",
                int(channel_id),
                revealed,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM roster WHERE channel_id = $1 ORDER BY suggested ASC",
                int(channel_id),
            )

        return [cls.model_validate(row) for row in rows]

    @classmethod
    async def count_by_channel_id(
        cls,
        conn: Connection,
        channel_id: UidType,
        *,
        revealed: Optional[bool] = None,
    ) -> int:
        if revealed is not None:
            count_val = await conn.fetchval(
                "SELECT COUNT(*) FROM roster WHERE channel_id = $1 AND revealed = $2",
                int(channel_id),
                revealed,
            )
        else:
            count_val = await conn.fetchval(
                "SELECT COUNT(*) FROM roster WHERE channel_id = $1",
                int(channel_id),
            )

        return count_val or 0
