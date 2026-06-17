"""晉級名單:從 JSON 載入、種入 session、計算公布節奏與狀態。"""
from asyncpg import Connection
from orjson import dumps, loads, OPT_INDENT_2

from datetime import date, datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

from config import CONFIG
from model.roster import Roster
from type.uid import UidType


class RosterTeam(NamedTuple):
    name: str
    reveal_date: datetime


def load_roster_file(path: Optional[str] = None) -> list[RosterTeam]:
    """從 JSON 檔讀取名單,回傳依 reveal_date 排序的隊伍清單。"""
    file_path = Path(path or CONFIG.game.roster.file)
    with open(file_path, "rb") as f:
        data = loads(f.read())

    teams: list[RosterTeam] = []
    for item in data.get("teams", []):
        name = str(item["name"]).strip()
        reveal_date = datetime.strptime(item["reveal_date"], "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        teams.append(RosterTeam(name=name, reveal_date=reveal_date))

    teams.sort(key=lambda t: t.reveal_date)
    return teams


async def seed_session(
    conn: Connection,
    channel_id: UidType,
    path: Optional[str] = None,
) -> int:
    """將名單種入指定 session,回傳種入的隊伍數量。"""
    teams = load_roster_file(path)
    return await Roster.seed(
        conn,
        channel_id,
        [(t.name, t.reveal_date) for t in teams],
    )


class RosterStatus(NamedTuple):
    revealed: list[Roster]
    due: list[Roster]      # 已到期但尚未公布(可公布)
    locked: list[Roster]   # 尚未到期


def classify(entries: list[Roster], today: date) -> RosterStatus:
    revealed = [e for e in entries if e.revealed]
    due = [
        e for e in entries
        if not e.revealed and e.suggested.date() <= today
    ]
    locked = [
        e for e in entries
        if not e.revealed and e.suggested.date() > today
    ]
    return RosterStatus(revealed=revealed, due=due, locked=locked)


def is_due(entry: Roster, today: date) -> bool:
    return not entry.revealed and entry.suggested.date() <= today


async def write_revealed_file(
    conn: Connection,
    channel_id: UidType,
    dir_path: Optional[str] = None,
) -> Path:
    """將某頻道目前已公布的隊伍輸出到 <channel_id>.json,回傳檔案路徑。"""
    entries = await Roster.get_all_by_channel_id(conn, channel_id, revealed=True)
    entries.sort(key=lambda e: e.revealed_at or datetime.min.replace(tzinfo=timezone.utc))

    out_dir = Path(dir_path or CONFIG.game.roster.revealed_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{int(channel_id)}.json"

    payload = {
        "channel_id": str(int(channel_id)),
        "revealed_count": len(entries),
        "teams": [
            {
                "name": e.name,
                "suggested_date": e.suggested.date().isoformat(),
                "revealed_at": e.revealed_at.isoformat() if e.revealed_at else None,
            }
            for e in entries
        ],
    }
    out_path.write_bytes(dumps(payload, option=OPT_INDENT_2))
    return out_path


def format_status(entries: list[Roster], today: date) -> str:
    """產生給模型參考的名單狀態文字(不洩漏未到期隊伍的名稱)。"""
    status = classify(entries, today)
    lines: list[str] = ["[晉級名單狀態]"]

    if status.revealed:
        lines.append("已公布: " + "、".join(e.name for e in status.revealed))
    else:
        lines.append("已公布: (尚無)")

    if status.due:
        lines.append(
            "現在可以公布(已到期,擇機透過 reveal_team 揭曉): "
            + "、".join(e.name for e in status.due)
        )
    else:
        lines.append("現在可以公布: (今日無到期隊伍,請專注鋪陳劇情,勿強行公布)")

    lines.append(
        f"尚未到期、不可公布的隊伍數量: {len(status.locked)} "
        "(這些隊伍名稱不可在劇情中透露或預告)"
    )
    return "\n".join(lines)
