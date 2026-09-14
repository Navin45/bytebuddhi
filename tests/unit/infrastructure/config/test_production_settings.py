"""Production configuration fail-closed behavior."""

import pytest

from app.infrastructure.config.settings import Settings


def test_production_rejects_placeholder_jwt_secret() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="your-super-secret-jwt-key-change-this",
        debug=False,
        workspace_mode="managed",
        database_url="postgresql+asyncpg://bytebuddhi:strong-unique-password@db:5432/bytebuddhi",
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        settings.validate_runtime_configuration()


def test_production_rejects_debug_true() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="a" * 32,
        debug=True,
        workspace_mode="managed",
        database_url="postgresql+asyncpg://bytebuddhi:strong-unique-password@db:5432/bytebuddhi",
    )
    with pytest.raises(RuntimeError, match="DEBUG"):
        settings.validate_runtime_configuration()


def test_production_rejects_local_workspace_mode() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="a" * 32,
        debug=False,
        workspace_mode="local",
        database_url="postgresql+asyncpg://bytebuddhi:strong-unique-password@db:5432/bytebuddhi",
    )
    with pytest.raises(RuntimeError, match="WORKSPACE_MODE"):
        settings.validate_runtime_configuration()


def test_development_allows_local_defaults() -> None:
    settings = Settings(app_env="development")
    settings.validate_runtime_configuration()
    settings.validate_model_settings()


def test_production_rejects_unavailable_default_model() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="a" * 32,
        debug=False,
        workspace_mode="managed",
        database_url="postgresql+asyncpg://bytebuddhi:strong-unique-password@db:5432/bytebuddhi",
        openai_api_key=None,
        default_model_provider="openai",
        default_model_name="gpt-4-turbo-preview",
        openai_model="gpt-4-turbo-preview",
        openai_models="gpt-4-turbo-preview",
        enabled_providers="openai",
    )
    with pytest.raises(RuntimeError, match="not available"):
        settings.validate_model_settings()


def test_production_rejects_default_database_password() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="a" * 32,
        debug=False,
        workspace_mode="managed",
        database_url="postgresql+asyncpg://bytebuddhi:password@localhost:5432/bytebuddhi",
    )
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        settings.validate_runtime_configuration()


def test_production_rejects_wildcard_cors() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="a" * 32,
        debug=False,
        workspace_mode="managed",
        database_url="postgresql+asyncpg://bytebuddhi:strong-unique-password@db:5432/bytebuddhi",
        cors_origins=["*"],
    )
    with pytest.raises(RuntimeError, match="CORS"):
        settings.validate_runtime_configuration()


def test_production_rejects_unisolated_browser_render() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="a" * 32,
        debug=False,
        workspace_mode="managed",
        database_url="postgresql+asyncpg://bytebuddhi:strong-unique-password@db:5432/bytebuddhi",
        web_render_enabled=True,
        web_render_isolated=False,
    )
    with pytest.raises(RuntimeError, match="WEB_RENDER"):
        settings.validate_runtime_configuration()
