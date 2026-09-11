"""Application port for SSRF-safe HTTP fetching of public web pages."""

from typing import Protocol, runtime_checkable

from app.application.web.models import FetchedDocument, FetchRequest


@runtime_checkable
class WebFetcher(Protocol):
    """Async HTTP fetch port. Does not leak httpx or parser types into callers."""

    async def fetch(self, request: FetchRequest) -> FetchedDocument:
        """Fetch a URL with SSRF, redirect, timeout, and byte-limit enforcement."""
        ...

    async def aclose(self) -> None:
        """Release HTTP session resources."""
        ...
