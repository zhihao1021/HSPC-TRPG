"""組裝傳給模型的訊息,並處理工具呼叫序列的健全性(sanitize)。"""
from asyncpg import Connection
from functools import lru_cache

import config
from game import roster as roster_game
from model.message import Message
from model.roster import RosterEntry

from datetime import datetime
from typing import Any


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    path = config.PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()


def sanitize(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """確保 assistant 的 tool_calls 與其後的 tool 結果配對完整。

    壓縮歷史時可能切斷工具序列,留下孤立的 tool 訊息或缺少回應的 tool_calls;
    OpenAI/Deepseek API 對此會報錯,故在送出前清理。
    """
    responded = {
        m.get("tool_call_id")
        for m in msgs
        if m.get("role") == "tool" and m.get("tool_call_id")
    }

    out: list[dict[str, Any]] = []
    referenced: set[str] = set()
    for m in msgs:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            kept = [tc for tc in m["tool_calls"] if tc.get("id") in responded]
            nm = dict(m)
            if kept:
                nm["tool_calls"] = kept
                for tc in kept:
                    referenced.add(tc["id"])
            else:
                nm.pop("tool_calls", None)
                nm["content"] = nm.get("content") or ""
            out.append(nm)
        elif role == "tool":
            if m.get("tool_call_id") in referenced:
                out.append(m)
                referenced.discard(m.get("tool_call_id"))
            # 否則為孤立 tool 訊息,丟棄
        else:
            out.append(m)
    return out


def _dynamic_system(
    now: datetime,
    summary: str,
    roster_entries: list[RosterEntry],
    include_roster: bool,
) -> dict[str, Any]:
    parts = [f"[目前時間] {now.strftime('%Y-%m-%d %H:%M:%S %Z').strip()}"]
    if summary:
        parts.append("[長期劇情摘要]\n" + summary)
    if include_roster:
        parts.append(roster_game.format_status(roster_entries, now.date()))
    return {"role": "system", "content": "\n\n".join(parts)}


async def build_messages(
    conn: Connection,
    channel_id: int,
    now: datetime,
    summary: str,
    roster_entries: list[RosterEntry],
    system_prompt: str = "system",
    include_roster: bool = True,
) -> list[dict[str, Any]]:
    history = await Message.fetch_recent(conn, channel_id, config.context_max_fetch())
    history_dicts = sanitize([m.to_openai() for m in history])

    return [
        {"role": "system", "content": load_prompt(system_prompt)},
        _dynamic_system(now, summary, roster_entries, include_roster),
        *history_dicts,
    ]


def render_for_summary(msgs: list[Message]) -> str:
    """將一批訊息轉成供摘要模型閱讀的純文字。"""
    lines: list[str] = []
    for m in msgs:
        if m.role == "user":
            lines.append(f"玩家: {m.content}")
        elif m.role == "assistant":
            if m.content:
                lines.append(f"GM: {m.content}")
            if m.tool_calls:
                names = ", ".join(
                    tc.get("function", {}).get("name", "?") for tc in m.tool_calls
                )
                lines.append(f"(GM 使用工具: {names})")
        elif m.role == "tool":
            lines.append(f"工具結果: {m.content}")
    return "\n".join(lines)
