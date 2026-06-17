from pydantic import BaseModel, Field

from typing import Literal

from game import roster as roster_game
from model.roster import Roster

from .base import ToolBase
from .types.chat_context import ChatContext


class RosterTool(ToolBase):
    __class_name__ = "roster"


class ListTeamsParam(BaseModel):
    status: Literal["all", "revealed", "pending"] = Field(
        default="all",
        description="Which teams to list: 'all' for every team, 'revealed' for teams "
        "already published, 'pending' for teams not yet published.",
    )


@RosterTool.register(
    scope=["game"],
    description="List the advancement-roster teams together with their suggested reveal "
    "dates and reveal status. Use the 'status' filter to get all / revealed / pending "
    "teams. Call this to understand the reveal pacing and to decide whether any team is "
    "due to be revealed today. IMPORTANT: this is for your own planning only — never tell "
    "players the names of teams that have not yet been revealed, nor announce future "
    "reveal dates."
)
async def list_teams(context: ChatContext, params: ListTeamsParam) -> dict:
    today = context.now.date()
    entries = await Roster.get_all_by_channel_id(context.conn, context.channel_id)

    def to_item(entry: Roster) -> dict:
        due = roster_game.is_due(entry, today)
        result = {
            "suggested_date": entry.suggested.date().isoformat(),
            "revealed": entry.revealed,
            "revealed_at": entry.revealed_at.isoformat() if entry.revealed_at else None,
            "due": due,
        }
        if due:
            result["name"] = entry.name

        return result

    if params.status == "revealed":
        selected = [e for e in entries if e.revealed]
    elif params.status == "pending":
        selected = [e for e in entries if not e.revealed]
    else:
        selected = list(entries)

    return {
        "today": today.isoformat(),
        "status": params.status,
        "count": len(selected),
        "teams": [to_item(e) for e in selected],
    }


class RevealTeamParam(BaseModel):
    team_name: str = Field(
        description="Name of the team to reveal. Must match a team on the roster exactly."
    )


@RosterTool.register(
    scope=["game"],
    description="Reveal one team from the advancement roster at a fitting moment in the "
    "story. Only teams that are already 'due' (past their suggested reveal date) can be "
    "revealed. If the team is not yet due or does not exist, the tool reports failure; in "
    "that case adjust your narrative instead of forcing a reveal. After a successful "
    "reveal, weave the team name naturally into the ongoing story rather than posting a "
    "formal announcement."
)
async def reveal_team(context: ChatContext, params: RevealTeamParam) -> str:
    team_name = params.team_name.strip()
    if not team_name:
        return "Error: team_name is required."

    today = context.now.date()
    entries = await Roster.get_all_by_channel_id(context.conn, context.channel_id)
    target = next((e for e in entries if e.name == team_name), None)
    if target is None:
        return f"No team named '{team_name}' on the roster. Do not invent team names."
    if target.revealed:
        return f"Team '{team_name}' has already been revealed."
    if not roster_game.is_due(target, today):
        return (
            f"Team '{team_name}' has not reached its suggested reveal date "
            f"({target.suggested.date().isoformat()}) yet. Keep building the story."
        )

    revealed = await Roster.reveal(context.conn, context.channel_id, team_name)
    if revealed is None:
        return f"Failed to reveal team '{team_name}'."

    context.revealed_teams.append(revealed)
    await roster_game.write_revealed_file(context.conn, context.channel_id)
    remaining = await Roster.count_remaining(context.conn, context.channel_id)

    return (
        f"Team '{team_name}' has been added to the advancement roster (and recorded). "
        "Do NOT post a separate formal announcement; instead weave this name naturally "
        "into your next piece of narration — e.g. a name carved on a monument, a team "
        "name forming among the stars, a proclamation in the throne hall. "
        f"There are {remaining} teams left to reveal; keep the pace at roughly one per day."
    )
