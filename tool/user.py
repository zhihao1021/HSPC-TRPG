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
    channel_id = context.target_channel_id
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
    channel_id = context.target_channel_id

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


class FinalizeCharacterParam(BaseModel):
    summary: Optional[str] = Field(
        None,
        description="A concise narrative summary of the character "
        "(race, class, personality, background).",
    )
    level: int = Field(
        1,
        description="Character level (a freshly created character is normally level 1).",
        ge=1,
        le=20,
    )
    hp: Optional[int] = Field(
        None,
        description="Current hit points. Defaults to max_hp when omitted.",
    )
    max_hp: int = Field(
        10,
        description="Maximum hit points.",
        ge=1,
    )
    state_str: int = Field(description="Strength ability score.", ge=1, le=30)
    state_dex: int = Field(description="Dexterity ability score.", ge=1, le=30)
    state_con: int = Field(description="Constitution ability score.", ge=1, le=30)
    state_int: int = Field(description="Intelligence ability score.", ge=1, le=30)
    state_wis: int = Field(description="Wisdom ability score.", ge=1, le=30)
    state_cha: int = Field(description="Charisma ability score.", ge=1, le=30)
    skills: list[SkillParam] = Field(
        default_factory=list,
        description="List of starting skills or abilities.",
    )
    inventory: list[InventoryItemParam] = Field(
        default_factory=list,
        description="List of starting inventory items.",
    )


@UserTool.register(
    scope=["chargen"],
    description="Finalize and create a player's character during the private "
    "character-creation flow. Call this only after the player has confirmed their "
    "character. The character is written to the corresponding game channel. "
    "The character's display name is always the player's server display name and "
    "must not be set here. A successful call means character creation is complete."
)
async def finalize_character(context: ChatContext, params: FinalizeCharacterParam) -> str:
    if context.owner_user_id is None:
        return "Error: cannot create a character in the current context."

    hp = params.hp if params.hp is not None else params.max_hp
    hp = max(0, min(hp, params.max_hp))

    display_name = context.owner_display_name or "冒險者"
    try:
        user = User(
            uid=SnowflakeId(context.owner_user_id),
            channel_id=SnowflakeId(context.target_channel_id),
            username=context.owner_username or str(context.owner_user_id),
            display_name=display_name,
            summary=params.summary or "",
            level=params.level,
            hp=hp,
            max_hp=params.max_hp,
            state_str=params.state_str,
            state_dex=params.state_dex,
            state_con=params.state_con,
            state_int=params.state_int,
            state_wis=params.state_wis,
            state_cha=params.state_cha,
            skills=[
                UserSkill(name=s.name, description=s.description, level=s.level)
                for s in params.skills
            ],
            inventory=[
                UserInventoryItem(
                    name=i.name, description=i.description, quantity=i.quantity
                )
                for i in params.inventory
            ],
        )
    except Exception as exc:
        return f"Character data invalid, cannot create: {exc}"

    await user.save(context.conn)
    context.character_created = True

    return (
        f"Character '{display_name}' created successfully and written to the game "
        "channel. Tell the player creation is complete and they may return to the "
        "game channel to begin their adventure."
    )
