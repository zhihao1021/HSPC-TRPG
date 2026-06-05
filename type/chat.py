from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageParam,
    ChatCompletionAssistantMessageParam
)

from typing import Literal, Optional, TypeAlias, Union


class DeepseekChatCompletionAssistantMessageParam(ChatCompletionAssistantMessageParam, total=False):
    """Custom assistant message parameter for Deepseek, extending the OpenAI type with additional fields."""

    reasoning_content: Optional[str]
    """Additional field to store the model's reasoning process, if available."""


class DeepseekChatCompletionMessage(ChatCompletionMessage):
    """Custom chat completion message for Deepseek, extending the OpenAI type with additional fields."""

    reasoning_content: Optional[str] = None
    """Additional field to store the model's reasoning process, if available."""


DeepseekChatCompletionMessageParam: TypeAlias = Union[
    ChatCompletionMessageParam,
    DeepseekChatCompletionAssistantMessageParam,
]

SessionKind: TypeAlias = Literal["game", "chargen"]
ChatType: TypeAlias = Union[SessionKind, Literal["summary"]]
