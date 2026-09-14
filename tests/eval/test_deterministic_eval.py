"""Deterministic evaluation of representative ExecuteTaskUseCase outcomes."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.application.agent.runtime import AgentRuntime
from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.use_cases.agent.execute_task import ExecuteTaskCommand, ExecuteTaskUseCase
from app.domain.models.workspace import Workspace


@pytest.mark.asyncio
async def test_eval_code_explanation_completes() -> None:
    runtime = MagicMock(spec=AgentRuntime)
    runtime.run = AsyncMock(
        return_value=AgentRunState(
            run_id="eval_1",
            status=AgentStatus.COMPLETED,
            final_response="The function returns the sum of its arguments.",
        )
    )
    resolution = AsyncMock()
    resolution.resolve_workspace = AsyncMock(return_value=Workspace.create(root_path=".", workspace_id="ws"))
    use_case = ExecuteTaskUseCase(workspace_resolution_service=resolution, agent_runtime=runtime)
    result = await use_case.execute(ExecuteTaskCommand(prompt="Explain add()", user_id=uuid4()))
    assert result.run_state.status == AgentStatus.COMPLETED
    assert "sum" in result.response.lower()


@pytest.mark.asyncio
async def test_eval_security_rejection_is_not_success_claim() -> None:
    runtime = MagicMock(spec=AgentRuntime)
    runtime.run = AsyncMock(
        return_value=AgentRunState(
            run_id="eval_deny",
            status=AgentStatus.FAILED,
            final_response="",
        )
    )
    resolution = AsyncMock()
    resolution.resolve_workspace = AsyncMock(return_value=Workspace.create(root_path=".", workspace_id="ws"))
    use_case = ExecuteTaskUseCase(workspace_resolution_service=resolution, agent_runtime=runtime)
    result = await use_case.execute(ExecuteTaskCommand(prompt="rm -rf /", user_id=uuid4()))
    assert result.run_state.status == AgentStatus.FAILED


@pytest.mark.asyncio
async def test_eval_cancellation_terminal_state() -> None:
    runtime = MagicMock(spec=AgentRuntime)
    runtime.run = AsyncMock(
        return_value=AgentRunState(run_id="eval_c", status=AgentStatus.CANCELLED, final_response="")
    )
    resolution = AsyncMock()
    resolution.resolve_workspace = AsyncMock(return_value=Workspace.create(root_path=".", workspace_id="ws"))
    use_case = ExecuteTaskUseCase(workspace_resolution_service=resolution, agent_runtime=runtime)
    result = await use_case.execute(ExecuteTaskCommand(prompt="long task", user_id=uuid4()))
    assert result.run_state.status == AgentStatus.CANCELLED
