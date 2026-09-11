"""Application port for optional JavaScript rendering of public pages."""

from typing import Protocol, runtime_checkable

from app.application.web.models import RenderedDocument, RenderRequest


@runtime_checkable
class WebRenderer(Protocol):
    """Async browser render port. Application code must not import Playwright."""

    @property
    def enabled(self) -> bool:
        """Whether rendering is configured and available."""
        ...

    async def render(self, request: RenderRequest) -> RenderedDocument:
        """Render a page and return HTML. Must enforce the same URL safety policy."""
        ...

    async def aclose(self) -> None:
        """Close browser instances, contexts, and pages."""
        ...
