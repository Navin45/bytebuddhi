"""Build the routing ModelGateway, catalog, and provider adapters from settings."""

from enum import StrEnum

from app.application.llm.catalog import InMemoryProviderRegistry, StaticModelCatalog, assert_default_registered
from app.application.llm.routing import RoutingModelGateway
from app.application.ports.output.llm.llm_provider import LLMProvider
from app.application.ports.output.llm.model_gateway import ModelCapability, ModelDescriptor, ModelGateway, ModelRef
from app.infrastructure.config.settings import Settings, settings
from app.infrastructure.llm.anthropic_gateway import AnthropicModelGateway
from app.infrastructure.llm.anthropic_provider import AnthropicProvider
from app.infrastructure.llm.openai_gateway import OpenAIModelGateway
from app.infrastructure.llm.openai_provider import OpenAIProvider

_CHAT_CAPABILITIES = (
    ModelCapability.CHAT,
    ModelCapability.STREAMING,
    ModelCapability.TOOL_CALLING,
)


class LLMProviderType(StrEnum):
    """Built-in adapter ids. Additional ids may be registered at composition time."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai-compatible"


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _has_usable_secret(value: str | None) -> bool:
    if value is None:
        return False
    trimmed = value.strip()
    if not trimmed:
        return False
    placeholders = {
        "your-openai-api-key-here",
        "your-anthropic-api-key-here",
        "changeme",
        "change-me",
    }
    return trimmed.lower() not in placeholders


def resolved_default(cfg: Settings) -> ModelRef:
    provider = cfg.default_model_provider.strip().lower() or LLMProviderType.OPENAI.value
    name = (cfg.default_model_name or "").strip()
    if not name:
        if provider == LLMProviderType.OPENAI.value:
            name = cfg.openai_model
        elif provider == LLMProviderType.ANTHROPIC.value:
            name = cfg.anthropic_model
        elif provider == cfg.openai_compatible_provider_id.strip().lower():
            models = _csv(cfg.openai_compatible_models)
            name = models[0] if models else ""
        else:
            name = cfg.openai_model
    return ModelRef(provider=provider, model=name)


def enabled_provider_ids(cfg: Settings) -> list[str]:
    explicit = [item.lower() for item in _csv(cfg.enabled_providers)]
    if explicit:
        return explicit
    ids = [LLMProviderType.OPENAI.value, LLMProviderType.ANTHROPIC.value]
    if cfg.openai_compatible_enabled:
        ids.append(cfg.openai_compatible_provider_id.strip().lower() or LLMProviderType.OPENAI_COMPATIBLE.value)
    return ids


def build_model_catalog(cfg: Settings | None = None) -> StaticModelCatalog:
    cfg = cfg or settings
    enabled = set(enabled_provider_ids(cfg))
    descriptors: list[ModelDescriptor] = []

    if LLMProviderType.OPENAI.value in enabled:
        models = _csv(cfg.openai_models) or [cfg.openai_model]
        available = _has_usable_secret(cfg.openai_api_key)
        for model in models:
            descriptors.append(
                ModelDescriptor(
                    provider=LLMProviderType.OPENAI.value,
                    model=model,
                    display_name=f"OpenAI {model}",
                    capabilities=_CHAT_CAPABILITIES,
                    available=available,
                )
            )

    if LLMProviderType.ANTHROPIC.value in enabled:
        models = _csv(cfg.anthropic_models) or [cfg.anthropic_model]
        available = _has_usable_secret(cfg.anthropic_api_key)
        for model in models:
            descriptors.append(
                ModelDescriptor(
                    provider=LLMProviderType.ANTHROPIC.value,
                    model=model,
                    display_name=f"Anthropic {model}",
                    capabilities=_CHAT_CAPABILITIES,
                    available=available,
                )
            )

    compatible_id = cfg.openai_compatible_provider_id.strip().lower() or LLMProviderType.OPENAI_COMPATIBLE.value
    if compatible_id in enabled and cfg.openai_compatible_enabled:
        base = (cfg.openai_compatible_base_url or "").strip()
        models = _csv(cfg.openai_compatible_models)
        available = bool(base) and _has_usable_secret(cfg.openai_compatible_api_key)
        for model in models:
            descriptors.append(
                ModelDescriptor(
                    provider=compatible_id,
                    model=model,
                    display_name=f"{compatible_id} {model}",
                    capabilities=_CHAT_CAPABILITIES,
                    available=available,
                )
            )

    default = resolved_default(cfg)
    catalog = StaticModelCatalog(descriptors, default)
    assert_default_registered(catalog)
    return catalog


def build_provider_registry(cfg: Settings | None = None) -> InMemoryProviderRegistry:
    cfg = cfg or settings
    registry = InMemoryProviderRegistry()
    enabled = set(enabled_provider_ids(cfg))

    if LLMProviderType.OPENAI.value in enabled and _has_usable_secret(cfg.openai_api_key):
        registry.register(
            LLMProviderType.OPENAI.value,
            OpenAIModelGateway(api_key=cfg.openai_api_key, model=cfg.openai_model, provider_id="openai"),
        )

    if LLMProviderType.ANTHROPIC.value in enabled and _has_usable_secret(cfg.anthropic_api_key):
        registry.register(
            LLMProviderType.ANTHROPIC.value,
            AnthropicModelGateway(api_key=cfg.anthropic_api_key, model=cfg.anthropic_model),
        )

    compatible_id = cfg.openai_compatible_provider_id.strip().lower() or LLMProviderType.OPENAI_COMPATIBLE.value
    base = (cfg.openai_compatible_base_url or "").strip()
    if (
        compatible_id in enabled
        and cfg.openai_compatible_enabled
        and base
        and _has_usable_secret(cfg.openai_compatible_api_key)
    ):
        models = _csv(cfg.openai_compatible_models)
        registry.register(
            compatible_id,
            OpenAIModelGateway(
                api_key=cfg.openai_compatible_api_key,
                model=models[0] if models else "default",
                base_url=base,
                provider_id=compatible_id,
            ),
        )
    return registry


def create_routing_gateway(cfg: Settings | None = None) -> RoutingModelGateway:
    cfg = cfg or settings
    return RoutingModelGateway(build_model_catalog(cfg), build_provider_registry(cfg))


def validate_default_model_availability(cfg: Settings | None = None) -> None:
    """Production: default must be registered, enabled, and credentialed."""
    cfg = cfg or settings
    catalog = build_model_catalog(cfg)
    default = catalog.default_ref()
    match = next(
        (item for item in catalog.list_models() if item.provider == default.provider and item.model == default.model),
        None,
    )
    if match is None:
        raise RuntimeError(f"Default model {default.provider}/{default.model} is not registered")
    if cfg.is_production and not match.available:
        raise RuntimeError(
            f"Default model {default.provider}/{default.model} is not available (provider credentials missing)"
        )


def create_llm_provider(
    provider_type: LLMProviderType = LLMProviderType.OPENAI,
    api_key: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    if provider_type == LLMProviderType.OPENAI:
        return OpenAIProvider(api_key=api_key, model=model)
    if provider_type == LLMProviderType.ANTHROPIC:
        return AnthropicProvider(api_key=api_key, model=model)
    raise ValueError(f"Unsupported embedding/chat provider type: {provider_type}")


def create_embedding_provider(
    api_key: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    return OpenAIProvider(api_key=api_key, embedding_model=model)


def create_model_gateway(
    provider_type: LLMProviderType | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> ModelGateway:
    """Create a single adapter, or the routing gateway when no provider is specified."""
    if provider_type is None:
        return create_routing_gateway()
    if provider_type == LLMProviderType.OPENAI:
        return OpenAIModelGateway(api_key=api_key, model=model)
    if provider_type == LLMProviderType.ANTHROPIC:
        return AnthropicModelGateway(api_key=api_key, model=model)
    if provider_type == LLMProviderType.OPENAI_COMPATIBLE:
        raise ValueError("OpenAI-compatible adapters must be created from server configuration, not request input")
    raise ValueError(f"Unsupported ModelGateway provider type: {provider_type}")
