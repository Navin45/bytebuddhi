from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from app.application.agent.errors import ModelCallError
from app.application.ports.output.llm.model_gateway import ModelGateway
from app.infrastructure.llm.anthropic_gateway import AnthropicModelGateway
from app.infrastructure.llm.openai_gateway import OpenAIModelGateway
from app.infrastructure.llm.provider_factory import LLMProviderType, create_model_gateway


@pytest.mark.asyncio
async def test_openai_gateway_generate_text():
    mock_chat_model = AsyncMock()
    mock_response = AIMessage(
        content="Hello world!",
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        response_metadata={"finish_reason": "stop"},
    )
    mock_chat_model.ainvoke.return_value = mock_response

    gateway = OpenAIModelGateway(chat_model=mock_chat_model)
    assert isinstance(gateway, ModelGateway)

    resp = await gateway.generate([{"role": "user", "content": "hi"}])
    assert resp.content == "Hello world!"
    assert resp.has_tool_calls is False
    assert resp.usage is not None
    assert resp.usage.total_tokens == 15
    assert resp.finish_reason == "stop"


@pytest.mark.asyncio
async def test_openai_gateway_generate_tool_call():
    mock_chat_model = MagicMock()
    mock_bound_model = AsyncMock()
    mock_chat_model.bind_tools.return_value = mock_bound_model

    mock_response = AIMessage(
        content="",
        tool_calls=[{"id": "call_123", "name": "echo", "args": {"text": "ping"}}],
        usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        response_metadata={"finish_reason": "tool_calls"},
    )
    mock_bound_model.ainvoke.return_value = mock_response

    gateway = OpenAIModelGateway(chat_model=mock_chat_model)
    tools = [{"type": "function", "function": {"name": "echo"}}]
    resp = await gateway.generate([{"role": "user", "content": "echo ping"}], tools=tools)

    assert resp.has_tool_calls is True
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].id == "call_123"
    assert resp.tool_calls[0].name == "echo"
    assert resp.tool_calls[0].arguments == {"text": "ping"}


@pytest.mark.asyncio
async def test_openai_gateway_error_wrapping():
    mock_chat_model = AsyncMock()
    mock_chat_model.ainvoke.side_effect = RuntimeError("API connection timeout")

    gateway = OpenAIModelGateway(chat_model=mock_chat_model)
    with pytest.raises(ModelCallError) as exc_info:
        await gateway.generate([{"role": "user", "content": "test"}])
    assert "API connection timeout" in str(exc_info.value)
    assert exc_info.value.is_retryable is True


@pytest.mark.asyncio
async def test_anthropic_gateway_generate():
    mock_chat_model = AsyncMock()
    mock_response = AIMessage(
        content="Claude response",
        usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        response_metadata={"stop_reason": "end_turn"},
    )
    mock_chat_model.ainvoke.return_value = mock_response

    gateway = AnthropicModelGateway(chat_model=mock_chat_model)
    assert isinstance(gateway, ModelGateway)

    resp = await gateway.generate([{"role": "user", "content": "hi"}])
    assert resp.content == "Claude response"
    assert resp.finish_reason == "end_turn"


def test_factory_create_model_gateway():
    # Factory with mocked keys to verify instantiation
    gw_openai = create_model_gateway(LLMProviderType.OPENAI, api_key="sk-fake")
    assert isinstance(gw_openai, OpenAIModelGateway)

    gw_anthropic = create_model_gateway(LLMProviderType.ANTHROPIC, api_key="sk-ant-fake")
    assert isinstance(gw_anthropic, AnthropicModelGateway)
