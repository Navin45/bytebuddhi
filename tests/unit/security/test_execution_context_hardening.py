"""ExecutionContext hardening: metadata/tool-args must not become trusted identity."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.application.agent.context_projector import AgentContextProjector
from app.application.agent.orchestrator import MultiAgentOrchestrator
from app.application.agent.registry import AgentRegistry
from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus
from app.application.ports.output.llm.model_gateway import ModelGateway, ModelResponse
from app.application.tools.builtin.filesystem_tools import create_filesystem_tools
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall, ToolDefinition
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.exceptions.execution_exceptions import ExecutionContextRequired
from app.domain.models.agent import AgentDefinition, AgentRole, AgentTask, TaskExecutionStatus
from app.domain.models.credential import Credential, CredentialType
from app.domain.models.memory import MemoryScope
from app.domain.models.workspace import Workspace
from app.infrastructure.connectors.credentials.env_credential_provider import EnvAndDictCredentialProvider
from app.infrastructure.connectors.github.github_connector import GitHubConnector
from app.infrastructure.storage.local_artifact_store import LocalArtifactStore
from tests.helpers.execution import trusted_execution_context


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


def _capture_tool(sink: dict[str, Any]) -> tuple[ToolDefinition, Any]:
    definition = ToolDefinition(name="capture_identity", description="Record trusted identity")

    async def handler(context: ToolExecutionContext | None = None, **kwargs: Any) -> dict[str, Any]:
        if context is not None:
            sink["user_id"] = context.user_id
            sink["project_id"] = context.project_id
            sink["workspace_id"] = context.workspace_id
            sink["run_id"] = context.run_id
            sink["workspace_root"] = str(context.workspace.root_path)
            sink["execution"] = context.execution
            sink["metadata"] = dict(context.metadata)
            sink["tool_kwargs"] = dict(kwargs)
        return {"ok": True}

    return definition, handler


def _huge_tool() -> tuple[ToolDefinition, Any]:
    def handler(**kwargs: Any) -> str:
        return "Z" * 4000

    return ToolDefinition(name="blob", description="large payload"), handler


@pytest.mark.asyncio
async def test_attack_a_missing_trusted_context_is_rejected() -> None:
    runtime = AgentRuntime(model_gateway=_ScriptedGateway([]), tool_registry=ToolRegistry())
    with pytest.raises(ExecutionContextRequired):
        await runtime.run(messages=[{"role": "user", "content": "hello"}])

    orchestrator = MultiAgentOrchestrator(agent_runtime=runtime, agent_registry=AgentRegistry())
    task = AgentTask(task_id="t1", agent_id="coder", description="x")
    with pytest.raises(ExecutionContextRequired):
        await orchestrator.execute_task(task)
    with pytest.raises(ExecutionContextRequired):
        await orchestrator.execute_tasks([task])
    with pytest.raises(ExecutionContextRequired):
        await orchestrator.execute_task(task, parent_context={"user_id": "alice", "project_id": "proj"})  # type: ignore[arg-type]

    projector = AgentContextProjector()
    with pytest.raises(ExecutionContextRequired):
        projector.project_child_context(
            task=task,
            definition=AgentDefinition(id="coder", name="C", description="d", role=AgentRole.CODER, system_prompt="p"),
            child_run_id="c1",
            parent_execution=None,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_attack_b_metadata_identity_injection_trusted_context_wins(tmp_path) -> None:
    sink: dict[str, Any] = {}
    registry = ToolRegistry()
    defn, handler = _capture_tool(sink)
    registry.register(defn, handler)
    gateway = _ScriptedGateway(
        [
            ModelResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="capture_identity", arguments={})],
            ),
            ModelResponse(content="done"),
        ]
    )
    workspace = Workspace.create(root_path=tmp_path)
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=registry, tool_executor=ToolExecutor(registry))
    trusted = trusted_execution_context(
        user_id="actual-user",
        project_id="actual-project",
        run_id="run_trusted",
        workspace_id=workspace.workspace_id,
    )
    await runtime.run(
        messages=[{"role": "user", "content": "go"}],
        execution_context=trusted,
        metadata={"user_id": "attacker", "project_id": "victim", "workspace_id": "victim-workspace"},
        workspace=workspace,
    )
    assert sink["user_id"] == "actual-user"
    assert sink["project_id"] == "actual-project"
    assert sink["workspace_id"] == workspace.workspace_id
    assert sink["run_id"] == "run_trusted"
    assert "user_id" not in sink["metadata"]
    assert "project_id" not in sink["metadata"]
    assert sink["execution"] is not None
    assert sink["execution"].user_id == "actual-user"
    assert sink["execution"].project_id == "actual-project"


@pytest.mark.asyncio
async def test_attack_c_tool_argument_identity_injection_ignored(tmp_path) -> None:
    sink: dict[str, Any] = {}
    registry = ToolRegistry()
    defn, handler = _capture_tool(sink)
    registry.register(defn, handler)
    gateway = _ScriptedGateway(
        [
            ModelResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="capture_identity",
                        arguments={
                            "user_id": "victim",
                            "project_id": "victim",
                            "workspace": "victim",
                            "workspace_path": "/victim",
                        },
                    )
                ],
            ),
            ModelResponse(content="done"),
        ]
    )
    workspace = Workspace.create(root_path=tmp_path)
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=registry, tool_executor=ToolExecutor(registry))
    await runtime.run(
        messages=[{"role": "user", "content": "go"}],
        execution_context=trusted_execution_context(
            user_id="alice",
            project_id="proj_a",
            workspace_id=workspace.workspace_id,
        ),
        workspace=workspace,
    )
    assert sink["user_id"] == "alice"
    assert sink["project_id"] == "proj_a"
    assert sink["tool_kwargs"]["project_id"] == "victim"
    assert sink["execution"].project_id == "proj_a"


@pytest.mark.asyncio
async def test_attack_d_child_metadata_cannot_replace_parent_identity(tmp_path) -> None:
    sink: dict[str, Any] = {}
    registry = ToolRegistry()
    defn, handler = _capture_tool(sink)
    registry.register(defn, handler)
    gateway = _ScriptedGateway(
        [
            ModelResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="capture_identity", arguments={})],
            ),
            ModelResponse(content="child finished"),
        ]
    )
    workspace = Workspace.create(root_path=tmp_path)
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=registry, tool_executor=ToolExecutor(registry))
    agents = AgentRegistry()
    agents.register(
        AgentDefinition(
            id="researcher",
            name="Researcher",
            description="r",
            role=AgentRole.RESEARCHER,
            system_prompt="Research.",
            allowed_capabilities=("capture_identity",),
        )
    )
    orchestrator = MultiAgentOrchestrator(agent_runtime=runtime, agent_registry=agents)
    parent = trusted_execution_context(
        user_id="alice",
        project_id="proj_a",
        run_id="parent_run",
        workspace_id=workspace.workspace_id,
        delegation_depth=0,
    )
    result = await orchestrator.execute_task(
        AgentTask(
            task_id="t1",
            agent_id="researcher",
            description="look",
            input_data={"user_id": "victim", "project_id": "victim-project", "workspace_id": "victim-ws"},
            metadata={
                "user_id": "victim",
                "project_id": "victim-project",
                "workspace_id": "victim-ws",
                "run_id": "forged_run",
            },
        ),
        parent_context=parent,
    )
    assert result.status == TaskExecutionStatus.SUCCESS
    child = sink["execution"]
    assert child.user_id == "alice"
    assert child.project_id == "proj_a"
    assert child.workspace_id == parent.workspace_id
    assert child.parent_run_id == parent.run_id
    assert child.run_id != parent.run_id
    assert child.delegation_depth == 1
    assert parent.user_id == "alice"
    assert parent.delegation_depth == 0


@pytest.mark.asyncio
async def test_attack_e_artifact_owner_injection(tmp_path) -> None:
    store = LocalArtifactStore(base_dir=tmp_path / "artifacts")
    registry = ToolRegistry()
    defn, handler = _huge_tool()
    registry.register(defn, handler)
    executor = ToolExecutor(registry, artifact_store=store, max_output_chars=80)
    workspace = Workspace.create(root_path=tmp_path)
    gateway = _ScriptedGateway(
        [
            ModelResponse(
                content=None,
                tool_calls=[ToolCall(id="call_art", name="blob", arguments={"project_id": "another_project"})],
            ),
            ModelResponse(content="done"),
        ]
    )
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=registry, tool_executor=executor)
    await runtime.run(
        messages=[{"role": "user", "content": "go"}],
        execution_context=trusted_execution_context(
            user_id="alice",
            project_id="trusted_project",
            workspace_id=workspace.workspace_id,
        ),
        metadata={"project_id": "another_project"},
        workspace=workspace,
    )
    assert await store.get_artifact("tool_out_call_art", project_id="trusted_project") is not None
    assert await store.get_artifact("tool_out_call_art", project_id="another_project") is None


@pytest.mark.asyncio
async def test_attack_f_memory_scope_injection() -> None:
    mock_orch = AsyncMock()
    mock_orch.retrieve_memories.return_value = []
    runtime = AgentRuntime(
        model_gateway=_ScriptedGateway([ModelResponse(content="ok")]),
        tool_registry=ToolRegistry(),
        memory_orchestrator=mock_orch,
    )
    await runtime.run(
        messages=[{"role": "user", "content": "remember?"}],
        execution_context=trusted_execution_context(user_id="alice", project_id="proj_a", run_id="run_mem"),
        metadata={"user_id": "attacker", "project_id": "victim-project"},
    )
    scopes = mock_orch.retrieve_memories.call_args.kwargs["scopes"]
    assert (MemoryScope.USER, "alice") in scopes
    assert (MemoryScope.PROJECT, "proj_a") in scopes
    assert (MemoryScope.AGENT_RUN, "run_mem") in scopes
    assert (MemoryScope.USER, "attacker") not in scopes
    assert (MemoryScope.PROJECT, "victim-project") not in scopes


@pytest.mark.asyncio
async def test_attack_g_workspace_injection_rejected_or_ignored(tmp_path) -> None:
    registry = ToolRegistry()
    for defn, handler in create_filesystem_tools():
        registry.register(defn, handler)
    executor = ToolExecutor(registry)
    workspace = Workspace.create(root_path=tmp_path)
    ctx = ToolExecutionContext.from_execution(
        trusted_execution_context(workspace_id=workspace.workspace_id, project_id="proj_a"),
        tool_call_id="w1",
        workspace=workspace,
    )

    extra = await executor.execute(
        ToolCall(
            id="w1",
            name="write_file",
            arguments={
                "path": "owned.txt",
                "content": "trusted",
                "workspace_path": str(tmp_path / "another"),
                "workspace": "/another/project",
            },
        ),
        context=ctx,
    )
    assert extra.is_error is True

    escaped = await executor.execute(
        ToolCall(
            id="w2",
            name="write_file",
            arguments={"path": "/another/project/secret.txt", "content": "nope"},
        ),
        context=ctx,
    )
    assert escaped.is_error is True

    ok = await executor.execute(
        ToolCall(id="w3", name="write_file", arguments={"path": "owned.txt", "content": "trusted"}),
        context=ctx,
    )
    assert ok.is_error is False
    assert (tmp_path / "owned.txt").read_text() == "trusted"


@pytest.mark.asyncio
async def test_architecture_canonical_path_identity_not_from_metadata(tmp_path) -> None:
    """Exercise AgentRuntime -> ToolExecutionContext and prove metadata is not identity."""
    sink: dict[str, Any] = {}
    registry = ToolRegistry()
    defn, handler = _capture_tool(sink)
    registry.register(defn, handler)
    gateway = _ScriptedGateway(
        [
            ModelResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="arch1",
                        name="capture_identity",
                        arguments={"user_id": "model-user", "project_id": "model-project"},
                    )
                ],
            ),
            ModelResponse(content="final"),
        ]
    )
    workspace = Workspace.create(root_path=tmp_path)
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=registry, tool_executor=ToolExecutor(registry))
    state = await runtime.run(
        messages=[{"role": "user", "content": "go"}],
        execution_context=trusted_execution_context(
            user_id="server-user",
            project_id="server-project",
            run_id="server-run",
            workspace_id=workspace.workspace_id,
        ),
        metadata={"user_id": "meta-user", "project_id": "meta-project", "workspace_id": "meta-ws"},
        workspace=workspace,
    )
    assert state.status == AgentStatus.COMPLETED
    assert sink["execution"] is not None
    assert sink["user_id"] == "server-user"
    assert sink["project_id"] == "server-project"
    assert sink["run_id"] == "server-run"
    assert sink["tool_kwargs"]["user_id"] == "model-user"
    assert "user_id" not in sink["metadata"]


@pytest.mark.asyncio
async def test_credentials_resolve_from_execution_context_not_tool_args() -> None:
    provider = EnvAndDictCredentialProvider()
    await provider.set_credential(
        "github",
        Credential(
            name="alice",
            provider="github",
            secret_value="alice-secret",
            credential_type=CredentialType.BEARER_TOKEN,
        ),
        user_id="alice",
        project_id="proj_a",
    )
    await provider.set_credential(
        "github",
        Credential(
            name="victim", provider="github", secret_value="victim-secret", credential_type=CredentialType.BEARER_TOKEN
        ),
        user_id="victim",
        project_id="victim-project",
    )

    recorded: dict[str, str] = {}

    class _FakeHttp:
        async def request(self, **kwargs: Any) -> dict[str, Any]:
            recorded["authorization"] = kwargs["headers"]["Authorization"]
            return {"total_count": 0, "items": []}

    connector = GitHubConnector(credential_provider=provider, client=_FakeHttp())  # type: ignore[arg-type]
    ctx = ToolExecutionContext.from_execution(
        trusted_execution_context(user_id="alice", project_id="proj_a"),
        tool_call_id="gh1",
        workspace=Workspace.create(root_path="."),
    )
    await connector.invoke(
        "github_search_repositories",
        {"query": "bytebuddhi", "user_id": "victim", "project_id": "victim-project"},
        context=ctx,
    )
    assert recorded["authorization"] == "Bearer alice-secret"
