"""Test doubles for web research ports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.application.web.models import (
    FetchedDocument,
    FetchRequest,
    RenderedDocument,
    RenderRequest,
    SearchRequest,
    SearchResponse,
    SearchResult,
    utc_now,
)
from app.application.web.url_policy import HostnameResolver
from app.domain.exceptions.web_exceptions import (
    FetchTimeout,
    RenderFailed,
    UnsafeUrl,
)


class StaticResolver(HostnameResolver):
    """Maps hostnames to preconfigured addresses without touching real DNS."""

    def __init__(self, mapping: dict[str, tuple[str, ...]] | None = None) -> None:
        self.mapping = mapping or {}
        self.calls: list[str] = []

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        self.calls.append(hostname)
        if hostname not in self.mapping:
            raise UnsafeUrl(f"Test resolver has no mapping for '{hostname}'", url=hostname)
        return self.mapping[hostname]


class FakeSearchProvider:
    def __init__(self, results: list[SearchResult] | None = None, delay: float = 0.0) -> None:
        self._results = results or []
        self.delay = delay
        self.calls: list[SearchRequest] = []
        self.closed = False

    @property
    def provider_name(self) -> str:
        return "fake"

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.calls.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        return SearchResponse(
            query=request.query,
            provider=self.provider_name,
            results=tuple(self._results[: request.max_results]),
        )

    async def aclose(self) -> None:
        self.closed = True


class FakeFetcher:
    def __init__(self, pages: dict[str, FetchedDocument] | None = None) -> None:
        self.pages = pages or {}
        self.calls: list[str] = []
        self.current = 0
        self.max_seen = 0
        self.delay = 0.0
        self.closed = False

    async def fetch(self, request: FetchRequest) -> FetchedDocument:
        self.calls.append(request.url)
        self.current += 1
        self.max_seen = max(self.max_seen, self.current)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if request.url not in self.pages:
                raise FetchTimeout("missing fixture page")
            return self.pages[request.url]
        finally:
            self.current -= 1

    async def aclose(self) -> None:
        self.closed = True


class FakeRenderer:
    def __init__(self, html_by_url: dict[str, str] | None = None, enabled: bool = True) -> None:
        self.html_by_url = html_by_url or {}
        self._enabled = enabled
        self.calls: list[str] = []
        self.closed = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def render(self, request: RenderRequest) -> RenderedDocument:
        self.calls.append(request.url)
        html = self.html_by_url.get(request.url)
        if html is None:
            raise RenderFailed("no rendered html")
        return RenderedDocument(url=request.url, final_url=request.url, html=html, retrieved_at=utc_now())

    async def aclose(self) -> None:
        self.closed = True


class PolicyAwareFakeRenderer(FakeRenderer):
    """Renderer that applies URL policy before 'navigation' (browser SSRF stand-in)."""

    def __init__(self, url_policy, html_by_url: dict[str, str] | None = None) -> None:
        super().__init__(html_by_url=html_by_url, enabled=True)
        self.url_policy = url_policy

    async def render(self, request: RenderRequest) -> RenderedDocument:
        await self.url_policy.assert_safe(request.url)
        return await super().render(request)


def fetched_html(url: str, html: str, status_code: int = 200) -> FetchedDocument:
    return FetchedDocument(
        url=url,
        final_url=url,
        status_code=status_code,
        content_type="text/html",
        encoding="utf-8",
        body=html,
        raw_byte_length=len(html.encode("utf-8")),
        retrieved_at=utc_now(),
        redirect_count=0,
    )


@dataclass
class RecordingArtifactStore:
    saved: list[dict[str, object]] = field(default_factory=list)
    contents: dict[tuple[str, str | None], str] = field(default_factory=dict)

    async def save_artifact(
        self,
        artifact_id: str,
        content: str | bytes,
        metadata: dict | None = None,
        project_id: str | None = None,
    ) -> str:
        text = content.decode("utf-8") if isinstance(content, bytes) else content
        self.saved.append(
            {
                "artifact_id": artifact_id,
                "project_id": project_id,
                "metadata": metadata or {},
                "content": text,
            }
        )
        self.contents[(artifact_id, project_id)] = text
        return artifact_id

    async def get_artifact(self, artifact_id: str, project_id: str | None = None) -> str | bytes | None:
        return self.contents.get((artifact_id, project_id))

    async def delete_artifact(self, artifact_id: str, project_id: str | None = None) -> bool:
        return self.contents.pop((artifact_id, project_id), None) is not None

    async def artifact_exists(self, artifact_id: str, project_id: str | None = None) -> bool:
        return (artifact_id, project_id) in self.contents
