"""Domain models for Model Context Protocol (MCP) server configuration and capabilities."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPServerConfig:
    """Configuration for an approved Model Context Protocol server.

    Security Rule:
        Only pre-configured and approved MCPServerConfig instances can be contacted
        or executed by ByteBuddhi. Arbitrary model-specified URLs/commands are strictly blocked.
    """

    server_id: str = ""
    name: str = ""
    transport: str | None = None
    transport_type: str = "stdio"  # "stdio" | "sse" | "http"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    enabled: bool = True
    capability_allowlist: list[str] | None = None  # None allows all; list restricts to named tools

    def __post_init__(self) -> None:
        if not self.server_id and self.name:
            self.server_id = self.name
        elif not self.name and self.server_id:
            self.name = self.server_id

        if self.transport and not self.transport_type:
            self.transport_type = self.transport
        elif self.transport_type and not self.transport:
            self.transport = self.transport_type


@dataclass(frozen=True)
class MCPResource:
    """An external context/data resource exposed by an MCP server."""

    uri: str
    name: str
    description: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class MCPPrompt:
    """A prompt template discovered from an MCP server."""

    name: str
    description: str | None = None
    arguments: list[dict[str, Any]] = field(default_factory=list)
