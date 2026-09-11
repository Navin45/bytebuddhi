"""Unit tests for EnvironmentPolicy sanitization and allowlisting."""

from app.domain.models.environment_policy import EnvironmentPolicy


def test_standard_allowlisting_preserves_safe_vars():
    policy = EnvironmentPolicy()
    mock_env = {
        "PATH": "/usr/bin:/bin",
        "USER": "developer",
        "HOME": "/home/developer",
        "TEMP": "/tmp",
        "SHELL": "/bin/bash",
        "CUSTOM_UNALLOWED": "some_random_value",
    }

    sanitized = policy.build_env(base_env=mock_env)
    assert sanitized["PATH"] == "/usr/bin:/bin"
    assert sanitized["USER"] == "developer"
    assert sanitized["HOME"] == "/home/developer"
    assert "CUSTOM_UNALLOWED" not in sanitized


def test_blocked_secrets_are_never_inherited():
    policy = EnvironmentPolicy()
    mock_env = {
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "sk-1234567890",
        "ANTHROPIC_API_KEY": "sk-ant-123",
        "DATABASE_URL": "postgresql://postgres:secret@db:5432/app",
        "JWT_SECRET_KEY": "supersecretjwt",
        "POSTGRES_PASSWORD": "adminpassword",
        "AWS_SECRET_ACCESS_KEY": "awssecret",
        "AUTH_TOKEN": "bearer-token-123",
    }

    sanitized = policy.build_env(base_env=mock_env)
    assert "PATH" in sanitized
    assert "OPENAI_API_KEY" not in sanitized
    assert "ANTHROPIC_API_KEY" not in sanitized
    assert "DATABASE_URL" not in sanitized
    assert "JWT_SECRET_KEY" not in sanitized
    assert "POSTGRES_PASSWORD" not in sanitized
    assert "AWS_SECRET_ACCESS_KEY" not in sanitized
    assert "AUTH_TOKEN" not in sanitized


def test_custom_env_merges_safely():
    policy = EnvironmentPolicy(custom_env={"NODE_ENV": "development", "DEBUG": "1"})
    mock_env = {"PATH": "/usr/bin"}

    sanitized = policy.build_env(base_env=mock_env)
    assert sanitized["NODE_ENV"] == "development"
    assert sanitized["DEBUG"] == "1"


def test_custom_env_cannot_inject_secrets():
    policy = EnvironmentPolicy(custom_env={"MY_SECRET_KEY": "injected_secret", "SAFE_VAR": "valid"})
    mock_env = {"PATH": "/usr/bin"}

    sanitized = policy.build_env(base_env=mock_env)
    assert "MY_SECRET_KEY" not in sanitized
    assert sanitized["SAFE_VAR"] == "valid"


def test_extra_allowed_variables():
    policy = EnvironmentPolicy()
    mock_env = {
        "PATH": "/usr/bin",
        "GIT_AUTHOR_NAME": "ByteBuddhi",
        "RANDOM_VAR": "ignored",
    }

    sanitized = policy.build_env(base_env=mock_env, extra_allowed={"GIT_AUTHOR_NAME"})
    assert sanitized["GIT_AUTHOR_NAME"] == "ByteBuddhi"
    assert "RANDOM_VAR" not in sanitized
