"""Gateway-first CLI execution. Embedded mode is explicit and never a fallback."""

from __future__ import annotations

import asyncio
import io
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.use_cases.agent.execute_task import ExecuteTaskResult
from app.domain.models.user import User
from app.interfaces.api.schemas.run_schema import RunCreateResponse
from app.interfaces.cli.app import CliApp
from app.interfaces.cli.credentials import CredentialStore, StoredCredentials
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.gateway_dispatch import _stream_turn
from app.interfaces.cli.parser import build_parser
from app.interfaces.cli.runner import execute
from app.interfaces.gateway.client import GatewayClient
from app.interfaces.gateway.errors import GatewayUnavailable


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for name in (
        "BYTEBUDDHI_GATEWAY_URL",
        "BYTEBUDDHI_API_URL",
        "BYTEBUDDHI_GATEWAY_HOST",
        "BYTEBUDDHI_GATEWAY_PORT",
        "BYTEBUDDHI_EXECUTION_MODE",
        "BYTEBUDDHI_USER_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BYTEBUDDHI_CONFIG_DIR", str(tmp_path))


class _Client:
    kwargs: dict = {}
    runs: list[dict] = []
    fail = False
    stream_fail = False
    events: list[dict] = []
    cancelled: list[str] = []

    def __init__(self, base_url: str, token: str | None = None, **kwargs: object) -> None:
        _Client.kwargs = {"base_url": base_url, "token": token, **kwargs}

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def create_run(self, **kwargs: object) -> RunCreateResponse:
        _Client.runs.append(dict(kwargs))
        if _Client.fail:
            raise GatewayUnavailable("Gateway is not reachable. ByteBuddhi will not switch to embedded mode.")
        return RunCreateResponse(run_id="run_gw", conversation_id=None, status="queued")

    async def stream_run(self, run_id: str, *, after_sequence: int = 0):
        if _Client.fail or _Client.stream_fail:
            raise GatewayUnavailable("Gateway is not reachable. ByteBuddhi will not switch to embedded mode.")
        event = {
            "event_id": "evt",
            "run_id": run_id,
            "sequence": after_sequence + 1,
            "type": "assistant_delta",
            "schema_version": 1,
            "created_at": "2026-09-25T00:00:00+00:00",
            "data": {"delta": "from-gateway"},
        }
        yield event
        yield {
            **event,
            "sequence": after_sequence + 2,
            "type": "run_completed",
            "data": {"conversation_id": str(uuid4())},
        }

    async def cancel_run(self, run_id: str):
        _Client.cancelled.append(run_id)
        return None


def _install_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _Client.kwargs = {}
    _Client.runs = []
    _Client.fail = False
    _Client.stream_fail = False
    _Client.cancelled = []
    monkeypatch.setattr("app.interfaces.cli.gateway_dispatch.GatewayClient", _Client)

    async def _ready(_stderr: object) -> None:
        return None

    monkeypatch.setattr("app.interfaces.cli.gateway_dispatch._ensure_local_gateway", _ready)


def _sign_in() -> None:
    CredentialStore().save(
        StoredCredentials(user_id=uuid4(), access_token="cli-access-token", refresh_token="cli-refresh-token")
    )


def _embedded_app(stdout: io.StringIO) -> tuple[User, CliApp]:
    user = User(
        id=uuid4(),
        email="cli@example.com",
        username="cli-user",
        password_hash="hashed",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        is_active=True,
    )
    user_repo = AsyncMock()
    user_repo.get_by_id = AsyncMock(return_value=user)
    execute_task = AsyncMock()
    execute_task.execute = AsyncMock(
        return_value=ExecuteTaskResult(
            run_id="run_embedded",
            response="from-embedded",
            run_state=AgentRunState(run_id="run_embedded", status=AgentStatus.COMPLETED),
            conversation_id=uuid4(),
            workspace_id="proj_embedded",
        )
    )
    app = CliApp(
        execute_task=execute_task,
        list_projects=AsyncMock(),
        get_project=AsyncMock(),
        resolve_local_project=AsyncMock(),
        user_repository=user_repo,
        stdout=stdout,
        stderr=io.StringIO(),
    )
    return user, app


def test_run_uses_gateway_client_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch)
    _sign_in()
    stdout = io.StringIO()
    args = build_parser().parse_args(["run", "--json", "Explain this repository"])
    code = execute(args, stdin=io.StringIO(), stdout=stdout, stderr=io.StringIO())
    assert code == int(ExitCode.SUCCESS)
    assert _Client.kwargs["token"] == "cli-access-token"
    assert _Client.runs[0]["prompt"] == "Explain this repository"
    assert "user_id" not in _Client.runs[0]
    payload = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert payload[-1]["type"] == "run_completed"
    assert any(item["data"]["delta"] == "from-gateway" for item in payload if item["type"] == "assistant_delta")
    assert "cli-access-token" not in stdout.getvalue()
    assert "\x1b" not in stdout.getvalue()
    assert len(_Client.runs) == 1


def test_embedded_flag_uses_in_process_path(monkeypatch: pytest.MonkeyPatch) -> None:
    entered = {"yes": False}
    stdout = io.StringIO()
    user, app = _embedded_app(stdout)

    @asynccontextmanager
    async def _session(**_kwargs: object):
        entered["yes"] = True
        yield app

    monkeypatch.setattr("app.interfaces.cli.bootstrap.cli_session", _session)
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    args = build_parser().parse_args(["run", "--embedded", "--json", "hello"])
    code = execute(args, stdin=io.StringIO(), stdout=stdout, stderr=io.StringIO())
    assert code == int(ExitCode.SUCCESS)
    assert entered["yes"] is True
    assert json.loads(stdout.getvalue())["answer"] == "from-embedded"


