from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessageToolCall,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)

from asyncio import gather
from typing import Any, cast, Optional

from config import CONFIG
from game import roster as roster_game
from model.message import Message
from model.roster import Roster
from model.session import SessionKind
from tool.base import ToolBase
from tool.dice import DiceTool
from tool.roster import RosterTool
from tool.user import UserTool
from tool.types.chat_context import ChatContext
from type.chat import (
    DeepseekChatCompletionMessage,
    DeepseekChatCompletionMessageParam,
)


from .prompt import PromptStore

PROMPT_STORE = PromptStore()

TOOL_CLASSES: list[type[ToolBase]] = [
    DiceTool,
    UserTool,
    RosterTool,
]


class DeepseekClient():
    _client: AsyncOpenAI
    _model: str
    _reasoning: bool
    _max_tokens: int
    _temperature: float
    _session_kind: SessionKind

    def __init__(
        self,
        model: str,
        reasoning: bool = False,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        session_kind: SessionKind = "game",
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=CONFIG.llm.api_key,
            base_url=CONFIG.llm.base_url,
        )
        self._model = model
        self._reasoning = reasoning
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._session_kind = session_kind

    def _build_messages(
        self,
        ctx: Optional[ChatContext],
        messages: list[DeepseekChatCompletionMessageParam],
    ) -> list[DeepseekChatCompletionMessageParam]:
        system_prompt = PROMPT_STORE.get_prompt(self._session_kind)
        system_message = ChatCompletionSystemMessageParam(
            role="system",
            content=system_prompt,
        )

        system_prompts = [system_message]
        if ctx and ctx.summary:
            system_prompts.append(
                ChatCompletionSystemMessageParam(
                    role="system",
                    content="[長期劇情摘要]\n" + ctx.summary,
                )
            )
        return system_prompts + messages

    def _create_kwargs(self, *, with_tools: bool) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "tools": [
                tool
                for tool_cls in TOOL_CLASSES
                for tool in tool_cls.to_openai_tools(session=self._session_kind)
            ]
        }

        if self._reasoning:
            kwargs["reasoning_effort"] = "high"
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        else:
            kwargs["temperature"] = self._temperature
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        if with_tools:
            kwargs["tool_choice"] = "auto"
        else:
            kwargs["tool_choice"] = "none"

        return kwargs

    @staticmethod
    async def _dispatch_tool(
        ctx: ChatContext,
        tool_call: ChatCompletionMessageToolCall,
    ) -> str:
        for tool_cls in TOOL_CLASSES:
            result = await tool_cls.call_tool(ctx, tool_call)
            if result is not None:
                return result
        return f"Error: unknown tool '{tool_call.function.name}'"

    async def generate_opening(self, world: str = "") -> str:
        intro_prompt = PROMPT_STORE.get_prompt(f"{self._session_kind}_intro")

        user_messages: list[DeepseekChatCompletionMessageParam] = []
        if world:
            user_messages.append(ChatCompletionUserMessageParam(
                role="user",
                content=(
                    "【本場冒險的世界觀設定(由主持人於開場時提供)】\n"
                    f"{world}\n\n"
                    "請務必以上述世界觀為基礎來撰寫這場冒險的開場;"
                    "這段開場將成為後續所有劇情的世界觀基準。"
                ),
            ))
        user_messages.append(ChatCompletionUserMessageParam(
            role="user",
            content=intro_prompt,
        ))

        messages = self._build_messages(None, user_messages)

        response: ChatCompletion = await self._client.chat.completions.create(
            messages=messages,
            **self._create_kwargs(with_tools=False),
        )

        return response.choices[0].message.content or ""

    async def generate(
        self,
        ctx: ChatContext,
        messages: list[DeepseekChatCompletionMessageParam],
    ) -> list[DeepseekChatCompletionMessageParam]:
        system_messages = self._build_messages(ctx, messages)
        new_messages: list[DeepseekChatCompletionMessageParam] = []

        max_iters = CONFIG.llm.max_tool_iterations
        for i in range(max_iters):
            # 最後一輪強制不再呼叫工具,確保最終產出文字回覆
            with_tools = i < max_iters - 1
            response: ChatCompletion = await self._client.chat.completions.create(
                messages=system_messages + new_messages,
                **self._create_kwargs(with_tools=with_tools),
            )

            choice = response.choices[0]
            message = cast(
                DeepseekChatCompletionMessage,
                choice.message
            )
            message_dump = cast(
                DeepseekChatCompletionMessageParam,
                message.model_dump()
            )

            new_messages.append(message_dump)

            if not message.tool_calls or choice.finish_reason == "stop":
                break

            function_tool_calls = [
                tool_call
                for tool_call in message.tool_calls
                if tool_call.type == "function"
            ]

            tool_results = [
                await self._dispatch_tool(ctx, tool_call)
                for tool_call in function_tool_calls
            ]
            tool_params = [
                ChatCompletionToolMessageParam(
                    role="tool",
                    tool_call_id=tool_call.id,
                    content=tool_result,
                )
                for tool_call, tool_result in zip(
                    function_tool_calls,
                    tool_results
                )
            ]

            new_messages.extend(tool_params)

        return new_messages

    async def summarize(
        self,
        last_summary: str,
        messages: list[Message],
    ) -> str:
        system_message = ChatCompletionSystemMessageParam(
            role="system",
            content=PROMPT_STORE.get_prompt(f"summary"),
        )

        history = [
            "===== Last summary Start =====",
            last_summary,
            "===== Last summary End =====",
        ]
        for msg in messages:
            role = msg.role
            if role == "system":
                continue

            if role == "user":
                content = msg.content
                name = msg.name
                if not isinstance(content, str):
                    continue
                history.append(f"[User][{name or '?'}]{content}")
            elif role == "assistant":
                content = msg.content
                tool_calls = msg.tool_calls
                if content:
                    history.append(f"[GM]: {content}")
                elif tool_calls:
                    history.append(f"[Call Tools]")
            elif role == "tool":
                content = msg.content
                if not isinstance(content, str):
                    continue
                history.append(f"[Tool] {content}")

        history_string = "\n".join(history)
        prompt = ChatCompletionUserMessageParam(
            role="user",
            content=history_string
        )

        response: ChatCompletion = await self._client.chat.completions.create(
            messages=[system_message, prompt],
            **self._create_kwargs(with_tools=False),
        )

        return response.choices[0].message.content or ""
