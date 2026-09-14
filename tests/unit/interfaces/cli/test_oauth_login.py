"""CLI OAuth login stores ByteBuddhi tokens, not provider secrets."""

import io
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.interfaces.cli.credentials import StoredCredentials, load_credentials, save_credentials
from app.interfaces.cli.errors import CliError
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.oauth_login import login, logout
from app.interfaces.cli.parser import build_parser


@pytest.mark.asyncio
async def test_login_with_code_stores_bytebuddhi_tokens(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTEBUDDHI_CONFIG_DIR", str(tmp_path))
    user_id = uuid4()

    class _Response:
        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url: str, json: dict) -> _Response:
            assert url.endswith("/auth/oauth/exchange")
            assert json == {"code": "one-time"}
            return _Response(200, {"access_token": "bb-access", "refresh_token": "bb-refresh"})

        async def get(self, url: str, headers: dict) -> _Response:
            assert "Bearer bb-access" in headers["Authorization"]
            return _Response(200, {"id": str(user_id)})

    with patch("app.interfaces.cli.oauth_login.httpx.AsyncClient", _Client):
        code = await login(
            provider=None,
            code="one-time",
            api_url="http://127.0.0.1:8000",
            json_mode=False,
            stdin=io.StringIO(),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    assert code == 0
    stored = load_credentials()
    assert stored is not None
    assert stored.user_id == user_id
    assert stored.access_token == "bb-access"
    assert "gho_" not in stored.access_token


def test_logout_removes_credentials(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTEBUDDHI_CONFIG_DIR", str(tmp_path))
    save_credentials(StoredCredentials(user_id=uuid4(), access_token="a", refresh_token="r"))
    stdout = io.StringIO()
    assert logout(json_mode=False, stdout=stdout) == 0
    assert load_credentials() is None


def test_parser_login_has_no_client_secret_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["login", "--provider", "google", "--code", "abc"])
    assert args.command == "login"
    assert not hasattr(args, "client_secret")


@pytest.mark.asyncio
async def test_expired_exchange_code_is_auth_failure(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTEBUDDHI_CONFIG_DIR", str(tmp_path))

    class _Response:
        status_code = 400

        def json(self) -> dict:
            return {"error": "state_invalid"}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url: str, json: dict) -> _Response:
            return _Response()

    with patch("app.interfaces.cli.oauth_login.httpx.AsyncClient", _Client), pytest.raises(CliError) as exc:
        await login(
            provider=None,
            code="expired",
            api_url="http://127.0.0.1:8000",
            json_mode=False,
            stdin=io.StringIO(),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    assert exc.value.exit_code == ExitCode.AUTH_FAILURE
