"""OAuth HTTP routes: providers, open redirect, exchange, logout."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.application.auth.oauth_service import OAuthService
from app.domain.exceptions.auth_exceptions import AuthenticationError
from app.domain.models.user import User
from app.domain.value_objects.identity_provider import AuthFailureCategory, OAuthClientKind
from app.interfaces.api.dependencies import get_oauth_service
from app.interfaces.api.middleware.error_handler import error_handler_middleware
from app.interfaces.api.routes import oauth
from app.interfaces.api.routes.auth import router as auth_router


def _user() -> User:
    return User.create(email="oauth@example.com", username="oauth-user", password_hash=None)


@pytest.fixture
def oauth_app() -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=OAuthService)
    service.enabled_providers.return_value = {"google": True, "github": False}
    app = FastAPI()
    app.middleware("http")(error_handler_middleware)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(oauth.router, prefix="/api/v1")
    app.dependency_overrides[get_oauth_service] = lambda: service
    return app, service


@pytest.mark.asyncio
async def test_providers_hide_secrets(oauth_app: tuple[FastAPI, AsyncMock]) -> None:
    app, _service = oauth_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/auth/providers")
    assert response.status_code == 200
    body = response.json()
    assert body == {"google": True, "github": False}
    assert "client_secret" not in str(body)
    assert "access_token" not in str(body)


@pytest.mark.asyncio
async def test_login_ignores_open_redirect_next(oauth_app: tuple[FastAPI, AsyncMock]) -> None:
    app, service = oauth_app
    service.start_login = AsyncMock(return_value="https://accounts.google.com/o/oauth2/v2/auth?state=abc")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as client:
        response = await client.get(
            "/api/v1/auth/google/login",
            params={"client": "web", "next": "https://attacker.example"},
        )
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://accounts.google.com/")
    assert "attacker.example" not in response.headers["location"]
    service.start_login.assert_awaited_once()
    assert service.start_login.await_args.args[1] is OAuthClientKind.WEB


@pytest.mark.asyncio
async def test_callback_missing_state(oauth_app: tuple[FastAPI, AsyncMock]) -> None:
    app, service = oauth_app
    service.complete_callback = AsyncMock(
        side_effect=AuthenticationError(
            "Sign-in expired or is invalid. Try again.",
            AuthFailureCategory.STATE_INVALID,
            http_status=400,
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/auth/google/callback", params={"code": "abc"})
    assert response.status_code == 400
    assert response.json()["error"] == "state_invalid"
    assert "abc" not in response.text


@pytest.mark.asyncio
async def test_exchange_returns_bytebuddhi_tokens(
    oauth_app: tuple[FastAPI, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, service = oauth_app
    user = _user()
    service.consume_exchange_code = AsyncMock(return_value=user)

    class _Handler:
        access_token_expire_minutes = 30

        def create_access_token(self, user_id):
            assert user_id == user.id
            return "access.jwt"

        def create_refresh_token(self, user_id):
            return "refresh.jwt"

    monkeypatch.setattr("app.interfaces.api.routes.oauth.jwt_handler", _Handler())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/oauth/exchange", json={"code": "one-time-code"})
    assert response.status_code == 200
    assert response.json()["access_token"] == "access.jwt"
    assert "gho_" not in response.text


@pytest.mark.asyncio
async def test_logout_is_stateless() -> None:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 204
