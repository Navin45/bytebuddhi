"""Shared types for the ByteBuddhi Agent Runtime."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.domain.models.agent import TokenUsage

__all__ = ["AgentMessage", "AgentStatus", "TokenUsage"]


class AgentStatus(StrEnum):
    """Execution status of an agent run."""

    IDLE = "idle"
    RUNNING = "running"
    WAITING_FOR_TOOL = "waiting_for_tool"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentMessage:
    """A message in the agent conversation/runtime context."""

    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize message to dictionary."""
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        if self.metadata:
            d["metadata"] = self.metadata
        return d
