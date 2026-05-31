from asyncpg import Connection
from orjson import dumps, loads
from pydantic import BaseModel
from pydantic_snowflake import SnowflakeId

from typing import Any, Optional

# 可被工具更新的數值欄位(白名單,避免任意欄位被寫入)
NUMERIC_FIELDS = {
    "level",
    "hp",
    "max_hp",
    "state_str",
    "state_dex",
    "state_con",
    "state_int",
    "state_wis",
    "state_cha",
}
JSON_FIELDS = {"skills", "inventory"}
TEXT_FIELDS = {"summary", "display_name"}


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
    skills: list[Any] = []
    inventory: list[Any] = []

    async def insert(self, conn: Connection) -> None:
        await conn.execute(
            """
            INSERT INTO users (
                uid, channel_id, username, display_name, summary,
                level, hp, max_hp,
                state_str, state_dex, state_con,
                state_int, state_wis, state_cha,
                skills, inventory
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            ON CONFLICT (uid, channel_id) DO UPDATE SET
                username = EXCLUDED.username,
                display_name = EXCLUDED.display_name
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
            dumps(self.skills).decode("utf-8"),
            dumps(self.inventory).decode("utf-8"),
        )

    @classmethod
    def _from_row(cls, row) -> "User":
        data = dict(row)
        for f in JSON_FIELDS:
            v = data.get(f)
            if isinstance(v, (str, bytes)):
                data[f] = loads(v)
        return cls(**data)

    @classmethod
    async def get(
        cls, conn: Connection, uid: int, channel_id: int
    ) -> Optional["User"]:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE uid = $1 AND channel_id = $2",
            uid,
            channel_id,
        )
        if row is None:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_or_create(
        cls,
        conn: Connection,
        uid: int,
        channel_id: int,
        username: str,
        display_name: str,
    ) -> "User":
        user = await cls.get(conn, uid, channel_id)
        if user is not None:
            return user
        user = cls(
            uid=SnowflakeId(uid),
            channel_id=SnowflakeId(channel_id),
            username=username,
            display_name=display_name,
        )
        await user.insert(conn)
        return user

    @classmethod
    async def apply_updates(
        cls,
        conn: Connection,
        uid: int,
        channel_id: int,
        updates: dict[str, Any],
    ) -> Optional["User"]:
        """依白名單套用更新欄位。回傳更新後的 User,若不存在則回傳 None。"""
        sets: list[str] = []
        values: list[Any] = []
        idx = 3  # $1=uid, $2=channel_id
        for key, value in updates.items():
            if key in NUMERIC_FIELDS:
                sets.append(f"{key} = ${idx}")
                values.append(int(value))
            elif key in TEXT_FIELDS:
                sets.append(f"{key} = ${idx}")
                values.append(str(value))
            elif key in JSON_FIELDS:
                sets.append(f"{key} = ${idx}::jsonb")
                values.append(dumps(value).decode("utf-8"))
            else:
                continue
            idx += 1

        if not sets:
            return await cls.get(conn, uid, channel_id)

        row = await conn.fetchrow(
            f"""
            UPDATE users SET {", ".join(sets)}
            WHERE uid = $1 AND channel_id = $2
            RETURNING *
            """,
            uid,
            channel_id,
            *values,
        )
        if row is None:
            return None
        return cls._from_row(row)
