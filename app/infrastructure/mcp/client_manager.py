"""MCP Capability Manager for lifecycle, approved server whitelists, and capability discovery."""

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from app.application.ports.output.mcp.mcp_client import MCPClient
from app.application.ports.output.observability.meter import Counter, Histogram, Meter
from app.application.ports.output.observability.tracer import Tracer
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import CapabilityType, RiskLevel, ToolDefinition
from app.application.tools.registry import ToolRegistry
from app.domain.models.mcp import MCPServerConfig
from app.domain.models.observability import MetricNames, SpanAttributes, SpanNames
from app.infrastructure.config.logger import get_logger
from app.infrastructure.mcp.mock_mcp_client import MockMCPClient
from app.infrastructure.observability.noop import NoOpMeter, NoOpTracer

logger = get_logger(__name__)


class MCPCapabilityItem(tuple[ToolDefinition, Callable[..., Any]]):
    """A 2-tuple (ToolDefinition, Callable) that exposes convenient attribute access."""

    def __new__(cls, defn: ToolDefinition, handler: Callable[..., Any]) -> "MCPCapabilityItem":
        return super().__new__(cls, (defn, handler))

    @property
    def definition(self) -> ToolDefinition:
        return self[0]

    @property
    def handler(self) -> Callable[..., Any]:
        return self[1]

    @property
    def name(self) -> str:
        return self[0].name

    @property
    def id(self) -> str | None:
        return self[0].id


