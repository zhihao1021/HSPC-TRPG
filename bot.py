from asyncpg import Connection
from discord import (
    ApplicationContext,
    Bot,
    Colour,
    Embed,
    Intents,
    Member,
    Message as DiscordMessage,
)
from discord.abc import Messageable

from pydantic_snowflake import SnowflakeId

from asyncio import Queue, Task, create_task, wait_for
from datetime import datetime
from traceback import print_exc
from typing import Optional

import config
from db import get_db
from game import roster as roster_game
from llm.client import (
    GenerationResult,
    generate,
    generate_chargen,
    generate_chargen_opening,
    generate_opening,
)
from llm.tools import DiceEvent
from model.message import Message
from model.roster import RosterEntry
from model.session import Session
from model.user import User

intents = Intents.default()
intents.message_content = True

bot = Bot(intents=intents)

DISCORD_MSG_LIMIT = 2000
# worker 在閒置超過此秒數且佇列為空時自動結束,等下次訊息再重建
QUEUE_IDLE_TIMEOUT = 300.0
# 頻道內「隱藏提示」訊息的自動消失秒數
# (Discord 僅 interaction 支援真正的 ephemeral;一般訊息以自動刪除模擬)
HIDDEN_NOTICE_DELETE_AFTER = 30.0

# 每個頻道一條 Queue 與一個 worker,確保同頻道的多位玩家訊息依序處理
_queues: dict[int, "Queue[tuple[DiscordMessage, datetime]]"] = {}
_workers: dict[int, Task] = {}
# 有進行中 session 的頻道(記憶體快取,避免對無 session 頻道做 DB 查詢)
_active_channels: set[int] = set()


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user}")
    # 載入目前所有進行中的 session 頻道
    async with get_db() as conn:
        rows = await conn.fetch("SELECT channel_id FROM sessions")
    _active_channels.clear()
    _active_channels.update(int(r["channel_id"]) for r in rows)
    print(f"已載入 {len(_active_channels)} 個進行中的 session")


def _resolve_mentions(message: DiscordMessage) -> str:
    """將訊息中的 @提及 轉換為『@名稱(ID:數字)』,方便模型辨識玩家。"""
    content = message.content
    for member in message.mentions:
        label = f"@{member.display_name}(ID:{member.id})"
        content = content.replace(f"<@{member.id}>", label)
        content = content.replace(f"<@!{member.id}>", label)
    return content


def _build_player_block(message: DiscordMessage, now: datetime) -> str:
    resolved = _resolve_mentions(message)
    return (
        f"[時間] {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"[玩家] {message.author.display_name} (ID: {message.author.id})\n"
        f"[訊息]\n{resolved}"
    )


def _dice_embed(event: DiceEvent) -> Embed:
    mod = ""
    if event.modifier:
        mod = f" {'+' if event.modifier > 0 else '-'} {abs(event.modifier)}"
    formula = f"{event.count}d{event.sides}{mod}"
    detail = " + ".join(str(r) for r in event.rolls)

    # 依判定結果調整顏色
    colour = Colour.gold()
    if event.crit == "大成功" or event.success is True:
        colour = Colour.green()
    elif event.crit == "大失敗" or event.success is False:
        colour = Colour.red()

    embed = Embed(title="🎲 擲骰結果", colour=colour)
    if event.reason:
        embed.add_field(name="目的", value=event.reason, inline=False)
    embed.add_field(name="骰式", value=formula, inline=True)
    embed.add_field(name="擲出", value=f"[{detail}]{mod}", inline=True)
    embed.add_field(name="總計", value=str(event.total), inline=True)

    if event.dc is not None:
        embed.add_field(name="門檻 DC", value=str(event.dc), inline=True)

    # 判定(大成功/大失敗 優先,其次成功/失敗)
    verdict: Optional[str] = None
    if event.crit == "大成功":
        verdict = "🎯 大成功!"
    elif event.crit == "大失敗":
        verdict = "💥 大失敗!"
    elif event.success is True:
        verdict = "✅ 成功"
    elif event.success is False:
        verdict = "❌ 失敗"
    if verdict is not None:
        embed.add_field(name="判定", value=verdict, inline=True)

    if event.description:
        embed.add_field(name="說明", value=event.description, inline=False)
    return embed


