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
    }
)


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

    @property
    def user_id_str(self) -> str:
        return str(self.user_id)

    @property
    def project_id_str(self) -> str | None:
        return _optional_id(self.project_id)

    @property
    def conversation_id_str(self) -> str | None:
        return _optional_id(self.conversation_id)

    def with_conversation_id(self, conversation_id: UUID | str | None) -> "ExecutionContext":
        """Return a copy with a server-assigned conversation id."""
        return replace(self, conversation_id=conversation_id)

    def derive_child(self, child_run_id: str) -> "ExecutionContext":
        """Derive a child execution identity from this parent.

        Child runs receive a new run_id. Trusted caller identity is copied
        immutably and cannot be reconstructed from untrusted metadata.
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
        )
