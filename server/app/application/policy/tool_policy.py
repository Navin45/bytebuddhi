"""Tool authorization engine and policy boundary."""

from typing import Any

from app.application.policy.command_policy import CommandPolicy
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import RiskLevel, ToolCall
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class ToolPolicyEngine:
    """Policy engine enforcing authorization across all tool invocations."""

    def __init__(
        self,
        command_policy: CommandPolicy | None = None,
        registry: Any | None = None,
    ):
        self.command_policy = command_policy or CommandPolicy()
        self.registry = registry

    async def authorize_tool_call(
        self,
        tool_call: ToolCall,
        context: ToolExecutionContext | None = None,
    ) -> tuple[bool, str | None]:
        """Authorize a tool call before execution.

        Args:
            tool_call: Requested tool invocation.
            context: Optional execution context carrying workspace and run metadata.

        Returns:
            tuple[bool, Optional[str]]: (is_authorized, denial_reason)
        """
        # 1. Check approval requirement for high-risk or approval-gated capabilities
        if self.registry is not None:
            tool_entry = self.registry.get(tool_call.name) or self.registry.get_by_id(tool_call.name)
            if tool_entry:
                tool_def, _ = tool_entry
                if (
                    getattr(tool_def, "requires_approval", False)
                    or getattr(tool_def, "risk_level", None) == RiskLevel.HIGH
                ):
                    approved = False
                    if context is not None and context.metadata:
                        approved_actions = context.metadata.get("approved_actions", [])
                        if isinstance(approved_actions, (list, set, tuple)) and (
                            tool_call.name in approved_actions
                            or tool_def.id in approved_actions
                            or "*" in approved_actions
                        ):
                            approved = True
                        if context.metadata.get("approval_granted") is True:
                            approved = True

                    if not approved:
                        risk_val = (
                            tool_def.risk_level.value
                            if hasattr(tool_def.risk_level, "value")
                            else str(tool_def.risk_level)
                        )
                        return False, (
                            f"Action '{tool_call.name}' requires explicit approval before execution "
                            f"(risk tier: {risk_val})"
                        )
        # 1. Command execution policy
        if tool_call.name == "run_command":
            raw_command = tool_call.arguments.get("command") or tool_call.arguments.get("command_str")
            if not raw_command:
                return False, "Missing command argument for run_command tool"

            allowed, risk, reason = self.command_policy.validate_command(raw_command)
            if not allowed:
                return False, reason or f"Command rejected with risk tier: {risk.value}"

            # Check cwd if specified
            if context is not None and "cwd" in tool_call.arguments:
                cwd_arg = tool_call.arguments["cwd"]
                if cwd_arg and not context.workspace.is_safe_path(cwd_arg):
                    return False, f"Working directory '{cwd_arg}' resolves outside workspace boundary"

            return True, None

        # 2. Filesystem tools boundary check
        if tool_call.name in {"read_file", "write_file", "create_directory", "list_directory"}:
            path_arg = tool_call.arguments.get("path")
            if path_arg and context is not None and not context.workspace.is_safe_path(path_arg):
                return False, f"Target path '{path_arg}' resolves outside workspace boundary"

        return True, None
