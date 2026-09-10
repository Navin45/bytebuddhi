"""Builtin command execution tool."""

from typing import Any

from app.application.execution.command_executor import CommandExecutor
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolDefinition


def create_command_tool(
    command_executor: CommandExecutor,
) -> tuple[ToolDefinition, Any]:
    """Create and return the run_command ToolDefinition and handler."""

    async def run_command_handler(
        command: list[str] | None = None,
        command_str: str | None = None,
        cwd: str | None = None,
        timeout: int = 30,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        result = await command_executor.execute(
            command=command,
            command_str=command_str,
            cwd=cwd,
            timeout=float(timeout),
            context=context,
        )

        return {
            "execution_id": result.execution_id,
            "exit_code": result.exit_code,
            "status": result.status.value,
            "duration_seconds": result.duration_seconds,
            "stdout": result.stdout_preview,
            "stderr": result.stderr_preview,
            "stdout_ref": result.stdout_ref,
            "stderr_ref": result.stderr_ref,
            "is_truncated": result.is_truncated,
        }

    definition = ToolDefinition(
        name="run_command",
        description=(
            "Execute an OS command inside the workspace. "
            "Prefers command as an argument list (e.g. ['git', 'status']) over shell strings."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command and arguments as a list (e.g. ['git', 'status']). Preferred.",
                },
                "command_str": {
                    "type": "string",
                    "description": "Shell command string (subject to high-risk validation).",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory relative to workspace root (defaults to workspace root).",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30).",
                },
            },
            "required": [],
        },
    )

    return definition, run_command_handler
