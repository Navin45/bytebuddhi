"""Unit tests for Credential domain model and CredentialProvider."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models.credential import Credential, CredentialType
from app.infrastructure.connectors.credentials.env_credential_provider import (
    EnvAndDictCredentialProvider,
)


def test_credential_secret_masking():
    """Verify Credential never exposes plain secret in repr or safe dict."""
    cred = Credential(
        name="gh_token",
        provider="github",
        credential_type=CredentialType.BEARER_TOKEN,
        secret_value="ghp_1234567890abcdef1234567890abcdef",
    )

    masked = cred.masked_secret()
    assert "1234567890abcdef1234567890abcdef" not in masked
    assert masked.startswith("ghp_")
    assert "..." in masked

    safe_dict = cred.to_safe_dict()
    assert "secret_value" not in safe_dict
    assert safe_dict["secret"] == masked
    assert safe_dict["name"] == "gh_token"
    assert safe_dict["provider"] == "github"

    # Short secret masking
    short_cred = Credential(
        name="short",
        provider="github",
        credential_type=CredentialType.API_KEY,
        secret_value="secret",
    )
    assert short_cred.masked_secret() == "******"


def test_credential_expiration():
    """Verify Credential expiration detection."""
    now = datetime.now(UTC)
    expired_cred = Credential(
        name="expired",
        provider="github",
        credential_type=CredentialType.BEARER_TOKEN,
        secret_value="val",
        expires_at=now - timedelta(hours=1),
    )
    assert expired_cred.is_expired is True

    valid_cred = Credential(
        name="valid",
        provider="github",
        credential_type=CredentialType.BEARER_TOKEN,
        secret_value="val",
        expires_at=now + timedelta(hours=1),
    )
    assert valid_cred.is_expired is False


@pytest.mark.asyncio
async def test_credential_provider_user_tenant_isolation():
    """Verify tenant and user credential isolation in EnvAndDictCredentialProvider."""
    provider = EnvAndDictCredentialProvider()

    alice_cred = Credential(
        name="alice_token",
        provider="github",
        credential_type=CredentialType.BEARER_TOKEN,
        secret_value="alice_secret_token_123",
    )
    bob_cred = Credential(
        name="bob_token",
        provider="github",
        credential_type=CredentialType.BEARER_TOKEN,
        secret_value="bob_secret_token_456",
    )

    await provider.set_credential("github", alice_cred, user_id="alice")
    await provider.set_credential("github", bob_cred, user_id="bob")

    # Alice gets Alice's credential
    res_alice = await provider.get_credential("github", user_id="alice")
    assert res_alice is not None
    assert res_alice.secret_value == "alice_secret_token_123"

    # Bob gets Bob's credential
    res_bob = await provider.get_credential("github", user_id="bob")
    assert res_bob is not None
    assert res_bob.secret_value == "bob_secret_token_456"

    # Charlie gets None (no env fallback yet)
    res_charlie = await provider.get_credential("github", user_id="charlie")
    assert res_charlie is None


@pytest.mark.asyncio
async def test_credential_provider_env_fallback(monkeypatch: pytest.MonkeyPatch):
    """Verify fallback to environment variables when explicit user credential is not registered."""
    provider = EnvAndDictCredentialProvider()

    monkeypatch.setenv("GITHUB_TOKEN", "env_github_token_xyz")

    cred = await provider.get_credential("github", user_id="unknown_user")
    assert cred is not None
    assert cred.secret_value == "env_github_token_xyz"
    assert cred.provider == "github"


@pytest.mark.asyncio
async def test_credential_provider_removal():
    """Verify credential removal."""
    provider = EnvAndDictCredentialProvider()
    cred = Credential(
        name="tok",
        provider="slack",
        credential_type=CredentialType.BEARER_TOKEN,
        secret_value="xoxb-12345",
    )
    await provider.set_credential("slack", cred, user_id="u1")
    assert await provider.get_credential("slack", user_id="u1") is not None

    removed = await provider.remove_credential("slack", user_id="u1")
    assert removed is True
    assert await provider.get_credential("slack", user_id="u1") is None
