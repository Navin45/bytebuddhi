"""Security tests for web research: SSRF, identity, artifacts, injection, resources."""

import asyncio

import httpx
import pytest

from app.application.policy.tool_policy import ToolPolicyEngine
from app.application.tools.builtin.web_research import create_web_research_tool
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.application.web.limits import WebResearchLimits
from app.application.web.models import ResearchRequest, SearchResult
from app.application.web.research_service import WebResearchService
from app.application.web.url_policy import UrlSafetyPolicy
from app.domain.exceptions.web_exceptions import (
    ContentTooLarge,
    PrivateAddressBlocked,
    ResearchBudgetExceeded,
    ResearchCancelled,
    UnsafeUrl,
)
from app.domain.models.execution_context import ExecutionContext
from app.domain.models.workspace import Workspace
from app.infrastructure.storage.local_artifact_store import LocalArtifactStore
from app.infrastructure.web.fetch.httpx_fetcher import HttpxWebFetcher
from tests.fixtures.web.fakes import (
    FakeFetcher,
    FakeSearchProvider,
    PolicyAwareFakeRenderer,
    RecordingArtifactStore,
    StaticResolver,
    fetched_html,
)
from tests.fixtures.web.html_samples import PROMPT_INJECTION_HTML, SIMPLE_HTML


def _url_policy() -> UrlSafetyPolicy:
    return UrlSafetyPolicy(resolver=StaticResolver({"public.example": ("8.8.8.8",)}))


@pytest.mark.asyncio
async def test_attack_a_localhost_ssrf() -> None:
    with pytest.raises(PrivateAddressBlocked):
        await _url_policy().assert_safe("http://localhost/admin")


@pytest.mark.asyncio
async def test_attack_b_loopback_ssrf() -> None:
    policy = _url_policy()
    with pytest.raises(PrivateAddressBlocked):
        await policy.assert_safe("http://127.0.0.1/")
    with pytest.raises(PrivateAddressBlocked):
        await policy.assert_safe("http://[::1]/")


@pytest.mark.asyncio
async def test_attack_c_private_ip_ssrf() -> None:
    policy = _url_policy()
    for url in ("http://10.1.2.3/", "http://172.16.0.9/", "http://192.168.0.5/"):
        with pytest.raises(PrivateAddressBlocked):
            await policy.assert_safe(url)


@pytest.mark.asyncio
async def test_attack_d_cloud_metadata() -> None:
    with pytest.raises(PrivateAddressBlocked):
        await _url_policy().assert_safe("http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
async def test_attack_e_redirect_ssrf() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    fetcher = HttpxWebFetcher(
        url_policy=_url_policy(),
        limits=WebResearchLimits(max_retries=1),
        client=client,
    )
    from app.application.web.models import FetchRequest

    with pytest.raises(PrivateAddressBlocked):
        await fetcher.fetch(
            FetchRequest(
                url="https://public.example/page",
                timeout_seconds=5,
                max_response_bytes=1000,
                max_redirects=3,
            )
        )
    await fetcher.aclose()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "data:text/html,x", "javascript:alert(1)"])
@pytest.mark.asyncio
async def test_attack_f_unsupported_scheme(url: str) -> None:
    with pytest.raises(UnsafeUrl):
        await _url_policy().assert_safe(url)


