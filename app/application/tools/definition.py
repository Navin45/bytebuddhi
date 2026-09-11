"""Tool definitions and unified capability models for ByteBuddhi."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CapabilityType(StrEnum):
    """Origin/type of the capability."""

    NATIVE = "native"
    CONNECTOR = "connector"
    MCP = "mcp"


class RiskLevel(StrEnum):
    """Risk tier for capability invocation and policy gating."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ToolDefinition:
    """Unified definition of an agent capability/tool.

    Elevated to serve as the unified capability model for native tools,
    external connectors, and MCP capabilities.
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}, "required": []})
    id: str | None = None
    capability_type: CapabilityType = CapabilityType.NATIVE
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"{self.capability_type.value}.{self.name}"

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert definition to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        """Convert definition to Anthropic tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


# Canonical alias ensuring unified capability abstraction
Capability = ToolDefinition


@dataclass
class ToolCall:
    """A tool invocation requested by a model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """The result of executing a tool."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False
    error_details: dict[str, Any] | None = None

    def to_message_dict(self) -> dict[str, Any]:
        """Convert result to model message format."""
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "content": self.content,
        }
