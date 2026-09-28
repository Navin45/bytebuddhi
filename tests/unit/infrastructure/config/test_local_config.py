from pathlib import Path

from app.infrastructure.config.local_config import (
    CURRENT_CONFIG_VERSION,
    LocalConfig,
    load_local_config,
    migrate_config_dict,
    save_local_config,
)


def test_default_config_when_no_file(tmp_path: Path) -> None:
    cfg = load_local_config(tmp_path)
    assert cfg.config_version == CURRENT_CONFIG_VERSION
    assert cfg.channel == "stable"
    assert cfg.extra == {}


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cfg = LocalConfig(
        gateway_url="http://127.0.0.1:9999",
        channel="beta",
        extra={"custom_feature_flag": True, "nested": {"key": "val"}},
    )
    save_local_config(cfg, tmp_path)

    loaded = load_local_config(tmp_path)
    assert loaded.config_version == CURRENT_CONFIG_VERSION
    assert loaded.gateway_url == "http://127.0.0.1:9999"
    assert loaded.channel == "beta"
    assert loaded.extra["custom_feature_flag"] is True
    assert loaded.extra["nested"] == {"key": "val"}


def test_migration_preserves_unknown_fields() -> None:
    raw = {
        "config_version": 0,
        "legacy_key": "some_value",
        "custom_token_endpoint": "https://auth.internal.corp",
    }
    migrated = migrate_config_dict(raw)
    assert migrated["config_version"] == CURRENT_CONFIG_VERSION
    assert migrated["legacy_key"] == "some_value"
    assert migrated["custom_token_endpoint"] == "https://auth.internal.corp"
