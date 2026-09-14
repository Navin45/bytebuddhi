"""Routing ModelGateway, catalog authorization, and fake-provider extensibility."""

from uuid import uuid4

import pytest

from app.application.agent.errors import ModelCallError, ModelSelectionError
from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus
from app.application.llm.catalog import InMemoryProviderRegistry, StaticModelCatalog
from app.application.llm.routing import RoutingModelGateway
from app.application.ports.output.llm.model_gateway import (
    ModelCapability,
    ModelDescriptor,
    ModelRef,
    ModelResponse,
)
from app.application.tools.registry import ToolRegistry
from app.application.use_cases.agent.execute_task import ExecuteTaskCommand, ExecuteTaskUseCase
from app.domain.models.execution_context import ExecutionContext
from app.domain.models.workspace import Workspace


class FakeAdapter:
    def __init__(self, provider: str, label: str) -> None:
        self.provider = provider
        self.label = label
        self.calls: list[str] = []

    async def generate(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        model = str(kwargs.get("model") or "")
        self.calls.append(model)
        return ModelResponse(content=f"{self.label}:{model}", provider=self.provider, model=model)

    async def stream(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        if False:
            yield None


class FailingAdapter:
    async def generate(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        raise ModelCallError("provider exploded", details={"category": "provider_unavailable"}, is_retryable=True)

    async def stream(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        if False:
            yield None


def _catalog(*descriptors: ModelDescriptor, default: ModelRef | None = None) -> StaticModelCatalog:
    default_ref = default or ModelRef(descriptors[0].provider, descriptors[0].model)
    return StaticModelCatalog(list(descriptors), default_ref)


def _open_model(provider: str, model: str, available: bool = True) -> ModelDescriptor:
    return ModelDescriptor(
        provider=provider,
        model=model,
        display_name=f"{provider} {model}",
        capabilities=(ModelCapability.CHAT, ModelCapability.TOOL_CALLING, ModelCapability.STREAMING),
        available=available,
    )


@pytest.mark.asyncio
async def test_fake_provider_registers_without_runtime_changes() -> None:
    catalog = _catalog(_open_model("fake", "fake-1"))
    registry = InMemoryProviderRegistry()
    registry.register("fake", FakeAdapter("fake", "FAKE"))
    gateway = RoutingModelGateway(catalog, registry)
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=ToolRegistry())
    state = await runtime.run(
        messages=[{"role": "user", "content": "hi"}],
        execution_context=ExecutionContext(
            user_id=uuid4(),
            project_id=None,
            conversation_id=None,
            run_id="run_fake",
            workspace_id="ws_fake",
        ),
        model_provider="fake",
        model_name="fake-1",
    )
    assert state.status == AgentStatus.COMPLETED
    assert state.final_response == "FAKE:fake-1"


@pytest.mark.asyncio
async def test_per_request_model_selection_without_restart() -> None:
    catalog = _catalog(_open_model("a", "model-a"), _open_model("b", "model-b"), default=ModelRef("a", "model-a"))
    registry = InMemoryProviderRegistry()
    adapter_a = FakeAdapter("a", "A")
    adapter_b = FakeAdapter("b", "B")
    registry.register("a", adapter_a)
    registry.register("b", adapter_b)
    gateway = RoutingModelGateway(catalog, registry)
    first = await gateway.generate([{"role": "user", "content": "x"}], provider="a", model="model-a")
    second = await gateway.generate([{"role": "user", "content": "x"}], provider="b", model="model-b")
    assert first.content == "A:model-a"
    assert second.content == "B:model-b"
    assert adapter_a.calls == ["model-a"]
    assert adapter_b.calls == ["model-b"]


@pytest.mark.asyncio
async def test_default_selection_and_unauthorized_model() -> None:
    catalog = _catalog(_open_model("openai", "gpt-test"), _open_model("anthropic", "claude-test", available=False))
    registry = InMemoryProviderRegistry()
    registry.register("openai", FakeAdapter("openai", "O"))
    gateway = RoutingModelGateway(catalog, registry)
    default = await gateway.generate([{"role": "user", "content": "x"}])
    assert default.provider == "openai"
    with pytest.raises(ModelSelectionError, match="not available"):
        await gateway.generate([{"role": "user", "content": "x"}], provider="anthropic", model="claude-test")
    with pytest.raises(ModelSelectionError, match="not registered"):
        await gateway.generate([{"role": "user", "content": "x"}], provider="openai", model="attacker-model")


@pytest.mark.asyncio
async def test_provider_failure_does_not_corrupt_execution_context() -> None:
    catalog = _catalog(_open_model("boom", "x"))
    registry = InMemoryProviderRegistry()
    registry.register("boom", FailingAdapter())
    gateway = RoutingModelGateway(catalog, registry)
    user = uuid4()
    project = uuid4()
    workspace = Workspace.create(root_path="storage/workspaces/iso", workspace_id="ws_iso")

    class _Workspace:
        async def resolve_workspace(self, user_id, project_id=None):
            return workspace

    runtime = AgentRuntime(model_gateway=gateway, tool_registry=ToolRegistry())
    use_case = ExecuteTaskUseCase(
        workspace_resolution_service=_Workspace(),
        agent_runtime=runtime,
        model_catalog=catalog,
    )
    result = await use_case.execute(
        ExecuteTaskCommand(prompt="go", user_id=user, project_id=project, persist_messages=False)
    )
    assert result.run_state.status == AgentStatus.FAILED
    assert result.workspace_id == "ws_iso"


@pytest.mark.asyncio
async def test_openai_compatible_endpoint_cannot_come_from_request() -> None:
    catalog = _catalog(_open_model("openai-compatible", "local-1"))
    registry = InMemoryProviderRegistry()
    registry.register("openai-compatible", FakeAdapter("openai-compatible", "C"))
    gateway = RoutingModelGateway(catalog, registry)
    with pytest.raises(ModelSelectionError):
        await gateway.generate(
            [{"role": "user", "content": "x"}],
            provider="https://attacker.example",
            model="local-1",
        )
