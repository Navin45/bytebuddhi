"""DuckDuckGo HTML search adapter tests (no live network)."""

import httpx
import pytest

from app.application.web.limits import WebResearchLimits
from app.application.web.models import SearchRequest
from app.infrastructure.web.search.duckduckgo import DuckDuckGoSearchProvider
from tests.fixtures.web.html_samples import DDG_HTML


@pytest.mark.asyncio
async def test_duckduckgo_provider_normalizes_results_and_unwraps_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, text=DDG_HTML, headers={"content-type": "text/html"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DuckDuckGoSearchProvider(limits=WebResearchLimits(max_search_results=5), client=client)
    response = await provider.search(SearchRequest(query="example", max_results=5, timeout_seconds=5))
    assert response.provider == "duckduckgo"
    assert response.results[0].title == "First Result"
    assert response.results[0].url == "https://example.com/a"
    assert response.results[0].rank == 1
    assert response.results[1].url == "https://example.com/b"
    assert response.results[1].rank == 2
    await provider.aclose()


@pytest.mark.asyncio
async def test_duckduckgo_clamps_max_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=DDG_HTML)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DuckDuckGoSearchProvider(limits=WebResearchLimits(max_search_results=1), client=client)
    response = await provider.search(SearchRequest(query="example", max_results=50, timeout_seconds=5))
    assert len(response.results) == 1
    await provider.aclose()
