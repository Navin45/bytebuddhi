from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.application.agent.errors import ModelCallError
from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus
from app.application.ports.output.llm.model_gateway import ModelGateway, ModelResponse
from app.application.tools.builtin.echo_tool import register_echo_tool
from app.application.tools.definition import ToolCall
from app.application.tools.registry import ToolRegistry
from tests.helpers.execution import trusted_execution_context


class MockModelGateway(ModelGateway):
    """Mock ModelGateway that supports scripted responses."""

    def __init__(self, responses: list[ModelResponse]):
        self.responses = list(responses)
        self.call_count = 0
        self.recorded_calls: list[dict[str, Any]] = []

    async def generate(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        self.recorded_calls.append({"messages": messages, "tools": tools})
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return ModelResponse(content="Default fallback response")

    async def stream(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        if False:
            yield


@pytest.mark.asyncio
async def test_agent_runtime_direct_answer():
    gateway = MockModelGateway(
        [
            ModelResponse(content="Hello! How can I help with your code?", tool_calls=[]),
        ]
    )
    registry = ToolRegistry()
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=registry)

    result = await runtime.run(
        messages=[{"role": "user", "content": "hello"}],
        execution_context=trusted_execution_context(),
    )

    assert result.status == AgentStatus.COMPLETED
    assert result.final_response == "Hello! How can I help with your code?"
    assert result.iteration == 1
    assert len(result.tool_calls) == 0
    assert result.error is None


@pytest.mark.asyncio
async def test_agent_runtime_tool_call_loop():
    # Turn 1: model requests echo tool
    # Turn 2: model sees echo result, returns final answer
    gateway = MockModelGateway(
        [
            ModelResponse(
                content=None,
                tool_calls=[ToolCall(id="call_echo_1", name="echo", arguments={"message": "ByteBuddhi"})],
            ),
            ModelResponse(
                content="The echoed message was ByteBuddhi.",
                tool_calls=[],
            ),
        ]
    )
    registry = ToolRegistry()
    register_echo_tool(registry)
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=registry)

    result = await runtime.run(
        messages=[{"role": "user", "content": "echo ByteBuddhi"}],
        execution_context=trusted_execution_context(),
    )

    assert result.status == AgentStatus.COMPLETED
    assert result.iteration == 2
    assert result.final_response == "The echoed message was ByteBuddhi."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "echo"
    assert len(result.tool_results) == 1
    assert result.tool_results[0].content == "echo: ByteBuddhi"
    assert result.error is None


@pytest.mark.asyncio
async def test_agent_runtime_iteration_limit():
    # Model that continuously requests a tool call
    continuous_tool_resp = ModelResponse(
        content=None,
        tool_calls=[ToolCall(id="call_inf", name="echo", arguments={"message": "loop"})],
    )
    gateway = MockModelGateway([continuous_tool_resp] * 10)
    registry = ToolRegistry()
    register_echo_tool(registry)
    runtime = AgentRuntime(
        model_gateway=gateway,
        tool_registry=registry,
        max_iterations=3,
    )

    result = await runtime.run(
        messages=[{"role": "user", "content": "loop forever"}],
        execution_context=trusted_execution_context(),
    )

    assert result.status == AgentStatus.FAILED
    assert result.error is not None
    assert "iteration" in result.error.message.lower()


@pytest.mark.asyncio
async def test_agent_runtime_with_checkpointer():
    memory_checkpointer = MemorySaver()
    gateway = MockModelGateway(
        [
            ModelResponse(content="Answer preserved with checkpoint.", tool_calls=[]),
        ]
    )
    registry = ToolRegistry()
    runtime = AgentRuntime(
        model_gateway=gateway,
        tool_registry=registry,
        checkpointer=memory_checkpointer,
    )

    thread_config = {"configurable": {"thread_id": "thread-conv-99"}}
    result = await runtime.run(
        messages=[{"role": "user", "content": "hello"}],
        config=thread_config,
        execution_context=trusted_execution_context(run_id="run_checkpoint"),
    )

    assert result.status == AgentStatus.COMPLETED
    assert result.final_response == "Answer preserved with checkpoint."

    # Verify checkpointer saved state
    state = await runtime.graph.aget_state(thread_config)
    assert state is not None
    assert state.values["status"] == "completed"


class FlakyThenSucceedsGateway(ModelGateway):
    """Raises a retryable ModelCallError on the first N calls, then succeeds."""

    def __init__(self, failures_before_success: int, final_response: ModelResponse):
        self.failures_before_success = failures_before_success
        self.final_response = final_response
        self.call_count = 0

    async def generate(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        self.call_count += 1
        if self.call_count <= self.failures_before_success:
            raise ModelCallError(message="Model provider call failed (provider_unavailable)", is_retryable=True)
        return self.final_response

    async def stream(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        if False:
            yield


@pytest.mark.asyncio
async def test_agent_runtime_retries_transient_model_error():
    gateway = FlakyThenSucceedsGateway(
        failures_before_success=2,
        final_response=ModelResponse(content="Recovered after retries.", tool_calls=[]),
    )
    registry = ToolRegistry()
    runtime = AgentRuntime(
        model_gateway=gateway,
        tool_registry=registry,
        model_call_max_retries=2,
        model_call_retry_base_seconds=0.0,
    )

    result = await runtime.run(
        messages=[{"role": "user", "content": "hello"}],
        execution_context=trusted_execution_context(),
    )

    assert result.status == AgentStatus.COMPLETED
    assert result.final_response == "Recovered after retries."
    assert gateway.call_count == 3


@pytest.mark.asyncio
async def test_agent_runtime_gives_up_after_max_retries():
    gateway = FlakyThenSucceedsGateway(
        failures_before_success=5,
        final_response=ModelResponse(content="Never reached.", tool_calls=[]),
    )
    registry = ToolRegistry()
    runtime = AgentRuntime(
        model_gateway=gateway,
        tool_registry=registry,
        model_call_max_retries=2,
        model_call_retry_base_seconds=0.0,
    )

    result = await runtime.run(
        messages=[{"role": "user", "content": "hello"}],
        execution_context=trusted_execution_context(),
    )

    assert result.status == AgentStatus.FAILED
    assert gateway.call_count == 3  # initial attempt + 2 retries
    assert result.error is not None
    assert "provider_unavailable" in result.error.message
