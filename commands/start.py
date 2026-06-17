from discord import ApplicationContext, Cog, Member, slash_command
from discord.abc import Messageable

from config import CONFIG
from db import get_db
from game import roster as roster_game
from model.roster import Roster
from model.session import Session
from session.manager import SessionManager
from type.bot import TRPGBot


class StartCog(Cog):
    def __init__(self, bot: TRPGBot) -> None:
        self.bot = bot

    @slash_command(
        name="start",
        description="(管理員) 在本頻道開始一場新的 TRPG 冒險",
    )
    async def start(self, ctx: ApplicationContext) -> None:
        if ctx.guild is None or ctx.channel is None:
            await ctx.respond("此指令只能在伺服器頻道中使用。", ephemeral=True)
            return

        author = ctx.author
        if not isinstance(author, Member) or not author.guild_permissions.administrator:
            await ctx.respond("只有管理員可以開始新的冒險。", ephemeral=True)
            return

        channel_id: int = ctx.channel.id
        await ctx.defer(ephemeral=True)

        # 先驗證名單檔案可正確載入,再建立 session,避免留下空 session
        try:
            teams = roster_game.load_roster_file()
        except FileNotFoundError:
            await ctx.respond(
                f"找不到晉級名單檔案({CONFIG.game.roster.file}),請確認設定。冒險尚未開始。",
                ephemeral=True,
            )
            return

        async with get_db(transaction=True) as conn:
            if await Session.exists(conn, channel_id):
                await ctx.respond("本頻道已經有進行中的冒險了。", ephemeral=True)
                return

            meta = await Session.create(conn, channel_id)
            await Roster.seed(
                conn,
                channel_id,
                [(t.name, t.reveal_date) for t in teams],
            )

        manager = SessionManager(meta, host=self.bot.host)
        await manager.startup()
        self.bot.sessions[channel_id] = manager

        channel = ctx.channel
        if isinstance(channel, Messageable):
            await manager.send_opening(channel)


def setup(bot: TRPGBot) -> None:
    bot.add_cog(StartCog(bot))
