"""Unit tests for MCP integration: client manager, capability allowlists, and mock client."""

from unittest.mock import AsyncMock

import pytest

from app.application.tools.definition import CapabilityType
from app.application.tools.registry import ToolRegistry
from app.domain.models.mcp import MCPServerConfig
from app.infrastructure.mcp.client_manager import MCPCapabilityManager
from app.infrastructure.mcp.mock_mcp_client import MockMCPClient


@pytest.mark.asyncio
async def test_mcp_capability_manager_allowlist_filtering():
    """Verify MCPCapabilityManager filters tools according to capability_allowlist."""
    registry = ToolRegistry()
    manager = MCPCapabilityManager(registry=registry)

    # Server provides 3 tools: tool_a, tool_b, tool_c
    # But allowlist only allows tool_a and tool_c
    config = MCPServerConfig(
        name="docs_server",
        transport="stdio",
        command="dummy_cmd",
        capability_allowlist=["tool_a", "tool_c"],
    )

    mock_client = MockMCPClient(
        server_config=config,
        available_tools=[
            {
                "name": "tool_a",
                "description": "Allowed tool A",
                "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}},
            },
            {
                "name": "tool_b",
                "description": "Blocked tool B (not in allowlist)",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "tool_c",
                "description": "Allowed tool C",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ],
    )

    manager.register_server(config, client=mock_client)
    caps = await manager.discover_capabilities("docs_server")

    # Only 2 capabilities should be discovered and registered
    assert len(caps) == 2
    discovered_names = {defn.name for defn, _ in caps}
    assert discovered_names == {"mcp_docs_server_tool_a", "mcp_docs_server_tool_c"}

    # Check that tool_b was not registered in the ToolRegistry
    assert "mcp_docs_server_tool_b" not in registry
    assert "mcp_docs_server_tool_a" in registry
    assert "mcp_docs_server_tool_c" in registry

    # Verify definition metadata
    tool_a_def = registry.get("mcp_docs_server_tool_a")[0]
    assert tool_a_def.capability_type == CapabilityType.MCP
    assert tool_a_def.id == "mcp.docs_server.tool_a"


@pytest.mark.asyncio
async def test_mcp_tool_invocation_routing():
    """Verify invoking a discovered MCP tool routes to the client and returns formatted result."""
    registry = ToolRegistry()
    manager = MCPCapabilityManager(registry=registry)

    config = MCPServerConfig(
        name="echo_server",
        transport="stdio",
        command="dummy_cmd",
        capability_allowlist=["echo"],
    )

    mock_client = MockMCPClient(
        server_config=config,
        available_tools=[
            {
                "name": "echo",
                "description": "Echoes back message",
                "inputSchema": {"type": "object", "properties": {"msg": {"type": "string"}}},
            }
        ],
    )

    manager.register_server(config, client=mock_client)
    await manager.discover_capabilities("echo_server")

    # Call the tool handler via registry
    _, handler = registry.get("mcp_echo_server_echo")
    res = await handler(msg="hello MCP")
    assert res["status"] == "success"
    assert res["tool"] == "echo"
    assert res["arguments"] == {"msg": "hello MCP"}


@pytest.mark.asyncio
async def test_mcp_server_failure_isolation():
    """Verify server connection failure does not crash the manager or prevent others from working."""
    registry = ToolRegistry()
    manager = MCPCapabilityManager(registry=registry)

    # Failing client
    failing_config = MCPServerConfig(name="broken_server", transport="stdio", command="bad_cmd")
    failing_client = MockMCPClient(server_config=failing_config)
    failing_client.connect = AsyncMock(side_effect=RuntimeError("Process terminated abruptly"))  # type: ignore[method-assign]

    manager.register_server(failing_config, client=failing_client)

    # Discovering broken server logs error and returns empty list, does not raise
    caps = await manager.discover_capabilities("broken_server")
    assert caps == []
    assert len(registry) == 0
