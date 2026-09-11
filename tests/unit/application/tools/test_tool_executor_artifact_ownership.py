"""Generic ToolExecutor artifact ownership from trusted execution context."""

import asyncio

import pytest

from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall, ToolDefinition
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.models.execution_context import ExecutionContext
from app.domain.models.workspace import Workspace
from app.infrastructure.storage.local_artifact_store import LocalArtifactStore


def _ctx(workspace: Workspace, project_id: str, run_id: str = "run_a") -> ToolExecutionContext:
    return ToolExecutionContext.from_execution(
        ExecutionContext(
            user_id="alice",
            project_id=project_id,
            conversation_id=None,
            run_id=run_id,
            workspace_id=workspace.workspace_id,
        ),
        tool_call_id="call_1",
        workspace=workspace,
    )


@pytest.mark.asyncio
async def test_tool_executor_archives_with_project_scope(tmp_path) -> None:
    store = LocalArtifactStore(base_dir=tmp_path / "artifacts")
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="blob", description="large"),
        lambda: "X" * 5000,
    )
    executor = ToolExecutor(registry, artifact_store=store, max_output_chars=100)
    workspace = Workspace.create(root_path=tmp_path)
    result = await executor.execute(
        ToolCall(id="call_1", name="blob", arguments={}),
        context=_ctx(workspace, "proj_a"),
    )
    assert not result.is_error
    assert "archived" in result.content.lower()
    saved = await store.get_artifact("tool_out_call_1", project_id="proj_a")
    assert saved is not None
    assert str(saved).startswith("X")
    assert await store.get_artifact("tool_out_call_1", project_id="proj_b") is None
    assert await store.get_artifact("tool_out_call_1") is None


@pytest.mark.asyncio
async def test_model_project_id_cannot_change_artifact_owner(tmp_path) -> None:
    store = LocalArtifactStore(base_dir=tmp_path / "artifacts")
    registry = ToolRegistry()

    def handler(project_id: str = "ignored") -> str:
        return f"payload-{project_id}-" + ("Y" * 4000)

    registry.register(ToolDefinition(name="blob", description="large"), handler)
    executor = ToolExecutor(registry, artifact_store=store, max_output_chars=80)
    workspace = Workspace.create(root_path=tmp_path)
    await executor.execute(
        ToolCall(id="call_x", name="blob", arguments={"project_id": "proj_evil"}),
        context=_ctx(workspace, "proj_a"),
    )
    assert await store.get_artifact("tool_out_call_x", project_id="proj_a") is not None
    assert await store.get_artifact("tool_out_call_x", project_id="proj_evil") is None


@pytest.mark.asyncio
async def test_multiple_projects_can_store_same_artifact_filename_safely(tmp_path) -> None:
    store = LocalArtifactStore(base_dir=tmp_path / "artifacts")
    await store.save_artifact("summary.txt", "A", project_id="proj_a")
    await store.save_artifact("summary.txt", "B", project_id="proj_b")
    assert await store.get_artifact("summary.txt", project_id="proj_a") == "A"
    assert await store.get_artifact("summary.txt", project_id="proj_b") == "B"


@pytest.mark.asyncio
async def test_concurrent_artifact_creation(tmp_path) -> None:
    store = LocalArtifactStore(base_dir=tmp_path / "artifacts")

    async def write(project_id: str, content: str) -> None:
        await store.save_artifact("shared.txt", content, project_id=project_id)

    await asyncio.gather(
        write("proj_a", "alpha"),
        write("proj_b", "beta"),
        write("proj_c", "gamma"),
    )
    assert await store.get_artifact("shared.txt", project_id="proj_a") == "alpha"
    assert await store.get_artifact("shared.txt", project_id="proj_b") == "beta"
    assert await store.get_artifact("shared.txt", project_id="proj_c") == "gamma"
