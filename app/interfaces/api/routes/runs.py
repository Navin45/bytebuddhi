"""Async run transport. The route queues work and does not execute the agent."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, status

from app.application.ports.output.repository.conversation_repository import ConversationRepository
from app.application.ports.output.repository.user_repository import UserRepository
from app.application.runs.coordinator import RunCoordinator
from app.application.runs.errors import RunError
from app.application.runs.records import RunRecord
from app.application.runtime.admission import ConcurrentRunLimitExceeded
from app.domain.exceptions.project_exceptions import ProjectNotFoundException, ProjectOwnershipException
from app.domain.models.user import User
from app.infrastructure.auth.jwt_handler import jwt_handler
from app.infrastructure.config.logger import get_logger
from app.interfaces.api.dependencies import (
    get_conversation_repository,
    get_user_repository,
    get_workspace_resolution_service,
)
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.run_runtime import get_run_coordinator
from app.interfaces.api.run_stream import serve_run_stream
from app.interfaces.api.schemas.run_schema import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    CancelRunResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunEvent,
    RunEventPage,
    RunResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/runs", tags=["Runs"])


async def get_websocket_user(
    websocket: WebSocket,
    user_repo: UserRepository = Depends(get_user_repository),
) -> User | None:
    """Same access token as REST. The header is not logged."""
    header = websocket.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    if not token:
        return None
    user_id = jwt_handler.verify_token(token, token_type="access")
    if user_id is None:
        return None
    user = await user_repo.get_by_id(user_id)
    if user is None or not user.is_active:
        return None
    return user


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=RunCreateResponse)
async def create_run(
    request: RunCreateRequest,
    current_user: User = Depends(get_current_user),
    coordinator: RunCoordinator = Depends(get_run_coordinator),
    conversation_repo: ConversationRepository = Depends(get_conversation_repository),
    workspace: Any = Depends(get_workspace_resolution_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunCreateResponse:
    """Queue a run for the authenticated user and return before execution finishes."""
    project_id = await _authorized_project_id(request, current_user, conversation_repo)
    try:
        await workspace.resolve_workspace(current_user.id, project_id)
    except ProjectOwnershipException as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this project"
        ) from exc
    except ProjectNotFoundException as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from exc
    provider = request.model.provider if request.model else None
    model_name = request.model.model if request.model else None
    try:
        record = await coordinator.create_run(
            user_id=current_user.id,
            prompt=request.prompt,
            project_id=project_id,
            conversation_id=request.conversation_id,
            provider=provider,
            model=model_name,
            idempotency_key=_clean_key(idempotency_key),
        )
    except RunError as exc:
        raise _http_error(exc) from exc
    except ConcurrentRunLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many concurrent runs") from exc
    return _accepted(record)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    coordinator: RunCoordinator = Depends(get_run_coordinator),
) -> RunResponse:
    try:
        record = await coordinator.get_run(run_id, current_user.id)
    except RunError as exc:
        raise _http_error(exc) from exc
    return _run_response(record)


@router.get("/{run_id}/events", response_model=RunEventPage)
async def list_run_events(
    run_id: str,
    after_sequence: int = Query(default=0),
    limit: int = Query(default=200, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    coordinator: RunCoordinator = Depends(get_run_coordinator),
) -> RunEventPage:
    try:
        page = await coordinator.list_events(
            run_id,
            current_user.id,
            after_sequence=after_sequence,
            limit=limit,
        )
    except RunError as exc:
        raise _http_error(exc) from exc
    return RunEventPage(
        events=[RunEvent.model_validate(event.envelope()) for event in page.events],
        next_sequence=page.next_sequence,
        has_more=page.has_more,
    )


@router.post("/{run_id}/cancel", response_model=CancelRunResponse)
async def cancel_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    coordinator: RunCoordinator = Depends(get_run_coordinator),
) -> CancelRunResponse:
    try:
        record = await coordinator.cancel(run_id, current_user.id)
    except RunError as exc:
        raise _http_error(exc) from exc
    return CancelRunResponse(run_id=record.id, status=record.status.value)


@router.post("/{run_id}/approval", response_model=ApprovalDecisionResponse)
async def decide_approval(
    run_id: str,
    request: ApprovalDecisionRequest,
    current_user: User = Depends(get_current_user),
    coordinator: RunCoordinator = Depends(get_run_coordinator),
) -> ApprovalDecisionResponse:
    try:
        resolved = await coordinator.resolve_approval(
            run_id=run_id,
            user_id=current_user.id,
            action=request.action,
            approved=(request.decision == "approved"),
        )
    except RunError as exc:
        raise _http_error(exc) from exc

    status_str = request.decision if resolved else "not_found"
    return ApprovalDecisionResponse(
        run_id=run_id,
        action=request.action,
        status=status_str,
    )


@router.websocket("/{run_id}/stream")
async def stream_run(
    websocket: WebSocket,
    run_id: str,
    after_sequence: int = Query(default=0),
    current_user: User | None = Depends(get_websocket_user),
    coordinator: RunCoordinator = Depends(get_run_coordinator),
) -> None:
    if current_user is None:
        await websocket.accept()
        await websocket.close(code=4401)
        return
    await serve_run_stream(
        websocket,
        coordinator,
        run_id=run_id,
        user_id=current_user.id,
        after_sequence=after_sequence,
    )


def _accepted(record: RunRecord) -> RunCreateResponse:
    return RunCreateResponse(
        run_id=record.id,
        conversation_id=str(record.conversation_id) if record.conversation_id else None,
        status=record.status.value,
    )


def _run_response(record: RunRecord) -> RunResponse:
    return RunResponse(
        run_id=record.id,
        conversation_id=str(record.conversation_id) if record.conversation_id else None,
        project_id=str(record.project_id) if record.project_id else None,
        status=record.status.value,
        error_code=record.error_code,
        error_message=record.error_message,
        created_at=record.created_at.isoformat() if record.created_at else None,
        started_at=record.started_at.isoformat() if record.started_at else None,
        completed_at=record.completed_at.isoformat() if record.completed_at else None,
    )


def _http_error(exc: RunError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail={"error_code": exc.code, "message": exc.message})


def _clean_key(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text or len(text) > 128:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid Idempotency-Key")
    return text


async def _authorized_project_id(
    request: RunCreateRequest,
    current_user: User,
    conversation_repo: ConversationRepository,
) -> UUID | None:
    project_id = request.project_id
    if request.conversation_id is None:
        return project_id
    conversation = await conversation_repo.get_by_id(request.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this conversation")
    if (
        request.project_id is not None
        and conversation.project_id is not None
        and request.project_id != conversation.project_id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="project_id does not match the conversation"
        )
    if conversation.project_id is not None:
        return conversation.project_id
    return project_id
