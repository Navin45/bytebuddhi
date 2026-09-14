"""Google OIDC adapter verification tests."""

from unittest.mock import AsyncMock

import pytest

from app.domain.exceptions.auth_exceptions import AuthenticationError
from app.domain.exceptions.connector_exceptions import ConnectorTimeoutError
from app.domain.value_objects.identity_provider import AuthFailureCategory
from app.infrastructure.auth.oauth.google_provider import GoogleOAuthProvider


class _Verifier:
    def __init__(self, claims: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self.claims = claims or {}
        self.error = error

    def verify(self, token: str, audience: str) -> dict[str, object]:
        if self.error:
            raise self.error
        return self.claims


def _provider(claims: dict[str, object] | None = None, error: Exception | None = None) -> GoogleOAuthProvider:
    http = AsyncMock()
    http.post = AsyncMock(return_value={"id_token": "signed-jwt"})
    return GoogleOAuthProvider(
        client_id="client-id",
        client_secret="client-secret",
        http_client=http,
        verifier=_Verifier(claims, error),
    )


@pytest.mark.asyncio
async def test_google_valid_identity() -> None:
    provider = _provider(
        {
            "iss": "https://accounts.google.com",
            "aud": "client-id",
            "sub": "stable-sub",
            "email": "user@example.com",
            "email_verified": True,
            "name": "User",
        }
    )
    identity = await provider.exchange_code(code="ok", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert identity.subject == "stable-sub"
    assert identity.email_verified is True


@pytest.mark.asyncio
async def test_google_wrong_issuer() -> None:
    provider = _provider({"iss": "https://evil.example", "aud": "client-id", "sub": "x"})
    with pytest.raises(AuthenticationError) as exc:
        await provider.exchange_code(code="ok", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert exc.value.category is AuthFailureCategory.IDENTITY_VERIFICATION_FAILED


@pytest.mark.asyncio
async def test_google_wrong_audience() -> None:
    provider = _provider({"iss": "https://accounts.google.com", "aud": "other-client", "sub": "x"})
    with pytest.raises(AuthenticationError) as exc:
        await provider.exchange_code(code="ok", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert exc.value.category is AuthFailureCategory.IDENTITY_VERIFICATION_FAILED


@pytest.mark.asyncio
async def test_google_invalid_signature() -> None:
    provider = _provider(error=ValueError("invalid token"))
    with pytest.raises(AuthenticationError) as exc:
        await provider.exchange_code(code="ok", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert exc.value.category is AuthFailureCategory.IDENTITY_VERIFICATION_FAILED


@pytest.mark.asyncio
async def test_google_missing_subject() -> None:
    provider = _provider({"iss": "https://accounts.google.com", "aud": "client-id"})
    with pytest.raises(AuthenticationError) as exc:
        await provider.exchange_code(code="ok", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert exc.value.category is AuthFailureCategory.IDENTITY_VERIFICATION_FAILED


@pytest.mark.asyncio
async def test_google_unverified_email_flag() -> None:
    provider = _provider(
        {
            "iss": "accounts.google.com",
            "aud": "client-id",
            "sub": "sub",
            "email": "user@example.com",
            "email_verified": False,
        }
    )
    identity = await provider.exchange_code(code="ok", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert identity.email_verified is False


@pytest.mark.asyncio
async def test_google_timeout() -> None:
    http = AsyncMock()
    http.post = AsyncMock(side_effect=ConnectorTimeoutError("timeout", provider="google-oauth"))
    provider = GoogleOAuthProvider(
        client_id="client-id",
        client_secret="client-secret",
        http_client=http,
        verifier=_Verifier({"sub": "x"}),
    )
    with pytest.raises(AuthenticationError) as exc:
        await provider.exchange_code(code="ok", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert exc.value.category is AuthFailureCategory.PROVIDER_UNAVAILABLE


def test_google_authorization_url_includes_state_and_pkce() -> None:
    provider = _provider({"sub": "x"})
    url = provider.build_authorization_url(
        state="abc",
        code_challenge="challenge",
        redirect_uri="http://127.0.0.1/cb",
    )
    assert "state=abc" in url
    assert "code_challenge=challenge" in url
    assert "access_type=offline" not in url
    assert "repo" not in url
