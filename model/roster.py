from asyncpg import Connection
from pydantic import BaseModel
from pydantic_snowflake import SnowflakeId

from datetime import date, datetime
from typing import Optional


class RosterEntry(BaseModel):
    channel_id: SnowflakeId
    idx: int
    name: str
    suggested_date: date
    revealed: bool = False
    revealed_at: Optional[datetime] = None

    @classmethod
    def _from_row(cls, row) -> "RosterEntry":
        return cls(**dict(row))

    @classmethod
    async def seed(
        cls,
        conn: Connection,
        channel_id: int,
        teams: list[tuple[int, str, date]],
    ) -> None:
        """以 (idx, name, suggested_date) 種入名單;重複 idx 則略過。"""
        await conn.executemany(
            """
            INSERT INTO roster (channel_id, idx, name, suggested_date)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (channel_id, idx) DO NOTHING
            """,
            [(channel_id, idx, name, d) for idx, name, d in teams],
        )

    @classmethod
    async def fetch_all(
        cls, conn: Connection, channel_id: int
    ) -> list["RosterEntry"]:
        rows = await conn.fetch(
            "SELECT * FROM roster WHERE channel_id = $1 ORDER BY idx ASC",
            channel_id,
        )
        return [cls._from_row(r) for r in rows]

    @classmethod
    async def reveal(
        cls, conn: Connection, channel_id: int, name: str
    ) -> Optional["RosterEntry"]:
        """標記某隊伍為已公布並回傳;若查無該隊伍則回傳 None。"""
        row = await conn.fetchrow(
            """
            UPDATE roster
            SET revealed = TRUE, revealed_at = NOW()
            WHERE channel_id = $1 AND name = $2
            RETURNING *
            """,
            channel_id,
            name,
        )
        if row is None:
            return None
        return cls._from_row(row)

    @classmethod
    async def count_remaining(cls, conn: Connection, channel_id: int) -> int:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM roster WHERE channel_id = $1 AND NOT revealed",
            channel_id,
        )
