"""Versioned local configuration schema and non-destructive migrations.

Preserves unknown user fields across releases so newer or older CLI/UI
versions never wipe custom settings.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app._version import DEFAULT_CHANNEL, STABLE_CHANNEL
from app.interfaces.gateway.config import config_dir

CURRENT_CONFIG_VERSION = 1
CONFIG_FILE_NAME = "config.json"

_KNOWN_FIELDS = {
    "config_version",
    "gateway_url",
    "channel",
    "theme",
    "model_provider",
    "model_name",
    "auto_start_gateway",
    "profile",
}


@dataclass
class LocalConfig:
    config_version: int = CURRENT_CONFIG_VERSION
    gateway_url: str | None = None
    channel: str = DEFAULT_CHANNEL
    theme: str = "system"
    model_provider: str | None = None
    model_name: str | None = None
    auto_start_gateway: bool = True
    profile: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.extra)
        result.update(
            {
                "config_version": self.config_version,
                "gateway_url": self.gateway_url,
                "channel": self.channel,
                "theme": self.theme,
                "model_provider": self.model_provider,
                "model_name": self.model_name,
                "auto_start_gateway": self.auto_start_gateway,
            }
        )
        if self.profile:
            result["profile"] = self.profile
        return result


def migrate_config_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate config data dictionary across schema versions preserving all unknown fields."""
    migrated = dict(raw)
    current_version = raw.get("config_version")

    # If unversioned legacy config, default to version 1
    if not isinstance(current_version, int) or current_version < 1:
        current_version = 1

    # Future version migrations (e.g. 1 -> 2, 2 -> 3) would chain sequentially here:
    # if current_version == 1:
    #     migrated = _migrate_v1_to_v2(migrated)
    #     current_version = 2

    migrated["config_version"] = CURRENT_CONFIG_VERSION
    return migrated


def local_config_path(directory: Path | None = None) -> Path:
    base = directory if directory is not None else config_dir()
    return base / CONFIG_FILE_NAME


def load_local_config(directory: Path | None = None) -> LocalConfig:
    """Load configuration from disk.

    Migrates schema if version < CURRENT_CONFIG_VERSION and preserves unknown fields.
    """
    path = local_config_path(directory)
    if not path.is_file():
        return LocalConfig()

    try:
        raw_text = path.read_text(encoding="utf-8")
        parsed = json.loads(raw_text)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return LocalConfig()

    if not isinstance(parsed, dict):
        return LocalConfig()

    migrated = migrate_config_dict(parsed)
    extra = {k: v for k, v in migrated.items() if k not in _KNOWN_FIELDS}

    return LocalConfig(
        config_version=int(migrated.get("config_version", CURRENT_CONFIG_VERSION)),
        gateway_url=str(migrated["gateway_url"]) if migrated.get("gateway_url") is not None else None,
        channel=str(migrated.get("channel") or STABLE_CHANNEL),
        theme=str(migrated.get("theme") or "system"),
        model_provider=str(migrated["model_provider"]) if migrated.get("model_provider") is not None else None,
        model_name=str(migrated["model_name"]) if migrated.get("model_name") is not None else None,
        auto_start_gateway=bool(migrated.get("auto_start_gateway", True)),
        profile=str(migrated["profile"]) if migrated.get("profile") else None,
        extra=extra,
    )


def save_local_config(config: LocalConfig, directory: Path | None = None) -> Path:
    """Save configuration atomically to disk."""
    path = local_config_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.to_dict()
    data["config_version"] = CURRENT_CONFIG_VERSION
    content = json.dumps(data, indent=2, sort_keys=True)

    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(content, encoding="utf-8")
    os.replace(temp_path, path)
    return path
