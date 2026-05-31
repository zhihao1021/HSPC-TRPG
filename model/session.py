from asyncpg import Connection
from pydantic import BaseModel
from pydantic_snowflake import SnowflakeId

from datetime import datetime


class Session(BaseModel):
    channel_id: SnowflakeId
    created_at: datetime
    updated_at: datetime
    summary: str = ""
    last_token_usage: int = 0

    async def insert(self, conn: Connection) -> None:
        await conn.execute(
            """
            INSERT INTO sessions (
                channel_id,
                created_at,
                updated_at,
                summary,
                last_token_usage
            )
            VALUES ($1, $2, $3, $4, $5)
            """,
            self.channel_id,
            self.created_at,
            self.updated_at,
            self.summary,
            self.last_token_usage,
        )
