"""Memory domain models and execution observations for ByteBuddhi."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class MemoryType(StrEnum):
    """Categorization of memory retention and durability."""

    WORKING = "working"
    LONG_TERM = "long_term"
    EXECUTION_OBSERVATION = "execution_observation"
    PROJECT = "project"
    USER_PREFERENCE = "user_preference"


class MemoryScope(StrEnum):
    """Access boundary and ownership scope for memory entries."""

    USER = "user"
    PROJECT = "project"
    CONVERSATION = "conversation"
    AGENT_RUN = "agent_run"


class InvalidMemoryScopeError(ValueError):
    """Raised when a MemoryItem is constructed with an invalid scope for its type."""

    pass


ALLOWED_SCOPES_BY_TYPE: dict[MemoryType, set[MemoryScope]] = {
    MemoryType.WORKING: {MemoryScope.AGENT_RUN, MemoryScope.CONVERSATION},
    MemoryType.EXECUTION_OBSERVATION: {MemoryScope.AGENT_RUN, MemoryScope.CONVERSATION},
    MemoryType.LONG_TERM: {MemoryScope.USER, MemoryScope.PROJECT},
    MemoryType.PROJECT: {MemoryScope.PROJECT},
    MemoryType.USER_PREFERENCE: {MemoryScope.USER},
}


@dataclass
class MemoryItem:
    """Core domain entity representing a classified, scoped memory item."""

    id: str
    scope: MemoryScope
    scope_id: str
    memory_type: MemoryType
    content: str
    source: str
    importance: float = 0.5
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.importance <= 1.0):
            raise ValueError(f"Importance must be between 0.0 and 1.0, got {self.importance}")
        if not self.content.strip():
            raise ValueError("Memory content cannot be empty")
        if not self.scope_id or not str(self.scope_id).strip():
            raise ValueError("Memory scope_id cannot be empty")

        allowed_scopes = ALLOWED_SCOPES_BY_TYPE.get(self.memory_type)
        if allowed_scopes is not None and self.scope not in allowed_scopes:
            allowed_names = ", ".join(sorted(s.value for s in allowed_scopes))
            raise InvalidMemoryScopeError(
                f"Invalid memory scope '{self.scope.value}' for type '{self.memory_type.value}'. "
                f"Allowed scopes: {allowed_names}"
            )

    @classmethod
    def create(
        cls,
        scope: MemoryScope,
        scope_id: str,
        memory_type: MemoryType,
        content: str,
        source: str = "system",
        importance: float = 0.5,
        expires_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
        memory_id: str | None = None,
    ) -> "MemoryItem":
        """Factory method creating a new MemoryItem with generated ID and timestamps."""
        now = datetime.now(UTC)
        return cls(
            id=memory_id or f"mem_{uuid4().hex[:12]}",
            scope=scope,
            scope_id=scope_id,
            memory_type=memory_type,
            content=content.strip(),
            source=source,
            importance=importance,
            created_at=now,
            updated_at=now,
            last_accessed_at=now,
            expires_at=expires_at,
            metadata=metadata or {},
            embedding=embedding,
        )

    def is_expired(self, current_time: datetime | None = None) -> bool:
        """Check if memory has passed its expiration time."""
        if self.expires_at is None:
            return False
        ref_time = current_time or datetime.now(UTC)
        return ref_time >= self.expires_at

    def touch(self) -> None:
        """Update last accessed timestamp."""
        self.last_accessed_at = datetime.now(UTC)


@dataclass
class ExecutionObservation:
    """Structured observation captured from tool or OS process execution."""

    observation_id: str
    run_id: str
    tool_name: str
    tool_call_id: str
    command: str | None = None
    exit_code: int | None = None
    summary: str = ""
    stdout_preview: str = ""
    stderr_preview: str = ""
    artifact_ref: str | None = None
    is_error: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        run_id: str,
        tool_name: str,
        tool_call_id: str,
        command: str | None = None,
        exit_code: int | None = None,
        summary: str = "",
        stdout_preview: str = "",
        stderr_preview: str = "",
        artifact_ref: str | None = None,
        is_error: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> "ExecutionObservation":
        """Factory constructor for an ExecutionObservation."""
        return cls(
            observation_id=f"obs_{uuid4().hex[:12]}",
            run_id=run_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            command=command,
            exit_code=exit_code,
            summary=summary,
            stdout_preview=stdout_preview,
            stderr_preview=stderr_preview,
            artifact_ref=artifact_ref,
            is_error=is_error,
            timestamp=datetime.now(UTC),
            metadata=metadata or {},
        )

    def to_memory_item(self, scope: MemoryScope = MemoryScope.AGENT_RUN) -> MemoryItem:
        """Convert this observation to a working memory item."""
        status_str = "failed" if self.is_error else "succeeded"
        desc = (
            f"Tool '{self.tool_name}' {status_str} (exit code {self.exit_code}). "
            f"Summary: {self.summary or 'No summary'}. "
        )
        if self.stdout_preview:
            desc += f"Output preview: {self.stdout_preview[:200]}..."
        if self.stderr_preview:
            desc += f"Error preview: {self.stderr_preview[:200]}..."

        meta = {
            **self.metadata,
            "observation_id": self.observation_id,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "exit_code": self.exit_code,
            "artifact_ref": self.artifact_ref,
            "is_error": self.is_error,
        }

        return MemoryItem.create(
            scope=scope,
            scope_id=self.run_id,
            memory_type=MemoryType.EXECUTION_OBSERVATION,
            content=desc,
            source=f"tool:{self.tool_name}",
            importance=0.6 if self.is_error else 0.4,
            metadata=meta,
        )
