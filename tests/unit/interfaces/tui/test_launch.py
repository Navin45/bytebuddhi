"""TUI launch reuses gateway resolution and never falls back to embedded execution."""

from __future__ import annotations

import io
from argparse import Namespace
from uuid import uuid4

import pytest

from app.interfaces.cli.credentials import CredentialStore, StoredCredentials
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.parser import build_parser
from app.interfaces.cli.runner import execute
from app.interfaces.gateway.errors import GatewayUnavailable
from app.interfaces.tui.main import launch_tui


@pytest.fixture(autouse=True)
def _isolated_gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "BYTEBUDDHI_GATEWAY_URL",
        "BYTEBUDDHI_API_URL",
        "BYTEBUDDHI_GATEWAY_HOST",
        "BYTEBUDDHI_GATEWAY_PORT",
        "BYTEBUDDHI_EXECUTION_MODE",
    ):
        monkeypatch.delenv(name, raising=False)


def _args(**overrides: object) -> Namespace:
    parser = build_parser()
    argv = ["tui"]
    gateway = overrides.get("gateway_url")
    if isinstance(gateway, str):
        argv.extend(["--gateway-url", gateway])
    if overrides.get("no_start_gateway"):
        argv.append("--no-start-gateway")
    return parser.parse_args(argv)


def _tty() -> io.StringIO:
    stream = io.StringIO()
    stream.isatty = lambda: True  # type: ignore[method-assign]
    return stream


def _credentials() -> StoredCredentials:
    return StoredCredentials(user_id=uuid4(), access_token="access-token-value", refresh_token="refresh-token-value")


@pytest.fixture
def _patched(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    calls: dict[str, list] = {"ensure": [], "run": []}

    async def ensure(stderr: io.StringIO) -> None:
        calls["ensure"].append(True)

    async def run_async(self) -> None:
        calls["run"].append(True)

    monkeypatch.setattr("app.interfaces.tui.main._ensure_local_gateway", ensure)
    monkeypatch.setattr("app.interfaces.tui.app.ByteBuddhiApp.run_async", run_async)
    monkeypatch.setattr(CredentialStore, "load", lambda self: _credentials())
    return calls


@pytest.mark.asyncio
async def test_local_gateway_is_started(_patched: dict[str, list]) -> None:
    code = await launch_tui(_args(), stdin=_tty(), stderr=io.StringIO())
    assert code == int(ExitCode.SUCCESS)
    assert _patched["ensure"] == [True]
    assert _patched["run"] == [True]


@pytest.mark.asyncio
async def test_remote_gateway_does_not_start_locally(
    _patched: dict[str, list], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BYTEBUDDHI_EXECUTION_MODE", "embedded")
    code = await launch_tui(_args(gateway_url="https://gateway.example"), stdin=_tty(), stderr=io.StringIO())
    assert code == int(ExitCode.SUCCESS)
    assert _patched["ensure"] == []
    assert _patched["run"] == [True]


@pytest.mark.asyncio
async def test_no_start_gateway_skips_the_local_process(_patched: dict[str, list]) -> None:
    code = await launch_tui(_args(no_start_gateway=True), stdin=_tty(), stderr=io.StringIO())
    assert code == int(ExitCode.SUCCESS)
    assert _patched["ensure"] == []


@pytest.mark.asyncio
async def test_unavailable_local_gateway_does_not_open_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[bool] = []

    async def ensure(_stderr: io.StringIO) -> None:
        raise GatewayUnavailable("Gateway is not reachable.")

    async def run_async(self) -> None:
        opened.append(True)

    monkeypatch.setattr("app.interfaces.tui.main._ensure_local_gateway", ensure)
    monkeypatch.setattr("app.interfaces.tui.app.ByteBuddhiApp.run_async", run_async)
    monkeypatch.setattr(CredentialStore, "load", lambda self: _credentials())
    stderr = io.StringIO()
    code = await launch_tui(_args(), stdin=_tty(), stderr=stderr)
    assert code == int(ExitCode.CONFIG_FAILURE)
    assert opened == []
    assert "Cannot connect to the ByteBuddhi gateway." in stderr.getvalue()
    assert "access-token-value" not in stderr.getvalue()


@pytest.mark.asyncio
async def test_missing_credentials_do_not_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CredentialStore, "load", lambda self: None)
    monkeypatch.setattr("app.interfaces.tui.main._ensure_local_gateway", _unused_ensure)
    stderr = io.StringIO()
    code = await launch_tui(_args(no_start_gateway=True), stdin=_tty(), stderr=stderr)
    assert code == int(ExitCode.AUTH_FAILURE)
    assert "bytebuddhi login" in stderr.getvalue()
    assert "access-token" not in stderr.getvalue()


@pytest.mark.asyncio
async def test_non_interactive_stdin_does_not_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[bool] = []

    async def run_async(self) -> None:
        opened.append(True)

    monkeypatch.setattr("app.interfaces.tui.app.ByteBuddhiApp.run_async", run_async)
    stderr = io.StringIO()
    code = await launch_tui(_args(), stdin=io.StringIO(), stderr=stderr)
    assert code == int(ExitCode.USAGE_ERROR)
    assert "interactive terminal" in stderr.getvalue()
    assert opened == []


def test_execute_routes_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def launch(args: Namespace, *, stdin: object, stderr: object, debug: bool = False) -> int:
        seen.append(args.command)
        return 0

    monkeypatch.setattr("app.interfaces.tui.main.launch_tui", launch)
    code = execute(_args(no_start_gateway=True), stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO())
    assert code == 0
    assert seen == ["tui"]


async def _unused_ensure(_stderr: io.StringIO) -> None:
    return None
