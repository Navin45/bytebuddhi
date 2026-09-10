"""End-to-end integration test for AgentRuntime with MemoryOrchestrator and ContextEngine."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.application.agent.context import ContextEngine
from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus
from app.application.memory.orchestrator import MemoryOrchestrator
from app.application.ports.output.llm.model_gateway import ModelGateway, ModelResponse
from app.application.tools.builtin.command_tools import create_command_tool
from app.application.tools.definition import ToolCall
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.models.memory import MemoryScope
from app.domain.models.workspace import Workspace
from app.infrastructure.execution.local_process_manager import LocalProcessManager
from app.infrastructure.persistence.sqlite.sqlite_memory_store import SqliteMemoryStore
from app.infrastructure.storage.local_artifact_store import LocalArtifactStore


@pytest.mark.asyncio
async def test_agent_runtime_memory_and_observation_integration(tmp_path: Path):
    workspace = Workspace.create(root_path=tmp_path)
    sqlite_db = tmp_path / "test_op_mem.db"
    working_store = SqliteMemoryStore(sqlite_db)

    mock_durable_store = AsyncMock()
    mock_durable_store.search.return_value = []
    mock_durable_store.save.side_effect = lambda m: m

    artifact_store = LocalArtifactStore(base_dir=tmp_path / "artifacts")

    orchestrator = MemoryOrchestrator(
        working_store=working_store,
        durable_store=mock_durable_store,
        artifact_store=artifact_store,
    )

    process_manager = LocalProcessManager()
    from app.application.execution.command_executor import CommandExecutor
    from app.application.policy.command_policy import CommandPolicy

    command_policy = CommandPolicy(allow_high_risk=True)
    command_executor = CommandExecutor(
        process_manager=process_manager,
        workspace=workspace,
        command_policy=command_policy,
        artifact_store=artifact_store,
    )

    registry = ToolRegistry()
    cmd_def, cmd_handler = create_command_tool(command_executor)
    registry.register(cmd_def, cmd_handler)

    tool_executor = ToolExecutor(registry)
    context_engine = ContextEngine()

    mock_gateway = AsyncMock(spec=ModelGateway)
    call_count = 0

    async def mock_generate(messages, tools=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First turn: call run_command
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc_echo",
                        name="run_command",
                        arguments={"command": [sys.executable, "-c", "print('hello_memory_world')"]},
                    )
                ],
            )
        else:
            # Second turn: verify observation made it to system prompt context and return answer
            system_msg = messages[0]["content"]
            assert "hello_memory_world" in system_msg or "run_command" in system_msg
            return ModelResponse(content="Successfully verified memory observation.")

    mock_gateway.generate.side_effect = mock_generate

    runtime = AgentRuntime(
        model_gateway=mock_gateway,
        tool_registry=registry,
        context_engine=context_engine,
        tool_executor=tool_executor,
        workspace=workspace,
        memory_orchestrator=orchestrator,
        max_iterations=5,
    )

    state = await runtime.run(
        messages=[{"role": "user", "content": "Execute echo and verify memory"}],
        run_id="run_mem_test",
    )

    assert state.status == AgentStatus.COMPLETED
    assert "Successfully verified" in (state.final_response or "")

    # Verify observation was persisted into SQLite working memory
    obs_memories = await working_store.search(
        scope=MemoryScope.AGENT_RUN,
        scope_id="run_mem_test",
    )
    assert len(obs_memories) >= 1
    assert "run_command" in obs_memories[0].content
