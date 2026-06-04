from asyncpg import create_pool, Pool, Connection

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import config

_pool: Optional[Pool] = None  # pylint: disable=invalid-name


async def create_tables(conn: Connection) -> None:
    # Create tables if they do not exist
    with open("sql/create_tables.sql", "r", encoding="utf-8") as f:
        sql_commands = f.read()
        await conn.execute(sql_commands)


@asynccontextmanager
async def init_db() -> AsyncGenerator[Pool, None]:
    global _pool  # pylint: disable=global-statement
    if _pool:
        raise RuntimeError("Database pool is already initialized.")
    dsn = config.postgres_dsn()
    min_size = config.postgres_pool_min()
    max_size = config.postgres_pool_max()

    pool = await create_pool(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
    )

    try:
        _pool = pool
        async with pool.acquire() as conn:
            await create_tables(conn)  # type: ignore
        yield pool
    finally:
        await pool.close()
        _pool = None


@asynccontextmanager
async def get_db(transaction: bool = False) -> AsyncGenerator[Connection, None]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized.")

    async with _pool.acquire() as conn:
        if transaction:
            async with conn.transaction():
                yield conn  # type: ignore
        else:
            yield conn  # type: ignore
