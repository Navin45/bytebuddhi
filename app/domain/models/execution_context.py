"""Trusted execution context domain model."""

from dataclasses import dataclass, replace
from uuid import UUID

IDENTITY_METADATA_KEYS = frozenset(
    {
        "user_id",
        "project_id",
        "conversation_id",
        "workspace_id",
        "run_id",
        "parent_run_id",
        "child_run_id",
        "delegation_depth",
        "agent_id",
    }
)

AUTHORIZATION_METADATA_KEYS = frozenset(
    {
        "approval_granted",
        "approved_actions",
        "can_delegate",
        "role",
    }
)

STRIPPED_METADATA_KEYS = IDENTITY_METADATA_KEYS | AUTHORIZATION_METADATA_KEYS


def _optional_id(value: UUID | str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


@dataclass(frozen=True)
class ExecutionContext:
    """Immutable execution context carrying trusted identity and authorization metadata.

    Security & Boundary Invariants:
        1. Immutable: Instances cannot be modified after creation.
        2. Authoritative: Created only by server-side authorization and resolution services.
        3. Tamper-Proof: Model, client, or tool parameters can never override these values.
    """

    user_id: UUID | str
    project_id: UUID | str | None
    conversation_id: UUID | str | None
    run_id: str
    workspace_id: str
    parent_run_id: str | None = None
    child_run_id: str | None = None
    delegation_depth: int = 0
    approved_actions: tuple[str, ...] = ()
    agent_id: str | None = None

    @property
    def user_id_str(self) -> str:
        return str(self.user_id)

    @property
    def project_id_str(self) -> str | None:
        return _optional_id(self.project_id)

    @property
    def conversation_id_str(self) -> str | None:
        return _optional_id(self.conversation_id)

    @property
    def artifact_scope_id(self) -> str:
        """Namespace for execution-scoped artifacts. Never falls back to a global bucket."""
        return self.project_id_str or f"user_{self.user_id_str}"

    def with_conversation_id(self, conversation_id: UUID | str | None) -> "ExecutionContext":
        """Return a copy with a server-assigned conversation id."""
        return replace(self, conversation_id=conversation_id)

    def with_approvals(self, approved_actions: tuple[str, ...] | list[str]) -> "ExecutionContext":
        """Return a copy with server-issued capability approvals. Never copied to children."""
        return replace(self, approved_actions=tuple(approved_actions))

    def derive_child(self, child_run_id: str, *, agent_id: str | None = None) -> "ExecutionContext":
        """Derive a child execution identity from this parent.

        Child runs receive a new run_id. Trusted caller identity is copied
        immutably and cannot be reconstructed from untrusted metadata.
        Parent approvals are not inherited.
        """
        if not child_run_id.strip():
            raise ValueError("Child run identity must be non-empty")
        if child_run_id == self.run_id:
            raise ValueError("Child run identity must be unique")
        return ExecutionContext(
            user_id=self.user_id,
            project_id=self.project_id,
            conversation_id=self.conversation_id,
            run_id=child_run_id,
            workspace_id=self.workspace_id,
            parent_run_id=self.run_id,
            child_run_id=child_run_id,
            delegation_depth=self.delegation_depth + 1,
            approved_actions=(),
            agent_id=agent_id,
        )
