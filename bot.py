from discord import Intents, Message as DiscordMessage

from logging import getLogger

from db import get_db
from model.session import Session
from session.manager import SessionManager
from type.bot import TRPGBot

logger = getLogger(__name__)

EXTENSIONS = [
    "commands.start",
    "commands.status",
    "commands.roster",
    "commands.roster_admin",
    "commands.recalc_tokens",
    "commands.session_status",
]

intents = Intents.default()
intents.message_content = True

bot = TRPGBot(intents=intents)


@bot.event
async def on_ready() -> None:
    logger.info("Logged in as %s", bot.user)

    async with get_db() as conn:
        sessions = await Session.get_all(conn=conn)

    loaded = 0
    for meta in sessions:
        key = int(meta.channel_id)
        if key in bot.sessions:
            continue
        manager = SessionManager(meta, host=bot.host)
        await manager.startup()
        bot.sessions[key] = manager
        loaded += 1

    logger.info("已載入 %d 個進行中的 session", loaded)


@bot.event
async def on_message(message: DiscordMessage) -> None:
    if message.author.bot:
        return

    manager = bot.sessions.get(message.channel.id)
    if manager is None:
        return

    await manager.submit(message)


for _extension in EXTENSIONS:
    bot.load_extension(_extension)
