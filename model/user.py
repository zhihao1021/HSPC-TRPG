from asyncpg import Connection
from orjson import dumps
from pydantic import BaseModel
from pydantic_snowflake import SnowflakeId

from typing import Optional, Self

from type.uid import UidType


class UserSkill(BaseModel):
    name: str
    description: Optional[str] = None
    level: Optional[int] = None


class UserInventoryItem(BaseModel):
    name: str
    description: Optional[str] = None
    quantity: Optional[int] = None


class User(BaseModel):
    uid: SnowflakeId
    channel_id: SnowflakeId
    username: str
    display_name: str
    summary: str = ""
    level: int = 1
    hp: int = 10
    max_hp: int = 10
    state_str: int = 10
    state_dex: int = 10
    state_con: int = 10
    state_int: int = 10
    state_wis: int = 10
    state_cha: int = 10
    skills: list[UserSkill] = []
    inventory: list[UserInventoryItem] = []

    async def save(self, conn: Connection) -> None:
        await conn.execute(
            """
            INSERT INTO users (
                uid, channel_id, username, display_name, summary, level, hp, max_hp,
                state_str, state_dex, state_con, state_int, state_wis, state_cha,
                skills, inventory
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            ON CONFLICT (uid) DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                username = EXCLUDED.username,
                display_name = EXCLUDED.display_name,
                summary = EXCLUDED.summary,
                level = EXCLUDED.level,
                hp = EXCLUDED.hp,
                max_hp = EXCLUDED.max_hp,
                state_str = EXCLUDED.state_str,
                state_dex = EXCLUDED.state_dex,
                state_con = EXCLUDED.state_con,
                state_int = EXCLUDED.state_int,
                state_wis = EXCLUDED.state_wis,
                state_cha = EXCLUDED.state_cha,
                skills = EXCLUDED.skills,
                inventory = EXCLUDED.inventory
            """,
            int(self.uid),
            int(self.channel_id),
            self.username,
            self.display_name,
            self.summary,
            self.level,
            self.hp,
            self.max_hp,
            self.state_str,
            self.state_dex,
            self.state_con,
            self.state_int,
            self.state_wis,
            self.state_cha,
            dumps([s.model_dump() for s in self.skills]).decode("utf-8"),
            dumps([i.model_dump() for i in self.inventory]).decode("utf-8"),
        )

    @classmethod
    async def get_by_uid_and_channel_id(
        cls,
        conn: Connection,
        uid: UidType,
        channel_id: UidType,
    ) -> Optional[Self]:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE uid = $1 AND channel_id = $2",
            int(uid),
            int(channel_id),
        )

        return cls.model_validate(dict(row)) if row else None

    @classmethod
    async def get_all_by_channel_id(cls, conn: Connection, channel_id: UidType) -> list[Self]:
        rows = await conn.fetch(
            "SELECT * FROM users WHERE channel_id = $1",
            int(channel_id),
        )

        return [cls.model_validate(dict(row)) for row in rows]
