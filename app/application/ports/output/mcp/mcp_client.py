"""Output port protocol for MCP client sessions."""

from typing import Any, Protocol, runtime_checkable

from app.domain.models.mcp import MCPPrompt, MCPResource


@runtime_checkable
class MCPClient(Protocol):
    """Abstract port for communicating with an MCP server."""

    async def connect(self) -> None:
        """Establish session with the server and perform handshake."""
        ...

    async def list_tools(self) -> list[dict[str, Any]]:
        """Discover tools exposed by the MCP server."""
        ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool on the MCP server and return response dict."""
        ...

    async def list_resources(self) -> list[MCPResource]:
        """List resources exposed by the MCP server."""
        ...

    async def read_resource(self, uri: str) -> str:
        """Read content of an MCP resource."""
        ...

    async def list_prompts(self) -> list[MCPPrompt]:
        """List prompts discovered from the MCP server."""
        ...

    async def close(self) -> None:
        """Terminate the MCP session and release connections/processes."""
        ...
