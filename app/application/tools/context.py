"""Tool execution context passed explicitly to tool handlers."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.domain.models.execution_context import IDENTITY_METADATA_KEYS, ExecutionContext
from app.domain.models.workspace import Workspace


def auxiliary_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Copy metadata with trusted identity keys removed.

    Identity must come from ExecutionContext, never from model- or tool-supplied
    metadata dictionaries.
    """
    if not metadata:
        return {}
    return {key: value for key, value in metadata.items() if key not in IDENTITY_METADATA_KEYS}


@dataclass
class ToolExecutionContext:
    """Narrow execution-scoped projection of trusted ExecutionContext.

    Carries runtime metadata, workspace boundaries, and cancellation tokens
    without relying on global state. Trusted identity is owned by `execution`
    when present; metadata is auxiliary only.
    """

    run_id: str
    tool_call_id: str
    workspace: Workspace
    cancellation_token: asyncio.Event | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    execution: ExecutionContext | None = None

    def __post_init__(self) -> None:
        self.metadata = auxiliary_metadata(self.metadata)
        if self.execution is not None:
            self.user_id = self.execution.user_id_str
            self.run_id = self.execution.run_id

    @classmethod
    def from_execution(
        cls,
        execution: ExecutionContext,
        *,
        tool_call_id: str,
        workspace: Workspace,
        cancellation_token: asyncio.Event | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolExecutionContext":
        """Project a trusted ExecutionContext into a tool-scoped context."""
        return cls(
            run_id=execution.run_id,
            tool_call_id=tool_call_id,
            workspace=workspace,
            cancellation_token=cancellation_token,
            user_id=execution.user_id_str,
            metadata=auxiliary_metadata(metadata),
            execution=execution,
        )

    @property
    def project_id(self) -> str | None:
        """Trusted project identity. Never read from metadata or tool arguments."""
        if self.execution is None:
            return None
        return self.execution.project_id_str

    @property
    def workspace_id(self) -> str | None:
        if self.execution is not None:
            return self.execution.workspace_id
        return self.workspace.workspace_id

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self.cancellation_token.is_set() if self.cancellation_token is not None else False
