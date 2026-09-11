"""CLI security: identity, workspace selection, and credential hygiene."""

from __future__ import annotations

import io
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.use_cases.agent.execute_task import ExecuteTaskCommand, ExecuteTaskResult
from app.application.use_cases.project.get_project import GetProjectUseCase
from app.application.use_cases.project.resolve_project_by_local_path import ResolveProjectByLocalPathUseCase
from app.domain.exceptions.project_exceptions import ProjectOwnershipException
from app.domain.exceptions.workspace_exceptions import WorkspaceBoundaryError
from app.domain.models.project import Project
from app.domain.models.user import User
from app.interfaces.cli.app import CliApp
from app.interfaces.cli.dispatch import dispatch
from app.interfaces.cli.errors import CliError
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.parser import build_parser
from app.interfaces.cli.render import json_error_payload


def _user() -> User:
    now = datetime.utcnow()
    return User(
        id=uuid4(),
        email="sec@example.com",
        username="sec",
        password_hash="hashed",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_model_prompt_cannot_override_project(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    trusted_project = uuid4()
    execute_task = AsyncMock()

    async def _execute(command: ExecuteTaskCommand) -> ExecuteTaskResult:
        assert command.project_id == trusted_project
        return ExecuteTaskResult(
            run_id="r",
            response="ok",
            run_state=AgentRunState(run_id="r", status=AgentStatus.COMPLETED),
            conversation_id=uuid4(),
            workspace_id=f"proj_{trusted_project}",
        )

    execute_task.execute = _execute
    user_repo = AsyncMock()
    user_repo.get_by_id = AsyncMock(return_value=user)
    app = CliApp(
        execute_task=execute_task,
        list_projects=AsyncMock(),
        get_project=AsyncMock(),
        resolve_local_project=AsyncMock(),
        user_repository=user_repo,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    forged = uuid4()
    args = build_parser().parse_args(["run", "--project", str(trusted_project), f"use project_id {forged}"])
    code = await dispatch(args, app, json_mode=True, quiet=True, stdin=io.StringIO(), stderr=io.StringIO())
    assert code == 0


@pytest.mark.asyncio
async def test_cwd_denied_in_managed_mode(tmp_path) -> None:
    user = _user()
    repo = AsyncMock()
    repo.get_by_user_id = AsyncMock(return_value=[])
    use_case = ResolveProjectByLocalPathUseCase(repo, workspace_mode="managed")
    with pytest.raises(WorkspaceBoundaryError):
        await use_case.execute(user.id, str(tmp_path))


@pytest.mark.asyncio
async def test_cwd_must_match_owned_project_path(tmp_path) -> None:
    user = _user()
    other = tmp_path / "other"
    other.mkdir()
    project = Project.create(user_id=user.id, name="owned", local_path=str(tmp_path / "owned"))
    (tmp_path / "owned").mkdir()
    repo = AsyncMock()
    repo.get_by_user_id = AsyncMock(return_value=[project])
    use_case = ResolveProjectByLocalPathUseCase(repo, workspace_mode="local")
    with pytest.raises(WorkspaceBoundaryError):
        await use_case.execute(user.id, str(other))


@pytest.mark.asyncio
async def test_get_project_denies_other_owner() -> None:
    owner = uuid4()
    requester = uuid4()
    project = Project.create(user_id=owner, name="secret")
    repo = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=project)
    use_case = GetProjectUseCase(repo)
    with pytest.raises(ProjectOwnershipException):
        await use_case.execute(requester, project.id)


def test_json_error_envelope_does_not_include_secrets() -> None:
    payload = json_error_payload("An internal error occurred.", exit_code=3)
    serialized = str(payload)
    assert "password" not in serialized
    assert "jwt" not in serialized
    assert payload["status"] == "error"


@pytest.mark.asyncio
async def test_auth_error_from_cli_app() -> None:
    user = _user()
    app = CliApp(
        execute_task=AsyncMock(),
        list_projects=AsyncMock(),
        get_project=AsyncMock(),
        resolve_local_project=AsyncMock(),
        user_repository=AsyncMock(get_by_id=AsyncMock(return_value=None)),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    with pytest.raises(CliError) as exc:
        await app.authenticate(user.id)
    assert exc.value.exit_code == ExitCode.AUTH_FAILURE
