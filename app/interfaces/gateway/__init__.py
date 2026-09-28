"""Gateway transport boundary for CLI and future clients.

Phase 1 establishes:

    client → GatewayClient → FastAPI → application use cases → AgentRuntime

The gateway is not a second domain layer and does not own agent execution.
"""

from app.interfaces.gateway.client import GatewayClient
from app.interfaces.gateway.config import (
    resolve_bind_address,
    resolve_execution_mode,
    resolve_gateway_endpoint,
)
from app.interfaces.gateway.manager import GatewayManager

__all__ = [
    "GatewayClient",
    "GatewayManager",
    "resolve_bind_address",
    "resolve_execution_mode",
    "resolve_gateway_endpoint",
]
