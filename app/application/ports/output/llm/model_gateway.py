"""ModelGateway protocol and structured model interaction contracts."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from app.application.tools.definition import ToolCall


class ModelCapability(StrEnum):
    """Declared model capabilities. Adapters must not claim unsupported features."""

    CHAT = "chat"
    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"
    VISION = "vision"
    STRUCTURED_OUTPUT = "structured_output"
    REASONING = "reasoning"
    EMBEDDINGS = "embeddings"


@dataclass(frozen=True)
class ModelRef:
    """Provider-qualified model identity. Credentials are never part of this value."""

    provider: str
    model: str


@dataclass(frozen=True)
class ModelDescriptor:
    """Safe catalog entry exposed to clients. No keys, endpoints, or secrets."""

    provider: str
    model: str
    display_name: str
    capabilities: tuple[ModelCapability, ...] = (ModelCapability.CHAT,)
    available: bool = False
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None

    @property
    def ref(self) -> ModelRef:
        return ModelRef(provider=self.provider, model=self.model)


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
    """Normalized LLM response. Vendor SDK objects must not leak past adapters."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    model: str | None = None
    provider: str | None = None
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
    provider: str | None = None
    model: str | None = None


@dataclass
class ModelRequest:
    """Provider-agnostic generate/stream request."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    provider: str | None = None
    model: str | None = None
    stream: bool = False


@runtime_checkable
class ModelGateway(Protocol):
    """Single application LLM boundary. Runtime must not branch on provider identity."""

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Generate a response, optionally binding tools.

        Optional kwargs: provider, model. Selection is authorized by the catalog.
        """
        ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ModelStreamChunk]:
        """Stream normalized chunks. Same contract as generate()."""
        ...
