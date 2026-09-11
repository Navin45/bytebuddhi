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
