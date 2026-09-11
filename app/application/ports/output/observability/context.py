"""Correlation context management for tracing and lifecycle events across async boundaries."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CorrelationContext:
    """Immutable execution correlation context identifying a task across layers."""

    trace_id: str | None = None
    span_id: str | None = None
    run_id: str | None = None
    parent_run_id: str | None = None
    child_run_id: str | None = None
    agent_id: str | None = None
    agent_role: str | None = None
    task_id: str | None = None
    orchestration_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    delegation_depth: int | None = None

    def with_updates(self, **kwargs: Any) -> "CorrelationContext":
        """Create a new CorrelationContext with updated fields while preserving immutability."""
        current_data: dict[str, Any] = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "child_run_id": self.child_run_id,
            "agent_id": self.agent_id,
            "agent_role": self.agent_role,
            "task_id": self.task_id,
            "orchestration_id": self.orchestration_id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "delegation_depth": self.delegation_depth,
        }
        current_data.update(kwargs)
        return CorrelationContext(**current_data)

    def to_attributes(self) -> dict[str, Any]:
        """Export non-None identifiers as standard span/event attributes."""
        attrs: dict[str, Any] = {}
        if self.run_id:
            attrs["bytebuddhi.run.id"] = self.run_id
        if self.parent_run_id:
            attrs["bytebuddhi.parent_run.id"] = self.parent_run_id
        if self.child_run_id:
            attrs["bytebuddhi.child_run.id"] = self.child_run_id
        if self.agent_id:
            attrs["bytebuddhi.agent.id"] = self.agent_id
        if self.agent_role:
            attrs["bytebuddhi.agent.role"] = self.agent_role
        if self.task_id:
            attrs["bytebuddhi.task.id"] = self.task_id
        if self.orchestration_id:
            attrs["bytebuddhi.orchestration.id"] = self.orchestration_id
        if self.user_id:
            attrs["bytebuddhi.user.id"] = self.user_id
        if self.project_id:
            attrs["bytebuddhi.project.id"] = self.project_id
        if self.conversation_id:
            attrs["bytebuddhi.conversation.id"] = self.conversation_id
        if self.delegation_depth is not None:
            attrs["bytebuddhi.delegation.depth"] = self.delegation_depth
        return attrs


_CORRELATION_VAR: ContextVar[CorrelationContext | None] = ContextVar("bytebuddhi_correlation_context", default=None)


def get_correlation_context() -> CorrelationContext:
    """Retrieve the active correlation context for the current async task."""
    ctx = _CORRELATION_VAR.get()
    return ctx if ctx is not None else CorrelationContext()


def set_correlation_context(context: CorrelationContext) -> Token[CorrelationContext | None]:
    """Set the active correlation context for the current async task."""
    return _CORRELATION_VAR.set(context)


def reset_correlation_context(token: Token[CorrelationContext | None]) -> None:
    """Reset the correlation context back to a previous token state."""
    _CORRELATION_VAR.reset(token)


@contextmanager
def with_correlation_context(
    context: CorrelationContext | None = None,
    **kwargs: Any,
) -> Generator[CorrelationContext]:
    """Context manager for safely scoping correlation context to an async block."""
    if context is None:
        base = get_correlation_context()
        active_context = base.with_updates(**kwargs)
    else:
        active_context = context.with_updates(**kwargs) if kwargs else context

    token = set_correlation_context(active_context)
    try:
        yield active_context
    finally:
        reset_correlation_context(token)
