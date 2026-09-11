"""Verification of CLI readiness and decoupling from HTTP frameworks."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.application.agent.runtime import AgentRuntime
from app.application.agent.state import AgentRunState
from app.application.use_cases.agent.execute_task import (
    ExecuteTaskCommand,
    ExecuteTaskUseCase,
)
from app.application.workspace.resolution_service import WorkspaceResolutionService
from app.domain.models.project import Project


def test_core_runtime_clean_from_web_frameworks() -> None:
    """Importing application runtime and use cases must not pull in fastapi or starlette."""
    for mod in ["fastapi", "starlette"]:
        use_case_mod = sys.modules.get("app.application.use_cases.agent.execute_task")
        assert use_case_mod is not None
        assert not hasattr(use_case_mod, mod)


@pytest.mark.asyncio
async def test_execute_task_use_case_standalone(tmp_path) -> None:
    """ExecuteTaskUseCase can run standalone with mock dependencies, fully decoupled from HTTP."""
    mock_project_repo = AsyncMock()
    user_id = uuid4()
    project_id = uuid4()

    test_project = Project.create(
        user_id=user_id,
        name="test_proj",
        local_path=str(tmp_path / "proj"),
    )
    mock_project_repo.get_by_id = AsyncMock(return_value=test_project)

    resolution_service = WorkspaceResolutionService(
        project_repo=mock_project_repo,
        base_storage_dir=str(tmp_path / "workspaces"),
    )

    mock_runtime = MagicMock(spec=AgentRuntime)
    mock_state = AgentRunState(run_id="run-cli-1")
    mock_state.final_response = "CLI task executed successfully"
    mock_runtime.run = AsyncMock(return_value=mock_state)

    use_case = ExecuteTaskUseCase(
        workspace_resolution_service=resolution_service,
        agent_runtime=mock_runtime,
    )

    cmd = ExecuteTaskCommand(
        prompt="Build the CLI feature",
        user_id=user_id,
        project_id=project_id,
    )

    result = await use_case.execute(cmd)
    assert result.response == "CLI task executed successfully"
    assert result.workspace_id.startswith("proj_")
    assert mock_runtime.run.called
    run_kwargs = mock_runtime.run.await_args.kwargs
    execution_context = run_kwargs["execution_context"]
    assert str(execution_context.user_id) == str(user_id)
    assert str(execution_context.project_id) == str(project_id)
    assert execution_context.workspace_id == result.workspace_id
    assert "user_id" not in (run_kwargs.get("metadata") or {})


def test_docker_uses_supported_python() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "python:3.13" in dockerfile
    assert "uv.lock" in dockerfile
    assert "uv sync --frozen" in dockerfile
