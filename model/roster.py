from asyncpg import Connection
from pydantic import BaseModel
from pydantic_snowflake import SnowflakeId

from datetime import datetime
from typing import Iterable, Optional, Self

from type.uid import UidType


class Roster(BaseModel):
    channel_id: SnowflakeId
    name: str
    suggested: datetime
    revealed: bool = False
    revealed_at: Optional[datetime] = None

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

        return [cls.model_validate(dict(row)) for row in rows]

    @classmethod
    async def seed(
        cls,
        conn: Connection,
        channel_id: UidType,
        teams: Iterable[tuple[str, datetime]],
    ) -> int:
        """以 (name, suggested) 種入名單;重複的 (channel_id, name) 略過。回傳種入筆數。"""
        rows = [
            (int(channel_id), name, suggested)
            for name, suggested in teams
        ]
        await conn.executemany(
            """
            INSERT INTO roster (channel_id, name, suggested)
            VALUES ($1, $2, $3)
            ON CONFLICT (channel_id, name) DO NOTHING
            """,
            rows,
        )
        return len(rows)

    @classmethod
    async def reveal(
        cls,
        conn: Connection,
        channel_id: UidType,
        name: str,
    ) -> Optional[Self]:
        """標記某隊伍為已公布並回傳;若查無該隊伍則回傳 None。"""
        row = await conn.fetchrow(
            """
            UPDATE roster
            SET revealed = TRUE, revealed_at = NOW()
            WHERE channel_id = $1 AND name = $2
            RETURNING *
            """,
            int(channel_id),
            name,
        )
        return cls.model_validate(dict(row)) if row else None

    @classmethod
    async def set_suggested(
        cls,
        conn: Connection,
        channel_id: UidType,
        name: str,
        suggested: datetime,
    ) -> Optional[Self]:
        """調整指定隊伍的建議公布時間並回傳更新後資料;查無該隊伍則回傳 None。"""
        row = await conn.fetchrow(
            """
            UPDATE roster
            SET suggested = $3
            WHERE channel_id = $1 AND name = $2
            RETURNING *
            """,
            int(channel_id),
            name,
            suggested,
        )
        return cls.model_validate(dict(row)) if row else None

    @classmethod
    async def count_remaining(cls, conn: Connection, channel_id: UidType) -> int:
        count_val = await conn.fetchval(
            "SELECT COUNT(*) FROM roster WHERE channel_id = $1 AND NOT revealed",
            int(channel_id),
        )
        return count_val or 0

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
