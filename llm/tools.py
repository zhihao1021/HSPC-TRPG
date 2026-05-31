"""模型可用的工具:定義(OpenAI tools schema)與執行(dispatch)。

執行工具時的副作用(擲骰、公布隊伍)會被收集到 ToolContext 中,
由 bot 端用來產生對應的 Discord Embed。
"""
from asyncpg import Connection
from orjson import dumps, loads
from pydantic_snowflake import SnowflakeId

from dataclasses import dataclass, field
from datetime import date
from logging import getLogger
from random import randint
from typing import Any, Optional

from game import roster as roster_game
from model.roster import RosterEntry
from model.user import User

logger = getLogger("trpg.tools")

# ---- 工具 Schema(傳給模型)----

ALLOWED_SIDES = [2, 3, 4, 6, 8, 10, 12, 20, 100]

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "roll_dice",
            "description": (
                "擲骰。任何結果不確定的情況(攻擊、技能檢定、豁免、隨機事件)"
                "都應使用此工具,而非自行決定數字。結果會自動以 Embed 顯示給玩家。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "骰子數量",
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "sides": {
                        "type": "integer",
                        "description": "骰子面數,例如 20 代表 d20",
                        "enum": ALLOWED_SIDES,
                    },
                    "modifier": {
                        "type": "integer",
                        "description": "加成或減值(可為負),預設 0",
                    },
                    "reason": {
                        "type": "string",
                        "description": "這次擲骰的目的,例如『感知檢定』『長劍攻擊』",
                    },
                    "dc": {
                        "type": "integer",
                        "description": (
                            "成功門檻(難度等級 DC / 命中所需值)。"
                            "提供後系統會自動判定成功或失敗。"
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "對這次擲骰的補充說明,會顯示在結果 Embed 中。"
                            "可說明數值大小對應的意義,例如"
                            "『15 以上閃過陷阱;10 以下觸發機關;20 為完美閃避』。"
                        ),
                    },
                },
                "required": ["count", "sides"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_character",
            "description": "依 Discord 玩家 ID 查詢該玩家角色的屬性、HP、技能與裝備。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "玩家的 Discord 使用者 ID(純數字字串)",
                    }
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_character",
            "description": (
                "更新某玩家角色的狀態。僅傳入需要變更的欄位。"
                "skills 與 inventory 為整份覆寫。若角色尚不存在則此操作會失敗,"
                "請改以敘事引導玩家建立角色後再更新。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "玩家 Discord ID"},
                    "level": {"type": "integer"},
                    "hp": {"type": "integer", "description": "目前生命值"},
                    "max_hp": {"type": "integer", "description": "生命值上限"},
                    "state_str": {"type": "integer", "description": "力量"},
                    "state_dex": {"type": "integer", "description": "敏捷"},
                    "state_con": {"type": "integer", "description": "體質"},
                    "state_int": {"type": "integer", "description": "智力"},
                    "state_wis": {"type": "integer", "description": "感知"},
                    "state_cha": {"type": "integer", "description": "魅力"},
                    "skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "技能清單(整份覆寫)",
                    },
                    "inventory": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "裝備/物品清單(整份覆寫)",
                    },
                    "summary": {
                        "type": "string",
                        "description": "角色背景與現況的簡短摘要",
                    },
                    "reason": {"type": "string", "description": "本次更新的原因"},
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reveal_team",
            "description": (
                "在合適的劇情時機公布一組『已到期』的晉級隊伍。"
                "若該隊伍尚未到期或不存在,工具會回報失敗,此時請順勢調整敘事,不要強行公布。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "team_name": {
                        "type": "string",
                        "description": "要公布的隊伍名稱(需與名單完全相符)",
                    }
                },
                "required": ["team_name"],
            },
        },
    },
]


# 創角流程(私訊)專用的工具:擲屬性骰 + 最終定案
FINALIZE_CHARACTER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "finalize_character",
        "description": (
            "在私訊創角流程中,當玩家確認角色設定後呼叫此工具,正式建立角色。"
            "角色會被寫入對應的遊戲頻道。呼叫成功即代表創角完成。"
            "角色名稱一律使用玩家在群組中的顯示名稱,不需也不可由此工具指定。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "level": {"type": "integer"},
                "hp": {"type": "integer", "description": "目前生命值"},
                "max_hp": {"type": "integer", "description": "生命值上限"},
                "state_str": {"type": "integer", "description": "力量"},
                "state_dex": {"type": "integer", "description": "敏捷"},
                "state_con": {"type": "integer", "description": "體質"},
                "state_int": {"type": "integer", "description": "智力"},
                "state_wis": {"type": "integer", "description": "感知"},
                "state_cha": {"type": "integer", "description": "魅力"},
                "skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "技能清單",
                },
                "inventory": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "起始裝備/物品清單",
                },
                "summary": {
                    "type": "string",
                    "description": "角色背景與設定的簡短摘要",
                },
            },
            "required": [
                "state_str",
                "state_dex",
                "state_con",
                "state_int",
                "state_wis",
                "state_cha",
            ],
        },
    },
}


