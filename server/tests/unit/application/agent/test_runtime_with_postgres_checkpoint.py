from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus
from app.application.ports.output.llm.model_gateway import ModelGateway, ModelResponse
from app.application.tools.registry import ToolRegistry
from app.infrastructure.persistence.postgres.checkpoint_saver import CheckpointModel, PostgresCheckpointSaver


class MockModelGateway(ModelGateway):
    def __init__(self, responses: list[ModelResponse]):
        self.responses = list(responses)
        self.call_count = 0

    async def generate(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return ModelResponse(content="Done")

    async def stream(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        if False:
            yield


@pytest.mark.asyncio
async def test_agent_runtime_with_postgres_checkpoint_saver():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    saved_checkpoints = []

    def mock_add(model):
        if isinstance(model, CheckpointModel):
            saved_checkpoints.append(model)

    mock_session.add.side_effect = mock_add

    def mock_execute(stmt):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        return mock_result

    mock_session.execute.side_effect = mock_execute

    saver = PostgresCheckpointSaver(mock_session)

    gateway = MockModelGateway(
        [
            ModelResponse(content="Persistence confirmed with Postgres checkpoint saver.", tool_calls=[]),
        ]
    )
    registry = ToolRegistry()
    runtime = AgentRuntime(
        model_gateway=gateway,
        tool_registry=registry,
        checkpointer=saver,
    )

    thread_config = {"configurable": {"thread_id": "thread-pg-1"}}
    result = await runtime.run(
        messages=[{"role": "user", "content": "hello"}],
        config=thread_config,
    )

    assert result.status == AgentStatus.COMPLETED
    assert result.final_response == "Persistence confirmed with Postgres checkpoint saver."
    assert mock_session.add.called
    assert len(saved_checkpoints) > 0
    assert saved_checkpoints[0].thread_id == "thread-pg-1"