class MCPCapabilityManager:
    """Coordinates lifecycle, discovery, security allowlisting, and routing for approved MCP servers."""

    def __init__(
        self,
        servers: list[MCPServerConfig] | None = None,
        client_factory: Callable[[MCPServerConfig], MCPClient] | None = None,
        registry: ToolRegistry | None = None,
        tracer: Tracer | None = None,
        meter: Meter | None = None,
    ) -> None:
        self._servers: dict[str, MCPServerConfig] = {s.server_id: s for s in (servers or [])}
        self._clients: dict[str, MCPClient] = {}
        self._client_factory = client_factory or self._default_client_factory
        self.registry = registry
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self.tracer = tracer or NoOpTracer()
        self.meter = meter or NoOpMeter()
        self._calls_counter: Counter = self.meter.create_counter(
            MetricNames.MCP_CALLS_TOTAL,
            unit="1",
            description="Total MCP capability invocations",
        )
        self._failures_counter: Counter = self.meter.create_counter(
            MetricNames.MCP_FAILURES_TOTAL,
            unit="1",
            description="Total MCP capability invocation failures",
        )
        self._duration_hist: Histogram = self.meter.create_histogram(
            MetricNames.MCP_DURATION,
            unit="s",
            description="MCP capability invocation duration in seconds",
        )

    @staticmethod
    def _default_client_factory(config: MCPServerConfig) -> MCPClient:
        """Default factory creating appropriate MCP client based on transport."""
        return MockMCPClient(server_config=config)

    def register_server(self, config: MCPServerConfig, client: MCPClient | None = None) -> None:
        """Register an approved server configuration with optional pre-configured client."""
        self._servers[config.server_id] = config
        if client is not None:
            self._clients[config.server_id] = client

    def unregister_server(self, server_id: str) -> None:
        """Remove a server configuration and close any active client."""
        self._servers.pop(server_id, None)
        client = self._clients.pop(server_id, None)
        if client:
            with contextlib.suppress(Exception):
                import asyncio

                task = asyncio.create_task(client.close())
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

    def get_server_config(self, server_id: str) -> MCPServerConfig | None:
        """Retrieve server config if approved."""
        return self._servers.get(server_id)

    def list_server_configs(self) -> list[MCPServerConfig]:
        """List all approved server configurations."""
        return list(self._servers.values())

    async def get_client(self, server_id: str) -> MCPClient:
        """Get or initialize an active client for an approved server."""
        config = self._servers.get(server_id)
        if not config:
            raise KeyError(f"Server '{server_id}' is not registered")
        if not config.enabled:
            raise ValueError(f"MCP server '{server_id}' is currently disabled")

        if server_id not in self._clients:
            client = self._client_factory(config)
            await client.connect()
            self._clients[server_id] = client

        client = self._clients[server_id]
        if hasattr(client, "is_connected") and not client.is_connected:
            await client.connect()

        return client

    async def discover_capabilities(self, server_id: str) -> list[MCPCapabilityItem]:
        """Discover tools from an approved server and normalize to ToolDefinitions with handlers."""
        if server_id not in self._servers:
            raise KeyError(f"Server '{server_id}' is not registered")

        config = self._servers[server_id]
        if not config.enabled:
            return []

        try:
            client = await self.get_client(server_id)
            mcp_tools = await client.list_tools()
        except Exception as e:
            logger.warning(
                "Failed discovering capabilities from MCP server (isolated)", server_id=server_id, error=str(e)
            )
            return []

        capabilities: list[MCPCapabilityItem] = []
        for t in mcp_tools:
            tool_name = t.get("name", "")
            if not tool_name:
                continue

            # Enforce capability allowlist
            if config.capability_allowlist is not None and tool_name not in config.capability_allowlist:
                logger.info(
                    "Skipping MCP tool disallowed by allowlist policy",
                    server_id=server_id,
                    tool_name=tool_name,
                )
                continue

            cap_id = f"mcp.{server_id}.{tool_name}"
            llm_name = f"mcp_{server_id}_{tool_name}".replace("-", "_").replace(".", "_")

            cap_def = ToolDefinition(
                name=llm_name,
                description=f"[{config.name} MCP] {t.get('description', '')}",
                parameters=t.get("inputSchema", {"type": "object", "properties": {}}),
                id=cap_id,
                capability_type=CapabilityType.MCP,
                risk_level=RiskLevel.LOW,
                metadata={"server_id": server_id, "original_tool_name": tool_name},
            )

            # Build handler closure
            orig_tool = tool_name
            sid = server_id

            async def _handler(
                _sid: str = sid, _orig: str = orig_tool, context: ToolExecutionContext | None = None, **kwargs: Any
            ) -> Any:
                return await self.invoke_capability(
                    server_id=_sid,
                    tool_name=_orig,
                    arguments=kwargs,
                    context=context,
                )

            item = MCPCapabilityItem(cap_def, _handler)
            capabilities.append(item)

            if self.registry is not None:
                self.registry.register(cap_def, _handler)

        return capabilities

    async def invoke_capability(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        """Invoke an MCP tool with security validation and failure isolation."""
        import time

        start_time = time.monotonic()
        with self.tracer.start_as_current_span(
            SpanNames.MCP_EXECUTE,
            attributes={
                SpanAttributes.MCP_SERVER: server_id[:50],
                SpanAttributes.MCP_CAPABILITY: tool_name[:50],
            },
        ):
            self._calls_counter.add(1, {"mcp_server": server_id[:50]})
            try:
                if server_id not in self._servers:
                    raise KeyError(f"Server '{server_id}' is not registered")

                config = self._servers[server_id]
                if not config.enabled:
                    raise PermissionError(f"Security error: MCP server '{server_id}' is not approved or enabled")

                # Allowlist enforcement at invocation time
                if config.capability_allowlist is not None and tool_name not in config.capability_allowlist:
                    raise PermissionError(
                        f"Security violation: Tool '{tool_name}' on server '{server_id}' is not permitted by allowlist"
                    )

                if context and context.is_cancelled:
                    raise TimeoutError("Execution cancelled before MCP tool invocation")

                client = await self.get_client(server_id)
                try:
                    raw_result = await client.call_tool(tool_name, arguments)
                except Exception as e:
                    logger.error("MCP tool invocation error", server_id=server_id, tool_name=tool_name, error=str(e))
                    raise

                # Normalize result content
                is_error = bool(raw_result.get("isError", False))
                content_items = raw_result.get("content", [])
                text_parts = []
                for item in content_items:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        text_parts.append(item)
                    else:
                        text_parts.append(str(item))

                merged_text = "\n".join(text_parts) if text_parts else str(raw_result)
                if is_error:
                    raise RuntimeError(f"MCP server reported error during tool execution: {merged_text}")

                return {
                    "status": raw_result.get("status", "success"),
                    "tool": raw_result.get("tool", tool_name),
                    "arguments": raw_result.get("arguments", arguments),
                    "result": merged_text,
                    "raw": raw_result,
                }
            except Exception:
                self._failures_counter.add(1, {"mcp_server": server_id[:50]})
                raise
            finally:
                duration = time.monotonic() - start_time
                self._duration_hist.record(duration, {"mcp_server": server_id[:50]})

    async def register_all_into_registry(self, registry: ToolRegistry) -> list[ToolDefinition]:
        """Discover and register all approved server capabilities into the unified registry."""
        registered = []
        for server_id, config in self._servers.items():
            if not config.enabled:
                continue
            caps = await self.discover_capabilities(server_id)
            for cap_item in caps:
                defn, handler = cap_item
                registry.register(defn, handler)
                registered.append(defn)
        return registered

    async def close_all(self) -> None:
        """Close all active MCP client sessions."""
        for client in self._clients.values():
            with contextlib.suppress(Exception):
                await client.close()
        self._clients.clear()
