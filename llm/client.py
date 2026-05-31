"""Deepseek(OpenAI 相容)對話生成:tool-calling 迴圈、thinking、context 壓縮。"""
from asyncpg import Connection
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)
from pydantic_snowflake import SnowflakeId

import config
from llm import context
from llm.tools import CHARGEN_TOOLS, TOOLS, DiceEvent, ToolContext, dispatch
from model.message import Message
from model.roster import RosterEntry
from model.session import Session

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, cast

_client: Optional[AsyncOpenAI] = None


def get_client() -> AsyncOpenAI:
    global _client  # pylint: disable=global-statement
    if _client is None:
        _client = AsyncOpenAI(
            api_key=config.llm_api_key(),
            base_url=config.llm_base_url(),
        )
    return _client


@dataclass
class GenerationResult:
    content: str
    reasoning: Optional[str] = None
    dice_events: list[DiceEvent] = field(default_factory=list)
    revealed_teams: list[RosterEntry] = field(default_factory=list)
    prompt_tokens: int = 0
    character_created: bool = False


async def summarize(existing_summary: str, conversation_text: str) -> str:
    client = get_client()
    summary_messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": context.load_prompt("summary")},
        {
            "role": "user",
            "content": (
                f"目前已有的劇情摘要:\n{existing_summary or '(尚無)'}\n\n"
                f"以下是一段較舊的對話紀錄:\n{conversation_text}"
            ),
        },
    ]
    resp = await client.chat.completions.create(
        model=config.summary_model(),
        messages=summary_messages,
        temperature=config.llm_temperature(),
        max_tokens=config.llm_max_tokens(),
    )
    return (resp.choices[0].message.content or existing_summary).strip()


def _msg_chars(m: Message) -> int:
    """估算單則訊息的字元數(含 tool_calls),用於推估 token 量。"""
    chars = len(m.content or "")
    if m.tool_calls:
        chars += len(str(m.tool_calls))
    return chars


async def _maybe_compact(
    conn: Connection, channel_id: int, session: Session
) -> str:
    """當 prompt token 用量超過 window 的觸發比例時,把最舊訊息摘要壓縮,
    使 context 縮減回 window 的壓縮比例;回傳(可能更新後的)摘要。

    以實際 token 用量動態校準「字元/token」比例,再據此挑選要移除的最舊訊息,
    最近 CONTEXT_KEEP_RECENT 則一律保留。
    """
    if session.last_token_usage <= config.context_trigger_tokens():
        return session.summary

    keep = config.context_keep_recent()
    msgs = await Message.fetch_recent(conn, channel_id, config.context_max_fetch())
    if len(msgs) <= keep:
        return session.summary

    total_chars = sum(_msg_chars(m) for m in msgs) or 1
    chars_per_token = total_chars / max(session.last_token_usage, 1)
    tokens_to_remove = max(
        session.last_token_usage - config.context_target_tokens(), 0
    )
    chars_to_remove = tokens_to_remove * chars_per_token

    # 只在「最近 keep 則」以外的最舊訊息中挑選,累積到足夠的量為止
    removable = msgs[: len(msgs) - keep]
    selected: list[Message] = []
    acc = 0.0
    for m in removable:
        selected.append(m)
        acc += _msg_chars(m)
        if acc >= chars_to_remove:
            break

    if not selected:
        return session.summary

    conversation_text = context.render_for_summary(selected)
    new_summary = await summarize(session.summary, conversation_text)

    await Session.update_summary(conn, channel_id, new_summary)
    await Message.delete_ids(conn, [int(m.uid) for m in selected])
    return new_summary


