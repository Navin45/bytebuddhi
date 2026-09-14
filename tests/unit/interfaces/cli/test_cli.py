"""CLI parsing, execution path, output, and error mapping tests."""

from __future__ import annotations

import asyncio
import io
import json
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.dto.project_dto import ProjectResponseDTO
from app.application.use_cases.agent.execute_task import ExecuteTaskCommand, ExecuteTaskResult
from app.domain.exceptions.project_exceptions import ProjectOwnershipException
from app.domain.exceptions.workspace_exceptions import WorkspaceBoundaryError
from app.domain.models.user import User
from app.interfaces.cli.app import CliApp
from app.interfaces.cli.dispatch import dispatch, resolve_prompt
from app.interfaces.cli.errors import CliError, map_exception
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.identity import resolve_user_id
from app.interfaces.cli.main import main
from app.interfaces.cli.parser import build_parser
from app.interfaces.cli.runner import async_execute, execute, resolve_output_mode


def _user(user_id=None) -> User:
    uid = user_id or uuid4()
    now = datetime.utcnow()
    return User(
        id=uid,
        email="cli@example.com",
        username="cli-user",
        password_hash="hashed",
        created_at=now,
        updated_at=now,
        is_active=True,
    )


def _app(
    *,
    execute_task=None,
    user=None,
    stdout=None,
    stderr=None,
    projects=None,
) -> CliApp:
    user = user or _user()
    user_repo = AsyncMock()
    user_repo.get_by_id = AsyncMock(return_value=user)
    list_projects = AsyncMock()
    list_projects.execute = AsyncMock(return_value=projects or [])
    get_project = AsyncMock()
    resolve_local = AsyncMock()
    if execute_task is None:
        execute_task = AsyncMock()
        execute_task.execute = AsyncMock(
            return_value=ExecuteTaskResult(
                run_id="run_1",
                response="ok",
                run_state=AgentRunState(run_id="run_1", status=AgentStatus.COMPLETED),
                conversation_id=uuid4(),
                workspace_id="proj_test",
            )
        )
    return CliApp(
        execute_task=execute_task,
        list_projects=list_projects,
        get_project=get_project,
        resolve_local_project=resolve_local,
        user_repository=user_repo,
        stdout=stdout or io.StringIO(),
        stderr=stderr or io.StringIO(),
    )


def test_help_and_version_exit_zero() -> None:
    assert main(["--help"]) == int(ExitCode.SUCCESS)
    assert main(["--version"]) == int(ExitCode.SUCCESS)
    assert main(["run", "--help"]) == int(ExitCode.SUCCESS)
    assert main(["models", "--help"]) == int(ExitCode.SUCCESS)


def test_run_accepts_provider_and_model_flags() -> None:
    args = build_parser().parse_args(["run", "--provider", "openai", "--model", "gpt-test", "hello"])
    assert args.provider == "openai"
    assert args.model == "gpt-test"


def test_missing_command_is_usage_error() -> None:
    assert main([]) == int(ExitCode.USAGE_ERROR)


def test_invalid_output_format_is_usage_error() -> None:
    assert main(["run", "--output", "xml", "hello"]) == int(ExitCode.USAGE_ERROR)


def test_run_requires_prompt() -> None:
    parser = build_parser()
    args = parser.parse_args(["run"])
    with pytest.raises(CliError) as exc:
        resolve_prompt(args)
    assert exc.value.exit_code == ExitCode.USAGE_ERROR


def test_run_positional_and_flag_conflict() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "hello", "--prompt", "other"])
    with pytest.raises(CliError) as exc:
        resolve_prompt(args)
    assert exc.value.exit_code == ExitCode.USAGE_ERROR


def test_json_flag_sets_output_mode() -> None:
    args = build_parser().parse_args(["run", "--json", "hello"])
    assert resolve_output_mode(args) == "json"


