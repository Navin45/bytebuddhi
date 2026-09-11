"""Tool execution context passed explicitly to tool handlers."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.domain.models.workspace import Workspace


@dataclass
class ToolExecutionContext:
    """Execution context injected into tool invocations.

    Carries runtime metadata, workspace boundaries, and cancellation tokens
    without relying on global state.
    """

    run_id: str
    tool_call_id: str
    workspace: Workspace
    cancellation_token: asyncio.Event | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self.cancellation_token.is_set() if self.cancellation_token is not None else False
