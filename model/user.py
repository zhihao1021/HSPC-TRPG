from asyncpg import Connection
from pydantic import BaseModel
from pydantic_snowflake import SnowflakeId

class User(BaseModel):
    uid: SnowflakeId
    channel_id: SnowflakeId
    username: str
    display_name: str
    summary: str = ""
    state_str: int = 0
    state_dex: int = 0
    state_con: int = 0
    state_int: int = 0
    state_wis: int = 0
    state_cha: int = 0

    async def insert(self, conn: Connection) -> None:
        await conn.execute(
            """
            INSERT INTO users (
                uid,
                channel_id,
                username,
                display_name,
                summary,
                state_str,
                state_dex,
                state_con,
                state_int,
                state_wis,
                state_cha
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            self.uid,
            self.channel_id,
            self.username,
            self.display_name,
            self.summary,
            self.state_str,
            self.state_dex,
            self.state_con,
            self.state_int,
            self.state_wis,
            self.state_cha,
        )
