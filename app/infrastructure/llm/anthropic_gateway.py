"""Anthropic implementation of ModelGateway."""

from collections.abc import AsyncIterator
from typing import Any

from langchain_anthropic import ChatAnthropic

from app.application.agent.errors import ModelCallError
from app.application.ports.output.llm.model_gateway import (
    ModelGateway,
    ModelResponse,
    ModelStreamChunk,
    TokenUsage,
)
from app.application.tools.definition import ToolCall
from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings
from app.infrastructure.llm.message_converter import convert_dict_messages_to_langchain

logger = get_logger(__name__)


class AnthropicModelGateway(ModelGateway):
    """Anthropic implementation of ModelGateway supporting tool calling."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        chat_model: ChatAnthropic | None = None,
    ):
        self.api_key = api_key or settings.anthropic_api_key
        self.model_name = model or settings.anthropic_model

        if chat_model is not None:
            self.chat_model = chat_model
        else:
            if not self.api_key:
                raise ValueError("Anthropic API key is required for AnthropicModelGateway")
            self.chat_model = ChatAnthropic(
                api_key=self.api_key,
                model=self.model_name,
                temperature=0.7,
                streaming=True,
                max_tokens=4096,
            )

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Generate response with optional tool binding."""
        try:
            lc_messages = convert_dict_messages_to_langchain(messages)

            model: Any = self.chat_model
            if tools:
                model = model.bind_tools(tools)

            invoke_kwargs: dict[str, Any] = {}
            if max_tokens is not None:
                invoke_kwargs["max_tokens"] = max_tokens

            response = await model.ainvoke(lc_messages, **invoke_kwargs)

            tool_calls: list[ToolCall] = []
            if hasattr(response, "tool_calls") and response.tool_calls:
                for tc in response.tool_calls:
                    tool_calls.append(
                        ToolCall(
                            id=str(tc.get("id", "")),
                            name=tc.get("name", ""),
                            arguments=tc.get("args", {}),
                        )
                    )

            usage: TokenUsage | None = None
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage = TokenUsage(
                    prompt_tokens=response.usage_metadata.get("input_tokens", 0),
                    completion_tokens=response.usage_metadata.get("output_tokens", 0),
                    total_tokens=response.usage_metadata.get("total_tokens", 0),
                )

            content = response.content if isinstance(response.content, str) else str(response.content)

            return ModelResponse(
                content=content,
                tool_calls=tool_calls,
                usage=usage,
                model=self.model_name,
                finish_reason=response.response_metadata.get("stop_reason")
                if hasattr(response, "response_metadata")
                else None,
            )

        except Exception as e:
            logger.error("Anthropic model gateway call failed", error=str(e))
            raise ModelCallError(
                message=f"Anthropic call failed: {e!s}",
                details={"model": self.model_name},
                cause=e,
            ) from e

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ModelStreamChunk]:
        """Stream chunks from Anthropic model."""
        try:
            lc_messages = convert_dict_messages_to_langchain(messages)
            model: Any = self.chat_model
            if tools:
                model = model.bind_tools(tools)

            async for chunk in model.astream(lc_messages):
                tool_calls: list[ToolCall] = []
                if hasattr(chunk, "tool_calls") and chunk.tool_calls:
                    for tc in chunk.tool_calls:
                        tool_calls.append(
                            ToolCall(
                                id=str(tc.get("id", "")),
                                name=tc.get("name", ""),
                                arguments=tc.get("args", {}),
                            )
                        )
                yield ModelStreamChunk(
                    content=chunk.content if isinstance(chunk.content, str) else None,
                    tool_calls=tool_calls,
                )
        except Exception as e:
            logger.error("Anthropic streaming failed", error=str(e))
            raise ModelCallError(
                message=f"Anthropic stream failed: {e!s}",
                details={"model": self.model_name},
                cause=e,
            ) from e
