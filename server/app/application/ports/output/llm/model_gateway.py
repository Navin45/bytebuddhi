"""ModelGateway protocol and structured model interaction contracts."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.application.tools.definition import ToolCall


@dataclass
class TokenUsage:
    """Token usage metrics for an LLM call or run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "TokenUsage") -> "TokenUsage":
        """Sum token usages."""
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass
class ModelResponse:
    """Structured response from an LLM invocation."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    model: str | None = None
    finish_reason: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        """Check if model requested any tool invocations."""
        return len(self.tool_calls) > 0


@dataclass
class ModelStreamChunk:
    """A streaming chunk from an LLM invocation."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None


@runtime_checkable
class ModelGateway(Protocol):
    """Protocol for model-agnostic LLM interaction with tool-calling capabilities."""

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Generate a response, optionally binding tools."""
        ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ModelStreamChunk]:
        """Stream a response with token or tool call chunks."""
        ...
