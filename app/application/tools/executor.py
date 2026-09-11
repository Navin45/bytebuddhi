import asyncio
import inspect
import json
import time
from typing import Any, cast
from uuid import uuid4

from app.application.policy.tool_policy import ToolPolicyEngine
from app.application.ports.output.logger import get_logger
from app.application.ports.output.observability.meter import Meter
from app.application.ports.output.observability.noop import NoOpMeter, NoOpTracer
from app.application.ports.output.observability.tracer import SpanStatus, Tracer
from app.application.ports.output.storage.artifact_store import ArtifactStore
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall, ToolResult
from app.application.tools.registry import ToolRegistry
from app.domain.models.observability import MetricNames, SpanAttributes, SpanNames

logger = get_logger(__name__)


class ToolExecutor:
    """Executes tool calls using registered handlers with context injection and policy validation."""

    def __init__(
        self,
        registry: ToolRegistry,
        policy_engine: ToolPolicyEngine | None = None,
        artifact_store: ArtifactStore | None = None,
        max_output_chars: int = 6000,
        tracer: Tracer | None = None,
        meter: Meter | None = None,
    ):
        self.registry = registry
        self.policy_engine = policy_engine
        self.artifact_store = artifact_store
        self.max_output_chars = max_output_chars
        self.tracer = tracer or NoOpTracer()
        self.meter = meter or NoOpMeter()

        # Telemetry instruments
        self._tool_calls_counter = self.meter.create_counter(MetricNames.TOOL_CALLS_TOTAL)
        self._tool_failures_counter = self.meter.create_counter(MetricNames.TOOL_FAILURES_TOTAL)
        self._tool_duration_hist = self.meter.create_histogram(MetricNames.TOOL_DURATION, unit="ms")

    async def execute(
        self,
        tool_call: ToolCall,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        """Execute a single tool call safely with optional execution context and telemetry."""
        start_time = time.perf_counter()
        tool_entry = self.registry.get(tool_call.name)
        tool_def = tool_entry[0] if tool_entry else None

        parent_span = self.tracer.get_current_span()
        span_attrs: dict[str, Any] = {
            SpanAttributes.TOOL_NAME: tool_call.name,
            SpanAttributes.TOOL_ID: tool_call.id,
        }
        if tool_def:
            risk = getattr(tool_def, "risk_level", None)
            if risk is not None:
                span_attrs[SpanAttributes.TOOL_RISK] = risk.value
            span_attrs[SpanAttributes.TOOL_APPROVAL_REQUIRED] = getattr(tool_def, "requires_approval", False)

        with self.tracer.start_as_current_span(
            SpanNames.TOOL_EXECUTE,
            parent=parent_span,
            attributes=span_attrs,
        ) as span:
            self._tool_calls_counter.add(1, {"tool_name": tool_call.name})
            try:
                res = await self._execute_internal(tool_call, context=context, tool_entry=tool_entry)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                self._tool_duration_hist.record(duration_ms, {"tool_name": tool_call.name})
                if res.is_error:
                    self._tool_failures_counter.add(1, {"tool_name": tool_call.name})
                    span.set_status(SpanStatus.ERROR, description=str(res.content)[:200])
                else:
                    span.set_status(SpanStatus.OK)
                return res
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                self._tool_duration_hist.record(duration_ms, {"tool_name": tool_call.name})
                self._tool_failures_counter.add(1, {"tool_name": tool_call.name})
                span.record_exception(e)
                span.set_status(SpanStatus.ERROR, description=str(e))
                raise

    async def _execute_internal(
        self,
        tool_call: ToolCall,
        context: ToolExecutionContext | None = None,
        tool_entry: Any | None = None,
    ) -> ToolResult:
        # Pre-execution cancellation check
        if context is not None and context.is_cancelled:
            logger.info("Tool execution cancelled before start", tool_name=tool_call.name, tool_call_id=tool_call.id)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Execution cancelled for tool '{tool_call.name}'",
                is_error=True,
                error_details={"error": "CancelledError", "reason": "Operation cancelled by caller"},
            )
        entry = tool_entry or self.registry.get(tool_call.name)
        if not entry:
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
                auth_res = self.policy_engine.authorize_tool_call(tool_call, context)
                if inspect.isawaitable(auth_res):
                    allowed, reason = await auth_res
                else:
                    allowed, reason = cast(tuple[bool, str | None], auth_res)

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

        _, handler = entry
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

            # Post-execution cancellation check
            if context is not None and context.is_cancelled:
                logger.info(
                    "Tool execution cancelled after completion",
                    tool_name=tool_call.name,
                    tool_call_id=tool_call.id,
                )
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=f"Execution cancelled for tool '{tool_call.name}'",
                    is_error=True,
                    error_details={"error": "CancelledError", "reason": "Operation cancelled by caller"},
                )

            # Output bounding and large payload archiving
            if len(content) > self.max_output_chars:
                if self.artifact_store is not None:
                    try:
                        artifact_id = f"tool_out_{tool_call.id or uuid4().hex[:8]}"
                        if context is None or context.execution is None:
                            return ToolResult(
                                tool_call_id=tool_call.id,
                                name=tool_call.name,
                                content=(
                                    "Execution-scoped artifacts require a trusted ExecutionContext; "
                                    "refusing to archive into a global namespace"
                                ),
                                is_error=True,
                                error_details={"error": "ExecutionContextRequired"},
                            )
                        project_id = context.artifact_scope_id
                        ref = await self.artifact_store.save_artifact(
                            artifact_id=artifact_id,
                            content=content,
                            metadata={
                                "tool_name": tool_call.name,
                                "tool_call_id": tool_call.id,
                                "run_id": context.run_id if context else None,
                            },
                            project_id=project_id,
                        )
                        content = (
                            f"{content[:500]}\n\n"
                            f"[Large output archived to artifact '{ref}'. Full size: {len(content)} characters]"
                        )
                    except Exception as ae:
                        logger.warning("Failed to archive large tool output to ArtifactStore", error=str(ae))
                        content = f"{content[: self.max_output_chars]}\n\n[Output truncated at {self.max_output_chars} characters]"
                else:
                    content = f"{content[: self.max_output_chars]}\n\n[Output truncated at {self.max_output_chars} characters]"

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
