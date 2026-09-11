"""Integration tests for search → fetch → extract → ArtifactStore → ToolExecutor → AgentRuntime."""

import httpx
import pytest

from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus
from app.application.policy.tool_policy import ToolPolicyEngine
from app.application.ports.output.llm.model_gateway import ModelGateway, ModelResponse
from app.application.tools.builtin.web_research import create_web_research_tool
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.application.web.limits import WebResearchLimits
from app.application.web.research_service import WebResearchService
from app.application.web.url_policy import UrlSafetyPolicy
from app.domain.models.execution_context import ExecutionContext
from app.domain.models.workspace import Workspace
from app.infrastructure.storage.local_artifact_store import LocalArtifactStore
from app.infrastructure.web.fetch.httpx_fetcher import HttpxWebFetcher
from app.infrastructure.web.render.noop import NoOpWebRenderer
from app.infrastructure.web.search.duckduckgo import DuckDuckGoSearchProvider
from tests.fixtures.web.fakes import StaticResolver
from tests.fixtures.web.html_samples import DDG_HTML, SIMPLE_HTML


class _ScriptedGateway(ModelGateway):
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.call_count = 0

    async def generate(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return ModelResponse(content="done")

    async def stream(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        if False:
            yield


def _stack(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "duckduckgo" in url or request.method == "POST":
            return httpx.Response(200, text=DDG_HTML, headers={"content-type": "text/html"})
        if "example.com/a" in url:
            return httpx.Response(200, text=SIMPLE_HTML, headers={"content-type": "text/html"})
        if "example.com/b" in url:
            return httpx.Response(200, text=SIMPLE_HTML, headers={"content-type": "text/html"})
        return httpx.Response(404, text="missing")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    limits = WebResearchLimits(
        max_search_results=2,
        max_pages=2,
        min_usable_content_chars=20,
        max_retries=1,
        search_endpoint="https://html.duckduckgo.com/html/",
    )
    policy = UrlSafetyPolicy(
        resolver=StaticResolver(
            {
                "html.duckduckgo.com": ("8.8.8.8",),
                "example.com": ("8.8.8.8",),
            }
        )
    )
    search = DuckDuckGoSearchProvider(limits=limits, client=client, endpoint=limits.search_endpoint)
    fetcher = HttpxWebFetcher(url_policy=policy, limits=limits, client=client)
    store = LocalArtifactStore(base_dir=tmp_path / "artifacts")
    service = WebResearchService(
        search_provider=search,
        fetcher=fetcher,
        renderer=NoOpWebRenderer(),
        url_policy=policy,
        artifact_store=store,
        limits=limits,
    )
    return service, store


@pytest.mark.asyncio
async def test_search_fetch_extract_artifact_pipeline(tmp_path) -> None:
    service, store = _stack(tmp_path)
    from app.application.web.models import ResearchRequest

    result = await service.research(
        ResearchRequest(query="example", max_results=2, run_id="run_int", project_id="proj_int")
    )
    assert result.metadata.pages_succeeded >= 1
    assert result.sources[0].artifact_id
    content = await store.get_artifact(result.sources[0].artifact_id, project_id="proj_int")
    assert content is not None
    assert "Example Guide" in str(content) or "example" in str(content).lower()
    assert await store.get_artifact(result.sources[0].artifact_id, project_id="other") is None
    await service.aclose()


@pytest.mark.asyncio
async def test_web_research_tool_through_executor(tmp_path) -> None:
    service, _store = _stack(tmp_path)
    defn, handler = create_web_research_tool(service)
    registry = ToolRegistry()
    registry.register(defn, handler)
    executor = ToolExecutor(registry, policy_engine=ToolPolicyEngine(registry=registry))
    ws = Workspace.create(root_path=tmp_path)
    ctx = ToolExecutionContext.from_execution(
        ExecutionContext(
            user_id="u1",
            project_id="proj_int",
            conversation_id=None,
            run_id="run_tool",
            workspace_id=ws.workspace_id,
        ),
        tool_call_id="c1",
        workspace=ws,
    )
    result = await executor.execute(
        ToolCall(id="c1", name="web_research", arguments={"query": "example", "max_results": 2}),
        context=ctx,
    )
    assert result.is_error is False
    assert "untrusted" in result.content.lower()
    assert "example.com" in result.content
    await service.aclose()


@pytest.mark.asyncio
async def test_web_research_through_agent_runtime(tmp_path) -> None:
    service, _store = _stack(tmp_path)
    defn, handler = create_web_research_tool(service)
    registry = ToolRegistry()
    registry.register(defn, handler)
    executor = ToolExecutor(registry, policy_engine=ToolPolicyEngine(registry=registry))
    gateway = _ScriptedGateway(
        [
            ModelResponse(
                content=None,
                tool_calls=[ToolCall(id="w1", name="web_research", arguments={"query": "example"})],
            ),
            ModelResponse(content="Summarized public sources.", tool_calls=[]),
        ]
    )
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=registry, tool_executor=executor)
    workspace = Workspace.create(root_path=tmp_path)
    run = await runtime.run(
        messages=[{"role": "user", "content": "research example"}],
        execution_context=ExecutionContext(
            user_id="u1",
            project_id="proj_int",
            conversation_id=None,
            run_id="run_web",
            workspace_id=workspace.workspace_id,
        ),
        workspace=workspace,
    )
    assert run.status == AgentStatus.COMPLETED
    assert run.final_response == "Summarized public sources."
    assert run.tool_calls[0].name == "web_research"
    await service.aclose()
