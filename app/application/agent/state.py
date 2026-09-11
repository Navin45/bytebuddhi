"""Agent state definitions for ByteBuddhi Agent Runtime."""

from dataclasses import dataclass, field
from typing import Any, TypedDict

from app.application.agent.errors import AgentError, AgentErrorCode
from app.application.agent.types import AgentStatus
from app.application.tools.definition import ToolCall, ToolResult
from app.domain.models.agent import TokenUsage


class AgentLoopState(TypedDict):
    """LangGraph-facing state dictionary for the inner agent execution loop.

    Tracks conversation turns, tool invocations, iterations, and terminal results.
    """

    run_id: str
    messages: list[dict[str, Any]]
    status: str
    iteration: int
    max_iterations: int
    pending_tool_calls: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    final_response: str | None
    error: dict[str, Any] | None
    metadata: dict[str, Any]


@dataclass
class AgentRunState:
    """Rich domain representation of an agent run's complete state."""

    run_id: str
    status: AgentStatus = AgentStatus.IDLE
    messages: list[dict[str, Any]] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 10
    final_response: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    error: AgentError | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    token_usage: TokenUsage = field(default_factory=TokenUsage)

    @classmethod
    def from_loop_state(cls, state: dict[str, Any]) -> "AgentRunState":
        """Convert a LangGraph loop state dict to a typed AgentRunState."""
        status_val = state.get("status", AgentStatus.IDLE.value)
        try:
            status = AgentStatus(status_val)
        except ValueError:
            status = AgentStatus.IDLE

        error_dict = state.get("error")
        agent_error: AgentError | None = None
        if error_dict and isinstance(error_dict, dict):
            code_str = error_dict.get("code", AgentErrorCode.INTERNAL_ERROR.value)
            try:
                code = AgentErrorCode(code_str)
            except ValueError:
                code = AgentErrorCode.INTERNAL_ERROR
            agent_error = AgentError(
                code=code,
                message=error_dict.get("message", "Unknown error"),
                details=error_dict.get("details", {}),
                is_retryable=error_dict.get("is_retryable", False),
            )

        tool_calls: list[ToolCall] = []
        raw_tool_calls = state.get("tool_calls") or state.get("pending_tool_calls", [])
        for tc in raw_tool_calls:
            tool_calls.append(
                ToolCall(
                    id=str(tc.get("id", "")),
                    name=str(tc.get("name", "")),
                    arguments=tc.get("arguments", {}),
                )
            )

        tool_results: list[ToolResult] = []
        for tr in state.get("tool_results", []):
            tool_results.append(
                ToolResult(
                    tool_call_id=str(tr.get("tool_call_id", "")),
                    name=str(tr.get("name", "")),
                    content=str(tr.get("content", "")),
                    is_error=bool(tr.get("is_error", False)),
                )
            )

        raw_usage = state.get("token_usage") or state.get("metadata", {}).get("token_usage")
        if isinstance(raw_usage, TokenUsage):
            usage = raw_usage
        elif isinstance(raw_usage, dict):
            usage = TokenUsage(
                prompt_tokens=raw_usage.get("prompt_tokens", 0),
                completion_tokens=raw_usage.get("completion_tokens", 0),
                total_tokens=raw_usage.get("total_tokens", 0),
            )
        else:
            usage = TokenUsage()

        return cls(
            run_id=state.get("run_id", ""),
            status=status,
            messages=state.get("messages", []),
            iteration=state.get("iteration", 0),
            max_iterations=state.get("max_iterations", 10),
            final_response=state.get("final_response"),
            tool_calls=tool_calls,
            tool_results=tool_results,
            error=agent_error,
            metadata=state.get("metadata", {}),
            token_usage=usage,
        )