@pytest.mark.asyncio
async def test_attack_g_oversized_response_streaming() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"y" * 10_000, headers={"content-type": "text/plain"})

    fetcher = HttpxWebFetcher(
        url_policy=_url_policy(),
        limits=WebResearchLimits(max_response_bytes=256, max_retries=1),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    from app.application.web.models import FetchRequest

    with pytest.raises(ContentTooLarge):
        await fetcher.fetch(
            FetchRequest(
                url="https://public.example/page",
                timeout_seconds=5,
                max_response_bytes=256,
                max_redirects=1,
            )
        )
    await fetcher.aclose()


def test_attack_h_malicious_html_not_treated_as_page_text() -> None:
    from app.application.web.extractor import extract_html
    from tests.fixtures.web.html_samples import MALICIOUS_HTML

    extracted = extract_html(MALICIOUS_HTML)
    assert "document.cookie" not in extracted.markdown
    assert "Safe paragraph" in extracted.markdown


@pytest.mark.asyncio
async def test_attack_i_prompt_injection_cannot_alter_authorization() -> None:
    url = "https://public.example/page"
    store = RecordingArtifactStore()
    service = WebResearchService(
        search_provider=FakeSearchProvider(
            [SearchResult(title="Attack", url=url, snippet="", rank=1, provider="fake")]
        ),
        fetcher=FakeFetcher({url: fetched_html(url, PROMPT_INJECTION_HTML)}),
        renderer=PolicyAwareFakeRenderer(_url_policy()),
        url_policy=_url_policy(),
        artifact_store=store,
        limits=WebResearchLimits(min_usable_content_chars=10),
    )
    ws = Workspace.create(root_path=".")
    ctx = ToolExecutionContext.from_execution(
        ExecutionContext(
            user_id="alice",
            project_id="proj_a",
            conversation_id=None,
            run_id="run1",
            workspace_id=ws.workspace_id,
        ),
        tool_call_id="c1",
        workspace=ws,
        metadata={"approval_granted": False},
    )
    defn, handler = create_web_research_tool(service)
    registry = ToolRegistry()
    registry.register(defn, handler)
    executor = ToolExecutor(registry, policy_engine=ToolPolicyEngine(registry=registry))
    result = await executor.execute(
        ToolCall(id="c1", name="web_research", arguments={"query": "attack"}),
        context=ctx,
    )
    assert not result.is_error
    assert "approval_granted" not in ctx.metadata
    assert ctx.user_id == "alice"
    assert ctx.project_id == "proj_a"
    assert "Ignore previous instructions" in result.content
    assert "untrusted" in result.content.lower()


@pytest.mark.asyncio
async def test_attack_j_artifact_isolation(tmp_path) -> None:
    store = LocalArtifactStore(base_dir=tmp_path / "artifacts")
    await store.save_artifact("web_secret", "proj A page", project_id="proj_a")
    assert await store.get_artifact("web_secret", project_id="proj_b") is None
    assert await store.get_artifact("web_secret", project_id="proj_a") == "proj A page"


@pytest.mark.asyncio
async def test_attack_k_identity_tampering_ignored() -> None:
    url = "https://public.example/page"
    store = RecordingArtifactStore()
    service = WebResearchService(
        search_provider=FakeSearchProvider([SearchResult(title="Doc", url=url, snippet="", rank=1, provider="fake")]),
        fetcher=FakeFetcher({url: fetched_html(url, SIMPLE_HTML)}),
        renderer=PolicyAwareFakeRenderer(_url_policy()),
        url_policy=_url_policy(),
        artifact_store=store,
        limits=WebResearchLimits(min_usable_content_chars=10),
    )
    # Disable renderer for this path
    object.__setattr__(type(service._renderer), "enabled", property(lambda self: False)) if False else None
    service._renderer._enabled = False  # type: ignore[attr-defined]
    ws = Workspace.create(root_path=".")
    ctx = ToolExecutionContext.from_execution(
        ExecutionContext(
            user_id="alice",
            project_id="proj_a",
            conversation_id=None,
            run_id="run1",
            workspace_id=ws.workspace_id,
        ),
        tool_call_id="c1",
        workspace=ws,
    )
    defn, handler = create_web_research_tool(service)
    registry = ToolRegistry()
    registry.register(defn, handler)
    executor = ToolExecutor(registry)
    result = await executor.execute(
        ToolCall(
            id="c1",
            name="web_research",
            arguments={
                "query": "docs",
                "user_id": "attacker",
                "project_id": "proj_evil",
                "workspace": "/etc",
                "timeout": 9999,
            },
        ),
        context=ctx,
    )
    assert not result.is_error
    assert store.saved[0]["project_id"] == "proj_a"
    assert store.saved[0]["metadata"]["user_id"] == "alice"


@pytest.mark.asyncio
async def test_large_web_result_uses_correct_project_scope(tmp_path) -> None:
    url = "https://public.example/huge"
    huge_html = "<html><body><p>" + ("word " * 5000) + "</p></body></html>"
    store = LocalArtifactStore(base_dir=tmp_path / "artifacts")
    service = WebResearchService(
        search_provider=FakeSearchProvider([SearchResult(title="Huge", url=url, snippet="", rank=1, provider="fake")]),
        fetcher=FakeFetcher({url: fetched_html(url, huge_html)}),
        renderer=PolicyAwareFakeRenderer(_url_policy()),
        url_policy=_url_policy(),
        artifact_store=store,
        limits=WebResearchLimits(min_usable_content_chars=10, max_extracted_chars_per_page=50_000),
    )
    service._renderer._enabled = False  # type: ignore[attr-defined]
    ws = Workspace.create(root_path=tmp_path)
    ctx = ToolExecutionContext.from_execution(
        ExecutionContext(
            user_id="alice",
            project_id="proj_a",
            conversation_id=None,
            run_id="run_huge",
            workspace_id=ws.workspace_id,
        ),
        tool_call_id="c_huge",
        workspace=ws,
    )
    defn, handler = create_web_research_tool(service)
    registry = ToolRegistry()
    registry.register(defn, handler)
    executor = ToolExecutor(registry, artifact_store=store, max_output_chars=200)
    result = await executor.execute(
        ToolCall(id="c_huge", name="web_research", arguments={"query": "huge"}),
        context=ctx,
    )
    assert not result.is_error
    project_dir = tmp_path / "artifacts" / "projects" / "proj_a"
    assert project_dir.is_dir()
    assert any(project_dir.iterdir())
    assert not (tmp_path / "artifacts" / "global").exists() or not any((tmp_path / "artifacts" / "global").iterdir())
    assert await store.get_artifact("tool_out_c_huge", project_id="proj_b") is None


@pytest.mark.asyncio
async def test_attack_l_cancellation_terminates_in_flight_fetches() -> None:
    url = "https://public.example/page"
    fetcher = FakeFetcher({url: fetched_html(url, SIMPLE_HTML)})
    fetcher.delay = 2.0
    service = WebResearchService(
        search_provider=FakeSearchProvider([SearchResult(title="Doc", url=url, snippet="", rank=1, provider="fake")]),
        fetcher=fetcher,
        renderer=PolicyAwareFakeRenderer(_url_policy()),
        url_policy=_url_policy(),
        artifact_store=RecordingArtifactStore(),
        limits=WebResearchLimits(min_usable_content_chars=10, max_research_duration_seconds=30),
    )
    service._renderer._enabled = False  # type: ignore[attr-defined]
    token2 = asyncio.Event()
    token2.set()
    with pytest.raises(ResearchCancelled):
        await service.research(
            ResearchRequest(query="q", max_results=1, run_id="r"),
            cancellation_token=token2,
        )


@pytest.mark.asyncio
async def test_attack_m_timeout_does_not_exceed_research_budget() -> None:
    url = "https://public.example/page"
    fetcher = FakeFetcher({url: fetched_html(url, SIMPLE_HTML)})
    fetcher.delay = 2.0
    service = WebResearchService(
        search_provider=FakeSearchProvider([SearchResult(title="Doc", url=url, snippet="", rank=1, provider="fake")]),
        fetcher=fetcher,
        renderer=PolicyAwareFakeRenderer(_url_policy()),
        url_policy=_url_policy(),
        artifact_store=RecordingArtifactStore(),
        limits=WebResearchLimits(min_usable_content_chars=10, max_research_duration_seconds=0.05),
    )
    service._renderer._enabled = False  # type: ignore[attr-defined]
    with pytest.raises(ResearchBudgetExceeded):
        await service.research(ResearchRequest(query="q", max_results=1, run_id="r"))


@pytest.mark.asyncio
async def test_attack_n_concurrency_never_exceeds_configured_maximum() -> None:
    urls = [f"https://public.example/p{i}" for i in range(8)]
    results = [SearchResult(title=f"P{i}", url=u, snippet="", rank=i + 1, provider="fake") for i, u in enumerate(urls)]
    pages = {u: fetched_html(u, SIMPLE_HTML) for u in urls}
    fetcher = FakeFetcher(pages)
    fetcher.delay = 0.05
    service = WebResearchService(
        search_provider=FakeSearchProvider(results),
        fetcher=fetcher,
        renderer=PolicyAwareFakeRenderer(_url_policy()),
        url_policy=_url_policy(),
        artifact_store=RecordingArtifactStore(),
        limits=WebResearchLimits(
            min_usable_content_chars=10,
            max_pages=8,
            max_search_results=8,
            max_concurrent_fetches=3,
        ),
    )
    service._renderer._enabled = False  # type: ignore[attr-defined]
    await service.research(ResearchRequest(query="q", max_results=8, run_id="r"))
    assert fetcher.max_seen <= 3


@pytest.mark.asyncio
async def test_attack_o_browser_ssrf_blocked_by_url_policy() -> None:
    policy = _url_policy()
    renderer = PolicyAwareFakeRenderer(policy, html_by_url={})
    from app.application.web.models import RenderRequest

    with pytest.raises(PrivateAddressBlocked):
        await renderer.render(RenderRequest(url="http://127.0.0.1/", timeout_seconds=5, max_content_chars=100))
    with pytest.raises(PrivateAddressBlocked):
        await renderer.render(
            RenderRequest(url="http://169.254.169.254/latest/meta-data/", timeout_seconds=5, max_content_chars=100)
        )
