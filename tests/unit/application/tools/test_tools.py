import pytest

from app.application.tools.definition import ToolCall, ToolDefinition
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry


def test_tool_definition_schemas():
    defn = ToolDefinition(
        name="test_tool",
        description="A test tool",
        parameters={
            "type": "object",
            "properties": {"arg1": {"type": "string"}},
            "required": ["arg1"],
        },
    )
    openai_schema = defn.to_openai_schema()
    assert openai_schema["type"] == "function"
    assert openai_schema["function"]["name"] == "test_tool"
    assert "parameters" in openai_schema["function"]

    anthropic_schema = defn.to_anthropic_schema()
    assert anthropic_schema["name"] == "test_tool"
    assert "input_schema" in anthropic_schema


def test_tool_registry():
    registry = ToolRegistry()
    defn = ToolDefinition(name="echo", description="Echoes input")

    def echo_handler(text: str) -> str:
        return text

    registry.register(defn, echo_handler)

    assert registry.has("echo") is True
    assert registry.has("nonexistent") is False
    assert registry.get("echo") is not None
    assert len(registry.list_definitions()) == 1
    assert len(registry.get_schemas_for_openai()) == 1


@pytest.mark.asyncio
async def test_tool_executor_success_async():
    registry = ToolRegistry()
    defn = ToolDefinition(name="add", description="Add numbers")

    async def add_handler(a: int, b: int) -> int:
        return a + b

    registry.register(defn, add_handler)
    executor = ToolExecutor(registry)

    call = ToolCall(id="call_1", name="add", arguments={"a": 3, "b": 7})
    result = await executor.execute(call)

    assert result.tool_call_id == "call_1"
    assert result.name == "add"
    assert result.content == "10"
    assert result.is_error is False


@pytest.mark.asyncio
async def test_tool_executor_sync_and_dict_return():
    registry = ToolRegistry()
    defn = ToolDefinition(name="get_info", description="Get info")

    def info_handler() -> dict:
        return {"status": "ok"}

    registry.register(defn, info_handler)
    executor = ToolExecutor(registry)

    call = ToolCall(id="call_2", name="get_info", arguments={})
    result = await executor.execute(call)

    assert result.content == '{"status": "ok"}'
    assert result.is_error is False


@pytest.mark.asyncio
async def test_tool_executor_not_found():
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    call = ToolCall(id="call_3", name="missing", arguments={})
    result = await executor.execute(call)

    assert result.is_error is True
    assert "not registered" in result.content


@pytest.mark.asyncio
async def test_tool_executor_handler_exception():
    registry = ToolRegistry()
    defn = ToolDefinition(name="fail", description="Fails")

    def fail_handler():
        raise ValueError("Something broke")

    registry.register(defn, fail_handler)
    executor = ToolExecutor(registry)

    call = ToolCall(id="call_4", name="fail", arguments={})
    result = await executor.execute(call)

    assert result.is_error is True
    assert "Something broke" in result.content
