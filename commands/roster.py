from discord import (
    ApplicationContext,
    Cog,
    Colour,
    Embed,
    slash_command,
)

from db import get_db
from model.roster import Roster
from model.session import Session
from type.bot import TRPGBot


class RosterCog(Cog):
    def __init__(self, bot: TRPGBot) -> None:
        self.bot = bot

    @slash_command(
        name="roster",
        description="查看目前已公布的晉級隊伍名單",
    )
    async def roster(self, ctx: ApplicationContext) -> None:
        if ctx.guild is None or ctx.channel is None:
            await ctx.respond("此指令只能在伺服器頻道中使用。", ephemeral=True)
            return

        channel_id: int = ctx.channel.id

        async with get_db() as conn:
            if not await Session.exists(conn, channel_id):
                await ctx.respond(
                    "本頻道尚未開始冒險,請管理員先使用 /start。", ephemeral=True
                )
                return

            revealed = await Roster.get_all_by_channel_id(
                conn, channel_id, revealed=True
            )
            total = await Roster.count_by_channel_id(conn, channel_id)

        revealed.sort(key=lambda e: e.revealed_at or e.suggested)

        embed = Embed(title="🏆 已公布的晉級隊伍", colour=Colour.gold())
        embed.add_field(
            name="進度",
            value=f"已公布 {len(revealed)} / {total} 組",
            inline=False,
        )

        if not revealed:
            embed.description = "目前尚無任何已公布的隊伍,繼續冒險來解鎖吧!"
        else:
            lines = []
            for entry in revealed:
                when = entry.revealed_at or entry.suggested
                lines.append(f"**{entry.name}** — 公布於 {when.strftime('%Y-%m-%d')}")
            embed.add_field(name="名單", value="\n".join(lines), inline=False)

        await ctx.respond(embed=embed)


def setup(bot: TRPGBot) -> None:
    bot.add_cog(RosterCog(bot))
