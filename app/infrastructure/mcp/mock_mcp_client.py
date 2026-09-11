"""In-memory MockMCPClient implementation for testing and isolation."""

from collections.abc import Callable
from typing import Any

from app.application.ports.output.mcp.mcp_client import MCPClient
from app.domain.models.mcp import MCPPrompt, MCPResource


class MockMCPClient(MCPClient):
    """In-memory MCP client simulating server communication without OS subprocesses."""

    def __init__(
        self,
        tools: list[dict[str, Any]] | None = None,
        handlers: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
        resources: list[MCPResource] | None = None,
        prompts: list[MCPPrompt] | None = None,
        available_tools: list[dict[str, Any]] | None = None,
        server_config: Any | None = None,
    ) -> None:
        self._tools = available_tools if available_tools is not None else (tools or [])
        self._handlers = handlers or {}
        self._resources = resources or []
        self._prompts = prompts or []
        self.server_config = server_config
        self.is_connected = False
        self.is_closed = False

    async def connect(self) -> None:
        self.is_connected = True

    async def list_tools(self) -> list[dict[str, Any]]:
        if not self.is_connected:
            raise ConnectionError("MockMCPClient not connected")
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.is_connected:
            raise ConnectionError("MockMCPClient not connected")

        if name in self._handlers:
            result = self._handlers[name](arguments)
            if isinstance(result, dict) and "content" in result:
                return result
            return {
                "status": "success",
                "tool": name,
                "arguments": arguments,
                "content": [{"type": "text", "text": str(result)}],
                "isError": False,
            }

        return {
            "status": "success",
            "tool": name,
            "arguments": arguments,
            "content": [{"type": "text", "text": f"Mock executed {name} with {arguments}"}],
            "isError": False,
        }

    async def list_resources(self) -> list[MCPResource]:
        return list(self._resources)

    async def read_resource(self, uri: str) -> str:
        for r in self._resources:
            if r.uri == uri:
                return f"Content of {uri}"
        raise FileNotFoundError(f"MCP resource not found: {uri}")

    async def list_prompts(self) -> list[MCPPrompt]:
        return list(self._prompts)

    async def close(self) -> None:
        self.is_closed = True
        self.is_connected = False
