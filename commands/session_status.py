from aiohttp import ClientSession, ClientTimeout
from discord import ApplicationContext, Cog, Colour, Embed, slash_command

from typing import cast

from config import CONFIG
from type.bot import TRPGBot

_BALANCE_TIMEOUT = ClientTimeout(total=10)


async def _get_balance() -> str:
    if "api.deepseek.com" not in CONFIG.llm.base_url:
        return "N/A"

    try:
        async with ClientSession(
            base_url=CONFIG.llm.base_url,
            headers={"Authorization": f"Bearer {CONFIG.llm.api_key}"},
        ) as session:
            async with session.get(
                "/user/balance", timeout=_BALANCE_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    return "Error"
                data: dict = await resp.json()
    except Exception:  # noqa: BLE001 - 網路/解析錯誤都視為取得失敗
        return "Error"

    balance_infos = cast(
        list[dict[str, str]],
        data.get("balance_infos", [])
    )

    for info in balance_infos:
        if info.get("currency") != "CNY":
            continue
        return f"{info.get('total_balance', 'N/A')} CNY"
    return "N/A"


class SessionStatusCog(Cog):
    def __init__(self, bot: TRPGBot) -> None:
        self.bot = bot

    @slash_command(
        name="session_status",
        description="查看系統狀態:API 餘額與本頻道 Token 用量",
    )
    async def session_status(self, ctx: ApplicationContext) -> None:
        await ctx.defer(ephemeral=True)

        balance = await _get_balance()

        manager = self.bot.sessions.get(ctx.channel.id) if ctx.channel else None
        if manager is None:
            token_text = "本頻道沒有進行中的 session"
        else:
            token_text = f"{manager.token_usage} tokens"

        embed = Embed(title="🖥️ 系統狀態", colour=Colour.blurple())
        embed.add_field(name="API 餘額", value=balance, inline=False)
        embed.add_field(name="本頻道 Token 用量", value=token_text, inline=False)

        await ctx.respond(embed=embed, ephemeral=True)


def setup(bot: TRPGBot) -> None:
    bot.add_cog(SessionStatusCog(bot))
