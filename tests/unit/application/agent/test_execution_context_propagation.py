"""Trusted ExecutionContext propagation through runtime, tools, and children."""

from typing import Any

import pytest

from app.application.agent.orchestrator import MultiAgentOrchestrator
from app.application.agent.registry import AgentRegistry
from app.application.agent.runtime import AgentRuntime
from app.application.ports.output.llm.model_gateway import ModelGateway, ModelResponse
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall, ToolDefinition
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.models.agent import AgentDefinition, AgentRole, AgentTask, TaskExecutionStatus
from app.domain.models.execution_context import ExecutionContext
from app.domain.models.workspace import Workspace


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

    async def handler(
        note: str = "",
        context: ToolExecutionContext | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if context is not None:
            sink["incoming_metadata"] = dict(context.metadata)
            context.metadata["user_id"] = "from_tool_metadata"
            context.metadata["project_id"] = kwargs.get("project_id", "from_tool_arg")
            sink["user_id"] = context.user_id
            sink["project_id"] = context.project_id
            sink["workspace_id"] = context.workspace_id
            sink["run_id"] = context.run_id
            sink["execution"] = context.execution
            sink["metadata"] = dict(context.metadata)
            sink["tool_kwargs"] = dict(kwargs)
        return {"note": note, "project_id": context.project_id if context else None}

    return definition, handler


def _trusted(workspace: Workspace) -> ExecutionContext:
    return ExecutionContext(
        user_id="alice",
        project_id="proj_a",
        conversation_id="conv_1",
        run_id="run_trusted",
        workspace_id=workspace.workspace_id,
    )


@pytest.mark.asyncio
async def test_trusted_project_identity_propagates(tmp_path) -> None:
    sink: dict[str, Any] = {}
    registry = ToolRegistry()
    defn, handler = _capture_tool(sink)
    registry.register(defn, handler)
    gateway = _ScriptedGateway(
        [
            ModelResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="capture_identity", arguments={"note": "ok"})],
            ),
            ModelResponse(content="done"),
        ]
    )
    workspace = Workspace.create(root_path=tmp_path)
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=registry, tool_executor=ToolExecutor(registry))
    await runtime.run(
        messages=[{"role": "user", "content": "go"}],
        execution_context=_trusted(workspace),
        workspace=workspace,
    )
    assert sink["user_id"] == "alice"
    assert sink["project_id"] == "proj_a"
    assert sink["workspace_id"] == workspace.workspace_id
    assert sink["execution"] is not None
    assert sink["execution"].project_id == "proj_a"


@pytest.mark.asyncio
async def test_workspace_identity_propagates(tmp_path) -> None:
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
    workspace = Workspace.create(root_path=tmp_path, workspace_id="ws_explicit")
    runtime = AgentRuntime(model_gateway=gateway, tool_registry=registry, tool_executor=ToolExecutor(registry))
    ctx = ExecutionContext(
        user_id="alice",
        project_id="proj_a",
        conversation_id=None,
        run_id="run_ws",
        workspace_id="ws_explicit",
    )
    await runtime.run(
        messages=[{"role": "user", "content": "go"}],
        execution_context=ctx,
        workspace=workspace,
    )
    assert sink["workspace_id"] == "ws_explicit"


@pytest.mark.asyncio
async def test_model_metadata_cannot_override_identity(tmp_path) -> None:
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
    await runtime.run(
        messages=[{"role": "user", "content": "go"}],
        execution_context=_trusted(workspace),
        metadata={
            "user_id": "attacker",
            "project_id": "proj_evil",
            "workspace_id": "/etc",
            "run_id": "forged_run",
        },
        workspace=workspace,
    )
    assert sink["user_id"] == "alice"
    assert sink["project_id"] == "proj_a"
    assert sink["workspace_id"] == workspace.workspace_id
    assert sink["run_id"] == "run_trusted"
    assert "user_id" not in sink["incoming_metadata"]
    assert "project_id" not in sink["incoming_metadata"]


@pytest.mark.asyncio
async def test_tool_metadata_cannot_override_identity(tmp_path) -> None:
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
                        arguments={"user_id": "tool_attacker", "project_id": "proj_from_args"},
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
        execution_context=_trusted(workspace),
        workspace=workspace,
    )
    assert sink["user_id"] == "alice"
    assert sink["project_id"] == "proj_a"
    assert sink["tool_kwargs"]["project_id"] == "proj_from_args"
    assert sink["execution"].project_id == "proj_a"


@pytest.mark.asyncio
async def test_child_context_derives_from_parent(tmp_path) -> None:
    captured: dict[str, Any] = {}
    registry = ToolRegistry()

    async def child_handler(context: ToolExecutionContext | None = None, **kwargs: Any) -> str:
        if context is not None and context.execution is not None:
            captured["child"] = context.execution
        return "child-ok"

    registry.register(ToolDefinition(name="capture_identity", description="c"), child_handler)
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
            allowed_capabilities=["capture_identity"],
        )
    )
    orchestrator = MultiAgentOrchestrator(
        agent_runtime=runtime,
        agent_registry=agents,
    )
    parent = _trusted(workspace)
    result = await orchestrator.execute_task(
        AgentTask(task_id="t1", agent_id="researcher", description="look"),
        parent_context=parent,
    )
    assert result.status == TaskExecutionStatus.SUCCESS
    child = captured["child"]
    assert child.user_id == parent.user_id
    assert child.project_id == parent.project_id
    assert child.workspace_id == parent.workspace_id
    assert child.parent_run_id == parent.run_id
    assert child.run_id != parent.run_id
    assert child.delegation_depth == 1
    assert parent.delegation_depth == 0
    assert parent.user_id == "alice"
