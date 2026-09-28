"""Application run and event records. These are not ORM models."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from app.application.runs.status import RunStatus

SCHEMA_VERSION = 1
MAX_EVENT_TEXT = 4000
EVENT_PAGE_LIMIT = 200


@dataclass
class RunRecord:
    id: str
    user_id: UUID
    project_id: UUID | None
    conversation_id: UUID | None
    status: RunStatus
    prompt: str
    prompt_sha256: str
    provider: str | None = None
    model: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    cancellation_requested: bool = False
    event_sequence: int = 0
    idempotency_key: str | None = None
    worker_id: str | None = None
    execution_attempt: int = 0
    lease_token: str | None = None
    lease_acquired_at: datetime | None = None
    lease_expires_at: datetime | None = None

    def copy(self) -> RunRecord:
        return replace(self)


@dataclass(frozen=True)
class RunEventRecord:
    event_id: str
    run_id: str
    sequence: int
    event_type: str
    schema_version: int
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    def envelope(self) -> dict[str, Any]:
        created = self.created_at.isoformat() if self.created_at is not None else ""
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "type": self.event_type,
            "schema_version": self.schema_version,
            "created_at": created,
            "data": dict(self.payload),
        }


@dataclass(frozen=True)
class EventPage:
    events: tuple[RunEventRecord, ...]
    next_sequence: int
    has_more: bool
