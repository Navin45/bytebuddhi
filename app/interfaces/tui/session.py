"""Gateway calls used by the TUI. No database, Redis, or agent runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.interfaces.api.schemas.chat_schema import ConversationResponse, MessageResponse
from app.interfaces.api.schemas.project_schema import ProjectResponse
from app.interfaces.api.schemas.run_schema import RunCreateResponse, RunEventPage
from app.interfaces.gateway.client import GatewayClient
from app.interfaces.gateway.errors import (
    AuthenticationRequired,
    AuthorizationDenied,
    GatewayError,
    GatewayServerError,
    GatewayTimeout,
    GatewayUnavailable,
    InvalidRequest,
    RateLimited,
    ResourceNotFound,
)
from app.interfaces.tui.state import ConversationRef, ModelRef, ProjectRef, TranscriptItem


@dataclass(frozen=True)
class LoadedWorkspace:
    projects: tuple[ProjectRef, ...]
    conversations: tuple[ConversationRef, ...]
    models: tuple[ModelRef, ...]
    default_provider: str
    default_model: str


def human_error(exc: GatewayError) -> str:
    if isinstance(exc, AuthenticationRequired):
        return "Session expired. Run `bytebuddhi login`."
    if isinstance(exc, AuthorizationDenied):
        return "You do not have access to this project."
    if isinstance(exc, ResourceNotFound):
        return "That conversation or project was not found."
    if isinstance(exc, RateLimited):
        return "Request rate limited. Please retry shortly."
    if isinstance(exc, InvalidRequest):
        return exc.message or "The gateway rejected the request."
    if isinstance(exc, GatewayTimeout):
        return "The gateway timed out."
    if isinstance(exc, GatewayUnavailable):
        return "Cannot connect to the ByteBuddhi gateway."
    if isinstance(exc, GatewayServerError):
        return "ByteBuddhi gateway returned an internal error."
    return exc.message or "The gateway request failed."


class GatewaySession:
    """One GatewayClient plus the read methods the stream controller needs."""

    def __init__(self, client: GatewayClient) -> None:
        self.client = client
        self._closed = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.client.aclose()

    async def load(self) -> LoadedWorkspace:
        projects = await self.client.list_projects()
        conversations = await self.client.list_conversations()
        catalog = await self.client.list_models()
        return LoadedWorkspace(
            projects=tuple(_project(item) for item in projects),
            conversations=tuple(_conversation(item) for item in conversations),
            models=tuple(_model(item.provider, item.model, item.display_name) for item in catalog.models),
            default_provider=catalog.default_provider,
            default_model=catalog.default_model,
        )

    async def list_messages(self, conversation_id: str) -> list[MessageResponse]:
        return await self.client.list_messages(UUID(conversation_id))

    async def create_conversation(self, *, project_id: str | None, title: str) -> ConversationResponse:
        return await self.client.create_conversation(
            project_id=UUID(project_id) if project_id else None,
            title=title,
        )

    async def create_run(
        self,
        *,
        prompt: str,
        project_id: str | None,
        conversation_id: str | None,
        model_provider: str | None,
        model_name: str | None,
        idempotency_key: str,
    ) -> RunCreateResponse:
        return await self.client.create_run(
            prompt=prompt,
            project_id=UUID(project_id) if project_id else None,
            conversation_id=UUID(conversation_id) if conversation_id else None,
            model_provider=model_provider,
            model_name=model_name,
            idempotency_key=idempotency_key,
        )

    async def cancel_run(self, run_id: str) -> None:
        await self.client.cancel_run(run_id)

    async def submit_approval(self, run_id: str, *, action: str, decision: str) -> None:
        await self.client.submit_approval(run_id, action=action, decision=decision)

    async def read_run_socket(self, run_id: str, *, after_sequence: int = 0) -> AsyncIterator[dict[str, Any]]:
        async for event in self.client.read_run_socket(run_id, after_sequence=after_sequence):
            yield event

    async def get_run_events(self, run_id: str, *, after_sequence: int = 0, limit: int = 200) -> RunEventPage:
        return await self.client.get_run_events(run_id, after_sequence=after_sequence, limit=limit)


def _project(item: ProjectResponse) -> ProjectRef:
    return ProjectRef(id=str(item.id), name=item.name)


def _conversation(item: ConversationResponse) -> ConversationRef:
    updated = item.updated_at.strftime("%m-%d %H:%M")
    return ConversationRef(
        id=str(item.id),
        title=item.title or "Untitled",
        project_id=str(item.project_id) if item.project_id else None,
        updated_at=updated,
    )


def _model(provider: str, model: str, display_name: str) -> ModelRef:
    return ModelRef(provider=provider, model=model, display_name=display_name or model)


def history_items(messages: list[MessageResponse]) -> tuple[TranscriptItem, ...]:

    items: list[TranscriptItem] = []
    for message in messages:
        if message.role == "assistant":
            kind, title = "assistant", "ByteBuddhi"
        elif message.role == "user":
            kind, title = "user", "You"
        else:
            kind, title = "notice", message.role
        items.append(TranscriptItem(item_id=f"hist-{message.id}", kind=kind, title=title, body=message.content))
    return tuple(items)
