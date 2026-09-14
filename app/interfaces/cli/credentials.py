"""Local CLI credential file. Stores ByteBuddhi JWTs, never provider secrets."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.interfaces.cli.errors import CliError
from app.interfaces.cli.exit_codes import ExitCode

_DIR_ENV = "BYTEBUDDHI_CONFIG_DIR"
_FILENAME = "credentials.json"


@dataclass(frozen=True)
class StoredCredentials:
    user_id: UUID
    access_token: str
    refresh_token: str


def config_dir() -> Path:
    override = (os.environ.get(_DIR_ENV) or "").strip()
    if override:
        return Path(override)
    return Path.home() / ".bytebuddhi"


def credentials_path() -> Path:
    return config_dir() / _FILENAME


def load_credentials() -> StoredCredentials | None:
    path = credentials_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError("Stored credentials are unreadable. Sign in again.", ExitCode.AUTH_FAILURE) from exc
    try:
        return StoredCredentials(
            user_id=UUID(str(raw["user_id"])),
            access_token=str(raw["access_token"]),
            refresh_token=str(raw["refresh_token"]),
        )
    except (KeyError, ValueError) as exc:
        raise CliError("Stored credentials are invalid. Sign in again.", ExitCode.AUTH_FAILURE) from exc


def save_credentials(credentials: StoredCredentials) -> None:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = credentials_path()
    payload = json.dumps(
        {
            "user_id": str(credentials.user_id),
            "access_token": credentials.access_token,
            "refresh_token": credentials.refresh_token,
        }
    )
    path.write_text(payload, encoding="utf-8")
    with suppress(OSError):
        os.chmod(path, 0o600)


def delete_credentials() -> bool:
    path = credentials_path()
    if not path.is_file():
        return False
    path.unlink()
    return True