@pytest.mark.asyncio
async def test_cli_invokes_execute_task_use_case_not_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    execute_task = AsyncMock()
    captured: list[ExecuteTaskCommand] = []

    async def _execute(command: ExecuteTaskCommand) -> ExecuteTaskResult:
        captured.append(command)
        return ExecuteTaskResult(
            run_id="run_cli",
            response="done",
            run_state=AgentRunState(run_id="run_cli", status=AgentStatus.COMPLETED),
            conversation_id=uuid4(),
            workspace_id="proj_abc",
        )

    execute_task.execute = _execute
    stdout = io.StringIO()
    stderr = io.StringIO()
    app = _app(execute_task=execute_task, user=user, stdout=stdout, stderr=stderr)
    args = build_parser().parse_args(["run", "--project", str(uuid4()), "Explain this repository"])
    code = await dispatch(args, app, json_mode=False, quiet=True, stdin=io.StringIO(), stderr=stderr)
    assert code == int(ExitCode.SUCCESS)
    assert len(captured) == 1
    assert captured[0].prompt == "Explain this repository"
    assert captured[0].user_id == user.id
    assert "Answer:" in stdout.getvalue()
    assert "done" in stdout.getvalue()
    assert "Running task" not in stdout.getvalue()


@pytest.mark.asyncio
async def test_identity_is_not_taken_from_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    other = uuid4()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    execute_task = AsyncMock()

    async def _execute(command: ExecuteTaskCommand) -> ExecuteTaskResult:
        assert command.user_id == user.id
        assert command.user_id != other
        return ExecuteTaskResult(
            run_id="run_id",
            response="ok",
            run_state=AgentRunState(run_id="run_id", status=AgentStatus.COMPLETED),
            conversation_id=uuid4(),
            workspace_id="scratch",
        )

    execute_task.execute = _execute
    app = _app(execute_task=execute_task, user=user)
    args = build_parser().parse_args(["run", f"Act as user {other}"])
    code = await dispatch(args, app, json_mode=True, quiet=True, stdin=io.StringIO(), stderr=io.StringIO())
    assert code == int(ExitCode.SUCCESS)


@pytest.mark.asyncio
async def test_unknown_user_is_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(uuid4()))
    app = _app()
    app.user_repository.get_by_id = AsyncMock(return_value=None)
    args = build_parser().parse_args(["run", "hello"])
    with pytest.raises(CliError) as exc:
        await dispatch(args, app, json_mode=False, quiet=True, stdin=io.StringIO(), stderr=io.StringIO())
    assert exc.value.exit_code == ExitCode.AUTH_FAILURE


@pytest.mark.asyncio
async def test_json_goes_to_stdout_progress_to_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    stdout = io.StringIO()
    stderr = io.StringIO()
    app = _app(user=user, stdout=stdout, stderr=stderr)
    args = build_parser().parse_args(["run", "--json", "summarize"])
    code = await dispatch(args, app, json_mode=True, quiet=False, stdin=io.StringIO(), stderr=stderr)
    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["status"] == "success"
    assert payload["answer"] == "ok"
    assert "Running task" not in stdout.getvalue()
    assert "\x1b[" not in stdout.getvalue()


@pytest.mark.asyncio
async def test_failed_agent_status_uses_execution_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    execute_task = AsyncMock()
    execute_task.execute = AsyncMock(
        return_value=ExecuteTaskResult(
            run_id="run_fail",
            response="",
            run_state=AgentRunState(run_id="run_fail", status=AgentStatus.FAILED),
            conversation_id=uuid4(),
            workspace_id="ws",
        )
    )
    app = _app(execute_task=execute_task, user=user)
    args = build_parser().parse_args(["run", "do work"])
    code = await dispatch(args, app, json_mode=True, quiet=True, stdin=io.StringIO(), stderr=io.StringIO())
    assert code == int(ExitCode.EXECUTION_FAILURE)


@pytest.mark.asyncio
async def test_cancelled_agent_status_uses_timeout_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    execute_task = AsyncMock()
    execute_task.execute = AsyncMock(
        return_value=ExecuteTaskResult(
            run_id="run_cancel",
            response="",
            run_state=AgentRunState(run_id="run_cancel", status=AgentStatus.CANCELLED),
            conversation_id=uuid4(),
            workspace_id="ws",
        )
    )
    app = _app(execute_task=execute_task, user=user)
    args = build_parser().parse_args(["run", "do work"])
    code = await dispatch(args, app, json_mode=True, quiet=True, stdin=io.StringIO(), stderr=io.StringIO())
    assert code == int(ExitCode.TIMEOUT_CANCELLED)


