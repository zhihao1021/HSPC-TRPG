from pydantic import BaseModel, Field

from random import randint
from typing import Literal, Optional

from .base import ToolBase
from .types.chat_context import ChatContext
from .types.dice_event import DiceEvent, DiceResultType


class DiceTool(ToolBase):
    __class_name__ = "dice"


class DiceRollParam(BaseModel):
    count: int = Field(
        default=1,
        description="Number of dice to roll.",
        gt=0,
        le=100
    )
    sides: Literal[4, 6, 8, 10, 12, 20, 100] = Field(
        default=6,
        description="Number of sides on the die.",
    )
    modifier: int = Field(
        default=0,
        description="Modifier to add to the total roll.",
        ge=-1000,
        le=1000
    )
    reason: Optional[str] = Field(
        None,
        description="Optional reason for the roll, included in the response.",
    )
    dc: Optional[int] = Field(
        description="Optional difficulty class (DC) to compare the roll against."
    )
    description: Optional[str] = Field(
        None,
        description="Optional description of the roll's significance, e.g. '15+ to avoid trap; 10- triggers mechanism; 20 is perfect dodge.'"
    )


@DiceTool.register(
    scope=["game"],
    description="Roll a specified number of dice with a specified number of sides, and an optional modifier."
    "Can be used for any kind of roll, such as attack rolls, damage rolls, or skill checks."
    "The reason field can be used to provide context for the roll, which may be included in the response."
    "The DC field can be used to specify a difficulty class to compare the roll against, which may also be included in the response."
    "You should use this tool instance of determining the result of any die rolls, rather than generating random numbers yourself,"
    "to ensure that the rolls are properly recorded and can be referenced later in the session."
)
def roll_dice(context: ChatContext, params: DiceRollParam):
    results = [
        randint(1, params.sides) for _ in range(params.count)
    ]
    total = sum(results) + params.modifier

    if all([r == 1 for r in results]):
        verdice = DiceResultType.CRITICAL_FAILURE
    elif all([r == params.sides for r in results]):
        verdice = DiceResultType.CRITICAL_SUCCESS
    elif params.dc is not None:
        verdice = DiceResultType.SUCCESS if total >= params.dc else DiceResultType.FAILURE
    else:
        verdice = None

    dice_event = DiceEvent(
        count=params.count,
        sides=params.sides,
        modifier=params.modifier,
        reason=params.reason,
        dc=params.dc,
        description=params.description,
        raw_values=results,
        total=total,
        result=verdice
    )
    context.dice_events.append(dice_event)

    return (
        f"Rolled {params.count}d{params.sides}{'+' if params.modifier >= 0 else ''}{params.modifier}: "
        f"Results: {results}, Total: {total}, {verdice}"
    )
