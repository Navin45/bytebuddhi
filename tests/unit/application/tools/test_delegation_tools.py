"""Unit tests for delegation tool capability."""

from unittest.mock import AsyncMock

import pytest

from app.application.agent.orchestrator import MultiAgentOrchestrator
from app.application.tools.builtin.delegation_tools import create_delegation_tool
from app.application.tools.context import ToolExecutionContext
from app.domain.models.agent import AgentResult, TaskExecutionStatus
from app.domain.models.workspace import Workspace


@pytest.mark.asyncio
async def test_delegation_tool_success():
    """Verify delegate_task tool delegates to orchestrator and returns summary."""
    mock_orchestrator = AsyncMock(spec=MultiAgentOrchestrator)
    mock_orchestrator.execute_task.return_value = AgentResult(
        task_id="task_1",
        child_run_id="c1",
        parent_run_id="p1",
        agent_id="researcher",
        status=TaskExecutionStatus.SUCCESS,
        summary="Found 5 symbols in codebase.",
        answer="Details on 5 symbols.",
    )

    defn, handler = create_delegation_tool(mock_orchestrator)
    assert defn.name == "delegate_task"
    assert defn.id == "native.delegate_task"

    ctx = ToolExecutionContext(
        run_id="p1",
        tool_call_id="call_del",
        workspace=Workspace.create(root_path="."),
    )

    res = await handler(
        agent_id="researcher",
        task_description="Search for symbols",
        context=ctx,
    )

    assert "Subtask [task_1] (researcher) — ✓ SUCCESS" in res
    assert "Found 5 symbols in codebase" in res
    mock_orchestrator.execute_task.assert_called_once()


@pytest.mark.asyncio
async def test_delegation_tool_pre_cancellation():
    """Verify delegate_task halts if context is already cancelled."""
    mock_orchestrator = AsyncMock(spec=MultiAgentOrchestrator)
    import asyncio

    cancel_evt = asyncio.Event()
    cancel_evt.set()

    ctx = ToolExecutionContext(
        run_id="p1",
        tool_call_id="call_del",
        workspace=Workspace.create(root_path="."),
        cancellation_token=cancel_evt,
    )

    _defn, handler = create_delegation_tool(mock_orchestrator)
    res = await handler(
        agent_id="coder",
        task_description="Write code",
        context=ctx,
    )

    assert "cancelled before execution" in res.lower()
    mock_orchestrator.execute_task.assert_not_called()
