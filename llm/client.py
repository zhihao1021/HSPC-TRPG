from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionFunctionToolParam

from typing import Literal, TypeAlias, Union

import config
from model.session import SessionKind
from tool.dice import DiceTool
from tool.types.chat_context import ChatContext
from type.chat import DeepseekChatCompletionMessageParam


from .prompt import PromptStore

PROMPT_STORE = PromptStore()

TOOLS: list[ChatCompletionFunctionToolParam] = [
    *DiceTool.to_openai_tools(),
]


class DeepseekClient():
    _client: AsyncOpenAI
    _model: str
    _reasoning: bool
    _chat_type: SessionKind

    def __init__(
        self,
        model: str,
        reasoning: bool = False,
        chat_type: SessionKind = "game",
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=config.llm_api_key(),
            base_url=config.llm_base_url(),
        )
        self._model = model
        self._reasoning = reasoning
        self._chat_type = chat_type

    def _build_messages(
        self,
        messages: list[DeepseekChatCompletionMessageParam],
    ) -> list[DeepseekChatCompletionMessageParam]:
        system_prompts = []
        if self._chat_type == "game":
            system_prompts.append(PROMPT_STORE.get_prompt("game"))
        elif self._chat_type == "chargen":
            system_prompts.append(PROMPT_STORE.get_prompt("chargen"))
        else:
            raise ValueError(f"Invalid chat type: {self._chat_type}")

        return system_prompts + messages

    async def generate_intro(
        self,
        ctx: ChatContext,
    ) -> str:
        return ""

    async def generate(
        self,
        ctx: ChatContext,
        messages: list[DeepseekChatCompletionMessageParam],
    ) -> list[DeepseekChatCompletionMessageParam]:
        # response = await self.client.chat.completions.create(
        #     messages=
        # )

        return []
