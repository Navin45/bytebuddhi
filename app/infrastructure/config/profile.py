"""Execution profile resolution.

Precedence is explicit CLI, then ``BYTEBUDDHI_PROFILE``, then the persisted
local configuration, then ``server``. Existing installations stay on the
PostgreSQL profile until a person selects standalone.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from app.interfaces.gateway.config import config_dir

PROFILE_ENV = "BYTEBUDDHI_PROFILE"
SQLITE_PATH_ENV = "BYTEBUDDHI_SQLITE_PATH"
SERVER = "server"
STANDALONE = "standalone"
_PROFILES = frozenset({SERVER, STANDALONE})


class UnknownProfileError(ValueError):
    """Raised when a profile name is not server or standalone."""


def resolve_profile(
    *,
    cli: str | None = None,
    environ: Mapping[str, str] | None = None,
    persisted: str | None = None,
) -> str:
    """Return the active profile. Default is server."""
    env = environ if environ is not None else os.environ
    for raw in (cli, env.get(PROFILE_ENV), persisted):
        if raw is None:
            continue
        value = str(raw).strip().lower()
        if not value:
            continue
        if value not in _PROFILES:
            raise UnknownProfileError(f"Unknown profile: {value}")
        return value
    return SERVER


def is_standalone(
    *,
    cli: str | None = None,
    environ: Mapping[str, str] | None = None,
    persisted: str | None = None,
) -> bool:
    return resolve_profile(cli=cli, environ=environ, persisted=persisted) == STANDALONE


def apply_process_profile(cli: str | None = None) -> str:
    """Resolve the profile and publish it for child processes, including the gateway."""
    from app.infrastructure.config.local_config import load_local_config

    selected = resolve_profile(cli=cli, persisted=load_local_config().profile)
    os.environ[PROFILE_ENV] = selected
    return selected


def sqlite_database_path() -> Path:
    """SQLite file under the platform config directory, not the repository."""
    override = (os.environ.get(SQLITE_PATH_ENV) or "").strip()
    if override:
        return Path(override)
    return config_dir() / "data" / "bytebuddhi.db"


def artifact_directory() -> Path:
    if is_standalone():
        return config_dir() / "artifacts"
    return Path("./storage/artifacts")


def describe_profile() -> dict[str, str]:
    """Non-secret profile summary for doctor and health output."""
    selected = resolve_profile(persisted=_persisted_profile())
    if selected == STANDALONE:
        path = sqlite_database_path()
        return {
            "profile": STANDALONE,
            "storage": "sqlite",
            "database_path": str(path),
            "redis": "not_used",
            "execution_mode": "local",
        }
    return {
        "profile": SERVER,
        "storage": "postgresql",
        "database_path": "",
        "redis": "used",
        "execution_mode": "distributed",
    }


def _persisted_profile() -> str | None:
    from app.infrastructure.config.local_config import load_local_config

    return load_local_config().profile
