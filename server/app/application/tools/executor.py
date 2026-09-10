"""Tool executor for executing model-invoked tool calls with execution context and policy enforcement."""

import asyncio
import inspect
import json
from typing import Any

from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall, ToolResult
from app.application.tools.registry import ToolRegistry
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class ToolExecutor:
    """Executes tool calls using registered handlers with context injection and policy validation."""

    def __init__(
        self,
        registry: ToolRegistry,
        policy_engine: Any | None = None,
    ):
        self.registry = registry
        self.policy_engine = policy_engine

    async def execute(
        self,
        tool_call: ToolCall,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        """Execute a single tool call safely with optional execution context.

        Args:
            tool_call: The tool call requested by the model.
            context: Optional ToolExecutionContext carrying workspace and run metadata.

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

        # Policy boundary check before running tool handler
        if self.policy_engine is not None:
            try:
                if inspect.iscoroutinefunction(self.policy_engine.authorize_tool_call):
                    allowed, reason = await self.policy_engine.authorize_tool_call(tool_call, context)
                else:
                    allowed, reason = self.policy_engine.authorize_tool_call(tool_call, context)

                if not allowed:
                    logger.warning(
                        "Tool execution unauthorized by policy",
                        tool_name=tool_call.name,
                        tool_call_id=tool_call.id,
                        reason=reason,
                    )
                    return ToolResult(
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                        content=f"Policy authorization failed for tool '{tool_call.name}': {reason}",
                        is_error=True,
                        error_details={"error": "ToolAuthorizationError", "reason": reason},
                    )
            except Exception as pe:
                logger.error("Error evaluating tool policy", tool_name=tool_call.name, error=str(pe))
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=f"Policy evaluation error for tool '{tool_call.name}': {pe!s}",
                    is_error=True,
                    error_details={"error": "PolicyEvaluationError", "details": str(pe)},
                )

        _, handler = tool_entry
        logger.info("Executing tool", tool_name=tool_call.name, tool_call_id=tool_call.id)

        try:
            # Check if handler expects context parameter
            sig = inspect.signature(handler)
            call_kwargs = dict(tool_call.arguments)
            if "context" in sig.parameters and context is not None:
                call_kwargs["context"] = context

            if inspect.iscoroutinefunction(handler):
                result_val = await handler(**call_kwargs)
            else:
                result_val = handler(**call_kwargs)

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

    async def execute_all(
        self,
        tool_calls: list[ToolCall],
        context: ToolExecutionContext | None = None,
    ) -> list[ToolResult]:
        """Execute a batch of tool calls concurrently."""
        return await asyncio.gather(*(self.execute(call, context=context) for call in tool_calls))
