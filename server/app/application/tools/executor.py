"""Tool executor for executing model-invoked tool calls."""

import asyncio
import inspect
import json

from app.application.tools.definition import ToolCall, ToolResult
from app.application.tools.registry import ToolRegistry
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class ToolExecutor:
    """Executes tool calls using registered handlers."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool call safely.

        Args:
            tool_call: The tool call requested by the model.

        Returns:
            ToolResult containing execution output or error details.
        """
        tool_entry = self.registry.get(tool_call.name)
        if not tool_entry:
            logger.warning("Tool not found in registry", tool_name=tool_call.name)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Error: Tool '{tool_call.name}' is not registered.",
                is_error=True,
                error_details={"error": "ToolNotFoundError"},
            )

        _, handler = tool_entry
        logger.info("Executing tool", tool_name=tool_call.name, tool_call_id=tool_call.id)

        try:
            if inspect.iscoroutinefunction(handler):
                result_val = await handler(**tool_call.arguments)
            else:
                result_val = handler(**tool_call.arguments)

            if isinstance(result_val, (dict, list)):
                content = json.dumps(result_val)
            elif result_val is None:
                content = "Success"
            else:
                content = str(result_val)

            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=content,
                is_error=False,
            )

        except Exception as e:
            logger.error(
                "Tool execution error",
                tool_name=tool_call.name,
                tool_call_id=tool_call.id,
                error=str(e),
            )
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Error executing '{tool_call.name}': {e!s}",
                is_error=True,
                error_details={"exception": str(e), "type": type(e).__name__},
            )

    async def execute_all(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Execute a batch of tool calls concurrently."""
        return await asyncio.gather(*(self.execute(call) for call in tool_calls))
