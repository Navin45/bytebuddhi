"""WebResearchService orchestration, ordering, bounds, and artifact tests."""

import asyncio

import pytest

from app.application.web.limits import WebResearchLimits
from app.application.web.models import ResearchRequest, SearchResult
from app.application.web.research_service import WebResearchService
from app.application.web.url_policy import UrlSafetyPolicy
from app.domain.exceptions.web_exceptions import InvalidResearchRequest, ResearchCancelled
from tests.fixtures.web.fakes import (
    FakeFetcher,
    FakeRenderer,
    FakeSearchProvider,
    RecordingArtifactStore,
    StaticResolver,
    fetched_html,
)
from tests.fixtures.web.html_samples import JS_ONLY_HTML, PROMPT_INJECTION_HTML, SIMPLE_HTML


def _service(
    results: list[SearchResult],
    pages: dict,
    renderer: FakeRenderer | None = None,
    limits: WebResearchLimits | None = None,
) -> tuple[WebResearchService, RecordingArtifactStore, FakeFetcher]:
    store = RecordingArtifactStore()
    fetcher = FakeFetcher(pages)
    search = FakeSearchProvider(results)
    policy = UrlSafetyPolicy(
        resolver=StaticResolver({"example.com": ("8.8.8.8",)}),
    )
    service = WebResearchService(
        search_provider=search,
        fetcher=fetcher,
        renderer=renderer or FakeRenderer(enabled=False),
        url_policy=policy,
        artifact_store=store,
        limits=limits or WebResearchLimits(min_usable_content_chars=20, preview_chars=200),
    )
    return service, store, fetcher


@pytest.mark.asyncio
async def test_research_orders_by_search_rank_not_completion() -> None:
    slow = "https://example.com/slow"
    fast = "https://example.com/fast"
    results = [
        SearchResult(title="Slow", url=slow, snippet="", rank=1, provider="fake"),
        SearchResult(title="Fast", url=fast, snippet="", rank=2, provider="fake"),
    ]
    pages = {
        slow: fetched_html(slow, SIMPLE_HTML),
        fast: fetched_html(fast, SIMPLE_HTML),
    }
    service, _, fetcher = _service(results, pages)
    fetcher.delay = 0.05
    result = await service.research(ResearchRequest(query="example", max_results=5, run_id="run1", project_id="proj_a"))
    assert [source.rank for source in result.sources] == sorted(source.rank for source in result.sources)
    assert result.sources[0].url == slow


@pytest.mark.asyncio
async def test_research_deduplicates_equivalent_urls() -> None:
    results = [
        SearchResult(title="A", url="https://example.com/a#frag", snippet="", rank=1, provider="fake"),
        SearchResult(title="B", url="https://example.com/a", snippet="", rank=2, provider="fake"),
    ]
    pages = {"https://example.com/a#frag": fetched_html("https://example.com/a#frag", SIMPLE_HTML)}
    service, _, fetcher = _service(results, pages)
    result = await service.research(ResearchRequest(query="dup", max_results=5, run_id="run1"))
    assert fetcher.calls.count("https://example.com/a#frag") == 1
    assert "https://example.com/a" not in fetcher.calls
    assert result.metadata.pages_attempted == 1


@pytest.mark.asyncio
async def test_large_content_stored_as_project_scoped_artifact() -> None:
    url = "https://example.com/doc"
    results = [SearchResult(title="Doc", url=url, snippet="", rank=1, provider="fake")]
    pages = {url: fetched_html(url, SIMPLE_HTML)}
    service, store, _ = _service(results, pages)
    result = await service.research(
        ResearchRequest(query="doc", max_results=1, run_id="run9", project_id="proj_a", user_id="user_a")
    )
    assert result.sources[0].artifact_id
    assert store.saved[0]["project_id"] == "proj_a"
    assert result.sources[0].bounded_preview
    assert "Welcome to the example guide" in result.sources[0].bounded_preview


@pytest.mark.asyncio
async def test_render_fallback_when_http_content_thin() -> None:
    url = "https://example.com/app"
    results = [SearchResult(title="App", url=url, snippet="", rank=1, provider="fake")]
    pages = {url: fetched_html(url, JS_ONLY_HTML)}
    renderer = FakeRenderer(html_by_url={url: SIMPLE_HTML}, enabled=True)
    service, _, _ = _service(results, pages, renderer=renderer, limits=WebResearchLimits(min_usable_content_chars=80))
    result = await service.research(ResearchRequest(query="app", max_results=1, run_id="run2"))
    assert renderer.calls == [url]
    assert result.metadata.render_fallbacks == 1
    assert result.sources[0].extraction_method.value == "render"


@pytest.mark.asyncio
async def test_empty_query_rejected() -> None:
    service, _, _ = _service([], {})
    with pytest.raises(InvalidResearchRequest):
        await service.research(ResearchRequest(query="  ", max_results=1, run_id="run"))


@pytest.mark.asyncio
async def test_cancellation_raises_research_cancelled() -> None:
    url = "https://example.com/slow"
    results = [SearchResult(title="S", url=url, snippet="", rank=1, provider="fake")]
    pages = {url: fetched_html(url, SIMPLE_HTML)}
    service, _, fetcher = _service(results, pages)
    fetcher.delay = 1.0
    token = asyncio.Event()
    token.set()
    with pytest.raises(ResearchCancelled):
        await service.research(
            ResearchRequest(query="slow", max_results=1, run_id="run"),
            cancellation_token=token,
        )


@pytest.mark.asyncio
async def test_prompt_injection_remains_untrusted_preview() -> None:
    url = "https://example.com/attack"
    results = [SearchResult(title="Attack", url=url, snippet="", rank=1, provider="fake")]
    pages = {url: fetched_html(url, PROMPT_INJECTION_HTML)}
    service, store, _ = _service(results, pages)
    result = await service.research(ResearchRequest(query="attack", max_results=1, run_id="run", project_id="proj_a"))
    assert "untrusted" in result.untrusted_content_notice.lower()
    preview = result.sources[0].bounded_preview
    assert "Ignore previous instructions" in preview
    assert store.saved[0]["metadata"]["untrusted"] is True
    payload = result.to_tool_payload()
    assert payload["untrusted_content_notice"]
    assert "Ignore previous instructions" in str(payload["sources"])
