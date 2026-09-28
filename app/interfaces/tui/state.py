"""Presentation state for the terminal client. The server remains authoritative."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ProjectRef:
    id: str
    name: str


@dataclass(frozen=True)
class ConversationRef:
    id: str
    title: str
    project_id: str | None
    updated_at: str


@dataclass(frozen=True)
class ModelRef:
    provider: str
    model: str
    display_name: str


@dataclass(frozen=True)
class TranscriptItem:
    item_id: str
    kind: str
    title: str
    body: str
    detail: str = ""
    run_id: str | None = None
    streaming: bool = False
    tool_open: bool = False


@dataclass(frozen=True)
class TuiState:
    connection: str = "authenticating"
    reconnect_attempt: int = 0
    reconnect_limit: int = 3
    projects: tuple[ProjectRef, ...] = ()
    conversations: tuple[ConversationRef, ...] = ()
    models: tuple[ModelRef, ...] = ()
    active_project_id: str | None = None
    active_conversation_id: str | None = None
    active_run_id: str | None = None
    run_status: str = "idle"
    submitting: bool = False
    cancel_sent: bool = False
    last_sequence: int = 0
    selected_provider: str | None = None
    selected_model: str | None = None
    transcript: tuple[TranscriptItem, ...] = ()
    narrow: bool = False

    @property
    def run_active(self) -> bool:
        return self.submitting or self.run_status in {"queued", "running", "cancel_requested"}

    def visible_conversations(self) -> tuple[ConversationRef, ...]:
        if self.active_project_id is None:
            return tuple(item for item in self.conversations if item.project_id is None)
        return tuple(item for item in self.conversations if item.project_id == self.active_project_id)


def connection_label(state: TuiState) -> str:
    if state.connection == "reconnecting":
        return f"RECONNECTING {state.reconnect_attempt}/{state.reconnect_limit}"
    labels = {
        "authenticating": "AUTHENTICATING",
        "gateway_starting": "GATEWAY STARTING",
        "connected": "CONNECTED",
        "disconnected": "DISCONNECTED",
        "ready": "READY",
    }
    return labels.get(state.connection, state.connection.upper())


def run_label(status: str) -> str:
    labels = {
        "idle": "IDLE",
        "queued": "QUEUED",
        "running": "RUNNING",
        "completed": "COMPLETED",
        "failed": "FAILED",
        "cancelled": "CANCELLED",
        "interrupted": "INTERRUPTED",
        "cancel_requested": "CANCEL REQUESTED",
    }
    return labels.get(status, status.upper())


def status_line(state: TuiState) -> str:
    model = state.selected_model or "server default"
    return f"{connection_label(state)} • {run_label(state.run_status)} • {model} • Esc cancel • Enter send • ? help"


def with_user_message(state: TuiState, text: str, *, item_id: str) -> TuiState:
    item = TranscriptItem(item_id=item_id, kind="user", title="You", body=text)
    return replace(state, submitting=True, transcript=(*state.transcript, item))


def unlock(state: TuiState, status: str) -> TuiState:
    return replace(state, run_status=status, submitting=False, cancel_sent=False, active_run_id=state.active_run_id)
