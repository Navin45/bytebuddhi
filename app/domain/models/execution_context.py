"""Trusted execution context domain model."""

from dataclasses import dataclass
from uuid import UUID


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
