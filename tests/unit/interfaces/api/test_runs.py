"""POST /api/v1/runs queues work for the authenticated user."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.runs.bus import InProcessRunBus
from app.application.runs.coordinator import LocalRunQueue, RunCoordinator
from app.application.runs.status import RunStatus
from app.application.runs.store import MemoryRunStore
from app.application.runtime.admission import reset_run_admission_controller
from app.application.runtime.events import ExecutionEvent, ExecutionEventType
from app.application.use_cases.agent.execute_task import ExecuteTaskCommand, ExecuteTaskResult
from app.domain.exceptions.project_exceptions import ProjectOwnershipException
from app.domain.models.user import User
from app.interfaces.api.dependencies import get_conversation_repository, get_workspace_resolution_service
from app.interfaces.api.main import app
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.run_runtime import get_run_coordinator


def _user(user_id=None) -> User:
    return User(
        id=user_id or uuid4(),
        email="run@example.com",
        username="runner",
        password_hash="hash",
        created_at=None,
        updated_at=None,
        is_active=True,
    )


class _Workspace:
    def __init__(self) -> None:
        self.error: Exception | None = None

    async def resolve_workspace(self, user_id, project_id=None):
        if self.error is not None:
            raise self.error
        return None


def _coordinator(execute) -> RunCoordinator:
    return RunCoordinator(MemoryRunStore(), InProcessRunBus(), LocalRunQueue(), execute)


@pytest.fixture
def workspace() -> _Workspace:
    return _Workspace()


@pytest.fixture
def seen() -> list[ExecuteTaskCommand]:
    return []


@pytest.fixture
async def coordinator(seen: list[ExecuteTaskCommand]) -> RunCoordinator:
    async def execute(command: ExecuteTaskCommand) -> ExecuteTaskResult:
        seen.append(command)
        assert command.event_sink is not None
        await command.event_sink.aemit(ExecutionEvent(type=ExecutionEventType.RUN_STARTED, run_id=command.run_id or ""))
        await command.event_sink.aemit(
            ExecutionEvent(
                type=ExecutionEventType.ASSISTANT_DELTA,
                run_id=command.run_id or "",
                payload={"delta": "done"},
            )
        )
        return ExecuteTaskResult(
            run_id=command.run_id or "run_test",
            response="done",
            run_state=AgentRunState(
                run_id=command.run_id or "run_test", status=AgentStatus.COMPLETED, final_response="done"
            ),
            conversation_id=uuid4(),
            workspace_id="ws_test",
            assistant_message_id=uuid4(),
        )

    coordinator = _coordinator(execute)
    await coordinator.start()
    yield coordinator
    await coordinator.stop()


@pytest.fixture(autouse=True)
def _reset(coordinator: RunCoordinator, workspace: _Workspace) -> None:
    reset_run_admission_controller()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_run_coordinator] = lambda: coordinator
    app.dependency_overrides[get_workspace_resolution_service] = lambda: workspace
    app.dependency_overrides[get_conversation_repository] = lambda: None
    yield
    app.dependency_overrides.clear()
    reset_run_admission_controller()


@pytest.mark.asyncio
async def test_run_identity_comes_from_the_token_not_the_body(seen: list[ExecuteTaskCommand]) -> None:
    owner = _user()
    other = uuid4()
    app.dependency_overrides[get_current_user] = lambda: owner
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/runs",
            json={"prompt": "Explain this repository", "user_id": str(other)},
            headers={"Idempotency-Key": str(uuid4())},
        )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert "answer" not in body
    for _ in range(50):
        if seen:
            break
        await _pause()
    assert seen[0].user_id == owner.id
    assert seen[0].user_id != other
    assert seen[0].prompt == "Explain this repository"


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_does_not_execute_twice(seen: list[ExecuteTaskCommand]) -> None:
    owner = _user()
    app.dependency_overrides[get_current_user] = lambda: owner
    key = str(uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/v1/runs", json={"prompt": "once"}, headers={"Idempotency-Key": key})
        second = await client.post("/api/v1/runs", json={"prompt": "once"}, headers={"Idempotency-Key": key})
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    for _ in range(50):
        if seen:
            break
        await _pause()
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_run_enforces_project_ownership(workspace: _Workspace, seen: list[ExecuteTaskCommand]) -> None:
    owner = _user()
    project_id = uuid4()
    workspace.error = ProjectOwnershipException(str(project_id), str(owner.id))
    app.dependency_overrides[get_current_user] = lambda: owner
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/runs", json={"prompt": "hello", "project_id": str(project_id)})
    assert response.status_code == 403
    assert seen == []


@pytest.mark.asyncio
async def test_missing_credentials_are_rejected(coordinator: RunCoordinator) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/api/v1/runs", json={"prompt": "hello"})
        invalid = await client.post(
            "/api/v1/runs",
            json={"prompt": "hello"},
            headers={"Authorization": "Bearer not-a-token"},
        )
    assert missing.status_code in {401, 403}
    assert invalid.status_code == 401
    assert coordinator is not None


@pytest.mark.asyncio
async def test_run_reaches_completed(seen: list[ExecuteTaskCommand]) -> None:
    owner = _user()
    app.dependency_overrides[get_current_user] = lambda: owner
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/v1/runs", json={"prompt": "hello"})
        run_id = created.json()["run_id"]
        status_code = 0
        body: dict[str, str] = {}
        for _ in range(50):
            current = await client.get(f"/api/v1/runs/{run_id}")
            status_code = current.status_code
            body = current.json()
            if body.get("status") == RunStatus.COMPLETED.value:
                break
            await _pause()
    assert status_code == 200
    assert body["status"] == "completed"
    events = await _events(run_id)
    assert events[0] == "run_queued"
    assert "run_completed" in events
    assert "done" not in str(body)


async def _events(run_id: str) -> list[str]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/runs/{run_id}/events")
    assert response.status_code == 200
    return [item["type"] for item in response.json()["events"]]


async def _pause() -> None:
    import asyncio

    await asyncio.sleep(0.02)
