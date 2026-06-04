from pydantic_snowflake import SnowflakeId

from typing import TypeAlias, Union

UidType: TypeAlias = Union[int, SnowflakeId]
