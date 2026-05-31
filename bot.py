from discord import (
    Bot,
    Intents,
    Interaction,
    Message,
)

from os import getenv

intents = Intents.default()
intents.message_content = True

bot = Bot(intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


@bot.event
async def on_message(message: Message):
    pass


async def start():
    token = getenv("DISCORD_BOT_TOKEN", None)
    if token is None:
        raise ValueError(
            "DISCORD_BOT_TOKEN is not set in environment variables.")

    await bot.start(token=token)
