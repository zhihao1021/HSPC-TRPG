from openai import pydantic_function_tool
from openai.types.chat import (
    ChatCompletionFunctionToolParam,
    ChatCompletionMessageToolCall,
)
from pydantic import BaseModel
from orjson import dumps

from inspect import isawaitable, signature
from logging import getLogger
from typing import (
    Any,
    Callable,
    ClassVar,
    Generic,
    Iterable,
    Optional,
    TypeVar,
)

from .types.chat_context import ChatContext, SessionKind

logger = getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
U = TypeVar("U", bound=Any)


class ToolData(Generic[U]):
    _class_name: str
    _name: str
    _func: Callable[..., U]
    _description: str
    _tool_param: type[BaseModel]
    _scope: Iterable[SessionKind]

    def __init__(
        self,
        class_name: str,
        name: str,
        func: Callable[..., U],
        scope: Iterable[SessionKind],
        description: str = "",
    ) -> None:
        self._class_name = class_name
        self._name = name
        self._func = func
        self._description = description
        self._scope = scope

        parameters = list(signature(func).parameters.values())
        if len(parameters) != 2:
            raise ValueError(
                "Tool function must have exactly two parameters: context and tool data.")

        _, tool_param = parameters
        self._tool_param = tool_param.annotation

    @property
    def scope(self) -> Iterable[SessionKind]:
        return self._scope

    @property
    def function_name(self) -> str:
        return f"{self._class_name}-{self._name}"

    def to_openai(self) -> ChatCompletionFunctionToolParam:
        return pydantic_function_tool(
            model=self._tool_param,
            name=self.function_name,
            description=self._description,
        )

    def call(
        self,
        ctx: ChatContext,
        tool_call: ChatCompletionMessageToolCall,
    ) -> U:
        return self._func(
            ctx,
            self._tool_param.model_validate_json(tool_call.function.arguments)
        )


class ToolBase():
    __class_name__: ClassVar[str]
    _registered_tools: ClassVar[dict[str, ToolData]]

    def __init_subclass__(cls) -> None:
        cls.__class_name__ = getattr(cls, "__class_name__", cls.__name__)
        cls._registered_tools = {}

    @classmethod
    def register(
        cls,
        description: str,
        name: Optional[str] = None,
        scope: Iterable[SessionKind] = ["game", "chargen"],
    ) -> Callable[[Callable[[ChatContext, T], U]], Callable[[ChatContext, T], U]]:
        def dec(func: Callable[[ChatContext, T], U]) -> Callable[[ChatContext, T], U]:
            tool = ToolData(
                class_name=cls.__class_name__,
                name=name or func.__name__,
                func=func,
                description=description,
                scope=scope
            )
            cls._registered_tools[tool.function_name] = tool
            return func

        return dec

    @classmethod
    def to_openai_tools(cls, session: SessionKind) -> list[ChatCompletionFunctionToolParam]:
        return [
            tool.to_openai()
            for tool in cls._registered_tools.values()
            if session in tool.scope
        ]

    @classmethod
    async def call_tool(
        cls,
        ctx: ChatContext,
        tool_call: ChatCompletionMessageToolCall,
    ) -> Optional[str]:
        function_name = tool_call.function.name
        tool = cls._registered_tools.get(function_name)
        if tool is None:
            return None

        logger.info(
            "工具呼叫: %s args=%s",
            function_name, tool_call.function.arguments,
        )

        result = tool.call(ctx, tool_call)
        if isawaitable(result):
            result = await result

        try:
            if isinstance(result, str):
                return result
            if isinstance(result, bytes):
                return result.decode("utf-8")
            if isinstance(result, (int, float, bool)):
                return str(result)
            if isinstance(result, BaseModel):
                return result.model_dump_json()
            return dumps(result).decode("utf-8")
        except Exception as e:
            raise ValueError(
                f"Tool function return value is not JSON serializable: {str(e)}") from e
