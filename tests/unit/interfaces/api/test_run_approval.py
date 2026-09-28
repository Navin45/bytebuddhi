"""Unit tests for server-authoritative tool approval workflow."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.runs.bus import InProcessRunBus
from app.application.runs.coordinator import LocalRunQueue, RunCoordinator
from app.application.runs.store import MemoryRunStore
from app.application.runtime.admission import reset_run_admission_controller
from app.application.runtime.approval import RunApprovalRegistry
from app.application.use_cases.agent.execute_task import ExecuteTaskCommand, ExecuteTaskResult
from app.domain.models.user import User
from app.interfaces.api.dependencies import get_conversation_repository, get_workspace_resolution_service
from app.interfaces.api.main import app
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.middleware.rate_limiter import RateLimitMiddleware
from app.interfaces.api.run_runtime import get_run_coordinator


def _user(user_id=None) -> User:
    return User(
        id=user_id or uuid4(),
        email="approval_test@example.com",
        username="approver",
        password_hash="hash",
        created_at=None,
        updated_at=None,
        is_active=True,
    )


class _Workspace:
    async def resolve_workspace(self, user_id, project_id=None):
        return None


@pytest.fixture
def workspace() -> _Workspace:
    return _Workspace()


def _clear_rate_limits():
    curr = getattr(app, "middleware_stack", None)
    while curr is not None:
        if isinstance(curr, RateLimitMiddleware):
            curr.request_counts.clear()
        curr = getattr(curr, "app", None)


@pytest.fixture(autouse=True)
def _reset_middleware():
    _clear_rate_limits()
    yield
    _clear_rate_limits()


@pytest.mark.asyncio
async def test_run_approval_flow_approved(workspace):
    reset_run_admission_controller()
    user = _user()
    approval_registry = RunApprovalRegistry()
    run_started_event = asyncio.Event()
    run_done_event = asyncio.Event()

    async def execute(command: ExecuteTaskCommand) -> ExecuteTaskResult:
        assert command.approval_registry is not None
        run_started_event.set()
        # Request approval for high risk action
        approved = await command.approval_registry.request_approval(
            run_id=command.run_id or "",
            user_id=user.id,
            action="dangerous_tool",
            risk_level="high",
            reason="Testing tool approval",
            sink=command.event_sink,
        )
        assert approved is True
        run_done_event.set()
        return ExecuteTaskResult(
            run_id=command.run_id or "",
            response="Action executed after approval",
            run_state=AgentRunState(run_id=command.run_id or "run_test", status=AgentStatus.COMPLETED),
            conversation_id=uuid4(),
            workspace_id="ws-test",
        )

    coordinator = RunCoordinator(
        MemoryRunStore(),
        InProcessRunBus(),
        LocalRunQueue(),
        execute,
        approval=approval_registry,
    )
    await coordinator.start()

    app.dependency_overrides.clear()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workspace_resolution_service] = lambda: workspace
    app.dependency_overrides[get_conversation_repository] = lambda: None
    app.dependency_overrides[get_run_coordinator] = lambda: coordinator

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Create run
            create_res = await client.post("/api/v1/runs", json={"prompt": "Do dangerous work"})
            assert create_res.status_code == 202
            run_id = create_res.json()["run_id"]

            # 2. Wait until run has started and requested approval
            await asyncio.wait_for(run_started_event.wait(), timeout=5.0)

            # 3. Post approval
            approval_res = await client.post(
                f"/api/v1/runs/{run_id}/approval",
                json={"action": "dangerous_tool", "decision": "approved"},
            )
            assert approval_res.status_code == 200
            data = approval_res.json()
            assert data["run_id"] == run_id
            assert data["action"] == "dangerous_tool"
            assert data["status"] == "approved"

            # 4. Wait for execution to finish
            await asyncio.wait_for(run_done_event.wait(), timeout=5.0)
            await asyncio.sleep(0.1)

            get_res = await client.get(f"/api/v1/runs/{run_id}")
            assert get_res.json()["status"] == "completed"

            # 5. Verify events include approval events
            events_res = await client.get(f"/api/v1/runs/{run_id}/events")
            types = [e["type"] for e in events_res.json()["events"]]
            assert "tool_approval_required" in types
            assert "tool_approved" in types
    finally:
        await coordinator.stop()
        app.dependency_overrides.clear()
        reset_run_admission_controller()


@pytest.mark.asyncio
async def test_run_approval_flow_rejected(workspace):
    reset_run_admission_controller()
    user = _user()
    approval_registry = RunApprovalRegistry()
    run_started_event = asyncio.Event()
    run_done_event = asyncio.Event()

    async def execute(command: ExecuteTaskCommand) -> ExecuteTaskResult:
        assert command.approval_registry is not None
        run_started_event.set()
        approved = await command.approval_registry.request_approval(
            run_id=command.run_id or "",
            user_id=user.id,
            action="dangerous_tool",
            risk_level="high",
            reason="Testing rejection",
            sink=command.event_sink,
        )
        assert approved is False
        run_done_event.set()
        return ExecuteTaskResult(
            run_id=command.run_id or "",
            response="Action was rejected by user",
            run_state=AgentRunState(run_id=command.run_id or "run_test", status=AgentStatus.COMPLETED),
            conversation_id=uuid4(),
            workspace_id="ws-test",
        )

    coordinator = RunCoordinator(
        MemoryRunStore(),
        InProcessRunBus(),
        LocalRunQueue(),
        execute,
        approval=approval_registry,
    )
    await coordinator.start()

    app.dependency_overrides.clear()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workspace_resolution_service] = lambda: workspace
    app.dependency_overrides[get_conversation_repository] = lambda: None
    app.dependency_overrides[get_run_coordinator] = lambda: coordinator

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            create_res = await client.post("/api/v1/runs", json={"prompt": "Do dangerous work"})
            assert create_res.status_code == 202
            run_id = create_res.json()["run_id"]

            await asyncio.wait_for(run_started_event.wait(), timeout=5.0)

            approval_res = await client.post(
                f"/api/v1/runs/{run_id}/approval",
                json={"action": "dangerous_tool", "decision": "rejected"},
            )
            assert approval_res.status_code == 200
            assert approval_res.json()["status"] == "rejected"

            await asyncio.wait_for(run_done_event.wait(), timeout=5.0)
            await asyncio.sleep(0.1)

            get_res = await client.get(f"/api/v1/runs/{run_id}")
            assert get_res.json()["status"] == "completed"

            events_res = await client.get(f"/api/v1/runs/{run_id}/events")
            types = [e["type"] for e in events_res.json()["events"]]
            assert "tool_approval_required" in types
            assert "tool_rejected" in types
    finally:
        await coordinator.stop()
        app.dependency_overrides.clear()
        reset_run_admission_controller()


@pytest.mark.asyncio
async def test_run_approval_unauthorized_user(workspace):
    reset_run_admission_controller()
    owner = _user()
    other_user = _user()

    async def execute(command: ExecuteTaskCommand) -> ExecuteTaskResult:
        return ExecuteTaskResult(
            run_id=command.run_id or "",
            response="",
            run_state=AgentRunState(run_id=command.run_id or "run_test", status=AgentStatus.COMPLETED),
            conversation_id=uuid4(),
            workspace_id="ws",
        )

    coordinator = RunCoordinator(MemoryRunStore(), InProcessRunBus(), LocalRunQueue(), execute)
    record = await coordinator.create_run(
        user_id=owner.id,
        prompt="test",
        project_id=None,
        conversation_id=None,
        provider=None,
        model=None,
        idempotency_key=None,
    )

    app.dependency_overrides.clear()
    app.dependency_overrides[get_current_user] = lambda: other_user
    app.dependency_overrides[get_workspace_resolution_service] = lambda: workspace
    app.dependency_overrides[get_conversation_repository] = lambda: None
    app.dependency_overrides[get_run_coordinator] = lambda: coordinator

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                f"/api/v1/runs/{record.id}/approval",
                json={"action": "dangerous_tool", "decision": "approved"},
            )
            assert res.status_code == 404
    finally:
        app.dependency_overrides.clear()
        reset_run_admission_controller()
