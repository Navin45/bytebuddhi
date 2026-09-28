"""Public run and event contracts. schema_version 1."""

from uuid import UUID

from pydantic import BaseModel, Field


class RunModelSelection(BaseModel):
    """Catalog selection. Either field may be omitted; the server resolves the rest."""

    provider: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)


class RunCreateRequest(BaseModel):
    """Queue one agent task. Identity comes from the bearer token."""

    prompt: str = Field(..., min_length=1, max_length=32000)
    project_id: UUID | None = Field(default=None)
    conversation_id: UUID | None = Field(default=None)
    model: RunModelSelection | None = Field(default=None)


class RunCreateResponse(BaseModel):
    """Accepted run. Execution continues after this response."""

    run_id: str
    conversation_id: str | None = None
    status: str


class RunResponse(BaseModel):
    """Durable run resource. The prompt is not returned."""

    run_id: str
    conversation_id: str | None = None
    project_id: str | None = None
    status: str
    error_code: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class RunEvent(BaseModel):
    """Stable event envelope. Payload fields live in data."""

    event_id: str
    run_id: str
    sequence: int
    type: str
    schema_version: int = 1
    created_at: str
    data: dict[str, object] = Field(default_factory=dict)


class RunEventPage(BaseModel):
    events: list[RunEvent]
    next_sequence: int
    has_more: bool


class CancelRunResponse(BaseModel):
    run_id: str
    status: str


class ApprovalDecisionRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=128)
    decision: str = Field(..., pattern="^(approved|rejected)$")


class ApprovalDecisionResponse(BaseModel):
    run_id: str
    action: str
    status: str
