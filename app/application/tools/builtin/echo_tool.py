"""Built-in deterministic echo tool for contract verification."""

from app.application.tools.definition import ToolDefinition
from app.application.tools.registry import ToolRegistry


def echo_handler(message: str) -> str:
    """Deterministic echo handler that returns input message."""
    return f"echo: {message}"


def create_echo_tool_definition() -> ToolDefinition:
    """Create the ToolDefinition for the echo tool."""
    return ToolDefinition(
        name="echo",
        description="Echo back an input message. Used to verify tool calling capabilities.",
        parameters={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The text message to echo back",
                }
            },
            "required": ["message"],
        },
    )


def register_echo_tool(registry: ToolRegistry) -> None:
    """Register the echo tool in a tool registry."""
    registry.register(create_echo_tool_definition(), echo_handler)
