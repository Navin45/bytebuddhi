"""End-to-end integration test for AgentRuntime with local command execution."""

import sys
from unittest.mock import AsyncMock

import pytest

from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus
from app.application.execution.command_executor import CommandExecutor
from app.application.policy.command_policy import CommandPolicy
from app.application.policy.tool_policy import ToolPolicyEngine
from app.application.ports.output.llm.model_gateway import ModelGateway, ModelResponse
from app.application.tools.builtin.command_tools import create_command_tool
from app.application.tools.builtin.filesystem_tools import create_filesystem_tools
from app.application.tools.definition import ToolCall
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.models.workspace import Workspace
from app.infrastructure.execution.local_process_manager import LocalProcessManager
from tests.helpers.execution import trusted_execution_context


@pytest.mark.asyncio
async def test_agent_runtime_executes_local_command(tmp_path):
    workspace = Workspace.create(root_path=tmp_path, workspace_id="ws_e2e_test")
    process_manager = LocalProcessManager()
    command_policy = CommandPolicy(allow_high_risk=True)
    command_executor = CommandExecutor(
        process_manager=process_manager,
        workspace=workspace,
        command_policy=command_policy,
    )

    registry = ToolRegistry()
    for defn, handler in create_filesystem_tools():
        registry.register(defn, handler)

    cmd_def, cmd_handler = create_command_tool(command_executor)
    registry.register(cmd_def, cmd_handler)

    policy_engine = ToolPolicyEngine(command_policy=command_policy)
    tool_executor = ToolExecutor(registry, policy_engine=policy_engine)

    # Mock ModelGateway: Turn 1 requests run_command, Turn 2 gives final answer
    mock_gateway = AsyncMock(spec=ModelGateway)
    mock_gateway.generate.side_effect = [
        # Turn 1: Model requests tool call
        ModelResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_version",
                    name="run_command",
                    arguments={"command": [sys.executable, "--version"]},
                )
            ],
            model="test-model",
        ),
        # Turn 2: Model consumes tool result and responds
        ModelResponse(
            content="The Python executable is verified and operational.",
            tool_calls=[],
            model="test-model",
        ),
    ]

    runtime = AgentRuntime(
        model_gateway=mock_gateway,
        tool_registry=registry,
        tool_executor=tool_executor,
        workspace=workspace,
    )

    messages = [{"role": "user", "content": "Check python version please"}]
    run_state = await runtime.run(
        messages=messages,
        workspace=workspace,
        execution_context=trusted_execution_context(workspace_id=workspace.workspace_id),
    )

    assert run_state.status == AgentStatus.COMPLETED
    assert run_state.iteration == 2
    assert len(run_state.tool_calls) == 1
    assert run_state.tool_calls[0].name == "run_command"
    assert len(run_state.tool_results) == 1
    assert not run_state.tool_results[0].is_error
    assert "Python" in run_state.tool_results[0].content
    assert run_state.final_response == "The Python executable is verified and operational."