def test_execution_mode_env_selects_embedded(monkeypatch: pytest.MonkeyPatch) -> None:
    entered = {"yes": False}
    stdout = io.StringIO()
    user, app = _embedded_app(stdout)

    @asynccontextmanager
    async def _session(**_kwargs: object):
        entered["yes"] = True
        yield app

    monkeypatch.setattr("app.interfaces.cli.bootstrap.cli_session", _session)
    monkeypatch.setenv("BYTEBUDDHI_EXECUTION_MODE", "embedded")
    monkeypatch.setenv("BYTEBUDDHI_USER_ID", str(user.id))
    args = build_parser().parse_args(["run", "hello"])
    code = execute(args, stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO())
    assert code == int(ExitCode.SUCCESS)
    assert entered["yes"] is True


def test_gateway_failure_does_not_fall_back_to_embedded(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch)
    _Client.fail = True
    _sign_in()

    def _boom(*_args: object, **_kwargs: object):
        raise AssertionError("embedded session started")

    monkeypatch.setattr("app.interfaces.cli.bootstrap.cli_session", _boom)
    stderr = io.StringIO()
    stdout = io.StringIO()
    args = build_parser().parse_args(["run", "--json", "hello"])
    code = execute(args, stdin=io.StringIO(), stdout=stdout, stderr=stderr)
    assert code == int(ExitCode.EXECUTION_FAILURE)
    assert "will not switch to embedded mode" in stderr.getvalue().lower()
    assert "cli-access-token" not in stderr.getvalue()
    assert "cli-access-token" not in stdout.getvalue()


def test_remote_gateway_and_no_start_flag_do_not_autostart(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch)
    _sign_in()

    async def _forbidden(_stderr: object) -> None:
        raise AssertionError("auto-start")

    monkeypatch.setattr("app.interfaces.cli.gateway_dispatch._ensure_local_gateway", _forbidden)
    remote = build_parser().parse_args(["run", "--gateway-url", "https://gateway.example", "hello"])
    assert execute(remote, stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO()) == 0
    local = build_parser().parse_args(["run", "--no-start-gateway", "hello"])
    assert execute(local, stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO()) == 0


def test_cwd_against_remote_gateway_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch)
    _sign_in()
    stderr = io.StringIO()
    args = build_parser().parse_args(["run", "--gateway-url", "https://gateway.example", "--cwd", "C:/repo", "hello"])
    code = execute(args, stdin=io.StringIO(), stdout=io.StringIO(), stderr=stderr)
    assert code == int(ExitCode.WORKSPACE_FAILURE)
    assert "--cwd" in stderr.getvalue()
    assert _Client.runs == []


def test_human_run_streams_deltas_without_a_json_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch)
    _sign_in()
    stdout = io.StringIO()
    stderr = io.StringIO()
    args = build_parser().parse_args(["run", "Explain this repository"])
    code = execute(args, stdin=io.StringIO(), stdout=stdout, stderr=stderr)
    assert code == int(ExitCode.SUCCESS)
    assert stdout.getvalue() == "from-gateway\n"
    assert "Running task" not in stdout.getvalue()
    assert len(_Client.runs) == 1


def test_stream_disconnect_does_not_submit_another_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch)
    _Client.stream_fail = True
    _sign_in()
    stderr = io.StringIO()
    args = build_parser().parse_args(["run", "--json", "hello"])
    code = execute(args, stdin=io.StringIO(), stdout=io.StringIO(), stderr=stderr)
    assert code == int(ExitCode.EXECUTION_FAILURE)
    assert len(_Client.runs) == 1
    assert "will not switch to embedded mode" in stderr.getvalue().lower()


@pytest.mark.asyncio
async def test_ctrl_c_requests_explicit_cancellation() -> None:
    cancelled: list[str] = []

    class _Blocking:
        async def create_run(self, **_kwargs: object) -> RunCreateResponse:
            return RunCreateResponse(run_id="run_ctrl", conversation_id=None, status="queued")

        async def stream_run(self, run_id: str, *, after_sequence: int = 0):
            yield {
                "event_id": "evt",
                "run_id": run_id,
                "sequence": after_sequence + 1,
                "type": "run_started",
                "schema_version": 1,
                "created_at": "2026-09-25T00:00:00+00:00",
                "data": {},
            }
            await asyncio.Event().wait()

        async def cancel_run(self, run_id: str) -> None:
            cancelled.append(run_id)

    task = asyncio.create_task(
        _stream_turn(
            cast(GatewayClient, _Blocking()),
            prompt="stop",
            project_id=None,
            conversation_id=None,
            provider=None,
            model_name=None,
            json_mode=True,
            quiet=True,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    )
    for _ in range(50):
        if task.done():
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled == ["run_ctrl"]


def test_interrupted_run_exits_as_execution_failure() -> None:
    from app.interfaces.cli.gateway_dispatch import _render_stream_event

    stderr = io.StringIO()
    code = _render_stream_event(
        {
            "type": "run_interrupted",
            "data": {"error_message": "The worker lease expired and the run was not replayed"},
        },
        json_mode=False,
        quiet=True,
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == int(ExitCode.EXECUTION_FAILURE)
    assert "not replayed" in stderr.getvalue()
