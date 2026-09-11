"""Bounded performance and concurrency tests for web research (no public internet)."""

import pytest

from app.application.web.limits import WebResearchLimits
from app.application.web.models import ResearchRequest, SearchResult
from app.application.web.research_service import WebResearchService
from app.application.web.url_policy import UrlSafetyPolicy
from app.domain.exceptions.web_exceptions import ResearchBudgetExceeded
from tests.fixtures.web.fakes import (
    FakeFetcher,
    FakeRenderer,
    FakeSearchProvider,
    RecordingArtifactStore,
    StaticResolver,
    fetched_html,
)
from tests.fixtures.web.html_samples import LARGE_HTML, SIMPLE_HTML


def _make_service(count: int, delay: float, concurrent: int, duration: float) -> tuple[WebResearchService, FakeFetcher]:
    urls = [f"https://example.com/p{i}" for i in range(count)]
    results = [SearchResult(title=f"P{i}", url=u, snippet="", rank=i + 1, provider="fake") for i, u in enumerate(urls)]
    pages = {u: fetched_html(u, SIMPLE_HTML) for u in urls}
    fetcher = FakeFetcher(pages)
    fetcher.delay = delay
    service = WebResearchService(
        search_provider=FakeSearchProvider(results),
        fetcher=fetcher,
        renderer=FakeRenderer(enabled=False),
        url_policy=UrlSafetyPolicy(resolver=StaticResolver({"example.com": ("8.8.8.8",)})),
        artifact_store=RecordingArtifactStore(),
        limits=WebResearchLimits(
            max_search_results=count,
            max_pages=count,
            max_concurrent_fetches=concurrent,
            min_usable_content_chars=10,
            max_research_duration_seconds=duration,
        ),
    )
    return service, fetcher


@pytest.mark.asyncio
async def test_five_concurrent_pages_respect_semaphore() -> None:
    service, fetcher = _make_service(count=5, delay=0.02, concurrent=5, duration=10)
    result = await service.research(ResearchRequest(query="q", max_results=5, run_id="perf"))
    assert result.metadata.pages_succeeded == 5
    assert fetcher.max_seen <= 5


@pytest.mark.asyncio
async def test_max_concurrency_cap() -> None:
    service, fetcher = _make_service(count=8, delay=0.03, concurrent=2, duration=10)
    await service.research(ResearchRequest(query="q", max_results=8, run_id="perf"))
    assert fetcher.max_seen <= 2


@pytest.mark.asyncio
async def test_large_html_is_character_bounded() -> None:
    url = "https://example.com/large"
    service = WebResearchService(
        search_provider=FakeSearchProvider([SearchResult(title="Large", url=url, snippet="", rank=1, provider="fake")]),
        fetcher=FakeFetcher({url: fetched_html(url, LARGE_HTML)}),
        renderer=FakeRenderer(enabled=False),
        url_policy=UrlSafetyPolicy(resolver=StaticResolver({"example.com": ("8.8.8.8",)})),
        artifact_store=RecordingArtifactStore(),
        limits=WebResearchLimits(
            min_usable_content_chars=10,
            max_extracted_chars_per_page=500,
            max_total_research_chars=500,
            preview_chars=100,
        ),
    )
    result = await service.research(ResearchRequest(query="large", max_results=1, run_id="perf"))
    assert result.sources[0].content_length <= 600
    assert len(result.sources[0].bounded_preview) <= 100


@pytest.mark.asyncio
async def test_timeout_budget_enforced() -> None:
    service, _ = _make_service(count=1, delay=1.0, concurrent=1, duration=0.05)
    with pytest.raises(ResearchBudgetExceeded):
        await service.research(ResearchRequest(query="q", max_results=1, run_id="perf"))