def _chunk(text: str, limit: int = DISCORD_MSG_LIMIT) -> list[str]:
    """將過長文字依長度切分,盡量在換行處斷開。"""
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


async def _send_result(channel: Messageable, result: GenerationResult) -> None:
    # 擲骰 Embed(由工具觸發,確保準確)
    dice_embeds = [_dice_embed(e) for e in result.dice_events]

    content_chunks = _chunk(result.content)

    if not content_chunks:
        # 沒有文字內容時,至少把骰子結果送出
        if dice_embeds:
            await channel.send(embeds=dice_embeds[:10])
        return

    for idx, chunk in enumerate(content_chunks):
        # 把擲骰 Embed 附在第一則訊息
        if idx == 0 and dice_embeds:
            await channel.send(content=chunk, embeds=dice_embeds[:10])
        else:
            await channel.send(content=chunk)

    if config.show_reasoning() and result.reasoning:
        for chunk in _chunk(f"🧠 思考過程:\n{result.reasoning}"):
            await channel.send(content=chunk)


@bot.event
async def on_message(message: DiscordMessage) -> None:
    # 忽略機器人自身與其他 bot 的訊息
    if message.author.bot:
        return

    channel_id: int = message.channel.id
    # 只有進行中 session 的頻道才回應(含遊戲頻道與私訊創角頻道,快取判斷 O(1))
    if channel_id not in _active_channels:
        return

    now = datetime.now().astimezone()
    _enqueue(channel_id, message, now)


def _enqueue(channel_id: int, message: DiscordMessage, now: datetime) -> None:
    """把訊息放進該頻道的 Queue;若無 worker 則建立一個。"""
    queue = _queues.get(channel_id)
    if queue is None:
        queue = Queue()
        _queues[channel_id] = queue
        _workers[channel_id] = create_task(_channel_worker(channel_id, queue))
    queue.put_nowait((message, now))


async def _channel_worker(
    channel_id: int, queue: "Queue[tuple[DiscordMessage, datetime]]"
) -> None:
    """逐一處理同一頻道的訊息,確保多位玩家同時輸入時依序產生回應。"""
    try:
        while True:
            try:
                message, now = await wait_for(queue.get(), timeout=QUEUE_IDLE_TIMEOUT)
            except TimeoutError:
                # 閒置且佇列已空 -> 結束 worker(下次訊息會重建)
                if queue.empty():
                    return
                continue

            try:
                await _handle_message(message, now)
            except Exception:  # noqa: BLE001 - 單則訊息失敗不應終止 worker
                print_exc()
            finally:
                queue.task_done()
    finally:
        # 僅在這正是目前註冊的 queue 且已清空時才移除,避免誤刪新建的 worker
        if _queues.get(channel_id) is queue and queue.empty():
            _queues.pop(channel_id, None)
            _workers.pop(channel_id, None)


async def _handle_message(message: DiscordMessage, now: datetime) -> None:
    channel_id: int = message.channel.id

    async with get_db() as conn:
        session = await Session.get(conn, channel_id)
        # 防禦性再確認 session(可能在排隊期間被刪除)
        if session is None:
            _active_channels.discard(channel_id)
            return

        # 私訊創角 session
        if session.kind == "chargen":
            await _handle_chargen(conn, message, session, now)
            return

        # 一般遊戲 session:沒有角色的玩家先導向私訊創角,避免干擾遊戲
        user = await User.get(conn, message.author.id, channel_id)
        if user is None:
            await _begin_chargen(conn, message)
            return

        # 寫入玩家訊息(message_id 為 Discord Message ID)
        await Message(
            channel_id=SnowflakeId(channel_id),
            message_id=SnowflakeId(message.id),
            role="user",
            name=message.author.display_name,
            content=_build_player_block(message, now),
        ).insert(conn)

        async with message.channel.typing():
            result = await generate(conn, channel_id, now)

    await _send_result(message.channel, result)


