"""OAuth configuration fail-closed tests."""

import pytest

from app.infrastructure.config.settings import Settings


def test_enabled_provider_requires_secrets() -> None:
    settings = Settings(google_oauth_enabled=True, google_client_id="", google_client_secret="")
    with pytest.raises(RuntimeError, match="Google OAuth is enabled"):
        settings.validate_oauth_configuration()


def test_half_configured_secrets_fail_even_when_disabled() -> None:
    settings = Settings(google_oauth_enabled=False, google_client_id="id-only", google_client_secret="")
    with pytest.raises(RuntimeError, match="both be set"):
        settings.validate_oauth_configuration()


def test_google_only_enabled_is_valid() -> None:
    settings = Settings(
        google_oauth_enabled=True,
        google_client_id="id",
        google_client_secret="secret",
        google_redirect_uri="http://127.0.0.1:8000/api/v1/auth/google/callback",
        github_oauth_enabled=False,
    )
    settings.validate_oauth_configuration()


def test_github_only_enabled_is_valid() -> None:
    settings = Settings(
        github_oauth_enabled=True,
        github_client_id="id",
        github_client_secret="secret",
        github_redirect_uri="http://127.0.0.1:8000/api/v1/auth/github/callback",
        google_oauth_enabled=False,
    )
    settings.validate_oauth_configuration()


def test_production_rejects_http_non_loopback_callback() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="a" * 32,
        debug=False,
        workspace_mode="managed",
        database_url="postgresql+asyncpg://bytebuddhi:strong-unique-password@db:5432/bytebuddhi",
        google_oauth_enabled=True,
        google_client_id="id",
        google_client_secret="secret",
        google_redirect_uri="http://example.com/callback",
    )
    with pytest.raises(RuntimeError, match="HTTPS"):
        settings.validate_runtime_configuration()


def test_production_rejects_http_post_login_redirect() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="a" * 32,
        debug=False,
        workspace_mode="managed",
        database_url="postgresql+asyncpg://bytebuddhi:strong-unique-password@db:5432/bytebuddhi",
        oauth_post_login_redirect="http://attacker.example/land",
    )
    with pytest.raises(RuntimeError, match="HTTPS"):
        settings.validate_oauth_configuration()
