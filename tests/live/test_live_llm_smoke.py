"""Optional live ModelGateway smoke. Skipped unless credentials are present.

CI must report SKIPPED when secrets are unavailable. Never print keys.
"""

from __future__ import annotations

import os

import pytest

from app.application.llm.routing import RoutingModelGateway
from app.infrastructure.config.settings import Settings
from app.infrastructure.llm.provider_factory import build_model_catalog, build_provider_registry

pytestmark = pytest.mark.live_llm


def _live_configured() -> bool:
    provider = (os.environ.get("LIVE_LLM_PROVIDER") or os.environ.get("DEFAULT_MODEL_PROVIDER") or "").strip()
    model = (os.environ.get("LIVE_LLM_MODEL") or os.environ.get("DEFAULT_MODEL_NAME") or "").strip()
    if not provider or not model:
        return False
    key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    env_name = key_map.get(provider.lower())
    if env_name is None:
        env_name = "OPENAI_COMPATIBLE_API_KEY" if provider.lower() not in {"openai", "anthropic"} else None
    if env_name is None:
        return False
    return bool((os.environ.get(env_name) or "").strip())


@pytest.mark.asyncio
@pytest.mark.skipif(not _live_configured(), reason="SKIPPED — secret unavailable")
async def test_live_model_gateway_normalized_response() -> None:
    settings = Settings()
    catalog = build_model_catalog(settings)
    gateway = RoutingModelGateway(catalog, build_provider_registry(settings))
    provider = (os.environ.get("LIVE_LLM_PROVIDER") or settings.default_model_provider).strip()
    model = (os.environ.get("LIVE_LLM_MODEL") or settings.default_model_name or settings.openai_model).strip()
    response = await gateway.generate(
        [{"role": "user", "content": "Reply with the single word pong."}],
        provider=provider,
        model=model,
        max_tokens=16,
    )
    assert response.content
    assert "sk-" not in (response.content or "")
    assert response.provider == provider
    assert response.model == model