async def _hidden_notice(message: DiscordMessage, text: str) -> None:
    """在頻道內以『自動消失的回覆』提示玩家(近似隱藏回覆,降低對遊戲的干擾)。"""
    try:
        await message.reply(
            text,
            delete_after=HIDDEN_NOTICE_DELETE_AFTER,
            mention_author=True,
        )
    except Exception:  # noqa: BLE001 - 訊息可能已被刪除等
        print_exc()


def _channel_link(message: DiscordMessage) -> str:
    """產生遊戲頻道的可點擊連結;有 guild 時用 jump URL,否則退回頻道 mention。"""
    channel_id = message.channel.id
    if message.guild is not None:
        return f"https://discord.com/channels/{message.guild.id}/{channel_id}"
    return f"<#{channel_id}>"


def _resolve_display_name(game_channel_id: int, user_id: int, fallback: str) -> str:
    """取得玩家在該遊戲頻道所屬群組中的顯示名稱。"""
    channel = bot.get_channel(game_channel_id)
    guild = getattr(channel, "guild", None)
    if guild is not None:
        member = guild.get_member(user_id)
        if member is not None:
            return member.display_name
    return fallback


async def _begin_chargen(conn: Connection, message: DiscordMessage) -> None:
    """為尚無角色的玩家開啟私訊創角流程;在遊戲頻道僅以隱藏回覆提示查看私訊。"""
    author = message.author
    game_channel_id: int = message.channel.id
    # 角色名稱固定使用玩家在群組中的顯示名稱
    owner = (author.id, str(author), author.display_name)

    # 若已在創角中,僅以頻道隱藏回覆提醒,不重複建立、不再私訊
    existing = await Session.find_chargen(conn, author.id, game_channel_id)
    if existing is not None:
        await _hidden_notice(
            message,
            "你正在進行角色創建,請查看與我的私訊完成創角後再回到頻道行動。",
        )
        return

    try:
        dm = await author.create_dm()
    except Exception:  # noqa: BLE001 - 玩家可能關閉私訊
        print_exc()
        await _hidden_notice(
            message,
            "你還沒有冒險角色,但我無法私訊你。請開啟此伺服器的私訊權限後再發言一次。",
        )
        return

    await Session.create_chargen(
        conn,
        channel_id=dm.id,
        owner_user_id=author.id,
        game_channel_id=game_channel_id,
    )
    _active_channels.add(dm.id)

    # 先在頻道以隱藏回覆提示玩家查看私訊(而非直接私訊作為首次接觸)
    await _hidden_notice(
        message,
        "你還沒有冒險角色!我已私訊你進行創角,請查看私訊並依指示完成,稍後再回到頻道行動。",
    )

    # 私訊開頭附上遊戲頻道連結,避免與其他頻道搞混
    try:
        await dm.send(
            f"👋 這裡是**角色創建**私訊。你正在為遊戲頻道 {_channel_link(message)} "
            "建立角色,完成後請回到該頻道開始冒險。"
        )
    except Exception:  # noqa: BLE001
        print_exc()

    now = datetime.now().astimezone()
    async with dm.typing():
        result = await generate_chargen_opening(
            conn, dm.id, now, game_channel_id=game_channel_id, owner=owner
        )
    await _send_result(dm, result)