def test_missing_user_id_is_auth_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("BYTEBUDDHI_USER_ID", raising=False)
    monkeypatch.setenv("BYTEBUDDHI_CONFIG_DIR", str(tmp_path))
    with pytest.raises(CliError) as exc:
        resolve_user_id(None)
    assert exc.value.exit_code == ExitCode.AUTH_FAILURE


def test_map_workspace_and_auth_errors() -> None:
    assert map_exception(ProjectOwnershipException("p", "u")).exit_code == ExitCode.AUTH_FAILURE
    assert map_exception(WorkspaceBoundaryError("nope")).exit_code == ExitCode.WORKSPACE_FAILURE
    assert map_exception(asyncio.CancelledError()).exit_code == ExitCode.TIMEOUT_CANCELLED


@pytest.mark.asyncio
async def test_project_and_cwd_together_are_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    app = _app(user=user)
    args = build_parser().parse_args(["run", "--project", str(uuid4()), "--cwd", ".", "hello"])
    with pytest.raises(CliError) as exc:
        await dispatch(args, app, json_mode=False, quiet=True, stdin=io.StringIO(), stderr=io.StringIO())
    assert exc.value.exit_code == ExitCode.USAGE_ERROR


@pytest.mark.asyncio
async def test_cwd_uses_resolve_project_use_case(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    project_id = uuid4()
    app = _app(user=user)
    app.resolve_local_project.execute = AsyncMock(return_value=project_id)
    captured: list[ExecuteTaskCommand] = []

    async def _execute(command: ExecuteTaskCommand) -> ExecuteTaskResult:
        captured.append(command)
        return ExecuteTaskResult(
            run_id="run_cwd",
            response="ok",
            run_state=AgentRunState(run_id="run_cwd", status=AgentStatus.COMPLETED),
            conversation_id=uuid4(),
            workspace_id=f"proj_{project_id}",
        )

    app.execute_task.execute = _execute  # type: ignore[union-attr]
    args = build_parser().parse_args(["run", "--cwd", str(tmp_path), "hello"])
    code = await dispatch(args, app, json_mode=True, quiet=True, stdin=io.StringIO(), stderr=io.StringIO())
    assert code == 0
    app.resolve_local_project.execute.assert_awaited_once()
    assert captured[0].project_id == project_id


@pytest.mark.asyncio
async def test_chat_reuses_conversation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    conv = uuid4()
    execute_task = AsyncMock()
    seen: list[ExecuteTaskCommand] = []

    async def _execute(command: ExecuteTaskCommand) -> ExecuteTaskResult:
        seen.append(command)
        return ExecuteTaskResult(
            run_id=f"run_{len(seen)}",
            response="turn",
            run_state=AgentRunState(run_id=f"run_{len(seen)}", status=AgentStatus.COMPLETED),
            conversation_id=conv,
            workspace_id="ws",
        )

    execute_task.execute = _execute
    app = _app(execute_task=execute_task, user=user)
    args = build_parser().parse_args(["chat"])
    stdin = io.StringIO("first\nsecond\n:quit\n")
    code = await dispatch(args, app, json_mode=True, quiet=True, stdin=stdin, stderr=io.StringIO())
    assert code == 0
    assert len(seen) == 2
    assert seen[0].conversation_id is None
    assert seen[1].conversation_id == conv


@pytest.mark.asyncio
async def test_signal_cancellation_maps_to_exit_five(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    execute_task = AsyncMock()

    async def _hang(_command: ExecuteTaskCommand) -> ExecuteTaskResult:
        await asyncio.sleep(60)
        raise AssertionError("should have been cancelled")

    execute_task.execute = _hang
    app = _app(execute_task=execute_task, user=user)
    args = build_parser().parse_args(["run", "long task"])
    task = asyncio.create_task(
        async_execute(
            args,
            json_mode=True,
            quiet=True,
            debug=False,
            stdin=io.StringIO(),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            app=app,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    code = await task
    assert code == int(ExitCode.TIMEOUT_CANCELLED)


@pytest.mark.asyncio
async def test_health_does_not_call_execute_task() -> None:
    execute_task = AsyncMock()
    app = _app(execute_task=execute_task)
    app.health_check = AsyncMock(return_value={"status": "healthy", "database": "connected"})
    args = build_parser().parse_args(["health", "--json"])
    stdout = io.StringIO()
    app.stdout = stdout
    code = await dispatch(args, app, json_mode=True, quiet=True, stdin=io.StringIO(), stderr=io.StringIO())
    assert code == 0
    execute_task.execute.assert_not_called()
    payload = json.loads(stdout.getvalue())
    assert payload["status"] == "healthy"


@pytest.mark.asyncio
async def test_project_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    now = datetime.utcnow()
    project = ProjectResponseDTO(
        id=uuid4(),
        user_id=user.id,
        name="demo",
        description=None,
        repository_url=None,
        local_path="/tmp/demo",
        language=None,
        framework=None,
        created_at=now,
        updated_at=now,
        last_indexed_at=None,
        is_active=True,
    )
    stdout = io.StringIO()
    app = _app(user=user, stdout=stdout, projects=[project])
    args = build_parser().parse_args(["project", "list", "--json"])
    code = await dispatch(args, app, json_mode=True, quiet=True, stdin=io.StringIO(), stderr=io.StringIO())
    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["projects"][0]["name"] == "demo"


def test_execute_with_injected_app_does_not_need_database(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    stdout = io.StringIO()
    stderr = io.StringIO()
    app = _app(user=user, stdout=stdout, stderr=stderr)
    args = build_parser().parse_args(["run", "--json", "hello"])
    code = execute(args, stdin=io.StringIO(), stdout=stdout, stderr=stderr, app=app)
    assert code == 0
    assert json.loads(stdout.getvalue())["status"] == "success"


@pytest.mark.asyncio
async def test_cli_use_case_builds_trusted_execution_context(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from unittest.mock import MagicMock

    from app.application.agent.runtime import AgentRuntime
    from app.application.use_cases.agent.execute_task import ExecuteTaskUseCase
    from app.application.workspace.resolution_service import WorkspaceResolutionService
    from app.domain.models.project import Project

    user = _user()
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    project = Project.create(user_id=user.id, name="cli-ws", local_path=str(tmp_path / "proj"))
    (tmp_path / "proj").mkdir()
    project_repo = AsyncMock()
    project_repo.get_by_id = AsyncMock(return_value=project)
    resolution = WorkspaceResolutionService(
        project_repo=project_repo,
        base_storage_dir=str(tmp_path / "workspaces"),
        workspace_mode="local",
        workspace_root=str(tmp_path / "workspaces"),
    )
    runtime = MagicMock(spec=AgentRuntime)
    state = AgentRunState(run_id="run-ctx", status=AgentStatus.COMPLETED)
    state.final_response = "context ok"
    runtime.run = AsyncMock(return_value=state)
    use_case = ExecuteTaskUseCase(workspace_resolution_service=resolution, agent_runtime=runtime)
    stdout = io.StringIO()
    app = _app(execute_task=use_case, user=user, stdout=stdout, stderr=io.StringIO())
    args = build_parser().parse_args(["run", "--project", str(project.id), "Explain this repository"])
    code = await dispatch(args, app, json_mode=True, quiet=True, stdin=io.StringIO(), stderr=io.StringIO())
    assert code == 0
    execution_context = runtime.run.await_args.kwargs["execution_context"]
    assert str(execution_context.user_id) == str(user.id)
    assert str(execution_context.project_id) == str(project.id)
    assert execution_context.workspace_id.startswith("proj_")
    assert "user_id" not in (runtime.run.await_args.kwargs.get("metadata") or {})


def test_sanitize_hides_secret_markers() -> None:
    from app.interfaces.cli.errors import sanitize_message

    assert "sk-secret" not in sanitize_message("bad api_key sk-secret")
