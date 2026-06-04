from pydantic import BaseModel
from discord import Embed, Colour

from enum import Enum
from typing import Optional


class DiceResultType(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    CRITICAL_SUCCESS = "critical_success"
    CRITICAL_FAILURE = "critical_failure"


class DiceEvent(BaseModel):
    count: int
    sides: int
    modifier: int
    reason: Optional[str] = None
    dc: Optional[int] = None
    description: Optional[str] = None
    raw_values: list[int]
    total: int
    result: Optional[DiceResultType] = None

    def to_discord_embed(self) -> Embed:
        mod = ""
        if self.modifier:
            mod = f" {'+' if self.modifier > 0 else '-'} {abs(self.modifier)}"
        formula = f"{self.count}d{self.sides}{mod}"
        detail = " + ".join(str(r) for r in self.raw_values)

        colour = Colour.gold()
        if self.result == DiceResultType.SUCCESS or self.result == DiceResultType.CRITICAL_SUCCESS:
            colour = Colour.green()
        elif self.result == DiceResultType.FAILURE or self.result == DiceResultType.CRITICAL_FAILURE:
            colour = Colour.red()

        embed = Embed(title="🎲 擲骰結果", colour=colour)
        if self.reason:
            embed.add_field(name="目的", value=self.reason, inline=False)
        embed.add_field(name="骰式", value=formula, inline=True)
        embed.add_field(name="擲出", value=f"[{detail}]{mod}", inline=True)
        embed.add_field(name="總計", value=str(self.total), inline=True)

        if self.dc is not None:
            embed.add_field(name="門檻 DC", value=str(self.dc), inline=True)

        # 判定(大成功/大失敗 優先,其次成功/失敗)
        verdict: Optional[str] = None
        if self.result == DiceResultType.CRITICAL_SUCCESS:
            verdict = "🎯 大成功!"
        elif self.result == DiceResultType.CRITICAL_FAILURE:
            verdict = "💥 大失敗!"
        elif self.result == DiceResultType.SUCCESS:
            verdict = "✅ 成功"
        elif self.result == DiceResultType.FAILURE:
            verdict = "❌ 失敗"
        if verdict is not None:
            embed.add_field(name="判定", value=verdict, inline=True)

        if self.description:
            embed.add_field(name="說明", value=self.description, inline=False)

        return embed