def _tool_by_name(name: str) -> dict[str, Any]:
    return next(t for t in TOOLS if t["function"]["name"] == name)


CHARGEN_TOOLS: list[dict[str, Any]] = [
    _tool_by_name("roll_dice"),
    FINALIZE_CHARACTER_TOOL,
]


# ---- 副作用收集 ----

@dataclass
class DiceEvent:
    count: int
    sides: int
    modifier: int
    rolls: list[int]
    total: int
    reason: Optional[str] = None
    dc: Optional[int] = None
    description: Optional[str] = None
    success: Optional[bool] = None  # 有提供 dc 時的成功/失敗判定
    crit: Optional[str] = None      # 單顆 d20 的『大成功』/『大失敗』


@dataclass
class ToolContext:
    conn: Connection
    channel_id: int  # 觸發本次生成的 session 頻道(reveal_team 以此為準)
    today: date
    # 角色相關工具實際操作的頻道;創角時為對應的遊戲頻道,一般情況等同 channel_id
    target_channel_id: Optional[int] = None
    # 創角流程專用:這個角色屬於哪位玩家
    owner_user_id: Optional[int] = None
    owner_username: Optional[str] = None
    owner_display_name: Optional[str] = None
    dice_events: list[DiceEvent] = field(default_factory=list)
    revealed_teams: list[RosterEntry] = field(default_factory=list)
    character_created: bool = False

    def __post_init__(self) -> None:
        if self.target_channel_id is None:
            self.target_channel_id = self.channel_id


# ---- 工具執行 ----

