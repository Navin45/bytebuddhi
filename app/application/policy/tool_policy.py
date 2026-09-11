"""Tool authorization engine and policy boundary."""

import contextlib
from typing import Any

from app.application.policy.command_policy import CommandPolicy
from app.application.ports.output.observability.meter import Counter, Meter
from app.application.ports.output.observability.tracer import Tracer
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import RiskLevel, ToolCall
from app.domain.models.observability import MetricNames, SpanAttributes, SpanNames
from app.infrastructure.config.logger import get_logger
from app.infrastructure.observability.noop import NoOpMeter, NoOpTracer

logger = get_logger(__name__)


class ToolPolicyEngine:
    """Policy engine enforcing authorization across all tool invocations."""

    def __init__(
        self,
        command_policy: CommandPolicy | None = None,
        registry: Any | None = None,
        tracer: Tracer | None = None,
        meter: Meter | None = None,
    ):
        self.command_policy = command_policy or CommandPolicy()
        self.registry = registry
        self.tracer = tracer or NoOpTracer()
        self.meter = meter or NoOpMeter()
        self._denials_counter: Counter = self.meter.create_counter(
            MetricNames.TOOL_DENIALS_TOTAL,
            unit="1",
            description="Total number of tool calls denied by policy",
        )

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
        with self.tracer.start_as_current_span(
            SpanNames.TOOL_POLICY,
            attributes={
                SpanAttributes.TOOL_NAME: tool_call.name[:50],
            },
        ) as span:
            is_authorized, denial_reason = await self._evaluate_authorization(tool_call, context)
            span.set_attribute(
                SpanAttributes.POLICY_DECISION,
                "allow" if is_authorized else "deny",
            )
            if not is_authorized:
                if denial_reason:
                    span.set_attribute(SpanAttributes.DENIAL_REASON, denial_reason[:200])
                with contextlib.suppress(Exception):
                    self._denials_counter.add(1, {"tool_name": tool_call.name[:50]})
            return is_authorized, denial_reason

    async def _evaluate_authorization(
        self,
        tool_call: ToolCall,
        context: ToolExecutionContext | None = None,
    ) -> tuple[bool, str | None]:
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

        return True, None
