"""Structured error models for ByteBuddhi Agent Runtime."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentErrorCode(StrEnum):
    """Enumeration of structured agent error codes."""

    VALIDATION_ERROR = "validation_error"
    MODEL_ERROR = "model_error"
    TOOL_ERROR = "tool_error"
    TOOL_NOT_FOUND = "tool_not_found"
    ITERATION_LIMIT = "iteration_limit_exceeded"
    CONTEXT_OVERFLOW = "context_overflow"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


@dataclass
class AgentError(Exception):
    """Base structured error for agent runtime operations."""

    code: AgentErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    is_retryable: bool = False
    cause: Exception | None = None

    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize error for user messaging or telemetry."""
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
            "is_retryable": self.is_retryable,
        }


class ModelSelectionError(AgentError):
    """Raised when a requested model is not registered, enabled, or available."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(
            code=AgentErrorCode.VALIDATION_ERROR,
            message=message,
            details=details or {},
            is_retryable=False,
            cause=cause,
        )


class ModelCallError(AgentError):
    """Raised when an LLM provider call fails."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        is_retryable: bool = True,
        cause: Exception | None = None,
    ):
        super().__init__(
            code=AgentErrorCode.MODEL_ERROR,
            message=message,
            details=details or {},
            is_retryable=is_retryable,
            cause=cause,
        )


class ToolExecutionError(AgentError):
    """Raised when a tool execution fails."""

    def __init__(
        self,
        tool_name: str,
        message: str,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        d = details or {}
        d["tool_name"] = tool_name
        super().__init__(
            code=AgentErrorCode.TOOL_ERROR,
            message=f"Tool '{tool_name}' failed: {message}",
            details=d,
            is_retryable=False,
            cause=cause,
        )


class ToolNotFoundError(AgentError):
    """Raised when an agent attempts to call an unregistered tool."""

    def __init__(self, tool_name: str):
        super().__init__(
            code=AgentErrorCode.TOOL_NOT_FOUND,
            message=f"Tool '{tool_name}' is not registered in ToolRegistry",
            details={"tool_name": tool_name},
            is_retryable=False,
        )


class IterationLimitExceededError(AgentError):
    """Raised when the agent loop exceeds maximum allowed iterations."""

    def __init__(self, iterations: int, max_iterations: int):
        super().__init__(
            code=AgentErrorCode.ITERATION_LIMIT,
            message=f"Agent exceeded maximum iterations ({iterations}/{max_iterations})",
            details={"iterations": iterations, "max_iterations": max_iterations},
            is_retryable=False,
        )


class AgentCancelledError(AgentError):
    """Raised when an agent run is cancelled."""

    def __init__(self, reason: str = "Execution cancelled"):
        super().__init__(
            code=AgentErrorCode.CANCELLED,
            message=reason,
            details={"reason": reason},
            is_retryable=False,
        )
