"""Cancellation registry and runtime cooperative cancel."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus
from app.application.runtime.cancellation import (
    CancellationToken,
    RunCancellationRegistry,
    reset_run_cancellation_registry,
)
from app.application.tools.registry import ToolRegistry
from app.application.use_cases.agent.execute_task import ExecuteTaskCommand, ExecuteTaskUseCase
from app.domain.models.execution_context import ExecutionContext
from app.domain.models.workspace import Workspace


@pytest.mark.asyncio
async def test_registry_cancel_requires_owning_user() -> None:
    registry = RunCancellationRegistry()
    owner = uuid4()
    other = uuid4()
    token = CancellationToken()
    await registry.register("run_1", owner, token)
    assert await registry.request_cancel("run_1", other) is False
    assert token.is_cancelled() is False
    assert await registry.request_cancel("run_1", owner) is True
    assert token.is_cancelled() is True
    assert await registry.request_cancel("missing", owner) is False


@pytest.mark.asyncio
async def test_registry_cancel_cancels_bound_task() -> None:
    registry = RunCancellationRegistry()
    user = uuid4()
    token = CancellationToken()

    async def hang() -> str:
        await asyncio.sleep(30)
        return "done"

    task = asyncio.create_task(hang())
    await registry.register("run_hang", user, token)
    await registry.bind_task("run_hang", task)
    await registry.request_cancel("run_hang", user)
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_runtime_observes_pre_cancelled_token() -> None:
    gateway = AsyncMock()
    gateway.generate = AsyncMock(side_effect=AssertionError("model must not be called"))
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=ToolRegistry())
    token = CancellationToken()
    token.cancel()
    state = await runtime.run(
        messages=[{"role": "user", "content": "hi"}],
        execution_context=ExecutionContext(
            user_id="u",
            project_id="p",
            conversation_id=None,
            run_id="run_pre",
            workspace_id="ws",
        ),
        cancellation_token=token,
    )
    assert state.status == AgentStatus.CANCELLED
    gateway.generate.assert_not_called()


@pytest.mark.asyncio
async def test_runtime_cancels_in_flight_generate() -> None:
    gateway = AsyncMock()
    started = asyncio.Event()

    async def slow(*_args: object, **_kwargs: object) -> MagicMock:
        started.set()
        await asyncio.sleep(30)
        response = MagicMock()
        response.has_tool_calls = False
        response.content = "should-not-return"
        return response

    gateway.generate.side_effect = slow
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=ToolRegistry(), llm_timeout_seconds=None)
    token = CancellationToken()
    ctx = ExecutionContext(
        user_id="u",
        project_id="p",
        conversation_id=None,
        run_id="run_inflight",
        workspace_id="ws",
    )
    run_task = asyncio.create_task(
        runtime.run(
            messages=[{"role": "user", "content": "hi"}],
            execution_context=ctx,
            cancellation_token=token,
        )
    )
    await started.wait()
    token.cancel()
    state = await asyncio.wait_for(run_task, timeout=2)
    assert state.status == AgentStatus.CANCELLED


@pytest.mark.asyncio
async def test_runtime_wait_for_timeout_propagates() -> None:
    gateway = AsyncMock()

    async def slow(*_args: object, **_kwargs: object) -> MagicMock:
        await asyncio.sleep(1)
        response = MagicMock()
        response.has_tool_calls = False
        response.content = "late"
        return response

    gateway.generate.side_effect = slow
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=ToolRegistry())
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            runtime.run(
                messages=[{"role": "user", "content": "hi"}],
                execution_context=ExecutionContext(
                    user_id="u",
                    project_id="p",
                    conversation_id=None,
                    run_id="run_to",
                    workspace_id="ws",
                ),
            ),
            timeout=0.05,
        )


@pytest.mark.asyncio
async def test_execute_task_forwards_cancellation_token() -> None:
    runtime = MagicMock()
    runtime.run = AsyncMock()
    from app.application.agent.state import AgentRunState

    runtime.run.return_value = AgentRunState(run_id="run_fwd", status=AgentStatus.COMPLETED, final_response="ok")
    resolution = AsyncMock()
    resolution.resolve_workspace = AsyncMock(return_value=Workspace.create(root_path=".", workspace_id="ws"))
    use_case = ExecuteTaskUseCase(workspace_resolution_service=resolution, agent_runtime=runtime)
    token = CancellationToken()
    await use_case.execute(ExecuteTaskCommand(prompt="go", user_id=uuid4(), project_id=None, cancellation_token=token))
    assert runtime.run.await_args.kwargs["cancellation_token"] is token


def test_reset_registry_isolates_tests() -> None:
    reset_run_cancellation_registry()
    assert reset_run_cancellation_registry() is not None
