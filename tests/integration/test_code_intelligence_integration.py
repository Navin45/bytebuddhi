"""End-to-end integration tests for CodeIntelligenceService with AgentRuntime and ContextEngine."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.application.agent.context import ContextEngine
from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus
from app.application.code.in_memory_index import InMemoryCodeIndex
from app.application.code.intelligence_service import CodeIntelligenceService
from app.application.ports.output.llm.model_gateway import ModelGateway, ModelResponse
from app.application.tools.builtin.code_tools import create_code_tools
from app.application.tools.definition import ToolCall
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.models.workspace import Workspace
from app.infrastructure.parser.tree_sitter_parser import TreeSitterCodeParser
from tests.helpers.execution import trusted_execution_context


@pytest.mark.asyncio
async def test_code_intelligence_with_agent_runtime(tmp_path: Path):
    # Setup workspace with source files
    workspace = Workspace.create(root_path=str(tmp_path), workspace_id="ws_integration")
    source_file = tmp_path / "payment_service.py"
    source_file.write_text(
        "class PaymentService:\n"
        '    """Handles checkout processing."""\n'
        "    def process(self, amount: float) -> bool:\n"
        "        return amount > 0\n",
        encoding="utf-8",
    )

    # Initialize CodeIntelligence stack
    parser = TreeSitterCodeParser()
    index = InMemoryCodeIndex()
    code_service = CodeIntelligenceService(parser=parser, index=index)

    # Tool registry and executor
    registry = ToolRegistry()
    for defn, handler in create_code_tools(code_service, default_workspace=workspace):
        registry.register(defn, handler)

    tool_executor = ToolExecutor(registry)
    context_engine = ContextEngine()

    mock_gateway = AsyncMock(spec=ModelGateway)
    call_count = 0

    async def mock_generate(messages, tools=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First turn: Agent calls get_code_structure
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc_struct_1",
                        name="get_code_structure",
                        arguments={"path": "payment_service.py", "max_depth": 3},
                    )
                ],
            )
        else:
            # Second turn: verify code structure was returned and model answers
            last_msg = messages[-1]["content"]
            assert "PaymentService" in last_msg
            assert "process" in last_msg
            return ModelResponse(content="PaymentService contains process method.")

    mock_gateway.generate.side_effect = mock_generate

    runtime = AgentRuntime(
        model_gateway=mock_gateway,
        tool_registry=registry,
        context_engine=context_engine,
        tool_executor=tool_executor,
        workspace=workspace,
        max_iterations=5,
    )

    state = await runtime.run(
        messages=[{"role": "user", "content": "Analyze payment_service.py structure"}],
        execution_context=trusted_execution_context(
            run_id="run_code_int",
            workspace_id=workspace.workspace_id,
        ),
    )

    assert state.status == AgentStatus.COMPLETED
    assert "PaymentService contains process method." in (state.final_response or "")

    # Verify that index now contains the parsed structure
    cached_struct = index.get("payment_service.py")
    assert cached_struct is not None
    assert cached_struct.language == "python"
    assert len(cached_struct.symbols) == 2