def _assistant_dict(msg: ChatCompletionMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        out["tool_calls"] = [tc.model_dump() for tc in msg.tool_calls]
    return out


async def generate(
    conn: Connection,
    channel_id: int,
    now: datetime,
    kickoff: Optional[str] = None,
    *,
    system_prompt: str = "system",
    include_roster: bool = True,
    tools: Optional[list[dict[str, Any]]] = None,
    target_channel_id: Optional[int] = None,
    owner: Optional[tuple[int, str, str]] = None,
    model: Optional[str] = None,
) -> GenerationResult:
    """根據目前 session 的對話歷史生成回應(含工具呼叫)。

    kickoff: 一次性的指示訊息(例如開場導言指令),會附加在訊息尾端引導模型,
        但本身不寫入資料庫歷史。
    system_prompt / include_roster / tools: 供創角等特殊情境改用不同的提示與工具。
    target_channel_id / owner: 創角時角色寫入的目標遊戲頻道與該玩家資訊。
    """
    session = await Session.get(conn, channel_id)
    if session is None:
        raise RuntimeError(f"session 不存在: {channel_id}")

    active_tools = tools if tools is not None else TOOLS

    summary = await _maybe_compact(conn, channel_id, session)
    roster_entries = (
        await RosterEntry.fetch_all(conn, channel_id) if include_roster else []
    )

    messages = await context.build_messages(
        conn, channel_id, now, summary, roster_entries,
        system_prompt=system_prompt, include_roster=include_roster,
    )
    if kickoff:
        messages.append({"role": "user", "content": kickoff})

    owner_user_id, owner_username, owner_display_name = owner or (None, None, None)
    ctx = ToolContext(
        conn=conn,
        channel_id=channel_id,
        today=now.date(),
        target_channel_id=target_channel_id,
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        owner_display_name=owner_display_name,
    )
    client = get_client()
    model = model or config.llm_model()
    reasoning_parts: list[str] = []
    prompt_tokens = 0
    final_content = ""

    max_iters = config.llm_max_tool_iterations()
    for i in range(max_iters):
        # 最後一輪強制不再呼叫工具,確保產出文字回覆
        tool_choice = "none" if i == max_iters - 1 else "auto"
        resp = await client.chat.completions.create(
            model=model,
            messages=cast(list[ChatCompletionMessageParam], messages),
            tools=cast(list[ChatCompletionToolParam], active_tools),
            tool_choice=tool_choice,
            temperature=config.llm_temperature(),
            max_tokens=config.llm_max_tokens(),
        )

        if resp.usage is not None:
            prompt_tokens = resp.usage.prompt_tokens

        msg = resp.choices[0].message
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning:
            reasoning_parts.append(reasoning)

        if msg.tool_calls:
            assistant_dict = _assistant_dict(msg)
            messages.append(assistant_dict)
            await Message(
                channel_id=SnowflakeId(channel_id),
                role="assistant",
                content=msg.content or "",
                tool_calls=assistant_dict.get("tool_calls"),
            ).insert(conn)

            for tc in msg.tool_calls:
                # 只處理 function 類型的工具呼叫(本專案未使用 custom tool)
                if not isinstance(tc, ChatCompletionMessageFunctionToolCall):
                    continue
                result = await dispatch(ctx, tc.function.name, tc.function.arguments)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )
                await Message(
                    channel_id=SnowflakeId(channel_id),
                    role="tool",
                    content=result,
                    tool_call_id=tc.id,
                ).insert(conn)
            continue

        # 無工具呼叫 -> 取得最終文字
        final_content = msg.content or ""
        await Message(
            channel_id=SnowflakeId(channel_id),
            role="assistant",
            content=final_content,
        ).insert(conn)
        break

    await Session.update_token_usage(conn, channel_id, prompt_tokens)

    return GenerationResult(
        content=final_content,
        reasoning="\n\n".join(reasoning_parts) if reasoning_parts else None,
        dice_events=ctx.dice_events,
        revealed_teams=ctx.revealed_teams,
        prompt_tokens=prompt_tokens,
        character_created=ctx.character_created,
    )


async def generate_opening(
    conn: Connection, channel_id: int, now: datetime
) -> GenerationResult:
    """在 /start 後產生 GM 開場導言(導言指令不寫入歷史,GM 回應會保留)。"""
    return await generate(
        conn, channel_id, now, kickoff=context.load_prompt("intro")
    )


async def generate_chargen(
    conn: Connection,
    dm_channel_id: int,
    now: datetime,
    game_channel_id: int,
    owner: tuple[int, str, str],
    kickoff: Optional[str] = None,
) -> GenerationResult:
    """在私訊頻道進行角色創建;角色最終寫入對應的遊戲頻道。"""
    return await generate(
        conn,
        dm_channel_id,
        now,
        kickoff=kickoff,
        system_prompt="chargen",
        include_roster=False,
        tools=CHARGEN_TOOLS,
        target_channel_id=game_channel_id,
        owner=owner,
        model=config.chargen_model(),
    )


async def generate_chargen_opening(
    conn: Connection,
    dm_channel_id: int,
    now: datetime,
    game_channel_id: int,
    owner: tuple[int, str, str],
) -> GenerationResult:
    """私訊創角的開場引導。"""
    return await generate_chargen(
        conn,
        dm_channel_id,
        now,
        game_channel_id=game_channel_id,
        owner=owner,
        kickoff=context.load_prompt("chargen_intro"),
    )
