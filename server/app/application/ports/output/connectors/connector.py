"""Output port protocol for provider-neutral external connectors."""

from typing import Any, Protocol, runtime_checkable

from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolDefinition


@runtime_checkable
class BaseConnector(Protocol):
    """Abstract connector port bridging ByteBuddhi to an external service."""

    connector_id: str
    name: str

    async def connect(self) -> None:
        """Establish or verify connectivity to the provider."""
        ...

    async def disconnect(self) -> None:
        """Release any client sessions or resources."""
        ...

    def get_capabilities(self) -> list[ToolDefinition]:
        """Return list of capability definitions exposed by this connector."""
        ...

    async def invoke(
        self,
        capability_name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> Any:
        """Execute a connector capability with execution context.

        Args:
            capability_name: Short function name (e.g. 'github_create_issue').
            arguments: Validated input arguments from the model.
            context: Trusted execution context carrying caller identity and cancellation tokens.

        Returns:
            Normalized result data (dict, list, or primitive).
        """
        ...
