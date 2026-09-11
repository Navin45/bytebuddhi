"""Web research output ports."""

from app.application.ports.output.web.fetch import WebFetcher
from app.application.ports.output.web.render import WebRenderer
from app.application.ports.output.web.search import WebSearchProvider

__all__ = ["WebFetcher", "WebRenderer", "WebSearchProvider"]
