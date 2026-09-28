"""Atomic local gateway runtime metadata. Never store secrets here."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

STATE_FILENAME = "gateway.json"
LOCK_FILENAME = "gateway.lock"
CLAIM_FILENAME = "gateway.starting"
SHUTDOWN_FILENAME = "gateway.shutdown"
LOG_FILENAME = "gateway.log"


@dataclass(frozen=True)
class GatewayState:
    pid: int | None
    bind_host: str
    port: int
    url: str
    started_at: str
    version: str


def state_path(directory: Path) -> Path:
    return directory / STATE_FILENAME


def lock_path(directory: Path) -> Path:
    return directory / LOCK_FILENAME


def claim_path(directory: Path) -> Path:
    return directory / CLAIM_FILENAME


def shutdown_path(directory: Path) -> Path:
    return directory / SHUTDOWN_FILENAME


def log_path(directory: Path) -> Path:
    return directory / LOG_FILENAME


def load_state(directory: Path) -> GatewayState | None:
    path = state_path(directory)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        pid_raw = raw.get("pid")
        pid = int(pid_raw) if pid_raw is not None else None
        return GatewayState(
            pid=pid,
            bind_host=str(raw["bind_host"]),
            port=int(raw["port"]),
            url=str(raw["url"]),
            started_at=str(raw["started_at"]),
            version=str(raw.get("version") or ""),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_state(directory: Path, state: GatewayState) -> None:
    payload = {
        "pid": state.pid,
        "bind_host": state.bind_host,
        "port": state.port,
        "url": state.url,
        "started_at": state.started_at,
        "version": state.version,
    }
    atomic_write_text(state_path(directory), json.dumps(payload, sort_keys=True))


def clear_state(directory: Path) -> None:
    state_path(directory).unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def clear_shutdown(directory: Path) -> None:
    shutdown_path(directory).unlink(missing_ok=True)


def request_shutdown(directory: Path) -> None:
    atomic_write_text(shutdown_path(directory), "stop\n")
