from discord import (
    ApplicationContext,
    Cog,
    Colour,
    Embed,
    Member,
    Option,
    Permissions,
    SlashCommandGroup,
)

from datetime import datetime, timezone
from typing import Optional

from db import get_db
from game import roster as roster_game
from model.roster import Roster
from model.session import Session
from type.bot import TRPGBot


def _parse_date(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def _ensure_admin(ctx: ApplicationContext) -> bool:
    """檢查使用情境與管理員權限,未通過時直接回覆並回傳 False。"""
    if ctx.guild is None or ctx.channel is None:
        await ctx.respond("此指令只能在伺服器頻道中使用。", ephemeral=True)
        return False

    author = ctx.author
    if not isinstance(author, Member) or not author.guild_permissions.administrator:
        await ctx.respond("只有管理員可以使用此指令。", ephemeral=True)
        return False

    return True


class RosterAdminCog(Cog):
    roster_admin = SlashCommandGroup(
        "roster_admin",
        "(管理員) 管理晉級名單的公布時間",
        default_member_permissions=Permissions(administrator=True),
    )

    def __init__(self, bot: TRPGBot) -> None:
        self.bot = bot

    @roster_admin.command(
        name="list",
        description="(管理員) 列出本頻道所有晉級隊伍與其建議公布時間",
    )
    async def list_teams(self, ctx: ApplicationContext) -> None:
        if not await _ensure_admin(ctx):
            return

        channel_id: int = ctx.channel.id

        async with get_db() as conn:
            if not await Session.exists(conn, channel_id):
                await ctx.respond(
                    "本頻道尚未開始冒險,請先使用 /start。", ephemeral=True
                )
                return

            entries = await Roster.get_all_by_channel_id(conn, channel_id)

        today = datetime.now(timezone.utc).date()
        entries.sort(key=lambda e: e.suggested)

        embed = Embed(title="🛠️ 晉級名單管理", colour=Colour.blurple())
        if not entries:
            embed.description = "本頻道的名單為空。"
        else:
            lines = []
            for entry in entries:
                date_text = entry.suggested.strftime("%Y-%m-%d")
                if entry.revealed:
                    state = "✅ 已公布"
                elif roster_game.is_due(entry, today):
                    state = "🟡 可公布"
                else:
                    state = "🔒 未到期"
                lines.append(f"`{date_text}` **{entry.name}** — {state}")
            embed.description = "\n".join(lines)

        await ctx.respond(embed=embed, ephemeral=True)

    @roster_admin.command(
        name="set",
        description="(管理員) 調整指定隊伍的建議公布日期",
    )
    async def set_reveal(
        self,
        ctx: ApplicationContext,
        team: Option(str, "隊伍名稱(需與名單完全相符)"),  # type: ignore[valid-type]
        date: Option(str, "建議公布日期,格式 YYYY-MM-DD"),  # type: ignore[valid-type]
    ) -> None:
        if not await _ensure_admin(ctx):
            return

        channel_id: int = ctx.channel.id

        suggested = _parse_date(date)
        if suggested is None:
            await ctx.respond(
                "日期格式錯誤,請使用 `YYYY-MM-DD`(例如 2026-06-20)。", ephemeral=True
            )
            return

        async with get_db() as conn:
            if not await Session.exists(conn, channel_id):
                await ctx.respond(
                    "本頻道尚未開始冒險,請先使用 /start。", ephemeral=True
                )
                return

            updated = await Roster.set_suggested(
                conn, channel_id, team.strip(), suggested
            )

        if updated is None:
            await ctx.respond(
                f"名單中找不到隊伍「{team}」,請確認名稱是否完全相符。", ephemeral=True
            )
            return

        note = "(此隊伍已公布,調整公布日期不影響已公布狀態)" if updated.revealed else ""
        await ctx.respond(
            f"已將「{updated.name}」的建議公布日期調整為 "
            f"{updated.suggested.strftime('%Y-%m-%d')}。{note}",
            ephemeral=True,
        )


def setup(bot: TRPGBot) -> None:
    bot.add_cog(RosterAdminCog(bot))
