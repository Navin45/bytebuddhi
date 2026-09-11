"""Application port for provider-agnostic public web search."""

from typing import Protocol, runtime_checkable

from app.application.web.models import SearchRequest, SearchResponse


@runtime_checkable
class WebSearchProvider(Protocol):
    """Async search port. Application code must not import concrete providers."""

    @property
    def provider_name(self) -> str:
        """Stable, low-cardinality provider identifier for telemetry."""
        ...

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Search the public web and return normalized application models."""
        ...

    async def aclose(self) -> None:
        """Release provider resources."""
        ...