def _parse_args(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - 模型可能產生非法 JSON
        return {}


async def dispatch(ctx: ToolContext, name: str, raw_arguments: str) -> str:
    """執行單一工具呼叫,回傳要餵回模型的結果文字。"""
    args = _parse_args(raw_arguments)
    # 記錄工具呼叫的參數(時間戳由 logging 格式提供)
    logger.info(
        "tool-call channel=%s name=%s args=%s",
        ctx.channel_id,
        name,
        dumps(args).decode("utf-8"),
    )
    try:
        if name == "roll_dice":
            result = _roll_dice(ctx, args)
        elif name == "get_character":
            result = await _get_character(ctx, args)
        elif name == "update_character":
            result = await _update_character(ctx, args)
        elif name == "reveal_team":
            result = await _reveal_team(ctx, args)
        elif name == "finalize_character":
            result = await _finalize_character(ctx, args)
        else:
            result = f"未知的工具: {name}"
    except Exception as exc:  # noqa: BLE001 - 防止工具錯誤中斷整個回應
        result = f"工具 {name} 執行失敗: {exc}"

    # 記錄工具結果
    logger.info("tool-result channel=%s name=%s -> %s", ctx.channel_id, name, result)
    return result


def _roll_dice(ctx: ToolContext, args: dict[str, Any]) -> str:
    count = int(args.get("count", 1))
    sides = int(args.get("sides", 20))
    modifier = int(args.get("modifier", 0) or 0)
    reason = args.get("reason")
    description = args.get("description")
    dc = args.get("dc")
    dc = int(dc) if dc is not None else None

    count = max(1, min(count, 100))
    if sides not in ALLOWED_SIDES:
        sides = 20

    rolls = [randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier

    # 成功判定與單顆 d20 的大成功/大失敗
    success = (total >= dc) if dc is not None else None
    crit: Optional[str] = None
    if count == 1 and sides == 20:
        if rolls[0] == 20:
            crit = "大成功"
        elif rolls[0] == 1:
            crit = "大失敗"

    ctx.dice_events.append(
        DiceEvent(
            count=count,
            sides=sides,
            modifier=modifier,
            rolls=rolls,
            total=total,
            reason=reason,
            dc=dc,
            description=description,
            success=success,
            crit=crit,
        )
    )

    detail = " + ".join(str(r) for r in rolls)
    mod_str = ""
    if modifier:
        mod_str = f" {'+' if modifier > 0 else '-'} {abs(modifier)}"

    verdict = ""
    if crit is not None:
        verdict = f";{crit}"
    elif success is not None:
        verdict = f";對 DC {dc} {'成功' if success else '失敗'}"

    return (
        f"擲骰 {count}d{sides}{mod_str}"
        f"{f' ({reason})' if reason else ''}: "
        f"[{detail}]{mod_str} = 總計 {total}{verdict}"
    )


def _parse_user_id(args: dict[str, Any]) -> Optional[int]:
    raw = args.get("user_id")
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


async def _get_character(ctx: ToolContext, args: dict[str, Any]) -> str:
    uid = _parse_user_id(args)
    if uid is None:
        return "錯誤: 缺少或無效的 user_id。"
    user = await User.get(ctx.conn, uid, ctx.target_channel_id)
    if user is None:
        return f"玩家 {uid} 尚未建立角色。"
    return (
        f"玩家 {user.display_name} (ID:{user.uid}) 的角色:\n"
        f"等級 {user.level} / HP {user.hp}/{user.max_hp}\n"
        f"力量 {user.state_str}、敏捷 {user.state_dex}、體質 {user.state_con}、"
        f"智力 {user.state_int}、感知 {user.state_wis}、魅力 {user.state_cha}\n"
        f"技能: {', '.join(map(str, user.skills)) or '無'}\n"
        f"裝備: {', '.join(map(str, user.inventory)) or '無'}\n"
        f"摘要: {user.summary or '(無)'}"
    )


_UPDATE_KEYS = {
    "level",
    "hp",
    "max_hp",
    "state_str",
    "state_dex",
    "state_con",
    "state_int",
    "state_wis",
    "state_cha",
    "skills",
    "inventory",
    "summary",
}


async def _update_character(ctx: ToolContext, args: dict[str, Any]) -> str:
    uid = _parse_user_id(args)
    if uid is None:
        return "錯誤: 缺少或無效的 user_id。"

    updates = {k: v for k, v in args.items() if k in _UPDATE_KEYS}
    if not updates:
        return "未提供任何可更新的欄位。"

    user = await User.apply_updates(ctx.conn, uid, ctx.target_channel_id, updates)
    if user is None:
        return (
            f"玩家 {uid} 尚未建立角色,無法更新。"
            "請先在劇情中引導其建立角色。"
        )
    return (
        f"已更新玩家 {user.display_name} (ID:{user.uid}) 的角色。"
        f"目前 HP {user.hp}/{user.max_hp}、等級 {user.level}。"
    )


async def _reveal_team(ctx: ToolContext, args: dict[str, Any]) -> str:
    team_name = str(args.get("team_name", "")).strip()
    if not team_name:
        return "錯誤: 缺少 team_name。"

    entries = await RosterEntry.fetch_all(ctx.conn, ctx.channel_id)
    target = next((e for e in entries if e.name == team_name), None)
    if target is None:
        return f"名單中找不到隊伍『{team_name}』,請勿杜撰隊伍名稱。"
    if target.revealed:
        return f"隊伍『{team_name}』先前已公布過。"
    if not roster_game.is_due(target, ctx.today):
        return (
            f"隊伍『{team_name}』尚未到建議公布日期({target.suggested_date}),"
            "現在還不能公布,請繼續鋪陳劇情。"
        )

    revealed = await RosterEntry.reveal(ctx.conn, ctx.channel_id, team_name)
    if revealed is None:
        return f"公布隊伍『{team_name}』時發生錯誤。"

    ctx.revealed_teams.append(revealed)
    # 將已公布名單輸出到獨立檔案
    await roster_game.write_revealed_file(ctx.conn, ctx.channel_id)
    remaining = await RosterEntry.count_remaining(ctx.conn, ctx.channel_id)
    return (
        f"隊伍『{team_name}』已正式列入晉級名單(並已寫入紀錄檔)。"
        f"請『不要』另外貼出一段制式公告,而是把這個名字自然地融入你接下來的劇情敘述中"
        f"——例如刻在石碑上的名字、星光中浮現的隊名、王座大廳的宣告等,讓公布成為故事的一部分。"
        f"尚有 {remaining} 組隊伍未公布,請維持每天約一組的節奏。"
    )


async def _finalize_character(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.owner_user_id is None or ctx.target_channel_id is None:
        return "錯誤: 目前情境無法建立角色。"

    fields = {k: v for k, v in args.items() if k in _UPDATE_KEYS}
    # 角色名稱一律使用玩家在群組中的顯示名稱
    display_name = ctx.owner_display_name or "冒險者"

    try:
        user = User(
            uid=SnowflakeId(ctx.owner_user_id),
            channel_id=SnowflakeId(ctx.target_channel_id),
            username=ctx.owner_username or str(ctx.owner_user_id),
            display_name=display_name,
            **fields,
        )
    except Exception as exc:  # noqa: BLE001 - 欄位驗證失敗
        return f"角色資料無效,無法建立: {exc}"

    await user.insert(ctx.conn)
    ctx.character_created = True
    return (
        f"角色『{display_name}』已建立完成並寫入遊戲頻道。"
        "請告知玩家創角完成,可回到遊戲頻道開始冒險。"
    )
