"""Unit tests for ToolExecutor with ToolExecutionContext and PolicyEngine."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall, ToolDefinition
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.models.workspace import Workspace


@pytest.fixture
def workspace(tmp_path) -> Workspace:
    return Workspace.create(root_path=tmp_path, workspace_id="test_ws")


@pytest.mark.asyncio
async def test_tool_executor_injects_context(workspace: Workspace):
    registry = ToolRegistry()

    received_context = {}

    def context_aware_tool(message: str, context: ToolExecutionContext) -> dict[str, Any]:
        received_context["run_id"] = context.run_id
        received_context["workspace_id"] = context.workspace.workspace_id
        return {"reply": message}

    definition = ToolDefinition(name="context_tool", description="Test context injection")
    registry.register(definition, context_aware_tool)

    executor = ToolExecutor(registry)
    context = ToolExecutionContext(run_id="run_123", tool_call_id="call_abc", workspace=workspace)

    call = ToolCall(id="call_abc", name="context_tool", arguments={"message": "hello"})
    result = await executor.execute(call, context=context)

    assert not result.is_error
    assert result.content == '{"reply": "hello"}'
    assert received_context["run_id"] == "run_123"
    assert received_context["workspace_id"] == "test_ws"


@pytest.mark.asyncio
async def test_tool_executor_policy_denies_tool_call(workspace: Workspace):
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="blocked_tool", description="blocked"), lambda: "ok")

    mock_policy = MagicMock()
    mock_policy.authorize_tool_call = MagicMock(return_value=(False, "Restricted by security policy"))

    executor = ToolExecutor(registry, policy_engine=mock_policy)
    context = ToolExecutionContext(run_id="run_123", tool_call_id="call_1", workspace=workspace)

    call = ToolCall(id="call_1", name="blocked_tool", arguments={})
    result = await executor.execute(call, context=context)

    assert result.is_error
    assert "Policy authorization failed" in result.content
    assert result.error_details is not None
    assert result.error_details["error"] == "ToolAuthorizationError"
    assert result.error_details["reason"] == "Restricted by security policy"
