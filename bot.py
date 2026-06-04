from discord import Bot, Intents, Message as DiscordMessage

from datetime import datetime

import config
from db import get_db
from model.session import Session
from session.manager import SessionManager

intents = Intents.default()
intents.message_content = True

bot = Bot(intents=intents)


_sessions: dict[int, SessionManager] = {}


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user}")

    session_keys = set()
    async with get_db() as conn:
        sessions = await Session.get_all(conn=conn)

        for session_meta in sessions:
            session_key = session_meta.channel_id
            session_keys.add(session_key)
            if session_key in _sessions:
                continue

            manager = SessionManager(
                data=session_meta,
            )
            await manager.startup()

    print(f"已載入 {len(_sessions)} 個進行中的 session")


@bot.event
async def on_message(message: DiscordMessage) -> None:
    if message.author.bot:
        return

    manager = _sessions.get(message.channel.id)
    if manager is None:
        return

    manager.enqueue(message)


async def start():
    await bot.start(config.discord_token())