async def _handle_chargen(
    conn: Connection, message: DiscordMessage, session: Session, now: datetime
) -> None:
    """處理私訊創角 session 的對話;完成創角後結束此臨時 session。"""
    # 僅該創角擁有者本人可推進此流程
    if session.owner_user_id is None or int(session.owner_user_id) != message.author.id:
        return
    if session.game_channel_id is None:
        return

    author = message.author
    dm_channel_id: int = message.channel.id
    game_channel_id: int = int(session.game_channel_id)
    # 角色名稱固定使用玩家在遊戲頻道所屬群組中的顯示名稱
    display_name = _resolve_display_name(game_channel_id, author.id, author.display_name)
    owner = (author.id, str(author), display_name)

    await Message(
        channel_id=SnowflakeId(dm_channel_id),
        message_id=SnowflakeId(message.id),
        role="user",
        name=author.display_name,
        content=_build_player_block(message, now),
    ).insert(conn)

    async with message.channel.typing():
        result = await generate_chargen(
            conn, dm_channel_id, now, game_channel_id=game_channel_id, owner=owner
        )

    await _send_result(message.channel, result)

    # 創角完成 -> 結束臨時 session
    if result.character_created:
        await Session.delete(conn, dm_channel_id)
        _active_channels.discard(dm_channel_id)
        await message.channel.send(
            "✅ 角色建立完成!請回到遊戲頻道,開始你的冒險吧。"
        )
        # 在遊戲頻道公開通知:該玩家已準備就緒加入冒險
        game_channel = bot.get_channel(game_channel_id)
        if isinstance(game_channel, Messageable):
            try:
                await game_channel.send(
                    f"🎉 <@{author.id}> 的角色「{display_name}」已準備就緒,"
                    "踏入了這場冒險!"
                )
            except Exception:  # noqa: BLE001 - 頻道可能不可用
                print_exc()


# ===================== Slash Commands =====================

@bot.slash_command(name="start", description="(管理員) 在本頻道開始一場新的 TRPG 冒險")
async def start_command(ctx: ApplicationContext) -> None:
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
            f"找不到晉級名單檔案({config.roster_file()}),"
            "請確認 ROSTER_FILE 設定。冒險尚未開始。",
            ephemeral=True,
        )
        return
    except Exception as exc:  # noqa: BLE001
        await ctx.respond(f"晉級名單檔案格式錯誤: {exc}", ephemeral=True)
        return

    async with get_db(transaction=True) as conn:
        if await Session.exists(conn, channel_id):
            await ctx.respond("本頻道已經有進行中的冒險了。", ephemeral=True)
            return

        await Session.create(conn, channel_id)
        rows = [(idx, t.name, t.reveal_date) for idx, t in enumerate(teams)]
        await RosterEntry.seed(conn, channel_id, rows)
        count = len(rows)

    # 標記為進行中,on_message 才會開始回應此頻道
    _active_channels.add(channel_id)

    await ctx.respond(
        f"✨ 冒險已在本頻道開始!已載入 {count} 組待解鎖的晉級隊伍。\n"
        "玩家現在可以直接在頻道中發言來行動,我會以 GM 的身份回應。",
        ephemeral=False,
    )

    # 由 GM 先輸出開場導言
    channel = ctx.channel
    if isinstance(channel, Messageable):
        now = datetime.now().astimezone()
        try:
            async with channel.typing():
                async with get_db() as conn:
                    result = await generate_opening(conn, channel_id, now)
            await _send_result(channel, result)
        except Exception:  # noqa: BLE001 - 導言失敗不應讓整個指令報錯
            print_exc()


@bot.slash_command(name="status", description="查看你的角色與目前冒險進度")
async def status_command(ctx: ApplicationContext) -> None:
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

        user: Optional[User] = await User.get(conn, ctx.author.id, channel_id)
        entries: list[RosterEntry] = await RosterEntry.fetch_all(conn, channel_id)

    revealed = sum(1 for e in entries if e.revealed)
    total = len(entries)

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
        embed.add_field(
            name=f"{user.display_name} 的角色",
            value=(
                f"等級 {user.level} ／ HP {user.hp}/{user.max_hp}\n"
                f"力量 {user.state_str}、敏捷 {user.state_dex}、體質 {user.state_con}、"
                f"智力 {user.state_int}、感知 {user.state_wis}、魅力 {user.state_cha}\n"
                f"技能: {', '.join(map(str, user.skills)) or '無'}\n"
                f"裝備: {', '.join(map(str, user.inventory)) or '無'}"
            ),
            inline=False,
        )
        if user.summary:
            embed.add_field(name="角色摘要", value=user.summary, inline=False)

    await ctx.respond(embed=embed, ephemeral=True)


async def start():
    token = config.discord_token()
    await bot.start(token=token)
