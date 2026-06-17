from discord import ApplicationContext, Cog, Member, slash_command

from type.bot import TRPGBot


class RecalcTokensCog(Cog):
    def __init__(self, bot: TRPGBot) -> None:
        self.bot = bot

    @slash_command(
        name="recalc_tokens",
        description="(管理員) 重新計算本頻道的 Token 用量",
    )
    async def recalc_tokens(self, ctx: ApplicationContext) -> None:
        if ctx.guild is None or ctx.channel is None:
            await ctx.respond("此指令只能在伺服器頻道中使用。", ephemeral=True)
            return

        author = ctx.author
        if not isinstance(author, Member) or not author.guild_permissions.administrator:
            await ctx.respond("只有管理員可以使用此指令。", ephemeral=True)
            return

        manager = self.bot.sessions.get(ctx.channel.id)
        if manager is None:
            await ctx.respond("本頻道沒有進行中的 session。", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)
        before = manager.token_usage
        after = await manager.recalculate_tokens()

        await ctx.respond(
            f"已重新計算本頻道的 Token 用量:{before} → {after}",
            ephemeral=True,
        )


def setup(bot: TRPGBot) -> None:
    bot.add_cog(RecalcTokensCog(bot))
