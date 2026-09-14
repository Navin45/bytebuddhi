"""GitHub OAuth adapter identity and email tests."""

from unittest.mock import AsyncMock

import pytest

from app.domain.exceptions.auth_exceptions import AuthenticationError
from app.domain.value_objects.identity_provider import AuthFailureCategory
from app.infrastructure.auth.oauth.github_provider import GitHubOAuthProvider


def _provider(responses: list[object]) -> GitHubOAuthProvider:
    http = AsyncMock()
    http.post = AsyncMock(return_value=responses[0])
    http.get = AsyncMock(side_effect=responses[1:])
    return GitHubOAuthProvider(
        client_id="client-id",
        client_secret="client-secret",
        http_client=http,
    )


@pytest.mark.asyncio
async def test_github_profile_and_verified_email() -> None:
    provider = _provider(
        [
            {"access_token": "gho_tmp"},
            {"id": 12345, "login": "octocat", "email": None, "avatar_url": "https://example/a.png"},
            [
                {"email": "hidden@example.com", "primary": True, "verified": True},
                {"email": "other@example.com", "primary": False, "verified": True},
            ],
        ]
    )
    identity = await provider.exchange_code(code="ok", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert identity.subject == "12345"
    assert identity.email == "hidden@example.com"
    assert identity.email_verified is True
    assert identity.display_name == "octocat"


@pytest.mark.asyncio
async def test_github_unverified_emails_are_not_marked_verified() -> None:
    provider = _provider(
        [
            {"access_token": "gho_tmp"},
            {"id": 9, "login": "user", "email": "visible@example.com"},
            [{"email": "visible@example.com", "primary": True, "verified": False}],
        ]
    )
    identity = await provider.exchange_code(code="ok", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert identity.email == "visible@example.com"
    assert identity.email_verified is False


@pytest.mark.asyncio
async def test_github_missing_email() -> None:
    provider = _provider(
        [
            {"access_token": "gho_tmp"},
            {"id": 9, "login": "user", "email": None},
            [],
        ]
    )
    identity = await provider.exchange_code(code="ok", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert identity.email is None
    assert identity.email_verified is False


@pytest.mark.asyncio
async def test_github_invalid_token_response() -> None:
    provider = _provider([{"error": "bad_verification_code"}])
    with pytest.raises(AuthenticationError) as exc:
        await provider.exchange_code(code="bad", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert exc.value.category is AuthFailureCategory.CODE_EXCHANGE_FAILED


@pytest.mark.asyncio
async def test_github_malformed_profile_id() -> None:
    provider = _provider(
        [
            {"access_token": "gho_tmp"},
            {"id": "octocat", "login": "octocat"},
        ]
    )
    with pytest.raises(AuthenticationError) as exc:
        await provider.exchange_code(code="ok", code_verifier="v", redirect_uri="http://127.0.0.1/cb")
    assert exc.value.category is AuthFailureCategory.IDENTITY_VERIFICATION_FAILED


def test_github_login_url_does_not_request_repo_scopes() -> None:
    provider = _provider([{}])
    url = provider.build_authorization_url(
        state="st",
        code_challenge="ch",
        redirect_uri="http://127.0.0.1/cb",
    )
    assert "state=st" in url
    assert "repo" not in url
    assert "workflow" not in url
    assert "admin:org" not in url
    assert "user%3Aemail" in url or "user:email" in url
