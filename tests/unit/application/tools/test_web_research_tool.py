"""web_research tool contract tests."""

import pytest

from app.application.tools.builtin.web_research import create_web_research_tool
from app.application.tools.definition import RiskLevel
from app.application.web.limits import WebResearchLimits
from app.application.web.models import SearchResult
from app.application.web.research_service import WebResearchService
from app.application.web.url_policy import UrlSafetyPolicy
from tests.fixtures.web.fakes import (
    FakeFetcher,
    FakeRenderer,
    FakeSearchProvider,
    RecordingArtifactStore,
    StaticResolver,
    fetched_html,
)
from tests.fixtures.web.html_samples import SIMPLE_HTML


@pytest.mark.asyncio
async def test_web_research_tool_schema_does_not_expose_security_knobs() -> None:
    service = WebResearchService(
        search_provider=FakeSearchProvider([]),
        fetcher=FakeFetcher({}),
        renderer=FakeRenderer(enabled=False),
        url_policy=UrlSafetyPolicy(resolver=StaticResolver({})),
        artifact_store=RecordingArtifactStore(),
        limits=WebResearchLimits(),
    )
    definition, _handler = create_web_research_tool(service)
    props = definition.parameters["properties"]
    assert set(props) <= {"query", "max_results"}
    assert "timeout" not in props
    assert "headers" not in props
    assert "url" not in props
    assert definition.risk_level == RiskLevel.MEDIUM
    assert definition.parameters.get("additionalProperties") is False


@pytest.mark.asyncio
async def test_tool_clamps_max_results() -> None:
    url = "https://example.com/a"
    results = [
        SearchResult(title="R1", url=url, snippet="", rank=1, provider="fake"),
    ]
    service = WebResearchService(
        search_provider=FakeSearchProvider(results),
        fetcher=FakeFetcher({url: fetched_html(url, SIMPLE_HTML)}),
        renderer=FakeRenderer(enabled=False),
        url_policy=UrlSafetyPolicy(resolver=StaticResolver({"example.com": ("8.8.8.8",)})),
        artifact_store=RecordingArtifactStore(),
        limits=WebResearchLimits(max_search_results=1, min_usable_content_chars=10),
    )
    _defn, handler = create_web_research_tool(service)
    payload = await handler(query="q", max_results=99)
    assert payload["metadata"]["search_result_count"] <= 1
