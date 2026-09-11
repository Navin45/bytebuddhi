"""Disabled JavaScript renderer used when rendering is off."""

from app.application.web.models import RenderedDocument, RenderRequest
from app.domain.exceptions.web_exceptions import RenderFailed


class NoOpWebRenderer:
    """WebRenderer that never launches a browser."""

    @property
    def enabled(self) -> bool:
        return False

    async def render(self, request: RenderRequest) -> RenderedDocument:
        raise RenderFailed("JavaScript rendering is disabled")

    async def aclose(self) -> None:
        return None
