"""CLI-shaped client to WebSocket event order without a live model."""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.runs.bus import InProcessRunBus
from app.application.runs.coordinator import LocalRunQueue, RunCoordinator
from app.application.runs.store import MemoryRunStore
from app.application.runtime.events import ExecutionEvent, ExecutionEventType
from app.application.use_cases.agent.execute_task import ExecuteTaskResult
from app.domain.models.user import User
from app.interfaces.api.dependencies import get_conversation_repository, get_workspace_resolution_service
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.routes.runs import get_websocket_user, router
from app.interfaces.api.run_runtime import get_run_coordinator


def _user() -> User:
    return User(
        id=uuid4(),
        email="stream@example.com",
        username="stream",
        password_hash="hash",
        created_at=None,
        updated_at=None,
        is_active=True,
    )


class _Workspace:
    async def resolve_workspace(self, user_id, project_id=None):
        return None


def test_client_receives_deltas_in_order() -> None:
    owner = _user()
    holder: dict[str, RunCoordinator] = {}

    async def execute(command):
        await command.event_sink.aemit(ExecutionEvent(type=ExecutionEventType.RUN_STARTED, run_id=command.run_id or ""))
        await command.event_sink.aemit(
            ExecutionEvent(
                type=ExecutionEventType.ASSISTANT_DELTA, run_id=command.run_id or "", payload={"delta": "Hello"}
            )
        )
        await command.event_sink.aemit(
            ExecutionEvent(
                type=ExecutionEventType.ASSISTANT_DELTA, run_id=command.run_id or "", payload={"delta": " world"}
            )
        )
        return ExecuteTaskResult(
            run_id=command.run_id or "",
            response="Hello world",
            run_state=AgentRunState(
                run_id=command.run_id or "", status=AgentStatus.COMPLETED, final_response="Hello world"
            ),
            conversation_id=uuid4(),
            workspace_id="ws",
            assistant_message_id=uuid4(),
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        coordinator = RunCoordinator(MemoryRunStore(), InProcessRunBus(), LocalRunQueue(), execute)
        await coordinator.start()
        holder["coordinator"] = coordinator
        try:
            yield
        finally:
            await coordinator.stop()

    application = FastAPI(lifespan=lifespan)
    application.include_router(router, prefix="/api/v1")
    application.dependency_overrides[get_current_user] = lambda: owner
    application.dependency_overrides[get_websocket_user] = lambda: owner
    application.dependency_overrides[get_run_coordinator] = lambda: holder["coordinator"]
    application.dependency_overrides[get_workspace_resolution_service] = lambda: _Workspace()
    application.dependency_overrides[get_conversation_repository] = lambda: None

    with TestClient(application) as client:
        created = client.post("/api/v1/runs", json={"prompt": "hi"})
        assert created.status_code == 202
        run_id = created.json()["run_id"]
        with client.websocket_connect(f"/api/v1/runs/{run_id}/stream?after_sequence=0") as socket:
            events = []
            while True:
                item = socket.receive_json()
                if item.get("type") == "ping":
                    continue
                events.append(item)
                if item.get("type") in {"run_completed", "run_failed", "run_cancelled"}:
                    break
        replay = client.get(f"/api/v1/runs/{run_id}/events", params={"after_sequence": 2})

    types = [item["type"] for item in events]
    sequences = [item["sequence"] for item in events]
    assert sequences == list(range(1, len(sequences) + 1))
    assert types[0] == "run_queued"
    assert types[-1] == "run_completed"
    text = "".join(item["data"].get("delta", "") for item in events if item["type"] == "assistant_delta")
    assert text == "Hello world"
    assert events[-1]["data"]["assistant_message_id"]
    assert events[-1]["schema_version"] == 1
    assert replay.status_code == 200
    page = replay.json()
    assert page["events"]
    assert all(item["sequence"] > 2 for item in page["events"])
    assert page["next_sequence"] == page["events"][-1]["sequence"]
