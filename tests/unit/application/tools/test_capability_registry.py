"""Unit tests for ToolRegistry and unified capability models."""

import pytest

from app.application.tools.definition import (
    Capability,
    CapabilityType,
    RiskLevel,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from app.application.tools.registry import ToolRegistry


def test_tool_definition_elevation():
    """Verify ToolDefinition elevation to unified capability model."""
    cap = ToolDefinition(
        name="test_tool",
        description="A test capability",
        capability_type=CapabilityType.CONNECTOR,
        risk_level=RiskLevel.MEDIUM,
        requires_approval=True,
    )
    assert cap.id == "connector.test_tool"
    assert cap.capability_type == CapabilityType.CONNECTOR
    assert cap.risk_level == RiskLevel.MEDIUM
    assert cap.requires_approval is True

    # Test alias identity
    assert Capability is ToolDefinition


def test_tool_definition_schema_generation():
    """Verify OpenAI and Anthropic schema exports."""
    cap = ToolDefinition(
        name="search_repos",
        description="Search GitHub repositories",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        id="github.search_repos",
        capability_type=CapabilityType.CONNECTOR,
    )
    openai_schema = cap.to_openai_schema()
    assert openai_schema["type"] == "function"
    assert openai_schema["function"]["name"] == "search_repos"
    assert "query" in openai_schema["function"]["parameters"]["properties"]

    anthropic_schema = cap.to_anthropic_schema()
    assert anthropic_schema["name"] == "search_repos"
    assert "query" in anthropic_schema["input_schema"]["properties"]


def test_registry_dual_indexing_and_lookup():
    """Verify lookup by both tool name and canonical id."""
    registry = ToolRegistry()

    def dummy_handler(x: int) -> int:
        return x * 2

    defn = ToolDefinition(
        name="double_val",
        description="Doubles input value",
        id="math.double_val",
        capability_type=CapabilityType.NATIVE,
    )
    registry.register(defn, dummy_handler)

    # Lookup by name
    entry_by_name = registry.get("double_val")
    assert entry_by_name is not None
    assert entry_by_name[0].id == "math.double_val"

    # Lookup by id
    entry_by_id = registry.get_by_id("math.double_val")
    assert entry_by_id is not None
    assert entry_by_id[0].name == "double_val"

    # Verify len and membership
    assert len(registry) == 1
    assert "double_val" in registry


def test_registry_collision_handling():
    """Verify registry raises or replaces appropriately on name collision."""
    registry = ToolRegistry()

    defn1 = ToolDefinition(name="echo", description="First echo", id="native.echo1")
    defn2 = ToolDefinition(name="echo", description="Second echo", id="native.echo2")

    registry.register(defn1, lambda: "1")

    # Re-registering without allow_override raises ValueError
    with pytest.raises(ValueError, match="already registered"):
        registry.register(defn2, lambda: "2", allow_override=False)

    # Re-registering with allow_override succeeds
    registry.register(defn2, lambda: "2", allow_override=True)
    assert len(registry) == 1
    assert registry.get("echo")[0].id == "native.echo2"


def test_registry_unregister():
    """Verify unregistering capability removes it from both name and id indices."""
    registry = ToolRegistry()
    defn = ToolDefinition(name="temp_tool", description="Temp", id="temp.temp_tool")
    registry.register(defn, lambda: "ok")

    assert "temp_tool" in registry
    assert registry.get_by_id("temp.temp_tool") is not None

    # Unregister by name
    removed = registry.unregister("temp_tool")
    assert removed is True
    assert "temp_tool" not in registry
    assert registry.get_by_id("temp.temp_tool") is None

    # Re-register and unregister by ID
    registry.register(defn, lambda: "ok")
    removed_by_id = registry.unregister("temp.temp_tool")
    assert removed_by_id is True
    assert "temp_tool" not in registry


def test_registry_search_and_filtering():
    """Verify searching and filtering capabilities by type and risk."""
    registry = ToolRegistry()

    t1 = ToolDefinition(
        name="read_file",
        description="Read file content from disk",
        capability_type=CapabilityType.NATIVE,
        risk_level=RiskLevel.LOW,
    )
    t2 = ToolDefinition(
        name="github_create_issue",
        description="Create an issue on GitHub",
        capability_type=CapabilityType.CONNECTOR,
        risk_level=RiskLevel.HIGH,
        requires_approval=True,
    )
    t3 = ToolDefinition(
        name="mcp_fetch_doc",
        description="Fetch document from MCP server",
        capability_type=CapabilityType.MCP,
        risk_level=RiskLevel.MEDIUM,
    )

    registry.register(t1, lambda: "1")
    registry.register(t2, lambda: "2")
    registry.register(t3, lambda: "3")

    # Search keyword
    hits = registry.search("github")
    assert len(hits) == 1
    assert hits[0].name == "github_create_issue"

    # Filter by capability_type
    native_tools = registry.list_capabilities(capability_type=CapabilityType.NATIVE)
    assert len(native_tools) == 1
    assert native_tools[0].name == "read_file"

    mcp_tools = registry.list_capabilities(capability_type=CapabilityType.MCP)
    assert len(mcp_tools) == 1
    assert mcp_tools[0].name == "mcp_fetch_doc"

    # Filter by risk_level
    high_risk = registry.list_capabilities(risk_level=RiskLevel.HIGH)
    assert len(high_risk) == 1
    assert high_risk[0].name == "github_create_issue"


def test_tool_call_and_result():
    """Verify ToolCall and ToolResult models."""
    tc = ToolCall(id="call_123", name="test_tool", arguments={"a": 1})
    assert tc.id == "call_123"
    assert tc.name == "test_tool"
    assert tc.arguments == {"a": 1}

    tr = ToolResult(tool_call_id="call_123", name="test_tool", content="ok")
    assert tr.is_error is False
    msg = tr.to_message_dict()
    assert msg["role"] == "tool"
    assert msg["content"] == "ok"
