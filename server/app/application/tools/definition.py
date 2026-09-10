"""Tool definitions and invocation models for ByteBuddhi."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDefinition:
    """Definition of an agent capability/tool."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}, "required": []})

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
