"""Configured model catalog and OpenAI-compatible operator endpoint."""

import pytest

from app.infrastructure.config.settings import Settings
from app.infrastructure.llm.provider_factory import (
    LLMProviderType,
    build_model_catalog,
    create_model_gateway,
    enabled_provider_ids,
)


def test_catalog_marks_missing_credentials_unavailable() -> None:
    cfg = Settings(
        openai_api_key=None,
        anthropic_api_key=None,
        default_model_provider="openai",
        default_model_name="gpt-4-turbo-preview",
        openai_model="gpt-4-turbo-preview",
        openai_models="gpt-4-turbo-preview",
        anthropic_model="claude-3-5-sonnet-20241022",
        anthropic_models="claude-3-5-sonnet-20241022",
        enabled_providers="openai,anthropic",
        openai_compatible_enabled=False,
    )
    catalog = build_model_catalog(cfg)
    openai = next(item for item in catalog.list_models() if item.provider == "openai")
    assert openai.available is False


def test_enabled_providers_restrict_catalog() -> None:
    cfg = Settings(
        openai_api_key="sk-test-not-real",
        anthropic_api_key="sk-ant-test-not-real",
        enabled_providers="anthropic",
        default_model_provider="anthropic",
        default_model_name="claude-3-5-sonnet-20241022",
        anthropic_model="claude-3-5-sonnet-20241022",
        anthropic_models="claude-3-5-sonnet-20241022",
        openai_compatible_enabled=False,
    )
    catalog = build_model_catalog(cfg)
    assert enabled_provider_ids(cfg) == ["anthropic"]
    assert all(item.provider == "anthropic" for item in catalog.list_models())


def test_openai_compatible_requires_operator_url() -> None:
    cfg = Settings(openai_compatible_enabled=True, openai_compatible_base_url=None)
    with pytest.raises(RuntimeError, match="OPENAI_COMPATIBLE_BASE_URL"):
        cfg.validate_model_settings()


def test_create_compatible_adapter_rejects_request_style_factory() -> None:
    with pytest.raises(ValueError, match="server configuration"):
        create_model_gateway(LLMProviderType.OPENAI_COMPATIBLE, api_key="x", model="y")


def test_invalid_default_model_fails_closed() -> None:
    cfg = Settings(
        openai_api_key="sk-test-not-real",
        default_model_provider="openai",
        default_model_name="does-not-exist",
        openai_model="gpt-4-turbo-preview",
        openai_models="gpt-4-turbo-preview",
        enabled_providers="openai",
        openai_compatible_enabled=False,
    )
    with pytest.raises(RuntimeError, match="not registered"):
        build_model_catalog(cfg)
