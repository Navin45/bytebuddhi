"""Tool registry for registering and discovering agent capabilities."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.application.tools.definition import ToolDefinition

ToolHandler = Callable[..., Awaitable[Any]] | Callable[..., Any]


class ToolRegistry:
    """Central registry of tools available to agents."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolDefinition, ToolHandler]] = {}

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
    ) -> None:
        """Register a tool with its handler.

        Args:
            definition: The tool definition including schema.
            handler: Callable function or coroutine implementing the tool.
        """
        self._tools[definition.name] = (definition, handler)

    def get(self, name: str) -> tuple[ToolDefinition, ToolHandler] | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def list_definitions(self) -> list[ToolDefinition]:
        """List all registered tool definitions."""
        return [defn for defn, _ in self._tools.values()]

    def get_schemas_for_openai(self) -> list[dict[str, Any]]:
        """Get tool schemas formatted for OpenAI function calling."""
        return [defn.to_openai_schema() for defn, _ in self._tools.values()]

    def get_schemas_for_anthropic(self) -> list[dict[str, Any]]:
        """Get tool schemas formatted for Anthropic tool use."""
        return [defn.to_anthropic_schema() for defn, _ in self._tools.values()]
