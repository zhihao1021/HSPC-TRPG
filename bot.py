from discord import Intents, Message as DiscordMessage

from config import CONFIG
from db import get_db
from model.session import Session
from session.manager import SessionManager
from type.bot import TRPGBot

# 一個 command 一個檔案,放在 commands/ 套件中,以 Cog extension 載入。
EXTENSIONS = [
    "commands.start",
    "commands.status",
    "commands.roster",
    "commands.roster_admin",
]

intents = Intents.default()
intents.message_content = True

bot = TRPGBot(intents=intents)


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user}")

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

    print(f"已載入 {loaded} 個進行中的 session")


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


async def start():
    await bot.start(CONFIG.discord.token)
