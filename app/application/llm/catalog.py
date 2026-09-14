"""In-memory catalog and adapter registry used by the routing gateway."""

from app.application.agent.errors import ModelSelectionError
from app.application.ports.output.llm.model_catalog import ModelCatalog
from app.application.ports.output.llm.model_gateway import ModelDescriptor, ModelGateway, ModelRef


class StaticModelCatalog:
    """Configured model catalog. Endpoints and API keys are never stored here."""

    def __init__(self, descriptors: list[ModelDescriptor], default: ModelRef) -> None:
        self._descriptors = tuple(descriptors)
        self._default = default
        self._by_key = {(item.provider.lower(), item.model): item for item in self._descriptors}

    def default_ref(self) -> ModelRef:
        return self._default

    def list_models(self) -> list[ModelDescriptor]:
        return list(self._descriptors)

    def resolve(self, provider: str | None, model: str | None) -> ModelDescriptor:
        provider_id = (provider or "").strip().lower() or None
        model_id = (model or "").strip() or None
        if provider_id is None and model_id is None:
            return self._require(self._default.provider, self._default.model)
        if provider_id is None and model_id is not None:
            matches = [item for item in self._descriptors if item.model == model_id]
            if len(matches) == 1:
                return self._ensure_selectable(matches[0])
            raise ModelSelectionError(
                "Model is ambiguous without a provider",
                details={"model": model_id},
            )
        if provider_id is not None and model_id is None:
            raise ModelSelectionError(
                "Model name is required when a provider is specified",
                details={"provider": provider_id},
            )
        assert provider_id is not None and model_id is not None
        return self._ensure_selectable(self._require(provider_id, model_id))

    def _require(self, provider: str, model: str) -> ModelDescriptor:
        found = self._by_key.get((provider.lower(), model))
        if found is None:
            raise ModelSelectionError(
                "Requested model is not registered",
                details={"provider": provider, "model": model},
            )
        return found

    def _ensure_selectable(self, descriptor: ModelDescriptor) -> ModelDescriptor:
        if not descriptor.available:
            raise ModelSelectionError(
                "Requested model is not available",
                details={"provider": descriptor.provider, "model": descriptor.model},
            )
        return descriptor


class InMemoryProviderRegistry:
    """Small adapter map. No provider-specific branching."""

    def __init__(self) -> None:
        self._adapters: dict[str, ModelGateway] = {}

    def register(self, provider_id: str, adapter: ModelGateway) -> None:
        self._adapters[provider_id.strip().lower()] = adapter

    def get(self, provider_id: str) -> ModelGateway:
        adapter = self._adapters.get(provider_id.strip().lower())
        if adapter is None:
            raise ModelSelectionError(
                "Provider adapter is not registered",
                details={"provider": provider_id},
            )
        return adapter

    def registered_ids(self) -> list[str]:
        return list(self._adapters.keys())


def assert_default_registered(catalog: ModelCatalog) -> None:
    """Fail closed when the configured default is missing from the catalog."""
    default = catalog.default_ref()
    listed = {(item.provider.lower(), item.model) for item in catalog.list_models()}
    if (default.provider.lower(), default.model) not in listed:
        raise RuntimeError(f"Default model {default.provider}/{default.model} is not registered in the model catalog")
