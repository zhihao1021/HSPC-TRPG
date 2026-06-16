from discord import Message as DiscordMessage
from pydantic import BaseModel, Field
from pydantic_snowflake import SnowflakeId

from typing import Optional

from model.user import User, UserInventoryItem, UserSkill

from .base import ToolBase
from .types.chat_context import ChatContext


class UserTool(ToolBase):
    __class_name__ = "user"


class SkillParam(BaseModel):
    name: str = Field(description="Name of the skill or ability.")
    description: Optional[str] = Field(
        None,
        description="Short description of what the skill does.",
    )
    level: Optional[int] = Field(
        None,
        description="Proficiency level of the skill, if applicable.",
    )


class InventoryItemParam(BaseModel):
    name: str = Field(description="Name of the item.")
    description: Optional[str] = Field(
        None,
        description="Short description of the item.",
    )
    quantity: Optional[int] = Field(
        None,
        description="How many of this item the character holds.",
        ge=0,
    )


class GetCharacterParam(BaseModel):
    uid: int = Field(
        description="The Discord user ID of the player whose character sheet to read. "
        "This is the numeric ID shown in the structured player message."
    )


class UpdateCharacterParam(BaseModel):
    uid: int = Field(
        description="The Discord user ID of the player whose character to update. "
        "This is the numeric ID shown in the structured player message."
    )
    summary: Optional[str] = Field(
        None,
        description="A concise narrative summary of the character "
        "(race, class, personality, background). Replaces the existing summary when provided.",
    )
    level: Optional[int] = Field(
        None,
        description="Character level.",
        ge=1,
        le=20,
    )
    hp: Optional[int] = Field(
        None,
        description="Current hit points. Will be clamped to the range [0, max_hp].",
    )
    max_hp: Optional[int] = Field(
        None,
        description="Maximum hit points.",
        ge=1,
    )
    state_str: Optional[int] = Field(
        None,
        description="Strength ability score.",
        ge=1,
        le=30
    )
    state_dex: Optional[int] = Field(
        None,
        description="Dexterity ability score.",
        ge=1,
        le=30
    )
    state_con: Optional[int] = Field(
        None,
        description="Constitution ability score.",
        ge=1,
        le=30
    )
    state_int: Optional[int] = Field(
        None,
        description="Intelligence ability score.",
        ge=1,
        le=30
    )
    state_wis: Optional[int] = Field(
        None,
        description="Wisdom ability score.",
        ge=1,
        le=30
    )
    state_cha: Optional[int] = Field(
        None,
        description="Charisma ability score.",
        ge=1,
        le=30
    )
    skills: Optional[list[SkillParam]] = Field(
        None,
        description="List of skills or abilities to update. Replaces the existing list when provided.",
    )
    inventory: Optional[list[InventoryItemParam]] = Field(
        None,
        description="List of inventory items to update. Replaces the existing list when provided.",
    )


@UserTool.register(
    scope=["game"],
    description="Read a player's character sheet. Provide the uid to identify the character. "
    "Returns the character sheet as a JSON string. If no character is found for the given uid, returns an error message."
)
async def get_character(context: ChatContext, params: GetCharacterParam) -> str:
    channel_id = context.message.channel.id
    user = await User.get_by_uid_and_channel_id(
        context.conn,
        params.uid,
        channel_id,
    )

    if user is None:
        return (
            f"No character found for user {params.uid} in this channel. "
            "The player has not created a character yet."
        )

    return user.model_dump_json()


@UserTool.register(
    scope=["game"],
    description="Update a player's character sheet with new values. "
    "Provide the uid to identify the character, and any fields to update. "
    "Fields that are not included will remain unchanged. "
    "The inventory and skills fields will replace the existing lists when provided. "
)
async def update_character(context: ChatContext, params: UpdateCharacterParam) -> str:
    conn = context.conn
    channel_id = context.message.channel.id

    user = await User.get_by_uid_and_channel_id(conn, params.uid, channel_id)
    if user is None:
        return f"No character found for user {params.uid} in this channel. Cannot update non-existent character."

    update_data = params.model_dump(
        exclude_unset=True,
        exclude_none=True
    )

    for field in update_data.keys():
        setattr(user, field, getattr(params, field))
    user.hp = max(0, min(user.hp, user.max_hp))

    await user.save(conn)

    return f"Character updated successfully, current state: {user.model_dump_json()}"
