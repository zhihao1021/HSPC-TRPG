from discord import (
    ApplicationContext,
    Cog,
    Colour,
    Embed,
    slash_command,
)

from typing import Optional

from db import get_db
from model.roster import Roster
from model.session import Session
from model.user import User
from type.bot import TRPGBot


class StatusCog(Cog):
    def __init__(self, bot: TRPGBot) -> None:
        self.bot = bot

    @slash_command(
        name="status",
        description="查看你的角色與目前冒險進度",
    )
    async def status(self, ctx: ApplicationContext) -> None:
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

            user: Optional[User] = await User.get_by_uid_and_channel_id(
                conn, ctx.author.id, channel_id
            )
            total = await Roster.count_by_channel_id(conn, channel_id)
            revealed = await Roster.count_by_channel_id(conn, channel_id, revealed=True)

        embed = Embed(title="📜 冒險狀態", colour=Colour.blurple())
        embed.add_field(
            name="晉級名單進度",
            value=f"已公布 {revealed} / {total} 組",
            inline=False,
        )

        if user is None:
            embed.add_field(
                name="你的角色",
                value="尚未建立。直接在頻道中行動,我會引導你建立角色!",
                inline=False,
            )
        else:
            skills = "、".join(s.name for s in user.skills) or "無"
            inventory = "、".join(i.name for i in user.inventory) or "無"
            embed.set_author(
                name=user.display_name,
                icon_url=ctx.author.display_avatar.url
            )
            embed.add_field(
                name="狀態值",
                value=(
                    f"等級 `{user.level}`\n"
                    f"HP `{user.hp}/{user.max_hp}`\n"
                    f"STR `{user.state_str}`\n"
                    f"DEX `{user.state_dex}`\n"
                    f"CON `{user.state_con}`\n"
                    f"INT `{user.state_int}`\n"
                    f"WIS `{user.state_wis}`\n"
                    f"CHA `{user.state_cha}`"
                ),
                inline=False,
            )
            embed.add_field(name="技能", value=skills, inline=False,)
            embed.add_field(name="裝備", value=inventory, inline=False,)
            embed.add_field(
                name="角色摘要",
                value=user.summary or "無",
                inline=False,
            )
        await ctx.respond(embed=embed)


def setup(bot: TRPGBot) -> None:
    bot.add_cog(StatusCog(bot))
