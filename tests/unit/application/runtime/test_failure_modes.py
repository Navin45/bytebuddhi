"""Deterministic failure-mode tests for required vs optional dependencies."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.application.agent.errors import ModelCallError
from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus
from app.application.tools.registry import ToolRegistry
from app.domain.models.execution_context import ExecutionContext


@pytest.mark.asyncio
async def test_llm_provider_failure_becomes_failed_run() -> None:
    gateway = AsyncMock()
    gateway.generate = AsyncMock(side_effect=ModelCallError(message="provider 503", is_retryable=True))
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=ToolRegistry())
    state = await runtime.run(
        messages=[{"role": "user", "content": "hi"}],
        execution_context=ExecutionContext(
            user_id="u",
            project_id="p",
            conversation_id=None,
            run_id="run_fail",
            workspace_id="ws",
        ),
    )
    assert state.status == AgentStatus.FAILED
    assert state.error is not None


@pytest.mark.asyncio
async def test_malformed_model_response_does_not_raise_out_of_runtime() -> None:
    gateway = AsyncMock()
    response = MagicMock()
    response.has_tool_calls = False
    response.content = None
    response.tool_calls = []
    response.usage = None
    response.finish_reason = None
    gateway.generate = AsyncMock(return_value=response)
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=ToolRegistry())
    state = await runtime.run(
        messages=[{"role": "user", "content": "hi"}],
        execution_context=ExecutionContext(
            user_id=str(uuid4()),
            project_id=None,
            conversation_id=None,
            run_id="run_empty",
            workspace_id="ws",
        ),
    )
    assert state.status in {AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.IDLE, AgentStatus.RUNNING}
